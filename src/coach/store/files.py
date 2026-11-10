"""The athlete data store. Today a file backend under athlete/data/ (git is the database); every read and write
goes through the collections in coach/store/collections.py so the backend can become a real database later.

Callers use the typed methods (get/put/list/delete/report + entity helpers), never file paths."""

import datetime as dt
import json
from pathlib import Path
from typing import Any, TypeVar

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
from coach.models.journal import Availability, HealthEvent, Note
from coach.models.records import ThresholdZones
from coach.store.collections import COLLECTIONS, Collection

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


class Store:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else paths.state_dir()

    # ---------- file primitives (backend only) ----------
    def _path(self, rel: str) -> Path:
        return self.root / rel

    def _read(self, rel: str):
        p = self._path(rel)
        if not p.exists():
            return None
        with open(p) as f:
            return json.load(f)

    def _write(self, rel: str, data) -> Path:
        p = self._path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(dumps(data))
        return p

    # ---------- collections ----------
    @staticmethod
    def collection(name: str) -> Collection:
        if name not in COLLECTIONS:
            raise KeyError(f"unknown collection '{name}'")
        return COLLECTIONS[name]

    def get(self, name: str, key: str | None = None) -> Any:
        c = self.collection(name)
        data = self._read(c.file(key))
        if data is None or c.model is None:
            return data
        return c.model.model_validate(data)

    def put(self, name: str, obj: Any, key: str | None = None) -> Any:
        c = self.collection(name)
        if c.model is not None and not isinstance(obj, BaseModel):
            obj = c.model.model_validate(obj)
        if c.kind == "doc" and key is None:
            key = self.key_of(name, obj)
        self._write(c.file(key), obj)
        if name == "notes":
            self._render_notes()
        return obj

    def delete(self, name: str, key: str | None = None) -> bool:
        p = self._path(self.collection(name).file(key))
        if p.exists():
            p.unlink()
            return True
        return False

    def exists(self, name: str, key: str | None = None) -> bool:
        return self._path(self.collection(name).file(key)).exists()

    def keys(self, name: str) -> list[str]:
        c = self.collection(name)
        if c.kind != "doc":
            raise ValueError(f"{name} is not a document collection")
        if "{a}" in c.path:
            head, tail = c.path.split("{a}")
            mid, end = tail.split("{b}")
            base = self._path(head)
            pattern = f"*{mid}*{end}"
            if not base.exists():
                return []
            out = []
            for p in sorted(base.glob(pattern)):
                rel = p.relative_to(base).as_posix()
                a_, b_ = rel[: rel.index(mid)], rel[rel.index(mid) + len(mid) : -len(end)]
                out.append(f"{a_}:{b_}")
            return out
        head, tail = c.path.split("{key}")
        base = self._path(head)
        if not base.exists():
            return []
        if "/" in tail:  # one directory per key (e.g. weeks/{key}/plan.json)
            return sorted(p.parent.name for p in base.glob(f"*{tail}"))
        return sorted(p.name[: -len(tail)] for p in base.glob(f"*{tail}"))

    def query(self, name: str, start: dt.date | None = None, end: dt.date | None = None) -> list[Any]:
        out = [self.get(name, k) for k in self.keys(name)]
        out = [o for o in out if o is not None]
        if start or end:

            def day(o):
                for f in ("date", "start", "created"):
                    v = getattr(o, f, None)
                    if isinstance(v, dt.date):
                        return v
                return None

            out = [
                o
                for o in out
                if (d := day(o)) is None or ((start is None or d >= start) and (end is None or d <= end))
            ]
        return out

    @staticmethod
    def key_of(name: str, obj: Any) -> str:
        if isinstance(obj, BaseModel):
            for f in ("id", "week_id", "block_id", "event_id"):
                v = getattr(obj, f, None)
                if v:
                    if name == "test_sets":
                        return "{block_id}:{phase}".format(**vars(obj))
                    return str(v)
            d = getattr(obj, "date", None)
            if d is not None:
                return d.isoformat()
        raise ValueError(f"can't derive a key for {name}")

    def new_id(self, name: str, day: dt.date, kind: str) -> str:
        existing = [k for k in self.keys(name) if k.startswith(f"{day.isoformat()}-{kind}-")]
        return f"{day.isoformat()}-{kind}-{len(existing) + 1}"

    # ---------- reports (markdown) ----------
    def report(self, name: str, key: str | None = None) -> str:
        c = self.collection(name)
        p = self._path(c.file(key))
        return p.read_text() if p.exists() else ""

    def save_report(self, name: str, text: str, key: str | None = None) -> None:
        c = self.collection(name)
        if c.kind != "report":
            raise ValueError(f"{name} is not a report")
        p = self._path(c.file(key))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def append_report(self, name: str, text: str, key: str | None = None) -> None:
        self.save_report(name, self.report(name, key) + text, key)

    # ---------- references ("collection/key", used by proposals) ----------
    @staticmethod
    def ref(name: str, key: str | None = None) -> str:
        return f"{name}/{key}" if key else name

    def get_ref(self, ref: str) -> Any:
        name, _, key = ref.partition("/")
        return self.get(name, key or None)

    def put_ref(self, ref: str, obj: Any) -> Any:
        name, _, key = ref.partition("/")
        return self.put(name, obj, key or None)

    # ---------- metrics (JSON lines per month) ----------
    def _month_file(self, day: dt.date) -> Path:
        return self._path(f"metrics/{day:%Y-%m}.jsonl")

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
        out: list[dict] = []
        mdir = self._path("metrics")
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
        return [Gear.model_validate(g) for g in (self.get("gear") or [])]

    def checkins(self, start: dt.date | None = None, end: dt.date | None = None) -> list[Checkin]:
        """Merged per date: Intervals fields first, then Hevy-note tags, then chat check-ins."""
        raw = [Checkin.model_validate(r["data"]) for r in self.metric_records("checkin", start, end)]
        raw.extend(self.query("checkins", start, end))
        by_date: dict[dt.date, list[Checkin]] = {}
        for c in raw:
            by_date.setdefault(c.date, []).append(c)
        merged = []
        for _day, cs in sorted(by_date.items()):
            cs.sort(key=lambda c: CHECKIN_PRIORITY.get(c.source, 9))
            base = cs[0].model_copy(deep=True)
            for other in cs[1:]:
                for f, v in other.model_dump().items():
                    if f in {"date", "source"}:
                        continue
                    if f == "joints":
                        base.joints = {**v, **base.joints}
                    elif f == "session_pain":
                        base.session_pain = {**v, **base.session_pain}
                    elif f == "stiffness_up":
                        base.stiffness_up = sorted(set(base.stiffness_up) | set(v))
                    elif getattr(base, f) in (None, "", [], {}) and v not in (None, "", [], {}):
                        setattr(base, f, v)
            merged.append(base)
        return merged

    # ---------- entity helpers ----------
    def macrocycle(self) -> Macrocycle | None:
        return self.get("macrocycle")

    def outline(self, block_id: str) -> BlockOutline | None:
        return self.get("block_outlines", block_id)

    def goal(self, block_id: str) -> BlockGoal | None:
        return self.get("block_goals", block_id)

    def tests(self, block_id: str, phase: str) -> TestSet | None:
        return self.get("test_sets", f"{block_id}:{phase}")

    def week_plan(self, week_id: str) -> WeekPlan | None:
        return self.get("week_plans", week_id)

    def day_record(self, day: dt.date) -> DayRecord | None:
        return self.get("day_records", day.isoformat())

    def movement_readiness(self) -> MovementReadiness | None:
        return self.get("movement_readiness")

    def proposals(self, status: str | None = None) -> list[Proposal]:
        return [p for p in self.query("proposals") if status is None or p.status == status]

    def proposal(self, pid: str) -> Proposal | None:
        return self.get("proposals", pid)

    def save_proposal(self, p: Proposal) -> None:
        self.put("proposals", p)

    def health_events(self, active_on: dt.date | None = None) -> list[HealthEvent]:
        events = self.query("health_events")
        return [e for e in events if active_on is None or e.active_on(active_on)]

    def availability(self, start: dt.date | None = None, end: dt.date | None = None) -> list[Availability]:
        out = self.query("availability")
        return [a for a in out if (start is None or a.end >= start) and (end is None or a.start <= end)]

    def zones(self) -> ThresholdZones | None:
        return self.get("zones")

    def notes(self) -> str:
        return self.report("notes_view")

    def add_note(self, day: dt.date, text: str, category: str = "other", source: str = "coach") -> Note:
        return self.put(
            "notes",
            Note(id=self.new_id("notes", day, "note"), date=day, category=category, text=text, source=source),
        )

    def _render_notes(self) -> None:
        notes = sorted(self.query("notes"), key=lambda n: (n.date, n.id))
        lines = [
            "# Coach notes (durable facts)",
            "",
            "Rendered from athlete/data/notes/; add with `coach record add notes` or the skills.",
            "",
        ]
        lines += [f"- {n.date} [{n.category}] {n.text}" for n in notes]
        self.save_report("notes_view", "\n".join(lines) + "\n")
