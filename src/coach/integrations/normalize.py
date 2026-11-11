"""Raw API payload -> normalized models. Shared by mock and live clients, so fixtures exercise real code."""

import datetime as dt

from coach.engine.readiness import rpe_to_rir
from coach.engine.units import M_PER_MI
from coach.models import Checkin, DailyMetrics, Gear, SessionRecord, SetRecord
from coach.models.library import ExerciseLibrary


def _parse_ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _local(ts: dt.datetime) -> dt.datetime:
    from coach.clock import TZ

    if ts.tzinfo is None:
        return ts
    return ts.astimezone(TZ).replace(tzinfo=None)


# ---------------- Whoop (API v2) ----------------
def whoop_daily(recovery: list[dict], sleep: list[dict], cycles: list[dict]) -> list[DailyMetrics]:
    sleep_by_id = {s["id"]: s for s in sleep}
    cycles_by_id = {c["id"]: c for c in cycles}
    out = []
    for r in recovery:
        if r.get("score_state") != "SCORED" or not r.get("score"):
            continue
        day = _local(_parse_ts(r["created_at"])).date()
        sc = r["score"]
        s = sleep_by_id.get(r.get("sleep_id"))
        sleep_h = perf = None
        if s and s.get("score"):
            st = s["score"]["stage_summary"]
            sleep_h = round((st["total_in_bed_time_milli"] - st["total_awake_time_milli"]) / 3_600_000, 2)
            perf = s["score"].get("sleep_performance_percentage")
        # day strain belongs to the previous (completed) cycle; today's is still accruing
        c = cycles_by_id.get(r.get("cycle_id"))
        strain = c["score"]["strain"] if c and c.get("score") else None
        out.append(
            DailyMetrics(
                date=day,
                recovery_score=sc.get("recovery_score"),
                hrv_rmssd_ms=sc.get("hrv_rmssd_milli"),
                rhr_bpm=sc.get("resting_heart_rate"),
                sleep_hours=sleep_h,
                sleep_performance=perf,
                day_strain=strain,
                sources=["whoop"],
            )
        )
    return out


WHOOP_SPORT = {
    "running": "run",
    "weightlifting": "strength",
    "functional fitness": "metcon",
    "hiit": "metcon",
    "rowing": "row",
    "cycling": "bike",
    "walking": "walk",
    "skiing": "ski",
}


def whoop_workouts(raw: list[dict]) -> list[SessionRecord]:
    out = []
    for w in raw:
        if w.get("score_state") != "SCORED":
            continue
        start = _local(_parse_ts(w["start"]))
        end = _local(_parse_ts(w["end"]))
        sc = w["score"]
        z = sc.get("zone_durations", {})
        zones = [
            round(z.get(k, 0) / 60000, 1)
            for k in (
                "zone_zero_milli",
                "zone_one_milli",
                "zone_two_milli",
                "zone_three_milli",
                "zone_four_milli",
                "zone_five_milli",
            )
        ]
        out.append(
            SessionRecord(
                id=f"whoop:{w['id']}",
                date=start.date(),
                start=start,
                sport=WHOOP_SPORT.get(str(w.get("sport_name", "")).lower(), "other"),
                title=str(w.get("sport_name", "Workout")),
                duration_min=round((end - start).total_seconds() / 60, 1),
                strain=sc.get("strain"),
                kilojoule=sc.get("kilojoule"),
                avg_hr=sc.get("average_heart_rate"),
                max_hr=sc.get("max_heart_rate"),
                whoop_zone_minutes=zones,
                sources=["whoop"],
            )
        )
    return out


# ---------------- Hevy ----------------
def hevy_workouts(raw: list[dict], library: ExerciseLibrary) -> list[SessionRecord]:
    out = []
    for w in raw:
        start = _local(_parse_ts(w["start_time"]))
        end = _local(_parse_ts(w["end_time"]))
        sets = []
        for ex in w.get("exercises", []):
            match = None
            if ex.get("exercise_template_id"):
                match = next(
                    (
                        e
                        for e in library.exercises.values()
                        if e.hevy_template_id == ex["exercise_template_id"]
                    ),
                    None,
                )
            match = match or library.by_hevy_title(ex["title"])
            for s in ex.get("sets", []):
                st = s.get("type", "normal")
                sets.append(
                    SetRecord(
                        exercise_id=match.id if match else None,
                        exercise_name=ex["title"],
                        set_type=st if st in {"normal", "warmup", "failure", "dropset"} else "normal",
                        weight_kg=s.get("weight_kg"),
                        reps=s.get("reps"),
                        rpe=s.get("rpe"),
                        rir=rpe_to_rir(s.get("rpe")),
                        distance_m=s.get("distance_meters"),
                        duration_s=s.get("duration_seconds"),
                    )
                )
        notes = " ".join(
            x
            for x in [w.get("description") or "", *(e.get("notes") or "" for e in w.get("exercises", []))]
            if x
        )
        title = w.get("title", "Workout")
        sport = "metcon" if any(k in title.lower() for k in ("metcon", "hyrox", "open")) else "strength"
        out.append(
            SessionRecord(
                id=f"hevy:{w['id']}",
                date=start.date(),
                start=start,
                sport=sport,
                title=title,
                duration_min=round((end - start).total_seconds() / 60, 1),
                sets=sets,
                notes_untrusted=notes or None,
                sources=["hevy"],
            )
        )
    return out


