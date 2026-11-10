"""Long-term goals (Boston qualifier), race targets and race-day pacing from fitness."""

import datetime as dt
import json

import pytest

from coach.coaching import proposals
from coach.coaching.skills import assess, compete
from coach.engine import goals as G
from coach.models.profile import Identity, LongTermGoal, Race

ID = Identity.model_validate(
    {
        "birth_year": 1993,
        "birth_month": 3,
        "sex": "male",
        "height_cm": 188,
        "timezone": "America/New_York",
        "home": {"name": "x", "lat": 0, "lon": 0},
    }
)
BOSTON = LongTermGoal(
    id="bq",
    name="Boston qualifier",
    kind="marathon_time",
    event="Boston Marathon",
    event_date=dt.date(2029, 4, 16),
    qualifying_closes_days_before=213,
    standards=[
        {"min_age": 18, "max_age": 34, "time": "2:55:00"},
        {"min_age": 35, "max_age": 39, "time": "3:00:00"},
    ],
    margin_s=300,
)
TODAY = dt.date(2026, 11, 22)
OCT_2027 = Race(id="m", name="Fall marathon", kind="marathon", date=dt.date(2027, 10, 17), confirmed=False)


def test_age_on_race_day():
    assert ID.age_on(dt.date(2027, 4, 19)) == 34
    assert ID.age_on(dt.date(2028, 4, 17)) == 35
    assert ID.age_on(dt.date(2029, 2, 1)) == 35  # before the March birthday
    assert ID.age_on(dt.date(2029, 4, 16)) == 36


def test_standard_by_age_group():
    assert G.standard_for(BOSTON, 34) == G.hms("2:55:00")
    assert G.standard_for(BOSTON, 36) == G.hms("3:00:00")
    assert G.standard_for(BOSTON, 41) is None
    assert G.standard_for(BOSTON.model_copy(update={"target_time": "3:10:00"}), 41) == G.hms("3:10:00")


def test_riegel_matches_the_benchmark_and_inverts():
    assert abs(G.marathon_from_threshold(420) - G.hms("3:16:00")) < 60  # 7:00/mi threshold ~ 3:16
    for t in ("2:55:00", "3:00:00", "3:30:00"):
        s = G.hms(t)
        assert abs(G.marathon_from_threshold(G.threshold_for_marathon(s)) - s) <= 1
    assert G.fmt_hms(10500) == "2:55:00"


def test_gain_rate_assumed_observed_and_capped():
    assert G.gain_rate([], 8, 12)[0] == 8
    pts = [(dt.date(2027, 1, 1), 480.0), (dt.date(2027, 5, 1), 470.0)]  # ~2.1% in 17 weeks
    rate, basis = G.gain_rate(pts, 8, 12)
    assert 5 < rate < 8 and "observed" in basis
    fast = [(dt.date(2027, 1, 1), 480.0), (dt.date(2027, 5, 1), 420.0)]
    assert G.gain_rate(fast, 8, 12) == (12, G.gain_rate(fast, 8, 12)[1])
    assert "capped" in G.gain_rate(fast, 8, 12)[1]
    close = [(dt.date(2027, 1, 1), 480.0), (dt.date(2027, 1, 20), 470.0)]
    assert G.gain_rate(close, 8, 12)[0] == 8  # too close together to trust


def test_projection():
    assert G.project(370, 377, 8, TODAY) == TODAY
    assert G.project(480, 377, 0, TODAY) is None
    when = G.project(480, 377, 8, TODAY)
    assert when is not None and 2.5 < (when - TODAY).days / 365.25 < 3.5
    assert G.threshold_on(480, 8, TODAY, TODAY + dt.timedelta(days=365)) == pytest.approx(441.6, abs=0.5)


def test_check_statuses():
    c = G.check(BOSTON, ID, [OCT_2027], [], None, TODAY)
    assert c.status == "unknown" and c.age_on_event == 36 and c.required_s == G.hms("2:55:00")
    assert c.required_threshold_s_per_mi == pytest.approx(376.9, abs=0.5)
    behind = G.check(BOSTON, ID, [OCT_2027], [], (480.0, "test"), TODAY)
    assert behind.status == "behind" and behind.deadline == OCT_2027.date
    near = G.check(BOSTON, ID, [OCT_2027], [], (395.0, "test"), TODAY)
    assert near.status == "on_track"
    done = G.check(BOSTON, ID, [OCT_2027], [], (370.0, "test"), TODAY)
    assert done.status == "achieved"
    old = BOSTON.model_copy(update={"event_date": dt.date(2035, 4, 16)})
    assert G.check(old, ID, [], [], (400.0, "t"), TODAY).status == "unknown"  # 42: no standard configured


