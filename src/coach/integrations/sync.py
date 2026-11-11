"""`coach sync`: incremental, idempotent fetch -> normalize -> merge -> state/metrics/."""

import datetime as dt

from coach import clock
from coach.config import Config, load_config
from coach.engine.paces import zone_minutes_from_hr
from coach.engine.parsing import parse_checkin_tag
from coach.integrations.base import Sources
from coach.models import Checkin, DailyMetrics, SessionRecord
from coach.models.records import SyncState
from coach.store import Store

OVERLAP_DAYS = 3  # re-fetch a few days so late uploads are merged
FIRST_SYNC_DAYS = 75  # enough history for the 60-day HRV/RHR baselines
WHOOP_WINDOW_DAYS = 75  # Whoop is refetched for this window when the cache is cold (fresh container)
# Recovery-type fields: never committed, whichever source they came from (DECISIONS 73, 75)
WHOOP_DAILY_FIELDS = (
    "recovery_score",
    "hrv_rmssd_ms",
    "rhr_bpm",
    "sleep_hours",
    "sleep_performance",
    "day_strain",
)


def _without_whoop(m: DailyMetrics) -> DailyMetrics:
    return m.model_copy(update=dict.fromkeys(WHOOP_DAILY_FIELDS))


def _whoop_part(m: DailyMetrics, source: str) -> DailyMetrics | None:
    vals = {f: getattr(m, f) for f in WHOOP_DAILY_FIELDS if getattr(m, f) is not None}
    return DailyMetrics(date=m.date, sources=[source], **vals) if vals else None


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
            rec.kilojoule = w.kilojoule
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


def _plan_link(state: Store, s: SessionRecord) -> str | None:
    plan = state.week_plan(clock.iso_week_id(s.date))
    if plan:
        ps = plan.session_on(s.date)
        if ps:
            return ps.id
    return None


