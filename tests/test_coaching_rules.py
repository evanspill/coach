"""Rules added in the coaching audit: current e1RM, warm-up ramps, session length, prescription completeness,
rest days, extreme cold, new red flags, energy availability / 80-20, and the record submit pipeline."""

import datetime as dt

import pytest
from pydantic import ValidationError

from coach.coaching import records
from coach.engine import loads as L
from coach.engine import weather
from coach.engine.parsing import detect_red_flags
from coach.engine.validator import validate_week
from coach.models import Deviation, Prescription
from coach.models.metrics import SessionRecord, SetRecord
from coach.models.plans import RampSet

TODAY = dt.date(2026, 11, 29)


def codes(plan, ctx):
    return {v.code for v in validate_week(plan, ctx.validation(plan))}


@pytest.fixture
def P(b1):
    ctx, plan, _ = b1
    return ctx, plan.model_copy(deep=True)


def _session(day, kg, reps, rir=2.0, ex="back_squat"):
    return SessionRecord(
        id=f"s-{day}",
        date=day,
        start=dt.datetime(day.year, day.month, day.day, 9),
        sport="strength",
        title="lift",
        duration_min=60,
        sets=[
            SetRecord(exercise_id=ex, exercise_name=ex, set_type="warmup", weight_kg=kg * 0.5, reps=5),
            SetRecord(exercise_id=ex, exercise_name=ex, weight_kg=kg, reps=reps, rir=rir),
        ],
    )


# --- loads ---------------------------------------------------------------------------------------------


def test_current_e1rm_uses_latest_exposure_not_best_ever():
    hist = [_session(TODAY - dt.timedelta(days=30), 140, 5), _session(TODAY - dt.timedelta(days=5), 120, 5)]
    v, why = L.current_e1rm(hist, "back_squat", TODAY)
    assert v == pytest.approx(L.e1rm(120, 5, 2.0))
    assert "latest exposure" in why


def test_current_e1rm_discounts_after_a_layoff():
    hist = [_session(TODAY - dt.timedelta(days=35), 120, 5)]
    v, why = L.current_e1rm(hist, "back_squat", TODAY)
    assert v == pytest.approx(L.e1rm(120, 5, 2.0) * 0.95)
    assert "no exposure" in why
    assert L.current_e1rm([], "back_squat", TODAY) == (None, "no history")


def test_warmup_sets_are_ignored_for_e1rm():
    s = _session(TODAY - dt.timedelta(days=3), 100, 5)
    s.sets[0].weight_kg = 200  # a mislabelled heavy "warmup" must not inflate the estimate
    v, _ = L.current_e1rm([s], "back_squat", TODAY)
    assert v == pytest.approx(L.e1rm(100, 5, 2.0))


def test_ramp_sets_climb_below_the_working_weight(b1):
    ctx, _, _ = b1
    loading = ctx.cfg.equipment.loading
    ramp = L.ramp_sets(100, "barbell", loading, 5)
    kgs = [kg for _, kg, _ in ramp]
    assert kgs == sorted(kgs) and len(set(kgs)) == len(kgs)
    assert all(kg < 100 for kg in kgs) and len(ramp) == 3
    assert [r for r, _, _ in ramp] == [5, 3, 1]
    assert L.ramp_sets(25, "barbell", loading, 5) == [] or all(
        kg < 25 for _, kg, _ in L.ramp_sets(25, "barbell", loading, 5)
    )


def test_primary_lifts_get_a_ramp_in_the_plan(b1):
    _, plan, _ = b1
    ramps = [
        it
        for s in plan.sessions
        for b in s.blocks
        if b.kind == "strength"
        for it in b.items
        if it.ramp and it.load_kg
    ]
    assert ramps, "primary strength lifts should carry warm-up ramp sets"
    for it in ramps:
        assert all(r.load_kg is not None and r.load_kg < it.load_kg for r in it.ramp)


def test_ramp_tiers_and_machine_stacks(b1):
    ctx, _, _ = b1
    loading = ctx.cfg.equipment.loading
    assert [r for r, _, _ in L.ramp_sets(100, "barbell", loading, 8, "build")] == [5, 3]
    assert [r for r, _, _ in L.ramp_sets(100, "barbell", loading, 12, "feeler")] == [5]
    stack = L.ramp_sets(50, "cable", loading, 10, "build")
    assert stack and all(lb is not None and lb % 5 == 0 for _, _, lb in stack)
    assert L.ramp_sets(2, "machine", loading, 10, "feeler") == []  # too light to warm up below
    assert [L.bodyweight_warmup_reps(n) for n in (None, 1, 5, 12)] == [2, 1, 2, 3]


