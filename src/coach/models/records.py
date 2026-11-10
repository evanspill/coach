"""Day records, readiness, proposals, movement readiness and test results."""

import datetime as dt
from typing import Any, Literal

from pydantic import Field

from coach.models.common import Model
from coach.models.plans import Session

ReadinessState = Literal["green", "yellow", "red", "unknown"]


class HrvTrend(Model):
    mean7_ln: float | None = None
    baseline_ln: float | None = None
    lower_band: float | None = None
    upper_band: float | None = None
    below_days: int = 0


class JointFlag(Model):
    region: str
    since: dt.date
    restricted_tags: list[str]
    reason: str


class Readiness(Model):
    date: dt.date
    state: ReadinessState
    reasons: list[str]
    recovery_score: float | None = None
    hrv: HrvTrend = HrvTrend()
    rhr_delta: float | None = None
    joints: dict[str, int] = Field(default_factory=dict)
    joint_flags: list[JointFlag] = Field(default_factory=list)
    sustained_red: bool = False
    data_missing: list[str] = Field(default_factory=list)


class WeatherCall(Model):
    date: dt.date
    temp_f: float | None
    dew_point_f: float | None
    heat_sum: float | None
    tier: Literal["normal", "slow", "indoor"]
    icy: bool = False
    daylight: bool = True
    sunrise: str | None = None
    sunset: str | None = None
    pace_adjust_s_per_mi: tuple[int, int] = (0, 0)
    decision: str
    reasons: list[str] = Field(default_factory=list)


class NutritionDay(Model):
    date: dt.date
    carb_tier: Literal["high", "moderate", "low"]
    kcal: int
    protein_g: int
    fat_g: int
    carbs_g: int
    scaled: bool = False
    peri_workout: str = ""
    note: str = ""


class Change(Model):
    what: str
    why: str
    kind: Literal["small", "session_type_swap", "deload_pulled_forward", "replan"] = "small"


class DayRecord(Model):
    date: dt.date
    status: Literal["complete", "waiting_for_recovery", "paused", "stopped_red_flag"]
    readiness: Readiness | None = None
    weather: WeatherCall | None = None
    planned_session_id: str | None = None
    session: Session | None = None
    changes: list[Change] = Field(default_factory=list)
    recovery_prescription: list[str] = Field(default_factory=list)
    nutrition: NutritionDay | None = None
    fueling_cue: str = ""
    gear_alerts: list[str] = Field(default_factory=list)
    pushed: dict[str, Any] | None = None
    handoffs: list[str] = Field(default_factory=list)
    approvals_pending: list[str] = Field(default_factory=list)
    stale_sources: list[str] = Field(default_factory=list)
    generated_by: Literal["claude", "fallback"] = "claude"
    notification: str = ""


class RungEvent(Model):
    date: dt.date
    from_rung: int
    to_rung: int
    reason: str
    evidence: int = 0  # clean exposures at the old rung when the move happened


class Exposure(Model):
    date: dt.date
    rung: int
    session_pain: float | None = None
    stiffness_up: bool = False
    clean: bool = True


class FamilyState(Model):
    family: str
    rung: int
    exposures: list[Exposure] = Field(default_factory=list)  # exposures at the current rung
    history: list[RungEvent] = Field(default_factory=list)
    hold_until: dt.date | None = None  # regression hold (e.g. region flag: one week)
    eccentric_tempo_until: dt.date | None = None  # pain rule: 3 s eccentric, -15% load for 2 weeks

    def clean_exposures(self) -> int:
        return sum(1 for e in self.exposures if e.clean and e.rung == self.rung)


class MovementReadiness(Model):
    updated: dt.date
    families: dict[str, FamilyState]
    note: str = ""

    def rung(self, family: str) -> int:
        fs = self.families.get(family)
        return fs.rung if fs else 0


class TestResult(Model):
    test_id: str
    date: dt.date
    variant: str | None = None
    value: float
    unit: str
    comparable_value: float | None = None  # converted to the reference variant
    details: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class TestSet(Model):
    block_id: str
    phase: Literal["baseline", "start", "end"]
    results: list[TestResult] = Field(default_factory=list)
    scheduled: dict[str, dt.date] = Field(default_factory=dict)

    def get(self, test_id: str) -> TestResult | None:
        for r in self.results:
            if r.test_id == test_id:
                return r
        return None


class ProposalEvent(Model):
    at: dt.date
    status: str
    note: str = ""


class Proposal(Model):
    id: str
    kind: Literal[
        "weekly_plan",
        "block_goal",
        "baseline_battery",
        "replan",
        "early_deload",
        "calibration",
        "science_trial",
        "race_plan",
        "config_change",
        "session_swap",
        "calorie_phase",
    ]
    created: dt.date
    created_by: str  # skill name
    title: str
    what: str
    why: str
    before: Any = None
    after: Any = None
    target_path: str | None = None  # state file that becomes active on approval
    payload: dict[str, Any] | None = None  # e.g. config patch
    status: Literal["pending", "approved", "rejected", "applied", "superseded"] = "pending"
    history: list[ProposalEvent] = Field(default_factory=list)
