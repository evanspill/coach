"""adjust-day fallback: readiness, joints, weather, bar speed -> today's session + recovery + fuel."""

import datetime as dt
import statistics

from coach.coaching.context import Context
from coach.coaching.skills import design as D
from coach.coaching.skills import fuel
from coach.coaching.skills.design import Picker
from coach.coaching.skills.plan_week import finalize
from coach.engine import gear as G
from coach.engine import testing as T
from coach.engine.weather import weather_call
from coach.models import Change, DayRecord, Deviation, RunSegment, Session, SessionBlock, WeekPlan
from coach.models.records import WeatherCall

HARD_TYPES = {
    "run_long",
    "run_quality",
    "hyrox",
    "metcon",
    "test",
    "competition",
    "race",
    "full_body",
    "lower",
}


def _z2_block(location: str, minutes: int = 40, zone: str = "Z2") -> SessionBlock:
    if location == "gym":
        seg = RunSegment(
            label=f"{minutes} min {zone} (erg or treadmill)", zone=zone, duration_min=minutes, modality="bike"
        )  # type: ignore[arg-type]
    else:
        seg = RunSegment(label=f"{minutes} min {zone} run", zone=zone, duration_min=minutes)  # type: ignore[arg-type]
    return SessionBlock(kind="run", title=f"{minutes} min {zone} (replaces hard conditioning)", run=[seg])


def _resubstitute(s: Session, P: Picker, changes: list[Change], why: str) -> None:
    """Swap anything no longer allowed (rungs, joint flags, equipment) using regressions."""
    for b in s.blocks:
        items = list(b.items) + (list(b.metcon.movements) if b.metcon else [])
        for it in items:
            ex = P.lib.get(it.exercise_id)
            in_metcon = b.metcon is not None and it in b.metcon.movements
            if P.ok(ex, for_metcon=in_metcon, block_kind=b.kind):
                continue
            new = P.pick(it.exercise_id, for_metcon=in_metcon, block_kind=b.kind)
            if new and new != it.exercise_id:
                changes.append(
                    Change(what=f"{ex.name if ex else it.exercise_id} -> {P.lib.get(new).name}", why=why)
                )
                it.exercise_id = new
            elif new is None:
                changes.append(Change(what=f"dropped {ex.name if ex else it.exercise_id}", why=why))
                if in_metcon:
                    b.metcon.movements.remove(it)  # type: ignore[union-attr]
                else:
                    b.items.remove(it)


def _weather_route(s: Session, wc: WeatherCall, changes: list[Change]) -> None:
    if s.location not in {"outdoor", "track"} or not s.run_segments():
        return
    if wc.tier == "indoor":
        s.location = "gym"
        s.route = "gym_treadmill"
        for seg in s.run_segments():
            seg.terrain = "treadmill"
        changes.append(Change(what="run moved indoors to the gym treadmill", why="; ".join(wc.reasons)))
    elif wc.tier == "slow":
        changes.append(
            Change(
                what=f"paces +{wc.pace_adjust_s_per_mi[0]}-{wc.pace_adjust_s_per_mi[1]} s/mi, extra sodium",
                why="; ".join(wc.reasons),
            )
        )