def _warmup_session(items):
    from coach.models import Session, SessionBlock

    blocks = [SessionBlock(kind=k, title=k, items=[Prescription(**i)]) for k, i in items]
    return Session(
        id="t", date=TODAY, type="lower", title="t", intent="t", expected_minutes=60, blocks=blocks
    )


def test_every_strength_exercise_gets_warmups_sized_to_the_session(b1):
    from coach.coaching.fill import Filler

    ctx, _, _ = b1
    f = Filler(ctx.cfg.library, ctx.cfg.equipment.loading, [], ctx.zones, TODAY, ctx.cfg.training.rules)
    s = _warmup_session(
        [
            ("power", {"exercise_id": "box_jump", "sets": 3, "reps": 3}),
            ("strength", {"exercise_id": "trap_bar_deadlift_high", "sets": 4, "reps": 4, "rir": 2}),
            ("strength", {"exercise_id": "strict_pull_up", "sets": 4, "reps": 6}),
            ("hypertrophy", {"exercise_id": "seated_leg_curl", "sets": 3, "reps": 10, "rir": 2}),
            ("hypertrophy", {"exercise_id": "side_plank", "sets": 2, "duration_s": 30}),
        ]
    )
    f.fill(s)
    by = {it.exercise_id: it for b in s.blocks for it in b.items}
    assert by["box_jump"].ramp == []  # jumps are primed by the warm-up block
    dl = by["trap_bar_deadlift_high"]
    assert [r.pct for r in dl.ramp] == [0.5, 0.7, 0.85]  # no history: percentage ramp + note
    assert all(r.load_kg is None for r in dl.ramp) and "warm-up ~50% x4" in (dl.load_note or "")
    assert [(r.reps, r.load_kg) for r in by["strict_pull_up"].ramp] == [(2, None)]
    assert len(by["seated_leg_curl"].ramp) == 1  # isolation on a fresh prime mover: one feeler set
    s2 = _warmup_session(
        [
            ("hypertrophy", {"exercise_id": "seated_leg_curl", "sets": 3, "reps": 10, "rir": 2}),
            ("hypertrophy", {"exercise_id": "seated_leg_curl", "sets": 2, "reps": 12, "rir": 1}),
        ]
    )
    f.fill(s2)
    assert len(s2.blocks[0].items[0].ramp) == 1 and s2.blocks[1].items[0].ramp == []  # warm isolation: none
    assert by["side_plank"].ramp == []
    f.fill(s)  # refilling is idempotent
    assert by["trap_bar_deadlift_high"].load_note.count("warm-up") == 1
    dl.load_note = "kept from an earlier fill; warm-up ~50% x4 of your working weight"
    f.warmups(s)  # even without the load reset, the plan is never appended twice
    assert (dl.load_note or "").count("warm-up") == 1
    dl.load_note = "warm-up ~50% x4 of your working weight"
    f.warmups(s)
    assert (dl.load_note or "").count("warm-up") == 1
    with pytest.raises(ValidationError):
        RampSet(reps=5, pct=5.0)


def test_bodyweight_and_self_selected_warmups_push_without_a_weight(b1):
    from coach.integrations.push import hevy_routine

    ctx, plan, _ = b1
    s = next(s for s in plan.sessions if any(it.ramp for b in s.blocks for it in b.items)).model_copy(
        deep=True
    )
    it = next(it for b in s.blocks for it in b.items if it.ramp)
    it.ramp = [RampSet(reps=2), RampSet(reps=5, pct=0.5)]
    body = hevy_routine(s, ctx)
    assert body is not None
    warm = [
        st
        for ex in body["exercises"]
        for st in ex["sets"]
        if st["type"] == "warmup" and "weight_kg" not in st and "reps" in st
    ]
    assert {st["reps"] for st in warm} >= {2, 5}


