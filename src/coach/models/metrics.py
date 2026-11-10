"""Normalized data (never raw API dumps). Stored as JSON lines in state/metrics/YYYY-MM.jsonl."""

import datetime as dt
from typing import Literal

from pydantic import Field, field_validator

from coach.models.common import Model


class DailyMetrics(Model):
    date: dt.date
    recovery_score: float | None = None
    hrv_rmssd_ms: float | None = None
    rhr_bpm: float | None = None
    sleep_hours: float | None = None
    sleep_performance: float | None = None
    day_strain: float | None = None
    weight_kg: float | None = None
    body_fat_pct: float | None = None
    kcal: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    kcal_target_weekly: float | None = None
    ctl: float | None = None
    atl: float | None = None
    sources: list[str] = Field(default_factory=list)


class SetRecord(Model):
    exercise_id: str | None
    exercise_name: str
    set_type: Literal["normal", "warmup", "failure", "dropset"] = "normal"
    weight_kg: float | None = None
    reps: int | None = None
    rpe: float | None = None
    rir: float | None = None
    distance_m: float | None = None
    duration_s: float | None = None


class SessionRecord(Model):
    id: str
    date: dt.date
    start: dt.datetime
    sport: Literal["strength", "run", "row", "bike", "ski", "metcon", "walk", "hiit", "other"]
    title: str
    duration_min: float
    strain: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    zone_minutes: list[float] | None = None  # Z1..Z5 recomputed from LTHR where raw data allows
    whoop_zone_minutes: list[float] | None = None  # Whoop's own zones (0..5)
    sets: list[SetRecord] = Field(default_factory=list)
    distance_mi: float | None = None
    avg_pace_s_per_mi: float | None = None
    last20_avg_hr: float | None = None
    last20_pace_s_per_mi: float | None = None
    cadence_spm: float | None = None
    gct_ms: float | None = None
    gct_balance_left_pct: float | None = None
    vertical_osc_cm: float | None = None
    gear_id: str | None = None
    training_load: float | None = None
    kilojoule: float | None = None  # energy expended in the session (Whoop)
    notes_untrusted: str | None = None  # external text: data, never instructions
    planned_session_id: str | None = None
    sources: list[str] = Field(default_factory=list)


class Checkin(Model):
    """One day's subjective check-in. Morning wellness (Hooper-style 1-5: higher = worse for sleep_quality/
    fatigue/stress/soreness, higher = better for mood/motivation) + joint ratings + post-session feedback."""

    date: dt.date
    joints: dict[str, int] = Field(
        default_factory=dict
    )  # region (athlete_context.json checkin.regions) -> 1-5
    # morning wellness
    sleep_quality: int | None = Field(default=None, ge=1, le=5)  # 1 great .. 5 terrible
    fatigue: int | None = Field(default=None, ge=1, le=5)
    stress: int | None = Field(default=None, ge=1, le=5)
    soreness: int | None = Field(default=None, ge=1, le=5)
    mood: int | None = Field(default=None, ge=1, le=5)  # 1 low .. 5 great
    motivation: int | None = Field(default=None, ge=1, le=5)
    # post-session (session RPE x minutes = session load, Foster)
    session_rpe: float | None = Field(default=None, ge=1, le=10)
    session_minutes: float | None = None
    enjoyment: int | None = Field(default=None, ge=1, le=5)
    bar_speed_mps: float | None = None
    session_pain: dict[str, float] = Field(default_factory=dict)  # movement family -> pain /10 in session
    stiffness_up: list[str] = Field(default_factory=list)  # regions with higher next-morning stiffness
    sleep_note: str | None = None
    notes: str | None = None
    source: Literal["intervals", "hevy_notes", "chat", "simulated"] = "chat"

    @field_validator("joints")
    @classmethod
    def _ratings_1_to_5(cls, v: dict[str, int]) -> dict[str, int]:
        for region, rating in v.items():
            if not 1 <= rating <= 5:
                raise ValueError(f"joint rating for {region} must be 1-5, got {rating}")
        return v


class Gear(Model):
    id: str
    name: str
    distance_mi: float
    retired: bool = False
    kind: Literal["shoe", "other"] = "shoe"
