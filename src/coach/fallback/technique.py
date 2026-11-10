"""technique fallback: skill levels from logged practice / reported milestones, running-form cues from dynamics."""

import datetime as dt
import re
import statistics

import yaml

from coach.context import Context


def skill_from_message(text: str, cfg=None) -> list[tuple[str, int]]:
    """Milestone patterns per skill come from config/skills.yaml."""
    if cfg is None:
        from coach.config import load_config

        cfg = load_config()
    out = []
    low = text.lower()
    for skill, sk in cfg.skills.skills.items():
        if sk.milestone is None:
            continue
        pat, levels = sk.milestone.pattern, sk.milestone.levels
        m = re.search(pat, low)
        if not m:
            continue
        n = int(m.group(1)) if m.groups() else 0
        lvl = max((lv for thr, lv in levels.items() if n >= thr), default=None)
        if lvl is not None:
            out.append((skill, lvl))
    return out


def set_skill_level(ctx: Context, skill: str, level: int, why: str, day: dt.date) -> str:
    """Skill levels move one step at a time (like rungs); the gate rung must allow the skill."""
    path = ctx.cfg.root / "skills.yaml"
    data = yaml.safe_load(path.read_text())
    sk = data["skills"][skill]
    cur = sk["current_level"]
    new = min(level, cur + 1)
    gate = sk.get("gate")
    if gate and ctx.movement.rung(gate["family"]) < gate["rung"] and new >= sk["competent_level"]:
        return f"{skill}: held at level {cur} ({gate['family']} rung {ctx.movement.rung(gate['family'])} < {gate['rung']})"
    if new == cur:
        return f"{skill}: already at level {cur}"
    sk["current_level"] = new
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    competent = new >= sk["competent_level"]
    ctx.state.append_text(
        "notes.md",
        f"- {day}: {sk['name']} -> level {new} ({sk['levels'][new]}){' - COMPETENT: allowed in metcons' if competent else ''}. {why}\n",
    )
    return f"{skill}: level {cur} -> {new}" + (" (competent: now allowed in metcons)" if competent else "")


def running_form(ctx: Context, day: dt.date) -> list[str]:
    runs = [s for s in ctx.state.sessions(day - dt.timedelta(days=28), day) if s.sport == "run"]
    cues = []
    cad = [s.cadence_spm for s in runs if s.cadence_spm]
    gct = [s.gct_ms for s in runs if s.gct_ms]
    bal = [s.gct_balance_left_pct for s in runs if s.gct_balance_left_pct]
    vo = [s.vertical_osc_cm for s in runs if s.vertical_osc_cm]
    lo, _hi = ctx.cfg.profile.running.cadence_target_spm
    if cad and statistics.fmean(cad) < lo:
        cues.append(
            f"Cadence {statistics.fmean(cad):.0f} spm: shorten the stride, aim +5% (drill: 3 x 1 min quick feet in easy runs)."
        )
    if bal and abs(statistics.fmean(bal) - 50) > 1.5:
        cues.append(
            f"Ground-contact balance {statistics.fmean(bal):.1f}% L: watch for a favoured side (single-leg strength, hip mobility)."
        )
    if vo and statistics.fmean(vo) > 10:
        cues.append(
            f"Vertical oscillation {statistics.fmean(vo):.1f} cm: run 'tall and quiet', push back rather than up."
        )
    if gct and statistics.fmean(gct) > 280:
        cues.append(
            f"Ground contact {statistics.fmean(gct):.0f} ms: strides 2x/week and pogo hops in the warm-up."
        )
    return cues or ["Running form trends look fine: keep cadence 170-180."]


def form_check_due(ctx: Context, day: dt.date) -> bool:
    notes = ctx.state.notes()
    dates = [dt.date.fromisoformat(d) for d in re.findall(r"form check requested (\d{4}-\d{2}-\d{2})", notes)]
    return not dates or (day - max(dates)).days >= 21
