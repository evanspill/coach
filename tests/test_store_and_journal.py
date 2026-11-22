import datetime as dt

from coach.models.journal import Availability, HealthEvent, JournalEntry, LabResult, Measurement, Note
from coach.models.metrics import Checkin
from coach.store import Store
from coach.store.collections import COLLECTIONS


def test_every_collection_has_a_layout_and_roundtrips(home):
    st = Store(home / "athlete" / "data")
    d = dt.date(2026, 12, 1)
    samples = {
        "journal": JournalEntry(id="2026-12-01-win-1", date=d, kind="win", text="PR on the 2k row"),
        "health_events": HealthEvent(
            id="2026-12-01-illness-1", kind="illness", start=d, symptoms="above_neck"
        ),
        "availability": Availability(
            id="2026-12-01-travel-1", start=d, end=d + dt.timedelta(days=3), kind="travel"
        ),
        "lab_results": LabResult(
            id="2026-12-01-ferritin-1", date=d, marker="ferritin", value=80, unit="ng/mL"
        ),
        "measurements": Measurement(id="2026-12-01-waist-1", date=d, kind="waist_cm", value=86),
        "notes": Note(id="2026-12-01-note-1", date=d, category="injury", text="dips aggravate R shoulder"),
        "checkins": Checkin(date=d, joints={"back": 2}, stress=3),
    }
    for name, obj in samples.items():
        st.put(name, obj)
        key = st.key_of(name, obj)
        assert st.keys(name) == [key]
        assert st.get(name, key) == obj
        assert st.get_ref(st.ref(name, key)) == obj
    assert "dips aggravate R shoulder" in st.notes()  # rendered view
    assert st.health_events(d) and not st.health_events(d - dt.timedelta(days=1))
    for c in COLLECTIONS.values():
        assert c.kind in {"singleton", "doc", "report", "series"}
        assert c.kind in {"report", "series"} or c.name in {"gear", "push_ids"} or c.model is not None


def test_test_sets_composite_key(home):
    from coach.models import TestSet

    st = Store(home / "athlete" / "data")
    st.put("test_sets", TestSet(block_id="2026-27-B1", phase="end"))
    assert st.keys("test_sets") == ["2026-27-B1:end"]
    assert st.tests("2026-27-B1", "end").phase == "end"


def test_availability_reshapes_the_planned_week(b1):
    from coach.coaching.skills import replan

    ctx, plan, _ = b1
    ctx.state.put(
        "availability",
        Availability(id="t1", start=dt.date(2026, 12, 3), end=dt.date(2026, 12, 4), kind="travel"),
    )
    new, notes = replan.apply_availability(ctx, plan.model_copy(deep=True))
    assert notes and all(
        s.location in {"travel", "home", "outdoor"} or s.type == "rest"
        for s in new.sessions
        if s.date in {dt.date(2026, 12, 3), dt.date(2026, 12, 4)}
    )
    ctx.state.delete("availability", "t1")


def test_log_captures_journal_and_hooper_wellness(b1):
    from coach.coaching.skills import log as log_skill

    ctx, _plan, _ = b1
    day = dt.date(2026, 11, 29)
    r = log_skill.handle(ctx, "stress 4 mood 2 fatigue 4, honestly a rough week at work", day)
    ci = ctx.state.get("checkins", day.isoformat())
    assert (ci.stress, ci.mood, ci.fatigue) == (4, 2, 4)
    assert any(ref.startswith("journal/") for ref in r["records"])
    assert ctx.state.query("journal", day, day)[0].kind == "struggle"


def test_session_load_foster(b1):
    from coach.coaching.skills.review import session_load

    ctx, _plan, _ = b1
    d = dt.date(2026, 11, 2)
    for i, rpe in enumerate([6, 7, 0, 8, 5, 0, 7]):
        if rpe:
            ctx.state.put(
                "checkins", Checkin(date=d + dt.timedelta(days=i), session_rpe=rpe, session_minutes=60)
            )
    out = session_load(ctx, d, d + dt.timedelta(days=6))
    assert out["load"] == (6 + 7 + 8 + 5 + 7) * 60 and out["monotony"] and out["strain"]


def test_data_model_doc_lists_every_collection():
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[1] / "docs" / "DATA_MODEL.md").read_text()
    missing = [name for name in COLLECTIONS if f"`{name}`" not in doc]
    assert not missing, f"docs/DATA_MODEL.md is missing collections: {missing}"


