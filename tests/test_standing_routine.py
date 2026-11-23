"""Standing Hevy routines from training.yaml item sets (coach push --routine)."""

import datetime as dt

import pytest

TODAY = dt.date(2026, 11, 19)


def _ctx():
    from coach.coaching.context import build

    return build(today=TODAY)


def test_standing_routine_is_undated_and_estimated(home):
    from coach.integrations.push import standing_routine

    s = standing_routine("recovery_mobility", _ctx())
    assert s.id == "routine-recovery_mobility" and s.location == "home" and s.expected_minutes > 0
    assert s.all_items()


def test_push_routine_upserts_one_routine(home):
    from coach.integrations.mock import MockWorld, mock_sources
    from coach.integrations.push import push_routine
    from coach.store import Store

    world = MockWorld.load()
    src = mock_sources(world)
    ctx = _ctx()
    dry = push_routine("recovery_mobility", ctx, src, dry_run=True)
    assert dry["dry_run"] and "routine_id" not in dry and not world.routines
    a = push_routine("recovery_mobility", ctx, src, dry_run=False)
    b = push_routine("recovery_mobility", ctx, src, dry_run=False)
    assert a["routine_id"] == b["routine_id"] and len(world.routines) == 1
    r = world.routines[a["routine_id"]]
    assert r["title"].endswith("(coach)") and "Standing routine" in r["notes"]
    assert str(r["folder_id"]) == world.folders["Standing (coach)"] and len(world.folders) == 1
    assert Store().get("push_ids")["hevy:routine-recovery_mobility"] == a["routine_id"]


def test_push_routine_unknown_set(home):
    from coach.integrations.push import push_routine

    with pytest.raises(KeyError):
        push_routine("nope", _ctx(), None, dry_run=True)


def test_push_routine_refuses_work_it_would_drop(home):
    """A gym-only exercise has no home version: the push refuses rather than silently dropping it."""
    import copy

    from coach.integrations.push import PushRefused, push_routine
    from coach.models.season import ItemSet, ItemSpec

    ctx = _ctx()
    ctx.cfg = copy.deepcopy(ctx.cfg)
    ctx.cfg.training.item_sets["mixed"] = ItemSet(
        title="x",
        items=[ItemSpec(exercise="leg_press", sets=1, reps=5), ItemSpec(exercise="cat_cow", sets=1, reps=6)],
    )
    with pytest.raises(PushRefused) as e:
        push_routine("mixed", ctx, None, dry_run=True)
    assert "EQUIPMENT" in str(e.value.violations[0]) and "leg_press" in str(e.value.violations[0])


def test_push_routine_empty_set(home):
    import copy

    from coach.integrations.push import push_routine
    from coach.models.season import ItemSet

    ctx = _ctx()
    ctx.cfg = copy.deepcopy(ctx.cfg)
    ctx.cfg.training.item_sets["empty"] = ItemSet(title="e", items=[])
    assert "no exercises" in push_routine("empty", ctx, None, dry_run=True)["error"]


def test_push_routine_refused_when_ill(home):
    from coach.integrations.push import PushRefused, push_routine
    from coach.models.journal import HealthEvent
    from coach.store import Store

    Store().put(
        "health_events",
        HealthEvent(id="2026-11-19-ill", kind="illness", start=TODAY, symptoms="below_neck"),
    )
    with pytest.raises(PushRefused):
        push_routine("recovery_mobility", _ctx(), None, dry_run=True)


def test_cli_push_routine_unknown(home, capsys):
    import sys

    from coach.cli import main

    sys.argv = ["coach", "push", "--routine", "nope", "--dry-run"]
    main()
    assert "no item set" in capsys.readouterr().out
    sys.argv = ["coach", "push", "--routine", "recovery_mobility", "--dry-run"]
    main()
    out = capsys.readouterr().out
    assert '"dry_run": true' in out and "(coach)" in out
