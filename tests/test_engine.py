import datetime as dt
import math

import pytest

from coach.config import load_config
from coach.engine import deloads, loads, nutrition, paces, readiness, running, weather
from coach.engine import gear as G
from coach.models import Checkin, DailyMetrics, Gear

TH = load_config().profile.thresholds


def _metrics(today, rec_today, rec_y=72, hrv_drop=0.0, drop_days=0, rhr_add=0.0):
    out = []
    for i in range(70, -1, -1):
        d = today - dt.timedelta(days=i)
        ln = math.log(62) + (0.03 if i % 2 else -0.03) - (hrv_drop if i < drop_days else 0)
        rec = rec_today if i == 0 else rec_y if i == 1 else 72
        out.append(
            DailyMetrics(
                date=d, recovery_score=rec, hrv_rmssd_ms=math.exp(ln), rhr_bpm=50 + (rhr_add if i < 7 else 0)
            )
        )
    return out


D = dt.date(2027, 1, 10)


@pytest.mark.parametrize(
    "kw, checkins, expect",
    [
        (dict(rec_today=80), [], "green"),
        (dict(rec_today=50), [], "green"),  # 34-66 with HRV trend in band
        (dict(rec_today=50, hrv_drop=0.15, drop_days=1), [], "yellow"),  # 34-66 with HRV below band
        (dict(rec_today=30), [], "yellow"),  # single low day
        (dict(rec_today=80, rhr_add=4), [], "yellow"),
        (dict(rec_today=30, rec_y=25), [], "red"),  # two days <= 33
        (dict(rec_today=80, hrv_drop=0.2, drop_days=3), [], "red"),  # HRV below band 3 days
        (dict(rec_today=80, rhr_add=6), [], "red"),
        (dict(rec_today=90), [Checkin(date=D, shoulders=4)], "red"),  # joint >= 4 beats a great recovery
        (
            dict(rec_today=90),
            [Checkin(date=D - dt.timedelta(days=1), back=3), Checkin(date=D, back=3)],
            "red",
        ),
        (dict(rec_today=90), [Checkin(date=D, knees_achilles=3)], "yellow"),
    ],
)
def test_readiness_states_and_precedence(kw, checkins, expect):
    r = readiness.compute_readiness(D, _metrics(D, **kw), checkins, TH)
    assert r.state == expect, r.reasons
    assert r.reasons


def test_missing_recovery_is_unknown():
    ms = [m for m in _metrics(D, 80) if m.date != D]
    r = readiness.compute_readiness(D, ms, [], TH)
    assert r.state == "unknown" and "whoop_recovery" in r.data_missing


def test_joint_flag_sets_and_clears():
    restricted = load_config().progressions.joint_flags
    cis = [
        Checkin(date=D - dt.timedelta(days=3), shoulders=3),
        Checkin(date=D - dt.timedelta(days=2), shoulders=3),
    ]
    flags = readiness.joint_flags(cis, D, restricted, TH)
    assert flags and flags[0].region == "shoulders" and "overhead" in flags[0].restricted_tags
    cis += [Checkin(date=D - dt.timedelta(days=1), shoulders=2), Checkin(date=D, shoulders=2)]
    assert not readiness.joint_flags(cis, D, restricted, TH)


def test_sustained_red_from_prior_states():
    prior = {D - dt.timedelta(days=1): "red", D - dt.timedelta(days=2): "red"}
    r = readiness.compute_readiness(D, _metrics(D, 30, 25), [], TH, prior_states=prior)
    assert r.sustained_red


def test_rpe_to_rir():
    assert readiness.rpe_to_rir(8) == 2
    assert readiness.rpe_to_rir(10) == 0
    assert readiness.rpe_to_rir(None) is None


def test_load_rounding():
    L = load_config().equipment.loading
    r = loads.round_load(100.0, "barbell", L)  # 220.5 lb -> 220 lb (45 bar + 2.5 lb steps)
    assert r.load_lb == 220.0
    r = loads.round_load(30.0, "dumbbell", L)  # 66 lb -> 65
    assert r.load_lb == 65
    assert loads.round_load(60.0, "dumbbell", L).load_lb == 100  # rack max
    assert loads.round_load(23.0, "kettlebell", L).load_lb == 53
    assert loads.round_load(40.0, "kettlebell", L).load_kg is None  # > 70 lb: swap to DBs
    assert loads.round_load(50, "machine", L).load_kg is None


def test_e1rm_and_inverse():
    e = loads.e1rm(100, 5, 2)
    assert e == pytest.approx(100 * (1 + 7 / 30))
    assert loads.load_for(e, 5, 2) == pytest.approx(100)


def test_progression_rules():
    from coach.models import SessionRecord, SetRecord

    def sess(day, reps, rir):
        return SessionRecord(
            id=str(day),
            date=day,
            start=dt.datetime(day.year, day.month, day.day, 9),
            sport="strength",
            title="x",
            duration_min=60,
            sets=[
                SetRecord(
                    exercise_id="trap_bar_deadlift_high", exercise_name="x", weight_kg=150, reps=reps, rir=rir
                )
            ],
        )

    today = dt.date(2026, 12, 20)
    hit = [sess(today - dt.timedelta(days=7), 5, 2)]
    assert loads.progression(hit, "trap_bar_deadlift_high", 5, 2, today).factor > 1
    miss2 = [sess(today - dt.timedelta(days=14), 4, 0), sess(today - dt.timedelta(days=7), 4, 0)]
    assert loads.progression(miss2, "trap_bar_deadlift_high", 5, 2, today).factor < 1
    miss1 = [sess(today - dt.timedelta(days=14), 5, 2), sess(today - dt.timedelta(days=7), 4, 0)]
    assert loads.progression(miss1, "trap_bar_deadlift_high", 5, 2, today).factor == 1


