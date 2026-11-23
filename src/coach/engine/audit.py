"""Rule inventory for the re-evaluation audit (DECISIONS 104).

Every number or rule that changes what the athlete does is listed here: the config sections are walked
automatically, so a new threshold shows up as unreviewed without anyone remembering to add it, and the rules that
live in code are named in CODE_RULES. `coach audit` compares the inventory with the evidence records the coach has
written (athlete/data/evidence/) and says what to review next. Deterministic: it never judges the evidence itself.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any

from coach.config import Config


@dataclass(frozen=True)
class RuleRef:
    rule_id: str
    where: str
    value: Any
    description: str = ""
    safety: bool = False  # never loosened by an audit; always shown to the athlete when queued


# Safety-relevant rules: an audit may only make them clearer or stricter (skill rule), and the queue lists them.
SAFETY_RULES = {
    "thresholds.joint_red",
    "thresholds.joint_yellow",
    "thresholds.joint_flag_rating",
    "thresholds.joint_flag_consecutive",
    "thresholds.pain_rule_max",
    "thresholds.recovery_red_max",
    "thresholds.rhr_red_delta",
    "progressions.rules.max_session_pain_to_advance",
    "progressions.rules.regress_on_session_pain_above",
    "progressions.rules.regress_on_next_day_flare",
    "progressions.rules.pain_rule",
    "progressions.rules.region_flag_rating",
    "progressions.rules.region_flag_consecutive",
    "code.red_carry_48h",
    "code.sustained_red_replan",
}


# Rules that live in code, not config: id -> (where, what it does, version). The version is what `coach audit`
# compares with the evidence record: bump it whenever the rule's behaviour or constant changes, so the change shows
# up as `changed_since_review`. Keep in step with the code.
CODE_RULES: dict[str, tuple[str, str, str]] = {
    "code.red_carry_48h": (
        "coaching/skills/adjust_day.py",
        "the day after a Red day is Z1 + mobility too, only when the Red came from a joint rated at the Red level "
        "(v1 carried every Red; changed by the 2026-11-23 audit)",
        "v2",
    ),
    "code.red_accessory_halving_72h": (
        "coaching/skills/adjust_day.py",
        "accessory (hypertrophy) sets are halved for 72 h after a Red day",
        "v1",
    ),
    "code.sustained_red_replan": (
        "coaching/skills/adjust_day.py + replan",
        "sustained Red (thresholds.sustained_red_days in the window) hands off to replan (reactive deload)",
        "v1",
    ),
    "code.run_spike_cap": (
        "engine/validator.py + coaching/skills/plan_week.py",
        "no single run longer than the longest run of the last 30 days by more than thresholds.run_spike_max_pct "
        "(min step thresholds.run_spike_min_step_mi)",
        "v1",
    ),
    "code.rhr_7day_median": (
        "engine/readiness.py",
        "resting-HR trend = median of the last 7 days minus the median of the baseline window",
        "v1",
    ),
    "code.monotony_flag": (
        "coaching/skills/review.py",
        "weekly review flags training monotony > 2 (Foster)",
        "v1",
    ),
    "code.easy_share_flag": (
        "coaching/skills/review.py",
        "weekly review flags < 75% of running time easy over two weeks (80/20)",
        "v1",
    ),
    "code.energy_availability_flag": (
        "coaching/skills/review.py",
        "weekly review flags estimated energy availability < ~30 kcal/kg FFM/day",
        "v1",
    ),
    "code.two_a_day_gap_6h": (
        "engine/validator.py",
        ">= 6 h between endurance and hypertrophy on the same day (two-a-days)",
        "v1",
    ),
    "code.epley_e1rm": (
        "engine/testing.py",
        "estimated 1RM = weight x (1 + reps/30) from rep-max tests",
        "v1",
    ),
    "code.submax_threshold_pace": (
        "engine/testing.py",
        "threshold pace from a submax run = avg pace / 1.25 (low confidence)",
        "v1",
    ),
    "code.marathon_riegel": (
        "coaching/skills/assess.py",
        "race-time prediction with Riegel k = 1.06 (+10 min)",
        "v1",
    ),
    "code.goal_from_biggest_gap": (
        "coaching/skills/assess.py",
        "the block goal defaults to the focus test furthest from its benchmark",
        "v1",
    ),
}

# Config sections that hold rules (dotted path in the Config object -> label used in rule ids).
_SECTIONS = [
    ("profile.thresholds", "thresholds"),
    ("profile.weather", "weather"),
    ("profile.nutrition", "nutrition"),
    ("profile.running", "running"),
    ("training.rules", "training.rules"),
    ("training.skill_practice", "training.skill_practice"),
    ("season.season.deload", "season.deload"),
    ("progressions.rules", "progressions.rules"),
]
# Keys inside those sections that are data, not rules.
_SKIP = {
    "running.status",
    "running.default_zones",
    "running.marathon_prediction",
    "running.gait_analysis_recommended",
    "running.max_weekly_increase_pct",  # unused duplicate of thresholds.weekly_run_increase_pct
    "nutrition.supplements",  # context only: the coach never changes doses
    "nutrition.supplements_note",
}


def _get(obj: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        obj = obj.get(part) if isinstance(obj, dict) else getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def _as_dict(obj: Any) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    return dump() if dump else {}


def inventory(cfg: Config) -> list[RuleRef]:
    rules: list[RuleRef] = []
    for path, label in _SECTIONS:
        for key, value in _as_dict(_get(cfg, path)).items():
            rid = f"{label}.{key}"
            if rid in _SKIP:
                continue
            rules.append(RuleRef(rid, f"config {path}.{key}", value, safety=rid in SAFETY_RULES))
    for pillar, items in (cfg.benchmarks.get("pillars") or {}).items():
        for b in items:
            rules.append(
                RuleRef(
                    f"benchmarks.{b['test']}",
                    "config benchmarks.yaml",
                    b.get("target"),
                    f"{pillar} benchmark ({b.get('metric')}); {b.get('note', '')}".strip("; "),
                )
            )
    errors = {tid: t.typical_error_pct for tid, t in cfg.tests.tests.items()}
    rules.append(
        RuleRef(
            "tests.typical_error_pct",
            "config tests.yaml",
            errors,
            "test-retest noise per test: smaller changes are reported as noise",
        )
    )
    rules.append(
        RuleRef(
            "tests.goal_change_pct",
            "config tests.yaml",
            {tid: t.goal_change_pct for tid, t in cfg.tests.tests.items()},
            "default block-goal size per test",
        )
    )
    for rid, (where, what, version) in CODE_RULES.items():
        rules.append(RuleRef(rid, where, version, what, safety=rid in SAFETY_RULES))
    return sorted(rules, key=lambda r: r.rule_id)


def _norm(v: Any) -> Any:
    """Comparable form of a value (tuples and lists alike, dict order ignored)."""
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in sorted(v.items())}
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    return v


WEAK = {"practitioner", "theory", "none", "unknown"}


def _evidence_view(rec: Any) -> dict | None:
    """What `coach audit --full` shows next to each rule: where it came from and what supports it."""
    if rec is None:
        return None
    return {
        "origin": rec.origin,
        "level": rec.evidence_level,
        "verdict": rec.verdict,
        "sources": rec.source_counts(),
        "reviewed": rec.reviewed.isoformat(),
    }


def audit(cfg: Config, records: dict[str, Any], today: dt.date) -> dict:
    """records: rule_id -> EvidenceRecord. Returns the review queue, most urgent first."""
    inv = inventory(cfg)
    known = {r.rule_id for r in inv}
    changed, unreviewed, due, weak = [], [], [], []
    for r in inv:
        rec = records.get(r.rule_id)
        if rec is None:
            unreviewed.append(r.rule_id)
            continue
        if r.value is not None and _norm(rec.value_at_review) != _norm(r.value):
            changed.append({"rule_id": r.rule_id, "was": rec.value_at_review, "now": r.value})
        elif rec.review_after is not None and rec.review_after <= today:
            due.append(r.rule_id)
        if rec.evidence_level in WEAK and rec.impact == "high" and rec.verdict in {"keep", "keep_flagged"}:
            weak.append(r.rule_id)
    return {
        "rules": len(inv),
        "reviewed": len(inv) - len(unreviewed),
        "changed_since_review": changed,
        "unreviewed": unreviewed,
        "due": due,
        "weak_evidence_high_impact": weak,
        "orphaned_records": sorted(set(records) - known),  # a reviewed rule that no longer exists
        # safety rules in the queue: the verdict is always shown to the athlete, and may never loosen them
        "safety_rules_queued": sorted(
            {r.rule_id for r in inv if r.safety}
            & (
                {c["rule_id"] for c in changed}
                | set(unreviewed)
                | set(due)
                | set(weak)
                # a change/retire/trial verdict on a safety rule always reaches the athlete
                | {rid for rid, rec in records.items() if rec.verdict not in {"keep", "keep_flagged"}}
            )
        ),
        "inventory": [
            {
                "rule_id": r.rule_id,
                "where": r.where,
                "value": r.value,
                "description": r.description,
                "safety": r.safety,
                "evidence": _evidence_view(records.get(r.rule_id)),
            }
            for r in inv
        ],
    }
