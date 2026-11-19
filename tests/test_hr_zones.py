"""Heart-rate-reserve zones (Whoop's model) and how they reach the context and test scoring."""

import copy
import datetime as dt

import pytest

from coach.engine.paces import Zones

TODAY = dt.date(2026, 11, 18)


def test_lthr_model_is_unchanged_by_default():
    z = Zones(lthr=165, threshold_pace_s_per_mi=480)
    assert not z.uses_hrr and z.hr("Z2") == (124, 139) and z.z2_ceiling() == 139


def test_hrr_zones_match_whoop_settings_screen():
    # Whoop, resting 52 / max 194: Z1 109-137, Z2 138-152, Z3 153-166, Z4 167-180, Z5 181-194
    z = Zones(lthr=165, threshold_pace_s_per_mi=480, hr_model="hrr", max_hr=194, resting_hr=52)
    assert z.hr("Z2") == (138, 152) and z.z2_ceiling() == 152
    assert z.hr("Z1")[0] == 109 and z.hr("Z3")[1] == 166 and z.hr("T")[1] == 180 and z.hr("Z5")[1] == 194
    assert z.hr("strides") == (0, 0)
    d = z.as_dict()
    assert d["hr_model"] == "hrr" and d["hr"]["Z2"] == (138, 152)


def test_hrr_without_bounds_falls_back_to_lthr():
    assert Zones(lthr=165, threshold_pace_s_per_mi=480, hr_model="hrr").hr("Z2") == (124, 139)


def test_default_zones_hrr_needs_valid_bounds():
    from coach.models.profile import DefaultZones

    with pytest.raises(ValueError):
        DefaultZones(lthr=165, threshold_pace_s_per_mi=480, hr_model="hrr", max_hr=194)
    with pytest.raises(ValueError):
        DefaultZones(lthr=165, threshold_pace_s_per_mi=480, hr_model="hrr", max_hr=50, resting_hr=52)
    assert DefaultZones(lthr=165, threshold_pace_s_per_mi=480, hr_model="hrr", max_hr=194, resting_hr=52)


def _hrr_cfg():
    from coach.config import load_config
    from coach.models.profile import DefaultZones

    cfg = copy.deepcopy(load_config())  # never mutate a shared copy
    cfg.profile.running.default_zones = DefaultZones(
        lthr=165, threshold_pace_s_per_mi=480, hr_model="hrr", max_hr=194, resting_hr=52
    )
    return cfg


def _rhr(days, bpm):
    from coach.store import Store

    Store().upsert_metrics(
        [
            ("daily", d.isoformat(), d, {"date": d.isoformat(), "rhr_bpm": bpm})
            for d in (TODAY - dt.timedelta(days=i) for i in range(days))
        ],
        cache=True,
    )


def test_context_uses_config_then_whoop_values(home):
    from coach.coaching.context import build
    from coach.store import Store

    cfg = _hrr_cfg()
    z = build(cfg=cfg, today=TODAY).zones
    assert (z.hr_model, z.max_hr, z.resting_hr) == ("hrr", 194, 52)
    _rhr(6, 48)  # under a week of nights: the configured resting HR stays
    assert build(cfg=cfg, today=TODAY).zones.resting_hr == 52
    _rhr(10, 48)
    Store().set_whoop_body({"max_heart_rate": 191, "synced": TODAY.isoformat()})
    z = build(cfg=cfg, today=TODAY).zones
    assert (z.max_hr, z.resting_hr) == (191, 48)


def test_context_lthr_model_ignores_whoop(home):
    from coach.coaching.context import build
    from coach.store import Store

    Store().set_whoop_body({"max_heart_rate": 191})
    assert not build(today=TODAY).zones.uses_hrr


def _drift_result(lthr_est):
    from coach.models.records import TestResult, TestSet

    r = TestResult(
        test_id="run_submax_drift",
        date=TODAY,
        value=640,
        unit="s_per_mi",
        details={"lthr": lthr_est, "threshold_pace_s_per_mi": 640, "confidence": "low"},
    )
    return TestSet(block_id="B0", phase="baseline", results=[r])


