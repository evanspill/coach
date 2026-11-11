"""review fallback: weekly check-in, block review, burnout watch. Asks before prescribing."""

import datetime as dt
import statistics

from coach.coaching.context import Context
from coach.coaching.skills.assess import block_result
from coach.engine import gear as G
from coach.engine import movement as mv
from coach.engine.sessions import hard_sets, week_miles
from coach.engine.units import fmt_pace
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
    for field, label, worse_up in (
        ("mood", "mood", False),
        ("stress", "stress", True),
        ("fatigue", "fatigue", True),
    ):
        now, before = _avg([getattr(c, field) for c in recent]), _avg([getattr(c, field) for c in prior])
        if (
            now is not None
            and before is not None
            and ((now >= before + 1) if worse_up else (now <= before - 1))
        ):
            flags.append(f"{label} {'up' if worse_up else 'down'} {before} -> {now}")
    if e_now is not None and e_before is not None and e_now <= e_before - 1:
        flags.append(f"enjoyment down {e_before} -> {e_now}")
    if r_now is not None and r_before is not None and r_now >= r_before + 0.8 and loads_same:
        flags.append(f"session RPE up {r_before} -> {r_now} at similar loads")
    return {"enjoyment": (e_before, e_now), "rpe": (r_before, r_now), "flags": flags}


def session_load(ctx: Context, start: dt.date, end: dt.date) -> dict:
    """Foster session-RPE load: RPE x minutes per day; weekly load, monotony (mean/SD of daily load), strain."""
    cis = {c.date: c for c in ctx.state.checkins(start, end)}
    minutes: dict[dt.date, float] = {}
    for s in ctx.state.sessions(start, end):
        minutes[s.date] = minutes.get(s.date, 0) + s.duration_min
    daily = []
    for i in range((end - start).days + 1):
        d = start + dt.timedelta(days=i)
        c = cis.get(d)
        mins = (c.session_minutes if c and c.session_minutes else None) or minutes.get(d, 0)
        daily.append((c.session_rpe or 0) * mins if c and c.session_rpe else 0.0)
    total = sum(daily)
    sd = statistics.pstdev(daily) if len(daily) > 1 else 0
    monotony = round(statistics.fmean(daily) / sd, 2) if sd else None
    return {
        "load": round(total),
        "monotony": monotony,
        "strain": round(total * monotony) if monotony else None,
    }