def test_last_used_loads_round_dumbbells_and_keep_machine_numbers(b1):
    from coach.coaching.fill import Filler
    from coach.models import Session, SessionBlock

    ctx, _, _ = b1
    hist = [
        _session(TODAY - dt.timedelta(days=4), 13.3, 12, ex="ytw_raise"),
        _session(TODAY - dt.timedelta(days=3), 47.5, 12, ex="leg_press"),
    ]
    f = Filler(ctx.cfg.library, ctx.cfg.equipment.loading, hist, ctx.zones, TODAY)
    s = Session(
        id="t",
        date=TODAY,
        type="upper",
        title="t",
        intent="test",
        expected_minutes=30,
        location="gym",
        blocks=[
            SessionBlock(
                kind="hypertrophy",
                items=[
                    Prescription(exercise_id="ytw_raise", sets=2, reps=12, rir=2),
                    Prescription(exercise_id="leg_press", sets=2, reps=12, rir=2),
                ],
            )
        ],
    )
    f.fill(s)
    db, machine = s.blocks[0].items
    assert db.load_kg and db.load_kg != 13.3 and "last used" in db.load_note
    assert machine.load_kg == 47.5 and "47.5 kg" in machine.load_note


# --- validator -----------------------------------------------------------------------------------------


def test_session_length_cap(P):
    ctx, plan = P
    s = next(s for s in plan.sessions if s.type in {"full_body", "upper", "lower"})
    s.expected_minutes = ctx.cfg.training.rules.max_session_minutes + 30
    assert "SESSION_LENGTH" in codes(plan, ctx)


def test_long_runs_are_exempt_from_session_length(P):
    ctx, plan = P
    long_runs = [s for s in plan.sessions if s.type in ctx.cfg.training.rules.long_session_types]
    if not long_runs:
        pytest.skip("no long session this week")
    long_runs[0].expected_minutes = ctx.cfg.training.rules.max_session_minutes + 30
    assert "SESSION_LENGTH" not in codes(plan, ctx)


def test_prescription_needs_reps_and_rir(P):
    ctx, plan = P
    s = next(s for s in plan.sessions if any(b.kind == "strength" for b in s.blocks))
    b = next(b for b in s.blocks if b.kind == "strength")
    b.items[0].rir = None
    assert "PRESCRIPTION_INCOMPLETE" in codes(plan, ctx)
    b.items[0] = Prescription(exercise_id=b.items[0].exercise_id, sets=3)
    assert "PRESCRIPTION_INCOMPLETE" in codes(plan, ctx)


def test_at_least_one_rest_or_recovery_day(P):
    ctx, plan = P
    from coach.coaching.skills.templates import build_session

    for i, s in enumerate(plan.sessions):
        if s.type in {"rest", "recovery"}:
            plan.sessions[i] = build_session(
                ctx, "travel_run", s.date, "training", 3.0, s.date.isocalendar()[1]
            )
    assert "REST_DAY" in codes(plan, ctx)
    plan.deviations.append(Deviation(field="rest_days", planned="1", actual="0", reason="race week shuffle"))
    assert "REST_DAY" not in codes(plan, ctx)


# --- weather / safety ----------------------------------------------------------------------------------


def test_extreme_cold_moves_work_indoors(b1):
    ctx, _, _ = b1
    rules = ctx.cfg.profile.weather
    day = dt.date(2027, 1, 20)
    hours = [
        {"time": dt.datetime(2027, 1, 20, h), "temp_c": -20.0, "dew_point_c": -25.0, "precip_mm": 0.0}
        for h in range(24)
    ]
    call = weather.weather_call(day, hours, rules, 41.8, -72.9)
    assert call.tier == "indoor"
    assert any("extreme cold" in r for r in call.reasons)


@pytest.mark.parametrize(
    "text,flag",
    [
        ("my heart was racing at rest last night", "palpitations / irregular heartbeat"),
        ("felt an irregular heartbeat on the stairs", "palpitations / irregular heartbeat"),
        ("I stopped sweating near the end of the run", "possible heat illness"),
        ("got confused during the run in the heat", "possible heat illness"),
    ],
)
def test_new_red_flags(text, flag):
    assert flag in detect_red_flags(text)


def test_ordinary_soreness_is_not_a_red_flag():
    assert detect_red_flags("heart rate was high on the tempo, legs heavy") == []


# --- review flags --------------------------------------------------------------------------------------


def test_energy_availability_and_easy_share_are_computable(b1):
    from coach.coaching.skills import review

    ctx, _, _ = b1
    start, end = TODAY - dt.timedelta(days=13), TODAY
    ea = review.energy_availability(ctx, start, end)
    assert ea is None or 5 < ea < 80
    share = review.easy_share(ctx, start, end)
    assert share is None or 0 <= share <= 1


# --- submit pipeline (writes state: keep last in the module) -------------------------------------------


