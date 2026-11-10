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
            and ex.has_tag("eccentric_heavy", "high_impact")
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


def warmup(kind: str, P: Picker) -> SessionBlock:
    if kind in {"lower", "run", "full"}:
        items = _items(
            rx(P.pick("mcgill_curl_up", block_kind="warmup"), 1, 5, notes="10 s holds"),
            rx(P.pick("side_plank", block_kind="warmup"), 1, duration_s=20, per_side=True),
            rx(P.pick("bird_dog", block_kind="warmup"), 1, 6, per_side=True),
            rx(P.pick("tib_raise", block_kind="warmup"), 1, 15),
            rx(P.pick("pogo_hops", block_kind="warmup"), 2, 20)
            if P.week_type not in DELOAD_LIKE
            else rx(P.pick("ankle_rocker", block_kind="warmup"), 1, 10, per_side=True),
            rx(P.pick("couch_stretch", block_kind="warmup"), 1, duration_s=45, per_side=True),
        )
        if kind == "full":
            items += _items(
                rx(P.pick("band_pull_apart", block_kind="warmup"), 1, 15),
                rx(P.pick("thoracic_open_book", block_kind="warmup"), 1, 8, per_side=True),
            )
        return SessionBlock(
            kind="warmup", title="Lower/run prep: McGill Big 3, tibs, pogos, couch stretch", items=items
        )
    if kind == "upper":
        items = _items(
            rx(P.pick("band_pull_apart", block_kind="warmup"), 2, 15),
            rx(P.pick("scap_push_up", block_kind="warmup"), 1, 10),
            rx(P.pick("thoracic_open_book", block_kind="warmup"), 1, 8, per_side=True),
            rx(P.pick("bottoms_up_kb_press", block_kind="warmup"), 2, 5, per_side=True),
            rx(
                P.pick("crossover_symmetry_activation", block_kind="warmup"),
                1,
                1,
                notes="activation sequence",
            ),
        )
        return SessionBlock(kind="warmup", title="Shoulder prep", items=items)
    items = _items(
        rx(P.pick("cat_cow", block_kind="warmup"), 1, 8),
        rx(P.pick("world_greatest_stretch", block_kind="warmup"), 1, 4, per_side=True),
    )
    return SessionBlock(kind="warmup", title="Easy mobility warm-up", items=items)


def cooldown(P: Picker) -> SessionBlock:
    return SessionBlock(
        kind="cooldown",
        title="~3 min easy + slow breathing to HR < 110, then hangs",
        items=_items(
            rx(P.pick("easy_cooldown", block_kind="cooldown"), 1, duration_s=180),
            rx(P.pick("dead_hang", block_kind="cooldown"), 2, duration_s=30),
        ),
    )


def primer_lower(P: Picker) -> SessionBlock:
    jump = P.pick("box_jump", block_kind="power")
    return SessionBlock(
        kind="power",
        title="Neural primer",
        items=_items(rx(jump, 3, 3, rest_s=60), rx(P.pick("med_ball_scoop_toss", block_kind="power"), 2, 3)),
    )


def primer_upper(P: Picker) -> SessionBlock:
    return SessionBlock(
        kind="power",
        title="Upper primer",
        items=_items(rx(P.pick("med_ball_chest_pass", block_kind="power"), 3, 5)),
    )


def sprints(P: Picker) -> SessionBlock:
    s = P.pick("curve_sprint", block_kind="power")
    return SessionBlock(
        kind="power",
        title="Alactic sprints: 6 x 10 s, full recovery",
        items=_items(rx(s, 6, duration_s=10, rest_s=120)),
    )


SKILL_DRILLS = {
    "kipping_pull_up": ["kip_swing", "hollow_hold"],
    "toes_to_bar": ["kip_swing", "hanging_knee_raise"],
    "power_clean": ["hang_power_clean", "clean_positions_empty_bar"],
    "snatch": ["muscle_snatch", "snatch_positions_pvc"],
    "overhead_squat": ["overhead_squat", "snatch_positions_pvc"],
    "chest_to_bar": ["kipping_pull_up", "kip_swing"],
    "peg_board": ["peg_board_ascent", "strict_pull_up"],
}


def skill_block(P: Picker, week_number: int) -> SessionBlock | None:
    """10-12 min practice while fresh: 1-3 reps/set, <= 70% effort; rotates through skills not yet competent."""
    pending = [k for k, s in P.ctx.cfg.skills.skills.items() if not s.competent and k in SKILL_DRILLS]
    if not pending:
        return None
    chosen = [pending[(week_number + i) % len(pending)] for i in range(min(2, len(pending)))]
    items = []
    for sk in dict.fromkeys(chosen):
        for drill in SKILL_DRILLS[sk]:
            got = P.pick(drill, block_kind="skill")
            if got:
                items.append(
                    rx(
                        got,
                        4,
                        3,
                        rir=4,
                        notes=f"skill: {P.ctx.cfg.skills.skills[sk].name}; stop when mechanics degrade",
                    )
                )
                break
    items = [i for i in items if i is not None]
    if not items:
        items = _items(
            rx(P.pick("hollow_hold", block_kind="skill"), 3, duration_s=20),
            rx(P.pick("arch_hold", block_kind="skill"), 3, duration_s=20),
        )
    return SessionBlock(kind="skill", title="Skill primer (10-12 min, fresh, <= 70%)", items=items)


