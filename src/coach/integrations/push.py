"""`coach push`: the only thing that writes to Hevy / Intervals.icu. It always re-validates first and refuses
invalid plans, no matter who calls it. Dry-run unless config/coach.yaml push.enabled is true."""

import datetime as dt

from coach.coaching.context import Context
from coach.engine.paces import PACE_FACTORS
from coach.engine.units import fmt_pace
from coach.engine.validator import Violation, validate_session, validate_week
from coach.integrations.base import Sources
from coach.models import Session, WeekPlan

RUN_TYPES = {"run_easy", "run_long", "run_quality", "race", "test"}


class PushRefused(Exception):
    def __init__(self, violations: list[Violation]):
        super().__init__("push refused: plan fails validation")
        self.violations = violations


def hevy_routine(s: Session, ctx: Context) -> dict | None:
    lib = ctx.cfg.library
    exercises = []
    for b in s.blocks:
        if b.metcon is not None:
            mc = b.metcon
            moves = "; ".join(
                f"{lib.get(m.exercise_id).name if lib.get(m.exercise_id) else m.exercise_id} "
                + " ".join(
                    x
                    for x in [
                        f"{m.reps} reps" if m.reps else "",
                        f"{m.calories} cal" if m.calories else "",
                        f"{m.distance_m} m" if m.distance_m else "",
                        m.load_note or "",
                    ]
                    if x
                )
                for m in mc.movements
            )
            exercises.append(
                {
                    "exercise_template_id": None,
                    "title": f"METCON: {mc.name}",
                    "notes": f"{mc.format.upper()} {mc.time_cap_min:g} min cap. {moves}. Stimulus: {mc.stimulus}. Scaling: {mc.scaling}. "
                    "Log your score in the workout notes (e.g. 'score 5+7 rpe 8').",
                    "sets": [{"type": "normal", "duration_seconds": int(mc.time_cap_min * 60)}],
                }
            )
            continue
        for it in b.items:
            ex = lib.get(it.exercise_id)
            if ex is None or b.kind == "cooldown" and ex.id == "easy_cooldown":
                continue
            sets = []
            for _ in range(it.sets):
                st: dict = {"type": "warmup" if b.kind == "warmup" else "normal"}
                if it.load_kg is not None:
                    st["weight_kg"] = it.load_kg
                if it.reps is not None:
                    st["reps"] = it.reps
                if it.duration_s is not None:
                    st["duration_seconds"] = it.duration_s
                if it.distance_m is not None:
                    st["distance_meters"] = it.distance_m
                sets.append(st)
            note = " | ".join(
                x
                for x in [
                    f"{it.rir:g} RIR" if it.rir is not None else "",
                    it.load_note or "",
                    it.tempo and f"tempo {it.tempo}",
                    "per side" if it.per_side else "",
                    it.notes or "",
                ]
                if x
            )
            exercises.append(
                {
                    "exercise_template_id": ex.hevy_template_id,
                    "title": ex.hevy_title or ex.name,
                    "rest_seconds": it.rest_s,
                    "notes": note,
                    "sets": sets,
                }
            )
    if not exercises:
        return None
    return {
        "title": f"{s.date:%a %b %d}: {s.title}",
        "folder_id": None,
        "notes": f"{s.intent} (~{s.expected_minutes} min). Check-in tag in notes: back X shoulder Y knee Z rpe N",
        "exercises": exercises,
    }


def intervals_event(s: Session, ctx: Context) -> dict | None:
    segs = s.run_segments()
    if not any(seg.modality == "run" for seg in segs):
        return None
    lines = []
    for seg in segs:
        if seg.modality != "run":
            continue
        lo, hi = PACE_FACTORS[seg.zone]
        pct = (round(100 / hi), round(100 / lo))  # % of threshold pace (speed)
        size = f"{seg.distance_mi:g}mi" if seg.distance_mi else f"{seg.duration_min:g}m"
        prefix = f"{seg.reps}x\n" if seg.reps > 1 else ""
        rec = f"\n- {seg.recovery_min:g}m 60-70% Pace" if seg.recovery_min and seg.reps > 1 else ""
        lines.append(f"{prefix}- {size} {pct[0]}-{pct[1]}% Pace {seg.label}{rec}")
    paces = [
        f"{seg.label}: {fmt_pace(seg.pace_s_per_mi[0])}-{fmt_pace(seg.pace_s_per_mi[1])}"
        for seg in segs
        if seg.pace_s_per_mi
    ]
    return {
        "category": "WORKOUT",
        "type": "Run",
        "start_date_local": f"{s.date.isoformat()}T{s.start_time}:00",
        "name": s.title,
        "description": "\n".join(lines) + ("\n\n" + "; ".join(paces) if paces else "") + f"\n\n{s.intent}",
        "external_id": f"coach-{s.id}",
        "moving_time": s.expected_minutes * 60,
    }


def _push_sessions(sessions: list[Session], ctx: Context, sources: Sources | None, dry_run: bool) -> dict:
    ids = ctx.state.get("push_ids") or {}
    out: dict = {"dry_run": dry_run, "hevy": [], "intervals": []}
    events = []
    for s in sessions:
        if s.type == "rest":
            continue
        if s.location in {"gym", "travel", "home"} and s.type not in {
            "run_easy",
            "run_long",
            "run_quality",
            "race",
        }:
            r = hevy_routine(s, ctx)
            if r:
                if dry_run or sources is None:
                    out["hevy"].append(
                        {"session": s.id, "routine": r["title"], "exercises": len(r["exercises"])}
                    )
                else:
                    rid = sources.hevy.upsert_routine(r, ids.get(f"hevy:{s.id}"))
                    ids[f"hevy:{s.id}"] = rid
                    out["hevy"].append({"session": s.id, "routine_id": rid})
        e = intervals_event(s, ctx)
        if e:
            events.append(e)
    if events:
        if dry_run or sources is None:
            out["intervals"] = [{"session": e["external_id"], "name": e["name"]} for e in events]
        else:
            out["intervals"] = sources.intervals.upsert_events(events)
    if not dry_run:
        ctx.state.put("push_ids", ids)
    return out


def push_week(plan: WeekPlan, ctx: Context, sources: Sources | None, dry_run: bool | None = None) -> dict:
    violations = validate_week(plan, ctx.validation(plan))
    if violations:
        raise PushRefused(violations)
    if plan.approval == "pending":
        return {"skipped": "plan is pending approval (coach approve <proposal>)"}
    dry = (not ctx.cfg.settings.push.enabled) if dry_run is None else dry_run
    today = ctx.today
    upcoming = [s for s in plan.sessions if s.date >= today]
    return _push_sessions(upcoming, ctx, sources, dry)


def push_day(
    session: Session,
    ctx: Context,
    sources: Sources | None,
    plan: WeekPlan | None = None,
    dry_run: bool | None = None,
) -> dict:
    vctx = ctx.validation(plan)
    week_type = plan.week_type if plan else "training"
    violations = validate_session(session, vctx, week_type, plan)
    if violations:
        raise PushRefused(violations)
    dry = (not ctx.cfg.settings.push.enabled) if dry_run is None else dry_run
    return _push_sessions([session], ctx, sources, dry)


def current_week_only(plan: WeekPlan, today: dt.date) -> bool:
    return plan.start <= today <= plan.end or plan.start == today + dt.timedelta(days=1)
