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
from coach.models.records import Change, ThresholdZones
from coach.store.collections import COLLECTIONS, Collection

M = TypeVar("M", bound=BaseModel)
CHECKIN_PRIORITY = {"intervals": 0, "hevy_notes": 1, "chat": 2, "simulated": 3}
# Whoop data is never committed (docs/DECISIONS.md 73): sync refetches it into this git-ignored cache, readers
# merge it in, and it disappears with the container.
CACHE_DIR = ".cache/whoop"


def scrub_day_record(rec: DayRecord) -> DayRecord:
    """The stored copy keeps the readiness decision (state, numberless reasons, flags), not Whoop's numbers."""
    if rec.readiness is None:
        return rec
    out = rec.model_copy(deep=True)
    assert out.readiness is not None
    out.readiness.recovery_score = None
    out.readiness.rhr_delta = None
    out.readiness.hrv = type(out.readiness.hrv)()
    return out


def _default(o):
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if isinstance(o, set):
        return sorted(o)
    # a model nested in a command's result (e.g. the zones `coach test score` returns)
    if isinstance(o, BaseModel):
        return o.model_dump(mode="json")
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
        if c.kind == "report":
            return self.report(name, key) or None
        data = self._read(c.file(key))
        if data is None or c.model is None:
            return data
        if name == "week_plans":
            data = self._assemble_week(data)
        return c.model.model_validate(data)

    def put(self, name: str, obj: Any, key: str | None = None) -> Any:
        c = self.collection(name)
        if c.kind == "report":  # markdown, not JSON (e.g. a proposal's payload record "event_plans/<race>")
            self.save_report(name, str(obj), key)
            return obj
        if c.model is not None and not isinstance(obj, BaseModel):
            obj = c.model.model_validate(obj)
        if c.kind == "doc" and key is None:
            key = self.key_of(name, obj)
        if name == "week_plans":
            self._write_week_days(obj)
            self._write(c.file(key), obj.model_dump(mode="json", exclude={"sessions"}))
            return obj
        if name == "day_records":
            obj = self._keep_planned(obj)
        self._write(c.file(key), scrub_day_record(obj) if name == "day_records" else obj)
        if name == "notes":
            self._render_notes()
        return obj

    def delete(self, name: str, key: str | None = None) -> bool:
        p = self._path(self.collection(name).file(key))
        if not p.exists():
            return False
        p.unlink()
        if name == "notes":
            self._render_notes()
        return True

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

    # ---------- plans: the day record is the single home of a day's session (DECISIONS 102) ----------
    def _assemble_week(self, data: dict) -> dict:
        """A stored week file -> the week with its sessions: each day's current session from its day record. A
        week file still carrying its own sessions (written before DECISIONS 102) fills the days with no record."""
        start = dt.date.fromisoformat(str(data["start"]))
        embedded = {str(s["date"]): s for s in data.get("sessions") or []}
        sessions = []
        for i in range(7):
            d = start + dt.timedelta(days=i)
            rec = self.day_record(d)
            cur = rec.current_session() if rec else None
            if cur is not None:
                sessions.append(cur.model_dump(mode="json"))
            elif d.isoformat() in embedded:
                sessions.append(embedded[d.isoformat()])
        return {**data, "sessions": sessions}

    def _write_week_days(self, plan: WeekPlan) -> None:
        """Write a week's sessions into its day records. A day not run yet takes the session as its plan; a day
        already run (or adjusted) whose session the week changes gets it as its new plan and current session, with
        the change recorded. A day stopped for a red flag is never overwritten (only `coach health resolve` clears it). Days
        the week no longer schedules lose their planned-only record; a week can't drop the session of a day that
        already ran (replace it, e.g. with a rest session). Every check runs before anything is written."""
        dates = [s.date for s in plan.sessions]
        if len(set(dates)) != len(dates):
            raise ValueError(f"{plan.week_id}: one session per day (a day record holds one session)")
        outside = [d for d in dates if not plan.start <= d <= plan.end]
        if outside:
            raise ValueError(f"{plan.week_id}: sessions outside the week: {outside}")
        days = {plan.start + dt.timedelta(days=i): None for i in range(7)}
        recs = {d: self.day_record(d) for d in days}
        dropped = [
            d
            for d, r in recs.items()
            if d not in dates and r is not None and r.status != "planned" and r.current_session() is not None
        ]
        if dropped:
            raise ValueError(
                f"{plan.week_id}: can't drop the session of a day already run ({', '.join(map(str, dropped))}): "
                "replace it (e.g. with a rest session) instead"
            )
        for s in plan.sessions:
            rec = recs[s.date]
            if rec is None:
                rec = DayRecord(date=s.date, status="planned", planned_session=s, planned_session_id=s.id)
            elif rec.status == "stopped_red_flag":
                continue  # safety first: a stopped day keeps its stop, whatever the week says
            else:
                cur = rec.current_session()
                if cur is not None and cur.model_dump(mode="json") == s.model_dump(mode="json"):
                    continue
                if rec.status == "planned" or rec.session is None:
                    rec.planned_session, rec.planned_session_id, rec.session = s, s.id, None
                else:
                    # a revision of a day already run is that day's new plan too: a re-run of the daily run or
                    # finish mode starts from the planned session, so it must not rebuild from the old plan
                    rec.session, rec.planned_session, rec.planned_session_id = s, s, s.id
                    rec.changes.append(
                        Change(
                            what=f"{cur.title} -> {s.title}"
                            if cur and cur.title != s.title
                            else "session revised",
                            why="week plan revised",
                            kind="replan",
                        )
                    )
            self._write(self.collection("day_records").file(s.date.isoformat()), scrub_day_record(rec))
        for d, r in recs.items():
            if d not in dates and r is not None and r.status == "planned":
                self.delete("day_records", d.isoformat())

    def _keep_planned(self, rec: DayRecord) -> DayRecord:
        """A day record written without its planned session (the daily run builds a fresh record) keeps the one
        the week plan stored."""
        if rec.planned_session is not None:
            return rec
        prior = self.day_record(rec.date)
        if prior is None or prior.planned_session is None:
            return rec
        rec = rec.model_copy()
        rec.planned_session = prior.planned_session
        rec.planned_session_id = rec.planned_session_id or prior.planned_session_id
        return rec

    def migrate_week_plans(self) -> list[str]:
        """One-time move of week files written before DECISIONS 102 (sessions inside the week): each session becomes
        its day record's planned session (a day already run keeps its adjusted session), then the week file drops
        its copy. Idempotent."""
        c = self.collection("week_plans")
        done = []
        for key in self.keys("week_plans"):
            data = self._read(c.file(key))
            embedded = (data or {}).get("sessions") or []
            if not embedded:
                continue
            for raw in embedded:
                s = WeekPlan.model_validate({**data, "sessions": [raw]}).sessions[0]
                rec = self.day_record(s.date)
                if rec is None:
                    rec = DayRecord(date=s.date, status="planned", planned_session=s, planned_session_id=s.id)
                elif rec.planned_session is None:
                    rec.planned_session, rec.planned_session_id = s, rec.planned_session_id or s.id
                else:
                    continue
                self._write(self.collection("day_records").file(s.date.isoformat()), scrub_day_record(rec))
            self._write(c.file(key), {k: v for k, v in data.items() if k != "sessions"})
            done.append(key)
        return done

    @staticmethod
    def key_of(name: str, obj: Any) -> str:
        if isinstance(obj, BaseModel):
            for f in ("id", "week_id", "block_id", "event_id", "goal_id", "race_id"):
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
        """Next free `<day>-<kind>-<n>`: one past the highest n in use, so a gap (a deleted record, or an id written
        by hand) never hands out an id that already exists and overwrites it."""
        prefix = f"{day.isoformat()}-{kind}-"
        used = [
            int(k[len(prefix) :])
            for k in self.keys(name)
            if k.startswith(prefix) and k[len(prefix) :].isdigit()
        ]
        return f"{prefix}{max(used, default=0) + 1}"

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
    def _metrics_dir(self, cache: bool = False) -> Path:
        return self._path(f"{CACHE_DIR}/metrics" if cache else "metrics")

    def _month_file(self, day: dt.date, cache: bool = False) -> Path:
        return self._metrics_dir(cache) / f"{day:%Y-%m}.jsonl"

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
        cache: bool = False,
    ) -> int:
        """items: (kind, key, date, data). `replace_kinds_in` deletes existing records of a kind in a date range first
        (used for sessions, which are re-merged every sync). Returns the number of month files that changed."""
        by_file: dict[Path, list[tuple[str, str, dt.date, dict]]] = {}
        for it in items:
            by_file.setdefault(self._month_file(it[2], cache), []).append(it)
        if replace_kinds_in:
            for _kind, (start, end) in replace_kinds_in.items():
                d = start.replace(day=1)
                while d <= end:
                    by_file.setdefault(self._month_file(d, cache), [])
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
        self, kind: str, start: dt.date | None = None, end: dt.date | None = None, cache: bool = False
    ) -> list[dict]:
        out: list[dict] = []
        mdir = self._metrics_dir(cache)
        if not mdir.exists():
            return out
        for p in sorted(mdir.glob("*.jsonl")):
            # month files are named YYYY-MM: skip whole months outside the range without reading them
            if (start and p.stem < f"{start:%Y-%m}") or (end and p.stem > f"{end:%Y-%m}"):
                continue
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
        """Committed metrics (Hevy/Intervals) with the cached Whoop fields merged in, by date."""
        by_date: dict[str, dict] = {
            r["date"]: dict(r["data"]) for r in self.metric_records("daily", start, end)
        }
        for r in self.metric_records("daily", start, end, cache=True):
            base = by_date.setdefault(r["date"], {"date": r["date"]})
            for f, v in r["data"].items():
                if f == "sources":
                    base["sources"] = sorted(set(base.get("sources", [])) | set(v))
                elif v is not None:
                    base[f] = v
        return [DailyMetrics.model_validate(by_date[d]) for d in sorted(by_date)]

    def sessions(self, start: dt.date | None = None, end: dt.date | None = None) -> list[SessionRecord]:
        """Committed sessions, each replaced by its cached Whoop-merged version when there is one."""
        recs = {r["key"]: r for r in self.metric_records("session", start, end)}
        recs.update({r["key"]: r for r in self.metric_records("session", start, end, cache=True)})
        ordered = sorted(recs.values(), key=lambda r: (r["date"], r["key"]))
        return [SessionRecord.model_validate(r["data"]) for r in ordered]

    # ---------- Whoop cache (git-ignored, rolling window) ----------
    def metric_records_daily_cached(self) -> list[DailyMetrics]:
        return [DailyMetrics.model_validate(r["data"]) for r in self.metric_records("daily", cache=True)]

    def whoop_cache_coverage(self) -> tuple[dt.date, dt.date] | None:
        """(first day, last day) the cache was filled for; None = empty (a fresh container)."""
        p = self._path(f"{CACHE_DIR}/coverage.json")
        if not p.exists():
            return None
        raw = json.loads(p.read_text())
        return dt.date.fromisoformat(raw["since"]), dt.date.fromisoformat(raw["through"])

    def set_whoop_cache_coverage(self, since: dt.date, through: dt.date) -> None:
        p = self._path(f"{CACHE_DIR}/coverage.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"since": since.isoformat(), "through": through.isoformat()}) + "\n")

    def whoop_body(self) -> dict | None:
        """Whoop's body measurement (max_heart_rate, ...) from the last sync; cache only, never committed."""
        p = self._path(f"{CACHE_DIR}/body.json")
        return json.loads(p.read_text()) if p.exists() else None

    def set_whoop_body(self, body: dict) -> None:
        p = self._path(f"{CACHE_DIR}/body.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(body) + "\n")

    def prune_whoop_cache(self, before: dt.date) -> None:
        """Drop cached months entirely before `before` and records older than it in the boundary month."""
        mdir = self._metrics_dir(cache=True)
        if not mdir.exists():
            return
        for p in sorted(mdir.glob("*.jsonl")):
            recs = {k: r for k, r in self._read_month(p).items() if r["date"] >= before.isoformat()}
            if recs:
                self._write_month(p, recs)
            else:
                p.unlink()

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
