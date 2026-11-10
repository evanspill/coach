"""`coach simulate`: replay the fixtures through baseline -> Block 1 -> transition -> Block 2 start."""

import contextlib
import datetime as dt
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from coach import paths
from coach.config import load_config
from coach.daily import run_daily
from coach.fallback import log as log_skill
from coach.fallback import technique
from coach.integrations.mock import MockWorld, mock_sources
from coach.sim.athlete import SimAthlete
from coach.state import State


@dataclass
class SimResult:
    home: Path
    days: list[dict] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    scenarios: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s["passed"] for s in self.scenarios)


@contextlib.contextmanager
def sandbox(out_dir: Path | None = None, config: str = "demo"):
    """Temp COACH_HOME with a copy of the demo config (or the active config) and an empty state/.
    The athlete's own state is never touched."""
    home = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="coach-sim-"))
    if (home / "config").exists():
        shutil.rmtree(home / "config")
    if (home / "state").exists():
        shutil.rmtree(home / "state")
    shutil.copytree(paths.demo_config_dir() if config == "demo" else paths.config_dir(), home / "config")
    (home / "state").mkdir(parents=True, exist_ok=True)
    saved = {k: os.environ.get(k) for k in ("COACH_HOME", "COACH_STATE_DIR", "COACH_TODAY", "COACH_MOCK")}
    os.environ.update({"COACH_HOME": str(home), "COACH_STATE_DIR": str(home / "state"), "COACH_MOCK": "1"})
    try:
        yield home
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def simulate(
    days: int = 120,
    start: dt.date = dt.date(2026, 11, 16),
    out_dir: Path | None = None,
    echo=print,
    scenarios: bool = True,
    config: str = "demo",
) -> SimResult:
    with sandbox(out_dir, config) as home:
        res = SimResult(home=home)
        world = MockWorld.load()
        late = {dt.date.fromisoformat(d) for d in world.script.get("late_recovery_dates", [])}
        world.hide_recovery_for = set(late)
        sources = mock_sources(world)
        state = State(home / "state")
        athlete = SimAthlete(world, load_config(home / "config"))
        chat = world.script.get("chat", {})
        for i in range(days):
            day = start + dt.timedelta(days=i)
            os.environ["COACH_TODAY"] = day.isoformat()
            cfg = load_config(home / "config")
            out = run_daily(sources, state, day, "main", auto_approve=True, cfg=cfg)
            rec = out.record
            catchup_note = ""
            if rec and rec.status == "waiting_for_recovery":
                first = out.notification
                world.hide_recovery_for.discard(day)
                out2 = run_daily(sources, state, day, "catchup", auto_approve=True, cfg=cfg)
                rec = out2.record or rec
                catchup_note = f"[08:25 run] {first.splitlines()[0]} ... waiting_for_recovery -> [09:05 catch-up] completed"
                out.log += out2.log
                out = out2 if out2.record else out
            echo(f"\n=== {day:%a %Y-%m-%d} ===")
            if catchup_note:
                echo(catchup_note)
            echo(out.notification)
            for line in out.log:
                echo(f"  · {line}")
                res.events.append(f"{day} {line}")
            if day.isoformat() in chat:
                msg = chat[day.isoformat()]
                from coach.context import build

                ctx = build(state, cfg, day)
                r = log_skill.handle(ctx, msg, day)
                for skill, level in r.get("skill_updates", []):
                    echo(
                        "  · technique: "
                        + technique.set_skill_level(ctx, skill, level, "reported in chat", day)
                    )
                echo(
                    f'  > athlete: "{msg}"\n  < coach (log): {r["reply"]}'
                    + (f" | {r['follow_up']}" if r.get("follow_up") else "")
                )
            if (
                day.weekday() == 6
            ):  # the simulated athlete films pending lifts on Sunday; the coach reviews them
                from coach.engine import movement as mv

                mr = state.movement_readiness()
                if mr is not None:
                    for fam, fs in mr.families.items():
                        if fs.pending_form_check is not None:
                            rung = mv.clear_form_check(mr, fam, day, "coach (video review)")
                            echo(f"  · technique: [sim] form video reviewed: {fam} rung {rung} cleared")
                    state.write_json("movement_readiness.json", mr)
            for line in athlete.do_day(day, rec):
                echo(f"  · {line}")
            res.days.append(
                {
                    "date": day.isoformat(),
                    "status": rec.status if rec else None,
                    "readiness": rec.readiness.state if rec and rec.readiness else None,
                    "session": rec.session.title if rec and rec.session else None,
                    "changes": len(rec.changes) if rec else 0,
                }
            )
        if scenarios:
            from coach.sim.scenarios import run_all

            res.scenarios = run_all(echo=echo)
        write_report(res, state)
        return res


def write_report(res: SimResult, state: State) -> None:
    from collections import Counter

    c = Counter(d["readiness"] for d in res.days)
    lines = [
        "# Simulation report",
        "",
        f"Days: {len(res.days)} ({res.days[0]['date']} -> {res.days[-1]['date']})" if res.days else "",
        f"Readiness: {dict(c)}",
        f"Days with changes: {sum(1 for d in res.days if d['changes'])}",
        "",
        "## Key events",
        *[
            f"- {e}"
            for e in res.events
            if any(
                k in e for k in ("replan", "assess", "plan-block", "review: block", "rehab", "learn", "zones")
            )
        ],
    ]
    if res.scenarios:
        lines += [
            "",
            "## Per-skill scenarios",
            *[
                f"- [{'PASS' if s['passed'] else 'FAIL'}] {s['skill']}: {s['name']} - {s['detail']}"
                for s in res.scenarios
            ],
        ]
    state.write_text("simulation_report.md", "\n".join(lines) + "\n")
