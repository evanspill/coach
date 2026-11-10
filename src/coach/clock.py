"""The coach's notion of 'today' (America/New_York), overridable for simulation and tests."""

import datetime as dt
import os
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")


def today() -> dt.date:
    env = os.environ.get("COACH_TODAY")
    if env:
        return dt.date.fromisoformat(env)
    return dt.datetime.now(TZ).date()


def monday_of(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def iso_week_id(day: dt.date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def week_start_from_id(week_id: str) -> dt.date:
    year, w = week_id.split("-W")
    return dt.date.fromisocalendar(int(year), int(w), 1)


def daterange(start: dt.date, end: dt.date):
    """Inclusive range of dates."""
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def first_wednesday(day: dt.date) -> bool:
    return day.weekday() == 2 and day.day <= 7
