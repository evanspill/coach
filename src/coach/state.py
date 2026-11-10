"""Git is the database: thin typed access to everything under state/."""

import datetime as dt
import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from coach import paths
from coach.models import (
    BlockGoal,
    BlockOutline,
    Checkin,
    DailyMetrics,
    DayRecord,
    Gear,
    Macrocycle,
    MovementReadiness,
    Proposal,
    SessionRecord,
    TestSet,
    WeekPlan,
)

M = TypeVar("M", bound=BaseModel)
CHECKIN_PRIORITY = {"intervals": 0, "hevy_notes": 1, "chat": 2, "simulated": 3}


def _default(o):
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(type(o))


def dumps(data) -> str:
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    return json.dumps(data, indent=2, sort_keys=False, default=_default) + "\n"


class State:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else paths.state_dir()

    # ---------- generic ----------
    def path(self, rel: str) -> Path:
        return self.root / rel

    def exists(self, rel: str) -> bool:
        return self.path(rel).exists()

    def read_json(self, rel: str):
        p = self.path(rel)
        if not p.exists():
            return None
        with open(p) as f:
            return json.load(f)

    def write_json(self, rel: str, data) -> Path:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(dumps(data))
        return p

    def read_model(self, rel: str, model: type[M]) -> M | None:
        data = self.read_json(rel)
        return model.model_validate(data) if data is not None else None

    def write_text(self, rel: str, text: str) -> Path:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def read_text(self, rel: str) -> str:
        p = self.path(rel)
        return p.read_text() if p.exists() else ""

    def append_text(self, rel: str, text: str) -> None:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(text)

    # ---------- metrics (JSON lines per month) ----------
    def _month_file(self, day: dt.date) -> Path:
        return self.path(f"metrics/{day:%Y-%m}.jsonl")

    def _read_month(self, p: Path) -> dict[tuple[str, str], dict]:
        out: dict[tuple[str, str], dict] = {}
        if p.exists():
            for line in p.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    out[(rec["kind"], rec["key"])] = rec
        return out

    def _write_month(self, p: Path, recs: dict[tuple[str, str], dict]) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(recs[k], sort_keys=True, default=_default) for k in sorted(recs)]
        p.write_text("\n".join(lines) + ("\n" if lines else ""))

    def upsert_metrics(
        self,
        items: list[tuple[str, str, dt.date, dict]],
        replace_kinds_in: dict[str, tuple[dt.date, dt.date]] | None = None,
    ) -> int:
        """items: (kind, key, date, data). `replace_kinds_in` deletes existing records of a kind in a date range first
        (used for sessions, which are re-merged every sync). Returns number of changed records."""
        by_file: dict[Path, list[tuple[str, str, dt.date, dict]]] = {}
        for it in items:
            by_file.setdefault(self._month_file(it[2]), []).append(it)
        if replace_kinds_in:
            for _kind, (start, end) in replace_kinds_in.items():
                d = start.replace(day=1)
                while d <= end:
                    by_file.setdefault(self._month_file(d), [])
                    d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        changed = 0
        for p, its in by_file.items():
            recs = self._read_month(p)
            before = json.dumps(
                sorted(recs.values(), key=lambda r: (r["kind"], r["key"])), sort_keys=True, default=_default
            )
            if replace_kinds_in:
                for kind, (start, end) in replace_kinds_in.items():
                    for k in [
                        k
                        for k, r in recs.items()
                        if r["kind"] == kind and start.isoformat() <= r["date"] <= end.isoformat()
                    ]:
                        del recs[k]
            for kind, key, day, data in its:
                rec = {
                    "kind": kind,
                    "key": key,
                    "date": day.isoformat(),
                    "data": json.loads(json.dumps(data, default=_default)),
                }
                old = recs.get((kind, key))
                if kind == "daily" and old is not None:
                    merged = dict(old["data"])
                    for f, v in rec["data"].items():
                        if f == "sources":
                            merged["sources"] = sorted(set(merged.get("sources", [])) | set(v))
                        elif v is not None:
                            merged[f] = v
                    rec["data"] = merged
                recs[(kind, key)] = rec
            after = json.dumps(
                sorted(recs.values(), key=lambda r: (r["kind"], r["key"])), sort_keys=True, default=_default
            )
            if before != after:
                changed += 1
                self._write_month(p, recs)
        return changed

    def metric_records(
        self, kind: str, start: dt.date | None = None, end: dt.date | None = None
    ) -> list[dict]:
        out = []
        mdir = self.path("metrics")
        if not mdir.exists():
            return out
        for p in sorted(mdir.glob("*.jsonl")):
            for rec in self._read_month(p).values():
                if rec["kind"] != kind:
                    continue
                if start and rec["date"] < start.isoformat():
                    continue
                if end and rec["date"] > end.isoformat():
                    continue
                out.append(rec)
        return sorted(out, key=lambda r: (r["date"], r["key"]))

    def daily_metrics(self, start: dt.date | None = None, end: dt.date | None = None) -> list[DailyMetrics]:
        return [DailyMetrics.model_validate(r["data"]) for r in self.metric_records("daily", start, end)]

    def sessions(self, start: dt.date | None = None, end: dt.date | None = None) -> list[SessionRecord]:
        return [SessionRecord.model_validate(r["data"]) for r in self.metric_records("session", start, end)]

    def gear(self) -> list[Gear]:
        return [Gear.model_validate(r["data"]) for r in self.metric_records("gear")]

    def checkins(self, start: dt.date | None = None, end: dt.date | None = None) -> list[Checkin]:
        """Merged per date: Intervals fields first, then Hevy-note tags, then chat check-ins."""
        raw = [Checkin.model_validate(r["data"]) for r in self.metric_records("checkin", start, end)]
        cdir = self.path("checkins")
        if cdir.exists():
            for p in sorted(cdir.glob("*.json")):
                c = Checkin.model_validate(json.loads(p.read_text()))
                if (start is None or c.date >= start) and (end is None or c.date <= end):
                    raw.append(c)
        by_date: dict[dt.date, list[Checkin]] = {}
        for c in raw:
            by_date.setdefault(c.date, []).append(c)
        merged = []
        for day, cs in sorted(by_date.items()):
            cs.sort(key=lambda c: CHECKIN_PRIORITY.get(c.source, 9))
            base = cs[0].model_copy(deep=True)
            for other in cs[1:]:
                for f, v in other.model_dump().items():
                    if f in {"date", "source"}:
                        continue
                    if f == "session_pain":
                        base.session_pain = {**v, **base.session_pain}
                    elif f == "stiffness_up":
                        base.stiffness_up = sorted(set(base.stiffness_up) | set(v))
                    elif getattr(base, f) in (None, "", [], {}) and v not in (None, "", [], {}):
                        setattr(base, f, v)
            merged.append(base)
        return merged

    # ---------- planning state ----------
    def macrocycle(self) -> Macrocycle | None:
        return self.read_model("macrocycle.json", Macrocycle)

    def outline(self, block_id: str) -> BlockOutline | None:
        return self.read_model(f"blocks/{block_id}/outline.json", BlockOutline)

    def goal(self, block_id: str) -> BlockGoal | None:
        return self.read_model(f"blocks/{block_id}/goal.json", BlockGoal)

    def tests(self, block_id: str, phase: str) -> TestSet | None:
        return self.read_model(f"blocks/{block_id}/tests_{phase}.json", TestSet)

    def week_plan(self, week_id: str) -> WeekPlan | None:
        return self.read_model(f"weeks/{week_id}/plan.json", WeekPlan)

    def day_record(self, day: dt.date) -> DayRecord | None:
        return self.read_model(f"days/{day.isoformat()}.json", DayRecord)

    def movement_readiness(self) -> MovementReadiness | None:
        return self.read_model("movement_readiness.json", MovementReadiness)

    def proposals(self, status: str | None = None) -> list[Proposal]:
        pdir = self.path("proposals")
        if not pdir.exists():
            return []
        out = [Proposal.model_validate(json.loads(p.read_text())) for p in sorted(pdir.glob("*.json"))]
        return [p for p in out if status is None or p.status == status]

    def proposal(self, pid: str) -> Proposal | None:
        return self.read_model(f"proposals/{pid}.json", Proposal)

    def save_proposal(self, p: Proposal) -> None:
        self.write_json(f"proposals/{p.id}.json", p)

    def health(self) -> dict:
        return self.read_json("health.json") or {"red_flags": [], "illness": None, "travel": []}

    def zones(self) -> dict | None:
        return self.read_json("zones.json")

    def notes(self) -> str:
        return self.read_text("notes.md")
