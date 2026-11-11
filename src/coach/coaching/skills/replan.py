"""replan fallback: reactive deloads, illness (neck check + graded return), travel, missed sessions."""

import datetime as dt

from coach import clock
from coach.coaching.context import Context
from coach.coaching.skills import design as D
from coach.coaching.skills.plan_block import deload_ranges, targets_for
from coach.coaching.skills.plan_week import finalize, plan_week
from coach.engine.deloads import pull_forward
from coach.engine.validator import validate_outline
from coach.models import BlockOutline, Deviation, Session, WeekPlan
from coach.models.plans import Revision


def reactive_deload(ctx: Context, today: dt.date, reason: str) -> tuple[BlockOutline, int] | None:
    """Pull the next deload forward to next week and re-space the rest of the block."""
    ol = ctx.outline
    if ol is None or ctx.block is None:
        return None
    next_week = ctx.week_index + 1
    target = ol.week(next_week)
    if target is None or target.type in {"deload", "transition", "competition", "taper"}:
        return None
    if any(w in ol.deload_weeks for w in (ctx.week_index, next_week)):
        return None
    comp = set(ol.competition_weeks)
    n = len(ol.weeks)
    new_deloads = pull_forward(ol.deload_weeks, next_week, n, comp)
    new = ol.model_copy(deep=True)
    spec = ctx.cfg.season.spec(ctx.block.key)
    for w in new.weeks:
        if w.type in {"deload", "training"} and w.week_index not in comp:
            want = "deload" if w.week_index in new_deloads else "training"
            if want != w.type and w.week_index >= next_week:
                keys, ranges = targets_for(spec, want)
                prev = ol.week(w.week_index - 1)
                w.type = want  # type: ignore[assignment]
                w.key_sessions = keys
                w.hard_sets = (
                    ranges
                    if want == "training"
                    else deload_ranges(dict(wk1.hard_sets) if (wk1 := ol.week(1)) else ranges)
                )
                if want == "deload":
                    w.run_miles = round((prev.run_miles if prev else w.run_miles) * 0.7, 1)
                else:
                    w.run_miles = round(
                        max(
                            w.run_miles, (prev.run_miles if prev and prev.type == "training" else w.run_miles)
                        ),
                        1,
                    )
    new.deload_weeks = [w.week_index for w in new.weeks if w.type == "deload"]
    new.revisions.append(
        Revision(
            at=today,
            reason=reason,
            change=f"deload pulled forward to week {next_week}; deloads now {new.deload_weeks}",
        )
    )
    if validate_outline(new):
        return None
    return new, next_week


def illness(ctx: Context, plan: WeekPlan, start: dt.date, end: dt.date | None, symptoms: str) -> WeekPlan:
    """Below the neck: no training until resolved, then a graded return (Z1 -> Z2 -> deload-volume -> normal)."""
    new = plan.model_copy(deep=True)
    last_sick = end or new.end
    for i, s in enumerate(new.sessions):
        if start <= s.date <= last_sick:
            if symptoms == "below_neck":
                new.sessions[i] = D.rest_session(
                    ctx, s.date, "Below-the-neck illness: no training until symptoms resolve."
                )
                if s.date not in new.illness_dates:
                    new.illness_dates.append(s.date)
            elif s.type not in {"rest", "recovery"}:
                new.sessions[i] = D.recovery_session(
                    ctx, s.date, 25, "Above-the-neck symptoms: easy movement only."
                )
    if end and symptoms == "below_neck":
        graded = [
            ("return-1", lambda d: D.recovery_session(ctx, d, 25, "Graded return day 1: Z1 only")),
            ("return-2", lambda d: _easy_z2(ctx, d, 30)),
        ]
        for k, (_label, fn) in enumerate(graded):
            d = end + dt.timedelta(days=1 + k)
            idx = next((i for i, s in enumerate(new.sessions) if s.date == d), None)
            if idx is not None:
                new.sessions[idx] = fn(d)
        d3 = end + dt.timedelta(days=3)
        for s in new.sessions:
            if s.date >= d3:
                for b in s.blocks:
                    if b.kind in {"strength", "hypertrophy"}:
                        for it in b.items:
                            it.sets = max(1, round(it.sets * 0.6))
                    if b.metcon:
                        b.metcon.time_cap_min = max(6, round(b.metcon.time_cap_min * 0.6))
    new.deviations.append(
        Deviation(
            field="hard_sets",
            planned="outline",
            actual="reduced",
            reason=f"illness ({symptoms}) {start}..{end or 'ongoing'}",
        )
    )
    new.deviations.append(Deviation(field="run_miles", planned="outline", actual="reduced", reason="illness"))
    new.deviations.append(
        Deviation(
            field="key_sessions", planned="outline", actual="protected where possible", reason="illness"
        )
    )
    new.deviations.append(Deviation(field="pillars", planned="outline", actual="below MED", reason="illness"))
    finalize(ctx, new.sessions)
    new.rationale += f" Replanned for illness ({symptoms})."
    return new


