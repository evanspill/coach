"""replan fallback: reactive deloads, illness (neck check + graded return), travel, missed sessions."""

import datetime as dt

from coach import clock
from coach.context import Context
from coach.engine.deloads import pull_forward
from coach.fallback import design as D
from coach.fallback.plan_block import deload_ranges, targets_for
from coach.fallback.plan_week import finalize, plan_week
from coach.models import BlockOutline, Deviation, Metcon, Session, WeekPlan
from coach.models.plans import Revision
from coach.validator import validate_outline


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
    block_index = ctx.block.index
    for w in new.weeks:
        if w.type in {"deload", "training"} and w.week_index not in comp:
            want = "deload" if w.week_index in new_deloads else "training"
            if want != w.type and w.week_index >= next_week:
                keys, ranges = targets_for(block_index, want)
                prev = ol.week(w.week_index - 1)
                w.type = want  # type: ignore[assignment]
                w.key_sessions = keys
                w.hard_sets = (
                    ranges
                    if want == "training"
                    else deload_ranges(dict(ol.week(1).hard_sets) if ol.week(1) else ranges)
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


def _easy_z2(ctx: Context, day: dt.date, minutes: int) -> Session:
    from coach.models import RunSegment, SessionBlock

    P = D.Picker(ctx, "deload", "gym")
    blk = SessionBlock(
        kind="run",
        title=f"{minutes} min easy Zone 2 (bike or walk-run)",
        run=[RunSegment(label="Easy Z2 bike", zone="Z2", duration_min=minutes, modality="bike")],
    )
    return D.make_session(
        ctx,
        day,
        "return",
        "run_easy",
        "Graded return: easy Z2",
        "Day 2 back: easy aerobic only",
        [D.warmup("full", P), blk, D.cooldown(P)],
    )


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
        free = next((h for h in home_days if h.type in {"recovery", "rest", "run_easy"} and not h.key), None)
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
    from coach.models import SessionBlock

    P = D.Picker(ctx, "training", "travel")
    if (
        original.type in {"run_easy", "run_long", "run_quality", "recovery", "rest"}
        and original.type != "rest"
    ):
        miles = max(2.0, sum(seg.distance_mi or 0 for seg in original.run_segments()) * 0.8)
        return D.make_session(
            ctx,
            day,
            "travel-run",
            "run_easy",
            "Travel run",
            "Easy run wherever you are",
            [D.warmup("run", P), D.run_block("Easy run (explore safely, daylight)", miles), D.cooldown(P)],
            location="travel",
        )
    if original.type == "rest":
        return original
    circuit = SessionBlock(
        kind="hypertrophy",
        title="Hotel-room strength circuit",
        items=D._items(
            D.rx(P.pick("push_up"), 4, 12, 2),
            D.rx(P.pick("bodyweight_split_squat"), 3, 12, 2, per_side=True),
            D.rx(P.pick("single_leg_glute_bridge"), 3, 12, 2, per_side=True),
            D.rx(P.pick("band_row"), 4, 15, 2),
            D.rx(P.pick("band_pull_apart"), 3, 20),
            D.rx(P.pick("dead_bug"), 3, 10),
            D.rx(P.pick("side_plank"), 2, duration_s=30, per_side=True),
        ),
    )
    cond = SessionBlock(
        kind="conditioning",
        title="Bodyweight intervals",
        metcon=Metcon(
            name="Bodyweight EMOM",
            format="emom",
            time_cap_min=10,
            movements=D._items(D.rx(P.pick("burpee", for_metcon=True), 1, 8)),
            stimulus="Moderate, sustainable",
            score_type="none",
        ),
    )
    return D.make_session(
        ctx,
        day,
        "travel",
        "full_body",
        "Travel: bodyweight strength",
        "Keep the habit; no equipment needed",
        [D.warmup("upper", P), circuit, cond, D.cooldown(P)],
        location="travel",
    )


def _fix_back_to_back(ctx: Context, plan: WeekPlan) -> None:
    from coach.engine.sessions import categories
    from coach.validator import FORBIDDEN_BACK_TO_BACK

    ordered = sorted(plan.sessions, key=lambda s: s.date)
    for a, b in zip(ordered, ordered[1:], strict=False):
        ca, cb = categories(a, ctx.cfg.library, ctx.cfg.tests), categories(b, ctx.cfg.library, ctx.cfg.tests)
        if any(x in ca and y in cb for x, y in FORBIDDEN_BACK_TO_BACK):
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
