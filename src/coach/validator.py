"""`coach validate`: the guardrails every plan must pass before it is saved or pushed.

Each violation carries a stable rule code so Claude (and tests) can see exactly what to fix.
"""

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field

from coach.config import Config
from coach.engine import deloads as dl
from coach.engine import macrocycle as macro_engine
from coach.engine import movement as mv
from coach.engine import sessions as S
from coach.engine.running import RampRules, allowed_increase_cap, long_run_fraction_ok
from coach.engine.weather import in_daylight
from coach.models import BlockOutline, Macrocycle, MovementReadiness, Session, WeekPlan
from coach.models.records import JointFlag

FORBIDDEN_BACK_TO_BACK = [
    ("glycolytic", "glycolytic"),
    ("glycolytic", "run_quality"),
    ("run_quality", "glycolytic"),
    ("run_quality", "run_quality"),
    ("lower_heavy", "lower_heavy"),
    ("long_run", "run_quality"),
    ("run_quality", "long_run"),
    ("glycolytic", "long_run"),
]
MCGILL = {"mcgill_curl_up", "side_plank", "bird_dog"}
NON_TRAINING = {"rest"}
EXEMPT_STRUCTURE = {"rest", "recovery"}
DELOAD_TYPES = {"deload", "transition", "taper", "reset"}
NO_VOLUME_RULE_TYPES = {"taper", "transition", "baseline", "reset"}


@dataclass
class Violation:
    code: str
    message: str
    session_id: str | None = None

    def __str__(self) -> str:
        where = f" [{self.session_id}]" if self.session_id else ""
        return f"{self.code}{where}: {self.message}"


@dataclass
class ValidationContext:
    cfg: Config
    movement: MovementReadiness
    outline: BlockOutline | None = None
    joint_flags: list[JointFlag] = field(default_factory=list)
    health: dict = field(default_factory=dict)
    trailing_miles: list[float] = field(default_factory=list)
    threshold_pace: float = S.DEFAULT_THRESHOLD_PACE
    previous_session: Session | None = None  # last session of the previous week (back-to-back rule)
    previous_long_run: float | None = None  # longest run of the last normal week (long-run growth rule)
    week_type_override: str | None = None


def _restricted_tags(ctx: ValidationContext) -> dict[str, str]:
    out = {}
    for f in ctx.joint_flags:
        for t in f.restricted_tags:
            out[t] = f.region
    return out


def _illness_on(day: dt.date, ctx: ValidationContext, plan: WeekPlan | None) -> str | None:
    ill = ctx.health.get("illness")
    if ill:
        start = dt.date.fromisoformat(ill["start"])
        end = (
            dt.date.fromisoformat(ill["resolved_on"]) - dt.timedelta(days=1)
            if ill.get("resolved_on")
            else dt.date.max
        )
        if start <= day <= end:
            return ill.get("symptoms", "below_neck")
    if plan and day in plan.illness_dates:
        return "below_neck"
    return None


def _active_red_flags(ctx: ValidationContext, day: dt.date) -> list[str]:
    out = []
    for rf in ctx.health.get("red_flags", []):
        start = dt.date.fromisoformat(rf["date"])
        if (
            start <= day
            and not rf.get("cleared_on")
            or rf.get("cleared_on")
            and start <= day < dt.date.fromisoformat(rf["cleared_on"])
        ):
            out.append(rf["flag"])
    return out


