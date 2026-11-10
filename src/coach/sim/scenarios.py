"""Per-skill simulation scenarios: each coaching job judged on its own against expected outcomes."""

import datetime as dt
import math
import os
import random
from collections.abc import Callable

from coach import clock, proposals
from coach.config import load_config
from coach.context import Context, build
from coach.daily import bootstrap
from coach.engine import movement as mv
from coach.engine import testing as T
from coach.engine.sessions import hard_sets, long_run_miles, pillar_doses, week_miles
from coach.fallback import (
    adjust_day,
    assess,
    compete,
    design,
    fuel,
    learn,
    plan_block,
    plan_week,
    replan,
    review,
    technique,
)
from coach.fallback import log as log_skill
from coach.integrations.mock import MockWorld, mock_sources
from coach.models import Checkin, DailyMetrics, DayRecord, Readiness
from coach.sim.run import sandbox
from coach.state import State
from coach.sync import sync
from coach.validator import validate_config_lock, validate_session, validate_week

B1_START = dt.date(2026, 11, 23)


class Check:
    def __init__(self):
        self.failures: list[str] = []
        self.notes: list[str] = []

    def that(self, cond: bool, msg: str) -> None:
        if not cond:
            self.failures.append(msg)

    def note(self, msg: str) -> None:
        self.notes.append(msg)


def world_at(day: dt.date, with_outline: bool = True, sync_data: bool = True) -> Context:
    """Fresh state in the current sandbox: bootstrap + sync fixtures + B1 outline (from baseline results)."""
    os.environ["COACH_TODAY"] = day.isoformat()
    cfg = load_config()
    state = State()
    bootstrap(state, cfg, min(day, dt.date(2026, 11, 16)))
    if sync_data:
        sync(mock_sources(MockWorld.load()), state, day, cfg)
    ctx = build(state, cfg, day)
    if with_outline and ctx.macro:
        b1 = ctx.macro.blocks[0]
        state.write_json("zones.json", {"lthr": 169, "threshold_pace_s_per_mi": 462})
        ctx = build(state, cfg, day)
        ol = plan_block.build_outline(ctx, b1, None, [7.0, 7.0, 8.0])
        state.write_json(f"blocks/{b1.id}/outline.json", ol)
        ctx = build(state, cfg, day)
    return ctx


def baseline_testset(ctx: Context):
    from coach.models import TestSet

    raw = MockWorld.load().script["test_results"]["baseline"]
    ts = TestSet(block_id=f"{ctx.macro.season}-B0", phase="baseline")
    for tid in ("broad_jump", "hinge_rm", "squat_rm", "db_press_5rm", "pullups_max", "run_tt_30", "row_2k"):
        r = dict(raw[tid])
        if tid == "row_2k":
            r["bodyweight_kg"] = 96.5
        ts.results.append(T.score(tid, r, ctx.cfg.tests, dt.date(2026, 11, 16)))
    ts.results.append(
        T.score(
            "body_comp",
            {"weights_kg": [96.8, 96.6, 96.9, 96.5, 96.7, 96.4, 96.6], "body_fat_pct": [18.1] * 7},
            ctx.cfg.tests,
            dt.date(2026, 11, 22),
        )
    )
    return ts


def synthetic_metrics(
    state: State,
    today: dt.date,
    today_rec: float,
    yesterday_rec: float = 70,
    hrv_drop: float = 0.0,
    rhr_add: float = 0.0,
    drop_days: int = 0,
) -> None:
    rng = random.Random(3)
    items = []
    for i in range(70, -1, -1):
        d = today - dt.timedelta(days=i)
        ln = math.log(62) + rng.gauss(0, 0.06) - (hrv_drop if i < drop_days else 0)
        rec = today_rec if i == 0 else yesterday_rec if i == 1 else 72 + rng.gauss(0, 5)
        m = DailyMetrics(
            date=d,
            recovery_score=rec,
            hrv_rmssd_ms=round(math.exp(ln), 1),
            rhr_bpm=50 + (rhr_add if i < 7 else 0),
            weight_kg=95.0,
            sources=["synthetic"],
        )
        items.append(("daily", d.isoformat(), d, m.model_dump(mode="json", exclude_none=True)))
    state.upsert_metrics(items)


