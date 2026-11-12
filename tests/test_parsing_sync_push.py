import datetime as dt
import hashlib

import pytest

from coach.engine.parsing import classify_illness, detect_red_flags, parse_checkin_tag, parse_metcon_result
from coach.integrations.mock import MockWorld, mock_sources
from coach.integrations.sync import merge_sessions, sync
from coach.models import SessionRecord
from coach.store import Store


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
    st = Store(home / "athlete" / "data")
    world = MockWorld.load()
    d = dt.date(2026, 11, 20)
    import os

    os.environ["COACH_TODAY"] = d.isoformat()
    sync(mock_sources(world), st, d)

    def digest():
        return hashlib.md5(
            b"".join(p.read_bytes() for p in sorted((home / "athlete" / "data" / "metrics").glob("*.jsonl")))
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
    from coach.integrations.push import PushRefused, push_day, push_week

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
    from coach.integrations.push import hevy_routine, intervals_event

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


def test_every_cli_command_is_registered():
    from coach.cli import COMMANDS, build_parser

    sub = next(a for a in build_parser()._actions if a.dest == "cmd")
    assert set(COMMANDS) == set(sub.choices)


def test_live_requests_send_a_user_agent(monkeypatch):
    """Intervals.icu's Cloudflare front rejects urllib's default agent (error 1010), so every call names one."""
    from coach.integrations import live

    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"[]"

    def fake_urlopen(req, timeout):
        seen.update({k.lower(): v for k, v in req.header_items()})
        return Resp()

    monkeypatch.setattr(live.urllib.request, "urlopen", fake_urlopen)
    assert (
        live._request("GET", "https://intervals.icu/api/v1/athlete/0/gear", {"Authorization": "Basic x"})
        == []
    )
    assert seen["user-agent"] == live.USER_AGENT and not seen["user-agent"].startswith("Python-urllib")
    assert seen["authorization"] == "Basic x"


WHOOP_FIELDS = {"recovery_score", "hrv_rmssd_ms", "rhr_bpm", "sleep_hours", "sleep_performance", "day_strain"}


def test_whoop_data_is_never_committed(home):
    """Whoop numbers live only in the git-ignored cache; readers still see them merged in (DECISIONS 73)."""
    import json
    import os

    data = home / "athlete" / "data"
    st = Store(data)
    d = dt.date(2026, 11, 20)
    os.environ["COACH_TODAY"] = d.isoformat()
    sync(mock_sources(MockWorld.load()), st, d)

    committed = [
        json.loads(line) for p in (data / "metrics").glob("*.jsonl") for line in p.read_text().splitlines()
    ]
    assert committed
    for r in committed:
        assert not WHOOP_FIELDS & set(r["data"]), r
        assert "whoop" not in r["data"].get("sources", []), r
        if r["kind"] == "session" and r["data"].get("avg_hr"):
            assert r["data"]["sport"] in {"run", "row", "bike"}  # Garmin HR via Intervals, not Whoop
    assert (data / ".cache" / "whoop" / "metrics").is_dir()
    merged = st.daily_metrics(d - dt.timedelta(days=60), d)
    assert sum(m.recovery_score is not None for m in merged) >= 55
    assert any("whoop" in s.sources for s in st.sessions(d - dt.timedelta(days=30), d))
    assert any(m.weight_kg for m in merged)  # weigh-ins now come from Intervals wellness


def test_fresh_container_refetches_the_whoop_window(home):
    """Committed state survives, the cache doesn't: the next sync refetches 75 days so baselines are whole."""
    import os
    import shutil

    from coach.integrations.sync import WHOOP_WINDOW_DAYS

    data = home / "athlete" / "data"
    st = Store(data)
    d = dt.date(2026, 11, 20)
    os.environ["COACH_TODAY"] = d.isoformat()
    sync(mock_sources(MockWorld.load()), st, d)
    shutil.rmtree(data / ".cache")  # new container: git checkout without the cache
    assert not any(m.recovery_score for m in st.daily_metrics())
    nxt = d + dt.timedelta(days=1)
    os.environ["COACH_TODAY"] = nxt.isoformat()
    sync(mock_sources(MockWorld.load()), st, nxt)
    since, through = st.whoop_cache_coverage()
    assert since == nxt - dt.timedelta(days=WHOOP_WINDOW_DAYS) and through == nxt
    assert sum(m.recovery_score is not None for m in st.daily_metrics(since, nxt)) >= 60


def test_day_records_are_stored_without_whoop_numbers(home):
    from coach.models import DayRecord
    from coach.models.records import HrvTrend, Readiness

    st = Store(home / "athlete" / "data")
    d = dt.date(2026, 11, 20)
    r = Readiness(
        date=d,
        state="green",
        reasons=["recovery >= 67"],
        recovery_score=81,
        rhr_delta=-1.2,
        hrv=HrvTrend(mean7_ln=4.1),
    )
    rec = DayRecord(date=d, status="complete", generated_by="fallback", readiness=r)
    st.put("day_records", rec)
    assert rec.readiness.recovery_score == 81  # the caller's copy (used for today's call) is untouched
    back = st.day_record(d)
    assert back.readiness.state == "green" and back.readiness.reasons == ["recovery >= 67"]
    assert back.readiness.recovery_score is None and back.readiness.rhr_delta is None
    assert back.readiness.hrv.mean7_ln is None


def _offline_whoop_sources():
    import dataclasses

    from coach.integrations.base import WhoopSource

    class OfflineWhoop(WhoopSource):
        def daily(self, start, end):
            raise RuntimeError("broker down")

        def workouts(self, start, end):
            raise RuntimeError("broker down")

    return dataclasses.replace(mock_sources(MockWorld.load()), whoop=OfflineWhoop())


@pytest.mark.parametrize("setting", ["none", "intervals"])
def test_intervals_whoop_backup_fills_missing_days_without_committing(home, setting):
    """Direct Whoop down: with whoop_backup=intervals, Intervals.icu wellness HRV/RHR fill the cache (never git)."""
    import json
    import os

    from coach.config import load_config

    data = home / "athlete" / "data"
    st = Store(data)
    d = dt.date(2026, 11, 20)
    os.environ["COACH_TODAY"] = d.isoformat()
    cfg = load_config()
    cfg.settings.whoop_backup = setting
    r = sync(_offline_whoop_sources(), st, d, cfg)
    ms = st.daily_metrics(d - dt.timedelta(days=60), d)
    filled = [m for m in ms if m.hrv_rmssd_ms is not None]
    if setting == "none":
        assert not filled and "whoop_backup_days" not in r["counts"]
    else:
        assert len(filled) >= 55 and all("intervals_whoop" in m.sources for m in filled)
        assert r["counts"]["whoop_backup_days"] >= 55
    for p in (data / "metrics").glob("*.jsonl"):
        for line in p.read_text().splitlines():
            assert not WHOOP_FIELDS & set(json.loads(line)["data"])


def test_direct_whoop_wins_over_the_backup(home):
    import os

    from coach.config import load_config

    st = Store(home / "athlete" / "data")
    d = dt.date(2026, 11, 20)
    os.environ["COACH_TODAY"] = d.isoformat()
    cfg = load_config()
    cfg.settings.whoop_backup = "intervals"
    r = sync(mock_sources(MockWorld.load()), st, d, cfg)
    assert r["counts"].get("whoop_backup_days", 0) == 0  # direct covered every day that had a score
    assert all("intervals_whoop" not in m.sources for m in st.daily_metrics() if m.recovery_score is not None)


def test_jitter_waits_only_for_live_scheduled_runs(monkeypatch):
    import argparse

    from coach import cli

    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
    monkeypatch.setenv("COACH_MOCK", "0")
    cli._jitter(argparse.Namespace(jitter=90))
    assert len(slept) == 1 and 0 <= slept[0] <= 90
    cli._jitter(argparse.Namespace(jitter=0))
    monkeypatch.setenv("COACH_MOCK", "1")
    cli._jitter(argparse.Namespace(jitter=90))
    assert len(slept) == 1


@pytest.mark.parametrize(
    "name,sport",
    [
        ("weightlifting_msk", "strength"),  # live Whoop v2 name
        ("Weightlifting", "strength"),
        ("functional_fitness", "metcon"),
        ("functional fitness", "metcon"),
        ("running", "run"),
        ("golf", "other"),
        ("activity", "other"),
        (None, "other"),
    ],
)
def test_whoop_sport_names(name, sport):
    from coach.integrations.normalize import whoop_sport

    assert whoop_sport(name) == sport


def test_whoop_workouts_skip_unscored_recovery_activities():
    from coach.integrations.normalize import whoop_workouts

    base = {"start": "2026-11-07T14:00:00.000Z", "end": "2026-11-07T15:00:00.000Z", "score_state": "SCORED"}
    raw = [
        {**base, "id": "a", "sport_name": "air-compression-normatec", "score": None},  # live shape
        {
            **base,
            "id": "b",
            "sport_name": "weightlifting_msk",
            "score": {
                "strain": 9.1,
                "average_heart_rate": 120,
                "max_heart_rate": 160,
                "kilojoule": 1200.0,
                "zone_durations": None,
            },
        },
    ]
    out = whoop_workouts(raw)
    assert [s.sport for s in out] == ["strength"] and out[0].avg_hr == 120


def test_carried_forward_weight_is_not_a_weigh_in():
    """Intervals.icu repeats the last weight on days without a weigh-in; only new readings count."""
    from coach.integrations.normalize import intervals_wellness

    raw = [
        {"id": "2026-11-10", "weight": 96.512, "bodyFat": 18.1},
        {"id": "2026-11-11", "weight": 96.512},  # carried forward
        {"id": "2026-11-12", "weight": 96.512},  # carried forward
        {"id": "2026-11-13", "weight": 96.204, "bodyFat": 17.9},
        {"id": "2026-11-14", "weight": 96.204, "bodyFat": 18.0},  # same value but a real reading (body fat)
    ]
    ms, _ = intervals_wellness(raw)
    assert [m.weight_kg for m in ms] == [96.512, None, None, 96.204, 96.204]