def test_submit_refuses_an_invalid_week(b1):
    ctx, plan, _ = b1
    bad = plan.model_copy(deep=True)
    bad.sessions[0].blocks[0].items[0].exercise_id = "not_an_exercise"
    with pytest.raises(records.SubmitRefused) as e:
        records.submit(ctx.state, ctx.cfg, "week_plans", bad.model_dump(mode="json"), TODAY)
    assert e.value.violations
    assert ctx.state.get("week_plans", bad.week_id) is None


def test_submit_fills_saves_and_proposes(b1):
    ctx, plan, _ = b1
    draft = plan.model_copy(deep=True)
    for s in draft.sessions:
        for b in s.blocks:
            for it in b.items:
                it.load_kg = it.load_lb = None  # Claude never writes numbers; code fills them
    out = records.submit(ctx.state, ctx.cfg, "week_plans", draft.model_dump(mode="json"), TODAY)
    assert out["saved"] == f"week_plans/{plan.week_id}"
    assert any("filled" in a for a in out["actions"])
    saved = ctx.state.get("week_plans", plan.week_id)
    assert any(it.load_kg for s in saved.sessions for b in s.blocks for it in b.items)
    if ctx.cfg.settings.approval.weekly_plan == "manual":
        assert any("proposal" in a for a in out["actions"])


def test_submit_report_and_plain_record(b1):
    ctx, _, _ = b1
    out = records.submit(ctx.state, ctx.cfg, "week_summaries", "# hello", TODAY, key="2026-W48-test")
    assert out["kind"] == "report"
    with pytest.raises(ValidationError):
        records.submit(ctx.state, ctx.cfg, "journal", {"nonsense": True}, TODAY)


def test_whoop_offline_finalizes_without_guessing(home):
    """Broker down / strap not syncing: the day completes with no readiness score instead of waiting forever."""
    import dataclasses

    from coach.coaching.daily import run_daily
    from coach.integrations.base import WhoopSource
    from coach.integrations.mock import MockWorld, mock_sources
    from coach.store import Store

    class OfflineWhoop(WhoopSource):
        def daily(self, start, end):
            raise RuntimeError("WHOOP_BROKER_URL not configured")

        def workouts(self, start, end):
            raise RuntimeError("WHOOP_BROKER_URL not configured")

    day = dt.date(2026, 11, 17)
    src = dataclasses.replace(mock_sources(MockWorld.load()), whoop=OfflineWhoop())
    res = run_daily(src, Store(), day, auto_approve=True)
    rec = res.record
    assert rec is not None and rec.status == "complete"
    assert rec.readiness.state == "unknown" and rec.readiness.recovery_score is None
    assert "whoop: fetch failed" in rec.stale_sources
    assert res.notification.startswith("NO SCORE: Whoop offline")
    assert "9:05" not in res.notification
    assert run_daily(src, Store(), day, phase="catchup").log == ["catch-up: nothing waiting"]


def test_test_block_minutes_follow_the_work():
    from coach.coaching.skills.design import estimate_minutes
    from coach.models import Session
    from coach.models.plans import Prescription
    from coach.models.plans import SessionBlock as Block

    def sess(*blocks):
        return Session(
            id="x",
            date=dt.date(2026, 11, 17),
            type="test",
            title="t",
            intent="i",
            expected_minutes=0,
            blocks=list(blocks),
        )

    hold = Block(
        kind="test",
        title="h",
        test_id="sorensen_hold",
        items=[Prescription(exercise_id="sorensen_hold", sets=1, duration_s=240)],
    )
    sides = Block(
        kind="test",
        title="s",
        test_id="side_bridge",
        items=[Prescription(exercise_id="side_plank", sets=1, duration_s=180, per_side=True)],
    )
    rm = Block(
        kind="test",
        title="r",
        test_id="hinge_rm",
        items=[Prescription(exercise_id="trap_bar_deadlift_high", sets=5, reps=5, rir=2)],
    )
    assert estimate_minutes(sess(hold), 480) == 10  # 4 min hold + 2 rest + 2 setup -> rounded to 5s
    assert estimate_minutes(sess(sides), 480) == 15  # two sides x (3 + 2) + 2
    assert estimate_minutes(sess(rm), 480) == 25  # rep-max work-up keeps the 22-min allowance


# --- coaching skill fallbacks ---------------------------------------------------------------------------


