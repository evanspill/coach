"""plan-block fallback: approved goal + macro block -> block outline (weeks, deloads, targets, pillars)."""

import datetime as dt
import math

from coach.context import Context
from coach.engine.deloads import plan_deloads
from coach.engine.running import RampRules, ramp_targets
from coach.models import BlockGoal, BlockOutline, MacroBlock, WeekTarget
from coach.models.plans import MainLift, PillarPlan

TRAINING_SETS = {
    1: {
        "quads": (8, 16),
        "hamstrings": (6, 14),
        "glutes": (8, 18),
        "chest": (6, 14),
        "back": (10, 20),
        "shoulders": (6, 16),
    },
    2: {
        "quads": (12, 16),
        "hamstrings": (10, 16),
        "glutes": (12, 20),
        "chest": (12, 16),
        "back": (12, 18),
        "shoulders": (12, 18),
    },
    3: {
        "quads": (4, 9),
        "hamstrings": (4, 9),
        "glutes": (4, 12),
        "chest": (4, 8),
        "back": (4, 10),
        "shoulders": (4, 10),
    },
    4: {
        "quads": (2, 8),
        "hamstrings": (2, 8),
        "glutes": (2, 10),
        "chest": (2, 8),
        "back": (2, 10),
        "shoulders": (2, 10),
    },
}
RUN_RANGE = {1: (12.0, 15.0), 2: (15.0, 25.0), 3: (35.0, 50.0), 4: (20.0, 40.0)}
KEY_TRAINING = {
    1: ["lower_heavy", "upper_heavy", "glycolytic", "long_run"],
    2: ["lower_heavy", "upper_heavy", "glycolytic", "run_quality", "long_run"],
    3: ["run_quality", "glycolytic", "long_run", "lower_heavy"],
    4: ["run_quality", "long_run"],
}
PILLARS = {
    1: {
        "neural": PillarPlan(mode="maintain", description="primers 2x/wk", med=1, deload_med=1),
        "force": PillarPlan(
            mode="build", description="force: 4 d/wk, heavy 3-5 reps at 1-2 RIR", med=3, deload_med=2
        ),
        "glycolytic": PillarPlan(mode="build", description="Open peak: 2-3 metcons/wk", med=2, deload_med=1),
        "aerobic": PillarPlan(
            mode="maintain", description="12-15 mi/wk + erg in bad weather", med=90, deload_med=60
        ),
    },
    2: {
        "neural": PillarPlan(mode="maintain", description="primers", med=1, deload_med=1),
        "force": PillarPlan(
            mode="build", description="hypertrophy: 4 d/wk, 12-16 hard sets/muscle", med=3, deload_med=2
        ),
        "glycolytic": PillarPlan(mode="maintain", description="1 metcon + 1 threshold", med=2, deload_med=1),
        "aerobic": PillarPlan(mode="build", description="ramp 15 -> 25 mi/wk", med=150, deload_med=90),
    },
    3: {
        "neural": PillarPlan(mode="maintain", description="strides/sprints 1x/wk", med=1, deload_med=1),
        "force": PillarPlan(
            mode="maintain",
            description="2-3 d/wk, 4-6 heavy sets/muscle; sleds/trap bar instead of axial squats",
            med=2,
            deload_med=1,
        ),
        "glycolytic": PillarPlan(mode="build", description="Hyrox: compromised running", med=2, deload_med=1),
        "aerobic": PillarPlan(mode="build", description="35-50 mi/wk + long run", med=300, deload_med=180),
    },
    4: {
        "neural": PillarPlan(mode="sharpen", description="short race-pace bursts", med=1, deload_med=0),
        "force": PillarPlan(mode="maintain", description="2 d/wk light (flush)", med=1, deload_med=1),
        "glycolytic": PillarPlan(mode="taper", description="race execution", med=1, deload_med=0),
        "aerobic": PillarPlan(mode="taper", description="taper + flush", med=150, deload_med=60),
    },
}
MAIN_LIFTS = {
    1: [
        MainLift(
            family="hinge",
            scheme="4 x 3-5 @ 2 RIR (rung cap)",
            progression="+2.5% when all reps hit at target RIR",
        ),
        MainLift(family="squat", scheme="4 x 5 @ 2 RIR", progression="+2.5% when all reps hit"),
        MainLift(family="press", scheme="4 x 5 @ 2 RIR", progression="+1 DB step when all reps hit"),
        MainLift(
            exercise_id="strict_pull_up", scheme="4 x 5 (add load at 3 x 8)", progression="reps then load"
        ),
    ],
    2: [
        MainLift(family="hinge", scheme="3 x 6-8 @ 2 RIR", progression="double progression"),
        MainLift(family="squat", scheme="4 x 6-8 @ 2 RIR", progression="double progression"),
        MainLift(family="press", scheme="4 x 8-10 @ 2 RIR", progression="double progression"),
        MainLift(
            exercise_id="chest_supported_db_row", scheme="4 x 10-12 @ 2 RIR", progression="double progression"
        ),
    ],
    3: [
        MainLift(family="hinge", scheme="3 x 4-5 @ 2-3 RIR", progression="hold load, maintain"),
        MainLift(exercise_id="sled_push", scheme="4 x 25 m heavy", progression="maintain"),
        MainLift(family="press", scheme="3 x 5 @ 2 RIR", progression="maintain"),
    ],
    4: [MainLift(family="hinge", scheme="2 x 3 @ 3 RIR (flush)", progression="none")],
}
MACROFACTOR = {
    "cut": "MacroFactor: weight loss ~0.5% BW/week (coached, moderate); protein high",
    "recomp": "MacroFactor: maintenance-to-slight deficit (recomposition); protein high",
    "lean_gain": "MacroFactor: lean gain ~0.25% BW/week",
    "maintenance": "MacroFactor: maintenance, fuel-matched to training load",
}


