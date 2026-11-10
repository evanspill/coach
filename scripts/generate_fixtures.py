"""Generate deterministic mock fixtures (raw API shapes) for COACH_MOCK=1.

Covers 2026-09-17 -> 2027-03-21: ~60 days of pre-baseline history (for HRV/RHR baselines and loads)
plus ~126 days from the baseline week through Block 1's transition week. Includes a bad-recovery streak,
a shoulder flare-up, a missed week, late Whoop data, icy days and one block's worth of test results.

Run: python scripts/generate_fixtures.py   (writes src/coach/fixtures/*.json)
"""

import datetime as dt
import json
import math
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "coach" / "demo" / "fixtures"
START = dt.date(2026, 9, 17)
END = dt.date(2027, 3, 21)
BASELINE = dt.date(2026, 11, 16)
TZ_OFFSET = "-05:00"

rng = random.Random(20261116)

BAD_STREAK = {dt.date(2026, 12, 29) + dt.timedelta(days=i) for i in range(5)}  # sustained red
SINGLE_LOW = {dt.date(2026, 12, 9), dt.date(2027, 1, 14), dt.date(2027, 2, 23)}  # yellow days
MID_DIP = {dt.date(2026, 12, 2), dt.date(2026, 12, 3), dt.date(2027, 2, 10)}  # recovery 40-55
MISSED = {dt.date(2027, 1, 25) + dt.timedelta(days=i) for i in range(7)}  # work trip: missed week
LATE_RECOVERY = [dt.date(2026, 12, 10), dt.date(2027, 2, 2)]
ICY = {
    dt.date(2026, 12, 15),
    dt.date(2026, 12, 16),
    dt.date(2027, 1, 20),
    dt.date(2027, 2, 3),
    dt.date(2027, 2, 4),
}
SHOULDER = {
    dt.date(2027, 1, 18): 2,
    dt.date(2027, 1, 19): 3,
    dt.date(2027, 1, 20): 3,
    dt.date(2027, 1, 21): 4,
    dt.date(2027, 1, 22): 3,
    dt.date(2027, 1, 23): 2,
    dt.date(2027, 1, 24): 2,
}


def iso(d: dt.date, hh: int = 9, mm: int = 30) -> str:
    return f"{d.isoformat()}T{hh:02d}:{mm:02d}:00{TZ_OFFSET}"


def days():
    d = START
    while d <= END:
        yield d
        d += dt.timedelta(days=1)


