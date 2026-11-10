"""design-session fallback: builds sessions from an intent, respecting rungs, joint flags, skills,
equipment at the location and deload rules. Shared by plan-week, adjust-day, replan and compete."""

import datetime as dt
import math

from coach.context import Context
from coach.engine import movement as mv
from coach.engine.sessions import hard_sets
from coach.models import Exercise, Metcon, Prescription, RunSegment, Session, SessionBlock

DELOAD_LIKE = {"deload", "transition", "taper", "reset"}


class Picker:
    """Resolves an intended exercise to one that is allowed today."""

    def __init__(
        self, ctx: Context, week_type: str, location: str = "gym", restricted: set[str] | None = None
    ):
        self.ctx = ctx
        self.lib = ctx.cfg.library
        self.week_type = week_type
        self.location = location
        self.restricted = restricted if restricted is not None else self._restricted()
        self.available = ctx.cfg.equipment.available(location, ctx.cfg.profile.travel_equipment)

    def _restricted(self) -> set[str]:
        if not self.ctx.has_metrics():
            return set()
        tags: set[str] = set()
        for f in self.ctx.readiness().joint_flags:
            tags |= set(f.restricted_tags)
        return tags

    def ok(self, ex: Exercise | None, for_metcon: bool = False, block_kind: str = "") -> bool:
        if ex is None:
            return False
        if not mv.allowed(ex, self.ctx.movement)[0]:
            return False
        if self.restricted & set(ex.tags):
            return False
        if not set(ex.equipment) <= self.available:
            return False
        if (
            self.week_type in DELOAD_LIKE
            and block_kind not in {"warmup", "test"}
            and ex.has_tag(*self.ctx.cfg.training.rules.deload_banned_tags)
        ):
            return False
        if ex.skill and for_metcon:
            sk = self.ctx.cfg.skills.skills.get(ex.skill)
            if sk and not sk.competent:
                return False
        return True

    def pick(self, ex_id: str, for_metcon: bool = False, block_kind: str = "") -> str | None:
        ex = self.lib.get(ex_id)
        if self.ok(ex, for_metcon, block_kind):
            return ex_id
        if ex and ex.deload_swap and self.ok(self.lib.get(ex.deload_swap), for_metcon, block_kind):
            return ex.deload_swap
        return mv.safe_substitute(ex_id, self.lib, lambda e: self.ok(e, for_metcon, block_kind))

    def main_lift(self, family: str, prefer: str | None = None) -> str | None:
        ex_id = mv.exercise_for_rung(
            family, self.ctx.movement.rung(family), self.ctx.cfg.progressions, prefer
        )
        if ex_id is None:
            return None
        return self.pick(ex_id, block_kind="strength")


def rx(
    ex_id: str | None, sets: int, reps: int | None = None, rir: float | None = None, **kw
) -> Prescription | None:
    if ex_id is None:
        return None
    return Prescription(exercise_id=ex_id, sets=max(1, sets), reps=reps, rir=rir, **kw)


def _items(*xs: Prescription | None) -> list[Prescription]:
    return [x for x in xs if x is not None]


def _from_spec(
    spec, P: Picker, block_kind: str, scale_fn=None, for_metcon: bool = False
) -> Prescription | None:
    """ItemSpec (config) -> Prescription, resolving families to the current rung and swapping what isn't allowed."""
    if spec.family:
        ex_id = P.main_lift(spec.family)
    else:
        target = spec.exercise
        if spec.deload_exercise and P.week_type in DELOAD_LIKE:
            target = spec.deload_exercise
        ex_id = P.pick(target, for_metcon=for_metcon, block_kind=block_kind)
    if ex_id is None:
        return None
    sets = scale_fn(spec.sets) if scale_fn else spec.sets
    return Prescription(
        exercise_id=ex_id,
        sets=max(1, sets),
        reps=spec.reps,
        reps_max=spec.reps_max,
        rir=spec.rir,
        duration_s=spec.duration_s,
        distance_m=spec.distance_m,
        calories=spec.calories,
        rest_s=spec.rest_s,
        per_side=spec.per_side,
        notes=spec.notes,
        tempo=spec.tempo,
    )


def items_block(kind: str, specs, P: Picker, title: str = "", scale_fn=None) -> SessionBlock:
    return SessionBlock(
        kind=kind, title=title, items=_items(*(_from_spec(sp, P, kind, scale_fn) for sp in specs))
    )  # type: ignore[arg-type]


def warmup(kind: str, P: Picker) -> SessionBlock:
    ws = P.ctx.cfg.training.item_set(kind, "warmups")
    return items_block("warmup", ws.items, P, ws.title)


def cooldown(P: Picker, name: str = "standard") -> SessionBlock:
    cs = P.ctx.cfg.training.item_set(name, "cooldowns")
    return items_block("cooldown", cs.items, P, cs.title)


def item_set_block(kind: str, name: str, P: Picker, scale_fn=None) -> SessionBlock:
    st = P.ctx.cfg.training.item_set(name)
    return items_block(kind, st.items, P, st.title, scale_fn)