def validate_session(
    s: Session, ctx: ValidationContext, week_type: str = "training", plan: WeekPlan | None = None
) -> list[Violation]:
    cfg = ctx.cfg
    lib = cfg.library
    v: list[Violation] = []
    restricted = _restricted_tags(ctx)
    available = cfg.equipment.available(s.location, cfg.profile.travel_equipment)

    # --- health gates ---
    flags = _active_red_flags(ctx, s.date)
    if flags and s.type not in NON_TRAINING:
        v.append(
            Violation(
                "RED_FLAG",
                f"active red flag ({', '.join(flags)}): no training until cleared by a doctor",
                s.id,
            )
        )
    illness = _illness_on(s.date, ctx, plan)
    if illness == "below_neck" and s.type not in NON_TRAINING:
        v.append(Violation("ILLNESS", "below-the-neck illness: no training until symptoms resolve", s.id))
    if illness == "above_neck" and s.type not in {"rest", "recovery", "run_easy"}:
        v.append(Violation("ILLNESS", "above-the-neck symptoms: easy movement only", s.id))

    if s.type in NON_TRAINING:
        return v

    # --- structure ---
    if s.type not in EXEMPT_STRUCTURE:
        if not s.blocks or s.blocks[0].kind != "warmup" or not s.blocks[0].items:
            v.append(Violation("WARMUP_COOLDOWN", "session must start with a warm-up block", s.id))
        if not s.blocks or s.blocks[-1].kind != "cooldown" or not (s.blocks[-1].items or s.blocks[-1].run):
            v.append(Violation("WARMUP_COOLDOWN", "session must end with a cool-down block", s.id))
    if S.is_lower_body(s, lib) and s.type not in EXEMPT_STRUCTURE:
        warm = {it.exercise_id for b in s.blocks if b.kind == "warmup" for it in b.items}
        if not warm >= MCGILL:
            v.append(
                Violation(
                    "WARMUP_MCGILL",
                    f"lower-body day needs McGill Big 3 in the warm-up (missing {sorted(MCGILL - warm)})",
                    s.id,
                )
            )
    ranks = [
        S.block_rank(b.kind, b.test_id, cfg.tests) for b in s.blocks if b.kind not in {"warmup", "cooldown"}
    ]
    if any(b > a for a, b in zip(ranks[1:], ranks, strict=False)):
        order = " -> ".join(b.kind for b in s.blocks)
        v.append(
            Violation(
                "SESSION_ORDER",
                f"order must be speed/power -> heavy strength -> hypertrophy -> conditioning (got {order})",
                s.id,
            )
        )
    for i, b in enumerate(s.blocks):
        if b.kind == "warmup" and i != 0:
            v.append(Violation("SESSION_ORDER", "warm-up must come first", s.id))
        if b.kind == "cooldown" and i != len(s.blocks) - 1:
            v.append(Violation("SESSION_ORDER", "cool-down must come last", s.id))

    # --- exercises ---
    fatiguing_seen = False
    for b in s.blocks:
        items = list(b.items) + (list(b.metcon.movements) if b.metcon else [])
        for it in items:
            ex = lib.get(it.exercise_id)
            if ex is None:
                v.append(
                    Violation("EXERCISE_UNKNOWN", f"'{it.exercise_id}' is not in config/exercises.yaml", s.id)
                )
                continue
            ok, why = mv.allowed(ex, ctx.movement)
            if not ok:
                v.append(Violation("RUNG_ABOVE", why, s.id))
            if ex.family is not None and ex.rung is not None and it.rir is not None:
                fam = cfg.progressions.families[ex.family]
                cap = fam.rungs[min(ex.rung, len(fam.rungs) - 1)].min_rir
                if it.rir < cap and b.kind != "test":
                    v.append(
                        Violation(
                            "RUNG_CAP",
                            f"{ex.name} at {it.rir:g} RIR is above the rung's effort cap ({cap:g} RIR)",
                            s.id,
                        )
                    )
            hit = [t for t in ex.tags if t in restricted]
            if hit:
                v.append(
                    Violation(
                        "JOINT_RESTRICTED",
                        f"{ex.name} uses {hit} restricted by the active {restricted[hit[0]]} flag",
                        s.id,
                    )
                )
            missing = [e for e in ex.equipment if e not in available]
            if missing:
                v.append(
                    Violation("EQUIPMENT", f"{ex.name} needs {missing}, not available at {s.location}", s.id)
                )
            if (
                week_type in DELOAD_TYPES
                and b.kind not in {"test", "warmup"}
                and ex.has_tag("eccentric_heavy", "high_impact")
            ):
                v.append(
                    Violation(
                        "DELOAD_ECCENTRIC",
                        f"deload week keeps {ex.name} (eccentric-heavy/high-impact): swap to {ex.deload_swap or 'a concentric option'}",
                        s.id,
                    )
                )
            if ex.skill:
                sk = cfg.skills.skills.get(ex.skill)
                if sk and not sk.competent:
                    if b.metcon is not None and it in b.metcon.movements:
                        v.append(
                            Violation(
                                "SKILL_READINESS",
                                f"{ex.name} is not competent yet ({sk.levels[sk.current_level]}): not allowed in a metcon",
                                s.id,
                            )
                        )
                    elif fatiguing_seen:
                        v.append(
                            Violation(
                                "SKILL_READINESS", f"{ex.name} practice must come before fatiguing work", s.id
                            )
                        )
        if b.kind in {"strength", "hypertrophy", "conditioning", "run"} or b.metcon is not None:
            fatiguing_seen = True
        if week_type in DELOAD_TYPES and b.kind != "test":
            for seg in b.run:
                if seg.terrain == "downhill":
                    v.append(
                        Violation(
                            "DELOAD_ECCENTRIC", f"deload week keeps downhill running ({seg.label})", s.id
                        )
                    )

    # --- run location / daylight ---
    home = cfg.profile.identity.home
    is_track_or_quality = s.location == "track" or (
        s.location == "outdoor" and bool(S.categories(s, lib, cfg.tests) & {"run_quality"})
    )
    if is_track_or_quality and not in_daylight(s.date, s.start_time, s.expected_minutes, home.lat, home.lon):
        v.append(Violation("DAYLIGHT", "track/quality work must fit inside daylight", s.id))
    return v