# ---------------------------------------------------------------- assess
def sc_assess_baseline(c: Check) -> None:
    ctx = world_at(dt.date(2026, 11, 16), with_outline=False)
    plan = plan_week.plan_week(ctx, dt.date(2026, 11, 16))
    v = validate_week(plan, ctx.validation(plan))
    c.that(not v, f"baseline plan valid ({[str(x) for x in v][:2]})")
    slots: dict[str, set] = {}
    for s in plan.sessions:
        for t in s.tests:
            slots.setdefault(T.test_slot(t, ctx.cfg.tests).split("_")[0], set()).add(s.date)
    c.that(
        len({d for k in ("strength", "run", "engine") for d in slots.get(k, set())}) >= 3,
        "strength, run and engine tests on separate days",
    )
    c.that(
        not (slots.get("run", set()) & slots.get("engine", set())),
        "run TT and engine test not on the same day",
    )
    ts = baseline_testset(ctx)
    goal, _ = assess.propose_goal(ctx, ctx.macro.blocks[0], ts)
    p = assess.save_goal_proposal(ctx, goal, dt.date(2026, 11, 22))
    c.that(goal.status == "pending" and p.status == "pending", "block goal needs approval")
    c.that(1 <= len(goal.guardrails) <= 2, "one primary goal + 1-2 guardrails")
    c.that(
        goal.primary.test_id in ctx.cfg.season.spec("B1").goal.focus_tests,
        "primary goal measured by a configured test",
    )
    c.note(
        f"goal: {goal.primary.test_id} {goal.primary.baseline_value} -> {goal.primary.target_value}; guardrails: "
        + "; ".join(g.description for g in goal.guardrails)
    )


# ---------------------------------------------------------------- plan-week
def sc_plan_week_normal(c: Check) -> None:
    ctx = world_at(dt.date(2026, 11, 29))
    plan = plan_week.plan_week(ctx, dt.date(2026, 11, 30))
    v = validate_week(plan, ctx.validation(plan))
    c.that(not v, f"normal week passes the validator ({[str(x) for x in v][:3]})")
    doses = pillar_doses(plan, ctx.cfg.library, ctx.cfg.tests)
    c.that(
        all(doses[p] >= ctx.outline.pillars[p].med for p in doses), f"all four pillars at/above MED {doses}"
    )
    miles = week_miles(plan, 462)
    c.that(long_run_miles(plan, 462) / miles <= 0.40 + 1e-6, "long run within the low-volume fraction")
    c.note(f"{len(plan.sessions)} sessions, {miles} mi, pillars {doses}")


def sc_plan_week_deload(c: Check) -> None:
    ctx = world_at(dt.date(2026, 12, 13))
    normal = plan_week.plan_week(ctx, dt.date(2026, 12, 7))
    plan = plan_week.plan_week(ctx, dt.date(2026, 12, 14))
    c.that(plan.week_type == "deload", "week 4 is a planned deload")
    v = validate_week(plan, ctx.validation(plan))
    c.that(not v, f"deload week passes ({[str(x) for x in v][:3]})")
    lib = ctx.cfg.library
    bad = [
        it.exercise_id
        for s in plan.sessions
        for b in s.blocks
        if b.kind not in {"warmup", "test"}
        for it in [*b.items, *(b.metcon.movements if b.metcon else [])]
        if lib.get(it.exercise_id).has_tag("eccentric_heavy", "high_impact")
    ]
    c.that(not bad, f"no eccentric-heavy / high-impact work in the deload ({bad})")
    hn, hd = sum(hard_sets(normal, lib).values()), sum(hard_sets(plan, lib).values())
    c.that(hd <= 0.7 * hn, f"deload volume cut (~40-50%): {hn:g} -> {hd:g} hard sets")
    c.note(f"hard sets {hn:g} -> {hd:g}")


