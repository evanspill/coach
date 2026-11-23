"""Every validator rule, each with a failing example built from a known-good plan."""

import datetime as dt

import pytest

from coach.engine.validator import validate_session, validate_week
from coach.models import Deviation, Prescription, RunSegment, SessionBlock
from coach.models.journal import HealthEvent
from coach.models.records import JointFlag


def codes(plan, ctx, **override):
    vctx = ctx.validation(plan)
    for k, v in override.items():
        setattr(vctx, k, v)
    return {v.code for v in validate_week(plan, vctx)}


@pytest.fixture
def P(b1):
    ctx, plan, _ = b1
    return ctx, plan.model_copy(deep=True)


def blk(session, kind):
    return next(b for b in session.blocks if b.kind == kind)


def test_baseline_plan_is_valid(P):
    ctx, plan = P
    assert codes(plan, ctx) == set()


def test_unknown_exercise(P):
    ctx, plan = P
    blk(plan.sessions[0], "strength").items[0].exercise_id = "atlas_stone_to_shoulder"
    assert "EXERCISE_UNKNOWN" in codes(plan, ctx)


def test_rung_above_current(P):
    ctx, plan = P
    blk(plan.sessions[0], "strength").items[0].exercise_id = "conventional_deadlift"
    assert "RUNG_ABOVE" in codes(plan, ctx)


def test_rung_effort_cap(P):
    ctx, plan = P
    blk(plan.sessions[0], "strength").items[0].rir = 0
    assert "RUNG_CAP" in codes(plan, ctx)


def test_joint_flag_restricts_tags(P):
    ctx, plan = P
    blk(plan.sessions[1], "hypertrophy").items.append(Prescription(exercise_id="dips", sets=3, reps=8, rir=2))
    flag = JointFlag(
        region="shoulders",
        since=dt.date(2026, 11, 28),
        restricted_tags=["shoulder_extension_loaded", "overhead"],
        reason="test",
    )
    assert "JOINT_RESTRICTED" in codes(plan, ctx, joint_flags=[flag])
    assert "JOINT_RESTRICTED" not in codes(plan, ctx)


def test_mcgill_before_lower_days(P):
    ctx, plan = P
    w = blk(plan.sessions[0], "warmup")
    w.items = [i for i in w.items if i.exercise_id != "bird_dog"]
    assert "WARMUP_REQUIRED" in codes(plan, ctx)


def test_warmup_and_cooldown_required(P):
    ctx, plan = P
    plan.sessions[1].blocks = plan.sessions[1].blocks[:-1]
    assert "WARMUP_COOLDOWN" in codes(plan, ctx)


def test_session_order(P):
    ctx, plan = P
    s = plan.sessions[1]
    i, j = s.blocks.index(blk(s, "strength")), s.blocks.index(blk(s, "conditioning"))
    s.blocks[i], s.blocks[j] = s.blocks[j], s.blocks[i]
    assert "SESSION_ORDER" in codes(plan, ctx)


def test_skill_not_competent_in_metcon_or_after_fatigue(P):
    ctx, plan = P
    blk(plan.sessions[1], "conditioning").metcon.movements.append(
        Prescription(exercise_id="peg_board_ascent", sets=1, reps=2)
    )
    assert "SKILL_READINESS" in codes(plan, ctx)
    ctx2, plan2 = ctx, plan.model_copy(deep=True)
    blk(plan2.sessions[1], "conditioning").metcon.movements.pop()
    blk(plan2.sessions[1], "hypertrophy").items.append(
        Prescription(exercise_id="peg_board_ascent", sets=3, reps=1, rir=4)
    )
    assert "SKILL_READINESS" in codes(plan2, ctx2)


def test_deload_keeps_eccentric_or_impact(P):
    ctx, plan = P
    assert "DELOAD_ECCENTRIC" in codes(plan, ctx, week_type_override="deload")  # box jumps + BSS still in


def test_run_increase_over_trailing_average(P):
    ctx, plan = P
    long = next(s for s in plan.sessions if s.type == "run_long")
    long.blocks[1].run[0].distance_mi += 6
    assert "RUN_INCREASE" in codes(plan, ctx, trailing_miles=[9.0, 9.5, 10.0])


def test_long_run_fraction(P):
    ctx, plan = P
    long = next(s for s in plan.sessions if s.type == "run_long")
    long.blocks[1].run[0].distance_mi = 7
    assert "LONG_RUN_FRACTION" in codes(plan, ctx, trailing_miles=[14, 14, 14])


def test_hard_sets_outside_block_range(P):
    ctx, plan = P
    blk(plan.sessions[1], "hypertrophy").items[0].sets = 12
    assert "HARD_SETS" in codes(plan, ctx)


def test_two_a_day_and_6h_spacing(P):
    ctx, plan = P
    extra = plan.sessions[2].model_copy(deep=True)
    extra.date = plan.sessions[1].date
    extra.id = "extra-run"
    extra.start_time = "11:00"
    extra.location = "gym"
    for b in extra.blocks:
        b.items = [i for i in b.items if i.exercise_id not in {"copenhagen_plank_short"}]
    plan.sessions.append(extra)
    c = codes(plan, ctx)
    assert "TWO_A_DAY" in c and "SPACING_6H" in c