METCON_POOLS = {
    "short": [
        ("row_erg", dict(calories=12)),
        ("kb_swing", dict(reps=15)),
        ("burpee", dict(reps=10)),
        ("wall_ball", dict(reps=15)),
        ("toes_to_bar", dict(reps=10)),
        ("box_step_over", dict(reps=12)),
        ("echo_bike", dict(calories=10)),
        ("strict_pull_up", dict(reps=5)),
        ("db_hang_clean_and_press_low", dict(reps=10)),
        ("ski_erg", dict(calories=12)),
    ],
    "hyrox": [
        ("ski_erg", dict(distance_m=500)),
        ("sled_push", dict(distance_m=25)),
        ("sled_pull", dict(distance_m=25)),
        ("burpee_broad_jump", dict(reps=10)),
        ("row_erg", dict(distance_m=500)),
        ("farmers_carry", dict(distance_m=100)),
        ("sandbag_lunge", dict(distance_m=25)),
        ("wall_ball", dict(reps=20)),
    ],
}


def metcon_block(
    P: Picker, stimulus: str, minutes: float, week_number: int, name: str | None = None
) -> SessionBlock:
    pool = METCON_POOLS["hyrox" if stimulus == "hyrox" else "short"]
    n = 4 if stimulus == "hyrox" else 3
    start = (week_number * 3) % len(pool)
    chosen: list[Prescription] = []
    seen: set[str] = set()
    for i in range(len(pool)):
        ex_id, kw = pool[(start + i) % len(pool)]
        got = P.pick(ex_id, for_metcon=True, block_kind="conditioning")
        if got and got not in seen:
            seen.add(got)
            chosen.append(Prescription(exercise_id=got, sets=1, **kw))
        if len(chosen) == n:
            break
    if P.week_type in DELOAD_LIKE:
        minutes = max(6, round(minutes * 0.6))
    if stimulus == "hyrox":
        mc = Metcon(
            name=name or "Hyrox threshold intervals",
            format="intervals",
            time_cap_min=minutes,
            rounds=4,
            movements=chosen,
            stimulus="Threshold (~RPE 7-8): 400 m treadmill run between stations, steady not all-out; practise transitions",
            scaling="Hold the run at threshold pace; reduce station distance before slowing the run",
            score_type="time",
        )
    else:
        mc = Metcon(
            name=name or f"{int(minutes)}-min AMRAP",
            format="amrap",
            time_cap_min=minutes,
            movements=chosen,
            stimulus="Glycolytic, ~85-90% effort, sustainable pace with short breaks; no grinding",
            scaling="Only movements at or below current rungs/skill levels; scale reps before load",
            score_type="rounds_reps",
        )
    return SessionBlock(kind="conditioning", title=mc.name, metcon=mc)


def run_block(
    label: str,
    miles: float,
    zone: str = "Z2",
    location: str = "outdoor",
    mp_finish_min: float = 0,
    strides: int = 0,
) -> SessionBlock:
    segs = []
    terrain = "treadmill" if location == "gym" else "flat"
    if mp_finish_min > 0 and miles >= 8:
        mp_miles = round(min(mp_finish_min * 60 / 450, miles * 0.25), 1)
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


def recovery_session(ctx: Context, day: dt.date, minutes: int = 35, note: str = "") -> Session:
    P = Picker(ctx, "deload", "home")
    mob = SessionBlock(
        kind="mobility",
        title="Mobility: foam roller, bands, lacrosse ball",
        items=_items(
            rx(P.pick("foam_roll"), 1, duration_s=300),
            rx(P.pick("hip_90_90"), 1, 8, per_side=True),
            rx(P.pick("band_mobility"), 1, duration_s=300),
            rx(P.pick("thoracic_open_book"), 1, 8, per_side=True),
        ),
    )
    walk = SessionBlock(
        kind="run",
        title="Zone 1 walk",
        run=[RunSegment(label="Z1 walk", zone="Z1", duration_min=minutes, modality="walk")],
    )
    s = make_session(
        ctx,
        day,
        "recovery",
        "recovery",
        "Recovery: Z1 walk + mobility",
        note or "Promote recovery; nothing hard.",
        [walk, mob],
        location="home",
        route="neighbourhood walk",
    )
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


FILLERS = {
    "quads": "leg_extension",
    "hamstrings": "seated_leg_curl",
    "glutes": "hip_thrust",
    "chest": "cable_fly",
    "back": "cable_row",
    "shoulders": "lateral_raise_db",
}
LOWER = {"quads", "hamstrings", "glutes"}


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
        ex_id = P.pick(FILLERS[muscle], block_kind="hypertrophy")
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
