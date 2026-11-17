"""Small per-exercise prescriptions the code owns: rest between sets and when to wear a belt (rules in training.yaml)."""

from coach.models.library import Exercise
from coach.models.plans import Prescription
from coach.models.season import TrainingRules


def rest_for(block_kind: str, ex: Exercise | None, it: Prescription, rules: TrainingRules) -> int:
    """Rest between sets: the plan's own rest_s wins; otherwise by block kind (the stimulus), longer for primary lifts."""
    if it.rest_s is not None:
        return it.rest_s
    if ex is not None and "primary" in ex.tags and block_kind in rules.rest_primary_s:
        return rules.rest_primary_s[block_kind]
    return rules.rest_s.get(block_kind, rules.rest_s.get("default", 60))


def belt_for(block_kind: str, ex: Exercise | None, it: Prescription, rules: TrainingRules) -> str | None:
    """Which sets to wear a belt on, or None. Heavy spine-loaded primary lifts only; never warm-up or ramp sets."""
    b = rules.belt
    if (
        ex is None
        or not b.tags_all
        or not all(t in ex.tags for t in b.tags_all)
        or block_kind not in b.block_kinds
    ):
        return None
    if block_kind == "test":  # working up to a rep max: only the heaviest sets
        return f"last {b.test_sets} (heaviest) sets"
    if it.rir is not None and it.reps is not None and it.rir <= b.max_rir and it.reps <= b.max_reps:
        return "all work sets (not warm-up/ramp sets)"
    return None
