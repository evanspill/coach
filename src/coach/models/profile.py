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
    birth_year: int
    birth_month: int = Field(ge=1, le=12)
    sex: Literal["male", "female"]
    height_cm: float
    timezone: str
    home: Home

    def age_on(self, day: dt.date) -> int:
        """Age on a given day. With only the birth month known, a day in the birth month counts as after the birthday."""
        return day.year - self.birth_year - (1 if day.month < self.birth_month else 0)


class AgeStandard(Model):
    min_age: int
    max_age: int
    time: str  # H:MM:SS


class ReferenceTime(Model):
    """A placement benchmark looked up from official results, e.g. the Pro age-group winner at a qualifying event."""

    event: str
    date: dt.date
    age_group: str  # e.g. "30-34"
    time: str  # H:MM:SS
    source: str = ""


class LongTermGoal(Model):
    """A goal that may take more than one season. The coach checks feasibility at every transition week and never
    changes a long-term goal without the athlete's approval.

    kinds:
      marathon_time    an age-graded qualifying time (Boston): standards, margin_s
      race_time        a fixed finish time for a race kind (e.g. HYROX Open 1:10): target_time, division
      event_placement  a championship slot won by placing in an age group (HYROX Worlds): division, place,
                       reference_times (age-group results the coach looks up for the races being targeted)
      open_percentile  a percentile of a worldwide online stage (CrossFit Open -> Quarterfinals): top_pct, division,
                       prerequisite skills and movement families (Rx needs them)"""

    id: str
    name: str
    kind: Literal["marathon_time", "race_time", "event_placement", "open_percentile"]
    race_kind: Literal["marathon", "crossfit_open", "hyrox", "half_marathon", "other"] = "marathon"
    event: str  # the event the goal qualifies for
    event_date: dt.date  # the edition targeted; age is taken on this day
    date_confirmed: bool = True  # False: an estimate until the organiser publishes the date
    qualifying_closes_days_before: int = 0  # last day a qualifying result counts, relative to event_date
    standards: list[AgeStandard] = Field(
        default_factory=list
    )  # marathon_time: age-graded (sex from identity)
    target_time: str | None = None  # race_time (or marathon_time instead of age-graded standards)
    margin_s: int = 0  # marathon_time: how far under the standard to aim (oversubscribed events)
    division: str | None = None  # results count only in this division (e.g. "pro", "rx")
    place: int = 1  # event_placement: age-group place that earns the slot
    age_band_years: int = 5  # event_placement: width of age groups
    reference_times: list[ReferenceTime] = Field(default_factory=list)
    top_pct: float | None = None  # open_percentile: e.g. 25 = top 25% worldwide
    prerequisite_skills: list[str] = Field(default_factory=list)  # skills.yaml ids that must be competent
    prerequisite_families: list[str] = Field(
        default_factory=list
    )  # movement families that must be at the top rung
    source: str = ""  # where the qualification rules came from
    assumed_gain_pct_per_year: float | None = (
        8.0  # improvement assumed before an observed trend (None: wait for data)
    )
    max_gain_pct_per_year: float = 12.0  # cap on the observed rate when projecting (gains slow down)

    @property
    def qualify_by(self) -> dt.date:
        return self.event_date - dt.timedelta(days=self.qualifying_closes_days_before)


class BodyCompGoal(Model):
    target_weight_kg: float
    target_weight_lb: float
    target_body_fat_pct: tuple[float, float]


class Goals(Model):
    body_composition: BodyCompGoal
    outcomes: list[str]
    long_term: list[LongTermGoal] = Field(default_factory=list)


class Race(Model):
    id: str
    name: str
    kind: Literal["marathon", "crossfit_open", "hyrox", "half_marathon", "other"]
    date: dt.date
    confirmed: bool
    goal: str | None = None  # the athlete's own words; the coach's approved race target lives in race_targets
    workout_dates: list[dt.date] = Field(default_factory=list)
    note: str | None = None


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
    long_run_max_increase_mi: float = 1.0
    pain_rule_max: float
    shoe_alert_miles: float


class WeatherRules(Model):
    slow_sum_f: float
    indoor_sum_f: float
    slow_pace_s_per_mi: tuple[int, int]
    icy_temp_c: float
    icy_precip_hours: int
    extreme_cold_f: float = 0  # at or below this (air temp) quality/long work moves indoors


class NutritionRules(Model):
    protein_g_per_kg: tuple[float, float]
    fat_floor_g: float
    carb_g_per_kg: dict[Literal["high", "moderate", "low"], float]
    intra_session_carbs_g_per_h: tuple[int, int]
    intra_threshold_minutes: int
    supplements: list[str]
    supplements_note: str
    estimate_kcal_per_kg: float = 33
    calorie_phase_settings: dict[str, str] = Field(default_factory=dict)
    peri_workout: dict[str, str] = Field(default_factory=dict)


class CheckinRegion(Model):
    label: str
    words: list[str]
    intervals_field: str | None = None


class CheckinConfig(Model):
    regions: dict[str, CheckinRegion]
    intervals_fields: dict[str, str] = Field(default_factory=dict)


class RecoveryConfig(Model):
    after_hard_session: str
    evening_mobility: str
    nightly: str
    areas: dict[str, str]


class DefaultZones(Model):
    lthr: int
    threshold_pace_s_per_mi: int
    note: str = ""


class MarathonPrediction(Model):
    """Threshold pace -> marathon time. Riegel's formula underestimates recreational runners' marathon times (by 10+ min
    for half the runners in Vickers & Vertosick 2016), so a penalty applies until the athlete has a marathon result."""

    riegel_exponent: float = 1.06
    no_marathon_penalty_s: int = 600


class Running(Model):
    status: str
    ramp_start_miles: tuple[float, float]
    runs_per_week_at_start: int
    cadence_target_spm: tuple[int, int]
    max_weekly_increase_pct: float
    hold_every_nth_week: int
    gait_analysis_recommended: bool
    default_zones: DefaultZones = DefaultZones(lthr=165, threshold_pace_s_per_mi=480)
    marathon_prediction: MarathonPrediction = MarathonPrediction()


class AthleteProfile(Model):
    schema_version: int
    identity: Identity
    goals: Goals
    races: list[Race]
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
    checkin: CheckinConfig
    recovery: RecoveryConfig
    intake_questions: list[str] = Field(default_factory=list)
    notes_seed: list[str] = Field(default_factory=list)
    race_gear_checklist: str = ""
    emergency_number: str = "911"

    def race(self, kind: str) -> Race | None:
        return next((r for r in self.races if r.kind == kind), None)

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
    # Fill days the direct Whoop API missed from Intervals.icu wellness (its Whoop connection). Only turn on when
    # Intervals.icu's HRV / resting HR / sleep come from Whoop, not a watch worn part-time (DECISIONS 75).
    whoop_backup: Literal["none", "intervals"] = "none"