def adjust(
    ctx: Context, day: dt.date, plan: WeekPlan | None, sources=None, weather_hourly: list[dict] | None = None
) -> DayRecord:
    cfg = ctx.cfg
    rec = DayRecord(date=day, status="complete", generated_by="fallback")
    planned = plan.session_on(day) if plan else None
    rec.planned_session_id = planned.id if planned else None
    session = planned.model_copy(deep=True) if planned else None
    changes: list[Change] = []
    week_type = plan.week_type if plan else "training"

    # --- safety gates first (shared red-flag rules, docs/SAFETY.md) ---
    active_flags = [e for e in ctx.health if e.kind == "red_flag" and e.active_on(day)]
    if active_flags:
        rec.status = "stopped_red_flag"
        rec.session = D.rest_session(ctx, day, "Red flag reported: stop training and see a doctor.")
        rec.changes = [
            Change(
                what="all training stopped",
                why=f"red flag: {', '.join(e.flag or 'red flag' for e in active_flags)} (see a doctor before training)",
                kind="replan",
            )
        ]
        return rec
    ill = next((e for e in ctx.health if e.kind == "illness" and e.active_on(day)), None)
    if ill:
        if ill.symptoms != "above_neck":
            rec.session = D.rest_session(
                ctx, day, "Below-the-neck illness: no training until symptoms resolve."
            )
            changes.append(Change(what="rest day", why="below-the-neck symptoms (neck check)", kind="replan"))
        else:
            rec.session = D.recovery_session(ctx, day, 25, "Above-the-neck symptoms: easy movement only.")
            changes.append(
                Change(
                    what="easy walk + mobility only",
                    why="above-the-neck symptoms (neck check)",
                    kind="replan",
                )
            )
        session = None

    readiness = ctx.readiness(day)
    rec.readiness = readiness
    if readiness.state == "unknown" and "whoop_recovery" in readiness.data_missing:
        rec.status = "waiting_for_recovery"

    # --- weather ---
    if session is not None and weather_hourly is not None:
        home = cfg.profile.identity.home
        rec.weather = weather_call(
            day,
            weather_hourly,
            cfg.profile.weather,
            home.lat,
            home.lon,
            session.start_time,
            max(30, session.expected_minutes),
        )

    if session is not None and session.type != "rest" and rec.status != "waiting_for_recovery":
        P = Picker(ctx, week_type, session.location)
        yesterday = ctx.state.day_record(day - dt.timedelta(days=1))
        red_carry = bool(
            yesterday
            and yesterday.readiness
            and yesterday.readiness.state == "red"
            and readiness.state != "red"
        )
        state = readiness.state
        if session.tests and state == "red":
            new_day = None
            if plan:
                new_day = _reschedule_tests(ctx, plan, session, day)
            changes.append(
                Change(
                    what=f"tests {session.tests} moved to {new_day}"
                    if new_day
                    else f"tests {session.tests} postponed (no slot within +/-2 days)",
                    why="test day needs Green or Yellow readiness",
                    kind="replan",
                )
            )
            session = D.recovery_session(ctx, day, 30, "Red: Z1 + mobility")
        elif state == "red" or red_carry:
            why = "; ".join(readiness.reasons) if state == "red" else "second day of the 48 h after a Red day"
            changes.append(
                Change(
                    what=f"{session.title} -> Z1 walk + mobility", why=f"Red readiness ({why})", kind="small"
                )
            )
            session = D.recovery_session(
                ctx, day, cfg.training.rules.red_recovery_minutes, "Red: next 48 h are Z1 + mobility"
            )
        elif state == "yellow":
            yr = cfg.training.rules.yellow_replacement
            replaced = False
            for i, b in enumerate(session.blocks):
                is_hard_cond = b.metcon is not None or any(seg.zone in {"T", "Z5", "Z3"} for seg in b.run)
                if is_hard_cond and session.type not in {"test", "competition", "race"}:
                    session.blocks[i] = _z2_block(session.location, int(yr["minutes"]), yr.get("zone", "Z2"))
                    replaced = True
            if session.type == "run_quality":
                session.type = "run_easy"
            if replaced:
                changes.append(
                    Change(
                        what=f"metcon/threshold work -> {yr['minutes']} min {yr.get('zone', 'Z2')}; primary strength kept",
                        why=f"Yellow readiness ({'; '.join(readiness.reasons)})",
                    )
                )
        # accessory volume -50% in the 72 h after a Red day
        recent_red = any(
            (r := ctx.state.day_record(day - dt.timedelta(days=i)))
            and r.readiness
            and r.readiness.state == "red"
            for i in (2, 3)
        )
        if recent_red and session.type not in {"recovery", "rest"}:
            cut = False
            for b in session.blocks:
                if b.kind == "hypertrophy":
                    for it in b.items:
                        new = max(1, it.sets // 2)
                        if new < it.sets:
                            it.sets = new
                            cut = True
            if cut:
                changes.append(Change(what="accessory sets halved", why="returning from a Red day"))
        # joint flags, rungs, equipment -> regressions
        P = Picker(ctx, week_type, session.location)
        flags = [f.region for f in readiness.joint_flags]
        _resubstitute(
            session,
            P,
            changes,
            f"active joint flag ({', '.join(flags)})" if flags else "movement readiness rung / equipment",
        )
        if rec.weather:
            _weather_route(session, rec.weather, changes)
            if session.location == "gym":
                _resubstitute(session, Picker(ctx, week_type, "gym"), changes, "moved indoors")
        # same-day bar speed (VBT)
        load_cap: dict[str, float] = {}
        ci = next((c for c in ctx.state.checkins(day, day)), None)
        recent_v = [
            c.bar_speed_mps
            for c in ctx.state.checkins(day - dt.timedelta(days=42), day - dt.timedelta(days=1))
            if c.bar_speed_mps
        ]
        base_v = statistics.median(recent_v) if len(recent_v) >= 3 else None  # usual top warm-up set speed
        if ci and ci.bar_speed_mps and base_v:
            delta = (ci.bar_speed_mps - base_v) / base_v * 100
            if delta <= -cfg.profile.thresholds.vbt_slow_pct:
                changes.append(
                    Change(
                        what="main lift load capped at last week's", why=f"bar speed {delta:.0f}% vs usual"
                    )
                )
                for b in session.blocks:
                    if b.kind == "strength":
                        for it in b.items:
                            load_cap[it.exercise_id] = 0.97 * (it.load_kg or 9999)
            elif delta >= cfg.profile.thresholds.vbt_fast_pct:
                changes.append(
                    Change(
                        what="small load increase available on the main lift (+2.5%) if warm-ups feel crisp",
                        why=f"bar speed +{delta:.0f}% vs usual",
                    )
                )
        session.expected_minutes = D.estimate_minutes(session, ctx.zones.threshold_pace_s_per_mi)
        finalize(ctx, [session])
        if load_cap:
            for b in session.blocks:
                for it in b.items:
                    if it.exercise_id in load_cap and it.load_kg and it.load_kg > load_cap[it.exercise_id]:
                        it.load_kg = round(load_cap[it.exercise_id], 1)
        if rec.weather and rec.weather.tier == "slow":
            for seg in session.run_segments():
                if seg.pace_s_per_mi:
                    a, b2 = rec.weather.pace_adjust_s_per_mi
                    seg.pace_s_per_mi = (seg.pace_s_per_mi[0] + a, seg.pace_s_per_mi[1] + b2)
        rec.session = session
    elif session is not None:
        rec.session = session
    elif rec.session is None:
        rec.session = None

    rec.changes = changes + rec.changes
    # --- recovery prescription ---
    s = rec.session
    y_metrics = ctx.state.daily_metrics(day - dt.timedelta(days=1), day - dt.timedelta(days=1))
    y_strain = y_metrics[0].day_strain if y_metrics else None
    rx: list[str] = []
    rc = cfg.profile.recovery
    run_test = bool(s and s.type == "test" and any(cfg.tests.tests[t].slot == "run" for t in s.tests))
    if s and (s.type in {"run_long", "run_quality", "hyrox", "race", "competition"} or run_test):
        rx.append(rc.after_hard_session)
    if s and s.type in HARD_TYPES or (y_strain and y_strain > cfg.profile.thresholds.high_strain):
        lower = bool(s and s.type in {"run_long", "run_quality", "lower", "hyrox"})
        area = rc.areas.get("lower" if lower else "upper", "loaded areas")
        rx.append(rc.evening_mobility.format(area=area))
    if rc.nightly:
        rx.append(rc.nightly)
    rec.recovery_prescription = rx
    # --- nutrition ---
    rec.nutrition = fuel.day_targets(ctx, day, plan, sources, s if s and s.type != "rest" else None)
    rec.fueling_cue = rec.nutrition.peri_workout
    # --- gear ---
    runs_today = bool(s and any(seg.modality == "run" for seg in s.run_segments()))
    if runs_today:
        s.shoe = G.shoe_for(s.type, ctx.state.gear())
    alerts = G.shoe_alerts(ctx.state.gear(), cfg.profile.thresholds.shoe_alert_miles)
    # mention worn shoes on Sundays and on days they'd be used, not every day
    rec.gear_alerts = [
        a for a in alerts if day.weekday() == 6 or (runs_today and s.shoe and a.startswith(s.shoe))
    ]
    return rec


def _reschedule_tests(ctx: Context, plan: WeekPlan, session: Session, day: dt.date) -> dt.date | None:
    scheduled = {t: s.date for s in plan.sessions for t in s.tests}
    target = None
    for t in session.tests:
        nd = T.reschedule_for_red(t, scheduled, ctx.cfg.tests, day, day + dt.timedelta(days=1), 2, set())
        if nd is None or nd > plan.end:
            nd = None
            for cand in (day + dt.timedelta(days=d) for d in (1, 2)):
                if cand <= plan.end and cand not in {
                    d for tt, d in scheduled.items() if tt not in session.tests
                }:
                    nd = cand
                    break
        target = target or nd
    if target is None:
        return None
    moved = session.model_copy(deep=True)
    moved.date = target
    moved.id = f"{target.isoformat()}-test"
    plan.sessions = [s for s in plan.sessions if s.date != target and s.id != session.id]
    rec = D.recovery_session(ctx, day, 30, "Red: tests moved")
    plan.sessions += [moved, rec]
    plan.sessions.sort(key=lambda s: s.date)
    plan.deviations.append(
        Deviation(
            field="tests",
            planned=day.isoformat(),
            actual=target.isoformat(),
            reason="Red readiness on test day: rescheduled within +/-2 days",
        )
    )
    ctx.state.put("week_plans", plan)
    return target
