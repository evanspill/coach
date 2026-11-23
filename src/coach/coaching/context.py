"""Everything a skill needs to know about 'now', assembled from state + config (read-only)."""

import datetime as dt
from dataclasses import dataclass, field

from coach import clock
from coach.config import Config, load_config
from coach.engine import bodycomp as BC
from coach.engine import movement as mv
from coach.engine.paces import Zones, build_zones
from coach.engine.readiness import compute_readiness
from coach.engine.validator import ValidationContext
from coach.models import (
    BlockOutline,
    MacroBlock,
    Macrocycle,
    MovementReadiness,
    Readiness,
    WeekPlan,
    WeekTarget,
)
from coach.models.journal import HealthEvent
from coach.store import Store

NON_NORMAL_WEEKS = {"deload", "transition", "taper", "reset"}


@dataclass
class Context:
    cfg: Config
    state: Store
    today: dt.date
    macro: Macrocycle | None
    block: MacroBlock | None
    in_baseline: bool
    outline: BlockOutline | None
    week_target: WeekTarget | None
    week_index: int
    movement: MovementReadiness
    zones: Zones
    health: list[HealthEvent]
    _readiness: dict[dt.date, Readiness] = field(default_factory=dict)
    _body: dict[str, list[tuple[dt.date, float]]] = field(default_factory=dict)

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

    def body_trend(self, field: str = "weight_kg", until: dt.date | None = None) -> "BC.Trend | None":
        """EWMA trend (DECISIONS 87) of `weight_kg` or `body_fat_pct` from all readings up to `until`."""
        end = until or self.today
        return BC.trend([(d, v) for d, v in self._readings(field) if d <= end])

    def _readings(self, field: str) -> list[tuple[dt.date, float]]:
        """(date, value) for every day with a reading, oldest first; read once per Context (callers ask often)."""
        if field not in self._body:
            self._body[field] = [
                (m.date, v) for m in self.state.daily_metrics(None, self.today) if (v := getattr(m, field))
            ]
        return self._body[field]

    def settled_trend(self, field: str, start: dt.date) -> "BC.Trend | None":
        """Trend at `start`, or at the first later day with BC.MIN_READINGS readings so far (a block that starts
        with the first weigh-ins would otherwise compare against one unsmoothed reading)."""
        t = self.body_trend(field, start)
        if t and t.readings >= BC.MIN_READINGS:
            return t
        days = [d for d, _ in self._readings(field)]
        settled = [d for i, d in enumerate(days) if d >= start and i + 1 >= BC.MIN_READINGS]
        return self.body_trend(field, settled[0]) if settled else None

    def bodyweight_kg(self) -> float:
        """Trend weight (not a raw reading), so loads and macros don't jump with a single weigh-in.
        A stale trend is still used (it beats the 95 kg default); its age is surfaced by `bodyweight_age_days`
        and `coach context`, and sync flags a stale scale on the notification's Data line."""
        t = self.body_trend()
        return round(t.value, 1) if t else 95.0

    def bodyweight_age_days(self) -> int | None:
        t = self.body_trend()
        return t.age_days(self.today) if t else None

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

    def longest_run_30d(self, week_start: dt.date) -> float | None:
        """Longest single run in the 30 days before week_start: logged runs, plus planned runs on days not yet
        reached (planning next week on a Sunday counts the rest of this week as planned)."""
        from coach.engine.sessions import session_miles

        start, end = week_start - dt.timedelta(days=30), week_start - dt.timedelta(days=1)
        runs = [s.distance_mi or 0 for s in self.state.sessions(start, end) if s.sport == "run"]
        d = max(start, self.today)
        while d <= end:
            plan = self.state.week_plan(clock.iso_week_id(d))
            s = plan.session_on(d) if plan else None
            if s is not None:
                runs.append(session_miles(s, self.zones.threshold_pace_s_per_mi))
            d += dt.timedelta(days=1)
        best = max(runs, default=0.0)
        return round(best, 2) if best > 0 else None

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
            longest_run_30d=self.longest_run_30d(start),
        )

    def has_metrics(self) -> bool:
        return bool(self.state.daily_metrics(self.today - dt.timedelta(days=3), self.today))

    def outline_for(self, day: dt.date) -> BlockOutline | None:
        if not self.macro:
            return None
        b = self.macro.block_for(day)
        return self.state.outline(b.id) if b else None


def build(state: Store | None = None, cfg: Config | None = None, today: dt.date | None = None) -> Context:
    state = state or Store()
    cfg = cfg or load_config()
    today = today or clock.today()
    macro = state.macrocycle()
    block = macro.block_for(today) if macro else None
    in_baseline = bool(macro and macro.baseline_start <= today <= macro.baseline_end)
    outline = state.outline(block.id) if block else None
    week_index = ((clock.monday_of(today) - block.start).days // 7 + 1) if block else 0
    target = outline.week(week_index) if outline else None
    movement = state.movement_readiness() or mv.initial_state(cfg.progressions, today)
    zones = build_zones(cfg, state, today)
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
        health=state.health_events(),
    )
