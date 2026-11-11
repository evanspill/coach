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