# ---------------------------------------------------------------- design-session
def sc_design_metcon(c: Check) -> None:
    ctx = world_at(dt.date(2026, 11, 29))
    P = design.Picker(ctx, "training", "gym")
    blk = design.metcon_block(P, "short", 10, week_number=4)
    ids = [m.exercise_id for m in blk.metcon.movements]
    sk = ctx.cfg.skills.skills
    unready = [i for i in ids if (ex := ctx.cfg.library.get(i)).skill and not sk[ex.skill].competent]
    c.that(not unready, f"no unmastered skills in the metcon ({unready})")
    c.that("toes_to_bar" not in ids, "toes-to-bar (not competent, kipping rung 0) is scaled out")
    c.that(
        bool(blk.metcon.stimulus) and blk.metcon.time_cap_min == 10,
        "metcon states its intended stimulus and time domain",
    )
    s = design.make_session(
        ctx,
        dt.date(2026, 12, 1),
        "t",
        "upper",
        "t",
        "t",
        [design.warmup("upper", P), blk, design.cooldown(P)],
    )
    c.that(not validate_session(s, ctx.validation()), "metcon session valid")
    c.note(f"movements: {ids}")


# ---------------------------------------------------------------- adjust-day
def _adjust_case(
    c: Check,
    label: str,
    today_rec: float,
    yesterday_rec: float,
    hrv_drop: float,
    drop_days: int,
    expect: str,
    weather=None,
    session_role: str = "upper_skill_metcon",
) -> DayRecord:
    with sandbox():
        day = dt.date(2026, 12, 8)
        ctx = world_at(day, sync_data=False)
        synthetic_metrics(ctx.state, day, today_rec, yesterday_rec, hrv_drop, drop_days=drop_days)
        ctx = build(ctx.state, ctx.cfg, day)
        plan = plan_week.plan_week(ctx, clock.monday_of(day))
        from coach.fallback.templates import build_session

        spec = ctx.cfg.season.spec(ctx.block.key) if ctx.block else None
        s = build_session(ctx, session_role, day, "training", 4.0, day.isocalendar()[1], spec)
        plan.sessions = [x for x in plan.sessions if x.date != day] + [s]
        ctx.state.write_json(f"weeks/{plan.week_id}/plan.json", plan)
        rec = adjust_day.adjust(ctx, day, plan, None, weather or [])
        c.that(
            rec.readiness.state == expect,
            f"{label}: readiness {rec.readiness.state} (expected {expect}; {rec.readiness.reasons})",
        )
        v = validate_session(rec.session, ctx.validation(plan), plan.week_type, plan) if rec.session else []
        c.that(not v, f"{label}: adjusted session valid ({[str(x) for x in v][:2]})")
        c.note(
            f"{label}: {rec.readiness.state} -> {rec.session.title if rec.session else None}; changes: {[ch.what for ch in rec.changes]}"
        )
        return rec


def sc_adjust_green(c: Check) -> None:
    rec = _adjust_case(c, "green", 82, 75, 0, 0, "green")
    c.that(not rec.changes, "green: plan runs as written")


def sc_adjust_yellow(c: Check) -> None:
    rec = _adjust_case(c, "yellow", 30, 70, 0, 0, "yellow")
    s = rec.session
    c.that(not any(b.metcon for b in s.blocks), "yellow: metcon replaced")
    c.that(any(b.kind == "strength" for b in s.blocks), "yellow: primary strength kept")
    c.that(
        any(seg.duration_min == 40 and seg.zone == "Z2" for seg in s.run_segments()),
        "yellow: 40 min Zone 2 instead",
    )


def sc_adjust_red(c: Check) -> None:
    rec = _adjust_case(c, "red", 25, 28, 0, 0, "red")
    c.that(rec.session.type == "recovery", "red: Z1 + mobility only")


def sc_adjust_heat(c: Check) -> None:
    day = dt.date(2026, 12, 8)
    hot = [
        {
            "time": dt.datetime(day.year, day.month, day.day, h),
            "temp_c": 32.0 if 8 <= h <= 18 else 26.0,
            "dew_point_c": 24.0,
            "precip_mm": 0.0,
        }
        for h in range(24)
    ]
    rec = _adjust_case(c, "heat wave", 80, 75, 0, 0, "green", weather=hot, session_role="z2_run")
    c.that(
        rec.weather is not None and rec.weather.tier == "indoor",
        f"heat wave: temp + dew point > 150 -> indoor ({rec.weather and rec.weather.heat_sum})",
    )
    c.that(rec.session.location == "gym", "heat wave: run moved to the gym treadmill")


