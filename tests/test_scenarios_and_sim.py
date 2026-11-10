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
