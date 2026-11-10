"""Planning layers: macrocycle (year) -> block outline -> week plan -> sessions."""

import datetime as dt
from typing import Literal

from pydantic import Field, model_validator

from coach.models.common import Model

Location = Literal["gym", "outdoor", "track", "travel", "home"]
SessionType = Literal[
    "lower",
    "upper",
    "full_body",
    "run_easy",
    "run_long",
    "run_quality",
    "hyrox",
    "metcon",
    "sprint_upper",
    "recovery",
    "rest",
    "test",
    "competition",
    "race",
]
BlockKind = Literal[
    "warmup",
    "skill",
    "power",
    "strength",
    "hypertrophy",
    "conditioning",
    "run",
    "test",
    "mobility",
    "cooldown",
]
WeekType = Literal["baseline", "training", "deload", "transition", "competition", "taper", "reset"]
Zone = Literal["Z1", "Z2", "Z3", "MP", "T", "Z5", "strides"]
CarbTier = Literal["high", "moderate", "low"]
Pillar = Literal["neural", "force", "glycolytic", "aerobic"]


class Prescription(Model):
    exercise_id: str
    sets: int = Field(ge=1, le=12)
    reps: int | None = None
    reps_max: int | None = None
    duration_s: int | None = None
    distance_m: int | None = None
    calories: int | None = None
    rir: float | None = Field(default=None, ge=0, le=6)
    load_kg: float | None = None  # filled by `coach` from e1RM; Claude never sets it
    load_lb: float | None = None
    load_note: str | None = None
    tempo: str | None = None
    rest_s: int | None = None
    per_side: bool = False
    notes: str | None = None


class RunSegment(Model):
    label: str
    zone: Zone
    duration_min: float | None = None
    distance_mi: float | None = None
    reps: int = 1
    recovery_min: float | None = None
    modality: Literal["run", "row", "ski", "bike", "walk", "stairs"] = "run"
    terrain: Literal["flat", "rolling", "downhill", "treadmill"] = "flat"
    pace_s_per_mi: tuple[int, int] | None = None  # filled by `coach` from threshold pace
    hr_bpm: tuple[int, int] | None = None  # filled by `coach` from LTHR

    @model_validator(mode="after")
    def _has_size(self) -> "RunSegment":
        if self.duration_min is None and self.distance_mi is None:
            raise ValueError(f"run segment '{self.label}' needs duration_min or distance_mi")
        return self


class Metcon(Model):
    name: str
    format: Literal["amrap", "for_time", "emom", "intervals", "chipper", "hyrox_sim"]
    time_cap_min: float = Field(gt=0, le=90)
    rounds: int | None = None
    movements: list[Prescription]
    stimulus: str
    scaling: str = ""
    score_type: Literal["rounds_reps", "time", "calories", "load", "none"] = "rounds_reps"


class SessionBlock(Model):
    kind: BlockKind
    title: str = ""
    items: list[Prescription] = Field(default_factory=list)
    run: list[RunSegment] = Field(default_factory=list)
    metcon: Metcon | None = None
    test_id: str | None = None
    notes: str = ""


class Session(Model):
    id: str
    date: dt.date
    start_time: str = "09:30"
    type: SessionType
    title: str
    intent: str
    location: Location = "gym"
    route: str | None = None
    expected_minutes: int = Field(ge=0, le=300)
    key: bool = False
    carb_tier: CarbTier = "moderate"
    blocks: list[SessionBlock] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    recovery_note: str = ""
    shoe: str | None = None

    def all_items(self) -> list[Prescription]:
        out: list[Prescription] = []
        for b in self.blocks:
            out.extend(b.items)
            if b.metcon:
                out.extend(b.metcon.movements)
        return out

    def run_segments(self) -> list[RunSegment]:
        return [seg for b in self.blocks for seg in b.run]


class Deviation(Model):
    field: str
    planned: str
    actual: str
    reason: str


