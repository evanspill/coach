"""plan-block fallback: approved goal + macro block + its spec in config/season.yaml -> block outline."""

import datetime as dt
import math

from coach.context import Context
from coach.engine.deloads import plan_deloads
from coach.engine.running import RampRules, ramp_targets
from coach.models import BlockGoal, BlockOutline, MacroBlock, WeekTarget
from coach.models.plans import Revision  # noqa: F401 - re-exported for callers
from coach.models.season import BlockSpec


def calorie_phase_from(ctx: Context, block: MacroBlock) -> tuple[str, str]:
    spec = ctx.cfg.season.spec(block.key)
    if spec.calorie_phase != "auto":
        return spec.calorie_phase, f"{spec.name}: {spec.calorie_phase} (season.yaml)"
    bfs = [
        m.body_fat_pct
        for m in ctx.state.daily_metrics(ctx.today - dt.timedelta(days=14), ctx.today)
        if m.body_fat_pct
    ]
    bf = sum(bfs) / len(bfs) if bfs else None
    bc = ctx.cfg.profile.goals.body_composition
    goal_lo, goal_hi = bc.target_body_fat_pct
    if bf is None:
        return "recomp", "no body-fat trend yet"
    if bf > goal_hi + 3:
        return "cut", f"body fat trend {bf:.1f}% vs goal {goal_lo:g}-{goal_hi:g}%"
    if bf > goal_hi:
        return "recomp", f"body fat trend {bf:.1f}% is close to goal {goal_lo:g}-{goal_hi:g}%"
    return "lean_gain", f"body fat trend {bf:.1f}% at goal; building toward {bc.target_weight_kg:g} kg"


def week_types(block: MacroBlock, deload_every: int = 4, earliest: int = 3) -> list[str]:
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
        for d in plan_deloads(n, comp_idx, every=deload_every, min_first=earliest):
            if types[d - 1] == "training":
                types[d - 1] = "deload"
    return types


def deload_ranges(ranges: dict[str, tuple[int, int]]) -> dict[str, tuple[int, int]]:
    return {m: (max(1, math.floor(lo * 0.4)), max(3, math.ceil(hi * 0.65))) for m, (lo, hi) in ranges.items()}


def targets_for(spec: BlockSpec, wtype: str) -> tuple[list[str], dict[str, tuple[int, int]]]:
    ranges = {m: tuple(v) for m, v in spec.hard_sets.items()}
    keys = spec.key_sessions.get(wtype)
    if wtype == "training":
        return keys or [], ranges  # type: ignore[return-value]
    if wtype == "deload":
        return keys if keys is not None else ["long_run"], deload_ranges(ranges)  # type: ignore[arg-type]
    if wtype == "competition":
        return keys or [], {m: (1, hi) for m, (_lo, hi) in ranges.items()}
    if wtype == "transition":
        return ["test"], {}
    return keys or [], {}


def build_outline(
    ctx: Context, block: MacroBlock, goal: BlockGoal | None, trailing: list[float] | None = None
) -> BlockOutline:
    spec = ctx.cfg.season.spec(block.key)
    dl = ctx.cfg.season.season.deload
    types = week_types(block, dl.every, dl.earliest_week)
    lo, hi = spec.run_miles
    trailing = trailing if trailing is not None else ctx.trailing_miles(block.start)
    r = ctx.cfg.profile.running
    rules = RampRules(start_miles=r.ramp_start_miles, deload_factor=dl.run_factor)
    if trailing:
        start = max(r.ramp_start_miles[0], min(hi, round(sum(trailing[-3:]) / len(trailing[-3:]) * 1.1, 1)))
    else:
        start = r.ramp_start_miles[0]
    if "taper" in types:  # event block: volumes are fractions of the pre-taper level
        base = max(trailing[-1] if trailing else lo, lo)
        miles, t = [], 0
        for wt in types:
            if wt == "taper":
                miles.append(round(base * spec.taper_volumes[min(t, len(spec.taper_volumes) - 1)], 1))
                t += 1
            else:
                miles.append(round(base * spec.reset_volume, 1))
    else:
        miles = ramp_targets(len(types), types, start, hi, rules, trailing)
    th = ctx.cfg.profile.thresholds
    comp_race = ctx.cfg.profile.race(spec.competition_event) if spec.competition_event else None
    weeks = []
    for i, wt in enumerate(types, start=1):
        keys, ranges = targets_for(spec, wt)
        frac = (
            th.long_run_max_fraction
            if miles[i - 1] >= th.long_run_rule_min_weekly_miles
            else th.long_run_max_fraction_low_volume
        )
        note = {"transition": "deload early, tests late"}.get(wt, "")
        if wt == "competition" and comp_race:
            note = f"{comp_race.name} week"
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
                notes=note,
            )
        )
    phase, why = (goal.calorie_phase, goal.calorie_phase_reason) if goal else calorie_phase_from(ctx, block)
    setting = ctx.cfg.profile.nutrition.calorie_phase_settings.get(phase, phase)
    return BlockOutline(
        block_id=block.id,
        name=block.name,
        focus=block.focus,
        start=block.start,
        end=block.end,
        goal_id=f"{block.id}-goal" if goal else None,
        main_lifts=spec.main_lifts,
        progression="Loads from recent e1RM; +2.5% when all target reps are hit at >= target RIR; hold after a miss; -5% after two misses. "
        f"Deloads cut volume to ~{dl.volume_factor:.0%} and keep intensity.",
        pillars=spec.pillars,  # type: ignore[arg-type]
        weeks=weeks,
        deload_weeks=[i for i, t in enumerate(types, 1) if t == "deload"],
        competition_weeks=[i for i, t in enumerate(types, 1) if t == "competition"],
        taper_weeks=[i for i, t in enumerate(types, 1) if t == "taper"],
        transition_week=len(types),
        calorie_phase=phase,  # type: ignore[arg-type]
        macrofactor_setting=f"{setting} ({why})" if why else setting,
        variety="Main lifts fixed for the block; accessories, metcon formats, erg modality and run routes rotate weekly.",
        generated_by="fallback",
    )
