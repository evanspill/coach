"""compete fallback: marathon taper + race plan, CrossFit Open week strategy, post-event review."""

import datetime as dt

from coach.coaching.context import Context
from coach.engine import goals as G
from coach.engine.units import fmt_duration, fmt_pace

goal_seconds = G.hms


def race_pacing(ctx: Context, race_id: str) -> dict:
    """Race-day pace from current fitness. An approved target is used only if fitness supports it (within the run
    test's typical error); otherwise the plan paces from fitness and says so. Long-term goals are shown, never paced."""
    from coach.coaching.skills.assess import marathon_model

    k, pen, model = marathon_model(ctx)
    fitness = G.marathon_from_threshold(ctx.zones.threshold_pace_s_per_mi, k, pen)
    noise = ctx.cfg.tests.tests["run_tt_30"].typical_error_pct if "run_tt_30" in ctx.cfg.tests.tests else 2.0
    t = ctx.state.get("race_targets", race_id)
    if t is not None and t.status == "approved":
        target = G.hms(t.target_time)
        if target >= fitness * (1 - noise / 100):
            chosen, why = target, f"Approved target {t.target_time}; current fitness supports it."
        else:
            chosen, why = (
                fitness,
                f"Approved target {t.target_time} is faster than current fitness supports: pacing from fitness. "
                "Run the first half at this pace; only press after 20 mi if it feels controlled.",
            )
    else:
        chosen, why = fitness, "No approved race target: pacing from current fitness."
    long_term = []
    for g in (g for g in ctx.cfg.profile.goals.long_term if g.kind == "marathon_time"):
        rec = ctx.state.get("goal_progress", g.id)
        if rec and rec.latest and rec.latest.required_s:
            long_term.append(
                f"Long-term: {g.name} needs {fmt_duration(rec.latest.required_s)} "
                f"(status: {rec.latest.status.replace('_', ' ')}). Not used for pacing."
            )
    return {
        "pace_s_per_mi": chosen / G.MARATHON_MI,
        "fitness_s": fitness,
        "model": model,
        "why": why,
        "long_term": long_term,
    }


def taper_volumes(base_weekly_miles: float) -> list[float]:
    """3-week taper: ~80% / 60% / 40% volume, intensity kept (race-pace touches each week)."""
    return [round(base_weekly_miles * f, 1) for f in (0.8, 0.6, 0.4)]


def marathon_plan(ctx: Context, race_id: str | None = None) -> str:
    race = (
        next(r for r in ctx.cfg.profile.races if r.id == race_id)
        if race_id
        else ctx.cfg.profile.race("marathon")
    )
    assert race is not None, "no marathon in races"
    z = ctx.zones
    pacing = race_pacing(ctx, race.id)
    pace = pacing["pace_s_per_mi"]
    lines = [
        f"# Race plan: {race.name} ({race.date}){'' if race.confirmed else ' - DATE NOT CONFIRMED'}",
        "",
        f"**Pacing for:** {fmt_duration(pace * G.MARATHON_MI)} = {fmt_pace(pace)} average. {pacing['why']}",
        f"Current threshold pace {fmt_pace(z.threshold_pace_s_per_mi)} supports about {fmt_duration(pacing['fitness_s'])} "
        f"({pacing['model']}).",
        *pacing["long_term"],
        "",
        "## Pacing",
        f"- Miles 1-3: {fmt_pace(pace + 10)}-{fmt_pace(pace + 5)} (settle, HR below {z.hr('MP')[0]}).",
        f"- Miles 4-20: {fmt_pace(pace - 2)}-{fmt_pace(pace + 2)}; HR {z.hr('MP')[0]}-{z.hr('MP')[1]}. Even effort on hills, not even pace.",
        "- Miles 20-26.2: hold pace if HR < LTHR - 5; otherwise hold effort. Decide at 22, not before.",
        "",
        "## Fuelling",
        "- Breakfast 3 h out: 2-3 g/kg carbs, low fibre; 500 ml fluid + sodium.",
        "- 15 min before: 25 g carbs (gel). During: 60-90 g carbs/h (gel every 20-25 min, practised in long runs), 500-800 mg sodium/h, drink to thirst.",
        "",
        "## Warm-up",
        "- 8-10 min easy jog + 4 x 20 s strides, finish 10 min before the gun. Usual lower-body warm-up at home.",
        "",
        "## Gear check",
        "- "
        + (
            ctx.cfg.profile.race_gear_checklist
            or "Race shoes (broken in), watch charged, gels counted, bib/pins."
        ),
        "",
        "## Contingencies",
        "- Heat: temp F + dew point F 130-150 -> add 15-30 s/mi from mile 1 and extra sodium; > 150 -> race by HR, reset the goal.",
        "- GI trouble: drop to water + sodium for 15 min, resume carbs in smaller doses.",
        "- Calf/Achilles twinge: shorten stride, ease 10 s/mi; sharp pain = stop (docs/SAFETY.md).",
        "",
        "## Taper",
        "- Week -3: ~80% volume, one MP session. Week -2: ~60%, short T reps. Race week: ~40%, shakeout Saturday, Friday off.",
        "- Lifting: 2 light flush sessions/week, nothing new, no soreness.",
        "",
        "## After",
        "- 2-week structural reset: walking, easy bike, mobility; post-event review in this file within 3 days.",
    ]
    return "\n".join(lines) + "\n"


def open_week_strategy(ctx: Context, week_start: dt.date, workout_label: str) -> str:
    skills = ctx.cfg.skills.skills
    competent = [s.name for s in skills.values() if s.competent]
    not_yet = [s.name for s in skills.values() if not s.competent]
    release = week_start + dt.timedelta(days=3)
    sw = ctx.cfg.profile.schedule.model_extra.get("start_window", ["09:00", "10:00"])  # type: ignore[union-attr]
    window = "-".join(sw)
    return (
        "\n".join(
            [
                f"# CrossFit Open {workout_label} strategy (week of {week_start})",
                "",
                f"- Release Thursday {release:%b %d}; **attempt Friday morning** in the normal training slot ({window}) after a full warm-up.",
                "- Read the workout Thursday night: plan rep schemes per round and where to break *before* you need to (break early, rest short).",
                f"- Division: Rx only if every movement is competent ({', '.join(competent) or 'none yet'}) and within current rungs. "
                f"Not yet competent: {', '.join(not_yet)} -> scaled division (no shame: this is about training age, not ego).",
                "- Shoulder rules: no fatigued high-rep overhead snatching; if the workout has it at Rx, take the scaled version.",
                "- Re-attempt: only if the first score is clearly below what pacing should give AND Saturday-Monday readiness is Green; never two attempts on Yellow.",
                "- Recovery between attempts: Z1 + mobility, normal carbs (high tier on attempt days), usual post-session recovery.",
                "- Log the score in chat: 'Open 27.x done: <score>, rpe N, what broke'.",
            ]
        )
        + "\n"
    )


def post_event_review(event: str, result: str, notes: str) -> str:
    return f"\n## Post-event review\n- Result: {result}\n- Notes: {notes}\n- What to keep / change next time: (fill in after a check-in)\n"