# ---------------------------------------------------------------- replan
def sc_replan_sick(c: Check) -> None:
    day = dt.date(2026, 12, 1)
    ctx = world_at(day)
    plan = plan_week.plan_week(ctx, dt.date(2026, 11, 30))
    r = log_skill.handle(ctx, "Woke up with a fever and body aches, feel awful", day)
    c.that(ctx.health["illness"]["symptoms"] == "below_neck", "neck check: below-the-neck symptoms detected")
    new = replan.illness(ctx, plan, day, dt.date(2026, 12, 4), "below_neck")
    sick = [s for s in new.sessions if day <= s.date <= dt.date(2026, 12, 4)]
    c.that(all(s.type == "rest" for s in sick), "no training while sick (4 days)")
    c.that(new.session_on(dt.date(2026, 12, 5)).type == "recovery", "graded return day 1: Z1 only")
    health = ctx.state.health()
    health["illness"]["resolved_on"] = "2026-12-05"
    ctx.state.write_json("health.json", health)
    ctx = build(ctx.state, ctx.cfg, day)
    v = validate_week(new, ctx.validation(new))
    c.that(not v, f"replanned week passes ({[str(x) for x in v][:3]})")
    bad = plan.session_on(dt.date(2026, 12, 2))
    ctx.health = {"illness": {"start": "2026-12-01", "symptoms": "below_neck", "resolved_on": None}}
    vv = validate_session(bad, ctx.validation(plan), "training", plan)
    c.that(
        any(x.code == "ILLNESS" for x in vv), "validator rejects training through a below-the-neck illness"
    )
    c.note(r["reply"])


def sc_replan_travel(c: Check) -> None:
    ctx = world_at(dt.date(2026, 12, 6))
    plan = plan_week.plan_week(ctx, dt.date(2026, 12, 7))
    dates = [dt.date(2026, 12, 10) + dt.timedelta(days=i) for i in range(4)]
    new = replan.travel(ctx, plan, dates)
    v = validate_week(new, ctx.validation(new))
    c.that(not v, f"travel week passes (equipment, spacing) ({[str(x) for x in v][:3]})")
    c.that(
        all(
            s.location in {"travel", "outdoor", "home"} or s.type == "rest"
            for s in new.sessions
            if s.date in dates
        ),
        "no gym sessions on travel days",
    )
    c.note(next(d.actual for d in new.deviations if d.field == "key_sessions"))


# ---------------------------------------------------------------- review
def sc_review_adherence(c: Check) -> None:
    ctx = world_at(dt.date(2026, 12, 6))
    plan = plan_week.plan_week(ctx, dt.date(2026, 11, 30))
    ctx.state.write_json(f"weeks/{plan.week_id}/plan.json", plan)
    md, summary = review.weekly_review(ctx, plan)
    c.that(summary["adherence_pct"] < 70, f"adherence dip detected ({summary['adherence_pct']}%)")
    c.that(any("What got in the way" in q for q in summary["questions"]), "asks why before changing the plan")


def sc_review_burnout(c: Check) -> None:
    ctx = world_at(dt.date(2027, 3, 7), sync_data=False)
    end = dt.date(2027, 3, 7)
    for i in range(40):
        d = end - dt.timedelta(days=i)
        recent = i < 14
        ci = Checkin(date=d, enjoyment=2 if recent else 4, session_rpe=8.2 if recent else 7.0, source="chat")
        ctx.state.write_json(f"checkins/{d}.json", ci)
    bw = review.burnout_watch(ctx, end)
    c.that(len(bw["flags"]) == 2, f"burnout watch flags falling enjoyment and rising RPE ({bw['flags']})")
    plan = plan_week.plan_week(ctx, dt.date(2027, 3, 1))
    md, summary = review.weekly_review(ctx, plan)
    c.that(
        any("How are you feeling" in q for q in summary["questions"]),
        "asks about state of mind before prescribing",
    )


