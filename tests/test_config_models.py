import datetime as dt
import json

import pytest
from pydantic import ValidationError

from coach.config import load_config
from coach.engine import macrocycle as M
from coach.engine.validator import validate_macrocycle, validate_outline
from coach.models import AthleteProfile, Session


def test_config_loads_and_is_consistent():
    cfg = load_config()
    assert cfg.profile.identity.height_cm == 188
    assert "safety_squat_bar" in cfg.equipment.locations["gym"].equipment
    assert "belt_squat" not in cfg.equipment.locations["gym"].equipment
    assert cfg.equipment.loading["kettlebells_lb"] == [26, 35, 53, 70]
    assert len(cfg.progressions.families) == 6


def test_profile_rejects_unknown_fields_and_duplicate_races():
    raw = json.loads((load_config().root / "athlete_context.json").read_text())
    AthleteProfile.model_validate(raw)
    bad = dict(raw, current_weight_kg=97)
    with pytest.raises(ValidationError):
        AthleteProfile.model_validate(bad)
    dup = dict(raw, races=raw["races"] + [raw["races"][0]])
    with pytest.raises(ValidationError):
        AthleteProfile.model_validate(dup)


def test_profile_stores_no_current_weight():
    raw = (load_config().root / "athlete_context.json").read_text()
    assert "current_weight" not in raw and "body_fat_now" not in raw


def test_macrocycle_from_race_anchors():
    m = M.generate(load_config().profile, load_config().season, dt.date(2026, 11, 10))
    assert m.baseline_start == dt.date(2026, 11, 16)
    assert [b.start for b in m.blocks] == [
        dt.date(2026, 11, 23),
        dt.date(2027, 3, 15),
        dt.date(2027, 6, 28),
        dt.date(2027, 9, 27),
    ]
    assert m.blocks[3].end == dt.date(2027, 10, 31)
    assert m.blocks[0].competition_weeks == [dt.date(2027, 2, 15), dt.date(2027, 2, 22), dt.date(2027, 3, 1)]
    assert not validate_macrocycle(m)
    assert m.unconfirmed_races


def test_macrocycle_gap_and_overlap_detected():
    m = M.generate(load_config().profile, load_config().season, dt.date(2026, 11, 10))
    m.blocks[1].start += dt.timedelta(days=7)
    assert any(v.code == "MACRO_GAP" and "gap" in v.message for v in validate_macrocycle(m))
    m.blocks[1].start -= dt.timedelta(days=14)
    assert any("overlap" in v.message for v in validate_macrocycle(m))


def test_outline_validation(b1):
    ctx, _plan, _ = b1
    ol = ctx.outline
    assert not validate_outline(ol)
    bad = ol.model_copy(deep=True)
    for w in bad.weeks:
        if w.type == "deload":
            w.type = "training"
    bad.deload_weeks = []
    assert any(v.code == "OUTLINE_DELOAD" for v in validate_outline(bad))


def test_session_schema_requires_run_size():
    with pytest.raises(ValidationError):
        Session.model_validate(
            {
                "id": "x",
                "date": "2026-12-01",
                "type": "run_easy",
                "title": "t",
                "intent": "i",
                "expected_minutes": 30,
                "blocks": [{"kind": "run", "run": [{"label": "no size", "zone": "Z2"}]}],
            }
        )
