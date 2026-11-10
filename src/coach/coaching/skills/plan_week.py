"""plan-week fallback: outline week target -> detailed sessions, from the week/session templates in
config/training.yaml and the block spec in config/season.yaml."""

import datetime as dt

from coach import clock
from coach.coaching.context import Context
from coach.coaching.fill import Filler
from coach.coaching.skills import design as D
from coach.coaching.skills.templates import build_session
from coach.engine import nutrition as nut
from coach.engine import testing as T
from coach.engine.running import RampRules, allowed_increase_cap
from coach.models import Deviation, Session, WeekPlan
from coach.models.season import BlockSpec


def tests_for_week(
    ctx: Context, week_type: str, spec: BlockSpec | None, next_spec: BlockSpec | None = None
) -> list[str]:
    """Baseline battery, or (transition) the outgoing block's tests + the next block's entry tests + always-tracked."""
    b = ctx.cfg.tests.batteries
    if week_type == "baseline":
        ids = list(b["baseline"])
        recent = ctx.trailing_miles(ctx.today, n=4)
        swaps = b.get("low_volume_swaps", {})
        if recent and swaps and sum(recent) / len(recent) < b.get("low_volume_miles", 6):
            ids = [swaps.get(t, t) for t in ids]
    else:
        ids = [
            *(spec.tests if spec else []),
            *(next_spec.tests if next_spec else []),
            *b.get("always_tracked", []),
        ]
        ids = list(dict.fromkeys(ids))
    tests = ctx.cfg.tests.tests
    return [t for t in ids if t in tests and not tests[t].passive and tests[t].session]


def week_roles(ctx: Context, week_type: str, spec: BlockSpec | None, week_start: dt.date) -> list[str]:
    season = ctx.cfg.season.season
    tpl = ctx.cfg.training.week_templates
    if week_type == "baseline":
        return tpl[season.baseline_week]
    if week_type == "transition":
        return tpl[spec.weeks.get("transition", season.transition_week) if spec else season.transition_week]
    assert spec is not None
    if spec.length.event and "race" in spec.weeks:
        race = ctx.cfg.profile.race(spec.length.event.kind)
        if race and week_start <= race.date <= week_start + dt.timedelta(days=6):
            return tpl[spec.weeks["race"]]
    name = spec.weeks.get(week_type) or spec.weeks.get("training") or next(iter(spec.weeks.values()))
    return tpl[name]


RATIONALE = {
    "baseline": "Baseline week: full test battery spread so strength, run and engine tests fall on separate days.",
    "training": "Follows the block outline: main lifts fixed, accessories/metcons rotate.",
    "deload": "Planned deload: volume cut, intensity kept, eccentric/high-impact work swapped.",
    "competition": "Competition week: freshness for the event; volume trimmed.",
    "transition": "Transition week: deload early, retest + next block's entry tests late, on separate days.",
    "taper": "Taper: volume down, intensity kept.",
    "reset": "Structural reset: easy, varied, low impact.",
}