def test_new_id_skips_ids_already_in_use(home):
    st = Store(home / "athlete" / "data")
    d = dt.date(2026, 12, 1)
    # a hand-written id leaves a gap: counting keys would hand out -2 again and overwrite it
    st.put("notes", Note(id="2026-12-01-note-2", date=d, text="kept"))
    assert st.new_id("notes", d, "note") == "2026-12-01-note-3"
    st.add_note(d, "new")
    assert st.get("notes", "2026-12-01-note-2").text == "kept"
    st.delete("notes", "2026-12-01-note-2")
    assert "kept" not in st.notes()  # rendered view follows a delete


def test_keys_cannot_escape_the_collection(home):
    import pytest

    st = Store(home / "athlete" / "data")
    for bad in ("../../x", "a/b", ".hidden", ""):
        with pytest.raises(ValueError):
            st.get("journal", bad)
    with pytest.raises(ValueError):
        st.get("test_sets", "B1")  # composite key needs block:phase


def test_report_collections_go_through_put_and_get_as_markdown(home):
    st = Store(home / "athlete" / "data")
    st.put_ref("event_plans/marathon", "# Race plan\n\nGo out easy.\n")
    assert st.report("event_plans", "marathon").startswith("# Race plan")
    assert st.get_ref("event_plans/marathon").startswith("# Race plan")
    assert st.get("event_plans", "missing") is None


def test_record_invariants():
    import pytest
    from pydantic import ValidationError

    d = dt.date(2026, 12, 1)
    with pytest.raises(ValidationError):  # red flags clear only with a clearance
        HealthEvent(id="x", kind="red_flag", start=d, resolved_on=d + dt.timedelta(days=2))
    HealthEvent(id="x", kind="red_flag", start=d, resolved_on=d, cleared_by="doctor")
    with pytest.raises(ValidationError):  # only a doctor clears a red flag
        HealthEvent(id="x", kind="red_flag", start=d, resolved_on=d, cleared_by="athlete")
    with pytest.raises(ValidationError):
        Availability(id="x", start=d, end=d - dt.timedelta(days=1), kind="travel")
    with pytest.raises(ValidationError):
        Checkin(date=d, session_pain={"hinge": 12})


def test_health_resolve_needs_a_doctor_for_a_red_flag(home):
    import argparse

    from coach.cli import cmd_health
    from coach.models.journal import HealthEvent
    from coach.store import Store

    d = dt.date(2026, 12, 1)
    st = Store()
    st.put("health_events", HealthEvent(id="2026-12-01-red-flag-1", kind="red_flag", start=d))

    def resolve(by, day):
        return cmd_health(argparse.Namespace(id="2026-12-01-red-flag-1", by=by, date=day))

    assert "error" in resolve("athlete", "2026-12-03")
    assert st.get("health_events", "2026-12-01-red-flag-1").resolved_on is None
    assert "error" in resolve("doctor", "2026-11-30")  # before it started
    assert resolve("doctor", "2026-12-03")["cleared_by"] == "doctor"


def test_a_config_patch_that_breaks_the_config_is_undone(home):
    import pytest

    from coach.coaching import proposals
    from coach.config import load_config
    from coach.store import Store

    st = Store()
    cfg = load_config()
    f = home / "athlete" / "config" / "athlete_context.json"
    original = f.read_text()
    d = dt.date(2026, 12, 1)
    p = proposals.create(
        st,
        "calibration",
        "learn",
        "bad patch",
        "x",
        "y",
        d,
        payload={
            "config_patch": {
                "file": "athlete_context.json",
                "path": ["thresholds", "recovery_green_min"],
                "value": "not a number",
            }
        },
    )
    with pytest.raises(ValueError):
        proposals.approve(st, p.id, d, cfg)
    assert f.read_text() == original
    assert st.proposal(p.id).status == "pending"


# ---------- one home per session: the day record (DECISIONS 102) ----------
def _week_store(b1, tmp_path):
    _, plan, _ = b1
    st = Store(tmp_path / "data")
    st.put("week_plans", plan)
    return st, plan


def test_week_plan_sessions_live_in_day_records(b1, tmp_path):
    import json

    st, plan = _week_store(b1, tmp_path)
    raw = json.loads((tmp_path / "data" / "weeks" / plan.week_id / "plan.json").read_text())
    assert "sessions" not in raw  # the week file holds no copy
    for s in plan.sessions:
        rec = st.day_record(s.date)
        assert rec.status == "planned" and rec.planned_session == s and rec.session is None
    assert st.week_plan(plan.week_id) == plan  # assembled back from the day records


