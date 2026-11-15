import datetime as dt

import pytest

from coach.sim.scenarios import SCENARIOS, run_one


@pytest.mark.parametrize("skill,name,fn", SCENARIOS, ids=[f"{s}:{n}" for s, n, _ in SCENARIOS])
def test_skill_scenario(skill, name, fn):
    c = run_one(fn)
    assert not c.failures, c.failures


def test_short_simulation_runs_clean(tmp_path):
    from coach.sim.run import simulate

    lines: list[str] = []
    res = simulate(
        days=10, start=dt.date(2026, 11, 16), out_dir=tmp_path / "sim", echo=lines.append, scenarios=False
    )
    assert len(res.days) == 10
    assert not [e for e in res.events if "fails validation" in e or "refused" in e]
    text = "\n".join(lines)
    assert "assess: scored" in text and "plan-block: outline" in text
    assert (tmp_path / "sim" / "athlete" / "data" / "blocks" / "2026-27-B1" / "outline.json").exists()
    assert (tmp_path / "sim" / "athlete" / "data" / "zones.json").exists()


# ---- regression tests for the simulation harness itself ----


def _fake_daily(main_log, catchup_log=(), wait=False):
    """A stand-in run_daily: the 08:25 run returns `main_log` (waiting for recovery if `wait`), the catch-up
    returns `catchup_log`."""
    from coach.coaching.daily import DayResult
    from coach.models import DayRecord

    def run_daily(sources, state, day, phase="main", **_k):
        if phase == "catchup":
            return DayResult(DayRecord(date=day, status="complete"), "GREEN", list(catchup_log))
        status = "waiting_for_recovery" if wait else "complete"
        return DayResult(DayRecord(date=day, status=status), "PENDING: recovery not in", list(main_log))

    return run_daily


def test_simulation_fails_on_day_level_problems(tmp_path, monkeypatch):
    """A plan that fails validation or a refused push must fail `coach simulate`, not just be logged."""
    from coach.sim import run as sim_run

    monkeypatch.setattr(
        sim_run, "run_daily", _fake_daily(["plan 2027-W06 fails validation after fallback: X"])
    )
    monkeypatch.setattr(sim_run.SimAthlete, "do_day", lambda *_a: [])
    res = sim_run.simulate(days=1, out_dir=tmp_path / "sim", echo=lambda *_: None, scenarios=False)
    assert not res.ok
    assert res.problems == ["2026-11-16 plan 2027-W06 fails validation after fallback: X"]
    assert "## Problems" in (tmp_path / "sim" / "athlete" / "data" / "simulation_report.md").read_text()
    assert not sim_run.SimResult(home=tmp_path, events=["2026-11-16 push refused: Y"]).ok
    assert sim_run.SimResult(home=tmp_path, events=["2026-11-16 review: week adherence 90%"]).ok


def test_catchup_keeps_the_main_runs_log(tmp_path, monkeypatch):
    """On a late-recovery day, what the 08:25 run logged (e.g. a plan failing validation) must survive the
    09:05 catch-up instead of being replaced by the catch-up's log."""
    from coach.sim import run as sim_run

    monkeypatch.setattr(
        sim_run,
        "run_daily",
        _fake_daily(["plan 2026-W48 fails validation after fallback: X"], ["catch-up line"], wait=True),
    )
    monkeypatch.setattr(sim_run.SimAthlete, "do_day", lambda *_a: [])
    lines: list[str] = []
    res = sim_run.simulate(days=1, out_dir=tmp_path / "sim", echo=lines.append, scenarios=False)
    assert res.events == [
        "2026-11-16 plan 2026-W48 fails validation after fallback: X",
        "2026-11-16 catch-up line",
    ]
    assert not res.ok
    assert any("[09:05 catch-up] complete" in line for line in lines)


def test_sandbox_refuses_to_wipe_a_real_athlete_dir(tmp_path):
    from coach.sim.run import sandbox

    real = tmp_path / "athlete" / "data"
    real.mkdir(parents=True)
    (real / "notes.md").write_text("keep me")
    with pytest.raises(ValueError, match="not a simulation sandbox"), sandbox(tmp_path):
        pass
    assert (real / "notes.md").read_text() == "keep me"
    with sandbox(tmp_path / "sim"):  # a sandbox's own home can be reused
        pass
    with sandbox(tmp_path / "sim") as h:
        assert (h / "athlete" / "config").is_dir()


