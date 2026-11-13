"""`coach push`: the only thing that writes to Hevy / Intervals.icu. It always re-validates first and refuses
invalid plans, no matter who calls it. Dry-run unless config/coach.yaml push.enabled is true."""

import datetime as dt
from typing import Any

from coach.coaching.context import Context
from coach.engine.paces import PACE_FACTORS
from coach.engine.units import fmt_pace
from coach.engine.validator import Violation, validate_session, validate_week
from coach.integrations.base import Sources
from coach.models import Session, WeekPlan

RUN_TYPES = {"run_easy", "run_long", "run_quality", "race", "test"}


METCON_TITLE = "Metcon"
EQUIPMENT = {
    "barbell": "barbell",
    "safety_squat_bar": "barbell",
    "trap_bar": "barbell",
    "dumbbell": "dumbbell",
    "kettlebell": "kettlebell",
    "machine": "machine",
    "cable": "machine",
    "band": "resistance_band",
}
MUSCLE = {"quads": "quadriceps", "core": "abdominals", "back": "upper_back"}


class TemplateResolver:
    """Hevy needs an exercise_template_id per exercise. Titles come from the library (`hevy_title`, else the name);
    missing ones become custom exercises on first use only (free accounts allow 7). Dry runs only report."""

    def __init__(self, hevy=None, read_only: bool = False):
        self.hevy = hevy
        self.read_only = read_only  # dry run: look titles up in the catalog, create nothing
        self.catalog: dict[str, str] | None = None
        self.created: list[str] = []
        self.would_create: list[str] = []

    def _ids(self) -> dict[str, str]:
        if self.catalog is None:
            self.catalog = self.hevy.template_ids() if self.hevy else {}
        return self.catalog

    def resolve(self, title: str, exercise_type: str, equipment: str, muscle: str) -> str | None:
        tid = self._ids().get(title.lower())
        if tid:
            return tid
        if self.hevy is None or self.read_only:
            if title not in self.would_create:
                self.would_create.append(title)
            return None
        tid = self.hevy.create_template(title, exercise_type, equipment, muscle)
        self._ids()[title.lower()] = tid
        self.created.append(title)
        return tid


# A test's scoring decides how its exercise must be logged (a broad jump is a distance, a hold a duration).
SCORING_TYPE = {"best_of": "short_distance_weight", "max_hold": "duration", "max_reps": "reps_only"}


def _custom_spec(ex, it, tests=None) -> tuple[str, str, str]:
    scored = next(
        (
            SCORING_TYPE[t.scoring]
            for t in (tests or {}).values()
            if t.session.get("exercise") == ex.id and t.scoring in SCORING_TYPE
        ),
        None,
    )
    if scored:
        kind = scored
    elif it.duration_s is not None:
        kind = "duration"
    elif it.distance_m is not None:
        kind = "short_distance_weight"
    elif ex.load_mode == "bodyweight":
        kind = "reps_only"
    else:
        kind = "weight_reps"
    equipment = EQUIPMENT.get(ex.implement or "", "none" if ex.load_mode == "bodyweight" else "other")
    first = (ex.muscles or ["other"])[0]
    muscle = "lower_back" if first == "back" and "isometric" in ex.tags else MUSCLE.get(first, first)
    return kind, equipment, muscle


class PushRefused(Exception):
    def __init__(self, violations: list[Violation]):
        super().__init__("push refused: plan fails validation")
        self.violations = violations


def hevy_routine(s: Session, ctx: Context, resolver: TemplateResolver | None = None) -> dict | None:
    lib = ctx.cfg.library
    resolver = resolver or TemplateResolver()
    exercises: list[dict[str, Any]] = []
    for b in s.blocks:
        if b.metcon is not None:
            mc = b.metcon
            moves = "; ".join(
                f"{getattr(lib.get(m.exercise_id), 'name', m.exercise_id)} "
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
                    "exercise_template_id": resolver.resolve(METCON_TITLE, "duration", "other", "full_body"),
                    "notes": f"METCON: {mc.name}. {mc.format.upper()} {mc.time_cap_min:g} min cap. {moves}. Stimulus: {mc.stimulus}. Scaling: {mc.scaling}. "
                    "Log your score in the workout notes (e.g. 'score 5+7 rpe 8').",
                    "sets": [{"type": "normal", "duration_seconds": int(mc.time_cap_min * 60)}],
                }
            )
            continue
        for it in b.items:
            ex = lib.get(it.exercise_id)
            if ex is None or b.kind == "cooldown" and ex.id == "easy_cooldown":
                continue
            sets: list[dict[str, Any]] = [
                {"type": "warmup", "weight_kg": r.load_kg, "reps": r.reps} for r in it.ramp
            ]
            for _ in range(it.sets):
                st: dict = {
                    "type": "warmup" if b.kind in {"warmup", "cooldown"} else "normal"
                }  # Hevy has no cooldown type
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
            title = ex.hevy_title or ex.name
            if title.lower() in {"warm up", "stretching"} and ex.name.lower() != title.lower():
                note = f"{ex.name}" + (f" | {note}" if note else "")  # generic Hevy exercise: name the drill
            exercises.append(
                {
                    "exercise_template_id": ex.hevy_template_id
                    or resolver.resolve(title, *_custom_spec(ex, it, ctx.cfg.tests.tests)),
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


def _mmss(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def _pace_target(seg) -> str:
    """Absolute pace from the coach's own zones ('9:46-10:48/mi Pace'), so the watch target doesn't depend on a
    threshold pace being set in Intervals.icu (seen unset live 2026-11-12); % of threshold only as a fallback."""
    if seg.pace_s_per_mi:
        fast, slow = sorted(seg.pace_s_per_mi)
        return f"{_mmss(fast)}-{_mmss(slow)}/mi Pace"
    lo, hi = PACE_FACTORS[seg.zone]
    return f"{round(100 / hi)}-{round(100 / lo)}% Pace"


def intervals_event(s: Session, ctx: Context) -> dict | None:
    segs = s.run_segments()
    if not any(seg.modality == "run" for seg in segs):
        return None
    lines = []
    for seg in segs:
        if seg.modality != "run":
            continue
        size = f"{seg.distance_mi:g}mi" if seg.distance_mi else f"{seg.duration_min:g}m"
        prefix = f"{seg.reps}x\n" if seg.reps > 1 else ""
        rec = f"\n- {seg.recovery_min:g}m 60-70% Pace" if seg.recovery_min and seg.reps > 1 else ""
        lines.append(f"{prefix}- {size} {_pace_target(seg)} {seg.label}{rec}")
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
        "description": "\n".join(lines)
        + ("\n\n" + "; ".join(paces) if paces else "")
        + "".join(f"\n\n{b.notes}" for b in s.blocks if b.kind == "test" and b.notes)
        + f"\n\n{s.intent}",
        "external_id": f"coach-{s.id}",
        "moving_time": s.expected_minutes * 60,
    }


def _push_sessions(sessions: list[Session], ctx: Context, sources: Sources | None, dry_run: bool) -> dict:
    ids = ctx.state.get("push_ids") or {}
    out: dict = {"dry_run": dry_run, "hevy": [], "intervals": []}
    resolver = TemplateResolver(sources.hevy if sources else None, read_only=dry_run)
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
            r = hevy_routine(s, ctx, resolver)
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
    if resolver.would_create:
        out["hevy_custom_exercises_needed"] = resolver.would_create
    if resolver.created:
        out["hevy_custom_exercises_created"] = resolver.created
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