def test_a_day_change_shows_in_the_week(b1, tmp_path):
    """The bug that started this: a test added on the day was invisible to the week (and to test scoring)."""
    from coach.coaching.daily import tests_scheduled

    st, plan = _week_store(b1, tmp_path)
    day = plan.sessions[0].date
    rec = st.day_record(day)
    adjusted = rec.planned_session.model_copy(deep=True)
    adjusted.tests = [*adjusted.tests, "standing_reach"]
    rec.status, rec.session = "complete", adjusted
    st.put("day_records", rec)
    week = st.week_plan(plan.week_id)
    assert week.session_on(day).tests[-1] == "standing_reach"
    assert tests_scheduled(week)["standing_reach"] == day
    assert st.day_record(day).planned_session == plan.sessions[0]  # the plan as written is kept


def test_daily_record_keeps_the_planned_session(b1, tmp_path):
    from coach.models import DayRecord

    st, plan = _week_store(b1, tmp_path)
    day = plan.sessions[1].date
    st.put("day_records", DayRecord(date=day, status="paused"))  # a fresh record from the daily run
    rec = st.day_record(day)
    assert rec.planned_session == plan.sessions[1] and rec.current_session() == plan.sessions[1]


def test_adjust_starts_from_the_plan_not_an_earlier_adjustment(b1):
    from coach.coaching.skills import adjust_day

    ctx, plan, _ = b1
    day = plan.sessions[0].date
    ctx.state.put("week_plans", plan)
    first = adjust_day.adjust(ctx, day, ctx.state.week_plan(plan.week_id))
    ctx.state.put("day_records", first)
    again = adjust_day.adjust(ctx, day, ctx.state.week_plan(plan.week_id))
    assert again.planned_session == plan.sessions[0]
    assert again.session == first.session  # re-running applies the same changes once, not twice


def test_week_revision_of_a_day_already_run(b1, tmp_path):
    st, plan = _week_store(b1, tmp_path)
    day = plan.sessions[2].date
    rec = st.day_record(day)
    rec.status, rec.session = "complete", rec.planned_session.model_copy(deep=True)
    st.put("day_records", rec)
    st.put("week_plans", st.week_plan(plan.week_id))  # unchanged week: no-op
    assert st.day_record(day).changes == []
    revised = st.week_plan(plan.week_id)
    other = next(s for s in revised.sessions if s.type != revised.session_on(day).type)
    new = other.model_copy(deep=True)
    new.date, new.id = day, f"{day}-moved"
    revised.sessions = [new if s.date == day else s for s in revised.sessions]
    st.put("week_plans", revised)
    rec = st.day_record(day)
    assert rec.session == new and rec.planned_session == new  # the revision is the day's new plan
    assert rec.changes[-1].kind == "replan"


def test_rerun_after_a_week_revision_keeps_the_revision(b1):
    """Review of #18: complete day, week revised, daily re-run -> the re-run starts from the revised plan."""
    from coach.coaching.skills import adjust_day

    ctx, plan, _ = b1
    day = plan.sessions[0].date
    ctx.state.put("week_plans", plan)
    ctx.state.put("day_records", adjust_day.adjust(ctx, day, ctx.state.week_plan(plan.week_id)))
    revised = ctx.state.week_plan(plan.week_id)
    other = next(s for s in revised.sessions if s.type != revised.session_on(day).type)
    new = other.model_copy(deep=True)
    new.date, new.id = day, f"{day}-replanned"
    revised.sessions = [new if s.date == day else s for s in revised.sessions]
    ctx.state.put("week_plans", revised)
    again = adjust_day.adjust(ctx, day, ctx.state.week_plan(plan.week_id))
    assert again.planned_session_id == f"{day}-replanned"
    assert again.session is not None and again.session.type == new.type


def test_one_session_per_day(b1, tmp_path):
    import pytest

    _, plan, _ = b1
    bad = plan.model_copy(deep=True)
    dup = bad.sessions[0].model_copy(deep=True)
    dup.id = "dup"
    bad.sessions.append(dup)
    with pytest.raises(ValueError, match="one session per day"):
        Store(tmp_path / "d").put("week_plans", bad)


