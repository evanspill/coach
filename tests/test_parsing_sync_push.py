import datetime as dt
import hashlib

import pytest

from coach.engine.parsing import classify_illness, detect_red_flags, parse_checkin_tag, parse_metcon_result
from coach.integrations.mock import MockWorld, mock_sources
from coach.models import SessionRecord
from coach.state import State
from coach.sync import merge_sessions, sync


def test_checkin_from_hevy_notes():
    assert parse_checkin_tag("back 2 shoulder 3") == {"joints": {"back": 2, "shoulders": 3}}
    t = parse_checkin_tag("Felt ok. back:1 knee 2 rpe 7.5 enjoy 4 bar speed 0.62")
    assert (
        t["joints"]["back"] == 1
        and t["joints"]["knees_achilles"] == 2
        and t["session_rpe"] == 7.5
        and t["enjoyment"] == 4
        and t["bar_speed_mps"] == 0.62
    )
    assert parse_checkin_tag("") == {}
    assert parse_checkin_tag("Shoulder hurt during pressing, about 3/10")["session_pain"] == {"press": 3.0}


def test_metcon_result_parsing():
    r = parse_metcon_result(
        "Finished the Hyrox sim: 4 rounds in 26:40, sled heavy on round 3, wall balls unbroken, RPE 8.5"
    )
    assert r["kind"] == "hyrox_sim" and r["time_s"] == 1600 and r["rounds"] == 4 and r["rpe"] == 8.5
    assert {"movement": "sled", "note": "heavy", "round": 3} in r["movement_notes"]
    r2 = parse_metcon_result("amrap 12: 6 rounds + 4 reps rpe 9")
    assert r2["rounds"] == 6 and r2["extra_reps"] == 4 and r2["score_type"] == "rounds_reps"
    assert parse_metcon_result("metcon felt rough")["missing"][0] == "score"


def test_red_flags_and_neck_check():
    assert detect_red_flags("had chest pain on the run") == ["chest pain"]
    assert "possible rhabdomyolysis" in detect_red_flags("dark urine after yesterday's session")
    assert detect_red_flags("legs sore after squats") == []
    assert classify_illness("fever and chest congestion") == "below_neck"
    assert classify_illness("runny nose and a sore throat") == "above_neck"


def test_sync_is_idempotent(home):
    st = State(home / "state")
    world = MockWorld.load()
    d = dt.date(2026, 11, 20)
    import os

    os.environ["COACH_TODAY"] = d.isoformat()
    sync(mock_sources(world), st, d)

    def digest():
        return hashlib.md5(
            b"".join(p.read_bytes() for p in sorted((home / "state" / "metrics").glob("*.jsonl")))
        ).hexdigest()

    a = digest()
    r = sync(mock_sources(world), st, d)
    assert r["changed_files"] == 0 and digest() == a
    assert st.daily_metrics()[-1].date == d


def test_merge_sessions_no_double_count():
    t = dt.datetime(2026, 12, 1, 9, 35)
    whoop = SessionRecord(
        id="w",
        date=t.date(),
        start=t + dt.timedelta(minutes=4),
        sport="run",
        title="Running",
        duration_min=40,
        avg_hr=150,
        strain=12,
        sources=["whoop"],
    )
    iv = SessionRecord(
        id="i",
        date=t.date(),
        start=t,
        sport="run",
        title="Run",
        duration_min=39,
        distance_mi=4.0,
        avg_hr=148,
        sources=["intervals"],
    )
    lift_w = SessionRecord(
        id="w2",
        date=t.date(),
        start=t + dt.timedelta(hours=3),
        sport="strength",
        title="Weightlifting",
        duration_min=60,
        avg_hr=115,
        sources=["whoop"],
    )
    out = merge_sessions([whoop, lift_w], [iv], 170)
    runs = [s for s in out if s.sport == "run"]
    assert len(runs) == 1 and runs[0].avg_hr == 150 and runs[0].distance_mi == 4.0 and runs[0].strain == 12
    assert len(out) == 2  # unmatched Whoop session kept on its own


def test_push_refuses_invalid_plans(b1):
    from coach.push import PushRefused, push_day, push_week

    ctx, plan, _ = b1
    good = plan.model_copy(deep=True)
    good.approval = "approved"
    res = push_week(good, ctx, None, dry_run=True)
    assert res["dry_run"] and res["hevy"] and res["intervals"]
    bad = good.model_copy(deep=True)
    bad.sessions[0].blocks[2].items[0].exercise_id = "conventional_deadlift"
    with pytest.raises(PushRefused):
        push_week(bad, ctx, None, dry_run=True)
    with pytest.raises(PushRefused):
        push_day(bad.sessions[0], ctx, None, bad, dry_run=True)


def test_hevy_and_intervals_payloads(b1):
    from coach.push import hevy_routine, intervals_event

    ctx, plan, _ = b1
    r = hevy_routine(plan.sessions[1], ctx)
    assert any(e["title"].startswith("METCON") and "Stimulus" in e["notes"] for e in r["exercises"])
    run = next(s for s in plan.sessions if s.type == "run_long")
    ev = intervals_event(run, ctx)
    assert (
        ev["category"] == "WORKOUT"
        and "% Pace" in ev["description"]
        and ev["external_id"].startswith("coach-")
    )