def skill_block(P: Picker, week_number: int) -> SessionBlock | None:
    """10-12 min practice while fresh: 1-3 reps/set, <= 70% effort; rotates through skills not yet competent."""
    sp = P.ctx.cfg.training.skill_practice
    skills = P.ctx.cfg.skills.skills
    pending = [k for k, s in skills.items() if not s.competent and s.drills]
    items: list[Prescription] = []
    if pending:
        chosen = [pending[(week_number + i) % len(pending)] for i in range(min(sp.per_session, len(pending)))]
        for sk in dict.fromkeys(chosen):
            for drill in skills[sk].drills:
                got = P.pick(drill, block_kind="skill")
                if got:
                    items.append(
                        Prescription(
                            exercise_id=got,
                            sets=sp.sets,
                            reps=sp.reps,
                            rir=sp.rir,
                            notes=f"skill: {skills[sk].name}; stop when mechanics degrade",
                        )
                    )
                    break
    if not items:
        for ex in sp.fallback:
            got = P.pick(ex, block_kind="skill")
            if got:
                items.append(Prescription(exercise_id=got, sets=3, duration_s=20))
    if not items:
        return None
    return SessionBlock(kind="skill", title="Skill primer (10-12 min, fresh, <= 70%)", items=items)


def metcon_block(
    P: Picker, pool_name: str, minutes: float, week_number: int, name: str | None = None
) -> SessionBlock:
    pool = P.ctx.cfg.training.metcon_pools[pool_name]
    moves = pool.movements
    start = (week_number * 3) % len(moves)
    chosen: list[Prescription] = []
    seen: set[str] = set()
    for i in range(len(moves)):
        sp = moves[(start + i) % len(moves)]
        rx_ = _from_spec(sp, P, "conditioning", for_metcon=True)
        if rx_ and rx_.exercise_id not in seen:
            seen.add(rx_.exercise_id)
            rx_.sets = 1
            chosen.append(rx_)
        if len(chosen) == pool.count:
            break
    if P.week_type in DELOAD_LIKE:
        minutes = max(6, round(minutes * 0.6))
    mc = Metcon(
        name=name or pool.name.format(minutes=int(minutes)),
        format=pool.format,
        time_cap_min=minutes,
        rounds=pool.rounds,  # type: ignore[arg-type]
        movements=chosen,
        stimulus=pool.stimulus,
        scaling=pool.scaling,
        score_type=pool.score_type,
    )  # type: ignore[arg-type]
    return SessionBlock(kind="conditioning", title=mc.name, metcon=mc)


def run_block(
    label: str,
    miles: float,
    zone: str = "Z2",
    location: str = "outdoor",
    mp_finish_min: float = 0,
    strides: int = 0,
    mp_pace_s_per_mi: float = 450,
    mp_from_miles: float = 8,
) -> SessionBlock:
    segs = []
    terrain = "treadmill" if location == "gym" else "flat"
    if mp_finish_min > 0 and miles >= mp_from_miles:
        mp_miles = round(min(mp_finish_min * 60 / mp_pace_s_per_mi, miles * 0.25), 1)
        segs.append(
            RunSegment(
                label=f"{label} (easy)", zone=zone, distance_mi=round(miles - mp_miles, 1), terrain=terrain
            )
        )  # type: ignore[arg-type]
        segs.append(
            RunSegment(label="Marathon-pace finish", zone="MP", distance_mi=mp_miles, terrain=terrain)
        )
    else:
        segs.append(RunSegment(label=label, zone=zone, distance_mi=round(miles, 1), terrain=terrain))  # type: ignore[arg-type]
    if strides:
        segs.append(
            RunSegment(
                label="Strides (20 s, walk back)",
                zone="strides",
                duration_min=0.33,
                reps=strides,
                terrain=terrain,
            )
        )
    return SessionBlock(kind="run", title=label, run=segs)


def estimate_minutes(s: Session, threshold_pace: float) -> int:
    from coach.engine.paces import PACE_FACTORS

    total = 0.0
    for b in s.blocks:
        if b.kind == "warmup":
            total += 10
        elif b.kind == "cooldown":
            total += 5
        elif b.kind in {"skill", "power"}:
            total += 10
        elif b.kind == "strength":
            total += sum(it.sets * 3.5 for it in b.items)
        elif b.kind == "hypertrophy":
            total += sum(it.sets * 2.3 for it in b.items)
        elif b.kind == "mobility":
            total += 15
        elif b.kind == "test":
            total += 22
        if b.metcon:
            total += b.metcon.time_cap_min + 5
        for seg in b.run:
            if seg.duration_min:
                total += seg.duration_min * seg.reps + (seg.recovery_min or 0) * seg.reps
            elif seg.distance_mi:
                lo, hi = PACE_FACTORS[seg.zone]
                total += seg.distance_mi * threshold_pace * (lo + hi) / 2 / 60 * seg.reps
    return int(math.ceil(total / 5) * 5)


