"""compete fallback: marathon taper + race plan, CrossFit Open week strategy, post-event review."""

import datetime as dt

from coach.coaching.context import Context
from coach.engine.units import fmt_duration, fmt_pace


def goal_seconds(goal: str) -> int:
    parts = [int(x) for x in goal.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


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
    target = goal_seconds(ctx.cfg.profile.goals.marathon_target)
    pace = target / 26.2188
    z = ctx.zones
    lines = [
        f"# Race plan: {race.name} ({race.date}){'' if race.confirmed else ' - DATE NOT CONFIRMED'}",
        "",
        f"**Goal:** {fmt_duration(target)} = {fmt_pace(pace)} average. Current threshold pace {fmt_pace(z.threshold_pace_s_per_mi)} "
        f"(goal MP is {pace / z.threshold_pace_s_per_mi:.0%} of threshold pace: "
        + (
            "realistic"
            if pace / z.threshold_pace_s_per_mi >= 1.06
            else "aggressive: re-check after the next TT"
        )
        + ").",
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