def test_same_slot_next_year_is_patriots_day():
    assert G.same_slot_next_year(dt.date(2027, 4, 19)) == dt.date(2028, 4, 17)
    assert G.same_slot_next_year(dt.date(2029, 4, 16)) == dt.date(2030, 4, 15)


def test_config_patch_into_a_list(tmp_path):
    f = tmp_path / "athlete_context.json"
    f.write_text(json.dumps({"goals": {"long_term": [{"event_date": "2029-04-16"}]}}))
    proposals._apply_config_patch(
        tmp_path, {"file": f.name, "path": ["goals", "long_term", 0, "event_date"], "value": "2030-04-15"}
    )
    assert json.loads(f.read_text())["goals"]["long_term"][0]["event_date"] == "2030-04-15"


# --- coaching layer (sandbox) ---------------------------------------------------------------------------


def test_goal_progress_timeline_and_race_target(b1):
    ctx, _, _ = b1
    today = dt.date(2026, 11, 29)
    hist = assess.threshold_history(ctx)
    cur = assess.current_threshold(ctx, hist)
    checks = assess.goal_progress(ctx, today)
    assert len(checks) == len(ctx.cfg.profile.goals.long_term) == 1
    i, c = checks[0]
    rec = ctx.state.get("goal_progress", ctx.cfg.profile.goals.long_term[0].id)
    assert rec.latest == c
    if cur is not None:
        assert c.status in {"behind", "on_track", "achieved"}
        assert "Boston" in assess.describe_check("Boston qualifier", c)
    if c.status == "behind":
        assert c.rate_basis.startswith("assumed")
        assert (
            assess.goal_timeline_proposal(ctx, i, c, today) is None
        )  # one test: report, don't move the goal
        seen = c.model_copy(
            update={"rate_basis": "observed trend over 2 tests (+6.0%/yr)", "rate_pct_per_year": 6.0}
        )
        p = assess.goal_timeline_proposal(ctx, i, seen, today)
        assert p is not None and p.kind == "goal_timeline" and p.status == "pending"
        patch = p.payload["config_patch"]
        assert patch["path"] == ["goals", "long_term", 0, "event_date"]
        assert dt.date.fromisoformat(patch["value"]) > ctx.cfg.profile.goals.long_term[0].event_date

    msgs = assess.propose_race_targets(ctx, today)
    if cur is None:
        assert msgs == []
        return
    assert msgs and "race target proposed" in msgs[0]
    t = ctx.state.get("race_targets", "marathon-2027")
    assert t.status == "pending" and G.hms(t.target_time) >= t.predicted_s
    assert assess.propose_race_targets(ctx, today) == []  # same prediction: no new proposal
    pid = next(p.id for p in ctx.state.proposals("pending") if p.kind == "race_target")
    proposals.approve(ctx.state, pid, today, ctx.cfg)
    assert ctx.state.get("race_targets", "marathon-2027").status == "approved"
    pacing = compete.race_pacing(ctx, "marathon-2027")
    assert pacing["long_term"] and "Not used for pacing" in pacing["long_term"][0]


def test_config_change_approval_records_the_lock(b1):
    ctx, _, _ = b1
    day = dt.date(2026, 11, 29)
    p = proposals.create(ctx.state, "config_change", "assess", "goal added", "what", "why", day)
    actions = proposals.approve(ctx.state, p.id, day, ctx.cfg)
    assert "config lock recorded" in actions
    assert ctx.state.get("config_lock").approved_by == p.id


def test_cli_goals(home):
    import argparse

    from coach.cli import cmd_goals
    from coach.coaching.daily import bootstrap
    from coach.config import load_config
    from coach.store import Store

    bootstrap(Store(), load_config(), dt.date(2026, 11, 10))
    out = cmd_goals(argparse.Namespace(date="2026-11-10", check=True))
    assert out["goals"][0]["check"]["status"] in {"unknown", "behind", "on_track", "achieved"}
    again = cmd_goals(argparse.Namespace(date="2026-11-10", check=False))
    assert again["goals"][0]["check"] == out["goals"][0]["check"]


def test_penalty_until_a_marathon_result(b1):
    from coach.models.journal import EventResult

    ctx, _, _ = b1
    k, pen, basis = assess.marathon_model(ctx)
    assert pen == 600 and "no marathon result" in basis
    # the requirement gets harder by the penalty: 2:55 needs a 2:45 Riegel prediction
    assert G.threshold_for_marathon(10500, k, pen) == pytest.approx(
        G.threshold_for_marathon(9900, k), abs=0.01
    )
    assert G.marathon_from_threshold(420, k, pen) == G.marathon_from_threshold(420, k) + 600
    ctx.state.put(
        "event_results",
        EventResult(event_id="marathon-2027", date=dt.date(2027, 10, 17), result_time_s=12000),
    )
    assert assess.marathon_model(ctx)[1] == 0