def test_no_hard_lower_lifting_before_long_run(P):
    ctx, plan = P
    fri = plan.sessions[4]
    fri.blocks.insert(
        2,
        SessionBlock(
            kind="strength", items=[Prescription(exercise_id="trap_bar_deadlift_high", sets=3, reps=5, rir=2)]
        ),
    )
    assert "LONG_RUN_LOWER_24H" in codes(plan, ctx)


def test_forbidden_back_to_back(P):
    ctx, plan = P
    wed = plan.sessions[2]
    wed.blocks[1].run.append(RunSegment(label="tempo", zone="T", duration_min=20))
    assert "BACK_TO_BACK" in codes(plan, ctx)  # Wed threshold -> Thu glycolytic


def test_equipment_at_location(P):
    ctx, plan = P
    plan.sessions[2].blocks[2].items.append(
        Prescription(exercise_id="hip_thrust", sets=3, reps=10, rir=2)
    )  # outdoor
    assert "EQUIPMENT" in codes(plan, ctx)


def test_track_work_in_daylight(P):
    ctx, plan = P
    wed = plan.sessions[2]
    wed.location = "track"
    wed.start_time = "16:15"
    wed.blocks[1].run.append(RunSegment(label="reps", zone="T", duration_min=12))
    assert "DAYLIGHT" in codes(plan, ctx)


def test_outline_contradiction_needs_reason(P):
    ctx, plan = P
    long = next(s for s in plan.sessions if s.type == "run_long")
    long.blocks[1].run[0].distance_mi -= 2.5
    assert "OUTLINE_CONTRADICTION" in codes(plan, ctx)
    plan.deviations.append(
        Deviation(field="run_miles", planned="10", actual="7.6", reason="held mileage: three yellow days")
    )
    assert "OUTLINE_CONTRADICTION" not in codes(plan, ctx)


def test_tests_only_in_test_weeks(P):
    ctx, plan = P
    plan.sessions[0].tests = ["hinge_rm"]
    assert "TEST_WEEK" in codes(plan, ctx)


def test_pillar_minimum_effective_dose(P):
    ctx, plan = P
    for s in plan.sessions:
        s.blocks = [b for b in s.blocks if b.metcon is None]
    assert "PILLAR_MED" in codes(plan, ctx)


def test_red_flag_blocks_training(P):
    ctx, plan = P
    flag = HealthEvent(id="rf", kind="red_flag", start=dt.date(2026, 11, 29), flag="chest pain")
    assert "RED_FLAG" in codes(plan, ctx, health=[flag])
    cleared = flag.model_copy(update={"resolved_on": dt.date(2026, 11, 30), "cleared_by": "doctor"})
    assert "RED_FLAG" not in codes(plan, ctx, health=[cleared])


def test_illness_neck_check(P):
    ctx, plan = P
    below = [HealthEvent(id="i1", kind="illness", start=dt.date(2026, 12, 1), symptoms="below_neck")]
    assert "ILLNESS" in codes(plan, ctx, health=below)
    above = [
        HealthEvent(
            id="i2",
            kind="illness",
            start=dt.date(2026, 12, 2),
            symptoms="above_neck",
            resolved_on=dt.date(2026, 12, 3),
        )
    ]
    vctx = ctx.validation(plan)
    vctx.health = above
    wed = plan.sessions[2]  # easy run on an above-the-neck day is fine
    assert not [v for v in validate_session(wed, vctx, "training", plan) if v.code == "ILLNESS"]
    tue = plan.sessions[1].model_copy(deep=True)
    tue.date = dt.date(2026, 12, 2)
    assert [v for v in validate_session(tue, vctx, "training", plan) if v.code == "ILLNESS"]


def test_config_change_needs_approved_proposal(b1):
    from coach.config import load_config
    from coach.engine.validator import thresholds_fingerprint, validate_config_lock

    cfg = load_config()
    good = {"fingerprint": thresholds_fingerprint(cfg), "approved_by": "initial"}
    assert not validate_config_lock(cfg, good, set())
    assert (
        validate_config_lock(cfg, {"fingerprint": "deadbeef", "approved_by": "initial"}, set())[0].code
        == "CONFIG_UNAPPROVED"
    )
    assert validate_config_lock(cfg, {"fingerprint": good["fingerprint"], "approved_by": "p-1"}, set())
    assert validate_config_lock(cfg, None, set())


