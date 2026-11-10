"""fuel fallback: today's macros (calorie-neutral weekly redistribution) + peri-workout cue."""

import datetime as dt

from coach.context import Context
from coach.engine import nutrition as nut
from coach.models import NutritionDay, Session, WeekPlan


def weekly_target(ctx: Context, week_start: dt.date, sources=None) -> tuple[float, str]:
    if sources is not None:
        try:
            t = sources.nutrition.weekly_target_kcal(week_start)
            if t:
                return float(t), "MacroFactor weekly target"
        except Exception:  # noqa: BLE001 - nutrition is optional until Phase 3
            pass
    saved = ctx.state.read_json("macrofactor.json") or {}
    if saved.get("weekly_kcal"):
        return float(saved["weekly_kcal"]), "MacroFactor target (told to the coach)"
    bw = ctx.bodyweight_kg()
    return round(bw * 33 * 7), "estimate (33 kcal/kg/day) until MacroFactor data is connected"


def day_targets(
    ctx: Context, day: dt.date, plan: WeekPlan | None, sources=None, today_session: Session | None = None
) -> NutritionDay:
    rules = ctx.cfg.profile.nutrition
    week_start = day - dt.timedelta(days=day.weekday())
    sessions = {s.date: s for s in (plan.sessions if plan else []) if s.type != "rest"}
    if today_session is not None:
        sessions[day] = today_session
    tiers = {}
    for i in range(7):
        d = week_start + dt.timedelta(days=i)
        tiers[d] = nut.carb_tier_for(sessions.get(d), sessions.get(d + dt.timedelta(days=1)))
    kcal, source = weekly_target(ctx, week_start, sources)
    days = nut.distribute_week(kcal, ctx.bodyweight_kg(), tiers, rules)
    today = next(d for d in days if d.date == day)
    today.peri_workout = nut.peri_workout(sessions.get(day), rules)
    today.note = "; ".join(x for x in [today.note, source] if x)
    return today