def energy_availability(ctx: Context, start: dt.date, end: dt.date) -> float | None:
    """Mean daily energy availability = (intake - exercise energy) / fat-free mass, kcal/kg FFM/day.
    ~30 is a commonly used indicator of problematic low energy availability (REDs); the exact cut-off is debated."""
    ms = ctx.state.daily_metrics(start, end)
    kcal = [m.kcal for m in ms if m.kcal]
    weights = [m.weight_kg for m in ms if m.weight_kg]
    bfs = [m.body_fat_pct for m in ms if m.body_fat_pct]
    if not kcal or not weights:
        return None
    days = (end - start).days + 1
    target = ctx.state.get("nutrition_target")
    intake = (
        statistics.fmean(kcal)
        if len(kcal) >= max(3, days // 2)
        else (target.weekly_kcal / 7 if target else None)
    )
    if intake is None:
        return None
    exercise_kcal = sum((s.kilojoule or 0) / 4.184 for s in ctx.state.sessions(start, end)) / days
    ffm = statistics.fmean(weights) * (1 - (statistics.fmean(bfs) if bfs else 15) / 100)
    return round((intake - exercise_kcal) / ffm, 1)


def easy_share(ctx: Context, start: dt.date, end: dt.date) -> float | None:
    """Share of running time at or below Z2 (80/20 check); approximate when only average HR is known."""
    zm = [s.zone_minutes for s in ctx.state.sessions(start, end) if s.sport == "run" and s.zone_minutes]
    easy = sum(z[0] + z[1] for z in zm)
    total = sum(sum(z) for z in zm)
    return round(easy / total, 2) if total >= 60 else None


def journal_summary(ctx: Context, start: dt.date, end: dt.date) -> list[str]:
    entries = ctx.state.query("journal", start, end)
    return [f"{e.date:%a} [{e.kind}] {e.text[:140]}" for e in entries]


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
    regions = sorted({r for c in cis for r in c.joints})
    joints = {r: max(c.joints.get(r, 0) for c in cis) for r in regions}
    bw = burnout_watch(ctx, plan.end)
    planned_sets = hard_sets(plan, ctx.cfg.library)
    load = session_load(ctx, plan.start, plan.end)
    journal = journal_summary(ctx, plan.start, plan.end)
    mb = ctx.macro.block_by_id(plan.block_id) if ctx.macro else None
    tracked_muscles = set(ctx.cfg.season.spec(mb.key).hard_sets) if mb and mb.key else set(planned_sets)
    alerts = G.shoe_alerts(ctx.state.gear(), ctx.cfg.profile.thresholds.shoe_alert_miles)
    cadences = [s.cadence_spm for s in sessions if s.cadence_spm]
    ea = energy_availability(ctx, plan.start, plan.end)
    easy = easy_share(ctx, plan.start - dt.timedelta(days=7), plan.end)
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
    if sleep is not None and sleep < 7 and not any("sleep" in f.lower() for f in focus):
        to_fix.append(f"Sleep averaged {sleep} h.")
        focus.append("Sleep: 7-9 h, consistent bed and wake times; it's the cheapest recovery tool we have.")
    if load["monotony"] and load["monotony"] > 2.0:
        to_fix.append(
            f"Training monotony {load['monotony']} (> 2): days are too similar in load; vary hard and easy days."
        )
    if ea is not None and ea < 30 and plan.week_type not in {"taper"}:
        to_fix.append(
            f"Estimated energy availability ~{ea:g} kcal/kg fat-free mass/day: low for this training load (REDs risk)."
        )
        questions.append(
            "Your intake looks low for the training load. How are energy, mood and sleep? I'd like to raise "
            "intake on hard days or ease the deficit before it costs training or health."
        )
    if easy is not None and easy < 0.75 and plan.week_type in {"training", "deload"}:
        to_fix.append(
            f"Only {easy:.0%} of running time was easy over 2 weeks (target ~80%): slow the easy runs down."
        )
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
            f"Running cadence averaging {_avg(cadences):.0f} spm: nudge it up ~5% (quicker, shorter steps) toward 170-180; "
            "small steady changes, not a jump."
        )
    if not focus:
        focus.append("Keep doing the basics: protein at every meal, 8 h in bed, warm-ups every session.")
    lines = [
        f"# Week {plan.week_id} review ({plan.week_type})",
        "",
        f"- **Adherence:** {done}/{total} sessions ({pct}%)"
        + (f"; missed {', '.join(missed)}" if missed else ""),
        f"- **Running:** {run_actual} mi actual vs {run_plan} mi planned",
        "- **Readiness:** "
        + (
            ", ".join(f"{s} x{states.count(s)}" for s in ("green", "yellow", "red") if states.count(s))
            or "n/a"
        ),
        f"- **Recovery avg:** {rec}  |  **Sleep avg:** {sleep} h",
        f"- **Weight (7-day avg):** {w_now} kg"
        + (f" ({w_now - w_prev:+.2f} vs last week)" if w_now and w_prev else ""),
        "- **Peak joint ratings:** " + ", ".join(f"{k} {v}" for k, v in joints.items()),
        "- **Planned hard sets:** "
        + ", ".join(f"{m} {v:g}" for m, v in sorted(planned_sets.items()) if m in tracked_muscles),
        "- **Energy availability (est.):** " + (f"{ea:g} kcal/kg FFM/day" if ea is not None else "n/a"),
        f"- **Session load (sRPE x min):** {load['load']}"
        + (f" | monotony {load['monotony']} | strain {load['strain']}" if load["monotony"] else ""),
        f"- **Enjoyment / RPE (2-wk vs prior):** {bw['enjoyment'][1]} vs {bw['enjoyment'][0]} / {bw['rpe'][1]} vs {bw['rpe'][0]}",
        "",
        "## What went well",
        *[
            f"- {x}"
            for x in went_well
            or [
                "Not much to bank on the training side this week; recovery and data kept flowing, so next week starts from real numbers."
            ]
        ],
        "",
        "## What to fix",
        *[f"- {x}" for x in to_fix or ["Nothing major."]],
        "",
        "## Focus for next week",
        *[f"- {x}" for x in focus[:2]],
    ]
    if journal:
        lines += ["", "## From your journal", *[f"- {j}" for j in journal]]
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
        "session_load": load,
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
                is_pace = r.test_id.startswith("run")
                fmt = fmt_pace if is_pace else (lambda v: f"{v:.1f}")
                unit = "" if is_pace else f" {r.unit}"
                variant = (
                    f" (variant {s.variant} -> {r.variant}; compared at the reference variant)"
                    if s.variant and s.variant != r.variant
                    else ""
                )
                td = ctx.cfg.tests.tests.get(r.test_id)
                a, b_ = (s.comparable_value or s.value), (r.comparable_value or r.value)
                if td and a:
                    pct = (b_ - a) / a * 100 * (-1 if td.lower_is_better else 1)
                    noise = f"(within ~{td.typical_error_pct:g}% test noise)"
                    variant += f" {pct:+.1f}% " + (
                        "(real change)" if abs(pct) > td.typical_error_pct else noise
                    )
                lines.append(
                    f"- {r.test_id}: {fmt(s.comparable_value or s.value)} -> {fmt(r.comparable_value or r.value)}{unit}{variant}"
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
