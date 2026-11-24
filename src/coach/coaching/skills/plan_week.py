"""plan-week fallback: outline week target -> detailed sessions, from the week/session templates in
config/training.yaml and the block spec in config/season.yaml."""

import datetime as dt

from coach import clock
from coach.coaching.context import Context
from coach.coaching.fill import Filler, planned_rir
from coach.coaching.skills import design as D
from coach.coaching.skills.templates import build_session
from coach.engine import nutrition as nut
from coach.engine import testing as T
from coach.engine.running import RampRules, allowed_increase_cap
from coach.models import Deviation, RunSegment, Session, SessionBlock, WeekPlan
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
    th = ctx.cfg.profile.thresholds
    # --- run volume: outline target, capped by the weekly-increase rule over the trailing 3 normal weeks ---
    trailing = ctx.trailing_miles(week_start)
    if week_type == "baseline":
        run_total = 0.0
    else:
        run_total = target.run_miles  # type: ignore[union-attr]
        if week_type not in {"taper", "transition", "reset"}:
            rules = RampRules(
                start_miles=ctx.cfg.profile.running.ramp_start_miles,
                max_increase_pct=th.weekly_run_increase_pct,
            )
            cap = allowed_increase_cap(trailing, rules)
            if run_total > cap:
                deviations.append(
                    Deviation(
                        field="run_miles",
                        planned=f"{run_total:.1f}",
                        actual=f"{cap:.1f}",
                        reason=f"held to +{th.weekly_run_increase_pct:g}% over the trailing 3-week average "
                        f"({', '.join(f'{m:g}' for m in trailing)} mi)",
                    )
                )
                run_total = cap
    shares = {r: templates[r].run_share for r in dict.fromkeys(roles) if templates[r].run_share > 0}
    limit = (
        th.long_run_max_fraction
        if run_total >= th.long_run_rule_min_weekly_miles
        else th.long_run_max_fraction_low_volume
    )
    if "long_run" in shares:
        shares["long_run"] = min(shares["long_run"], limit - 0.02)
    total_share = sum(shares.values()) or 1
    miles_for = {r: round(run_total * shares[r] / total_share, 1) for r in shares}
    # single-run spike rule (audit 2026-11-23): no run beyond the cap set by the longest run of the last 30 days;
    # the surplus moves to runs under the cap, and what doesn't fit is dropped (and said so)
    from coach.engine.validator import spike_cap

    longest = ctx.longest_run_30d(week_start)
    spike = spike_cap(longest or 0.0, th)
    if spike is not None and miles_for and week_type not in {"taper", "transition", "reset", "baseline"}:
        spike = round(spike - 0.05, 1)  # rounded down: planned miles round to 0.1
        surplus = 0.0
        for r in miles_for:
            if miles_for[r] > spike:
                surplus += miles_for[r] - spike
                miles_for[r] = spike
        for r in sorted(miles_for, key=lambda r: miles_for[r]):
            room = spike - miles_for[r]
            take = min(room, surplus)
            if take > 0:
                miles_for[r] = round(miles_for[r] + take, 1)
                surplus -= take
        if surplus > 0.05:
            deviations.append(
                Deviation(
                    field="run_miles",
                    planned=f"{run_total:.1f}",
                    actual=f"{run_total - surplus:.1f}",
                    reason=f"single-run spike rule: no run over {spike:.1f} mi (longest in the last 30 days "
                    f"{longest:.1f} mi, +{th.run_spike_max_pct:g}%)",
                )
            )
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
    if outline is not None:
        _top_up_aerobic(ctx, sessions, outline, week_type, week_start)
    finalize(ctx, sessions)
    rationale = RATIONALE[week_type]
    return WeekPlan(
        week_id=clock.iso_week_id(week_start),
        block_id=block.id if block else f"{macro.season}-B0",
        week_index=week_index,
        week_type=week_type,
        start=week_start,
        sessions=sessions,
        deviations=deviations,
        generated_by="fallback",
        approval="pending",
        rationale=rationale + (" " + " ".join(notes) if notes else ""),
    )


def _top_up_aerobic(
    ctx: Context, sessions: list[Session], outline, week_type: str, week_start: dt.date
) -> None:
    """A capped or deload run total can leave the aerobic pillar under its minimum effective dose (the long-run erg
    extension only runs in training weeks). Cover the shortfall with zero-impact Z2 bike after the long run, so the
    fallback never builds a week its own validator rejects."""
    from coach.engine import sessions as S
    from coach.engine.validator import DELOAD_TYPES

    pp = outline.pillars.get("aerobic")
    if pp is None or week_type in {"baseline", "transition", "reset"}:
        return
    need = pp.deload_med if week_type in DELOAD_TYPES | {"competition"} else pp.med
    probe = WeekPlan(
        week_id=clock.iso_week_id(week_start),
        block_id=outline.block_id,
        week_index=0,
        week_type=week_type,
        start=week_start,
        sessions=sessions,
        generated_by="fallback",
        approval="pending",
    )
    short = need - S.pillar_doses(probe, ctx.cfg.library, ctx.cfg.tests)["aerobic"]
    host = next((s for s in sessions if s.type == "run_long"), None) or next(
        (s for s in sessions if s.type == "run_easy"), None
    )
    if short <= 0 or host is None:
        return
    minutes = int(-(-short // 5) * 5)  # round up to 5 min
    seg = RunSegment(label="Z2 bike (aerobic minimum)", zone="Z2", duration_min=minutes, modality="bike")
    blk = SessionBlock(kind="run", title="Erg top-up (aerobic volume without impact)", run=[seg])
    at = len(host.blocks) - 1 if host.blocks and host.blocks[-1].kind == "cooldown" else len(host.blocks)
    host.blocks.insert(at, blk)


def finalize(ctx: Context, sessions: list[Session]) -> None:
    """Minutes, carb tiers, loads and paces (code-computed numbers)."""
    hist = ctx.state.sessions(ctx.today - dt.timedelta(weeks=10), ctx.today)
    filler = Filler(
        ctx.cfg.library,
        ctx.cfg.equipment.loading,
        hist,
        ctx.zones,
        ctx.today,
        ctx.cfg.training.rules,
        planned=planned_rir(ctx.state, hist),
    )
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
