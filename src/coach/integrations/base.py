"""Abstract interfaces for every external service + the factory that picks mock or live."""

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass

from coach.models import Checkin, DailyMetrics, Gear, SessionRecord


class WhoopSource(ABC):
    """Source of truth for heart rate: recovery, HRV, RHR, sleep, day strain and every workout's HR/strain/zones."""

    name = "whoop"

    @abstractmethod
    def daily(self, start: dt.date, end: dt.date) -> list[DailyMetrics]: ...

    @abstractmethod
    def workouts(self, start: dt.date, end: dt.date) -> list[SessionRecord]: ...


class HevySource(ABC):
    """Lifting log (sets, reps, load, RPE) and routine writes."""

    name = "hevy"

    @abstractmethod
    def workouts(self, start: dt.date, end: dt.date) -> list[SessionRecord]: ...

    @abstractmethod
    def upsert_routine(self, routine: dict, routine_id: str | None = None) -> str: ...


class IntervalsSource(ABC):
    """Runs (+ Running Dynamics), wellness (incl. custom check-in fields), gear, planned events -> Garmin."""

    name = "intervals"

    @abstractmethod
    def activities(self, start: dt.date, end: dt.date) -> list[SessionRecord]: ...

    @abstractmethod
    def wellness(self, start: dt.date, end: dt.date) -> tuple[list[DailyMetrics], list[Checkin]]: ...

    @abstractmethod
    def gear(self) -> list[Gear]: ...

    @abstractmethod
    def upsert_events(self, events: list[dict]) -> list[str]: ...


class WeatherSource(ABC):
    name = "open_meteo"

    @abstractmethod
    def hourly(self, start: dt.date, end: dt.date) -> list[dict]:
        """[{'time': datetime, 'temp_c', 'dew_point_c', 'precip_mm'}]"""


class NutritionSource(ABC):
    name = "nutrition"

    @abstractmethod
    def daily(self, start: dt.date, end: dt.date) -> list[DailyMetrics]: ...

    @abstractmethod
    def weekly_target_kcal(self, week_start: dt.date) -> float | None: ...


@dataclass
class Sources:
    whoop: WhoopSource
    hevy: HevySource
    intervals: IntervalsSource
    weather: WeatherSource
    nutrition: NutritionSource
    mock: bool


def get_sources(mock: bool | None = None, world=None) -> Sources:
    from coach import paths

    use_mock = paths.is_mock() if mock is None else mock
    if use_mock:
        from coach.integrations.mock import MockWorld, mock_sources

        return mock_sources(world or MockWorld.load())
    from coach.integrations.live import live_sources

    return live_sources()
