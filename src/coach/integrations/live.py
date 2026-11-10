"""Live API clients (Phase 2). Credentials are injected by the cloud environment's proxy as network secrets,
so these clients send no keys themselves; for local testing, optional env vars are honoured.

Endpoints and payload shapes follow the public docs as of writing and MUST be verified in Phase 2:
- Hevy: https://api.hevyapp.com/docs (GET /v1/workouts, POST /v1/routines, PUT /v1/routines/{id})
- Intervals.icu: /api/v1/athlete/0/{activities,wellness,gear,events/bulk}  (athlete 0 = the key's owner)
- Whoop v2 + Withings: via the token broker (WHOOP_BROKER_URL), which holds the rotating refresh tokens
- Open-Meteo: /v1/forecast (no auth)
"""

import base64
import datetime as dt
import json
import os
import urllib.parse
import urllib.request

from coach.config import load_config
from coach.integrations import normalize as N
from coach.integrations.base import (
    BodyCompSource,
    HevySource,
    IntervalsSource,
    NutritionSource,
    Sources,
    WeatherSource,
    WhoopSource,
)

TIMEOUT = 30


def _request(method: str, url: str, headers: dict | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Accept": "application/json", **(headers or {})}
    )
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - fixed https hosts
        raw = resp.read()
        return json.loads(raw) if raw else None


class LiveWhoop(WhoopSource):
    def __init__(self):
        self.base = os.environ.get("WHOOP_BROKER_URL", "").rstrip("/")
        key = os.environ.get("WHOOP_BROKER_KEY")
        self.headers = {"X-Broker-Key": key} if key else {}

    def _get(self, path: str, start: dt.date, end: dt.date) -> list[dict]:
        if not self.base:
            raise RuntimeError("WHOOP_BROKER_URL not configured (Phase 2: deploy the token broker)")
        q = urllib.parse.urlencode(
            {"start": f"{start}T00:00:00Z", "end": f"{end + dt.timedelta(days=1)}T00:00:00Z"}
        )
        records: list[dict] = []
        url = f"{self.base}{path}?{q}"
        while url:
            page = _request("GET", url, self.headers)
            records.extend(page.get("records", []))
            token = page.get("next_token")
            url = f"{self.base}{path}?{q}&nextToken={token}" if token else ""
        return records

    def daily(self, start, end):
        return N.whoop_daily(
            self._get("/v2/recovery", start, end),
            self._get("/v2/activity/sleep", start, end),
            self._get("/v2/cycle", start, end),
        )

    def workouts(self, start, end):
        return N.whoop_workouts(self._get("/v2/activity/workout", start, end))


class LiveHevy(HevySource):
    BASE = "https://api.hevyapp.com/v1"

    def __init__(self):
        key = os.environ.get("HEVY_API_KEY")
        self.headers = {"api-key": key} if key else {}

    def workouts(self, start, end):
        out, page = [], 1
        while True:
            data = _request("GET", f"{self.BASE}/workouts?page={page}&pageSize=10", self.headers)
            ws = data.get("workouts", [])
            out.extend(ws)
            if page >= data.get("page_count", 1) or not ws:
                break
            if ws and dt.datetime.fromisoformat(ws[-1]["start_time"].replace("Z", "+00:00")).date() < start:
                break
            page += 1
        recs = N.hevy_workouts(out, load_config().library)
        return [r for r in recs if start <= r.date <= end]

    def upsert_routine(self, routine, routine_id=None):
        if routine_id:
            res = _request("PUT", f"{self.BASE}/routines/{routine_id}", self.headers, {"routine": routine})
        else:
            res = _request("POST", f"{self.BASE}/routines", self.headers, {"routine": routine})
        r = res.get("routine", res) if isinstance(res, dict) else {}
        if isinstance(r, list):
            r = r[0]
        return str(r.get("id", routine_id or ""))


class LiveIntervals(IntervalsSource):
    BASE = "https://intervals.icu/api/v1/athlete/0"

    def __init__(self):
        key = os.environ.get("INTERVALS_API_KEY")
        self.headers = {}
        if key:
            self.headers["Authorization"] = "Basic " + base64.b64encode(f"API_KEY:{key}".encode()).decode()

    def activities(self, start, end):
        return N.intervals_activities(
            _request("GET", f"{self.BASE}/activities?oldest={start}&newest={end}", self.headers)
        )

    def wellness(self, start, end):
        return N.intervals_wellness(
            _request("GET", f"{self.BASE}/wellness?oldest={start}&newest={end}", self.headers)
        )

    def gear(self):
        return N.intervals_gear(_request("GET", f"{self.BASE}/gear", self.headers))

    def upsert_events(self, events):
        res = _request("POST", f"{self.BASE}/events/bulk?upsert=true", self.headers, events)  # type: ignore[arg-type]
        return [str(e.get("id")) for e in (res or [])]


class LiveWeather(WeatherSource):
    def hourly(self, start, end):
        home = load_config().profile.identity.home
        q = urllib.parse.urlencode(
            {
                "latitude": home.lat,
                "longitude": home.lon,
                "hourly": "temperature_2m,dew_point_2m,precipitation",
                "timezone": "America/New_York",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            }
        )
        return N.open_meteo_hourly(_request("GET", f"https://api.open-meteo.com/v1/forecast?{q}"))


class LiveWithings(BodyCompSource):
    def __init__(self):
        self.base = os.environ.get("WHOOP_BROKER_URL", "").rstrip("/")
        key = os.environ.get("WHOOP_BROKER_KEY")
        self.headers = {"X-Broker-Key": key} if key else {}

    def measurements(self, start, end):
        if not self.base:
            raise RuntimeError("token broker not configured (Withings shares the Whoop broker)")
        s = int(dt.datetime(start.year, start.month, start.day, tzinfo=dt.UTC).timestamp())
        e = int(dt.datetime(end.year, end.month, end.day, 23, 59, tzinfo=dt.UTC).timestamp())
        return N.withings_measurements(
            _request(
                "GET", f"{self.base}/withings/measure?meastypes=1,6,8&startdate={s}&enddate={e}", self.headers
            )
        )


class LiveNutrition(NutritionSource):
    """MacroFactor -> Apple Health -> Intervals.icu wellness (Phase 3). Weekly target is told to the coach in chat."""

    def daily(self, start, end):
        metrics, _ = LiveIntervals().wellness(start, end)
        return [m for m in metrics if m.kcal is not None]

    def weekly_target_kcal(self, week_start):
        from coach.state import State

        data = State().read_json("macrofactor.json") or {}
        return data.get("weekly_kcal")


def live_sources() -> Sources:
    return Sources(
        whoop=LiveWhoop(),
        hevy=LiveHevy(),
        intervals=LiveIntervals(),
        weather=LiveWeather(),
        withings=LiveWithings(),
        nutrition=LiveNutrition(),
        mock=False,
    )
