"""config/season.yaml (shape of the year) and config/training.yaml (session content + training rules)."""

import datetime as dt
from typing import Any, Literal

from pydantic import Field, model_validator

from coach.models.common import Model
from coach.models.plans import MainLift, PillarPlan


class DeloadRules(Model):
    every: int = 4
    earliest_week: int = 3
    volume_factor: float = 0.55
    run_factor: float = 0.7
    taper_run_factor: float = 0.75
    competition_run_factor: float = 0.8


class SeasonSettings(Model):
    start: dt.date
    baseline_weeks: int = 1
    baseline_week: str = "baseline"
    transition_week: str = "transition"
    min_block_weeks: int = 4
    deload: DeloadRules = DeloadRules()


class EndAfterEvent(Model):
    kind: str
    weeks_after: int = 1


class EventAnchor(Model):
    kind: str
    taper_weeks: int = 3
    reset_weeks: int = 2


class BlockLength(Model):
    weeks: int | None = None
    end_after_event: EndAfterEvent | None = None
    event: EventAnchor | None = None
    fill: bool = False
    default_weeks: int | None = None

    @model_validator(mode="after")
    def _one_mode(self) -> "BlockLength":
        modes = [self.weeks is not None, self.end_after_event is not None, self.event is not None, self.fill]
        if sum(modes) != 1:
            raise ValueError("block length needs exactly one of weeks / end_after_event / event / fill")
        return self


class LongRunSpec(Model):
    target_minutes: int = 75
    erg_extension: bool = False
    mp_finish_min: int = 20
    mp_finish_from_miles: float = 8


class Guardrail(Model):
    test: str
    change: float
    mode: Literal["absolute", "pct", "weekly_pct"]
    description: str


class GoalSpec(Model):
    focus_tests: list[str]
    guardrails: list[Guardrail] = Field(default_factory=list, max_length=2)


class BlockSpec(Model):
    key: str
    name: str
    focus: str
    length: BlockLength
    competition_event: str | None = None
    weeks: dict[str, str]  # week type -> week template name
    run_miles: tuple[float, float]
    long_run: LongRunSpec = LongRunSpec()
    calorie_phase: Literal["auto", "cut", "recomp", "lean_gain", "maintenance"] = "auto"
    pillars: dict[Literal["neural", "force", "glycolytic", "aerobic"], PillarPlan]
    hard_sets: dict[str, tuple[int, int]]
    key_sessions: dict[str, list[str]]
    main_lifts: list[MainLift]
    tests: list[str]
    goal: GoalSpec
    taper_volumes: list[float] = Field(default_factory=lambda: [0.8, 0.6, 0.4])
    reset_volume: float = 0.35


class SeasonConfig(Model):
    season: SeasonSettings
    blocks: list[BlockSpec]

    @model_validator(mode="after")
    def _checks(self) -> "SeasonConfig":
        keys = [b.key for b in self.blocks]
        if len(keys) != len(set(keys)):
            raise ValueError("block keys must be unique")
        if sum(1 for b in self.blocks if b.length.fill) > 1:
            raise ValueError("at most one block may use fill: true")
        return self

    def spec(self, key: str) -> BlockSpec:
        for b in self.blocks:
            if b.key == key:
                return b
        raise KeyError(f"no block '{key}' in season.yaml")


class ItemSpec(Model):
    exercise: str | None = None
    family: str | None = None
    sets: int = 1
    reps: int | None = None
    reps_max: int | None = None
    rir: float | None = None
    duration_s: int | None = None
    distance_m: int | None = None
    calories: int | None = None
    rest_s: int | None = None
    per_side: bool = False
    notes: str | None = None
    tempo: str | None = None
    deload_exercise: str | None = None

    @model_validator(mode="after")
    def _one_target(self) -> "ItemSpec":
        if (self.exercise is None) == (self.family is None):
            raise ValueError("item needs exactly one of exercise / family")
        return self


class ItemSet(Model):
    title: str = ""
    items: list[ItemSpec] = Field(default_factory=list)
    same_as: str | None = None


class SegmentSpec(Model):
    label: str
    zone: str
    duration_min: float | None = None
    distance_mi: float | None = None
    reps: int = 1
    recovery_min: float | None = None
    modality: str = "run"


class BlockTemplate(Model):
    kind: str
    title: str = ""
    items: list[ItemSpec] = Field(default_factory=list)
    use: str | None = None
    generate: str | None = None
    # generator options
    pool: str | None = None
    minutes: float | None = None
    name: str | None = None
    format: str | None = None
    stimulus: str | None = None
    scaling: str | None = None
    label: str | None = None
    zone: str = "Z2"
    strides: int = 0
    min_miles: float = 0
    location: str | None = None
    rep_min: float | None = None
    recovery_min: float | None = None
    share_of_miles: float | None = None
    segments: list[SegmentSpec] = Field(default_factory=list)


class SessionTemplate(Model):
    type: str
    title: str
    intent: str
    location: str = "gym"
    route: Any = None
    key: bool = False
    warmup: str | None = None
    cooldown: str | None = "standard"
    run_share: float = 0.0
    scale: bool = True
    special: Literal["recovery", "rest", "tests"] | None = None
    blocks: list[BlockTemplate] = Field(default_factory=list)


class MetconPool(Model):
    count: int
    format: str
    name: str
    stimulus: str
    scaling: str = ""
    score_type: str = "rounds_reps"
    rounds: int | None = None
    movements: list[ItemSpec]


class SkillPractice(Model):
    sets: int = 4
    reps: int = 3
    rir: float = 4
    per_session: int = 2
    fallback: list[str] = Field(default_factory=list)


class TrainingRules(Model):
    required_warmup: dict[str, list[str]] = Field(default_factory=dict)
    forbidden_back_to_back: list[tuple[str, str]] = Field(default_factory=list)
    deload_banned_tags: list[str] = Field(default_factory=lambda: ["eccentric_heavy", "high_impact"])
    yellow_replacement: dict[str, Any] = Field(default_factory=lambda: {"minutes": 40, "zone": "Z2"})
    red_recovery_minutes: int = 35
    max_session_minutes: int = 120
    long_session_types: list[str] = Field(default_factory=lambda: ["run_long", "race", "test", "competition"])
    min_recovery_days_per_week: int = 1
    carb_tiers: dict[str, list[str]] = Field(default_factory=dict)
    intra_session_carb_types: list[str] = Field(default_factory=list)


class TestsDay(Model):
    run_location: str = "outdoor"
    run_route: str | None = None


class TrainingConfig(Model):
    rules: TrainingRules
    warmups: dict[str, ItemSet]
    cooldowns: dict[str, ItemSet]
    item_sets: dict[str, ItemSet]
    skill_practice: SkillPractice = SkillPractice()
    metcon_pools: dict[str, MetconPool]
    fillers: dict[str, str] = Field(default_factory=dict)
    tests_day: TestsDay = TestsDay()
    sessions: dict[str, SessionTemplate]
    week_templates: dict[str, list[str]]

    def item_set(self, name: str, kind: str = "item_sets") -> ItemSet:
        table = getattr(self, kind)
        s = table[name]
        return table[s.same_as] if s.same_as else s