def test_migrate_legacy_week_files(b1, tmp_path):
    import json

    from coach.models import DayRecord

    _, plan, _ = b1
    st = Store(tmp_path / "data")
    p = tmp_path / "data" / "weeks" / plan.week_id / "plan.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(plan.model_dump(mode="json")))  # a week file from before the change
    ran = plan.sessions[0]
    adjusted = ran.model_copy(deep=True)
    adjusted.title = "adjusted"
    st.put("day_records", DayRecord(date=ran.date, status="complete", session=adjusted))
    assert st.week_plan(plan.week_id).session_on(ran.date).title == "adjusted"  # readable before migrating
    assert st.migrate_week_plans() == [plan.week_id]
    assert "sessions" not in json.loads(p.read_text())
    rec = st.day_record(ran.date)
    assert rec.planned_session == ran and rec.session == adjusted
    assert st.day_record(plan.sessions[1].date).planned_session == plan.sessions[1]
    assert st.migrate_week_plans() == []  # idempotent
    week = st.week_plan(plan.week_id)
    assert [s.date for s in week.sessions] == [s.date for s in plan.sessions]


def test_week_save_guards(b1, tmp_path):
    """Review of #18: stopped days are never overwritten, a run day's session can't be dropped, sessions stay
    inside their week, and a dropped planned-only day loses its record. Checks run before any write."""
    import pytest

    from coach.coaching.skills import design as D

    ctx, plan, _ = b1
    st, plan = _week_store(b1, tmp_path)
    d0, d1, d2 = (plan.sessions[i].date for i in range(3))
    # a red-flag stop: the day keeps its rest session whatever the week says
    stop = st.day_record(d0)
    stop.status, stop.session = "stopped_red_flag", D.rest_session(ctx, d0, "Red flag: see a doctor.")
    st.put("day_records", stop)
    st.put("week_plans", plan)  # the original week again, with d0 still a training session
    assert (
        st.day_record(d0).session.type == "rest" and st.week_plan(plan.week_id).session_on(d0).type == "rest"
    )
    # dropping a planned-only day deletes its record
    week = st.week_plan(plan.week_id)
    week.sessions = [s for s in week.sessions if s.date != d2]
    st.put("week_plans", week)
    assert st.day_record(d2) is None and st.week_plan(plan.week_id).session_on(d2) is None
    # dropping a day already run fails, and nothing is written
    ran = st.day_record(d1)
    ran.status, ran.session = "complete", ran.planned_session
    st.put("day_records", ran)
    before = st.week_plan(plan.week_id)
    week = before.model_copy(deep=True)
    week.sessions = [s for s in week.sessions if s.date != d1]
    week.focus_points = ["changed"]
    with pytest.raises(ValueError, match="can't drop"):
        st.put("week_plans", week)
    assert st.week_plan(plan.week_id) == before
    # sessions outside the week
    week = before.model_copy(deep=True)
    week.sessions[-1].date = plan.end + dt.timedelta(days=1)
    with pytest.raises(ValueError, match="outside the week"):
        st.put("week_plans", week)


def test_daily_run_turns_a_planned_day_into_a_run_day(home):
    """planned -> complete through the daily run: the plan survives, the current session is the adjusted one, and a
    second run (finish mode, a re-run) starts from the same plan."""
    from coach.coaching.daily import run_daily
    from coach.integrations.mock import MockWorld, mock_sources

    day = dt.date(2026, 11, 17)
    src = mock_sources(MockWorld.load())
    st = Store()
    first = run_daily(src, st, day, auto_approve=True).record
    rec = st.day_record(day)
    assert rec.status == "complete" and rec.planned_session is not None
    assert rec.planned_session.id == first.planned_session_id
    nxt = st.day_record(day + dt.timedelta(days=1))
    assert nxt is not None and nxt.status == "planned" and nxt.session is None
    run_daily(src, st, day, auto_approve=True)
    again = st.day_record(day)
    assert again.planned_session == rec.planned_session and again.session == rec.session
    week = st.week_plan(rec.planned_session.date.strftime("%G-W%V"))
    assert week.session_on(day) == rec.current_session()


def test_week_submit_reports_a_kept_red_flag_stop(b1):
    from coach.coaching import records
    from coach.coaching.skills import design as D

    ctx, plan, _ = b1
    day = plan.sessions[0].date
    ctx.state.put("week_plans", plan)
    stop = ctx.state.day_record(day)
    stop.status, stop.session = "stopped_red_flag", D.rest_session(ctx, day, "Red flag: see a doctor.")
    ctx.state.put("day_records", stop)
    res = records.submit(ctx.state, ctx.cfg, "week_plans", plan.model_dump(mode="json"), day)
    assert any("kept the red-flag stop" in a for a in res["actions"])
    assert ctx.state.day_record(day).session.type == "rest"
