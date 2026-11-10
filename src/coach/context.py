"""Everything a skill needs to know about 'now', assembled from state + config (read-only)."""

import datetime as dt
import statistics
from dataclasses import dataclass, field

from coach import clock
from coach.config import Config, load_config
from coach.engine import movement as mv
from coach.engine.paces import Zones
from coach.engine.readiness import compute_readiness
from coach.models import (
    BlockOutline,
    MacroBlock,
    Macrocycle,
    MovementReadiness,
    Readiness,
    WeekPlan,
    WeekTarget,
)
from coach.state import State
from coach.validator import ValidationContext

NON_NORMAL_WEEKS = {"deload", "transition", "taper", "reset"}


@dataclass
class Context:
    cfg: Config
    state: State
    today: dt.date
    macro: Macrocycle | None
    block: MacroBlock | None
    in_baseline: bool
    outline: BlockOutline | None
    week_target: WeekTarget | None
    week_index: int
    movement: MovementReadiness
    zones: Zones
    health: dict
    _readiness: dict[dt.date, Readiness] = field(default_factory=dict)

    @property
    def block_id(self) -> str:
        if self.in_baseline and self.macro:
            return f"{self.macro.season}-B0"
        return self.block.id if self.block else "unplanned"

    def readiness(self, day: dt.date | None = None) -> Readiness:
        day = day or self.today
        if day not in self._readiness:
            start = day - dt.timedelta(days=75)
            metrics = self.state.daily_metrics(start, day)
            checkins = self.state.checkins(start, day)
            prior = {}
            for i in range(1, self.cfg.profile.thresholds.sustained_red_window):
                rec = self.state.day_record(day - dt.timedelta(days=i))
                if rec and rec.readiness:
                    prior[rec.date] = rec.readiness.state
            self._readiness[day] = compute_readiness(
                day, metrics, checkins, self.cfg.profile.thresholds, self.cfg.progressions.joint_flags, prior
            )
        return self._readiness[day]

    def bodyweight_kg(self) -> float:
        ms = [
            m.weight_kg
            for m in self.state.daily_metrics(self.today - dt.timedelta(days=7), self.today)
            if m.weight_kg
        ]
        if ms:
            return round(statistics.fmean(ms), 1)
        older = [m.weight_kg for m in self.state.daily_metrics() if m.weight_kg]
        return older[-1] if older else 95.0

    def week_plan(self, day: dt.date | None = None) -> WeekPlan | None:
        return self.state.week_plan(clock.iso_week_id(day or self.today))

    def trailing_miles(self, week_start: dt.date, n: int = 3, look_back: int = 8) -> list[float]:
        """Actual run miles of the last n normal weeks before week_start (planned if no data yet)."""
        out: list[float] = []
        sessions = self.state.sessions(
            week_start - dt.timedelta(weeks=look_back), week_start - dt.timedelta(days=1)
        )
        for i in range(1, look_back + 1):
            ws = week_start - dt.timedelta(weeks=i)
            plan = self.state.week_plan(clock.iso_week_id(ws))
            if plan and (plan.week_type in NON_NORMAL_WEEKS or plan.illness_dates):
                continue
            we = ws + dt.timedelta(days=6)
            actual = sum(s.distance_mi or 0 for s in sessions if ws <= s.date <= we and s.sport == "run")
            if actual == 0 and plan is not None:
                from coach.engine.sessions import week_miles

                actual = week_miles(plan, self.zones.threshold_pace_s_per_mi)
            if actual == 0 and plan is None and not any(ws <= s.date <= we for s in sessions):
                continue
            out.append(round(actual, 1))
            if len(out) == n:
                break
        return list(reversed(out))

    def previous_long_run(self, week_start: dt.date, look_back: int = 6) -> float | None:
        """Longest run of the last normal week before week_start (actual if logged, else planned)."""
        from coach.engine.sessions import long_run_miles

        for i in range(1, look_back + 1):
            ws = week_start - dt.timedelta(weeks=i)
            plan = self.state.week_plan(clock.iso_week_id(ws))
            if plan and (
                plan.week_type in NON_NORMAL_WEEKS or plan.week_type == "baseline" or plan.illness_dates
            ):
                continue
            runs = [
                s.distance_mi or 0
                for s in self.state.sessions(ws, ws + dt.timedelta(days=6))
                if s.sport == "run"
            ]
            if runs:
                return round(max(runs), 1)
            if plan is not None:
                return long_run_miles(plan, self.zones.threshold_pace_s_per_mi) or None
        return None

    def validation(
        self, plan: WeekPlan | None = None, outline: BlockOutline | None = None
    ) -> ValidationContext:
        start = plan.start if plan else clock.monday_of(self.today)
        prev = self.state.week_plan(clock.iso_week_id(start - dt.timedelta(days=7)))
        prev_session = None
        if prev:
            last = [s for s in prev.sessions if s.type != "rest" and s.date == start - dt.timedelta(days=1)]
            prev_session = last[-1] if last else None
        flags = (
            self.readiness(min(self.today, start + dt.timedelta(days=6))).joint_flags
            if self.has_metrics()
            else []
        )
        return ValidationContext(
            cfg=self.cfg,
            movement=self.movement,
            outline=outline if outline is not None else self.outline_for(start),
            joint_flags=flags,
            health=self.health,
            trailing_miles=self.trailing_miles(start),
            threshold_pace=self.zones.threshold_pace_s_per_mi,
            previous_session=prev_session,
            previous_long_run=self.previous_long_run(start),
        )

    def has_metrics(self) -> bool:
        return bool(self.state.daily_metrics(self.today - dt.timedelta(days=3), self.today))

    def outline_for(self, day: dt.date) -> BlockOutline | None:
        if not self.macro:
            return None
        b = self.macro.block_for(day)
        return self.state.outline(b.id) if b else None


def build(state: State | None = None, cfg: Config | None = None, today: dt.date | None = None) -> Context:
    state = state or State()
    cfg = cfg or load_config()
    today = today or clock.today()
    macro = state.macrocycle()
    block = macro.block_for(today) if macro else None
    in_baseline = bool(macro and macro.baseline_start <= today <= macro.baseline_end)
    outline = state.outline(block.id) if block else None
    week_index = ((clock.monday_of(today) - block.start).days // 7 + 1) if block else 0
    target = outline.week(week_index) if outline else None
    movement = state.movement_readiness() or mv.initial_state(cfg.progressions, today)
    dz = cfg.profile.running.default_zones
    z = state.zones() or {"lthr": dz.lthr, "threshold_pace_s_per_mi": dz.threshold_pace_s_per_mi}
    zones = Zones(lthr=int(z["lthr"]), threshold_pace_s_per_mi=int(z["threshold_pace_s_per_mi"]))
    return Context(
        cfg=cfg,
        state=state,
        today=today,
        macro=macro,
        block=block,
        in_baseline=in_baseline,
        outline=outline,
        week_target=target,
        week_index=week_index,
        movement=movement,
        zones=zones,
        health=state.health(),
    )
