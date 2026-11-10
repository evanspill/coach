"""rehab fallback: movement readiness ladders from yesterday's exposures, pain reports and region flags."""

import datetime as dt

from coach.coaching.context import Context
from coach.engine import movement as mv
from coach.engine.validator import validate_movement_change


def update(ctx: Context, day: dt.date) -> list[str]:
    """Log exposures from yesterday's sessions (pain from yesterday's check-in, stiffness from today's) and apply flags."""
    cfg = ctx.cfg
    before = ctx.movement.model_copy(deep=True)
    mr = ctx.movement
    y = day - dt.timedelta(days=1)
    checkins = {c.date: c for c in ctx.state.checkins(y, day)}
    yc, tc = checkins.get(y), checkins.get(day)
    touched: set[str] = set()
    for s in ctx.state.sessions(y, y):
        for st in s.sets:
            ex = cfg.library.get(st.exercise_id) if st.exercise_id else None
            if ex and ex.family:
                touched.add(ex.family)
    events: list[str] = []
    for fam in sorted(touched):
        pain = (yc.session_pain.get(fam) if yc else None) or 0.0
        region = cfg.progressions.families[fam].region
        stiff = bool(tc and region in tc.stiffness_up)
        for ev in mv.record_exposure(mr, fam, y, pain, stiff, cfg.progressions):
            events.append(f"{fam}: rung {ev.from_rung} -> {ev.to_rung} ({ev.reason})")
    # pain reported for a family with no logged sets (e.g. chat report)
    if yc:
        for fam, pain in yc.session_pain.items():
            if fam in touched or fam not in mr.families:
                continue
            for ev in mv.record_exposure(mr, fam, y, pain, False, cfg.progressions):
                events.append(f"{fam}: rung {ev.from_rung} -> {ev.to_rung} ({ev.reason})")
    if ctx.has_metrics():
        for flag in ctx.readiness(day).joint_flags:
            if flag.since >= day - dt.timedelta(days=1):
                for ev in mv.apply_region_flag(mr, flag.region, day, cfg.progressions):
                    events.append(f"{ev.reason}: {flag.region} families rung {ev.from_rung} -> {ev.to_rung}")
    for fam, fs in mr.families.items():
        was = before.families[fam].pending_form_check
        if fs.pending_form_check is not None and fs.pending_form_check != was:
            rung = cfg.progressions.families[fam].rungs[fs.pending_form_check]
            events.append(
                f"FORM CHECK: {fam} ready for rung {fs.pending_form_check} ({rung.name}): film a set for the coach or get a physio OK first"
            )
    mr.updated = day
    errors = validate_movement_change(before, mr, cfg)
    if errors:
        ctx.movement = before
        return [f"rejected change: {e}" for e in errors]
    ctx.state.put("movement_readiness", mr)
    return events


def physio_recommended(ctx: Context) -> bool:
    regress = sum(
        1
        for fs in ctx.movement.families.values()
        for h in fs.history
        if h.to_rung < h.from_rung and h.date >= ctx.today - dt.timedelta(days=28)
    )
    return regress >= 2
