"""Load and validate everything under config/."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from coach import paths
from coach.models import (
    AthleteProfile,
    CoachSettings,
    EquipmentConfig,
    Exercise,
    ExerciseLibrary,
    MovementProgressions,
    SkillsConfig,
    TestBattery,
)


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


@dataclass(frozen=True)
class Config:
    root: Path
    profile: AthleteProfile
    settings: CoachSettings
    equipment: EquipmentConfig
    library: ExerciseLibrary
    progressions: MovementProgressions
    skills: SkillsConfig
    tests: TestBattery
    benchmarks: dict

    def exercise(self, exercise_id: str) -> Exercise:
        ex = self.library.get(exercise_id)
        if ex is None:
            raise KeyError(f"unknown exercise '{exercise_id}'")
        return ex


def _library(raw: dict) -> ExerciseLibrary:
    defaults = raw.get("defaults", {})
    exercises = {}
    for ex_id, body in raw["exercises"].items():
        merged = {**defaults, **body, "id": ex_id}
        exercises[ex_id] = Exercise.model_validate(merged)
    return ExerciseLibrary(exercises=exercises)


def load_config(config_dir: Path | None = None) -> Config:
    cdir = Path(config_dir) if config_dir else paths.config_dir()
    return _load_cached(str(cdir.resolve()), _mtime_key(cdir))


def _mtime_key(cdir: Path) -> float:
    return max((p.stat().st_mtime for p in cdir.glob("*") if p.is_file()), default=0.0)


@lru_cache(maxsize=8)
def _load_cached(cdir_str: str, _mtime: float) -> Config:
    cdir = Path(cdir_str)
    profile = AthleteProfile.model_validate(load_json(cdir / "athlete_context.json"))
    settings = CoachSettings.model_validate(load_yaml(cdir / "coach.yaml"))
    equipment = EquipmentConfig.model_validate(load_yaml(cdir / "equipment.yaml"))
    library = _library(load_yaml(cdir / "exercises.yaml"))
    progressions = MovementProgressions.model_validate(load_yaml(cdir / "movement_progressions.yaml"))
    skills = SkillsConfig.model_validate(load_yaml(cdir / "skills.yaml"))
    tests = TestBattery.model_validate(load_yaml(cdir / "tests.yaml"))
    benchmarks = load_yaml(cdir / "benchmarks.yaml")
    cfg = Config(cdir, profile, settings, equipment, library, progressions, skills, tests, benchmarks)
    check_config_consistency(cfg)
    return cfg


def check_config_consistency(cfg: Config) -> None:
    """Cross-file integrity: every referenced exercise/equipment/family exists."""
    errors: list[str] = []
    all_equipment = set().union(*(set(loc.equipment) for loc in cfg.equipment.locations.values()))
    for ex in cfg.library.exercises.values():
        for eq in ex.equipment:
            if eq not in all_equipment:
                errors.append(f"exercise {ex.id}: equipment '{eq}' not in equipment.yaml")
        for r in [*ex.regressions, *([ex.deload_swap] if ex.deload_swap else [])]:
            if r not in cfg.library:
                errors.append(f"exercise {ex.id}: regression/swap '{r}' not in library")
        if ex.family and ex.family not in cfg.progressions.families:
            errors.append(f"exercise {ex.id}: family '{ex.family}' unknown")
        for fam in ex.requires:
            if fam not in cfg.progressions.families:
                errors.append(f"exercise {ex.id}: requires unknown family '{fam}'")
        if ex.skill and ex.skill not in cfg.skills.skills:
            errors.append(f"exercise {ex.id}: skill '{ex.skill}' not in skills.yaml")
    for fam_name, fam in cfg.progressions.families.items():
        for i, rung in enumerate(fam.rungs):
            for ex_id in rung.exercises:
                ex = cfg.library.get(ex_id)
                if ex is None:
                    errors.append(f"family {fam_name} rung {i}: exercise '{ex_id}' unknown")
                elif ex.family != fam_name or ex.rung != i:
                    errors.append(
                        f"family {fam_name} rung {i}: exercise '{ex_id}' declares {ex.family}/{ex.rung}"
                    )
    if errors:
        raise ValueError("config inconsistent:\n  " + "\n  ".join(errors))
