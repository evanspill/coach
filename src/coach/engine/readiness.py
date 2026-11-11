"""Daily readiness: Whoop recovery + HRV trend + RHR + joint check-ins. The most restrictive state wins."""

import datetime as dt
import math
import statistics
from collections.abc import Mapping

from coach.models import Checkin, DailyMetrics, Readiness
from coach.models.profile import Thresholds
from coach.models.records import HrvTrend, JointFlag

ORDER = {"unknown": -1, "green": 0, "yellow": 1, "red": 2}


def rpe_to_rir(rpe: float | None) -> float | None:
    """Hevy logs RPE; RIR = 10 - RPE (clamped to 0..10)."""
    if rpe is None:
        return None
    return max(0.0, min(10.0, 10.0 - rpe))


def _by_date(metrics: list[DailyMetrics]) -> dict[dt.date, DailyMetrics]:
    return {m.date: m for m in metrics}


def hrv_trend_for(day: dt.date, by_date: dict[dt.date, DailyMetrics], th: Thresholds) -> HrvTrend:
    """7-day mean ln(rMSSD) vs 60-day baseline +/- SWC (0.5 SD of the daily ln values)."""
    week = [
        math.log(m.hrv_rmssd_ms)
        for i in range(th.hrv_trend_days)
        if (m := by_date.get(day - dt.timedelta(days=i))) and m.hrv_rmssd_ms
    ]
    base = [
        math.log(m.hrv_rmssd_ms)
        for i in range(th.hrv_baseline_days)
        if (m := by_date.get(day - dt.timedelta(days=i))) and m.hrv_rmssd_ms
    ]
    if len(week) < 3 or len(base) < 14:
        return HrvTrend()
    mean7 = statistics.fmean(week)
    bmean = statistics.fmean(base)
    sd = statistics.pstdev(base)
    swc = th.hrv_swc_sd * sd
    return HrvTrend(
        mean7_ln=round(mean7, 4),
        baseline_ln=round(bmean, 4),
        lower_band=round(bmean - swc, 4),
        upper_band=round(bmean + swc, 4),
    )


def hrv_below_days(
    day: dt.date, by_date: dict[dt.date, DailyMetrics], th: Thresholds, max_look: int = 10
) -> int:
    count = 0
    for i in range(max_look):
        t = hrv_trend_for(day - dt.timedelta(days=i), by_date, th)
        if t.mean7_ln is None or t.lower_band is None or t.mean7_ln >= t.lower_band:
            break
        count += 1
    return count


def rhr_delta(day: dt.date, by_date: dict[dt.date, DailyMetrics], th: Thresholds) -> float | None:
    week = [m.rhr_bpm for i in range(7) if (m := by_date.get(day - dt.timedelta(days=i))) and m.rhr_bpm]
    base = [
        m.rhr_bpm
        for i in range(th.rhr_baseline_days)
        if (m := by_date.get(day - dt.timedelta(days=i))) and m.rhr_bpm
    ]
    if len(week) < 3 or len(base) < 14:
        return None
    return round(statistics.fmean(week) - statistics.fmean(base), 1)


def joint_flags(
    checkins: list[Checkin], day: dt.date, restricted: dict[str, list[str]], th: Thresholds
) -> list[JointFlag]:
    """A region rated >= flag rating on N consecutive check-ins is flagged until it is <= 2 on N consecutive."""
    ordered = sorted((c for c in checkins if c.date <= day), key=lambda c: c.date)
    flags: list[JointFlag] = []
    regions = sorted({r for c in ordered for r in c.joints})
    for region in regions:
        ratings = [(c.date, c.joints[region]) for c in ordered if region in c.joints]
        active_since: dt.date | None = None
        run_hi = run_lo = 0
        for date, value in ratings:
            if value >= th.joint_flag_rating:
                run_hi += 1
                run_lo = 0
                if run_hi >= th.joint_flag_consecutive and active_since is None:
                    active_since = date
            else:
                run_hi = 0
                run_lo += 1
                if active_since is not None and run_lo >= th.joint_flag_consecutive:
                    active_since = None
        if active_since is not None:
            flags.append(
                JointFlag(
                    region=region,
                    since=active_since,
                    restricted_tags=restricted.get(region, []),
                    reason=f"{region.replace('_', '/')} rated >= {th.joint_flag_rating} on "
                    f"{th.joint_flag_consecutive} consecutive check-ins",
                )
            )
    return flags


def _latest_checkins(checkins: list[Checkin], day: dt.date, n: int = 2) -> list[Checkin]:
    return sorted(
        (c for c in checkins if c.date <= day and c.date >= day - dt.timedelta(days=4)), key=lambda c: c.date
    )[-n:]


