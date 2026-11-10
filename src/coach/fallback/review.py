"""review fallback: weekly check-in, block review, burnout watch. Asks before prescribing."""

import datetime as dt
import statistics

from coach.context import Context
from coach.engine import gear as G
from coach.engine import movement as mv
from coach.engine.sessions import hard_sets, week_miles
from coach.engine.units import fmt_pace
from coach.fallback.assess import block_result
from coach.models import WeekPlan


def adherence(ctx: Context, plan: WeekPlan) -> tuple[int, int, list[str]]:
    """Planned vs completed, where 'planned' is what the coach finally prescribed that day (a Red-day swap to a
    walk is the coach's call, not a miss)."""
    done_days = {s.date for s in ctx.state.sessions(plan.start, plan.end)}
    planned = []
    for s in plan.sessions:
        rec = ctx.state.day_record(s.date)
        final = rec.session if rec and rec.session else s
        if final.type not in {"rest", "recovery"}:
            planned.append(final)
    missed = [f"{s.date:%a} {s.title}" for s in planned if s.date not in done_days]
    return len(planned) - len(missed), len(planned), missed


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 1) if xs else None


def burnout_watch(ctx: Context, end: dt.date) -> dict:
    """Falling enjoyment or rising session RPE at the same loads are early burnout signs."""
    recent = ctx.state.checkins(end - dt.timedelta(days=13), end)
    prior = ctx.state.checkins(end - dt.timedelta(days=41), end - dt.timedelta(days=14))
    e_now, e_before = _avg([c.enjoyment for c in recent]), _avg([c.enjoyment for c in prior])
    r_now, r_before = _avg([c.session_rpe for c in recent]), _avg([c.session_rpe for c in prior])
    loads_same = True  # loads come from the plan; RPE rising at planned loads is the signal
    flags = []
    if e_now is not None and e_before is not None and e_now <= e_before - 1:
        flags.append(f"enjoyment down {e_before} -> {e_now}")
    if r_now is not None and r_before is not None and r_now >= r_before + 0.8 and loads_same:
        flags.append(f"session RPE up {r_before} -> {r_now} at similar loads")
    return {"enjoyment": (e_before, e_now), "rpe": (r_before, r_now), "flags": flags}


def weekly_review(ctx: Context, plan: WeekPlan, next_target_note: str = "") -> tuple[str, dict]:
    done, total, missed = adherence(ctx, plan)
    pct = round(100 * done / total) if total else 100
    sessions = ctx.state.sessions(plan.start, plan.end)
    run_actual = round(sum(s.distance_mi or 0 for s in sessions if s.sport == "run"), 1)
    run_plan = week_miles(plan, ctx.zones.threshold_pace_s_per_mi)
    ms = ctx.state.daily_metrics(plan.start, plan.end)
    rec = _avg([m.recovery_score for m in ms])
    sleep = _avg([m.sleep_hours for m in ms])
    weights = [m.weight_kg for m in ms if m.weight_kg]
    prev_w = [
        m.weight_kg
        for m in ctx.state.daily_metrics(plan.start - dt.timedelta(days=7), plan.start - dt.timedelta(days=1))
        if m.weight_kg
    ]
    w_now, w_prev = _avg(weights), _avg(prev_w)
    states = []
    for i in range(7):
        r = ctx.state.day_record(plan.start + dt.timedelta(days=i))
        if r and r.readiness:
            states.append(r.readiness.state)
    cis = ctx.state.checkins(plan.start, plan.end)
    joints = {
        k: max((getattr(c, k) or 0) for c in cis) if cis else None
        for k in ("back", "shoulders", "knees_achilles")
    }
    bw = burnout_watch(ctx, plan.end)
    planned_sets = hard_sets(plan, ctx.cfg.library)
    alerts = G.shoe_alerts(ctx.state.gear(), ctx.cfg.profile.thresholds.shoe_alert_miles)
    cadences = [s.cadence_spm for s in sessions if s.cadence_spm]
    went_well, to_fix, focus, questions = [], [], [], []
    if pct >= 85:
        went_well.append(f"Adherence {done}/{total} sessions.")
    else:
        to_fix.append(f"Adherence {done}/{total} ({pct}%). Missed: {', '.join(missed)}.")
        questions.append(
            "Adherence dipped this week. What got in the way (schedule, energy, motivation, pain)? I'll adjust after I hear from you."
        )
    if run_actual and abs(run_actual - run_plan) <= max(1.0, 0.15 * run_plan):
        went_well.append(f"Running on target: {run_actual} mi of {run_plan} planned.")
    elif run_plan:
        to_fix.append(f"Running {run_actual} mi vs {run_plan} planned.")
    if states.count("red") >= 2:
        to_fix.append(f"{states.count('red')} Red days: recovery is the limiter right now.")
        focus.append("Protect sleep: aim for 8 h in bed on the nights before key sessions.")
    if bw["flags"]:
        to_fix.append("Burnout watch: " + "; ".join(bw["flags"]) + ".")
        questions.append(
            "Enjoyment is down and sessions feel harder at the same loads. How are you feeling about training and life outside it? "
            "I'd rather adjust now than push through."
        )
    if any(v and v >= 3 for v in joints.values()):
        to_fix.append(
            "Joint ratings hit 3+: " + ", ".join(f"{k} {v}" for k, v in joints.items() if v and v >= 3) + "."
        )
    if cadences and _avg(cadences) and _avg(cadences) < ctx.cfg.profile.running.cadence_target_spm[0]:
        focus.append(
            f"Running cadence averaging {_avg(cadences):.0f} spm: aim for 170-180 with quicker, shorter steps."
        )
    if not focus:
        focus.append("Keep doing the basics: protein at every meal, 8 h in bed, warm-ups every session.")
    lines = [
        f"# Week {plan.week_id} review ({plan.week_type})",
        "",
        f"- **Adherence:** {done}/{total} sessions ({pct}%)"
        + (f"; missed {', '.join(missed)}" if missed else ""),
        f"- **Running:** {run_actual} mi actual vs {run_plan} mi planned",
        f"- **Readiness:** "
        + (
            ", ".join(f"{s} x{states.count(s)}" for s in ("green", "yellow", "red") if states.count(s))
            or "n/a"
        ),
        f"- **Recovery avg:** {rec}  |  **Sleep avg:** {sleep} h",
        f"- **Weight (7-day avg):** {w_now} kg"
        + (f" ({w_now - w_prev:+.2f} vs last week)" if w_now and w_prev else ""),
        f"- **Peak joint ratings:** " + ", ".join(f"{k} {v}" for k, v in joints.items()),
        f"- **Planned hard sets:** "
        + ", ".join(
            f"{m} {v:g}"
            for m, v in sorted(planned_sets.items())
            if m in {"quads", "hamstrings", "glutes", "chest", "back", "shoulders"}
        ),
        f"- **Enjoyment / RPE (2-wk vs prior):** {bw['enjoyment'][1]} vs {bw['enjoyment'][0]} / {bw['rpe'][1]} vs {bw['rpe'][0]}",
        "",
        "## What went well",
        *[f"- {x}" for x in went_well or ["Showed up and logged the data: that's what lets the plan adapt."]],
        "",
        "## What to fix",
        *[f"- {x}" for x in to_fix or ["Nothing major."]],
        "",
        "## Focus for next week",
        *[f"- {x}" for x in focus[:2]],
    ]
    if alerts:
        lines += ["", "## Gear", *[f"- {a}" for a in alerts]]
    if questions:
        lines += [
            "",
            "## Questions for you (I'll ask before changing the plan)",
            *[f"- {q}" for q in questions],
        ]
    if next_target_note:
        lines += ["", next_target_note]
    summary = {
        "adherence_pct": pct,
        "missed": missed,
        "run_actual": run_actual,
        "run_plan": run_plan,
        "burnout_flags": bw["flags"],
        "questions": questions,
        "focus": focus[:2],
    }
    return "\n".join(lines) + "\n", summary