def _easy_z2(ctx: Context, day: dt.date, minutes: int | None = None) -> Session:
    from coach.coaching.skills.templates import build_session

    return build_session(ctx, "graded_return_z2", day, "deload", 0.0, day.isocalendar()[1])


def travel(ctx: Context, plan: WeekPlan, dates: list[dt.date]) -> WeekPlan:
    """No gym: bodyweight/bands strength + runs where you are. Protect key sessions by moving them off travel days."""
    new = plan.model_copy(deep=True)
    travel_set = set(dates)
    home_days = [s for s in new.sessions if s.date not in travel_set]
    moved: list[str] = []
    for s in sorted(
        [s for s in new.sessions if s.date in travel_set and s.key and s.location == "gym"],
        key=lambda s: s.date,
    ):
        recovery_left = sum(1 for h in new.sessions if h.type in {"recovery", "rest"})
        can_use_recovery = recovery_left > ctx.cfg.training.rules.min_recovery_days_per_week
        free = next(
            (
                h
                for h in home_days
                if not h.key
                and (h.type == "run_easy" or (can_use_recovery and h.type in {"recovery", "rest"}))
            ),
            None,
        )
        if free:
            idx = new.sessions.index(free)
            moved_s = s.model_copy(deep=True)
            moved_s.date = free.date
            moved_s.id = f"{free.date.isoformat()}-{s.id.split('-', 3)[-1]}"
            new.sessions[idx] = moved_s
            home_days.remove(free)
            moved.append(f"{s.title} -> {free.date:%a}")
    for i, s in enumerate(new.sessions):
        if s.date in travel_set:
            new.sessions[i] = _travel_session(ctx, s.date, s)
    new.travel_dates = sorted(travel_set)
    _fix_back_to_back(ctx, new)
    new.deviations.append(
        Deviation(field="hard_sets", planned="outline", actual="reduced", reason="travel without a gym")
    )
    new.deviations.append(
        Deviation(
            field="key_sessions",
            planned="outline",
            actual="moved: " + (", ".join(moved) or "none"),
            reason="travel",
        )
    )
    new.deviations.append(
        Deviation(field="pillars", planned="outline", actual="bodyweight versions", reason="travel")
    )
    new.deviations.append(Deviation(field="run_miles", planned="outline", actual="as able", reason="travel"))
    finalize(ctx, new.sessions)
    new.rationale += f" Replanned for travel {dates[0]}..{dates[-1]} (no gym)."
    return new


def _travel_session(ctx: Context, day: dt.date, original: Session) -> Session:
    from coach.coaching.skills.templates import build_session

    if original.type == "rest":
        return original
    if original.type == "recovery":  # a walk and mobility work anywhere; keep the recovery day
        kept = original.model_copy(deep=True)
        kept.location = "travel"
        return kept
    wn = day.isocalendar()[1]
    if original.type in {"run_easy", "run_long", "run_quality"}:
        miles = sum(seg.distance_mi or 0 for seg in original.run_segments() if seg.modality == "run") * 0.8
        return build_session(ctx, "travel_run", day, "training", miles, wn)
    return build_session(ctx, "travel_strength", day, "training", 0.0, wn)