def validate_week(plan: WeekPlan, ctx: ValidationContext) -> list[Violation]:
    cfg = ctx.cfg
    lib = cfg.library
    th = cfg.profile.thresholds
    week_type = ctx.week_type_override or plan.week_type
    v: list[Violation] = []

    for s in plan.sessions:
        if not (plan.start <= s.date <= plan.end):
            v.append(Violation("WEEK_DATES", f"session dated {s.date} is outside week {plan.week_id}", s.id))
        v.extend(validate_session(s, ctx, week_type, plan))

    by_date: dict[dt.date, list[Session]] = {}
    for s in plan.sessions:
        if s.type not in NON_TRAINING:
            by_date.setdefault(s.date, []).append(s)
    two_a_days = bool(cfg.profile.schedule.model_extra.get("two_a_days", False))  # type: ignore[union-attr]
    for day, ss in by_date.items():
        if len(ss) > 1 and not two_a_days:
            v.append(
                Violation(
                    "TWO_A_DAY",
                    f"{len(ss)} sessions on {day}: one session per day unless the athlete asks",
                    ss[1].id,
                )
            )
        # >= 6 h between endurance and hypertrophy on the same day
        for a in ss:
            for b in ss:
                if a is b:
                    continue
                ca, cb = S.categories(a, lib, cfg.tests), S.categories(b, lib, cfg.tests)
                if "endurance" in ca and "hypertrophy" in cb:
                    gap = abs((S.start_dt(a) - S.start_dt(b)).total_seconds()) / 3600
                    if gap < 6:
                        v.append(
                            Violation(
                                "SPACING_6H",
                                f"endurance and hypertrophy sessions only {gap:.1f} h apart",
                                b.id,
                            )
                        )

    # --- spacing across days ---
    ordered = sorted((s for s in plan.sessions if s.type not in NON_TRAINING), key=lambda s: s.date)
    if ctx.previous_session is not None:
        ordered = [ctx.previous_session, *ordered]
    cats = {id(s): S.categories(s, lib, cfg.tests) for s in ordered}
    for a, b in zip(ordered, ordered[1:], strict=False):
        if (b.date - a.date).days != 1:
            continue
        for x, y in FORBIDDEN_BACK_TO_BACK:
            if x in cats[id(a)] and y in cats[id(b)]:
                v.append(Violation("BACK_TO_BACK", f"{a.date:%a} {x} followed by {b.date:%a} {y}", b.id))
        if "long_run" in cats[id(b)] and S.has_hard_lower_lifting(a, lib):
            v.append(
                Violation(
                    "LONG_RUN_LOWER_24H", "hard lower-body lifting within 24 h before the long run", a.id
                )
            )

    # --- running volume ---
    miles = S.week_miles(plan, ctx.threshold_pace)
    long_run = S.long_run_miles(plan, ctx.threshold_pace)
    exempt = week_type in NO_VOLUME_RULE_TYPES or bool(plan.illness_dates)
    if not exempt:
        r = cfg.profile.running
        cap = allowed_increase_cap(ctx.trailing_miles, RampRules(start_miles=r.ramp_start_miles))
        if miles > cap + 0.5:
            v.append(
                Violation(
                    "RUN_INCREASE",
                    f"{miles:.1f} mi exceeds +{th.weekly_run_increase_pct:g}% over the trailing 3-week average (cap {cap:.1f} mi)",
                )
            )
        if (
            ctx.previous_long_run is not None
            and long_run > ctx.previous_long_run + th.long_run_max_increase_mi + 0.05
        ):
            v.append(
                Violation(
                    "LONG_RUN_INCREASE",
                    f"long run {long_run:.1f} mi grows more than {th.long_run_max_increase_mi:g} mi "
                    f"over the last normal week's {ctx.previous_long_run:.1f} mi",
                )
            )
        ok, limit = long_run_fraction_ok(long_run, miles, th)
        if not ok:
            v.append(
                Violation(
                    "LONG_RUN_FRACTION",
                    f"long run {long_run:.1f} mi is {long_run / miles:.0%} of {miles:.1f} mi (limit {limit:.0%})",
                )
            )

    # --- outline conformance ---
    ol = ctx.outline
    devs = {d.field for d in plan.deviations if d.reason.strip()}
    if ol is not None:
        target = ol.week(plan.week_index)
        if target is None:
            v.append(
                Violation("OUTLINE_CONTRADICTION", f"week {plan.week_index} is not in outline {ol.block_id}")
            )
        else:
            if target.type != plan.week_type and "week_type" not in devs:
                v.append(
                    Violation(
                        "OUTLINE_CONTRADICTION",
                        f"outline says {target.type} week, plan says {plan.week_type} (state a reason)",
                    )
                )
            if (
                target.run_miles > 0
                and abs(miles - target.run_miles) / target.run_miles > 0.15
                and "run_miles" not in devs
            ):
                v.append(
                    Violation(
                        "OUTLINE_CONTRADICTION",
                        f"run volume {miles:.1f} mi vs outline {target.run_miles:.1f} mi (state a reason)",
                    )
                )
            present: set[str] = set()
            for s in plan.sessions:
                present |= S.categories(s, lib, cfg.tests)
                if s.tests:
                    present.add("test")
                if s.type in {"competition", "race"}:
                    present.add(s.type)
            missing = [k for k in target.key_sessions if k not in present]
            if missing and "key_sessions" not in devs:
                v.append(
                    Violation("OUTLINE_CONTRADICTION", f"key sessions missing: {missing} (state a reason)")
                )
            if target.hard_sets and "hard_sets" not in devs and not plan.illness_dates:
                sets = S.hard_sets(plan, lib)
                for muscle, (lo, hi) in target.hard_sets.items():
                    have = sets.get(muscle, 0)
                    if not (lo <= have <= hi):
                        v.append(
                            Violation(
                                "HARD_SETS",
                                f"{muscle}: {have:g} hard sets, block range for this week is {lo}-{hi}",
                            )
                        )
            if not plan.illness_dates and week_type not in {"baseline", "transition", "reset"}:
                doses = S.pillar_doses(plan, lib, cfg.tests)
                low = []
                for p, pp in ol.pillars.items():
                    need = pp.deload_med if week_type in DELOAD_TYPES | {"competition"} else pp.med
                    if doses.get(p, 0) < need:
                        low.append(f"{p} {doses.get(p, 0):g} < {need:g}")
                if low and "pillars" not in devs:
                    v.append(
                        Violation("PILLAR_MED", "pillars below minimum effective dose: " + ", ".join(low))
                    )
    has_tests = any(s.tests for s in plan.sessions)
    if has_tests and plan.week_type not in {"baseline", "transition"} and "tests" not in devs:
        v.append(Violation("TEST_WEEK", "tests are only scheduled in the baseline or transition week"))
    return v


