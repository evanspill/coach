"""assess fallback: intake template, baseline battery proposal, test scoring, gap analysis, goal proposal."""

import datetime as dt
import math
import statistics

from coach.coaching import proposals
from coach.coaching.context import Context
from coach.engine import testing as T
from coach.engine.loads import e1rm
from coach.engine.units import fmt_pace
from coach.models import BlockGoal, MacroBlock, SessionRecord, TestSet
from coach.models.plans import GoalTarget, Guardrail
from coach.models.records import ThresholdZones

_INTAKE_DEFAULT = [  # generic fallback; the athlete's questions live in athlete_context.json intake_questions
    "Training history: years training, best lifts and race times (with dates)?",
    "Injury history: what happened, what aggravates it now, any imaging or physio notes?",
    "Exercises you love / hate / want to get back to?",
    "Typical week: work hours, travel, which days are hardest to train?",
    "Sleep: usual bed/wake time, how often < 7 h?",
    "Stress (1-5) and main sources right now?",
    "Nutrition: current calorie goal and tracking app; foods you avoid?",
    "What would make this year a success for you?",
]


def intake_template(day: dt.date, questions: list[str] | None = None) -> dict:
    return {
        "completed": False,
        "created": day.isoformat(),
        "refresh_due": (day + dt.timedelta(days=365)).isoformat(),
        "answers": {q: None for q in (questions or _INTAKE_DEFAULT)},
    }


def _top_set(sessions: list[SessionRecord], day: dt.date, pred) -> tuple[float, int, float, str] | None:
    best = None
    for s in sessions:
        if s.date != day:
            continue
        for st in s.sets:
            if (
                st.set_type == "warmup"
                or not st.weight_kg
                or not st.reps
                or not st.exercise_id
                or not pred(st.exercise_id)
            ):
                continue
            v = e1rm(st.weight_kg, st.reps, st.rir or 0)
            if best is None or v > best[0]:
                best = (v, st.reps, st.rir or 0, st.exercise_id, st.weight_kg)
    if best is None:
        return None
    return best[4], best[1], best[2], best[3]


def extract_raw(
    test_id: str, day: dt.date, ctx: Context, weather_hourly: list[dict] | None = None
) -> dict | None:
    lib = ctx.cfg.library
    t = ctx.cfg.tests.tests[test_id]
    sessions = ctx.state.sessions(day, day)
    fam = t.session.get("family") or t.family
    ex_id = t.session.get("exercise")
    if t.scoring == "epley_e1rm":
        if fam:
            top = _top_set(sessions, day, lambda ex: lib.get(ex) and lib.get(ex).family == fam)
        else:
            top = _top_set(sessions, day, lambda ex: ex == ex_id)
        return {"weight_kg": top[0], "reps": top[1], "rir": top[2], "variant": top[3]} if top else None
    if t.scoring == "max_reps" and ex_id:
        reps = [st.reps for s in sessions for st in s.sets if st.exercise_id == ex_id and st.reps]
        return {"reps": max(reps)} if reps else None
    if t.scoring == "best_of" and ex_id:
        att = [
            round(st.distance_m * 100)
            for s in sessions
            for st in s.sets
            if st.exercise_id == ex_id and st.distance_m
        ]
        return {"attempts": att} if att else None
    if t.scoring in {"lthr_from_last20", "submax_estimate"}:
        runs = [s for s in sessions if s.sport == "run"]
        if not runs:
            return None
        r = max(runs, key=lambda s: s.duration_min)
        cond = {}
        if weather_hourly:
            at = [w for w in weather_hourly if w["time"].date() == day and w["time"].hour in (9, 10)]
            if at:
                cond["temp_f"] = round(max(w["temp_c"] for w in at) * 9 / 5 + 32, 1)
        cond["variant"] = "indoor" if "treadmill" in (r.title or "").lower() else "outdoor"
        if t.scoring == "lthr_from_last20" and r.last20_avg_hr and r.last20_pace_s_per_mi:
            return {
                "last20_avg_hr": r.last20_avg_hr,
                "last20_pace_s_per_mi": r.last20_pace_s_per_mi,
                "conditions": cond,
                "variant": cond["variant"],
            }
        if r.avg_hr and r.avg_pace_s_per_mi:
            return {"avg_hr": r.avg_hr, "avg_pace_s_per_mi": r.avg_pace_s_per_mi, "conditions": cond}
        return None
    if t.scoring == "row_watts":
        rows = [s for s in sessions if s.sport == "row"]
        if not rows:
            return None
        return {"time_s": round(rows[0].duration_min * 60), "bodyweight_kg": ctx.bodyweight_kg()}
    if t.scoring == "seven_day_avg":
        ms = ctx.state.daily_metrics(day - dt.timedelta(days=6), day)
        w = [m.weight_kg for m in ms if m.weight_kg]
        return (
            {"weights_kg": w, "body_fat_pct": [m.body_fat_pct for m in ms if m.body_fat_pct]} if w else None
        )
    if t.scoring == "rolling_baseline":
        ms = ctx.state.daily_metrics(day - dt.timedelta(days=27), day)
        rhr = [m.rhr_bpm for m in ms if m.rhr_bpm]
        hrv = [math.log(m.hrv_rmssd_ms) for m in ms if m.hrv_rmssd_ms]
        return (
            {"rhr_bpm": round(statistics.fmean(rhr), 1), "ln_rmssd": round(statistics.fmean(hrv), 3)}
            if rhr
            else None
        )
    return None