def _fix_back_to_back(ctx: Context, plan: WeekPlan) -> None:
    from coach.engine.sessions import categories

    ordered = sorted(plan.sessions, key=lambda s: s.date)
    for a, b in zip(ordered, ordered[1:], strict=False):
        ca, cb = categories(a, ctx.cfg.library, ctx.cfg.tests), categories(b, ctx.cfg.library, ctx.cfg.tests)
        if any(x in ca and y in cb for x, y in ctx.cfg.training.rules.forbidden_back_to_back):
            for blk in b.blocks:
                if blk.metcon is not None and b.type in {"full_body", "upper", "lower"}:
                    blk.metcon.time_cap_min = 5  # becomes a short finisher, not glycolytic work


def missed_sessions(ctx: Context, plan: WeekPlan, today: dt.date) -> tuple[WeekPlan, list[str]] | None:
    """2+ missed sessions this week: protect the key sessions that are left, drop accessories."""
    done = {s.date for s in ctx.state.sessions(plan.start, today - dt.timedelta(days=1))}
    missed = [
        s
        for s in plan.sessions
        if s.date < today and s.type not in {"rest", "recovery"} and s.date not in done
    ]
    if len(missed) < 2:
        return None
    new = plan.model_copy(deep=True)
    notes = [f"missed: {', '.join(f'{s.date:%a} {s.title}' for s in missed)}"]
    for s in new.sessions:
        if s.date >= today and not s.key:
            for b in s.blocks:
                if b.kind == "hypertrophy":
                    b.items = b.items[:2]
    new.deviations.append(
        Deviation(
            field="hard_sets",
            planned="outline",
            actual="reduced",
            reason=f"{len(missed)} missed sessions this week",
        )
    )
    new.deviations.append(
        Deviation(field="run_miles", planned="outline", actual="as completed", reason="missed sessions")
    )
    new.deviations.append(
        Deviation(
            field="key_sessions",
            planned="outline",
            actual="remaining key sessions protected",
            reason="missed sessions",
        )
    )
    new.deviations.append(
        Deviation(field="pillars", planned="outline", actual="as completed", reason="missed sessions")
    )
    finalize(ctx, [s for s in new.sessions if s.date >= today])
    notes.append("remaining key sessions kept; accessories trimmed; no make-up doubling")
    return new, notes


def rebuild_next_week(ctx: Context, week_start: dt.date, note: str) -> WeekPlan:
    return plan_week(ctx, week_start, notes=[note])


def week_id(day: dt.date) -> str:
    return clock.iso_week_id(day)


def apply_availability(ctx: Context, plan: WeekPlan) -> tuple[WeekPlan, list[str]]:
    """Respect recorded travel / gym closures / busy days for this week (athlete data: availability)."""
    entries = ctx.state.availability(plan.start, plan.end)
    if not entries:
        return plan, []
    notes = []
    no_gym = sorted(
        {d for a in entries if a.kind in {"travel", "gym_closed", "vacation"} for d in _days(a, plan)}
    )
    busy = sorted({d for a in entries if a.kind == "busy" for d in _days(a, plan)})
    if no_gym:
        plan = travel(ctx, plan, no_gym)
        notes.append("no gym " + ", ".join(f"{d:%a}" for d in no_gym))
    for d in busy:
        s = plan.session_on(d)
        if s and s.type not in {"rest", "recovery"} and not s.key:
            idx = plan.sessions.index(s)
            plan.sessions[idx] = D.recovery_session(ctx, d, 20, "Busy day: short walk + mobility")
            notes.append(f"busy {d:%a}: short session")
    if notes:
        plan.deviations.append(
            Deviation(
                field="availability",
                planned="template",
                actual="; ".join(notes),
                reason="athlete availability (travel / closures / busy days)",
            )
        )
    return plan, notes


def _days(a, plan: WeekPlan) -> list[dt.date]:
    return [
        plan.start + dt.timedelta(days=i) for i in range(7) if a.covers(plan.start + dt.timedelta(days=i))
    ]
