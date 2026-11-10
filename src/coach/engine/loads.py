"""Training loads: e1RM, target loads from RIR, rounding to available implements, progression."""

import datetime as dt
from dataclasses import dataclass

from coach.engine.units import kg_to_lb, lb_to_kg
from coach.models import Exercise, SessionRecord


def e1rm(weight_kg: float, reps: int, rir: float = 0.0) -> float:
    """Epley with reps-in-reserve: a 5 @ 2 RIR counts as a 7-rep effort."""
    effective = reps + max(0.0, rir)
    if effective <= 1:
        return weight_kg
    return weight_kg * (1 + effective / 30.0)


def load_for(e1rm_kg: float, reps: int, rir: float) -> float:
    """Inverse Epley: load that leaves `rir` in the tank for `reps`."""
    return e1rm_kg / (1 + (reps + rir) / 30.0)


@dataclass
class Rounded:
    load_kg: float | None
    load_lb: float | None
    note: str


def round_load(target_kg: float, implement: str, loading: dict) -> Rounded:
    """Round to what the gym actually has (lb plates, 1.25 lb fractional per side, DB 5 lb steps, KB sizes)."""
    lb = kg_to_lb(target_kg)
    if implement in {"barbell", "trap_bar", "open_trap_bar", "safety_squat_bar", "smith_machine", "landmine"}:
        spec = loading.get(implement, loading["barbell"])
        bar = float(spec["bar_lb"])
        step = 2 * float(spec["smallest_step_lb_per_side"])
        plates = max(0.0, lb - bar)
        rounded = bar + round(plates / step) * step
        note = f"{rounded:g} lb" + (" on the sleeve" if implement == "landmine" else "")
        return Rounded(round(lb_to_kg(rounded), 1), rounded, note)
    if implement == "dumbbell":
        spec = loading["dumbbells_lb"]
        r = min(spec["max"], max(spec["min"], round(lb / spec["step"]) * spec["step"]))
        note = f"{r:g} lb DBs" + (" (rack max)" if lb > spec["max"] + spec["step"] / 2 else "")
        return Rounded(round(lb_to_kg(r), 1), float(r), note)
    if implement == "kettlebell":
        sizes = sorted(loading["kettlebells_lb"])
        if lb > sizes[-1] + 5:
            return Rounded(None, None, f"needs > {sizes[-1]} lb: swap to dumbbells")
        r = min(sizes, key=lambda s: abs(s - lb))
        return Rounded(round(lb_to_kg(r), 1), float(r), f"{r} lb KB")
    return Rounded(None, None, "by RIR (start from last used weight in Hevy)")


def kb_for_effort(level: str, loading: dict) -> Rounded:
    sizes = sorted(loading["kettlebells_lb"])
    idx = {"light": 0, "moderate": 1, "heavy": 2, "max": len(sizes) - 1}.get(level, 1)
    lb = sizes[min(idx, len(sizes) - 1)]
    return Rounded(round(lb_to_kg(lb), 1), float(lb), f"{lb} lb KB")


def best_recent_e1rm(
    history: list[SessionRecord], exercise_id: str, today: dt.date, weeks: int = 6
) -> float | None:
    since = today - dt.timedelta(weeks=weeks)
    best = None
    for s in history:
        if not (since <= s.date < today):
            continue
        for st in s.sets:
            if st.exercise_id != exercise_id or st.set_type == "warmup" or not st.weight_kg or not st.reps:
                continue
            v = e1rm(st.weight_kg, st.reps, st.rir or 0.0)
            best = v if best is None else max(best, v)
    return best


def current_e1rm(
    history: list[SessionRecord],
    exercise_id: str,
    today: dt.date,
    recent_days: int = 21,
    layoff_factor: float = 0.95,
) -> tuple[float | None, str]:
    """What the athlete can do now, not their best ever: the top set of the most recent exposure within
    `recent_days`; after a longer gap, the best of the last 8 weeks reduced by `layoff_factor` (detraining)."""
    sessions = sorted((s for s in history if s.date < today), key=lambda s: s.date, reverse=True)
    for s in sessions:
        work = [
            st
            for st in s.sets
            if st.exercise_id == exercise_id and st.set_type != "warmup" and st.weight_kg and st.reps
        ]
        if not work:
            continue
        top = max(e1rm(st.weight_kg, st.reps, st.rir or 0.0) for st in work)  # type: ignore[arg-type]
        if (today - s.date).days <= recent_days:
            return top, f"latest exposure {s.date}"
        break
    best = best_recent_e1rm(history, exercise_id, today, weeks=8)
    if best is None:
        return None, "no history"
    return best * layoff_factor, f"best of 8 weeks x {layoff_factor:g} (no exposure in {recent_days} days)"


def ramp_sets(
    work_kg: float, implement: str, loading: dict, reps: int
) -> list[tuple[int, float, float | None]]:
    """Warm-up ramp to a working weight: (reps, load_kg, load_lb). Empty for light loads or unloadable implements."""
    out: list[tuple[int, float, float | None]] = []
    for pct, r in ((0.5, 5), (0.7, 3), (0.85, 1)):
        rr = round_load(work_kg * pct, implement, loading)
        if rr.load_kg is None or rr.load_kg >= work_kg:
            continue
        if out and rr.load_kg <= out[-1][1]:
            continue
        out.append((min(r, reps), rr.load_kg, rr.load_lb))
    return out


def last_used(history: list[SessionRecord], exercise_id: str, today: dt.date) -> float | None:
    for s in sorted(history, key=lambda r: r.date, reverse=True):
        if s.date >= today:
            continue
        work = [
            st for st in s.sets if st.exercise_id == exercise_id and st.set_type != "warmup" and st.weight_kg
        ]
        if work:
            return max(st.weight_kg for st in work)  # type: ignore[type-var]
    return None


@dataclass
class ProgressionDecision:
    factor: float
    reason: str


def progression(
    history: list[SessionRecord], exercise_id: str, target_reps: int, target_rir: float, today: dt.date
) -> ProgressionDecision:
    """Add load when all target reps were hit at >= target RIR last time; hold/reduce after two misses."""
    sessions = sorted(
        (s for s in history if s.date < today and any(st.exercise_id == exercise_id for st in s.sets)),
        key=lambda s: s.date,
    )
    if not sessions:
        return ProgressionDecision(1.0, "no history: load from e1RM")

    def hit(s: SessionRecord) -> bool:
        work = [st for st in s.sets if st.exercise_id == exercise_id and st.set_type != "warmup"]
        return bool(work) and all(
            (st.reps or 0) >= target_reps and (st.rir if st.rir is not None else 0) >= target_rir - 0.5
            for st in work
        )

    last = sessions[-1]
    if hit(last):
        return ProgressionDecision(1.025, "all reps hit at target RIR last time: +2.5%")
    if len(sessions) >= 2 and not hit(sessions[-2]):
        return ProgressionDecision(0.95, "missed targets two sessions running: -5%")
    return ProgressionDecision(1.0, "missed targets once: hold")


def apply_eccentric_rule(load_kg: float) -> float:
    """Pain rule after a next-morning stiffness rise: -15% load, 3 s eccentric for 2 weeks."""
    return load_kg * 0.85


def implement_for(ex: Exercise) -> str:
    return ex.implement
