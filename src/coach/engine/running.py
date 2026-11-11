"""Return-to-running ramp and weekly volume rules."""

from dataclasses import dataclass


@dataclass
class RampRules:
    start_miles: tuple[float, float] = (10.0, 12.0)
    max_increase_pct: float = 10.0
    hold_every: int = 4
    deload_factor: float = 0.7


def allowed_increase_cap(trailing: list[float], rules: RampRules) -> float:
    """Max miles for next week: <= +10% over the trailing 3 normal weeks, never below the ramp start."""
    recent = [m for m in trailing[-3:] if m is not None]
    floor = rules.start_miles[0]
    if not recent:
        return rules.start_miles[1]
    avg = sum(recent) / len(recent)
    return max(floor, round(avg * (1 + rules.max_increase_pct / 100), 1))


def ramp_targets(
    n_weeks: int,
    week_types: list[str],
    start: float,
    cap: float,
    rules: RampRules,
    trailing: list[float] | None = None,
) -> list[float]:
    """Outline mileage targets: +<=10% per normal week vs trailing avg, hold flat every 4th, cut on deloads."""
    history = list(trailing or [])
    out: list[float] = []
    current = start
    normal_count = 0
    for i in range(n_weeks):
        wt = week_types[i]
        if wt == "competition":
            out.append(round(current * 0.8, 1))
            continue
        if wt in {"deload", "transition", "taper", "reset"}:
            factor = rules.deload_factor if wt != "taper" else 0.75
            out.append(round(current * factor, 1))
            continue
        normal_count += 1
        if i == 0 and not history:
            target = start
        elif normal_count % rules.hold_every == 0:
            target = current
        else:
            target = min(cap, allowed_increase_cap(history, rules), round(current * 1.08, 1))
            target = max(target, current) if current <= cap else cap
        current = round(min(target, cap), 1)
        out.append(current)
        history.append(current)
    return out


def long_run_fraction_ok(long_run: float, weekly: float, th) -> tuple[bool, float]:
    limit = (
        th.long_run_max_fraction
        if weekly >= th.long_run_rule_min_weekly_miles
        else th.long_run_max_fraction_low_volume
    )
    if weekly <= 0:
        return True, limit
    return long_run / weekly <= limit + 1e-6, limit
