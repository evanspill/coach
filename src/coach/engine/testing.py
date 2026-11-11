"""Test scheduling (incl. Red-day reschedule) and scoring with variant comparability."""

import datetime as dt
import statistics

from coach.engine.loads import e1rm
from coach.models import TestResult
from coach.models.library import TestBattery


def test_slot(test_id: str, battery: TestBattery) -> str:
    return battery.tests[test_id].slot


def schedule(week_start: dt.date, test_ids: list[str], battery: TestBattery, kind: str) -> dict[str, dt.date]:
    """Day offsets per slot come from config/tests.yaml `schedule` (baseline | transition)."""
    days = battery.schedule[kind]
    return {t: week_start + dt.timedelta(days=days[test_slot(t, battery)]) for t in test_ids}


def lower_is_better(test_id: str, battery: TestBattery) -> bool:
    t = battery.tests.get(test_id)
    return bool(t and t.lower_is_better)


def reschedule_for_red(
    test_id: str,
    scheduled: dict[str, dt.date],
    battery: TestBattery,
    red_day: dt.date,
    today: dt.date,
    window: int = 2,
    blocked: set[dt.date] | None = None,
) -> dt.date | None:
    """Move a test off a Red day to the nearest day within +/- window that is free of other test slots
    and not adjacent to a conflicting slot (run next to engine). Returns None if nothing fits."""
    slot = test_slot(test_id, battery)
    others = {
        d: test_slot(t, battery)
        for t, d in scheduled.items()
        if t != test_id and test_slot(t, battery) != "body"
    }
    taken = {d for d, s in others.items() if s != slot}
    blocked = blocked or set()
    conflict = {("run", "engine"), ("engine", "run")}
    for delta in [1, -1, 2, -2][: 2 * window]:
        cand = red_day + dt.timedelta(days=delta)
        if cand < today or cand in taken or cand in blocked:
            continue
        neighbours = {others.get(cand - dt.timedelta(days=1)), others.get(cand + dt.timedelta(days=1))}
        if any((slot, n) in conflict for n in neighbours if n):
            continue
        return cand
    return None


def score(test_id: str, raw: dict, battery: TestBattery, day: dt.date) -> TestResult:
    t = battery.tests[test_id]
    variant = raw.get("variant") or t.reference_variant
    details: dict = {}
    conditions = dict(raw.get("conditions", {}))
    if t.scoring == "epley_e1rm":
        value = e1rm(raw["weight_kg"], int(raw["reps"]), raw.get("rir", 1.0))
        factor = t.variants.get(variant, 1.0) if variant else 1.0
        comparable = value * factor
        details = {
            "weight_kg": raw["weight_kg"],
            "reps": raw["reps"],
            "rir": raw.get("rir", 1.0),
            "factor": factor,
        }
    elif t.scoring == "best_of":
        value = max(raw["attempts"])
        comparable = value
        details = {"attempts": raw["attempts"]}
    elif t.scoring == "max_reps":
        value = float(raw["reps"] if "reps" in raw else raw["value"])
        comparable = value
    elif t.scoring == "lthr_from_last20":
        lthr = round(raw["last20_avg_hr"])
        pace = raw["last20_pace_s_per_mi"]
        temp_f = conditions.get("temp_f")
        adj = 0.0
        heat = t.model_extra.get("heat_adjustment", {}) if t.model_extra else {}
        if temp_f is not None and temp_f > 60:
            adj = -(temp_f - 60) * heat.get("per_f_above_60", 0.6)
        elif temp_f is not None and temp_f < 40:
            adj = -(40 - temp_f) * heat.get("per_f_below_40", 0.3)
        value = pace
        comparable = pace + adj
        details = {"lthr": lthr, "threshold_pace_s_per_mi": round(pace), "weather_adjust_s": round(adj, 1)}
        variant = raw.get("variant", "outdoor")
    elif t.scoring == "submax_estimate":
        pace = raw["avg_pace_s_per_mi"]
        hr = raw["avg_hr"]
        value = pace / 1.25
        comparable = value
        details = {
            "lthr": round(hr / 0.80),
            "threshold_pace_s_per_mi": round(value),
            "confidence": "low: estimated from a submaximal run",
        }
    elif t.scoring == "cardiac_drift":
        h1, h2 = raw["first_half_hr"], raw["second_half_hr"]
        p1, p2 = raw.get("first_half_pace", 1.0), raw.get("second_half_pace", 1.0)
        value = ((h2 / p1 * p2) / h1 - 1) * 100 if p1 and p2 else (h2 / h1 - 1) * 100
        comparable = value
        details = {"pass": value < t.model_extra.get("pass_below", 5.0) if t.model_extra else value < 5}
    elif t.scoring == "row_watts":
        secs = raw["time_s"]
        pace_per_m = secs / 2000
        watts = 2.80 / pace_per_m**3
        value = secs
        comparable = secs
        details = {"watts": round(watts), "split_500m_s": round(secs / 4, 1)}
        if "bodyweight_kg" in raw:
            details["watts_per_kg"] = round(watts / raw["bodyweight_kg"], 2)
    elif t.scoring == "time":
        value = raw["time_s"]
        comparable = value
    elif t.scoring == "seven_day_avg":
        weights = raw["weights_kg"]
        value = statistics.fmean(weights)
        comparable = value
        details = {"n": len(weights)}
        if raw.get("body_fat_pct"):
            details["body_fat_pct"] = round(statistics.fmean(raw["body_fat_pct"]), 1)
        if raw.get("waist_cm"):
            details["waist_cm"] = raw["waist_cm"]
    else:
        raise ValueError(f"unknown scoring '{t.scoring}' for {test_id}")
    return TestResult(
        test_id=test_id,
        date=day,
        variant=variant,
        value=round(value, 2),
        unit=t.unit,
        comparable_value=round(comparable, 2) if comparable is not None else None,
        details=details,
        conditions=conditions,
    )


def change_pct(before: TestResult, after: TestResult, lower_is_better: bool = False) -> float:  # noqa: FBT001
    a = before.comparable_value if before.comparable_value is not None else before.value
    b = after.comparable_value if after.comparable_value is not None else after.value
    if not a:
        return 0.0
    pct = (b - a) / a * 100
    return round(-pct if lower_is_better else pct, 2)
