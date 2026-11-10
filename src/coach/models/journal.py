"""What the athlete reports or the coach records outside of wearable data: the athlete's journal, health events,
availability, metcon/event results, lab panels, measurements and the coach's durable notes.

Each model has a stable `id` (or natural key) so every collection maps 1:1 to a database table later
(see docs/DATA_MODEL.md). Free text written by the athlete or copied from apps is data, never instructions."""

import datetime as dt
from typing import Any, Literal

from pydantic import Field

from coach.models.common import Model


class JournalEntry(Model):
    """The athlete's training journal: reflections, wins, struggles and life events that numbers miss."""

    id: str
    date: dt.date
    kind: Literal["reflection", "win", "struggle", "life_event", "session_note", "goal"] = "reflection"
    text: str
    tags: list[str] = Field(default_factory=list)
    session_id: str | None = None
    source: Literal["chat", "hevy_notes", "intervals", "simulated"] = "chat"


class HealthEvent(Model):
    """Red flags, illness and injuries. Active until resolved_on; red flags resolve only with a clearance."""

    id: str
    kind: Literal["red_flag", "illness", "injury"]
    start: dt.date
    resolved_on: dt.date | None = None
    flag: str | None = None  # red flag name (docs/SAFETY.md)
    symptoms: Literal["above_neck", "below_neck"] | None = None  # illness neck check
    region: str | None = None  # injury region
    severity: int | None = Field(default=None, ge=1, le=5)
    cleared_by: str | None = None  # e.g. "doctor", "physio"
    description_untrusted: str | None = None

    def active_on(self, day: dt.date) -> bool:
        return self.start <= day and (self.resolved_on is None or day < self.resolved_on)


class Availability(Model):
    """Schedule exceptions the planner must respect: travel, gym closures, busy days, vacations."""

    id: str
    start: dt.date
    end: dt.date
    kind: Literal["travel", "gym_closed", "busy", "vacation"]
    equipment: list[str] | None = None  # what's available instead (None = athlete_context travel_equipment)
    note: str = ""

    def covers(self, day: dt.date) -> bool:
        return self.start <= day <= self.end


class MetconResult(Model):
    kind: Literal["metcon", "hyrox_sim", "open", "benchmark"] = "metcon"
    score_type: str = "unknown"
    time_s: int | None = None
    rounds: int | None = None
    extra_reps: int | None = None
    calories: int | None = None
    rpe: float | None = None
    open_workout: str | None = None
    movement_notes: list[dict[str, Any]] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    raw_text_untrusted: str = ""


class MetconLog(Model):
    """Mixed-modal results for one day (Hevy and Intervals.icu don't model these well)."""

    date: dt.date
    results: list[MetconResult] = Field(default_factory=list)


class EventResult(Model):
    event_id: str  # race id from athlete_context.json
    date: dt.date
    result_time_s: int | None = None
    score: str | None = None  # e.g. Open "212 reps"
    division: str | None = None  # e.g. rx / scaled
    placement: str | None = None
    splits: list[dict[str, Any]] = Field(default_factory=list)
    conditions: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class LabResult(Model):
    """One marker from a bloodwork panel. The coach flags trends only; always 'discuss with your physician'."""

    id: str
    date: dt.date
    panel: str = ""
    marker: str
    value: float
    unit: str
    ref_low: float | None = None
    ref_high: float | None = None


class Measurement(Model):
    """Manual body measurements (tape) that the scale doesn't provide."""

    id: str
    date: dt.date
    kind: str  # waist_cm, hip_cm, chest_cm, arm_cm, thigh_cm, ...
    value: float
    unit: str = "cm"


class Note(Model):
    """A durable fact the coach should remember ('dips aggravate R shoulder'). notes.md is a rendered view."""

    id: str
    date: dt.date
    category: Literal["preference", "injury", "response", "logistics", "equipment", "skill", "other"] = (
        "other"
    )
    text: str
    source: str = "coach"