def test_plan_week_ramp_cap_uses_the_configured_pct(home, monkeypatch):
    from coach.coaching.skills.plan_week import plan_week
    from coach.sim.scenarios import world_at

    ctx = world_at(dt.date(2026, 11, 29))
    monkeypatch.setattr(ctx.cfg.profile.running, "ramp_start_miles", (5.0, 6.0))
    monkeypatch.setattr(ctx, "trailing_miles", lambda *a, **k: [9.5, 9.5, 9.5])
    th = ctx.cfg.profile.thresholds
    monkeypatch.setattr(th, "weekly_run_increase_pct", 10.0)
    assert not [d for d in plan_week(ctx, dt.date(2026, 11, 30)).deviations if d.field == "run_miles"]
    monkeypatch.setattr(th, "weekly_run_increase_pct", 2.0)
    dev = [d for d in plan_week(ctx, dt.date(2026, 11, 30)).deviations if d.field == "run_miles"]
    assert dev and dev[0].actual == "9.7" and "+2%" in dev[0].reason


def test_block_outline_ramp_uses_the_configured_pct(home, monkeypatch):
    from coach.coaching.skills import plan_block
    from coach.sim.scenarios import world_at

    ctx = world_at(dt.date(2026, 11, 29))
    b1 = ctx.macro.blocks[0]
    th = ctx.cfg.profile.thresholds
    monkeypatch.setattr(th, "weekly_run_increase_pct", 10.0)
    assert plan_block.build_outline(ctx, b1, None, [11.0] * 3).weeks[0].run_miles == 12.1
    monkeypatch.setattr(th, "weekly_run_increase_pct", 2.0)
    assert plan_block.build_outline(ctx, b1, None, [11.0] * 3).weeks[0].run_miles == 11.2


@pytest.mark.parametrize(
    "text,symptoms",
    [
        ("bad cough today", "above_neck"),
        ("sneezing all morning", "above_neck"),
        ("chills and vomiting overnight", "below_neck"),
        ("stomach bug, diarrhea since last night", "below_neck"),
        ("threw up after dinner, feverish", "below_neck"),
        ("vomiting on and off since last night", "below_neck"),
    ],
)
def test_log_neck_check_catches_every_symptom_classify_knows(home, text, symptoms):
    from coach.coaching.skills import log as log_skill
    from coach.sim.scenarios import world_at

    day = dt.date(2026, 11, 29)
    ctx = world_at(day, with_outline=False, sync_data=False)
    r = log_skill.handle(ctx, text, day)
    assert r.get("handoff") == "replan"
    ev = next(e for e in ctx.state.health_events() if e.kind == "illness")
    assert ev.symptoms == symptoms


def test_exertional_vomiting_logs_the_metcon_not_an_illness(home):
    from coach.coaching.skills import log as log_skill
    from coach.sim.scenarios import world_at

    day = dt.date(2026, 11, 29)
    ctx = world_at(day, with_outline=False, sync_data=False)
    r = log_skill.handle(ctx, "metcon: 5 rounds + 3 reps, almost threw up during the burpees, rpe 9", day)
    assert "handoff" not in r and not [e for e in ctx.state.health_events() if e.kind == "illness"]
    assert r["reply"].startswith("Logged")


def test_reported_skill_milestone_below_the_current_level_never_demotes(home):
    import yaml

    from coach.coaching.skills import technique
    from coach.sim.scenarios import world_at

    day = dt.date(2026, 11, 29)
    ctx = world_at(day, with_outline=False, sync_data=False)
    path = ctx.cfg.root / "skills.yaml"
    data = yaml.safe_load(path.read_text())
    data["skills"]["strict_pull_up"]["current_level"] = 3
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    msg = technique.set_skill_level(ctx, "strict_pull_up", 2, "reported in chat", day)
    assert "already at level 3" in msg
    assert yaml.safe_load(path.read_text())["skills"]["strict_pull_up"]["current_level"] == 3


def test_family_movement_in_a_metcon_respects_skill_competence(home):
    from types import SimpleNamespace

    from coach.coaching.skills import design as D
    from coach.sim.scenarios import world_at

    ctx = world_at(dt.date(2026, 11, 29), with_outline=False, sync_data=False)
    ctx.movement.families["kipping"].rung = 2  # rung exercise: kipping pull-up, a skill not yet competent
    P = D.Picker(ctx, "training", "gym", restricted=set())
    spec = SimpleNamespace(
        family="kipping",
        exercise=None,
        deload_exercise=None,
        sets=1,
        reps=10,
        reps_max=None,
        rir=None,
        duration_s=None,
        distance_m=None,
        calories=None,
        rest_s=None,
        per_side=False,
        alternating=None,
        notes=None,
        tempo=None,
    )
    assert D._from_spec(spec, P, "strength").exercise_id == "kipping_pull_up"
    got = D._from_spec(spec, P, "conditioning", for_metcon=True)
    assert got is None or P.ok(ctx.cfg.library.get(got.exercise_id), for_metcon=True)


