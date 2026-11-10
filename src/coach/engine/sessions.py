"""Facts about planned sessions: categories, hard sets, pillar doses, mileage, ordering."""

import datetime as dt

from coach.engine.paces import miles_for_segment
from coach.models import Session, WeekPlan
from coach.models.library import ExerciseLibrary, TestBattery

BLOCK_RANK = {
    "warmup": 0,
    "skill": 1,
    "power": 1,
    "strength": 2,
    "hypertrophy": 3,
    "conditioning": 4,
    "run": 4,
    "mobility": 5,
    "cooldown": 6,
}
TEST_RANK = {"power": 1, "strength": 2, "run": 4, "engine": 4, "body": 5}
HARD_RIR = 4.0
QUALITY_ZONES = {"T", "Z5", "Z3"}
DEFAULT_THRESHOLD_PACE = 480


def block_rank(kind: str, test_id: str | None, battery: TestBattery | None) -> int:
    if kind == "test" and test_id and battery and test_id in battery.tests:
        return TEST_RANK[battery.tests[test_id].category]
    return BLOCK_RANK.get(kind, 3)


def session_miles(s: Session, threshold_pace: float = DEFAULT_THRESHOLD_PACE) -> float:
    from coach.engine.paces import PACE_FACTORS

    total = 0.0
    for seg in s.run_segments():
        if seg.modality != "run":
            continue
        lo, hi = PACE_FACTORS[seg.zone]
        pace = threshold_pace * (lo + hi) / 2
        total += miles_for_segment(seg.duration_min, seg.distance_mi, pace, seg.reps)
    return round(total, 2)


def week_miles(plan: WeekPlan, threshold_pace: float = DEFAULT_THRESHOLD_PACE) -> float:
    return round(sum(session_miles(s, threshold_pace) for s in plan.sessions), 1)


def long_run_miles(plan: WeekPlan, threshold_pace: float = DEFAULT_THRESHOLD_PACE) -> float:
    longs = [session_miles(s, threshold_pace) for s in plan.sessions if s.type in {"run_long", "race"}]
    return max(longs, default=0.0)


def hard_sets(plan_or_sessions, library: ExerciseLibrary) -> dict[str, float]:
    sessions = plan_or_sessions.sessions if isinstance(plan_or_sessions, WeekPlan) else plan_or_sessions
    out: dict[str, float] = {}
    for s in sessions:
        for b in s.blocks:
            if b.kind not in {"strength", "hypertrophy", "power", "test"}:
                continue
            for it in b.items:
                if it.rir is None or it.rir > HARD_RIR:
                    continue
                ex = library.get(it.exercise_id)
                if not ex:
                    continue
                for m in ex.muscles:
                    out[m] = out.get(m, 0) + it.sets
    return out


def is_lower_body(s: Session, library: ExerciseLibrary) -> bool:
    if s.type in {"lower", "full_body"}:
        return True
    for b in s.blocks:
        if b.kind in {"strength", "hypertrophy", "power"} or (b.kind == "test" and b.test_id):
            for it in b.items:
                ex = library.get(it.exercise_id)
                if ex and "lower" in ex.tags and ex.has_tag("hinge", "squat", "lunge", "plyo", "sprint"):
                    return True
            if b.kind == "test" and b.test_id in {"hinge_rm", "squat_rm", "broad_jump"}:
                return True
    return False


def has_hard_lower_lifting(s: Session, library: ExerciseLibrary) -> bool:
    for b in s.blocks:
        if b.kind in {"strength", "hypertrophy"}:
            for it in b.items:
                ex = library.get(it.exercise_id)
                if ex and "lower" in ex.tags and ex.has_tag("hinge", "squat", "lunge") and (it.rir or 0) <= 3:
                    return True
        if b.kind == "test" and b.test_id in {"hinge_rm", "squat_rm"}:
            return True
    return False


def categories(s: Session, library: ExerciseLibrary, battery: TestBattery | None = None) -> set[str]:
    """Stress categories used for back-to-back and spacing rules."""
    cats: set[str] = set()
    if s.type in {"rest", "recovery"}:
        return cats
    if s.type in {"run_long"}:
        cats.add("long_run")
    if s.type == "race":
        cats.update({"long_run", "run_quality"})
    for b in s.blocks:
        if b.kind == "test" and b.test_id and battery and b.test_id in battery.tests:
            cat = battery.tests[b.test_id].category
            cats.add(
                {
                    "strength": "lower_heavy" if b.test_id in {"hinge_rm", "squat_rm"} else "upper_heavy",
                    "run": "run_quality",
                    "engine": "glycolytic",
                    "power": "neural",
                    "body": "none",
                }[cat]
            )
        if b.metcon is not None and b.metcon.time_cap_min >= 6:
            cats.add("glycolytic")
        if b.kind == "strength":
            for it in b.items:
                ex = library.get(it.exercise_id)
                if ex and "primary" in ex.tags and (it.rir if it.rir is not None else 9) <= 3:
                    cats.add("lower_heavy" if "lower" in ex.tags else "upper_heavy")
        if b.kind == "hypertrophy" and b.items:
            cats.add("hypertrophy")
        if b.kind == "power":
            cats.add("neural")
        q = sum(
            (
                seg.duration_min
                if seg.duration_min is not None
                else (seg.distance_mi or 0) * DEFAULT_THRESHOLD_PACE / 60
            )
            * seg.reps
            for seg in b.run
            if seg.zone in QUALITY_ZONES
        )
        if q >= 8:
            cats.add("run_quality")
        if any(seg.zone in {"Z1", "Z2", "MP"} and seg.modality != "walk" for seg in b.run):
            cats.add("endurance")
        if any(seg.zone in QUALITY_ZONES for seg in b.run):
            cats.add("endurance")
    if s.type == "hyrox":
        cats.add("glycolytic")
    return cats


def pillar_doses(
    plan: WeekPlan, library: ExerciseLibrary, battery: TestBattery | None = None
) -> dict[str, float]:
    neural = force = glyco = 0
    aerobic_min = 0.0
    for s in plan.sessions:
        if s.type == "rest":
            continue
        cats = categories(s, library, battery)
        if "neural" in cats or any(
            (ex := library.get(it.exercise_id)) and ex.has_tag("plyo", "sprint", "power")
            for b in s.blocks
            if b.kind in {"power", "warmup"}
            for it in b.items
            if b.kind == "power"
            or (library.get(it.exercise_id) and library.get(it.exercise_id).has_tag("plyo"))
        ):
            neural += 1
        if any(
            b.kind in {"strength", "hypertrophy"}
            and any(it.rir is not None and it.rir <= HARD_RIR for it in b.items)
            for b in s.blocks
        ) or cats & {"lower_heavy", "upper_heavy"}:
            force += 1
        if cats & {"glycolytic", "run_quality"}:
            glyco += 1
        for b in s.blocks:
            for seg in b.run:
                if seg.zone in {"Z1", "Z2", "MP", "Z3"} and seg.modality != "walk":
                    if seg.duration_min is not None:
                        aerobic_min += seg.duration_min * seg.reps
                    elif seg.distance_mi is not None:
                        aerobic_min += seg.distance_mi * 10 * seg.reps
    return {"neural": neural, "force": force, "glycolytic": glyco, "aerobic": round(aerobic_min)}


def start_dt(s: Session) -> dt.datetime:
    h, m = (int(x) for x in s.start_time.split(":"))
    return dt.datetime(s.date.year, s.date.month, s.date.day, h, m)