def whoop_and_wellness():
    recovery, sleep, cycles, wellness = [], [], [], []
    base_ln = math.log(62)
    for i, d in enumerate(days()):
        ln = base_ln + rng.gauss(0, 0.09) + 0.03 * math.sin(i / 9)
        rhr = 50 + rng.gauss(0, 1.3)
        sleep_h = 7.4 + rng.gauss(0, 0.5)
        if d in BAD_STREAK:
            ln -= 0.38 + 0.04 * rng.random()
            rhr += 6.5
            sleep_h -= 1.4
        elif d in SINGLE_LOW:
            ln -= 0.35
            rhr += 2
        elif d in MID_DIP:
            ln -= 0.10
            rhr += 1
        hrv = round(math.exp(ln), 1)
        rec = 66 + 150 * (ln - base_ln) - 2.5 * (rhr - 50) + rng.gauss(0, 6)
        if d in BAD_STREAK:
            rec = 17 + rng.random() * 13
        if d in SINGLE_LOW:
            rec = min(rec, 30)
        if d in MID_DIP:
            rec = max(36, min(rec, 55))
        rec = int(max(5, min(99, rec)))
        cid = 900000 + i
        recovery.append(
            {
                "cycle_id": cid,
                "sleep_id": f"sleep-{d.isoformat()}",
                "user_id": 1,
                "created_at": f"{d.isoformat()}T07:10:00.000Z",
                "updated_at": f"{d.isoformat()}T07:12:00.000Z",
                "score_state": "SCORED",
                "score": {
                    "user_calibrating": False,
                    "recovery_score": rec,
                    "resting_heart_rate": round(rhr),
                    "hrv_rmssd_milli": hrv,
                    "spo2_percentage": 96.5,
                    "skin_temp_celsius": 33.4,
                },
            }
        )
        in_bed = sleep_h * 3600_000
        sleep.append(
            {
                "id": f"sleep-{d.isoformat()}",
                "start": f"{(d - dt.timedelta(days=1)).isoformat()}T22:45:00.000Z",
                "end": f"{d.isoformat()}T06:30:00.000Z",
                "nap": False,
                "score_state": "SCORED",
                "score": {
                    "stage_summary": {
                        "total_in_bed_time_milli": int(in_bed + 1800_000),
                        "total_awake_time_milli": 1800_000,
                    },
                    "sleep_performance_percentage": int(max(40, min(100, sleep_h / 8 * 100))),
                },
            }
        )
        cycles.append(
            {
                "id": cid,
                "start": f"{d.isoformat()}T05:00:00.000Z",
                "end": f"{(d + dt.timedelta(days=1)).isoformat()}T05:00:00.000Z",
                "score_state": "SCORED",
                "score": {
                    "strain": round(8 + rng.random() * 4, 1),
                    "kilojoule": 9000,
                    "average_heart_rate": 64,
                    "max_heart_rate": 150,
                },
            }
        )
        # wellness: weight via Withings separately; joints from check-ins; nutrition (Phase 3) via HealthFit
        w = {"id": d.isoformat(), "restingHR": round(rhr), "hrv": hrv, "ctl": None, "atl": None}
        if d >= BASELINE - dt.timedelta(days=30):
            target = 2800 if d >= dt.date(2026, 11, 23) else 3200
            kcal = target + rng.gauss(0, 180)
            if d in MISSED:
                kcal += 350
            protein = 210 + rng.gauss(0, 12)
            fat = 95 + rng.gauss(0, 12)
            carbs = (kcal - protein * 4 - fat * 9) / 4
            w.update(
                {
                    "kcalConsumed": round(kcal),
                    "protein": round(protein),
                    "fatTotal": round(fat),
                    "carbohydrates": round(carbs),
                }
            )
        if d >= BASELINE:
            back = 2 if rng.random() < 0.8 else 1
            sh = SHOULDER.get(d, 2 if rng.random() < 0.7 else 1)
            ka = 1 if rng.random() < 0.7 else 2
            if d in MISSED and rng.random() < 0.6:
                pass  # traveling: no check-in
            else:
                w.update({"BackFeel": back, "ShoulderFeel": sh, "KneeAchillesFeel": ka})
        wellness.append(w)
    return recovery, sleep, cycles, wellness


def withings():
    groups = []
    for i, d in enumerate(days()):
        if rng.random() < 0.08:
            continue  # skipped weigh-in
        progress = max(0, (d - dt.date(2026, 11, 23)).days)
        weight = 96.8 - 0.032 * progress + rng.gauss(0, 0.35)
        if d in MISSED:
            weight += 0.6
        bf = 18.2 - 0.020 * progress + rng.gauss(0, 0.5)
        ts = int(dt.datetime(d.year, d.month, d.day, 11, 45, tzinfo=dt.UTC).timestamp())
        groups.append(
            {
                "grpid": 5000 + i,
                "attrib": 0,
                "date": ts,
                "category": 1,
                "measures": [
                    {"value": int(round(weight * 1000)), "type": 1, "unit": -3},
                    {"value": int(round(bf * 10)), "type": 6, "unit": -1},
                    {"value": int(round(weight * bf / 100 * 1000)), "type": 8, "unit": -3},
                ],
            }
        )
    return {"status": 0, "body": {"updatetime": 0, "timezone": "America/New_York", "measuregrps": groups}}


def weather():
    times, temp, dew, precip = [], [], [], []
    d = START - dt.timedelta(days=1)
    while d <= END + dt.timedelta(days=2):
        doy = d.timetuple().tm_yday
        # seasonal mean (C): ~15 in late Sep, ~-4 in late Jan
        seasonal = 4.5 + 11 * math.cos(2 * math.pi * (doy - 200) / 365)
        day_offset = rng.gauss(0, 4)
        wet = rng.random() < 0.22 or d in ICY or (d + dt.timedelta(days=1)) in ICY
        for h in range(24):
            t = seasonal + day_offset + 4 * math.sin((h - 9) / 24 * 2 * math.pi)
            if d in ICY:
                t = min(t, -2.0)
            times.append(f"{d.isoformat()}T{h:02d}:00")
            temp.append(round(t, 1))
            dew.append(round(t - 3 - rng.random() * 4, 1))
            p = round(rng.random() * 1.2, 1) if wet and 0 <= h <= 8 else 0.0
            precip.append(p)
        d += dt.timedelta(days=1)
    return {
        "latitude": 41.8226,
        "longitude": -72.897,
        "timezone": "America/New_York",
        "hourly_units": {"temperature_2m": "°C", "dew_point_2m": "°C", "precipitation": "mm"},
        "hourly": {"time": times, "temperature_2m": temp, "dew_point_2m": dew, "precipitation": precip},
    }