# ---------------------------------------------------------------- rehab
def sc_rehab_advance_regress(c: Check) -> None:
    cfg = load_config()
    mr = mv.initial_state(cfg.progressions, dt.date(2026, 11, 16))
    before = mr.model_copy(deep=True)
    evs = []
    for k in range(3):
        evs += mv.record_exposure(
            mr, "hinge", dt.date(2026, 11, 23) + dt.timedelta(days=7 * k), 1.0, False, cfg.progressions
        )
    c.that(mr.rung("hinge") == 1 and len(evs) == 1, "clean advance after 3 pain-free exposures (one rung)")
    from coach.validator import validate_movement_change

    c.that(not validate_movement_change(before, mr, cfg), "advance passes the rung-change validator")
    jump = mr.model_copy(deep=True)
    jump.families["hinge"].rung = 3
    c.that(bool(validate_movement_change(before, jump, cfg)), "a two-rung jump is rejected")
    mid = mr.model_copy(deep=True)
    evs2 = mv.record_exposure(mr, "hinge", dt.date(2026, 12, 14), 3.0, False, cfg.progressions)
    c.that(mr.rung("hinge") == 0 and evs2 and "regress" in evs2[0].reason, "pain 3/10 drops one rung")
    c.that(not validate_movement_change(mid, mr, cfg), "regression passes the validator")
    mv.record_exposure(mr, "hinge", dt.date(2026, 12, 15), 0.0, True, cfg.progressions)
    c.that(
        mr.families["hinge"].eccentric_tempo_until == dt.date(2026, 12, 29),
        "stiffness rise -> 3 s eccentric, -15% for 2 weeks",
    )


# ---------------------------------------------------------------- technique
def sc_technique_competent(c: Check) -> None:
    ctx = world_at(dt.date(2027, 2, 1), sync_data=False)
    mr = ctx.movement
    mr.families["kipping"].rung = 3
    ctx.state.write_json("movement_readiness.json", mr)
    import yaml

    path = ctx.cfg.root / "skills.yaml"
    data = yaml.safe_load(path.read_text())
    data["skills"]["toes_to_bar"]["current_level"] = 2
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    ctx = build(ctx.state, load_config(), dt.date(2027, 2, 1))
    r = log_skill.handle(
        ctx, "Skill session today: got 10 unbroken toes to bar, felt smooth", dt.date(2027, 2, 1)
    )
    msg = [
        technique.set_skill_level(ctx, s, lv, "reported in chat", dt.date(2027, 2, 1))
        for s, lv in r.get("skill_updates", [])
    ]
    cfg = load_config()
    c.that(cfg.skills.skills["toes_to_bar"].competent, f"toes-to-bar marked competent ({msg})")
    ctx = build(ctx.state, cfg, dt.date(2027, 2, 1))
    P = design.Picker(ctx, "training", "gym")
    c.that(P.ok(cfg.library.get("toes_to_bar"), for_metcon=True), "now allowed inside metcons")
    c.note("; ".join(msg))


# ---------------------------------------------------------------- fuel
def sc_fuel_long_run(c: Check) -> None:
    ctx = world_at(dt.date(2026, 12, 5))
    plan = plan_week.plan_week(ctx, dt.date(2026, 11, 30))
    sat = plan.session_on(dt.date(2026, 12, 5))
    sat.expected_minutes = 95
    nd = fuel.day_targets(ctx, dt.date(2026, 12, 5), plan)
    fri = fuel.day_targets(ctx, dt.date(2026, 12, 4), plan)
    c.that(
        nd.carb_tier == "high" and fri.carb_tier == "high",
        "high carbs on the long-run day and the day before",
    )
    c.that(
        "during: 45-60 g carbs/h" in nd.peri_workout, f"intra-session carbs for > 75 min ({nd.peri_workout})"
    )
    c.note(f"long-run day: {nd.kcal} kcal, P{nd.protein_g} F{nd.fat_g} C{nd.carbs_g}")


def sc_fuel_compressed(c: Check) -> None:
    ctx = world_at(dt.date(2026, 12, 5))
    ctx.state.write_json("macrofactor.json", {"weekly_kcal": 2300 * 7})
    plan = plan_week.plan_week(ctx, dt.date(2026, 11, 30))
    days = [fuel.day_targets(ctx, dt.date(2026, 11, 30) + dt.timedelta(days=i), plan) for i in range(7)]
    total = sum(d.kcal for d in days)
    c.that(all(d.scaled for d in days), "carbs scaled down when the weekly target is tight")
    c.that(abs(total - 2300 * 7) <= 14, f"calorie-neutral: {total} vs {2300 * 7}")
    c.that(all(d.fat_g >= 100 for d in days), "fat floor kept at 100 g")
    c.that(
        max(d.carbs_g for d in days) > min(d.carbs_g for d in days),
        "hard days still get more carbs than rest days",
    )


