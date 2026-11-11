"""Mock integrations backed by fixtures in coach/fixtures (raw API shapes run through the real normalizers).

`MockWorld` also lets the simulation's athlete append completed workouts, and records routines/events that
`coach push` would have sent, so the whole loop runs end to end with COACH_MOCK=1.
"""

import copy
import datetime as dt
import json
from dataclasses import dataclass, field

from coach import clock, paths
from coach.config import load_config
from coach.integrations import normalize as N
from coach.integrations.base import (
    HevySource,
    IntervalsSource,
    NutritionSource,
    Sources,
    WeatherSource,
    WhoopSource,
)
from coach.models import Checkin, DailyMetrics, Gear, SessionRecord


def _load(name: str):
    with open(paths.fixtures_dir() / name) as f:
        return json.load(f)


@dataclass
class MockWorld:
    whoop: dict
    hevy: dict
    intervals: dict
    weather: dict
    script: dict
    hide_recovery_for: set[dt.date] = field(default_factory=set)
    routines: dict[str, dict] = field(default_factory=dict)
    events: dict[str, dict] = field(default_factory=dict)
    extra_gear_miles: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "MockWorld":
        script = _load("athlete_script.json")
        return cls(
            whoop=_load("whoop.json"),
            hevy=_load("hevy.json"),
            intervals=_load("intervals.json"),
            weather=_load("open_meteo.json"),
            script=script,
        )

    def copy(self) -> "MockWorld":
        return copy.deepcopy(self)

    @staticmethod
    def now_cutoff() -> dt.date:
        return clock.today()


def _in(day: dt.date, start: dt.date, end: dt.date) -> bool:
    return start <= day <= end


class MockWhoop(WhoopSource):
    def __init__(self, world: MockWorld):
        self.w = world

    def daily(self, start, end):
        today = MockWorld.now_cutoff()
        out = []
        for m in N.whoop_daily(self.w.whoop["recovery"], self.w.whoop["sleep"], self.w.whoop["cycles"]):
            if not _in(m.date, start, min(end, today)):
                continue
            if m.date == today and today in self.w.hide_recovery_for:
                continue  # Whoop hasn't processed last night yet
            if m.date == today:
                m.day_strain = None  # today's cycle is still accruing
            out.append(m)
        return out

    def workouts(self, start, end):
        today = MockWorld.now_cutoff()
        return [
            s
            for s in N.whoop_workouts(self.w.whoop["workouts"])
            if _in(s.date, start, end) and s.date < today
        ]


class MockHevy(HevySource):
    def __init__(self, world: MockWorld):
        self.w = world

    def workouts(self, start, end):
        today = MockWorld.now_cutoff()
        lib = load_config().library
        return [
            s
            for s in N.hevy_workouts(self.w.hevy["workouts"], lib)
            if _in(s.date, start, end) and s.date < today
        ]

    def upsert_routine(self, routine, routine_id=None):
        rid = routine_id or f"mock-routine-{len(self.w.routines) + 1}"
        self.w.routines[rid] = routine
        return rid


class MockIntervals(IntervalsSource):
    def __init__(self, world: MockWorld):
        self.w = world

    def activities(self, start, end):
        today = MockWorld.now_cutoff()
        return [
            a
            for a in N.intervals_activities(self.w.intervals["activities"])
            if _in(a.date, start, end) and a.date < today
        ]

    def wellness(self, start, end) -> tuple[list[DailyMetrics], list[Checkin]]:
        today = MockWorld.now_cutoff()
        metrics, checkins = N.intervals_wellness(self.w.intervals["wellness"])
        # nutrition for a day is complete only after the day ends; check-ins for today are morning entries
        metrics = [m for m in metrics if _in(m.date, start, end) and m.date < today]
        checkins = [c for c in checkins if _in(c.date, start, min(end, today))]
        return metrics, checkins

    def gear(self) -> list[Gear]:
        gear = N.intervals_gear(self.w.intervals["gear"])
        for g in gear:
            g.distance_mi = round(g.distance_mi + self.w.extra_gear_miles.get(g.id, 0.0), 1)
        return gear

    def upsert_events(self, events):
        ids = []
        for e in events:
            eid = e.get("external_id") or f"mock-event-{len(self.w.events) + 1}"
            self.w.events[eid] = e
            ids.append(eid)
        return ids


class MockWeather(WeatherSource):
    def __init__(self, world: MockWorld):
        self.w = world

    def hourly(self, start, end):
        return [r for r in N.open_meteo_hourly(self.w.weather) if start <= r["time"].date() <= end]


class MockNutrition(NutritionSource):
    """Phase 3 route: MacroFactor -> Apple Health -> Intervals.icu wellness. Mock reads the same wellness fixture."""

    def __init__(self, world: MockWorld):
        self.w = world

    def daily(self, start, end):
        metrics, _ = MockIntervals(self.w).wellness(start, end)
        return [m for m in metrics if m.kcal is not None]

    def weekly_target_kcal(self, week_start):
        target = None
        for t in self.w.script.get("macrofactor_targets", []):
            if dt.date.fromisoformat(t["from"]) <= week_start:
                target = t["kcal_per_day"] * 7
        return target


def mock_sources(world: MockWorld) -> Sources:
    return Sources(
        whoop=MockWhoop(world),
        hevy=MockHevy(world),
        intervals=MockIntervals(world),
        weather=MockWeather(world),
        nutrition=MockNutrition(world),
        mock=True,
    )


def add_session_record_raw(world: MockWorld, kind: str, payload: dict) -> None:
    """Used by the simulated athlete to 'complete' workouts."""
    if kind == "hevy":
        world.hevy["workouts"].append(payload)
    elif kind == "whoop":
        world.whoop["workouts"].append(payload)
    elif kind == "intervals":
        world.intervals["activities"].append(payload)
    elif kind == "wellness":
        for w in world.intervals["wellness"]:
            if w["id"] == payload["id"]:
                w.update({k: v for k, v in payload.items() if v is not None})
                return
        world.intervals["wellness"].append(payload)
    else:
        raise ValueError(kind)


__all__ = ["MockWorld", "SessionRecord", "add_session_record_raw", "mock_sources"]
