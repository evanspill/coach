import datetime as dt

import pytest

from coach.config import load_config
from coach.engine import movement as mv
from coach.engine import testing as T
from coach.engine.validator import validate_movement_change

CFG = load_config()


def test_schedule_separates_strength_run_engine():
    wk = dt.date(2027, 3, 8)
    s = T.schedule(
        wk, ["hinge_rm", "db_press_5rm", "run_tt_30", "row_2k", "broad_jump"], CFG.tests, "transition"
    )
    assert len({s["hinge_rm"], s["run_tt_30"], s["row_2k"]}) == 3
    assert s["run_tt_30"] >= wk + dt.timedelta(days=3)  # late in the week


def test_red_day_reschedule_within_window():
    wk = dt.date(2027, 3, 8)
    s = T.schedule(wk, ["hinge_rm", "run_tt_30", "row_2k"], CFG.tests, "transition")
    red = s["hinge_rm"]
    new = T.reschedule_for_red("hinge_rm", s, CFG.tests, red, red)
    assert new is not None and abs((new - red).days) <= 2 and new != s["run_tt_30"] and new != s["row_2k"]
    # run TT can't land next to the engine test
    new_tt = T.reschedule_for_red("run_tt_30", s, CFG.tests, s["run_tt_30"], s["run_tt_30"])
    assert new_tt is None or abs((new_tt - s["row_2k"]).days) > 1


def test_scoring_e1rm_and_variant_comparability():
    hi = T.score(
        "hinge_rm",
        {"weight_kg": 160, "reps": 5, "rir": 1, "variant": "trap_bar_deadlift_high"},
        CFG.tests,
        dt.date(2026, 11, 16),
    )
    lo = T.score(
        "hinge_rm",
        {"weight_kg": 152.5, "reps": 5, "rir": 1, "variant": "trap_bar_deadlift_low"},
        CFG.tests,
        dt.date(2027, 3, 12),
    )
    assert hi.value == round(160 * 1.2, 2)
    assert lo.variant == "trap_bar_deadlift_low" and lo.comparable_value == round(152.5 * 1.2 * 1.05, 2)
    assert T.change_pct(hi, lo) == round(
        (lo.comparable_value - hi.comparable_value) / hi.comparable_value * 100, 2
    )


def test_scoring_tt_gives_lthr_and_threshold_with_heat_adjustment():
    r = T.score(
        "run_tt_30",
        {"last20_avg_hr": 169.4, "last20_pace_s_per_mi": 462, "conditions": {"temp_f": 80}},
        CFG.tests,
        dt.date(2026, 11, 19),
    )
    assert r.details["lthr"] == 169 and r.details["threshold_pace_s_per_mi"] == 462
    assert r.comparable_value < 462  # hot day: normalised faster


def test_scoring_row_and_jump():
    r = T.score("row_2k", {"time_s": 420, "bodyweight_kg": 95}, CFG.tests, dt.date(2026, 11, 21))
    assert 280 <= r.details["watts"] <= 310
    assert T.score("broad_jump", {"attempts": [230, 236, 233]}, CFG.tests, dt.date(2026, 11, 16)).value == 236


def test_movement_advance_one_rung_after_criteria():
    mr = mv.initial_state(CFG.progressions, dt.date(2026, 11, 16))
    before = mr.model_copy(deep=True)
    d = dt.date(2026, 11, 23)
    mv.record_exposure(mr, "squat", d, 1, False, CFG.progressions)
    mv.record_exposure(mr, "squat", d + dt.timedelta(days=7), 2, False, CFG.progressions)
    assert mr.rung("squat") == 0
    mv.record_exposure(mr, "squat", d + dt.timedelta(days=14), 0, False, CFG.progressions)
    assert mr.rung("squat") == 1
    assert not validate_movement_change(before, mr, CFG)


def test_movement_min_days_at_rung():
    mr = mv.initial_state(CFG.progressions, dt.date(2026, 11, 16))
    d = dt.date(2026, 11, 23)
    for k in range(3):
        mv.record_exposure(mr, "press", d + dt.timedelta(days=7 * k), 0, False, CFG.progressions)
    assert mr.rung("press") == 1
    for k in range(3):  # three more clean exposures within 10 days: too soon
        mv.record_exposure(mr, "press", d + dt.timedelta(days=15 + 3 * k), 0, False, CFG.progressions)
    assert mr.rung("press") == 1


