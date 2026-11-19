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
    assert Store().get("push_ids")["hevy:routine-recovery_mobility"] == a["routine_id"]


def test_push_routine_unknown_set(home):
    from coach.integrations.push import push_routine

    with pytest.raises(KeyError):
        push_routine("nope", _ctx(), None, dry_run=True)


def test_push_routine_only_home_equipment(home):
    """The picker swaps gym-only work for what's available at home (or the push refuses it)."""
    import copy

    from coach.integrations.push import PushRefused, push_routine, standing_routine
    from coach.models.season import ItemSet, ItemSpec

    ctx = _ctx()
    ctx.cfg = copy.deepcopy(ctx.cfg)
    ctx.cfg.training.item_sets["gym_only"] = ItemSet(
        title="x", items=[ItemSpec(exercise="leg_press", sets=1, reps=5)]
    )
    available = ctx.cfg.equipment.available("home", ctx.cfg.profile.travel_equipment)
    try:
        s = standing_routine("gym_only", ctx)
        push_routine("gym_only", ctx, None, dry_run=True)
    except PushRefused as e:
        assert "EQUIPMENT" in str(e.violations[0])
    else:
        for it in s.all_items():
            assert all(eq in available for eq in ctx.cfg.library.get(it.exercise_id).equipment)


def test_cli_push_routine_unknown(home, capsys):
    import sys

    from coach.cli import main

    sys.argv = ["coach", "push", "--routine", "nope", "--dry-run"]
    main()
    assert "no item set" in capsys.readouterr().out