def score_week(
    ctx: Context,
    block_id: str,
    phase: str,
    scheduled: dict[str, dt.date],
    weather_hourly: list[dict] | None = None,
    end_day: dt.date | None = None,
) -> TestSet:
    ts = ctx.state.tests(block_id, phase) or TestSet(block_id=block_id, phase=phase)  # type: ignore[arg-type]
    ts.scheduled = {**ts.scheduled, **scheduled}
    for test_id, day in scheduled.items():
        if ts.get(test_id):
            continue
        raw = extract_raw(test_id, day, ctx, weather_hourly)
        if raw is None:
            continue
        ts.results.append(T.score(test_id, raw, ctx.cfg.tests, day))
    end_day = end_day or max(scheduled.values(), default=ctx.today)
    for passive in ("body_comp", "vitals"):
        if not ts.get(passive):
            raw = extract_raw(passive, end_day, ctx)
            if raw:
                ts.results.append(T.score(passive, raw, ctx.cfg.tests, end_day))
    return ts


def update_zones_from(ctx: Context, ts: TestSet) -> ThresholdZones | None:
    tests = ctx.cfg.tests.tests
    found = [
        r
        for r in ts.results
        if r.test_id in tests
        and tests[r.test_id].scoring in {"lthr_from_last20", "submax_estimate"}
        and "lthr" in r.details
    ]
    found.sort(
        key=lambda r: tests[r.test_id].scoring != "lthr_from_last20"
    )  # a full TT beats a submax estimate
    if not found:
        return None
    r = found[0]
    z = ThresholdZones(
        lthr=int(r.details["lthr"]),
        threshold_pace_s_per_mi=int(r.details["threshold_pace_s_per_mi"]),
        source=f"{r.test_id} {r.date}",
        confidence=r.details.get("confidence", "normal"),
    )
    ctx.state.put("zones", z)
    return z


def gap_analysis(ctx: Context, ts: TestSet) -> dict[str, float]:
    """Each benchmark -> % of target achieved (100 = at benchmark). Lower = bigger gap."""
    bw = ctx.bodyweight_kg()
    out: dict[str, float] = {}
    for pillar, items in ctx.cfg.benchmarks["pillars"].items():
        for b in items:
            r = ts.get(b["test"])
            if not r:
                continue
            tgt = b["target"][0] if isinstance(b["target"], list) else b["target"]
            val = r.comparable_value if r.comparable_value is not None else r.value
            if b["metric"] == "bw_ratio" or b["metric"] == "bw_ratio_per_hand":
                pct = val / bw / tgt * 100
            elif b["metric"] == "threshold_pace_s_per_mi":
                pct = tgt / val * 100
            elif b["metric"] == "watts_per_kg":
                pct = r.details.get("watts_per_kg", 0) / tgt * 100
            else:
                pct = val / tgt * 100
            out[f"{pillar}:{b['test']}"] = round(pct, 1)
    return out