def compute_readiness(
    day: dt.date,
    metrics: list[DailyMetrics],
    checkins: list[Checkin],
    th: Thresholds,
    restricted_tags: dict[str, list[str]] | None = None,
    prior_states: Mapping[dt.date, str] | None = None,
) -> Readiness:
    by_date = _by_date(metrics)
    today = by_date.get(day)
    reasons_by_state: dict[str, list[str]] = {"green": [], "yellow": [], "red": []}
    missing: list[str] = []

    rec = today.recovery_score if today else None
    if rec is None:
        missing.append("whoop_recovery")
    yesterday = by_date.get(day - dt.timedelta(days=1))
    rec_y = yesterday.recovery_score if yesterday else None

    trend = hrv_trend_for(day, by_date, th)
    below = hrv_below_days(day, by_date, th) if trend.mean7_ln is not None else 0
    trend.below_days = below
    hrv_below_today = below >= 1
    rdelta = rhr_delta(day, by_date, th)

    latest = _latest_checkins(checkins, day, 2)
    joints = dict(latest[-1].joints) if latest else {}
    flags = joint_flags(checkins, day, restricted_tags or {}, th)

    # --- red ---
    if rec is not None and rec <= th.recovery_red_max and rec_y is not None and rec_y <= th.recovery_red_max:
        reasons_by_state["red"].append(f"recovery <= {th.recovery_red_max} two days running")
    if below >= th.hrv_below_days_red:
        reasons_by_state["red"].append(f"HRV trend below baseline band {below} days")
    if rdelta is not None and rdelta > th.rhr_red_delta:
        reasons_by_state["red"].append(f"resting HR more than {th.rhr_red_delta} bpm above baseline")
    for region, v in joints.items():
        if v >= th.joint_red:
            reasons_by_state["red"].append(f"{region.replace('_', '/')} rated {v}/5")
    if len(latest) == 2:
        for region in sorted(set(latest[0].joints) | set(latest[1].joints)):
            a, b = latest[0].joints.get(region), latest[1].joints.get(region)
            if a is not None and b is not None and a >= th.joint_flag_rating and b >= th.joint_flag_rating:
                reasons_by_state["red"].append(
                    f"{region.replace('_', '/')} >= {th.joint_flag_rating} on 2 check-ins"
                )

    # --- yellow ---
    if rec is not None and rec <= th.recovery_red_max and not reasons_by_state["red"]:
        reasons_by_state["yellow"].append(f"recovery <= {th.recovery_red_max} (single low day)")
    if rec is not None and th.recovery_red_max < rec < th.recovery_green_min and hrv_below_today:
        reasons_by_state["yellow"].append(f"recovery under {th.recovery_green_min} with HRV trend below band")
    if below >= th.hrv_below_days_yellow and below < th.hrv_below_days_red:
        reasons_by_state["yellow"].append(f"HRV trend below band {below} days")
    if rdelta is not None and th.rhr_yellow_delta <= rdelta <= th.rhr_red_delta:
        reasons_by_state["yellow"].append(
            f"resting HR {th.rhr_yellow_delta}-{th.rhr_red_delta} bpm above baseline"
        )
    for region, v in joints.items():
        if th.joint_yellow <= v < th.joint_red:
            reasons_by_state["yellow"].append(f"{region.replace('_', '/')} rated {v}/5")

    if rec is None and not reasons_by_state["red"] and not reasons_by_state["yellow"]:
        state = "unknown"
        reasons = ["today's Whoop recovery not available yet"]
    elif reasons_by_state["red"]:
        state, reasons = "red", reasons_by_state["red"]
    elif reasons_by_state["yellow"]:
        state, reasons = "yellow", reasons_by_state["yellow"]
    else:
        state = "green"
        # Reasons name the rule, never Whoop's values: they are stored and sent in notifications (DECISIONS 73)
        if rec is not None and rec >= th.recovery_green_min:
            reasons = [f"recovery >= {th.recovery_green_min}"]
        else:
            reasons = [f"recovery under {th.recovery_green_min} with HRV trend in band"]

    sustained = False
    if prior_states is not None:
        window = [prior_states.get(day - dt.timedelta(days=i)) for i in range(1, th.sustained_red_window)]
        reds = sum(1 for s in window if s == "red") + (1 if state == "red" else 0)
        sustained = state == "red" and reds >= th.sustained_red_days
    if any(v >= th.joint_red for v in joints.values()):
        sustained = True  # a joint >= 4 triggers the reactive-deload path immediately

    return Readiness(
        date=day,
        state=state,
        reasons=reasons,
        recovery_score=rec,
        hrv=trend,
        rhr_delta=rdelta,
        joints=joints,
        joint_flags=flags,
        sustained_red=sustained,
        data_missing=missing,
    )


def most_restrictive(*states: str) -> str:
    return max(states, key=lambda s: ORDER.get(s, -1))
