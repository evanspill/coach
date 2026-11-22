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
HevyLog = Literal["default", "inches"]
# How a one-side-at-a-time exercise is done: "split" = all reps on one side, then the other (logged as Left/Right
# exercises); "alternating" = sides alternate within the set (one entry); "either" = both are fine, the
# prescription's `alternating` picks (default split); "none" = bilateral / not per side.
Sides = Literal["none", "split", "alternating", "either"]
SIDES = ("Left", "Right")
INCHES_SUFFIX = " (in)"
# calorie efforts (erg tests, calorie intervals): Hevy has no calories field, so they are logged as reps = calories
# in a reps-only custom exercise '<name> (cal)'
CALORIES_SUFFIX = " (cal)"
M_PER_IN = 0.0254


def is_calorie_title(title: str) -> bool:
    """A logged Hevy title of a calorie effort ('Echo bike (cal)', also with a ' (Left)'/' (Right)' suffix)."""
    t = title.strip()
    for s in SIDES:
        if t.endswith(f" ({s})"):
            t = t[: -len(f" ({s})")]
            break
    return t.endswith(CALORIES_SUFFIX)


class EstimateFrom(Model):
    exercise: str
    factor: float


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
    # "inches": logged in Hevy as reps = inches. Hevy's API returns distances in whole metres, too coarse for jumps.
    hevy_log: HevyLog = "default"
    sides: Sides = "none"
    implements: int = Field(
        default=1, ge=1, le=2
    )  # 2 = a pair of dumbbells/kettlebells (loads are per implement)
    description: str | None = (
        None  # short how-to, shown in the Hevy routine notes (the API can't set it on the exercise)
    )
    video_url: str | None = None  # demo video, shown next to the how-to
    estimate_from: "EstimateFrom | None" = None

    def alternates(self, prescribed: bool | None = None) -> bool:
        """True when per-side work alternates within the set (logged as one exercise, reps per side)."""
        if self.sides == "either":
            return bool(prescribed)
        return self.sides == "alternating"

    def sides_cue(self, alternating: bool, per_side_count: str) -> str:
        """The plain-language instruction for per-side work, shown in the Hevy note."""
        if alternating:
            return f"Alternate sides each rep: {per_side_count} per side (log the per-side count)"
        return "One side at a time: finish all of this side, then switch"

    def has_tag(self, *tags: str) -> bool:
        return any(t in self.tags for t in tags)

    def hevy_name(self, side: str | None = None, calories: bool = False) -> str:
        """The Hevy exercise title this exercise is logged under. Inch-logged exercises get their own custom
        exercise ('Standing broad jump (in)'), as do calorie efforts ('Echo bike (cal)'); per-side work is two
        exercises, 'X (Left)' and 'X (Right)'."""
        if calories:
            base = f"{self.name}{CALORIES_SUFFIX}"
        elif self.hevy_log == "inches":
            base = f"{self.name}{INCHES_SUFFIX}"
        else:
            base = self.hevy_title or self.name
        return f"{base} ({side})" if side else base


class ExerciseLibrary(Model):
    exercises: dict[str, Exercise]

    def get(self, exercise_id: str) -> Exercise | None:
        return self.exercises.get(exercise_id)

    def __contains__(self, exercise_id: str) -> bool:
        return exercise_id in self.exercises

    def parse_hevy_title(self, title: str) -> tuple[Exercise | None, str | None]:
        """A logged Hevy title -> (library exercise, side). Strips the ' (Left)'/' (Right)' suffix of per-side
        exercises and resolves inch-logged titles ('Standing broad jump (in)')."""
        t = title.strip()
        exact = self.by_hevy_title(t)
        if exact is not None:  # a library title that itself ends in "(Left)" maps as is
            return exact, None
        side = None
        for s in SIDES:
            if t.endswith(f" ({s})"):
                t, side = t[: -len(f" ({s})")], s.lower()
                break
        if t.endswith(CALORIES_SUFFIX):
            base = t[: -len(CALORIES_SUFFIX)]
            hit = next((e for e in self.exercises.values() if e.name.lower() == base.lower()), None)
            return hit or self.by_hevy_title(base), side
        if t.endswith(INCHES_SUFFIX):
            base = t[: -len(INCHES_SUFFIX)].lower()
            hit = next(
                (e for e in self.exercises.values() if e.hevy_log == "inches" and e.name.lower() == base),
                None,
            )
            if hit:
                return hit, side
        return self.by_hevy_title(t), side

    def by_hevy_title(self, title: str) -> Exercise | None:
        """The library exercise a logged Hevy title belongs to. Generic titles shared by several exercises
        ('Warm Up', 'Stretching') are ambiguous and map to None rather than to an arbitrary drill."""
        t = title.strip().lower()
        hits = [ex for ex in self.exercises.values() if ex.hevy_title and ex.hevy_title.lower() == t]
        if not hits:
            hits = [ex for ex in self.exercises.values() if ex.name.lower() == t]
        return hits[0] if len(hits) == 1 else None


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
    min_days_before: int | None = None  # days at the rung below before advancing into this one
    form_check: bool = False  # needs a recorded form check / physio OK before advancing into this rung


class Family(Model):
    region: str
    aliases: list[str] = Field(default_factory=list)
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


class Milestone(Model):
    pattern: str
    levels: dict[int, int]


class Skill(Model):
    name: str
    drills: list[str] = Field(default_factory=list)
    milestone: Milestone | None = None
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
    slot: str = "engine"
    stress: str = "none"
    lower_is_better: bool = False
    goal_change_pct: float = 5.0
    typical_error_pct: float = 3.0
    session: dict[str, Any] = Field(default_factory=dict)


class TestBattery(Model):
    standard_conditions: dict[str, Any]
    schedule: dict[str, dict[str, int]]
    tests: dict[str, TestDef]
    batteries: dict[str, Any]