def sync(
    sources: Sources, state: Store | None = None, today: dt.date | None = None, cfg: Config | None = None
) -> dict:
    state = state or Store()
    cfg = cfg or load_config()
    today = today or clock.today()
    sync_state = state.get("sync_state") or SyncState()
    last = sync_state.last_sync
    start = (last - dt.timedelta(days=OVERLAP_DAYS)) if last else today - dt.timedelta(days=FIRST_SYNC_DAYS)
    report: dict = {"window": [start.isoformat(), today.isoformat()], "counts": {}, "stale": [], "errors": {}}
    items: list[tuple[str, str, dt.date, dict]] = []

    def run(name, fn):
        try:
            return fn()
        except Exception as e:  # a failing source must not block the others
            report["errors"][name] = f"{type(e).__name__}: {e}"
            return None

    # --- Whoop: never committed. Refetched into the git-ignored cache (DECISIONS 73) for a rolling window. ---
    cov = state.whoop_cache_coverage()
    window_start = today - dt.timedelta(days=WHOOP_WINDOW_DAYS)
    warm = cov is not None and cov[0] <= window_start and cov[1] >= start
    wstart = max(start, window_start) if warm else window_start

    whoop_daily = run("whoop", lambda: sources.whoop.daily(wstart, today))
    report["counts"]["whoop_daily"] = len(whoop_daily or [])
    if whoop_daily is not None:
        state.upsert_metrics(
            [
                ("daily", m.date.isoformat(), m.date, m.model_dump(mode="json", exclude_none=True))
                for m in whoop_daily
            ],
            cache=True,
        )

    daily: list[DailyMetrics] = []
    nutrition = run("nutrition", lambda: sources.nutrition.daily(start, today)) or []
    report["counts"]["nutrition_daily"] = len(nutrition)
    daily.extend(_without_whoop(m) for m in nutrition)
    backup = cfg.settings.whoop_backup == "intervals"
    wfrom = min(start, wstart) if backup else start
    wellness = run("intervals_wellness", lambda: sources.intervals.wellness(wfrom, today))
    checkins: list[Checkin] = []
    if wellness:
        wm, wc = wellness
        daily.extend(
            _without_whoop(m)
            for m in wm
            if m.date >= start and any(v is not None for v in (m.ctl, m.atl, m.weight_kg, m.body_fat_pct))
        )
        checkins.extend(c for c in wc if c.date >= start)
        if backup:  # only days the direct API left without a recovery score; cache only
            have = {m.date for m in state.metric_records_daily_cached() if m.recovery_score is not None}
            fill = [p for m in wm if m.date not in have and (p := _whoop_part(m, "intervals_whoop"))]
            report["counts"]["whoop_backup_days"] = len(fill)
            state.upsert_metrics(
                [
                    ("daily", m.date.isoformat(), m.date, m.model_dump(mode="json", exclude_none=True))
                    for m in fill
                ],
                cache=True,
            )
    report["counts"]["weigh_ins"] = sum(1 for m in daily if m.weight_kg is not None)
    for m in daily:
        items.append(("daily", m.date.isoformat(), m.date, m.model_dump(mode="json", exclude_none=True)))

    hevy_w = run("hevy", lambda: sources.hevy.workouts(start, today)) or []
    acts = run("intervals_activities", lambda: sources.intervals.activities(start, today)) or []
    zones = state.zones()
    lthr = zones.lthr if zones else cfg.profile.running.default_zones.lthr  # default until the first TT
    detail = merge_sessions([], [*hevy_w, *acts], lthr)  # committed: no Whoop fields
    for s in detail:
        s.planned_session_id = _plan_link(state, s)
        items.append(("session", _session_key(s), s.date, s.model_dump(mode="json", exclude_none=True)))
        tag = parse_checkin_tag(s.notes_untrusted) if "hevy" in s.sources else {}
        if tag:
            checkins.append(Checkin(date=s.date, source="hevy_notes", **tag))
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
        state.put("gear", [g.model_dump(mode="json") for g in gear])

    changed = state.upsert_metrics(
        items, replace_kinds_in={"session": (start, today)} if (hevy_w or acts) else None
    )
    report["changed_files"] = changed

    # Whoop HR/strain/zones merged onto the committed sessions of the window, kept only in the cache
    whoop_w = run("whoop_workouts", lambda: sources.whoop.workouts(wstart, today))
    if whoop_w is not None:
        committed = [
            SessionRecord.model_validate(r["data"]) for r in state.metric_records("session", wstart, today)
        ]
        overlay = [s for s in merge_sessions(whoop_w, committed, lthr) if "whoop" in s.sources]
        for s in overlay:
            s.planned_session_id = s.planned_session_id or _plan_link(state, s)
        state.upsert_metrics(
            [
                ("session", _session_key(s), s.date, s.model_dump(mode="json", exclude_none=True))
                for s in overlay
            ],
            replace_kinds_in={"session": (wstart, today)},
            cache=True,
        )
    else:  # don't let a stale cached copy hide a session that was just re-synced
        state.upsert_metrics([], replace_kinds_in={"session": (start, today)}, cache=True)
    report["counts"]["sessions"] = len(state.sessions(start, today))
    if (whoop_daily is not None and whoop_w is not None) or (backup and wellness):
        state.set_whoop_cache_coverage(window_start, today)
    state.prune_whoop_cache(window_start)

    # stale-source detection: report, never guess
    latest: dict[str, dt.date | None] = {k: None for k in ("whoop", "weight")}
    for m in state.daily_metrics(today - dt.timedelta(days=10), today):
        if m.recovery_score is not None:
            latest["whoop"] = m.date
        if m.weight_kg is not None:
            latest["weight"] = m.date
    if latest["whoop"] != today:
        report["stale"].append(
            "whoop: today's recovery not available yet"
            if latest["whoop"] == today - dt.timedelta(days=1)
            else (
                f"whoop: no recovery since {latest['whoop']}"
                if latest["whoop"]
                else "whoop: no recovery in the last 10 days"
            )
        )
    if latest["weight"] is None or (today - latest["weight"]).days > 3:
        report["stale"].append(
            f"weight: no weigh-in since {latest['weight']}"
            if latest["weight"]
            else "weight: no weigh-in in the last 10 days"
        )
    for name in report["errors"]:
        report["stale"].append(f"{name}: fetch failed")
    report["recovery_today"] = latest["whoop"] == today
    # Offline (not just late): the source failed, or nothing for 2+ days. The 9:05 catch-up can't fix that, so
    # the daily run finalizes without a readiness score instead of waiting (never guesses one).
    report["whoop_offline"] = latest["whoop"] != today and (
        "whoop" in report["errors"] or latest["whoop"] is None or (today - latest["whoop"]).days >= 2
    )
    sync_state.last_sync = today
    sync_state.last_report = report
    state.put("sync_state", sync_state)
    return report
