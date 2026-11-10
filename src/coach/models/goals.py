"""Long-term goal tracking and per-race targets (athlete/data: goal_progress, race_targets)."""

import datetime as dt
from typing import Literal

from pydantic import Field

from coach.models.common import Model


class GoalCheck(Model):
    """One feasibility check of a long-term goal (written at every transition week, or on demand)."""

    date: dt.date
    event_date: dt.date
    qualify_by: dt.date
    age_on_event: int
    standard_s: int | None  # None: no standard for this age in the config
    required_s: int | None  # standard minus margin
    required_threshold_s_per_mi: float | None
    current_threshold_s_per_mi: float | None
    threshold_source: str = ""
    predicted_marathon_s: int | None = None  # what current threshold pace supports (Riegel)
    rate_pct_per_year: float | None = None  # threshold-pace improvement used for the projection
    rate_basis: str = ""
    projected_date: dt.date | None = None  # when threshold pace reaches the requirement at that rate
    deadline: dt.date | None = None  # the last planned marathon that counts (or qualify_by)
    status: Literal["achieved", "on_track", "behind", "unknown"]
    note: str = ""


class GoalProgress(Model):
    goal_id: str
    checks: list[GoalCheck] = Field(default_factory=list)

    @property
    def latest(self) -> GoalCheck | None:
        return self.checks[-1] if self.checks else None


class RaceTarget(Model):
    """The coach's proposed finish time for one race, set from test results; needs the athlete's approval."""

    race_id: str
    set_on: dt.date
    target_time: str  # H:MM:SS
    predicted_s: int  # fitness-supported time projected to race day
    basis: str  # where the prediction came from
    status: Literal["pending", "approved"] = "pending"
    rationale: str = ""
