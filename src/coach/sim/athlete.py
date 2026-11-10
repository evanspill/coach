"""A simulated athlete: does (or skips) what the coach prescribed and logs it the way the real apps would
(raw Hevy / Intervals.icu / Whoop shapes), so the next morning's sync runs the real normalizers."""

import datetime as dt
import random

from coach.config import Config
from coach.engine.loads import e1rm as epley
from coach.engine.units import M_PER_MI
from coach.integrations.mock import MockWorld, add_session_record_raw
from coach.models import DayRecord, Session

TZ = "-05:00"


class SimAthlete:
    def __init__(self, world: MockWorld, cfg: Config, seed: int = 7):
        self.w = world
        self.cfg = cfg
        self.script = world.script
        self.rng = random.Random(seed)
        self.true_e1rm: dict[str, float] = {}
        self.n = 0
        self.missed = {dt.date.fromisoformat(d) for d in self.script.get("missed_dates", [])}
        self.skipped = {dt.date.fromisoformat(d) for d in self.script.get("skipped_sessions", [])}
        self.start: dt.date | None = None

    # ---- physiology ----
    def capacity(
        self, ex_id: str, prescribed_load: float | None, reps: int, rir: float, day: dt.date
    ) -> float | None:
        if ex_id not in self.true_e1rm:
            if prescribed_load is None:
                return None
            # first exposure: the coach's estimate was roughly right (within +/- 4%)
            self.true_e1rm[ex_id] = epley(prescribed_load, reps, rir) * (1 + self.rng.uniform(-0.04, 0.04))
        weeks = (day - (self.start or day)).days / 7
        return self.true_e1rm[ex_id] * (1 + 0.004 * weeks)

    def _phase(self, day: dt.date) -> str:
        from coach.store import Store

        macro = Store().macrocycle()
        if macro is None or day <= macro.baseline_end:
            return "baseline"
        block = macro.block_for(day)
        return f"end_{block.key}" if block else "baseline"

    # ---- logging ----
    def do_day(self, day: dt.date, rec: DayRecord | None) -> list[str]:
        self.start = self.start or day
        notes: list[str] = []
        s = rec.session if rec else None
        if s is None or s.type == "rest":
            return notes
        if day in self.missed:
            return [f"[athlete] missed {s.title} ({self.script.get('missed_reason', '')})"]
        if day in self.skipped and not s.tests and not s.key:
            return [f"[athlete] skipped {s.title}"]
        self.n += 1
        start = dt.datetime(day.year, day.month, day.day, *map(int, s.start_time.split(":"))) + dt.timedelta(
            minutes=5
        )
        state = rec.readiness.state if rec and rec.readiness else "green"
        rpe_add = 0.5 if state == "yellow" else 1.0 if state == "red" else 0.0
        dip = self.script.get("enjoyment_dip", {})
        in_dip = dip and dt.date.fromisoformat(dip["start"]) <= day <= dt.date.fromisoformat(dip["end"])
        if in_dip:
            rpe_add += dip.get("rpe_add", 0)
        results = self.script["test_results"].get(self._phase(day), {})
        lifts = self._lifts(s, day, results, rpe_add)
        runs = self._runs(s, day, start, results)
        minutes = s.expected_minutes or 45
        sport = (
            "Running"
            if runs and not lifts
            else (
                "Functional Fitness"
                if any(b.metcon for b in s.blocks)
                else "Walking"
                if s.type == "recovery"
                else "Weightlifting"
            )
        )
        if s.type == "recovery":
            minutes = 35
        avg_hr = {"Running": 148, "Functional Fitness": 142, "Walking": 98, "Weightlifting": 118}[sport]
        strain = {
            "run_long": 14.5,
            "run_quality": 15.5,
            "hyrox": 16.5,
            "test": 15.0,
            "competition": 17.0,
            "recovery": 5.5,
        }.get(s.type, 12.5)
        self._whoop(day, start, sport, minutes, avg_hr, strain)
        joints = self._checkin_note(day, s, state, in_dip)
        if lifts:
            self._hevy(day, start, s.title, minutes, lifts, joints)
        for act in runs:
            add_session_record_raw(self.w, "intervals", act)
        session_rpe = min(10, round((7.0 if s.key else 5.5) + rpe_add + self.rng.uniform(-0.5, 0.5), 1))
        enjoy = dip.get("enjoyment", 2) if in_dip else (4 if self.rng.random() < 0.7 else 3)
        add_session_record_raw(
            self.w, "wellness", {"id": day.isoformat(), "SessionRPE": session_rpe, "Enjoyment": enjoy}
        )
        notes.append(f"[athlete] did {s.title} (RPE {session_rpe})")
        return notes

    def _lifts(self, s: Session, day: dt.date, results: dict, rpe_add: float) -> list[dict]:
        lib = self.cfg.library
        out = []
        for b in s.blocks:
            if b.kind == "test" and b.test_id:
                out += self._test_sets(b.test_id, b.items, results)
                continue
            if b.kind not in {"strength", "hypertrophy", "power", "skill"}:
                continue
            for it in b.items:
                ex = lib.get(it.exercise_id)
                if ex is None:
                    continue
                sets = []
                for i in range(it.sets):
                    load = it.load_kg
                    reps = it.reps
                    rir = it.rir if it.rir is not None else 3
                    cap = (
                        self.capacity(ex.id, load, reps or 5, rir, day)
                        if (load and reps and ex.load_mode == "e1rm")
                        else None
                    )
                    if cap and load and reps:
                        true_rir = (cap / load - 1) * 30 - reps - 0.25 * i
                        true_rir = max(0.0, min(5.0, true_rir))
                        if true_rir < 0.5 and self.rng.random() < 0.5:
                            reps = max(1, reps - 1)
                        rpe = round(min(10, 10 - true_rir + rpe_add * 0.5) * 2) / 2
                    else:
                        rpe = round(min(10, 10 - rir + self.rng.uniform(-0.5, 0.5)) * 2) / 2
                    sets.append(
                        {
                            "index": i,
                            "type": "normal",
                            "weight_kg": load,
                            "reps": reps,
                            "rpe": rpe,
                            "duration_seconds": it.duration_s,
                            "distance_meters": it.distance_m,
                        }
                    )
                out.append({"title": ex.hevy_title or ex.name, "sets": sets})
        return out

    def _test_sets(self, test_id: str, items, results: dict) -> list[dict]:
        lib = self.cfg.library
        r = results.get(test_id)
        if r is None or not items:
            return []
        it = items[0]
        ex = lib.get(it.exercise_id)
        title = (ex.hevy_title or ex.name) if ex else it.exercise_id
        if test_id in {"hinge_rm", "squat_rm"}:
            factor = self.cfg.tests.tests[test_id].variants.get(it.exercise_id, 1.0)
            w = round(r["weight_kg"] / factor / 2.5) * 2.5
            warm = [
                {"index": i, "type": "warmup", "weight_kg": round(w * f / 2.5) * 2.5, "reps": 5}
                for i, f in enumerate((0.5, 0.7, 0.85))
            ]
            return [
                {
                    "title": title,
                    "sets": [
                        *warm,
                        {
                            "index": 3,
                            "type": "normal",
                            "weight_kg": w,
                            "reps": r["reps"],
                            "rpe": 10 - r["rir"],
                        },
                    ],
                }
            ]
        if test_id == "db_press_5rm":
            return [
                {
                    "title": title,
                    "sets": [
                        {
                            "index": 0,
                            "type": "normal",
                            "weight_kg": r["weight_kg"],
                            "reps": r["reps"],
                            "rpe": 10 - r["rir"],
                        }
                    ],
                }
            ]
        if test_id == "pullups_max":
            return [{"title": title, "sets": [{"index": 0, "type": "normal", "reps": r["reps"], "rpe": 10}]}]
        if test_id == "broad_jump":
            return [
                {
                    "title": title,
                    "sets": [
                        {"index": i, "type": "normal", "distance_meters": a / 100, "reps": 1}
                        for i, a in enumerate(r["attempts"])
                    ],
                }
            ]
        return []

    def _runs(self, s: Session, day: dt.date, start: dt.datetime, results: dict) -> list[dict]:
        acts = []
        tt = next(
            (b for b in s.blocks if b.kind == "test" and b.test_id in {"run_tt_30", "run_submax_drift"}), None
        )
        weeks = (day - (self.start or day)).days / 7
        cadence = min(176, 166 + 0.5 * weeks)
        if tt is not None:
            r = results.get(tt.test_id, {})
            if tt.test_id == "run_tt_30" and r:
                first_pace = r.get("first10_pace_s_per_mi", r["last20_pace_s_per_mi"] + 8)
                d1 = 600 / first_pace * M_PER_MI
                d2 = 1200 / r["last20_pace_s_per_mi"] * M_PER_MI
                wu = 2.0 * M_PER_MI
                laps = [
                    {
                        "start_offset_s": 0,
                        "moving_time": 600,
                        "distance": d1,
                        "average_heartrate": r["last20_avg_hr"] - 6,
                    },
                    {
                        "start_offset_s": 600,
                        "moving_time": 1200,
                        "distance": d2,
                        "average_heartrate": r["last20_avg_hr"],
                    },
                ]
                acts.append(
                    self._activity(
                        day,
                        start,
                        "Run",
                        "30-min time trial",
                        1800,
                        d1 + d2,
                        r["last20_avg_hr"] - 2,
                        cadence,
                        laps,
                    )
                )
                acts.append(
                    self._activity(
                        day, start - dt.timedelta(minutes=20), "Run", "TT warm-up", 1200, wu, 138, cadence
                    )
                )
            elif r:
                acts.append(
                    self._activity(
                        day,
                        start,
                        "Run",
                        "Submax drift run",
                        2400,
                        2400 / r["avg_pace_s_per_mi"] * M_PER_MI,
                        r["avg_hr"],
                        cadence,
                    )
                )
            return acts
        rowt = next((b for b in s.blocks if b.kind == "test" and b.test_id == "row_2k"), None)
        if rowt is not None and results.get("row_2k"):
            acts.append(
                self._activity(
                    day, start, "Rowing", "2k row test", results["row_2k"]["time_s"], 2000, 172, None
                )
            )
            return acts
        miles = secs = 0.0
        hrs = []
        for seg in s.run_segments():
            if seg.modality != "run" or seg.zone == "strides":
                continue
            pace = sum(seg.pace_s_per_mi) / 2 if seg.pace_s_per_mi else 600
            d = (
                seg.distance_mi * seg.reps
                if seg.distance_mi
                else (seg.duration_min or 0) * seg.reps * 60 / pace
            )
            miles += d
            secs += d * pace
            if seg.hr_bpm:
                hrs.append(sum(seg.hr_bpm) / 2)
        if miles > 0.2:
            name = "Treadmill run" if s.location == "gym" else s.title
            acts.append(
                self._activity(
                    day,
                    start,
                    "Run",
                    name,
                    secs,
                    miles * M_PER_MI,
                    sum(hrs) / len(hrs) if hrs else 140,
                    cadence,
                )
            )
            shoe = "g-2" if s.type in {"run_quality", "hyrox"} else "g-1"
            self.w.extra_gear_miles[shoe] = self.w.extra_gear_miles.get(shoe, 0) + miles
        return acts

    def _activity(self, day, start, typ, name, secs, meters, hr, cadence, laps=None) -> dict:
        self.n += 1
        a = {
            "id": f"sim-{day.isoformat()}-{self.n}",
            "start_date_local": start.isoformat(),
            "type": typ,
            "name": name,
            "moving_time": int(secs),
            "elapsed_time": int(secs) + 20,
            "distance": round(meters),
            "average_heartrate": round(hr),
            "max_heartrate": round(hr + 15),
            "icu_training_load": round(secs / 60 * 0.9),
            "gear": {"id": "g-1"} if typ == "Run" else None,
        }
        if cadence:
            a.update(
                {
                    "average_cadence": cadence / 2,
                    "avg_ground_contact_time": round(270 - (cadence - 166) * 2),
                    "avg_vertical_oscillation": 9.4,
                    "avg_gct_balance": 50.8,
                }
            )
        if laps:
            a["laps"] = laps
        return a

    def _whoop(self, day, start, sport, minutes, avg_hr, strain):
        self.n += 1
        total = minutes * 60000
        end = start + dt.timedelta(minutes=minutes)
        add_session_record_raw(
            self.w,
            "whoop",
            {
                "id": f"sim-w-{day.isoformat()}-{self.n}",
                "start": start.isoformat() + TZ,
                "end": end.isoformat() + TZ,
                "sport_name": sport,
                "score_state": "SCORED",
                "score": {
                    "strain": strain,
                    "average_heart_rate": avg_hr,
                    "max_heart_rate": avg_hr + 25,
                    "kilojoule": 1500,
                    "zone_durations": {
                        "zone_zero_milli": int(total * 0.05),
                        "zone_one_milli": int(total * 0.3),
                        "zone_two_milli": int(total * 0.35),
                        "zone_three_milli": int(total * 0.2),
                        "zone_four_milli": int(total * 0.08),
                        "zone_five_milli": int(total * 0.02),
                    },
                },
            },
        )

    def _checkin_note(self, day: dt.date, s: Session, state: str, in_dip: bool) -> str:
        parts = []
        pain = self.script.get("shoulder_session_pain", {}).get(day.isoformat())
        if pain:
            for fam, p in pain.items():
                parts.append(f"{fam} pain {p:g}/10")
        stiff = self.script.get("stiffness_up", {}).get(day.isoformat())
        if stiff:
            parts.append(f"{stiff[0]} stiffer this morning")
        bs = self.script.get("bar_speed", {}).get(day.isoformat())
        if bs:
            parts.append(f"bar speed {bs}")
        return ", ".join(parts)

    def _hevy(self, day, start, title, minutes, exercises, note):
        self.n += 1
        end = start + dt.timedelta(minutes=minutes)
        add_session_record_raw(
            self.w,
            "hevy",
            {
                "id": f"sim-h-{day.isoformat()}-{self.n}",
                "title": title,
                "description": note,
                "start_time": start.isoformat() + TZ,
                "end_time": end.isoformat() + TZ,
                "exercises": [
                    {
                        "index": i,
                        "title": e["title"],
                        "notes": "",
                        "exercise_template_id": None,
                        "sets": e["sets"],
                    }
                    for i, e in enumerate(exercises)
                ],
            },
        )