def test_the_day_after_red_follows_its_own_readiness_unless_a_joint_was_red(home):
    """Audit 2026-11-23: a Red day no longer forces the next day easy; a joint rated at the Red level still does
    (and a test on that day moves)."""
    from coach.coaching.skills import adjust_day
    from coach.coaching.skills.plan_week import plan_week
    from coach.models import DayRecord
    from coach.sim.scenarios import world_at

    day = dt.date(2026, 11, 17)
    ctx = world_at(day, with_outline=False)
    plan = plan_week(ctx, dt.date(2026, 11, 16))
    tests = plan.session_on(day).tests
    assert tests and ctx.readiness(day).state != "red"
    y = day - dt.timedelta(days=1)
    red = ctx.readiness(y).model_copy(
        update={"state": "red", "reasons": ["HRV trend below baseline band 3 days"]}
    )
    ctx.state.put("day_records", DayRecord(date=y, status="complete", readiness=red))
    rec = adjust_day.adjust(ctx, day, plan.model_copy(deep=True))
    assert rec.session.type == "test" and rec.session.tests == tests  # today's own readiness decides

    red_joint = red.model_copy(update={"reasons": ["back rated 4/5"], "joints": {"back": 4}})
    ctx.state.put("day_records", DayRecord(date=y, status="complete", readiness=red_joint))
    rec = adjust_day.adjust(ctx, day, plan)
    assert rec.session.type == "recovery"
    assert any(c.what.startswith(f"tests {tests} moved to") for c in rec.changes)
    assert any(set(tests) <= set(s.tests) for s in plan.sessions if s.date > day)


def test_adjust_day_keeps_the_high_carb_tier_before_the_long_run(home):
    from coach.coaching.skills import adjust_day
    from coach.coaching.skills.plan_week import plan_week
    from coach.sim.scenarios import world_at

    day = dt.date(2026, 12, 4)
    ctx = world_at(day)
    plan = plan_week(ctx, dt.date(2026, 11, 30))
    assert plan.session_on(day + dt.timedelta(days=1)).type == "run_long"
    plan.session_on(day).type = "upper"  # a moderate-tier type on its own
    rec = adjust_day.adjust(ctx, day, plan)
    assert rec.status == "complete"
    assert rec.session.carb_tier == "high" == rec.nutrition.carb_tier


def test_a_week_plan_draft_cannot_approve_itself(home):
    from coach.coaching.records import submit
    from coach.coaching.skills.plan_week import plan_week
    from coach.sim.scenarios import world_at

    day = dt.date(2026, 11, 29)
    ctx = world_at(day)
    draft = plan_week(ctx, dt.date(2026, 11, 30)).model_dump(mode="json")
    draft["approval"] = "approved"
    submit(ctx.state, ctx.cfg, "week_plans", draft, day)
    assert ctx.state.week_plan(draft["week_id"]).approval == "pending"
    assert any(p.kind == "weekly_plan" for p in ctx.state.proposals("pending"))


def test_a_block_goal_draft_cannot_approve_itself(home):
    from coach.coaching import proposals
    from coach.coaching.records import submit
    from coach.coaching.skills import assess
    from coach.sim.scenarios import baseline_testset, world_at

    day = dt.date(2026, 11, 29)
    ctx = world_at(day)
    goal, _ = assess.propose_goal(ctx, ctx.macro.blocks[1], baseline_testset(ctx))
    draft = goal.model_dump(mode="json")
    draft["status"] = "approved"
    submit(ctx.state, ctx.cfg, "block_goals", draft, day)  # nothing stored yet
    assert ctx.state.goal(goal.block_id).status == "pending"
    prop = next(p for p in ctx.state.proposals("pending") if p.kind == "block_goal")
    proposals.approve(ctx.state, prop.id, day, ctx.cfg)
    stored = ctx.state.goal(goal.block_id).model_dump(mode="json")
    submit(ctx.state, ctx.cfg, "block_goals", stored, day)  # unchanged approved goal stays approved
    assert ctx.state.goal(goal.block_id).status == "approved"
    stored["primary"]["target_value"] += 5
    submit(ctx.state, ctx.cfg, "block_goals", stored, day)  # changed target: back to pending
    assert ctx.state.goal(goal.block_id).status == "pending"