def history():
    """Pre-baseline training (Sep 17 - Nov 15): 3 lifts + 2 short runs per week, as logged by the athlete."""
    hevy, whoop_w, activities = [], [], []
    lifts = {
        0: (
            "Lower",
            [
                ("Trap Bar Deadlift (High Handle)", 145, 5),
                ("Box Squat (Safety Squat Bar)", 105, 6),
                ("Seated Leg Curl (Machine)", 50, 10),
            ],
        ),
        2: (
            "Upper",
            [
                ("Bench Press (Dumbbell)", 30, 8),
                ("Pull Up", 0, 7),
                ("Chest Supported Incline Row (Dumbbell)", 30, 10),
            ],
        ),
        4: (
            "Full body",
            [
                ("Trap Bar Deadlift (High Handle)", 135, 6),
                ("Bench Press (Dumbbell)", 28, 10),
                ("Lat Pulldown (Cable)", 65, 10),
            ],
        ),
    }
    d = START
    n = 0
    while d < BASELINE:
        wd = d.weekday()
        if wd in lifts:
            title, exs = lifts[wd]
            weeks_in = (d - START).days / 7
            exercises = []
            for idx, (name, kg, reps) in enumerate(exs):
                load = round((kg * (1 + 0.006 * weeks_in)) / 2.5) * 2.5 if kg else 0
                sets = [
                    {
                        "index": 0,
                        "type": "warmup",
                        "weight_kg": round(load * 0.6, 1) if load else None,
                        "reps": 5,
                        "rpe": None,
                    }
                ]
                for s in range(3):
                    sets.append(
                        {
                            "index": s + 1,
                            "type": "normal",
                            "weight_kg": load or None,
                            "reps": reps,
                            "rpe": round(7.5 + rng.random(), 1),
                        }
                    )
                exercises.append(
                    {"index": idx, "title": name, "notes": "", "exercise_template_id": None, "sets": sets}
                )
            wid = f"hevy-hist-{n}"
            hevy.append(
                {
                    "id": wid,
                    "title": title,
                    "description": "back 2 shoulder 2" if rng.random() < 0.5 else "",
                    "start_time": iso(d, 9, 35),
                    "end_time": iso(d, 10, 35),
                    "exercises": exercises,
                }
            )
            whoop_w.append(_whoop_workout(f"ww-hist-{n}", d, "Weightlifting", 60, 118, 9.5))
        if wd in (1, 5):
            dist_mi = 3.0 if wd == 1 else 4.0
            pace = 600 + rng.gauss(0, 10)
            secs = int(dist_mi * pace)
            activities.append(
                {
                    "id": f"i-hist-{n}",
                    "start_date_local": f"{d.isoformat()}T09:40:00",
                    "type": "Run",
                    "name": "Easy run",
                    "moving_time": secs,
                    "elapsed_time": secs + 30,
                    "distance": round(dist_mi * 1609.344),
                    "average_heartrate": 138,
                    "max_heartrate": 151,
                    "icu_training_load": 30,
                    "average_cadence": 83,
                    "avg_ground_contact_time": 262,
                    "avg_vertical_oscillation": 9.1,
                    "avg_gct_balance": 50.6,
                    "gear": {"id": "g-1", "name": "Cushioned trainer"},
                    "description": None,
                }
            )
            whoop_w.append(_whoop_workout(f"ww-hist-run-{n}", d, "Running", secs / 60, 138, 9.0, hh=9, mm=40))
        n += 1
        d += dt.timedelta(days=1)
    return hevy, whoop_w, activities


def _whoop_workout(wid, d, sport, minutes, avg_hr, strain, hh=9, mm=35):
    start = dt.datetime(d.year, d.month, d.day, hh, mm)
    end = start + dt.timedelta(minutes=minutes)
    total = minutes * 60000
    return {
        "id": wid,
        "start": start.isoformat() + TZ_OFFSET,
        "end": end.isoformat() + TZ_OFFSET,
        "sport_name": sport,
        "score_state": "SCORED",
        "score": {
            "strain": strain,
            "average_heart_rate": avg_hr,
            "max_heart_rate": avg_hr + 22,
            "kilojoule": 1800,
            "zone_durations": {
                "zone_zero_milli": int(total * 0.05),
                "zone_one_milli": int(total * 0.35),
                "zone_two_milli": int(total * 0.4),
                "zone_three_milli": int(total * 0.15),
                "zone_four_milli": int(total * 0.05),
                "zone_five_milli": 0,
            },
        },
    }