def plan_week(
    ctx: Context, week_start: dt.date, *, notes: list[str] | None = None, race_week: bool = False
) -> WeekPlan:
    macro = ctx.macro
    assert macro is not None, "macrocycle missing: run `coach macrocycle regenerate`"
    in_baseline = macro.baseline_start <= week_start <= macro.baseline_end
    block = None if in_baseline else macro.block_for(week_start)
    outline = ctx.state.outline(block.id) if block else None
    if not in_baseline and (block is None or outline is None):
        raise ValueError(f"no outline for week starting {week_start}")
    week_index = 0 if in_baseline else (week_start - block.start).days // 7 + 1  # type: ignore[union-attr]
    target = outline.week(week_index) if outline else None
    week_type = "baseline" if in_baseline else target.type  # type: ignore[union-attr]
    spec = ctx.cfg.season.spec(block.key) if block else None
    roles = week_roles(ctx, week_type, spec, week_start)
    templates = ctx.cfg.training.sessions

    deviations: list[Deviation] = []
    # --- run volume: outline target, capped by the 10% rule over the trailing 3 normal weeks ---
    trailing = ctx.trailing_miles(week_start)
    if week_type == "baseline":
        run_total = 0.0
    else:
        run_total = target.run_miles  # type: ignore[union-attr]
        if week_type not in {"taper", "transition", "reset"}:
            cap = allowed_increase_cap(
                trailing, RampRules(start_miles=ctx.cfg.profile.running.ramp_start_miles)
            )
            if run_total > cap:
                deviations.append(
                    Deviation(
                        field="run_miles",
                        planned=f"{run_total:.1f}",
                        actual=f"{cap:.1f}",
                        reason=f"held to +10% over the trailing 3-week average ({', '.join(f'{m:g}' for m in trailing)} mi)",
                    )
                )
                run_total = cap
    shares = {r: templates[r].run_share for r in dict.fromkeys(roles) if templates[r].run_share > 0}
    th = ctx.cfg.profile.thresholds
    limit = (
        th.long_run_max_fraction
        if run_total >= th.long_run_rule_min_weekly_miles
        else th.long_run_max_fraction_low_volume
    )
    if "long_run" in shares:
        shares["long_run"] = min(shares["long_run"], limit - 0.02)
    total_share = sum(shares.values()) or 1
    miles_for = {r: round(run_total * shares[r] / total_share, 1) for r in shares}
    prev_long = ctx.previous_long_run(week_start)
    if (
        "long_run" in miles_for
        and prev_long
        and week_type not in {"taper", "transition", "reset", "baseline"}
    ):
        cap = round(prev_long + th.long_run_max_increase_mi, 1)
        if miles_for["long_run"] > cap:
            surplus = round(miles_for["long_run"] - cap, 1)
            miles_for["long_run"] = cap
            others = [r for r in miles_for if r != "long_run"]
            if others:
                biggest = max(others, key=lambda r: miles_for[r])
                miles_for[biggest] = round(miles_for[biggest] + surplus, 1)
    if week_type in {"baseline", "transition"}:
        miles_for = {r: 3.0 for r in shares}

    scheduled: dict[str, dt.date] = {}
    if week_type in {"baseline", "transition"}:
        nxt = macro.next_block(block.id) if block else None
        next_spec = (
            ctx.cfg.season.spec(nxt.key)
            if nxt
            else (ctx.cfg.season.blocks[0] if week_type == "baseline" else None)
        )
        tests = tests_for_week(ctx, week_type, spec, next_spec)
        scheduled = T.schedule(
            week_start, tests, ctx.cfg.tests, "baseline" if week_type == "baseline" else "transition"
        )
    week_number = week_start.isocalendar()[1]
    sessions: list[Session] = []
    for i, role in enumerate(roles):
        day = week_start + dt.timedelta(days=i)
        today_tests = [t for t, d in scheduled.items() if d == day]
        sessions.append(
            build_session(ctx, role, day, week_type, miles_for.get(role, 0.0), week_number, spec, today_tests)
        )
    if target and target.hard_sets:
        D.balance_hard_sets(sessions, target.hard_sets, ctx, week_type)
    finalize(ctx, sessions)
    rationale = RATIONALE[week_type]
    return WeekPlan(
        week_id=clock.iso_week_id(week_start),
        block_id=block.id if block else f"{macro.season}-B0",
        week_index=week_index,
        week_type=week_type,  # type: ignore[arg-type]
        start=week_start,
        sessions=sessions,
        deviations=deviations,
        generated_by="fallback",
        approval="pending",
        rationale=rationale + (" " + " ".join(notes) if notes else ""),
    )


def finalize(ctx: Context, sessions: list[Session]) -> None:
    """Minutes, carb tiers, loads and paces (code-computed numbers)."""
    hist = ctx.state.sessions(ctx.today - dt.timedelta(weeks=10), ctx.today)
    filler = Filler(ctx.cfg.library, ctx.cfg.equipment.loading, hist, ctx.zones, ctx.today)
    ordered = sorted(sessions, key=lambda s: s.date)
    for i, s in enumerate(ordered):
        s.expected_minutes = D.estimate_minutes(s, ctx.zones.threshold_pace_s_per_mi)
        tomorrow = ordered[i + 1] if i + 1 < len(ordered) else None
        s.carb_tier = nut.carb_tier_for(s, tomorrow, ctx.cfg.training.rules.carb_tiers)  # type: ignore[assignment]
        fams = {
            f
            for f, fs in ctx.movement.families.items()
            if fs.eccentric_tempo_until and fs.eccentric_tempo_until >= s.date
        }
        filler.fill(s, eccentric_families=fams)