def validate_outline(ol: BlockOutline) -> list[Violation]:
    v = []
    types = [w.type for w in sorted(ol.weeks, key=lambda w: w.week_index)]
    longest = dl.max_run_without_deload(types)
    if longest > 4:
        v.append(
            Violation(
                "OUTLINE_DELOAD", f"{longest} consecutive weeks without a deload (max 4 in any 5-week span)"
            )
        )
    if not ol.weeks or ol.weeks[-1].type != "transition" or ol.transition_week != ol.weeks[-1].week_index:
        v.append(Violation("OUTLINE_DELOAD", "the last week of the block must be the transition week"))
    for w in ol.weeks:
        if (w.week_index in ol.deload_weeks) != (w.type == "deload"):
            v.append(Violation("OUTLINE_DELOAD", f"week {w.week_index}: deload_weeks and week type disagree"))
    expected = (ol.end - ol.start).days // 7 + 1
    if len(ol.weeks) != expected:
        v.append(Violation("OUTLINE_DELOAD", f"outline has {len(ol.weeks)} weeks, block spans {expected}"))
    return v


def validate_macrocycle(m: Macrocycle) -> list[Violation]:
    return [Violation("MACRO_GAP", e) for e in macro_engine.check(m)]


def validate_movement_change(
    before: MovementReadiness, after: MovementReadiness, cfg: Config
) -> list[Violation]:
    return [Violation("RUNG_CHANGE", e) for e in mv.validate_change(before, after, cfg.progressions)]