def athlete_script():
    """How the simulated athlete behaves and performs: used by `coach simulate` (never by live runs)."""
    return {
        "missed_dates": sorted(d.isoformat() for d in MISSED),
        "missed_reason": "work trip (no gym)",
        "late_recovery_dates": [d.isoformat() for d in LATE_RECOVERY],
        "shoulder_session_pain": {"2027-01-19": {"press": 3.0}},
        "stiffness_up": {"2027-01-20": ["shoulders"]},
        "enjoyment_dip": {"start": "2027-02-22", "end": "2027-03-07", "enjoyment": 2, "rpe_add": 1.0},
        "bar_speed": {"2026-12-07": 0.62, "2026-12-14": 0.55, "2027-02-08": 0.71},
        "bar_speed_baseline": 0.66,
        "skipped_sessions": ["2026-12-17", "2026-12-18", "2027-02-11"],
        "test_results": {
            "baseline": {
                "broad_jump": {"attempts": [231, 236, 234]},
                "hinge_rm": {"weight_kg": 160.0, "reps": 5, "rir": 1},
                "squat_rm": {"weight_kg": 115.0, "reps": 5, "rir": 1},
                "db_press_5rm": {"weight_kg": 34.0, "reps": 5, "rir": 1},
                "pullups_max": {"reps": 9},
                "run_tt_30": {
                    "last20_avg_hr": 169,
                    "last20_pace_s_per_mi": 462,
                    "first10_pace_s_per_mi": 470,
                },
                "run_submax_drift": {"avg_hr": 141, "avg_pace_s_per_mi": 600},
                "row_2k": {"time_s": 425},
            },
            "end_B1": {
                "broad_jump": {"attempts": [240, 244, 243]},
                "hinge_rm": {"weight_kg": 172.5, "reps": 5, "rir": 1},
                "squat_rm": {"weight_kg": 125.0, "reps": 5, "rir": 1},
                "db_press_5rm": {"weight_kg": 36.0, "reps": 5, "rir": 1},
                "pullups_max": {"reps": 12},
                "run_tt_30": {
                    "last20_avg_hr": 171,
                    "last20_pace_s_per_mi": 451,
                    "first10_pace_s_per_mi": 458,
                },
                "row_2k": {"time_s": 414},
            },
        },
        "chat": {
            "2026-12-12": "Finished the metcon: 5 rounds + 7 reps, wall balls unbroken, burpees slow, rpe 8",
            "2027-01-19": "Shoulder hurt during pressing, about 3/10",
            "2027-02-20": "Open 27.1 done: 212 reps, rpe 9.5. Toes to bar broke up a lot",
        },
        "macrofactor_targets": [
            {"from": "2026-09-01", "kcal_per_day": 3200},
            {"from": "2026-11-23", "kcal_per_day": 2800},
        ],
        "gear": [
            {"id": "g-1", "name": "Cushioned trainer", "start_miles": 180},
            {"id": "g-2", "name": "Firm trainer", "start_miles": 40},
        ],
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    recovery, sleep, cycles, wellness = whoop_and_wellness()
    hevy, whoop_w, activities = history()
    files = {
        "whoop.json": {"recovery": recovery, "sleep": sleep, "cycles": cycles, "workouts": whoop_w},
        "hevy.json": {"workouts": hevy},
        "intervals.json": {
            "activities": activities,
            "wellness": wellness,
            "gear": [
                {
                    "id": "g-1",
                    "name": "Cushioned trainer",
                    "type": "Shoes",
                    "distance": round(180 * 1609.344),
                    "retired": None,
                },
                {
                    "id": "g-2",
                    "name": "Firm trainer",
                    "type": "Shoes",
                    "distance": round(40 * 1609.344),
                    "retired": None,
                },
            ],
        },
        "open_meteo.json": weather(),
        "withings.json": withings(),
        "athlete_script.json": athlete_script(),
    }
    for name, data in files.items():
        with open(OUT / name, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        print(f"wrote {OUT / name} ({(OUT / name).stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