def propose_goal(ctx: Context, block: MacroBlock, ts: TestSet) -> tuple[BlockGoal, list[str]]:
    gaps = gap_analysis(ctx, ts)
    spec = ctx.cfg.season.spec(block.key)
    cands = [t for t in spec.goal.focus_tests if ts.get(t)]
    if not cands:
        cands = [r.test_id for r in ts.results if r.test_id not in {"body_comp", "vitals"}][:1]
    gap_of = {t: next((v for k, v in gaps.items() if k.endswith(":" + t)), 100.0) for t in cands}
    primary_id = min(cands, key=lambda t: gap_of[t])
    r = ts.get(primary_id)
    assert r is not None
    lower_better = T.lower_is_better(primary_id, ctx.cfg.tests)
    pct = ctx.cfg.tests.tests[primary_id].goal_change_pct
    base = r.comparable_value if r.comparable_value is not None else r.value
    target = base * (1 - pct / 100) if lower_better else base * (1 + pct / 100)
    guards = []
    for gs in spec.goal.guardrails:
        g = ts.get(gs.test)
        if not g:
            continue
        gbase = g.comparable_value if g.comparable_value is not None else g.value
        if gs.mode == "absolute":
            limit = gbase + gs.change
        elif gs.mode == "pct":
            limit = gbase * (1 + gs.change / 100)
        else:  # weekly_pct over the block
            limit = gbase * (1 + gs.change / 100 * block.weeks)
        worse_is_higher = T.lower_is_better(gs.test, ctx.cfg.tests) or (
            gs.mode != "weekly_pct" and gs.change > 0
        )
        guards.append(
            Guardrail(
                test_id=gs.test,
                metric=g.unit,
                description=gs.description,
                baseline_value=round(gbase, 1),
                limit_value=round(limit, 1),
                direction="no_higher_than" if worse_is_higher else "no_lower_than",
            )
        )
    guards = guards[:2]
    from coach.coaching.skills.plan_block import calorie_phase_from

    phase, phase_why = calorie_phase_from(ctx, block)
    name = ctx.cfg.tests.tests[primary_id].name
    is_pace = r.unit == "s_per_mi"
    fmt = (lambda v: fmt_pace(v)) if is_pace else (lambda v: f"{v:.1f} {r.unit}")
    rationale = (
        f"Block focus: {block.focus}. Biggest gap among focus tests: {name} at {gap_of[primary_id]:.0f}% of the hybrid benchmark. "
        f"Goal {fmt(base)} -> {fmt(target)} ({'-' if lower_better else '+'}{pct:g}%). Trade-off: guardrails keep the other pillars from sliding."
    )
    goal = BlockGoal(
        block_id=block.id,
        primary=GoalTarget(
            test_id=primary_id,
            metric=r.unit,
            baseline_value=round(base, 1),
            target_value=round(target, 1),
            unit=r.unit,
            change_pct=pct,
            direction="decrease" if lower_better else "increase",
        ),
        guardrails=guards,
        rationale=rationale,
        gap_analysis=gaps,
        calorie_phase=phase,  # type: ignore[arg-type]
        calorie_phase_reason=phase_why,
        status="pending",
        generated_by="fallback",
    )
    return goal, [rationale]


def save_goal_proposal(ctx: Context, goal: BlockGoal, day: dt.date):
    ctx.state.put("block_goals", goal)
    rel = ctx.state.ref("block_goals", goal.block_id)
    return proposals.create(
        ctx.state,
        "block_goal",
        "assess",
        f"Block goal for {goal.block_id}",
        f"{goal.primary.test_id}: {goal.primary.baseline_value} -> {goal.primary.target_value} {goal.primary.unit}; "
        f"guardrails: {'; '.join(g.description for g in goal.guardrails)}; calorie phase: {goal.calorie_phase}",
        goal.rationale,
        day,
        after=goal.model_dump(mode="json"),
        target=rel,
    )


def block_result(goal: BlockGoal, end: TestSet) -> dict:
    r = end.get(goal.primary.test_id)
    out = {"primary": None, "guardrails": []}
    if r:
        v = r.comparable_value if r.comparable_value is not None else r.value
        hit = (
            v <= goal.primary.target_value
            if goal.primary.direction == "decrease"
            else v >= goal.primary.target_value
        )
        out["primary"] = {
            "test": goal.primary.test_id,
            "start": goal.primary.baseline_value,
            "end": round(v, 1),
            "target": goal.primary.target_value,
            "hit": hit,
        }
    for g in goal.guardrails:
        rr = end.get(g.test_id)
        if rr:
            v = rr.comparable_value if rr.comparable_value is not None else rr.value
            ok = v <= g.limit_value if g.direction == "no_higher_than" else v >= g.limit_value
            out["guardrails"].append(
                {
                    "test": g.test_id,
                    "start": g.baseline_value,
                    "end": round(v, 1),
                    "limit": g.limit_value,
                    "held": ok,
                }
            )
    return out
