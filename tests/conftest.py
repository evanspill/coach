import datetime as dt

import pytest

from coach.sim.run import sandbox
from coach.sim.scenarios import world_at


@pytest.fixture
def home():
    with sandbox() as h:
        yield h


@pytest.fixture(scope="module")
def b1():
    """Block 1 context on Sun 2026-11-29 with a valid plan for the week of 2026-11-30."""
    from coach.fallback.plan_week import plan_week

    with sandbox() as h:
        ctx = world_at(dt.date(2026, 11, 29))
        plan = plan_week(ctx, dt.date(2026, 11, 30))
        yield ctx, plan, h