def test_zones_from_lthr():
    z = paces.Zones(lthr=170, threshold_pace_s_per_mi=450)
    lo, hi = z.hr("Z2")
    assert hi <= 0.85 * 170 and lo >= 0.74 * 170
    t_fast, t_slow = z.pace("T")
    assert t_fast <= 450 <= t_slow
    assert z.pace("Z2")[0] > 450


def test_weather_tiers_ice_and_daylight():
    rules = load_config().profile.weather
    day = dt.date(2027, 7, 15)

    def hours(temp_c, dew_c, precip=0.0, d=day):
        return [
            {
                "time": dt.datetime(d.year, d.month, d.day, h),
                "temp_c": temp_c,
                "dew_point_c": dew_c,
                "precip_mm": precip,
            }
            for h in range(24)
        ]

    assert weather.weather_call(day, hours(20, 10), rules, 41.8, -72.9).tier == "normal"  # 68 + 50 = 118
    w = weather.weather_call(day, hours(28, 18), rules, 41.8, -72.9)  # 82 + 64 = 146
    assert w.tier == "slow" and w.pace_adjust_s_per_mi == (15, 30)
    assert weather.weather_call(day, hours(33, 24), rules, 41.8, -72.9).tier == "indoor"  # 91 + 75
    winter = dt.date(2027, 1, 20)
    ice = hours(-3, -6, 0.5, winter)
    assert weather.weather_call(winter, ice, rules, 41.8, -72.9).icy
    assert (
        weather.weather_call(winter, hours(5, 0, 0, winter), rules, 41.8, -72.9, start="18:30").tier
        == "indoor"
    )  # dark
    rise, sset = weather.sun_times(dt.date(2026, 12, 21), 41.82, -72.9)
    assert 7 <= rise.hour <= 7 and 16 <= sset.hour <= 16


def test_calorie_neutral_carbs():
    rules = load_config().profile.nutrition
    start = dt.date(2026, 11, 30)
    tiers = {
        start + dt.timedelta(days=i): t
        for i, t in enumerate(["high", "moderate", "moderate", "high", "moderate", "high", "low"])
    }
    days = nutrition.distribute_week(3000 * 7, 95, tiers, rules)
    assert abs(sum(d.kcal for d in days) - 21000) <= 7
    assert all(d.fat_g >= 100 for d in days)
    assert days[0].carbs_g > days[6].carbs_g
    tight = nutrition.distribute_week(2100 * 7, 95, tiers, rules)
    assert all(d.scaled for d in tight) and abs(sum(d.kcal for d in tight) - 14700) <= 7
    assert tight[0].carbs_g / tight[6].carbs_g == pytest.approx(5.5 / 3.0, rel=0.02)


def test_deload_placement_counts_back_from_transition():
    assert deloads.plan_deloads(16, {13, 14, 15}) == [4, 8, 12]
    d = deloads.plan_deloads(15)
    assert d == [3, 7, 11]
    types = ["deload" if i in d else "training" for i in range(1, 15)] + ["transition"]
    assert deloads.max_run_without_deload(types) <= 4


def test_reactive_deload_shifts_rest_of_block():
    new = deloads.pull_forward([4, 8, 12], 7, 16, {13, 14, 15})
    assert new == [4, 7, 11]
    types = ["deload" if i in new else "training" for i in range(1, 16)] + ["transition"]
    assert deloads.max_run_without_deload(types) <= 4


def test_return_to_running_ramp():
    rules = running.RampRules(start_miles=(10, 12))
    types = ["training"] * 3 + ["deload"] + ["training"] * 4
    t = running.ramp_targets(8, types, 10, 15, rules)
    assert t[0] == 10
    assert t[3] < t[2]  # deload
    normal = [m for m, wt in zip(t, types, strict=True) if wt == "training"]  # deloads don't reset the ramp
    for a, b in zip(normal, normal[1:], strict=False):
        assert b <= a * 1.10 + 0.05
    assert max(t) <= 15
    assert running.allowed_increase_cap([10, 10, 10], rules) == 11
    assert running.allowed_increase_cap([], rules) == 12
    assert running.allowed_increase_cap([4, 4, 4], rules) == 10  # ramp start is a floor


def test_long_run_fraction():
    assert running.long_run_fraction_ok(4.0, 11.0, TH)[0]  # low volume: 40%
    assert not running.long_run_fraction_ok(9.0, 25.0, TH)[0]  # 36% > 30%


def test_shoe_alerts():
    gear = [
        Gear(id="a", name="Cushioned trainer", distance_mi=262),
        Gear(id="b", name="Firm trainer", distance_mi=40),
    ]
    alerts = G.shoe_alerts(gear, 250)
    assert len(alerts) == 1 and "Cushioned" in alerts[0]
    assert G.shoe_for("hyrox", gear) == "Firm trainer"
    assert G.shoe_for("run_long", gear) == "Cushioned trainer"