def test_sandbox_isolates_today_and_cleans_up(monkeypatch):
    import os

    from coach.sim.run import sandbox

    monkeypatch.setenv("COACH_TODAY", "2027-01-01")
    with sandbox(keep=False) as h:
        assert "COACH_TODAY" not in os.environ
        assert h.exists()
    assert not h.exists()
    assert os.environ["COACH_TODAY"] == "2027-01-01"


def test_sim_run_is_logged_on_the_shoe_credited_with_the_miles(home):
    from coach.integrations.mock import MockWorld
    from coach.models import DayRecord
    from coach.sim.athlete import SimAthlete
    from coach.sim.scenarios import world_at

    ctx = world_at(dt.date(2026, 11, 29))
    from coach.coaching.skills.plan_week import plan_week

    plan = plan_week(ctx, dt.date(2026, 11, 30))
    easy = next(s for s in plan.sessions if s.type == "run_easy")
    for s, shoe in (
        (easy.model_copy(update={"type": "run_quality"}), "g-2"),  # no shoe picked: firm for quality work
        (easy.model_copy(update={"shoe": "Firm trainer"}), "g-2"),  # the coach's pick wins
        (easy, "g-1"),
    ):
        world = MockWorld.load()
        n = len(world.intervals["activities"])
        SimAthlete(world, ctx.cfg).do_day(s.date, DayRecord(date=s.date, status="complete", session=s))
        runs = [a for a in world.intervals["activities"][n:] if a["type"] == "Run"]
        assert runs and {a["gear"]["id"] for a in runs} == {shoe} == set(world.extra_gear_miles)


# ---- scenarios must be able to fail: break the behaviour, expect a failure ----


def test_sick_scenario_fails_when_sick_days_are_dropped(monkeypatch):
    from coach.coaching.skills import replan
    from coach.sim import scenarios as S

    real = replan.illness

    def drops_sick_days(ctx, plan, start, end, symptoms):
        new = real(ctx, plan, start, end, symptoms)
        new.sessions = [s for s in new.sessions if not (start <= s.date <= end)]
        return new

    monkeypatch.setattr(replan, "illness", drops_sick_days)
    assert any("no training while sick" in f for f in run_one(S.sc_replan_sick).failures)


def test_travel_scenario_fails_when_travel_days_are_dropped(monkeypatch):
    from coach.coaching.skills import replan
    from coach.sim import scenarios as S

    real = replan.travel

    def drops_travel_days(ctx, plan, dates):
        new = real(ctx, plan, dates)
        new.sessions = [s for s in new.sessions if s.date not in dates]
        return new

    monkeypatch.setattr(replan, "travel", drops_travel_days)
    assert any("no gym sessions on travel days" in f for f in run_one(S.sc_replan_travel).failures)


def test_pillar_scenario_fails_when_doses_are_missing(monkeypatch):
    from coach.sim import scenarios as S

    monkeypatch.setattr(S, "pillar_doses", lambda *_a: {})
    assert any("all four pillars" in f for f in run_one(S.sc_plan_week_normal).failures)


def test_deload_scenario_fails_when_no_hard_sets_are_counted(monkeypatch):
    from coach.sim import scenarios as S

    monkeypatch.setattr(S, "hard_sets", lambda *_a: {})
    assert any("deload volume cut" in f for f in run_one(S.sc_plan_week_deload).failures)


def test_adherence_scenario_fails_when_adherence_ignores_completed_sessions(monkeypatch):
    from coach.coaching.skills import review
    from coach.sim import scenarios as S

    def nothing_done(ctx, plan):
        planned = [s for s in plan.sessions if s.type not in {"rest", "recovery"}]
        return 0, len(planned), [s.title for s in planned]

    monkeypatch.setattr(review, "adherence", nothing_done)
    assert any("adherence dip detected" in f for f in run_one(S.sc_review_adherence).failures)