def test_joint_flag_swaps_use_regressions(P):
    """adjust-day swaps restricted exercises via the library's regressions instead of dropping work."""
    from coach.coaching.skills.adjust_day import _resubstitute
    from coach.coaching.skills.design import Picker

    ctx, plan = P
    tue = plan.sessions[1]
    blk(tue, "hypertrophy").items.append(Prescription(exercise_id="dips", sets=3, reps=8, rir=2))
    picker = Picker(
        ctx,
        "training",
        "gym",
        restricted={"shoulder_extension_loaded", "overhead", "kipping", "overhead_ballistic"},
    )
    changes = []
    _resubstitute(tue, picker, changes, "active joint flag (shoulders)")
    ids = [it.exercise_id for b in tue.blocks for it in b.items]
    assert "dips" not in ids and "push_up" in ids
    assert any("Dips -> Push-up" in c.what for c in changes)
    flag = JointFlag(
        region="shoulders",
        since=dt.date(2026, 11, 28),
        restricted_tags=sorted(picker.restricted),
        reason="test",
    )
    assert "JOINT_RESTRICTED" not in codes(plan, ctx, joint_flags=[flag])


def test_single_run_spikes_limited(P):
    """Audit 2026-11-23: each run against the longest run of the last 30 days (+10%, min step 0.25 mi)."""
    from coach.engine.sessions import session_miles
    from coach.engine.validator import spike_cap

    ctx, plan = P
    longest = max(session_miles(s, ctx.zones.threshold_pace_s_per_mi) for s in plan.sessions)
    assert "RUN_SPIKE" not in codes(plan, ctx, longest_run_30d=longest)
    assert "RUN_SPIKE" not in codes(
        plan, ctx, longest_run_30d=None
    )  # no recent base: the ramp-start rule governs
    assert "RUN_SPIKE" in codes(plan, ctx, longest_run_30d=longest / 1.3)
    th = ctx.cfg.profile.thresholds
    assert spike_cap(1.0, th) == 1.25 and spike_cap(4.0, th) == 4.4 and spike_cap(0, th) is None


def test_run_increase_uses_the_configured_pct(P, monkeypatch):
    from coach.engine import sessions as S

    ctx, plan = P
    long = next(s for s in plan.sessions if s.type == "run_long")
    long.blocks[1].run[0].distance_mi += 15  # well above the ramp floor, so the pct sets the cap
    vctx = ctx.validation(plan)
    miles = S.week_miles(plan, vctx.threshold_pace)
    trailing = [round(miles / 1.1, 2)] * 3  # this week is a 10% increase
    th = vctx.cfg.profile.thresholds
    monkeypatch.setattr(th, "weekly_run_increase_pct", 10.0)
    assert "RUN_INCREASE" not in codes(plan, ctx, trailing_miles=trailing)
    monkeypatch.setattr(th, "weekly_run_increase_pct", 2.0)
    assert "RUN_INCREASE" in codes(plan, ctx, trailing_miles=trailing)


def test_alternating_must_match_the_library(P):
    from coach.models import Prescription

    ctx, plan = P
    vctx = ctx.validation(plan)
    s = plan.sessions[0].model_copy(deep=True)

    def sides_codes(**kw):
        s.blocks[0].items = [Prescription(sets=1, reps=6, **kw)]
        return [v for v in validate_session(s, vctx, "training", plan) if v.code == "SIDES"]

    assert not sides_codes(exercise_id="reverse_lunge_db", per_side=True, alternating=True)
    assert not sides_codes(exercise_id="hip_90_90", per_side=True)
    assert sides_codes(exercise_id="side_plank", per_side=True, alternating=True)  # split-only
    assert sides_codes(exercise_id="hip_90_90", per_side=True, alternating=False)  # always alternates
    assert sides_codes(exercise_id="reverse_lunge_db", alternating=True)  # not per-side work


def test_new_thresholds_at_default_keep_the_lock(home):
    """Decision 105: the spike thresholds join the fingerprint only when set away from their defaults."""
    from coach.config import load_config
    from coach.engine.validator import thresholds_fingerprint

    cfg = load_config()
    fp = thresholds_fingerprint(cfg)
    cfg.profile.thresholds.run_spike_max_pct = 15.0
    assert thresholds_fingerprint(cfg) != fp


def test_longest_run_counts_a_run_done_today_once(b1, monkeypatch):
    """Review of #21: on a day with a logged run, the planned run that day doesn't count (no plan/log double count)."""
    import datetime as dt

    from coach.engine.sessions import session_miles
    from coach.models import SessionRecord

    ctx, plan, _ = b1
    plan = plan.model_copy(deep=True)
    run = next(s for s in plan.sessions if any(seg.modality == "run" for seg in s.run_segments()))
    seg = next(seg for seg in run.run_segments() if seg.modality == "run")
    seg.distance_mi, seg.duration_min = 50.0, None  # an obviously huge planned run today
    ctx.state.put("week_plans", plan)
    d = run.date
    ctx.today = d
    logged = SessionRecord(
        id="r",
        date=d,
        start=dt.datetime(d.year, d.month, d.day, 9),
        sport="run",
        title="run",
        duration_min=10,
        distance_mi=0.5,
        sources=["intervals"],
    )
    monkeypatch.setattr(ctx.state, "sessions", lambda a, b: [logged] if a <= d <= b else [])
    pace = ctx.zones.threshold_pace_s_per_mi
    later = [session_miles(s, pace) for s in plan.sessions if s.date > d]
    longest = ctx.longest_run_30d(plan.start + dt.timedelta(days=7))
    assert longest == round(max([0.5, *later]), 2) and longest < 50