# ---------------------------------------------------------------- compete
def sc_compete_taper(c: Check) -> None:
    ctx = world_at(dt.date(2027, 9, 26), sync_data=False)
    b4 = ctx.macro.blocks[3]
    ol = plan_block.build_outline(ctx, b4, None, [40.0, 42.0, 44.0])
    vols = [w.run_miles for w in ol.weeks if w.type == "taper"]
    c.that(len(vols) == 3 and vols[0] > vols[1] > vols[2], f"3-week taper with falling volume {vols}")
    c.that(abs(vols[0] / 44 - 0.8) < 0.02 and abs(vols[2] / 44 - 0.4) < 0.02, "taper ~80/60/40%")
    md = compete.marathon_plan(ctx)
    c.that(
        ("7:28/mi" in md or "7:29/mi" in md) and "60-90 g carbs/h" in md and "Contingencies" in md,
        "race plan has pacing, fuelling and contingencies",
    )
    ctx.state.write_text("events/marathon-2027.md", md)


def sc_compete_open(c: Check) -> None:
    ctx = world_at(dt.date(2027, 2, 14), sync_data=False)
    plan = plan_week.plan_week(ctx, dt.date(2027, 2, 15))
    c.that(plan.week_type == "competition", "Open week is a competition week")
    v = validate_week(plan, ctx.validation(plan))
    c.that(not v, f"Open week passes ({[str(x) for x in v][:3]})")
    att = [s for s in plan.sessions if s.type == "competition"]
    c.that(att and att[0].date == dt.date(2027, 2, 19), "attempt Friday after Thursday's release")
    md = compete.open_week_strategy(ctx, dt.date(2027, 2, 15), "27.1")
    c.that(
        "scaled division" in md and "Re-attempt" in md, "strategy covers division choice and re-attempt rule"
    )


# ---------------------------------------------------------------- log
def sc_log_messy(c: Check) -> None:
    ctx = world_at(dt.date(2026, 12, 12), sync_data=False)
    day = dt.date(2026, 12, 12)
    r1 = log_skill.handle(ctx, "did the metcon - 4 rds + 12, wallballs unbroken, burpees slow, rpe 8", day)
    m = ctx.state.read_json(f"metcons/{day}.json")["results"][-1]
    c.that(
        m["rounds"] == 4 and m.get("extra_reps") == 12 and m["rpe"] == 8.0,
        f"messy metcon parsed ({m.get('rounds')}+{m.get('extra_reps')})",
    )
    r2 = log_skill.handle(ctx, "check in: back 2, shoulder 3, slept badly", day)
    ci = ctx.state.read_json(f"checkins/{day}.json")
    c.that(
        ci["joints"]["back"] == 2 and ci["joints"]["shoulders"] == 3 and ci.get("sleep_note"),
        "check-in parsed (back 2, shoulder 3, slept badly)",
    )
    r3 = log_skill.handle(ctx, "metcon done, legs were toast", day)
    c.that(r3["follow_up"] is not None, "asks one short follow-up when the score is missing")
    c.note(f"{r1['reply']} | {r2['reply']} | follow-up: {r3['follow_up']}")


def sc_log_red_flag(c: Check) -> None:
    day = dt.date(2026, 12, 12)
    ctx = world_at(day)
    r = log_skill.handle(
        ctx, "Felt some chest pain and got dizzy on the treadmill yesterday, probably nothing", day
    )
    c.that("chest pain" in r["red_flags"], "chest pain detected as a red flag")
    c.that("doctor" in r["reply"], "tells the athlete to stop and see a doctor")
    ctx = build(ctx.state, ctx.cfg, day + dt.timedelta(days=1))
    plan = plan_week.plan_week(ctx, clock.monday_of(day + dt.timedelta(days=1)))
    rec = adjust_day.adjust(ctx, day + dt.timedelta(days=1), plan, None, [])
    c.that(rec.status == "stopped_red_flag" and rec.session.type == "rest", "next day's session is stopped")
    v = validate_week(plan, ctx.validation(plan))
    c.that(
        any(x.code == "RED_FLAG" for x in v), "validator rejects any plan that trains through the red flag"
    )