def test_approve_and_reject_guard_their_state(home):
    import argparse

    from coach.cli import cmd_approve, cmd_reject
    from coach.coaching import proposals
    from coach.sim.scenarios import world_at

    day = dt.date(2026, 11, 29)
    ctx = world_at(day)
    ns = dict(date=day.isoformat(), note="")
    ctx.state.delete("config_lock")
    assert cmd_approve(argparse.Namespace(target="initial-config", **ns)) == {"approved": "initial-config"}
    assert "error" in cmd_approve(argparse.Namespace(target="initial-config", **ns))  # only once
    assert "error" in cmd_approve(argparse.Namespace(target="2026-11-29-typo", **ns))
    p = proposals.create(ctx.state, "config_change", "coach", "t", "w", "y", day)
    cmd_approve(argparse.Namespace(target=p.id, **ns))
    r = cmd_reject(argparse.Namespace(id=p.id, reason="changed my mind", date=day.isoformat()))
    assert "error" in r and ctx.state.proposal(p.id).status == "approved"


def test_record_add_with_bad_json_returns_an_error(home):
    import argparse

    from coach.cli import cmd_record
    from coach.sim.scenarios import world_at

    world_at(dt.date(2026, 11, 29), with_outline=False, sync_data=False)
    base = dict(
        action="add", collection="notes", key=None, file=None, start=None, end=None, date="2026-11-29"
    )
    assert "error" in cmd_record(argparse.Namespace(json="{bad", **base))
    assert "error" in cmd_record(argparse.Namespace(json="[1, 2]", **base))


def test_a_transition_with_no_scored_tests_skips_the_goal(home, monkeypatch):
    from coach.coaching import daily
    from coach.coaching.skills import assess
    from coach.models import TestSet
    from coach.sim.scenarios import world_at

    ctx = world_at(dt.date(2026, 11, 29))
    monkeypatch.setattr(
        assess, "score_week", lambda ctx, bid, phase, *a, **k: TestSet(block_id=bid, phase=phase, results=[])
    )
    called = []
    monkeypatch.setattr(assess, "propose_goal", lambda *a, **k: called.append(1))
    nxt = ctx.macro.blocks[1].start
    log = daily._transition(ctx, nxt - dt.timedelta(days=1), nxt, None, False, None)
    assert not called and any("block goal waits for a retest" in line for line in log)


def test_an_approved_race_target_survives_a_new_prediction(home):
    from coach.coaching import proposals
    from coach.coaching.skills import assess
    from coach.models.goals import RaceTarget
    from coach.sim.scenarios import world_at

    day = dt.date(2026, 11, 29)
    ctx = world_at(day)
    race = next((r for r in ctx.cfg.profile.races if r.kind == "marathon"), None)
    if race is None:
        pytest.skip("demo config has no marathon")
    old = RaceTarget(
        race_id=race.id,
        set_on=day,
        target_time="9:59:00",
        predicted_s=35940,
        basis="x",
        status="approved",
        rationale="x",
    )
    ctx.state.put("race_targets", old)
    out = assess.propose_race_targets(ctx, day)
    if not out:
        pytest.skip("no new prediction for this race")
    assert (
        ctx.state.get("race_targets", race.id).target_time == "9:59:00"
    )  # still pacing from the approved one
    p = next(p for p in ctx.state.proposals("pending") if p.kind == "race_target")
    proposals.approve(ctx.state, p.id, day, ctx.cfg)
    t = ctx.state.get("race_targets", race.id)
    assert t.target_time != "9:59:00" and t.status == "approved"


