import datetime as dt
import os
import shutil
import tempfile
from pathlib import Path

import pytest


def pytest_configure(config):
    """Engine tests run against the bundled demo athlete, never the repo's own config/ or state/."""
    from coach import paths

    home = Path(tempfile.mkdtemp(prefix="coach-tests-"))
    shutil.copytree(paths.demo_config_dir(), home / "config")
    (home / "state").mkdir()
    os.environ.update({"COACH_HOME": str(home), "COACH_STATE_DIR": str(home / "state"), "COACH_MOCK": "1"})


@pytest.fixture
def home():
    from coach.sim.run import sandbox

    with sandbox() as h:
        yield h


@pytest.fixture(scope="module")
def b1():
    """Block 1 context on Sun 2026-11-29 with a valid plan for the week of 2026-11-30."""
    from coach.fallback.plan_week import plan_week
    from coach.sim.run import sandbox
    from coach.sim.scenarios import world_at

    with sandbox() as h:
        ctx = world_at(dt.date(2026, 11, 29))
        plan = plan_week(ctx, dt.date(2026, 11, 30))
        yield ctx, plan, h
