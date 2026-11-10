"""Weather routing: heat tiers (temp F + dew point F), ice, and daylight (computed sunrise/sunset)."""

import datetime as dt
import math
from zoneinfo import ZoneInfo

from coach.engine.units import c_to_f
from coach.models import WeatherCall
from coach.models.profile import WeatherRules


def sun_times(
    day: dt.date, lat: float, lon: float, tz: str = "America/New_York"
) -> tuple[dt.datetime, dt.datetime]:
    """NOAA-style sunrise/sunset approximation (accurate to a few minutes). Returns local datetimes."""
    n = day.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    lat_r = math.radians(lat)
    cos_ha = math.cos(math.radians(90.833)) / (math.cos(lat_r) * math.cos(decl)) - math.tan(lat_r) * math.tan(
        decl
    )
    cos_ha = max(-1.0, min(1.0, cos_ha))
    ha = math.degrees(math.acos(cos_ha))
    sunrise_utc_min = 720 - 4 * (lon + ha) - eqtime
    sunset_utc_min = 720 - 4 * (lon - ha) - eqtime
    base = dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC)
    zone = ZoneInfo(tz)
    rise = (base + dt.timedelta(minutes=sunrise_utc_min)).astimezone(zone)
    sset = (base + dt.timedelta(minutes=sunset_utc_min)).astimezone(zone)
    return rise, sset


def in_daylight(day: dt.date, start: str, minutes: int, lat: float, lon: float) -> bool:
    rise, sset = sun_times(day, lat, lon)
    h, m = (int(x) for x in start.split(":"))
    begin = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=rise.tzinfo)
    end = begin + dt.timedelta(minutes=minutes)
    return begin >= rise and end <= sset


def weather_call(
    day: dt.date,
    hourly: list[dict],
    rules: WeatherRules,
    lat: float,
    lon: float,
    start: str = "09:30",
    minutes: int = 60,
) -> WeatherCall:
    """hourly: [{'time': datetime, 'temp_c', 'dew_point_c', 'precip_mm'}] for the day (and the previous 12 h)."""
    h = int(start.split(":")[0])
    rise, sset = sun_times(day, lat, lon)
    daylight = in_daylight(day, start, minutes, lat, lon)
    target = [r for r in hourly if r["time"].date() == day and r["time"].hour in (h, h + 1)]
    reasons: list[str] = []
    if not target:
        return WeatherCall(
            date=day,
            temp_f=None,
            dew_point_f=None,
            heat_sum=None,
            tier="normal",
            daylight=daylight,
            sunrise=rise.strftime("%H:%M"),
            sunset=sset.strftime("%H:%M"),
            decision="no forecast available: run as planned, check conditions at the door",
            reasons=["weather data missing"],
        )
    temp_c = max(r["temp_c"] for r in target)
    dew_c = max(r["dew_point_c"] for r in target)
    temp_f, dew_f = c_to_f(temp_c), c_to_f(dew_c)
    heat_sum = temp_f + dew_f
    start_dt = target[0]["time"]
    prior = [
        r for r in hourly if start_dt - dt.timedelta(hours=rules.icy_precip_hours) <= r["time"] <= start_dt
    ]
    precip_prior = sum(r.get("precip_mm", 0.0) for r in prior)
    min_temp_prior = min((r["temp_c"] for r in prior), default=temp_c)
    icy = min(temp_c, min_temp_prior) <= rules.icy_temp_c and precip_prior > 0.2

    tier = "normal"
    adjust = (0, 0)
    if heat_sum > rules.indoor_sum_f:
        tier = "indoor"
        reasons.append(
            f"heat {temp_f:.0f}F + dew point {dew_f:.0f}F = {heat_sum:.0f} (> {rules.indoor_sum_f:.0f})"
        )
    elif heat_sum >= rules.slow_sum_f:
        tier = "slow"
        adjust = tuple(rules.slow_pace_s_per_mi)  # type: ignore[assignment]
        reasons.append(f"heat sum {heat_sum:.0f}: slow {adjust[0]}-{adjust[1]} s/mi and add sodium")
    if icy:
        tier = "indoor"
        reasons.append(
            f"icy: <= {rules.icy_temp_c:.0f}C with {precip_prior:.1f} mm precipitation in prior 12 h"
        )
    if not daylight:
        tier = "indoor"
        reasons.append("outside daylight")
    decision = {
        "normal": "outdoor OK",
        "slow": "outdoor OK, slower paces + extra sodium",
        "indoor": "quality and long work moves indoors (treadmill or erg)",
    }[tier]
    return WeatherCall(
        date=day,
        temp_f=round(temp_f, 1),
        dew_point_f=round(dew_f, 1),
        heat_sum=round(heat_sum, 1),
        tier=tier,  # type: ignore[arg-type]
        icy=icy,
        daylight=daylight,
        sunrise=rise.strftime("%H:%M"),
        sunset=sset.strftime("%H:%M"),
        pace_adjust_s_per_mi=adjust,
        decision=decision,
        reasons=reasons or [f"{temp_f:.0f}F, dew point {dew_f:.0f}F"],
    )