def block_review(ctx: Context, block_id: str) -> str:
    goal = ctx.state.goal(block_id)
    start = ctx.state.tests(block_id, "start") or ctx.state.tests(
        f"{block_id.rsplit('-', 1)[0]}-B0", "baseline"
    )
    end = ctx.state.tests(block_id, "end")
    outline = ctx.state.outline(block_id)
    lines = [f"# Block review: {block_id}", ""]
    if goal and end:
        res = block_result(goal, end)
        p = res["primary"]
        if p:
            lines.append(
                f"**Primary goal ({p['test']}):** {p['start']} -> {p['end']} (target {p['target']}): **{'HIT' if p['hit'] else 'MISSED'}**"
            )
        for g in res["guardrails"]:
            lines.append(
                f"- Guardrail {g['test']}: {g['start']} -> {g['end']} (limit {g['limit']}): {'held' if g['held'] else 'BROKEN'}"
            )
        if p and not p["hit"]:
            lines += [
                "",
                "**Likely limiting factors:** missed training weeks, Red streaks and joint flares reduced effective loading weeks; "
                "see adherence below. Next block's outline protects key sessions first.",
            ]
    lines += ["", "## Start vs end"]
    if start and end:
        for r in end.results:
            s = start.get(r.test_id)
            if s:
                fmt = fmt_pace if r.test_id.startswith("run") else (lambda v: f"{v:.1f}")
                lines.append(
                    f"- {r.test_id}: {fmt(s.comparable_value or s.value)} -> {fmt(r.comparable_value or r.value)} {r.unit}"
                    f" (variant {s.variant} -> {r.variant})"
                )
    if outline:
        planned = done = 0
        for w in outline.weeks:
            from coach.clock import iso_week_id

            plan = ctx.state.week_plan(iso_week_id(w.start))
            if plan:
                d, t, _ = adherence(ctx, plan)
                planned += t
                done += d
        lines += [
            "",
            f"## Adherence: {done}/{planned} sessions ({round(100 * done / planned) if planned else 0}%)",
        ]
        if outline.revisions:
            lines += [
                "",
                "## Changes during the block",
                *[f"- {r.at}: {r.change} ({r.reason})" for r in outline.revisions],
            ]
    ms = ctx.state.daily_metrics(outline.start if outline else ctx.today - dt.timedelta(days=90), ctx.today)
    first = [m.weight_kg for m in ms[:14] if m.weight_kg]
    last = [m.weight_kg for m in ms[-14:] if m.weight_kg]
    if first and last:
        lines += [
            "",
            f"## Trends: weight {_avg(first)} -> {_avg(last)} kg; RHR {_avg([m.rhr_bpm for m in ms[:28]])} -> {_avg([m.rhr_bpm for m in ms[-28:]])} bpm",
        ]
    lines += [
        "",
        f"**Movement families fully unlocked:** {mv.unlocked_pct(ctx.movement, ctx.cfg.progressions)}%",
        "Rungs: " + ", ".join(f"{f} {fs.rung}" for f, fs in ctx.movement.families.items()),
    ]
    return "\n".join(lines) + "\n"
