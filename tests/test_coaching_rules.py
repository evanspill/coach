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
    ramps = [it for s in plan.sessions for b in s.blocks if b.kind == "strength" for it in b.items if it.ramp]
    assert ramps, "primary strength lifts should carry warm-up ramp sets"
    for it in ramps:
        assert all(r.load_kg < it.load_kg for r in it.ramp)


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
