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
from coach.models.season import SeasonConfig, TrainingConfig


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
    season: SeasonConfig
    training: TrainingConfig

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
    season = SeasonConfig.model_validate(load_yaml(cdir / "season.yaml"))
    training = TrainingConfig.model_validate(load_yaml(cdir / "training.yaml"))
    cfg = Config(
        cdir, profile, settings, equipment, library, progressions, skills, tests, benchmarks, season, training
    )
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
    for fam_name, family in cfg.progressions.families.items():
        for i, rung in enumerate(family.rungs):
            for ex_id in rung.exercises:
                rung_ex = cfg.library.get(ex_id)
                if rung_ex is None:
                    errors.append(f"family {fam_name} rung {i}: exercise '{ex_id}' unknown")
                elif rung_ex.family != fam_name or rung_ex.rung != i:
                    errors.append(
                        f"family {fam_name} rung {i}: exercise '{ex_id}' declares {ex.family}/{ex.rung}"
                    )
    for g in cfg.profile.goals.long_term:
        for sk in g.prerequisite_skills:
            if sk not in cfg.skills.skills:
                errors.append(f"goal {g.id}: prerequisite skill '{sk}' not in skills.yaml")
        for fam in g.prerequisite_families:
            if fam not in cfg.progressions.families:
                errors.append(f"goal {g.id}: prerequisite family '{fam}' unknown")
        if g.kind == "race_time" and not g.target_time:
            errors.append(f"goal {g.id}: race_time needs target_time")
        if g.kind == "open_percentile" and g.top_pct is None:
            errors.append(f"goal {g.id}: open_percentile needs top_pct")
    errors += _check_training(cfg)
    if errors:
        raise ValueError("config inconsistent:\n  " + "\n  ".join(errors))


def _check_training(cfg: Config) -> list[str]:
    """Every exercise, family, item set, session and week template referenced by training/season config must exist."""
    tr, errors = cfg.training, []

    def item(where, it):
        if it.exercise and it.exercise not in cfg.library:
            errors.append(f"{where}: exercise '{it.exercise}' not in exercises.yaml")
        if it.deload_exercise and it.deload_exercise not in cfg.library:
            errors.append(f"{where}: deload_exercise '{it.deload_exercise}' not in exercises.yaml")
        if it.family and it.family not in cfg.progressions.families:
            errors.append(f"{where}: family '{it.family}' not in movement_progressions.yaml")

    for table in ("warmups", "cooldowns", "item_sets"):
        for name, s in getattr(tr, table).items():
            if s.same_as and s.same_as not in getattr(tr, table):
                errors.append(f"training.{table}.{name}: same_as '{s.same_as}' missing")
            for it in s.items:
                item(f"training.{table}.{name}", it)
    for name, pool in tr.metcon_pools.items():
        for it in pool.movements:
            item(f"training.metcon_pools.{name}", it)
    for muscle, ex in tr.fillers.items():
        if ex not in cfg.library:
            errors.append(f"training.fillers.{muscle}: '{ex}' not in exercises.yaml")
    for ex in tr.skill_practice.fallback:
        if ex not in cfg.library:
            errors.append(f"training.skill_practice.fallback: '{ex}' not in exercises.yaml")
    for rule_list in tr.rules.required_warmup.values():
        for ex in rule_list:
            if ex not in cfg.library:
                errors.append(f"training.rules.required_warmup: '{ex}' not in exercises.yaml")
    for name, st in tr.sessions.items():
        if st.warmup and st.warmup not in tr.warmups:
            errors.append(f"training.sessions.{name}: warmup '{st.warmup}' missing")
        if st.cooldown and st.cooldown not in tr.cooldowns:
            errors.append(f"training.sessions.{name}: cooldown '{st.cooldown}' missing")
        for b in st.blocks:
            for it in b.items:
                item(f"training.sessions.{name}", it)
            if b.use and b.use not in tr.item_sets:
                errors.append(f"training.sessions.{name}: item set '{b.use}' missing")
            if b.generate == "metcon" and b.pool not in tr.metcon_pools:
                errors.append(f"training.sessions.{name}: metcon pool '{b.pool}' missing")
    for name, days in tr.week_templates.items():
        if len(days) != 7:
            errors.append(f"training.week_templates.{name}: needs 7 days (Mon..Sun)")
        for role in days:
            if role not in tr.sessions:
                errors.append(f"training.week_templates.{name}: session '{role}' missing")
    for wt in (cfg.season.season.baseline_week, cfg.season.season.transition_week):
        if wt not in tr.week_templates:
            errors.append(f"season: week template '{wt}' missing")
    for spec in cfg.season.blocks:
        for wtype, tpl in spec.weeks.items():
            if tpl not in tr.week_templates:
                errors.append(f"season block {spec.key}: week template '{tpl}' ({wtype}) missing")
        for t in [*spec.tests, *spec.goal.focus_tests, *(g.test for g in spec.goal.guardrails)]:
            if t not in cfg.tests.tests:
                errors.append(f"season block {spec.key}: test '{t}' not in tests.yaml")
        for ml in spec.main_lifts:
            if ml.family and ml.family not in cfg.progressions.families:
                errors.append(f"season block {spec.key}: family '{ml.family}' unknown")
            if ml.exercise_id and ml.exercise_id not in cfg.library:
                errors.append(f"season block {spec.key}: exercise '{ml.exercise_id}' unknown")
    for sk_id, sk in cfg.skills.skills.items():
        for d in sk.drills:
            if d not in cfg.library:
                errors.append(f"skills.{sk_id}: drill '{d}' not in exercises.yaml")
    for lib_ex in cfg.library.exercises.values():
        if lib_ex.estimate_from and lib_ex.estimate_from.exercise not in cfg.library:
            errors.append(f"exercise {lib_ex.id}: estimate_from '{lib_ex.estimate_from.exercise}' unknown")
    for tid, tdef in cfg.tests.tests.items():
        for key in ("exercise", "family"):
            v = tdef.session.get(key)
            if v and v not in (cfg.library.exercises if key == "exercise" else cfg.progressions.families):
                errors.append(f"tests.{tid}: session {key} '{v}' unknown")
        if tdef.slot not in {k for sched in cfg.tests.schedule.values() for k in sched}:
            errors.append(f"tests.{tid}: slot '{tdef.slot}' not in tests.yaml schedule")
    return errors