# ---------------------------------------------------------------- learn
def sc_learn_calibration(c: Check) -> None:
    day = dt.date(2027, 2, 3)
    ctx = world_at(day, sync_data=False)
    rng = random.Random(5)
    for i in range(1, 50):
        d = day - dt.timedelta(days=i)
        st = "yellow" if i % 5 == 0 else "green"
        ctx.state.write_json(
            f"days/{d}.json",
            DayRecord(date=d, status="complete", readiness=Readiness(date=d, state=st, reasons=["x"])),
        )
        ctx.state.write_json(
            f"checkins/{d + dt.timedelta(days=1)}.json",
            Checkin(date=d + dt.timedelta(days=1), session_rpe=round(7 + rng.uniform(-0.3, 0.3), 1)),
        )
    md, prop = learn.calibration(ctx, day)
    c.that(
        prop is not None and prop.status == "pending", "calibration produces a pending proposal (N=1 trial)"
    )
    if prop:
        c.that("Stop rule" in prop.what, "trial has a metric and a stop rule")
        lock = ctx.state.read_json("config_lock.json")
        proposals.approve(ctx.state, prop.id, day, ctx.cfg)
        cfg2 = load_config()
        approved = {p.id for p in ctx.state.proposals("approved")}
        c.that(cfg2.profile.thresholds.recovery_green_min == 64, "approval applies the threshold change")
        c.that(
            not validate_config_lock(cfg2, ctx.state.read_json("config_lock.json"), approved),
            "config lock updated by the approved proposal",
        )
        c.that(
            bool(validate_config_lock(cfg2, lock, approved)),
            "an unapproved threshold change would be rejected",
        )
        c.that(
            "changelog" in ctx.state.read_text("changelog.md") or ctx.state.read_text("changelog.md"),
            "change logged in the changelog",
        )
    sci = learn.science_audit_scaffold(ctx, day)
    c.that(
        "PMID" in sci and "No findings, no citations" in sci, "offline science audit never invents citations"
    )


SCENARIOS: list[tuple[str, str, Callable[[Check], None]]] = [
    ("assess", "baseline week + goal proposal", sc_assess_baseline),
    ("plan-week", "normal week", sc_plan_week_normal),
    ("plan-week", "deload week", sc_plan_week_deload),
    ("design-session", "metcon at the right skill level", sc_design_metcon),
    ("adjust-day", "Green", sc_adjust_green),
    ("adjust-day", "Yellow", sc_adjust_yellow),
    ("adjust-day", "Red", sc_adjust_red),
    ("adjust-day", "heat wave", sc_adjust_heat),
    ("replan", "sick 4 days (below the neck) + graded return", sc_replan_sick),
    ("replan", "travel with no gym", sc_replan_travel),
    ("review", "adherence dip", sc_review_adherence),
    ("review", "burnout watch", sc_review_burnout),
    ("rehab", "clean advance + pain regression", sc_rehab_advance_regress),
    ("technique", "skill marked competent", sc_technique_competent),
    ("fuel", "long-run day", sc_fuel_long_run),
    ("fuel", "compressed-carb week", sc_fuel_compressed),
    ("compete", "taper + marathon race plan", sc_compete_taper),
    ("compete", "Open week", sc_compete_open),
    ("log", "messy metcon + check-in", sc_log_messy),
    ("log", "red flag stops training", sc_log_red_flag),
    ("learn", "calibration proposal needs approval", sc_learn_calibration),
]


def run_one(fn: Callable[[Check], None]) -> Check:
    c = Check()
    with sandbox():
        try:
            fn(c)
        except Exception as e:  # noqa: BLE001 - report, don't crash the whole suite
            import traceback

            c.failures.append(
                f"crashed: {type(e).__name__}: {e} @ {traceback.format_exc().splitlines()[-3].strip()}"
            )
    return c


def run_all(echo=print, only: str | None = None) -> list[dict]:
    out = []
    echo("\n=== Per-skill scenarios ===")
    for skill, name, fn in SCENARIOS:
        if only and only != skill:
            continue
        c = run_one(fn)
        passed = not c.failures
        detail = "; ".join(c.failures) if c.failures else "; ".join(c.notes) or "ok"
        echo(f"[{'PASS' if passed else 'FAIL'}] {skill}: {name}" + (f" - {detail}" if detail else ""))
        out.append({"skill": skill, "name": name, "passed": passed, "detail": detail})
    return out