def test_movement_regress_and_invalid_jumps():
    mr = mv.initial_state(CFG.progressions, dt.date(2026, 11, 16), {"hinge": 2})
    before = mr.model_copy(deep=True)
    mv.record_exposure(mr, "hinge", dt.date(2026, 12, 1), 3.0, False, CFG.progressions)
    assert mr.rung("hinge") == 1
    assert not validate_movement_change(before, mr, CFG)
    bad = before.model_copy(deep=True)
    bad.families["hinge"].rung = 0
    assert any(
        "more than one rung" in v.message
        for v in validate_movement_change(mr.model_copy(deep=True) if False else _at(2), bad, CFG)
    )
    unearned = before.model_copy(deep=True)
    unearned.families["hinge"].rung = 3
    assert any("without criteria" in v.message for v in validate_movement_change(before, unearned, CFG))


def _at(rung):
    mr = mv.initial_state(CFG.progressions, dt.date(2026, 11, 16), {"hinge": rung})
    return mr


def test_region_flag_drops_families_once():
    mr = mv.initial_state(CFG.progressions, dt.date(2026, 11, 16), {"press": 2, "overhead": 1, "kipping": 0})
    ev = mv.apply_region_flag(mr, "shoulders", dt.date(2027, 1, 20), CFG.progressions)
    assert mr.rung("press") == 1 and mr.rung("overhead") == 0 and len(ev) == 2
    assert not mv.apply_region_flag(mr, "shoulders", dt.date(2027, 1, 21), CFG.progressions)


def test_exercise_gate_and_variant_test_rung():
    mr = mv.initial_state(CFG.progressions, dt.date(2026, 11, 16))
    assert not mv.allowed(CFG.exercise("conventional_deadlift"), mr)[0]
    assert mv.allowed(CFG.exercise("trap_bar_deadlift_high"), mr)[0]
    assert not mv.allowed(
        CFG.exercise("muscle_snatch"),
        mv.initial_state(CFG.progressions, dt.date(2026, 11, 16), {"olympic": 1}),
    )[0]
    assert mv.exercise_for_rung("hinge", 1, CFG.progressions) == "trap_bar_deadlift_low"


def test_top_rungs_need_three_weeks_and_a_form_check():
    mr = mv.initial_state(CFG.progressions, dt.date(2026, 11, 16), {"hinge": 2})
    fs = mr.families["hinge"]
    fs.history.append(mv.RungEvent(date=dt.date(2026, 12, 1), from_rung=1, to_rung=2, reason="advance"))
    d = dt.date(2026, 12, 8)
    for k in range(3):  # 3 clean exposures, but only 7-15 days at rung 2
        mv.record_exposure(mr, "hinge", d + dt.timedelta(days=4 * k), 0, False, CFG.progressions)
    assert mr.rung("hinge") == 2 and fs.pending_form_check is None
    assert mv.advance_blocker(fs, dt.date(2026, 12, 16), CFG.progressions) == "time"
    mv.record_exposure(mr, "hinge", dt.date(2026, 12, 23), 0, False, CFG.progressions)  # 22 days: time ok
    assert mr.rung("hinge") == 2 and fs.pending_form_check == 3  # held for the form check
    before = mr.model_copy(deep=True)
    mv.clear_form_check(mr, "hinge", dt.date(2026, 12, 27), "physio")
    mv.record_exposure(mr, "hinge", dt.date(2026, 12, 28), 0, False, CFG.progressions)
    assert mr.rung("hinge") == 3
    assert not validate_movement_change(before, mr, CFG)


def test_validator_rejects_top_rung_without_form_check():
    before = mv.initial_state(CFG.progressions, dt.date(2026, 11, 16), {"squat": 1})
    after = before.model_copy(deep=True)
    fs = after.families["squat"]
    fs.history.append(
        mv.RungEvent(date=dt.date(2027, 1, 30), from_rung=1, to_rung=2, reason="advance", evidence=3)
    )
    fs.rung = 2
    assert any("form check" in v.message for v in validate_movement_change(before, after, CFG))


def test_max_hold_scoring_and_manual_results():
    from coach.config import load_config
    from coach.engine import testing as T

    bat = load_config().tests
    side = T.score("side_bridge", {"holds_s": [70, 56]}, bat, dt.date(2026, 11, 18))
    assert side.value == 56 and side.details["asymmetry_pct"] == 20.0  # weaker side counts
    sor = T.score("sorensen_hold", {"holds_s": [95]}, bat, dt.date(2026, 11, 18))
    assert sor.value == 95
    raw = T.manual_raw(["sorensen_hold=95", "side_bridge=70,56", "pullups_max=8"], bat)
    assert raw == {
        "sorensen_hold": {"holds_s": [95.0]},
        "side_bridge": {"holds_s": [70.0, 56.0]},
        "pullups_max": {"reps": 8.0},
    }
    for bad in (["nope=3"], ["hinge_rm=100"], ["sorensen_hold"]):
        with pytest.raises(ValueError):
            T.manual_raw(bad, bat)