def make_session(
    ctx: Context,
    day: dt.date,
    role: str,
    stype: str,
    title: str,
    intent: str,
    blocks: list[SessionBlock | None],
    location: str = "gym",
    route: str | None = None,
    key: bool = False,
    tests: list[str] | None = None,
) -> Session:
    s = Session(
        id=f"{day.isoformat()}-{role}",
        date=day,
        start_time=ctx.cfg.profile.default_start,
        type=stype,  # type: ignore[arg-type]
        title=title,
        intent=intent,
        location=location,  # type: ignore[arg-type]
        route=route,
        expected_minutes=0,
        key=key,
        blocks=[b for b in blocks if b is not None],
        tests=tests or [],
    )
    s.expected_minutes = estimate_minutes(s, ctx.zones.threshold_pace_s_per_mi)
    return s


def recovery_session(ctx: Context, day: dt.date, minutes: int | None = None, note: str = "") -> Session:
    """The `recovery` session template, optionally with a different walk length / intent."""
    from coach.fallback.templates import build_session

    s = build_session(ctx, "recovery", day, "deload", 0.0, week_number=day.isocalendar()[1])
    if minutes is not None:
        for seg in s.run_segments():
            if seg.modality == "walk":
                seg.duration_min = minutes
    if note:
        s.intent = note
    s.expected_minutes = estimate_minutes(s, ctx.zones.threshold_pace_s_per_mi)
    s.carb_tier = "low"
    return s


def rest_session(ctx: Context, day: dt.date, reason: str) -> Session:
    return Session(
        id=f"{day.isoformat()}-rest",
        date=day,
        start_time=ctx.cfg.profile.default_start,
        type="rest",
        title="Rest",
        intent=reason,
        location="gym",
        expected_minutes=0,
        carb_tier="low",
    )


LOWER = {"quads", "hamstrings", "glutes", "calves", "adductors"}


def balance_hard_sets(
    sessions: list[Session], ranges: dict[str, tuple[int, int]], ctx: Context, week_type: str, rir: float = 2
) -> None:
    """Nudge accessory volume until every muscle sits inside the outline's hard-set range."""
    lib = ctx.cfg.library
    for _ in range(60):
        sets = hard_sets(sessions, lib)
        low = [m for m, (lo, _hi) in ranges.items() if sets.get(m, 0) < lo]
        high = [m for m, (_lo, hi) in ranges.items() if sets.get(m, 0) > hi]
        if not low and not high:
            return
        if high:
            m = high[0]
            if not _trim(sessions, m, ctx, ranges, sets):
                return
            continue
        m = low[0]
        if not _add(sessions, m, ctx, ranges, sets, week_type, rir):
            return


def _hyp_items(sessions, muscle, lib):
    for s in sessions:
        for b in s.blocks:
            if b.kind == "hypertrophy":
                for it in b.items:
                    ex = lib.get(it.exercise_id)
                    if ex and muscle in ex.muscles:
                        yield s, b, it, ex


def _side_effect_ok(ex, sets, ranges, delta) -> bool:
    for m in ex.muscles:
        if m in ranges:
            lo, hi = ranges[m]
            if not (lo - 99 <= sets.get(m, 0) + delta <= hi):
                return False
    return True


def _trim(sessions, muscle, ctx, ranges, sets) -> bool:
    lib = ctx.cfg.library
    cands = sorted(_hyp_items(sessions, muscle, lib), key=lambda t: len(t[3].muscles))
    for _s, b, it, _ex in cands:
        if it.sets > 1:
            it.sets -= 1
            return True
        b.items.remove(it)
        return True
    for s in sessions:
        for b in s.blocks:
            if b.kind == "strength":
                for it in b.items:
                    ex = lib.get(it.exercise_id)
                    if ex and muscle in ex.muscles and it.sets > 2:
                        it.sets -= 1
                        return True
    return False


def _add(sessions, muscle, ctx, ranges, sets, week_type, rir) -> bool:
    lib = ctx.cfg.library
    cands = sorted(_hyp_items(sessions, muscle, lib), key=lambda t: len(t[3].muscles))
    for _s, _b, it, ex in cands:
        if it.sets < 5 and _side_effect_ok(ex, sets, ranges, +1):
            it.sets += 1
            return True
    lower = muscle in LOWER
    targets = [
        s
        for s in sessions
        if s.type in ({"lower", "full_body"} if lower else {"upper", "sprint_upper", "full_body"})
    ]
    for s in targets:
        P = Picker(ctx, week_type, s.location)
        filler = ctx.cfg.training.fillers.get(muscle)
        ex_id = P.pick(filler, block_kind="hypertrophy") if filler else None
        if not ex_id or any(it.exercise_id == ex_id for b in s.blocks for it in b.items):
            continue
        hyp = next((b for b in s.blocks if b.kind == "hypertrophy"), None)
        if hyp is None:
            hyp = SessionBlock(kind="hypertrophy", title="Accessories")
            idx = next(
                (
                    i
                    for i, b in enumerate(s.blocks)
                    if b.kind in {"conditioning", "run", "mobility", "cooldown"}
                ),
                len(s.blocks),
            )
            s.blocks.insert(idx, hyp)
        hyp.items.append(Prescription(exercise_id=ex_id, sets=2, reps=12, rir=rir))
        return True
    return False