# ---------- config / threshold lock ----------
def thresholds_fingerprint(cfg: Config) -> str:
    p = cfg.profile
    payload = {
        "thresholds": p.thresholds.model_dump(mode="json"),
        "weather": p.weather.model_dump(mode="json"),
        "nutrition": {
            k: v
            for k, v in p.nutrition.model_dump(mode="json").items()
            if k not in {"supplements", "supplements_note"}
        },
        "progression_rules": cfg.progressions.rules.model_dump(mode="json"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def validate_config_lock(cfg: Config, lock: dict | None, approved_ids: set[str]) -> list[Violation]:
    fp = thresholds_fingerprint(cfg)
    if lock is None:
        return [
            Violation(
                "CONFIG_UNAPPROVED",
                "no config lock recorded: run `coach approve initial-config` once after setup",
            )
        ]
    if lock.get("fingerprint") != fp:
        return [
            Violation(
                "CONFIG_UNAPPROVED",
                "thresholds/rules changed without an approved proposal (fingerprint mismatch)",
            )
        ]
    if lock.get("approved_by") not in approved_ids | {"initial"}:
        return [
            Violation(
                "CONFIG_UNAPPROVED",
                f"config lock cites proposal {lock.get('approved_by')} which is not approved",
            )
        ]
    return []