def calorie_phase_from(ctx: Context, block: MacroBlock) -> tuple[str, str]:
    if block.index >= 3:
        return "maintenance", "marathon build/taper: fuel-matched maintenance"
    bfs = [
        m.body_fat_pct
        for m in ctx.state.daily_metrics(ctx.today - dt.timedelta(days=14), ctx.today)
        if m.body_fat_pct
    ]
    bf = sum(bfs) / len(bfs) if bfs else None
    goal_lo, goal_hi = ctx.cfg.profile.goals.body_composition.target_body_fat_pct
    if bf is None:
        return "recomp", "no body-fat trend yet"
    if bf > goal_hi + 3:
        return "cut", f"body fat trend {bf:.1f}% vs goal {goal_lo:g}-{goal_hi:g}%"
    if bf > goal_hi:
        return "recomp", f"body fat trend {bf:.1f}% is close to goal {goal_lo:g}-{goal_hi:g}%"
    return "lean_gain", f"body fat trend {bf:.1f}% at goal; weight below 200 lb target"


def week_types(block: MacroBlock) -> list[str]:
    n = block.weeks
    comp_idx = {(d - block.start).days // 7 + 1 for d in block.competition_weeks}
    taper_idx = {(d - block.start).days // 7 + 1 for d in block.taper_weeks}
    reset_idx = {(d - block.start).days // 7 + 1 for d in block.reset_weeks}
    types = ["training"] * n
    for i in range(1, n + 1):
        if i in taper_idx:
            types[i - 1] = "taper"
        elif i in reset_idx:
            types[i - 1] = "reset"
        elif i in comp_idx:
            types[i - 1] = "competition"
    types[-1] = "transition"
    if not taper_idx:
        for d in plan_deloads(n, comp_idx):
            if types[d - 1] == "training":
                types[d - 1] = "deload"
    return types


def deload_ranges(ranges: dict[str, tuple[int, int]]) -> dict[str, tuple[int, int]]:
    return {m: (max(1, math.floor(lo * 0.4)), max(3, math.ceil(hi * 0.65))) for m, (lo, hi) in ranges.items()}


def targets_for(block_index: int, wtype: str) -> tuple[list[str], dict[str, tuple[int, int]]]:
    ranges = TRAINING_SETS[block_index]
    if wtype == "training":
        return KEY_TRAINING[block_index], ranges
    if wtype == "deload":
        return ["lower_heavy", "long_run"] if block_index < 3 else ["long_run"], deload_ranges(ranges)
    if wtype == "competition":
        return (["competition"] if block_index == 1 else ["race"]), {
            m: (1, hi) for m, (_lo, hi) in ranges.items()
        }
    if wtype == "transition":
        return ["test"], {}
    return [], {}


def build_outline(
    ctx: Context, block: MacroBlock, goal: BlockGoal | None, trailing: list[float] | None = None
) -> BlockOutline:
    types = week_types(block)
    lo, hi = RUN_RANGE[block.index]
    trailing = trailing if trailing is not None else ctx.trailing_miles(block.start)
    r = ctx.cfg.profile.running
    rules = RampRules(start_miles=r.ramp_start_miles)
    if trailing:
        start = max(r.ramp_start_miles[0], min(hi, round(sum(trailing[-3:]) / len(trailing[-3:]) * 1.1, 1)))
    else:
        start = r.ramp_start_miles[0]
    if block.index == 4:
        start = max(start, lo)
    miles = ramp_targets(len(types), types, start, hi, rules, trailing)
    if block.index == 4:
        base = trailing[-1] if trailing else lo
        taper = [0.8, 0.6, 0.4]
        miles = []
        t = 0
        for wt in types:
            if wt == "taper":
                miles.append(round(base * taper[min(t, 2)], 1))
                t += 1
            else:
                miles.append(round(base * 0.35, 1))
    weeks = []
    th = ctx.cfg.profile.thresholds
    for i, wt in enumerate(types, start=1):
        keys, ranges = targets_for(block.index, wt)
        frac = (
            th.long_run_max_fraction
            if miles[i - 1] >= th.long_run_rule_min_weekly_miles
            else th.long_run_max_fraction_low_volume
        )
        weeks.append(
            WeekTarget(
                week_index=i,
                start=block.start + dt.timedelta(weeks=i - 1),
                type=wt,  # type: ignore[arg-type]
                run_miles=miles[i - 1],
                long_run_miles=round(miles[i - 1] * (frac - 0.02), 1)
                if wt not in {"transition", "reset"}
                else None,
                key_sessions=keys,
                hard_sets=ranges,
                notes={
                    "competition": "Open week: attempt Friday after Thursday release",
                    "transition": "deload early, tests late",
                }.get(wt, ""),
            )
        )
    phase, why = (goal.calorie_phase, goal.calorie_phase_reason) if goal else calorie_phase_from(ctx, block)
    deloads = [i for i, t in enumerate(types, 1) if t == "deload"]
    return BlockOutline(
        block_id=block.id,
        name=block.name,
        focus=block.focus,
        start=block.start,
        end=block.end,
        goal_id=f"{block.id}-goal" if goal else None,
        main_lifts=MAIN_LIFTS[block.index],
        progression="Loads from recent e1RM; +2.5% when all target reps are hit at >= target RIR; hold after a miss; -5% after two misses. "
        "Deloads cut volume ~45% and keep intensity.",
        pillars=PILLARS[block.index],  # type: ignore[arg-type]
        weeks=weeks,
        deload_weeks=deloads,
        competition_weeks=[i for i, t in enumerate(types, 1) if t == "competition"],
        taper_weeks=[i for i, t in enumerate(types, 1) if t == "taper"],
        transition_week=len(types),
        calorie_phase=phase,  # type: ignore[arg-type]
        macrofactor_setting=f"{MACROFACTOR[phase]} ({why})" if why else MACROFACTOR[phase],
        variety="Main lifts fixed for the block; accessories, metcon formats, erg modality and run routes rotate weekly.",
        generated_by="fallback",
    )
