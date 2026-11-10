"""Exercise library, equipment, movement ladders, skills and the test battery (all from config/)."""

from typing import Any, Literal

from pydantic import Field

from coach.models.common import LooseModel, Model

Implement = Literal[
    "barbell",
    "trap_bar",
    "open_trap_bar",
    "safety_squat_bar",
    "landmine",
    "smith_machine",
    "dumbbell",
    "kettlebell",
    "machine",
    "cable",
    "none",
]
LoadMode = Literal["e1rm", "last_used", "bodyweight", "kb", "none"]


class Exercise(Model):
    id: str
    name: str
    equipment: list[str]
    implement: Implement = "none"
    muscles: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    family: str | None = None
    rung: int | None = None
    requires: dict[str, int] = Field(default_factory=dict)
    regressions: list[str] = Field(default_factory=list)
    deload_swap: str | None = None
    skill: str | None = None
    load_mode: LoadMode = "none"
    hevy_title: str | None = None
    hevy_template_id: str | None = None

    def has_tag(self, *tags: str) -> bool:
        return any(t in self.tags for t in tags)


class ExerciseLibrary(Model):
    exercises: dict[str, Exercise]

    def get(self, exercise_id: str) -> Exercise | None:
        return self.exercises.get(exercise_id)

    def __contains__(self, exercise_id: str) -> bool:
        return exercise_id in self.exercises

    def by_hevy_title(self, title: str) -> Exercise | None:
        t = title.strip().lower()
        for ex in self.exercises.values():
            if (ex.hevy_title and ex.hevy_title.lower() == t) or ex.name.lower() == t:
                return ex
        return None


class LocationEquipment(Model):
    description: str
    equipment: list[str]


class EquipmentConfig(Model):
    locations: dict[str, LocationEquipment]
    loading: dict[str, Any]

    def available(self, location: str, travel_equipment: list[str] | None = None) -> set[str]:
        if location == "travel" and travel_equipment is not None:
            return set(travel_equipment)
        loc = self.locations.get(location)
        return set(loc.equipment) if loc else set()


class Rung(Model):
    name: str
    exercises: list[str]
    min_rir: float


class Family(Model):
    region: str
    rungs: list[Rung]


class ProgressionRules(LooseModel):
    exposures_to_advance: int
    min_days_at_rung: int = 14
    max_session_pain_to_advance: float
    regress_on_session_pain_above: float
    regress_on_next_day_flare: bool
    region_flag_rating: int
    region_flag_consecutive: int


class MovementProgressions(Model):
    rules: ProgressionRules
    families: dict[str, Family]
    joint_flags: dict[str, list[str]]

    def families_for_region(self, region: str) -> list[str]:
        return [name for name, fam in self.families.items() if fam.region == region]


class SkillGate(Model):
    family: str
    rung: int


class Skill(Model):
    name: str
    levels: list[str]
    competent_level: int
    current_level: int
    gate: SkillGate | None = None

    @property
    def competent(self) -> bool:
        return self.current_level >= self.competent_level


class SkillsConfig(Model):
    skills: dict[str, Skill]


class TestDef(LooseModel):
    name: str
    quality: str
    pillar: str
    category: Literal["power", "strength", "run", "engine", "body"]
    protocol: dict[str, str]
    equipment: list[str]
    location: str
    safety: str
    metric: str
    unit: str
    scoring: str
    variants: dict[str, float] = Field(default_factory=dict)
    reference_variant: str | None = None
    family: str | None = None
    passive: bool = False


class TestBattery(Model):
    standard_conditions: dict[str, Any]
    tests: dict[str, TestDef]
    batteries: dict[str, Any]
