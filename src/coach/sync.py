"""`coach sync`: incremental, idempotent fetch -> normalize -> merge -> state/metrics/."""

import datetime as dt

from coach import clock
from coach.config import Config, load_config
from coach.engine.paces import zone_minutes_from_hr
from coach.engine.parsing import parse_checkin_tag
from coach.integrations.base import Sources
from coach.models import Checkin, DailyMetrics, SessionRecord
from coach.state import State

OVERLAP_DAYS = 3  # re-fetch a few days so late uploads are merged
FIRST_SYNC_DAYS = 75  # enough history for the 60-day HRV/RHR baselines
MATCH_MINUTES = 15
COMPATIBLE = {
    "strength": {"strength", "metcon", "hiit", "other"},
    "metcon": {"strength", "metcon", "hiit", "other"},
    "hiit": {"strength", "metcon", "hiit", "other"},
    "other": {"strength", "metcon", "hiit", "other", "run", "row", "bike", "walk", "ski"},
    "run": {"run", "other"},
    "row": {"row", "other"},
    "bike": {"bike", "other"},
    "ski": {"ski", "other"},
    "walk": {"walk", "other"},
}


def merge_sessions(
    whoop: list[SessionRecord], detail: list[SessionRecord], lthr: int | None
) -> list[SessionRecord]:
    """One Session per real workout: HR/strain from Whoop, sets from Hevy, pace/dynamics from Intervals.
    Matched by start time (+/- 15 min) and compatible activity type; nothing is double counted."""
    merged: list[SessionRecord] = []
    used_whoop: set[str] = set()
    for d in sorted(detail, key=lambda s: s.start):
        best = None
        for w in whoop:
            if w.id in used_whoop or w.date != d.date:
                continue
            gap = abs((w.start - d.start).total_seconds()) / 60
            if (
                gap <= MATCH_MINUTES
                and w.sport in COMPATIBLE.get(d.sport, set())
                and (best is None or gap < best[0])
            ):
                best = (gap, w)
        rec = d.model_copy(deep=True)
        if best:
            w = best[1]
            used_whoop.add(w.id)
            rec.avg_hr, rec.max_hr, rec.strain = w.avg_hr, w.max_hr, w.strain
            rec.whoop_zone_minutes = w.whoop_zone_minutes
            rec.sources = sorted(set(rec.sources) | {"whoop"})
        merged.append(rec)
    # a Hevy and an Intervals record of the same workout (e.g. treadmill logged twice) merge too
    final: list[SessionRecord] = []
    for rec in merged:
        twin = next(
            (
                f
                for f in final
                if f.date == rec.date
                and abs((f.start - rec.start).total_seconds()) <= MATCH_MINUTES * 60
                and {f.sources[0], rec.sources[0]} == {"hevy", "intervals"}
                and rec.sport in COMPATIBLE.get(f.sport, set())
            ),
            None,
        )
        if twin:
            twin.sets = twin.sets or rec.sets
            twin.distance_mi = twin.distance_mi or rec.distance_mi
            twin.sources = sorted(set(twin.sources) | set(rec.sources))
        else:
            final.append(rec)
    for w in whoop:
        if w.id not in used_whoop:
            final.append(w.model_copy(deep=True))  # HR-only session (e.g. a walk recorded only on Whoop)
    for rec in final:
        if lthr and rec.avg_hr and rec.zone_minutes is None:
            rec.zone_minutes = zone_minutes_from_hr(rec.avg_hr, rec.duration_min, lthr)
    return sorted(final, key=lambda s: s.start)


def _session_key(s: SessionRecord) -> str:
    prio = [src for src in ("hevy", "intervals", "whoop") if src in s.sources]
    return f"{prio[0] if prio else 'x'}:{s.start.isoformat()}"


def _plan_link(state: State, s: SessionRecord) -> str | None:
    plan = state.week_plan(clock.iso_week_id(s.date))
    if plan:
        ps = plan.session_on(s.date)
        if ps:
            return ps.id
    return None