# ---------------- Intervals.icu ----------------
INTERVALS_SPORT = {
    "run": "run",
    "virtualrun": "run",
    "rowing": "row",
    "ride": "bike",
    "virtualride": "bike",
    "walk": "walk",
    "weighttraining": "strength",
    "workout": "hiit",
    "nordicski": "ski",
}


def intervals_activities(raw: list[dict]) -> list[SessionRecord]:
    out = []
    for a in raw:
        start = dt.datetime.fromisoformat(a["start_date_local"])
        sport = INTERVALS_SPORT.get(str(a.get("type", "")).lower(), "other")
        dist_m = a.get("distance") or 0
        moving = a.get("moving_time") or 0
        miles = dist_m / M_PER_MI if dist_m else None
        pace = moving / miles if miles else None
        last20_hr = last20_pace = None
        laps = a.get("laps") or []
        if laps:
            tail = [lap for lap in laps if lap.get("start_offset_s", 0) >= 600]
            if tail:
                secs = sum(lap["moving_time"] for lap in tail)
                dist = sum(lap["distance"] for lap in tail)
                last20_hr = sum(lap["average_heartrate"] * lap["moving_time"] for lap in tail) / secs
                last20_pace = secs / (dist / M_PER_MI)
        cadence = a.get("average_cadence")
        if cadence and sport == "run" and cadence < 120:
            cadence *= 2  # Garmin reports steps per minute per leg on some exports
        out.append(
            SessionRecord(
                id=f"intervals:{a['id']}",
                date=start.date(),
                start=start,
                sport=sport,
                title=a.get("name") or a.get("type", "Activity"),
                duration_min=round(moving / 60, 1),
                avg_hr=a.get("average_heartrate"),
                max_hr=a.get("max_heartrate"),
                distance_mi=round(miles, 2) if miles else None,
                avg_pace_s_per_mi=round(pace, 1) if pace else None,
                last20_avg_hr=round(last20_hr, 1) if last20_hr else None,
                last20_pace_s_per_mi=round(last20_pace, 1) if last20_pace else None,
                cadence_spm=cadence,
                gct_ms=a.get("avg_ground_contact_time"),
                gct_balance_left_pct=a.get("avg_gct_balance"),
                vertical_osc_cm=a.get("avg_vertical_oscillation"),
                gear_id=(a.get("gear") or {}).get("id"),
                training_load=a.get("icu_training_load"),
                notes_untrusted=a.get("description"),
                sources=["intervals"],
            )
        )
    return out


DEFAULT_CHECKIN_FIELDS = {
    "SessionRPE": "session_rpe",
    "Enjoyment": "enjoyment",
    "Soreness": "soreness",
    "BarSpeed": "bar_speed_mps",
}


def checkin_fields(cfg=None) -> tuple[dict[str, str], dict[str, str]]:
    """(Intervals field -> joint region, Intervals field -> Checkin field) from config/athlete_context.json checkin."""
    if cfg is None:
        from coach.config import load_config

        cfg = load_config()
    ck = cfg.profile.checkin
    joints = {spec.intervals_field: region for region, spec in ck.regions.items() if spec.intervals_field}
    return joints, {**DEFAULT_CHECKIN_FIELDS, **ck.intervals_fields}


def intervals_wellness(raw: list[dict], cfg=None) -> tuple[list[DailyMetrics], list[Checkin]]:
    joint_fields, other_fields = checkin_fields(cfg)
    metrics, checkins = [], []
    for w in raw:
        day = dt.date.fromisoformat(w["id"])
        metrics.append(
            DailyMetrics(
                date=day,
                ctl=w.get("ctl"),
                atl=w.get("atl"),
                kcal=w.get("kcalConsumed"),
                protein_g=w.get("protein"),
                carbs_g=w.get("carbohydrates"),
                fat_g=w.get("fatTotal"),
                # Whoop via Intervals.icu's own Whoop connection (backup only; sync keeps these out of git)
                recovery_score=w.get("readiness"),
                hrv_rmssd_ms=w.get("hrv"),
                rhr_bpm=w.get("restingHR"),
                sleep_hours=round(w["sleepSecs"] / 3600, 2) if w.get("sleepSecs") else None,
                sleep_performance=w.get("sleepScore"),
                weight_kg=w.get("weight"),  # scale weigh-ins (Apple Health -> HealthFit -> Intervals.icu)
                body_fat_pct=w.get("bodyFat"),
                sources=["intervals"],
            )
        )
        fields = {dst: w[src] for src, dst in other_fields.items() if w.get(src) is not None}
        joints = {region: int(w[src]) for src, region in joint_fields.items() if w.get(src) is not None}
        if fields or joints:
            checkins.append(Checkin(date=day, source="intervals", joints=joints, **fields))
    return metrics, checkins


def intervals_gear(raw: list[dict]) -> list[Gear]:
    return [
        Gear(
            id=g["id"],
            name=g["name"],
            distance_mi=round((g.get("distance") or 0) / M_PER_MI, 1),
            retired=bool(g.get("retired")),
            kind="shoe" if str(g.get("type", "")).lower().startswith("shoe") else "other",
        )
        for g in raw
    ]


# ---------------- Open-Meteo ----------------
def open_meteo_hourly(raw: dict) -> list[dict]:
    h = raw["hourly"]
    return [
        {"time": dt.datetime.fromisoformat(t), "temp_c": tc, "dew_point_c": dp, "precip_mm": pr or 0.0}
        for t, tc, dp, pr in zip(
            h["time"], h["temperature_2m"], h["dew_point_2m"], h["precipitation"], strict=False
        )
    ]
