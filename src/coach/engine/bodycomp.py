"""Trend weight and body fat: exponentially smoothed daily weigh-ins (DECISIONS 86).

Scale readings swing 1-2 kg day to day with water, glycogen and food in the gut, so goals, calorie phases and
reviews use a smoothed trend instead of raw values or plain averages. Each reading moves the trend by ALPHA
(10% per day, the classic "Hacker's Diet" trend weight); a gap of n days without a reading counts as n steps, so
one reading after a week away moves the trend more than one the day after the last.
"""

import datetime as dt
from dataclasses import dataclass

ALPHA = 0.10  # per-day smoothing: ~10-day effective window
RATE_WINDOW_DAYS = 14  # weekly rate = trend change over the last 14 days


@dataclass(frozen=True)
class Trend:
    value: float  # current trend value
    day: dt.date  # date of the last reading
    readings: int
    rate_per_week: float | None  # change per week over RATE_WINDOW_DAYS (None until enough history)


def ewma_series(readings: list[tuple[dt.date, float]], alpha: float = ALPHA) -> list[tuple[dt.date, float]]:
    """Trend value after each reading (readings in any order; duplicates on a day are averaged)."""
    by_day: dict[dt.date, list[float]] = {}
    for d, v in readings:
        by_day.setdefault(d, []).append(v)
    out: list[tuple[dt.date, float]] = []
    trend: float | None = None
    last: dt.date | None = None
    for d in sorted(by_day):
        v = sum(by_day[d]) / len(by_day[d])
        if trend is None or last is None:
            trend = v
        else:
            a = 1 - (1 - alpha) ** max((d - last).days, 1)  # a gap of n days = n smoothing steps
            trend += a * (v - trend)
        last = d
        out.append((d, trend))
    return out


def trend(readings: list[tuple[dt.date, float]], alpha: float = ALPHA) -> Trend | None:
    series = ewma_series(readings, alpha)
    if not series:
        return None
    end_day, end = series[-1]
    start = [v for d, v in series if d <= end_day - dt.timedelta(days=RATE_WINDOW_DAYS)]
    rate = None
    if start and len(series) >= 5:
        first_day = max(d for d, _ in series if d <= end_day - dt.timedelta(days=RATE_WINDOW_DAYS))
        weeks = (end_day - first_day).days / 7
        rate = round((end - start[-1]) / weeks, 2) if weeks > 0 else None
    return Trend(value=round(end, 2), day=end_day, readings=len(series), rate_per_week=rate)