def sync(
    sources: Sources, state: State | None = None, today: dt.date | None = None, cfg: Config | None = None
) -> dict:
    state = state or State()
    cfg = cfg or load_config()
    today = today or clock.today()
    sync_state = state.read_json("metrics/sync_state.json") or {}
    last = sync_state.get("last_sync")
    start = (
        (dt.date.fromisoformat(last) - dt.timedelta(days=OVERLAP_DAYS))
        if last
        else today - dt.timedelta(days=FIRST_SYNC_DAYS)
    )
    report: dict = {"window": [start.isoformat(), today.isoformat()], "counts": {}, "stale": [], "errors": {}}
    items: list[tuple[str, str, dt.date, dict]] = []

    def run(name, fn):
        try:
            return fn()
        except Exception as e:  # a failing source must not block the others
            report["errors"][name] = f"{type(e).__name__}: {e}"
            return None

    daily: list[DailyMetrics] = []
    for name, fn in [
        ("whoop", lambda: sources.whoop.daily(start, today)),
        ("withings", lambda: sources.withings.measurements(start, today)),
        ("nutrition", lambda: sources.nutrition.daily(start, today)),
    ]:
        got = run(name, fn) or []
        report["counts"][f"{name}_daily"] = len(got)
        daily.extend(got)
    wellness = run("intervals_wellness", lambda: sources.intervals.wellness(start, today))
    checkins: list[Checkin] = []
    if wellness:
        wm, wc = wellness
        daily.extend(m for m in wm if m.ctl is not None or m.atl is not None)
        checkins.extend(wc)
    for m in daily:
        items.append(("daily", m.date.isoformat(), m.date, m.model_dump(mode="json", exclude_none=True)))

    whoop_w = run("whoop_workouts", lambda: sources.whoop.workouts(start, today)) or []
    hevy_w = run("hevy", lambda: sources.hevy.workouts(start, today)) or []
    acts = run("intervals_activities", lambda: sources.intervals.activities(start, today)) or []
    zones = state.zones() or {}
    merged = merge_sessions(whoop_w, [*hevy_w, *acts], zones.get("lthr"))
    for s in merged:
        s.planned_session_id = _plan_link(state, s)
        items.append(("session", _session_key(s), s.date, s.model_dump(mode="json", exclude_none=True)))
        tag = parse_checkin_tag(s.notes_untrusted) if "hevy" in s.sources else {}
        if tag:
            checkins.append(Checkin(date=s.date, source="hevy_notes", **tag))
    report["counts"]["sessions"] = len(merged)
    for c in checkins:
        items.append(
            (
                "checkin",
                f"{c.date.isoformat()}:{c.source}",
                c.date,
                c.model_dump(mode="json", exclude_none=True),
            )
        )
    gear = run("intervals_gear", sources.intervals.gear)
    if gear is not None:
        state.write_json("metrics/gear.json", [g.model_dump(mode="json") for g in gear])

    changed = state.upsert_metrics(
        items, replace_kinds_in={"session": (start, today)} if (hevy_w or acts or whoop_w) else None
    )
    report["changed_files"] = changed

    # stale-source detection: report, never guess
    latest = {k: None for k in ("whoop", "withings")}
    for m in state.daily_metrics(today - dt.timedelta(days=10), today):
        if m.recovery_score is not None:
            latest["whoop"] = m.date
        if m.weight_kg is not None:
            latest["withings"] = m.date
    if latest["whoop"] != today:
        report["stale"].append(
            "whoop: today's recovery not available yet"
            if latest["whoop"] == today - dt.timedelta(days=1)
            else f"whoop: no recovery since {latest['whoop']}"
        )
    if latest["withings"] is None or (today - latest["withings"]).days > 3:
        report["stale"].append(f"withings: no weigh-in since {latest['withings']}")
    for name in report["errors"]:
        report["stale"].append(f"{name}: fetch failed")
    report["recovery_today"] = latest["whoop"] == today
    sync_state["last_sync"] = today.isoformat()
    sync_state["last_report"] = report
    state.write_json("metrics/sync_state.json", sync_state)
    return report