def test_an_approved_week_keeps_approval_only_for_a_same_shape_revision(home):
    from coach.coaching import proposals
    from coach.coaching.records import submit
    from coach.coaching.skills.plan_week import plan_week
    from coach.sim.scenarios import world_at

    day = dt.date(2026, 11, 29)
    ctx = world_at(day)
    draft = plan_week(ctx, dt.date(2026, 11, 30)).model_dump(mode="json")
    submit(ctx.state, ctx.cfg, "week_plans", draft, day)
    prop = next(p for p in ctx.state.proposals("pending") if p.kind == "weekly_plan")
    proposals.approve(ctx.state, prop.id, day, ctx.cfg)
    same = ctx.state.week_plan(draft["week_id"]).model_dump(mode="json")
    submit(ctx.state, ctx.cfg, "week_plans", same, day)
    assert ctx.state.week_plan(draft["week_id"]).approval == "approved"
    moved = ctx.state.week_plan(draft["week_id"]).model_dump(mode="json")
    moved["sessions"] = [
        s for s in moved["sessions"] if s["type"] != "recovery"
    ]  # a session dropped: re-approve
    submit(ctx.state, ctx.cfg, "week_plans", moved, day)
    assert ctx.state.week_plan(draft["week_id"]).approval == "pending"


def test_rejecting_a_new_race_target_keeps_the_approved_one(home):
    from coach.coaching import proposals
    from coach.coaching.skills import assess
    from coach.models.goals import RaceTarget
    from coach.sim.scenarios import world_at

    day = dt.date(2026, 11, 29)
    ctx = world_at(day)
    race = next((r for r in ctx.cfg.profile.races if r.kind == "marathon"), None)
    if race is None:
        pytest.skip("demo config has no marathon")
    old = RaceTarget(
        race_id=race.id,
        set_on=day,
        target_time="9:59:00",
        predicted_s=35940,
        basis="x",
        status="approved",
        rationale="x",
    )
    ctx.state.put("race_targets", old)
    if not assess.propose_race_targets(ctx, day):
        pytest.skip("no new prediction for this race")
    p = next(p for p in ctx.state.proposals("pending") if p.kind == "race_target")
    proposals.reject(ctx.state, p.id, day, "too aggressive")
    t = ctx.state.get("race_targets", race.id)
    assert t.target_time == "9:59:00" and t.status == "approved"


def test_a_short_deload_week_is_topped_up_to_the_aerobic_minimum(home):
    from coach.coaching.skills import plan_week as PW
    from coach.engine import sessions as S
    from coach.sim.scenarios import world_at

    ctx = world_at(dt.date(2026, 11, 29))
    start = dt.date(2026, 11, 30)
    plan = PW.plan_week(ctx, start)
    outline = ctx.state.outline(plan.block_id)
    for s in plan.sessions:  # a heavily capped week: every run cut to a mile
        for b in s.blocks:
            b.run = [
                seg.model_copy(update={"distance_mi": 1.0, "duration_min": None})
                for seg in b.run
                if seg.modality == "run"
            ]
    plan.week_type = "deload"
    assert (
        S.pillar_doses(plan, ctx.cfg.library, ctx.cfg.tests)["aerobic"]
        < outline.pillars["aerobic"].deload_med
    )
    PW._top_up_aerobic(ctx, plan.sessions, outline, "deload", start)
    assert (
        S.pillar_doses(plan, ctx.cfg.library, ctx.cfg.tests)["aerobic"]
        >= outline.pillars["aerobic"].deload_med
    )
    host = next(s for s in plan.sessions if s.type == "run_long")
    assert host.blocks[-1].kind == "cooldown" and any(
        seg.modality == "bike" for b in host.blocks for seg in b.run
    )


def test_waiting_for_recovery_asks_the_athlete_to_say_when_recovery_is_in():
    from coach.coaching.notify import compose
    from coach.models import DayRecord

    rec = DayRecord(date=dt.date(2026, 11, 18), status="waiting_for_recovery")
    text = compose(rec)
    assert "tell me when recovery is in" in text and "9:05" not in text and "catch-up" not in text


def test_weekly_review_logs_readiness_against_outcome(b1):
    """Audit 2026-11-23: each day's colour next to what happened, so learn can test the colours later."""
    from coach.coaching.skills import review
    from coach.models import DayRecord

    ctx, plan, _ = b1
    ctx.state.put("week_plans", plan)
    d = plan.sessions[0].date
    r = ctx.readiness(d).model_copy(update={"state": "yellow"})
    rec = ctx.state.day_record(d)
    ctx.state.put(
        "day_records", DayRecord(date=d, status="complete", readiness=r, planned_session=rec.planned_session)
    )
    md, summary = review.weekly_review(ctx, ctx.state.week_plan(plan.week_id))
    rows = summary["readiness_outcomes"]
    assert len(rows) == 7 and rows[0]["state"] == "yellow" and rows[0]["session"] == plan.sessions[0].type
    assert "## Readiness vs outcome" in md