class WeekPlan(Model):
    week_id: str
    block_id: str
    week_index: int
    week_type: WeekType
    start: dt.date
    sessions: list[Session]
    deviations: list[Deviation] = Field(default_factory=list)
    generated_by: Literal["claude", "fallback"] = "claude"
    approval: Literal["pending", "approved", "auto"] = "pending"
    rationale: str = ""
    illness_dates: list[dt.date] = Field(default_factory=list)
    travel_dates: list[dt.date] = Field(default_factory=list)
    focus_points: list[str] = Field(default_factory=list)

    @property
    def end(self) -> dt.date:
        return self.start + dt.timedelta(days=6)

    def session_on(self, day: dt.date) -> Session | None:
        for s in self.sessions:
            if s.date == day:
                return s
        return None


class PillarPlan(Model):
    mode: Literal["build", "maintain", "sharpen", "taper"]
    description: str
    med: float  # minimum effective dose per normal week (sessions; aerobic = minutes)
    deload_med: float


class WeekTarget(Model):
    week_index: int
    start: dt.date
    type: WeekType
    run_miles: float
    long_run_miles: float | None = None
    key_sessions: list[str] = Field(default_factory=list)
    hard_sets: dict[str, tuple[int, int]] = Field(default_factory=dict)
    notes: str = ""


class MainLift(Model):
    family: str | None = None
    exercise_id: str | None = None
    scheme: str
    progression: str


class Revision(Model):
    at: dt.date
    reason: str
    change: str


class BlockOutline(Model):
    block_id: str
    name: str
    focus: str
    start: dt.date
    end: dt.date
    goal_id: str | None = None
    main_lifts: list[MainLift]
    progression: str
    pillars: dict[Pillar, PillarPlan]
    weeks: list[WeekTarget]
    deload_weeks: list[int]
    competition_weeks: list[int] = Field(default_factory=list)
    taper_weeks: list[int] = Field(default_factory=list)
    transition_week: int
    calorie_phase: Literal["cut", "recomp", "lean_gain", "maintenance"]
    macrofactor_setting: str
    variety: str = ""
    generated_by: Literal["claude", "fallback"] = "claude"
    revisions: list[Revision] = Field(default_factory=list)

    def week(self, index: int) -> WeekTarget | None:
        for w in self.weeks:
            if w.week_index == index:
                return w
        return None

    def week_for_date(self, day: dt.date) -> WeekTarget | None:
        for w in self.weeks:
            if w.start <= day <= w.start + dt.timedelta(days=6):
                return w
        return None


class MacroBlock(Model):
    id: str
    key: str = ""  # block key in config/season.yaml
    index: int
    name: str
    focus: str
    start: dt.date
    end: dt.date
    competition_weeks: list[dt.date] = Field(default_factory=list)
    taper_weeks: list[dt.date] = Field(default_factory=list)
    reset_weeks: list[dt.date] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)

    @property
    def weeks(self) -> int:
        return ((self.end - self.start).days + 1) // 7

    @property
    def transition_start(self) -> dt.date:
        return self.end - dt.timedelta(days=6)


class Macrocycle(Model):
    season: str
    baseline_start: dt.date
    baseline_end: dt.date
    blocks: list[MacroBlock]
    generated_on: dt.date
    unconfirmed_races: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def block_for(self, day: dt.date) -> MacroBlock | None:
        for b in self.blocks:
            if b.start <= day <= b.end:
                return b
        return None

    def block_by_id(self, block_id: str) -> MacroBlock | None:
        for b in self.blocks:
            if b.id == block_id:
                return b
        return None

    def next_block(self, block_id: str) -> MacroBlock | None:
        for i, b in enumerate(self.blocks):
            if b.id == block_id and i + 1 < len(self.blocks):
                return self.blocks[i + 1]
        return None


class GoalTarget(Model):
    test_id: str
    metric: str
    baseline_value: float
    target_value: float
    unit: str
    change_pct: float
    direction: Literal["increase", "decrease"]


class Guardrail(Model):
    test_id: str
    metric: str
    description: str
    baseline_value: float
    limit_value: float
    direction: Literal["no_lower_than", "no_higher_than"]


class BlockGoal(Model):
    block_id: str
    primary: GoalTarget
    guardrails: list[Guardrail] = Field(min_length=1, max_length=2)
    rationale: str
    gap_analysis: dict[str, float] = Field(default_factory=dict)
    calorie_phase: Literal["cut", "recomp", "lean_gain", "maintenance"]
    calorie_phase_reason: str = ""
    status: Literal["pending", "approved", "rejected"] = "pending"
    generated_by: Literal["claude", "fallback"] = "claude"
