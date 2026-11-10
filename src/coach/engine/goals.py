"""Long-term goal feasibility: qualifying standard for the athlete's age, the threshold pace that standard needs,
and when the athlete's threshold-pace trend gets there. Pure functions, no I/O.

Race equivalence uses Riegel's formula T2 = T1 x (D2 / D1) ** k, treating threshold pace as roughly a one-hour race
pace. With k = 1.06 a 7:00/mi threshold predicts 3:16 (the repo's benchmark). Riegel substantially underestimates
recreational runners' marathon times (10+ min for half the runners in Vickers & Vertosick 2016, PMC5000509), so
predictions carry `running.marathon_prediction.no_marathon_penalty_s` until the athlete has a marathon result.
"""

import datetime as dt
import math

from coach.models.goals import GoalCheck
from coach.models.profile import Identity, LongTermGoal, Race

MARATHON_MI = 26.2188
WEEKS_PER_YEAR = 52.18


def hms(t: str) -> int:
    parts = [int(x) for x in t.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def fmt_hms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def marathon_from_threshold(threshold_s_per_mi: float, k: float = 1.06, penalty_s: int = 0) -> int:
    """Predicted marathon time (s) from threshold pace, treating threshold as ~1-hour race pace, plus a penalty
    (Riegel is optimistic for recreational marathoners)."""
    hour_miles = 3600 / threshold_s_per_mi
    return round(3600 * (MARATHON_MI / hour_miles) ** k) + penalty_s


def threshold_for_marathon(marathon_s: float, k: float = 1.06, penalty_s: int = 0) -> float:
    """Threshold pace (s/mi) that supports a marathon time (inverse of marathon_from_threshold)."""
    hour_miles = MARATHON_MI / ((marathon_s - penalty_s) / 3600) ** (1 / k)
    return 3600 / hour_miles


def standard_for(goal: LongTermGoal, age: int) -> int | None:
    if goal.target_time:
        return hms(goal.target_time)
    for st in goal.standards:
        if st.min_age <= age <= st.max_age:
            return hms(st.time)
    return None


def gain_rate(
    history: list[tuple[dt.date, float]], assumed_pct: float, max_pct: float, min_weeks: int = 8
) -> tuple[float, str]:
    """Threshold-pace improvement in % per year (positive = getting faster). Uses the observed trend once two tests
    are at least `min_weeks` apart (capped at `max_pct`: early gains don't continue at the same rate); else the
    assumed rate."""
    pts = sorted(history)
    if len(pts) >= 2 and (pts[-1][0] - pts[0][0]).days >= min_weeks * 7:
        xs = [(d - pts[0][0]).days / 7 for d, _ in pts]
        ys = [math.log(p) for _, p in pts]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sum((x - mx) ** 2 for x in xs)
        observed = (1 - math.exp(slope * WEEKS_PER_YEAR)) * 100
        basis = f"observed trend over {len(pts)} tests ({observed:+.1f}%/yr)"
        if observed > max_pct:
            return max_pct, basis + f", capped at {max_pct:g}%/yr"
        return round(observed, 1), basis
    return assumed_pct, f"assumed {assumed_pct:g}%/yr (fewer than two run tests {min_weeks}+ weeks apart)"


def project(current: float, required: float, rate_pct: float, today: dt.date) -> dt.date | None:
    """Date the threshold pace reaches `required` at a constant % improvement per year; None if never."""
    if current <= required:
        return today
    if rate_pct <= 0:
        return None
    weekly = 1 - (1 - rate_pct / 100) ** (1 / WEEKS_PER_YEAR)
    weeks = math.log(required / current) / math.log(1 - weekly)
    return today + dt.timedelta(weeks=math.ceil(weeks))


def threshold_on(current: float, rate_pct: float, today: dt.date, day: dt.date) -> float:
    """Projected threshold pace on a future day (no faster improvement than the rate allows)."""
    years = max(0, (day - today).days) / 365.25
    return current * (1 - max(rate_pct, 0) / 100) ** years


def deadline(goal: LongTermGoal, races: list[Race], today: dt.date) -> dt.date:
    """The last planned marathon that still counts, else the end of the qualifying window."""
    counting = [r.date for r in races if r.kind == "marathon" and today <= r.date <= goal.qualify_by]
    return max(counting) if counting else goal.qualify_by


def check(
    goal: LongTermGoal,
    identity: Identity,
    races: list[Race],
    history: list[tuple[dt.date, float]],
    current: tuple[float, str] | None,
    today: dt.date,
    k: float = 1.06,
    penalty_s: int = 0,
) -> GoalCheck:
    age = identity.age_on(goal.event_date)
    std = standard_for(goal, age)
    base = {
        "date": today,
        "event_date": goal.event_date,
        "qualify_by": goal.qualify_by,
        "age_on_event": age,
        "standard_s": std,
    }
    if std is None:
        return GoalCheck(
            **base,
            required_s=None,
            required_threshold_s_per_mi=None,
            current_threshold_s_per_mi=None,
            status="unknown",
            note=f"no standard for age {age} in the config: add it (from {goal.source or 'the event'})",
        )
    required = std - goal.margin_s
    need = round(threshold_for_marathon(required, k, penalty_s), 1)
    end = deadline(goal, races, today)
    if current is None:
        return GoalCheck(
            **base,
            required_s=required,
            required_threshold_s_per_mi=need,
            current_threshold_s_per_mi=None,
            deadline=end,
            status="unknown",
            note="no measured threshold pace yet: the baseline run test sets it",
        )
    pace, source = current
    rate, basis = gain_rate(history, goal.assumed_gain_pct_per_year, goal.max_gain_pct_per_year)
    when = project(pace, need, rate, today)
    predicted = marathon_from_threshold(pace, k, penalty_s)
    if pace <= need:
        status, note = (
            "achieved",
            "current fitness supports the time: it now has to be run in a counting race",
        )
    elif when is not None and when <= end:
        status, note = "on_track", ""
    else:
        status = "behind"
        note = (
            "at this rate the required fitness arrives after the last counting race"
            if when
            else "threshold pace isn't improving: no projection"
        )
    return GoalCheck(
        **base,
        required_s=required,
        required_threshold_s_per_mi=need,
        current_threshold_s_per_mi=round(pace, 1),
        threshold_source=source,
        predicted_marathon_s=predicted,
        rate_pct_per_year=rate,
        rate_basis=basis,
        projected_date=when,
        deadline=end,
        status=status,
        note=note,
    )


def same_slot_next_year(day: dt.date) -> dt.date:
    """Same month, weekday and week-of-month one year on (e.g. the third Monday of April)."""
    nth = (day.day - 1) // 7
    first = dt.date(day.year + 1, day.month, 1)
    offset = (day.weekday() - first.weekday()) % 7
    return first + dt.timedelta(days=offset + 7 * nth)