def test_submax_estimate_keeps_lthr_under_hrr(home):
    from coach.coaching.context import build
    from coach.coaching.skills import assess

    ctx = build(cfg=_hrr_cfg(), today=TODAY)
    z = assess.update_zones_from(ctx, _drift_result(188))
    assert z and z.lthr == 165 and z.threshold_pace_s_per_mi == 640
    ctx = build(today=TODAY)  # LTHR model: the estimate is taken as before
    assert assess.update_zones_from(ctx, _drift_result(188)).lthr == 188


def test_sync_caches_whoop_max_hr(home):
    from coach.integrations import mock
    from coach.integrations.sync import sync
    from coach.store import Store

    world = mock.MockWorld.load()
    world.whoop["body"] = {"max_heart_rate": 192.0, "height_meter": 1.8}
    report = sync(mock.mock_sources(world), Store(), TODAY)
    assert "whoop_body" not in report["errors"]
    assert Store().whoop_body()["max_heart_rate"] == 192
    assert "height_meter" not in Store().whoop_body()


def test_resting_at_or_above_max_falls_back_to_lthr(home):
    from coach.coaching.context import build
    from coach.store import Store

    Store().set_whoop_body({"max_heart_rate": 50})  # implausible: below the resting HR
    assert not build(cfg=_hrr_cfg(), today=TODAY).zones.uses_hrr


def test_live_whoop_body_calls_the_broker(monkeypatch):
    from coach.integrations import live

    calls = []
    monkeypatch.setenv("WHOOP_BROKER_URL", "https://broker.example/")
    monkeypatch.setattr(
        live, "_request", lambda m, url, h=None, **k: calls.append((m, url)) or {"max_heart_rate": 194}
    )
    assert live.LiveWhoop().body() == {"max_heart_rate": 194}
    assert calls == [("GET", "https://broker.example/v2/user/measurement/body")]
    monkeypatch.delenv("WHOOP_BROKER_URL")
    with pytest.raises(RuntimeError):
        live.LiveWhoop().body()


@pytest.mark.parametrize("body", ["fail", {"height_meter": 1.8}, None])
def test_sync_body_failure_or_missing_max_is_not_whoop_offline(home, body):
    from coach.integrations import mock
    from coach.integrations.sync import sync
    from coach.store import Store

    world = mock.MockWorld.load()
    src = mock.mock_sources(world)
    if body == "fail":

        def boom():
            raise RuntimeError("broker 404")

        src.whoop.body = boom
    else:
        world.whoop["body"] = body
    report = sync(src, Store(), TODAY)
    assert ("whoop_body" in report["errors"]) == (body == "fail")
    assert "whoop" not in report["errors"] and not report["whoop_offline"]
    assert Store().whoop_body() is None


def test_fingerprint_locks_hrr_settings_only_when_used():
    from coach.config import load_config
    from coach.engine.validator import thresholds_fingerprint
    from coach.models.profile import DefaultZones

    base = copy.deepcopy(load_config())
    fp_lthr = thresholds_fingerprint(base)
    base.profile.running.default_zones = DefaultZones(lthr=165, threshold_pace_s_per_mi=480, max_hr=194)
    assert thresholds_fingerprint(base) == fp_lthr  # LTHR model: existing locks stay valid
    hrr = _hrr_cfg()
    fp_hrr = thresholds_fingerprint(hrr)
    assert fp_hrr != fp_lthr
    hrr.profile.running.default_zones = DefaultZones(
        lthr=165, threshold_pace_s_per_mi=480, hr_model="hrr", max_hr=190, resting_hr=52
    )
    assert thresholds_fingerprint(hrr) != fp_hrr  # changing a fallback needs approval


def test_zone_minutes_use_hrr_bins():
    from coach.engine.paces import zone_minutes_from_hr

    z = Zones(lthr=165, threshold_pace_s_per_mi=480, hr_model="hrr", max_hr=194, resting_hr=52)
    assert zone_minutes_from_hr(150, 20, 165, z) == [0.0, 20.0, 0.0, 0.0, 0.0]  # Whoop Z2
    assert zone_minutes_from_hr(150, 20, 165) == [0.0, 0.0, 20.0, 0.0, 0.0]  # LTHR model: 91% of LTHR
