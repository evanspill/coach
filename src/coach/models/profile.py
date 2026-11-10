"""Athlete profile (config/athlete_context.json) and behaviour settings (config/coach.yaml)."""

import datetime as dt
from typing import Literal

from pydantic import Field, field_validator

from coach.models.common import LooseModel, Model


class Home(Model):
    name: str
    lat: float
    lon: float


class Identity(Model):
    age: int
    sex: Literal["male", "female"]
    height_cm: float
    timezone: str
    home: Home


class BodyCompGoal(Model):
    target_weight_kg: float
    target_weight_lb: float
    target_body_fat_pct: tuple[float, float]


class Goals(Model):
    body_composition: BodyCompGoal
    marathon_target: str
    outcomes: list[str]


class Race(Model):
    id: str
    name: str
    kind: Literal["marathon", "crossfit_open", "hyrox", "half_marathon", "other"]
    date: dt.date
    confirmed: bool
    goal: str | None = None
    workout_dates: list[dt.date] = Field(default_factory=list)
    note: str | None = None


class Season(Model):
    start: dt.date
    post_open_weeks: int = 1
    marathon_build_weeks: int = 13
    taper_weeks: int = 3
    reset_weeks: int = 2


class Thresholds(Model):
    recovery_green_min: int
    recovery_red_max: int
    hrv_baseline_days: int
    hrv_trend_days: int
    hrv_swc_sd: float
    hrv_below_days_yellow: int
    hrv_below_days_red: int
    rhr_baseline_days: int
    rhr_yellow_delta: float
    rhr_red_delta: float
    joint_yellow: int
    joint_red: int
    joint_flag_rating: int
    joint_flag_consecutive: int
    sustained_red_days: int
    sustained_red_window: int
    vbt_slow_pct: float
    vbt_fast_pct: float
    high_strain: float
    weekly_run_increase_pct: float
    long_run_max_fraction: float
    long_run_max_fraction_low_volume: float
    long_run_rule_min_weekly_miles: float
    pain_rule_max: float
    shoe_alert_miles: float


class WeatherRules(Model):
    slow_sum_f: float
    indoor_sum_f: float
    slow_pace_s_per_mi: tuple[int, int]
    icy_temp_c: float
    icy_precip_hours: int


class NutritionRules(Model):
    protein_g_per_kg: tuple[float, float]
    fat_floor_g: float
    carb_g_per_kg: dict[Literal["high", "moderate", "low"], float]
    intra_session_carbs_g_per_h: tuple[int, int]
    intra_threshold_minutes: int
    supplements: list[str]
    supplements_note: str


class Running(Model):
    status: str
    ramp_start_miles: tuple[float, float]
    runs_per_week_at_start: int
    cadence_target_spm: tuple[int, int]
    max_weekly_increase_pct: float
    hold_every_nth_week: int
    gait_analysis_recommended: bool


class AthleteProfile(Model):
    schema_version: int
    identity: Identity
    goals: Goals
    races: list[Race]
    season: Season
    injury_history: LooseModel
    schedule: LooseModel
    running: Running
    routes: dict[str, LooseModel]
    gear: LooseModel
    recovery_tools: list[str]
    no_access: list[str]
    thresholds: Thresholds
    weather: WeatherRules
    nutrition: NutritionRules
    travel_equipment: list[str]

    @field_validator("races")
    @classmethod
    def _unique_race_ids(cls, races: list[Race]) -> list[Race]:
        ids = [r.id for r in races]
        if len(ids) != len(set(ids)):
            raise ValueError("race ids must be unique")
        return races

    @property
    def default_start(self) -> str:
        return str(self.schedule.model_extra.get("default_start", "09:30"))  # type: ignore[union-attr]


class PushSettings(Model):
    enabled: bool = False


class ApprovalSettings(Model):
    weekly_plan: Literal["manual", "auto"] = "manual"
    daily_adjustments: Literal["auto", "manual"] = "auto"
    manual_if: list[str] = Field(default_factory=list)


class ValidatorSettings(Model):
    max_attempts: int = 3


class CoachSettings(Model):
    push: PushSettings = PushSettings()
    approval: ApprovalSettings = ApprovalSettings()
    paused: bool = False
    notification_detail: Literal["brief", "normal"] = "normal"
    validator: ValidatorSettings = ValidatorSettings()
