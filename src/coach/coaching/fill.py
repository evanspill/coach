"""Fill in the numbers Claude must not invent: loads (from e1RM, rounded to real plates/DBs/KBs) and paces/HR."""

import datetime as dt
import re

from coach.engine import loads as L
from coach.engine.paces import Zones
from coach.engine.prescribe import rest_for
from coach.models import Change, Session, SessionRecord
from coach.models.library import ExerciseLibrary
from coach.models.plans import RampSet
from coach.models.season import TrainingRules

# Blocks whose exercises get warm-up sets; the warm-up block itself primes everything else (holds, jumps, metcons).
WARMUP_BLOCKS = {"strength", "hypertrophy", "test", "power"}
# Exercises that never get their own warm-up sets: light prep/core/mobility work, timed holds, carries and jumps
# (extra holds or jumps before a test only add fatigue), and conditioning movements.
NO_WARMUP_TAGS = {
    "core", "prehab", "mobility", "warmup", "screen", "mcgill", "recovery", "cooldown", "isometric", "carry",
    "plyo", "plyo_low", "conditioning", "erg", "decompression", "gymnastics_drill", "skill_drill", "sprint",
}  # fmt: skip
LOADED_MODES = {"e1rm", "last_used", "kb"}


def planned_rir(state, history: list[SessionRecord]) -> L.PlannedRIR:
    """The RIR each logged session's plan prescribed per exercise, from its day record (`planned_session`, the
    plan as written). A test block's sets count as 0 RIR whatever it prescribed: test scoring reads them as
    all-out (Epley at 0 RIR), and rep-max work-ups drift toward the max. DECISIONS 107."""
    out: L.PlannedRIR = {}
    for s in history:
        if not s.planned_session_id:
            continue
        rec = state.day_record(s.date)
        plan = rec.planned_session if rec else None
        if plan is None or plan.id != s.planned_session_id:
            continue
        for b in plan.blocks:
            for it in b.items:
                if b.kind == "test":
                    out[(plan.id, it.exercise_id)] = 0.0
                elif it.rir is not None:
                    out.setdefault((plan.id, it.exercise_id), it.rir)
    return out


def planned_reps(state, history: list[SessionRecord]) -> L.PlannedReps:
    """The reps per set each logged session's plan prescribed per exercise, from its day record (`planned_session`).
    Test blocks are left out: a rep-max work-up's lighter sets aren't misses. DECISIONS 108."""
    out: L.PlannedReps = {}
    for s in history:
        if not s.planned_session_id:
            continue
        rec = state.day_record(s.date)
        plan = rec.planned_session if rec else None
        if plan is None or plan.id != s.planned_session_id:
            continue
        for b in plan.blocks:
            if b.kind == "test":
                continue
            for it in b.items:
                if it.reps:
                    out.setdefault((plan.id, it.exercise_id), it.reps)
    return out


def _loads(s: Session) -> dict[str, tuple[float | None, float | None]]:
    out: dict[str, tuple[float | None, float | None]] = {}
    for b in s.blocks:
        for it in list(b.items) + (list(b.metcon.movements) if b.metcon else []):
            if it.load_kg is not None:
                out.setdefault(it.exercise_id, (it.load_kg, it.load_lb))
    return out


def load_changes(planned: Session | None, session: Session | None, library: ExerciseLibrary) -> list[Change]:
    """Working loads that differ between the plan as written and today's filled session (the same exercise in both),
    as changes the athlete sees: a recalculation from newer logs or updated load rules is never silent
    (DECISIONS 108)."""
    if planned is None or session is None:
        return []
    before, after = _loads(planned), _loads(session)
    out = []
    for ex_id, (kg, lb) in after.items():
        if ex_id not in before:
            continue
        kg0, lb0 = before[ex_id]
        if lb is not None and lb0 is not None:
            if abs(lb - lb0) < 0.01:
                continue
            what = f"{lb0:g} -> {lb:g} lb"
        else:
            if kg is None or kg0 is None or abs(kg - kg0) < 0.05:
                continue
            what = f"{kg0:g} -> {kg:g} kg"
        ex = library.get(ex_id)
        out.append(
            Change(
                what=f"{ex.name if ex else ex_id}: {what}",
                why="load recalculated from the latest logs and load rules",
            )
        )
    return out


class Filler:
    def __init__(
        self,
        library: ExerciseLibrary,
        loading: dict,
        history: list[SessionRecord],
        zones: Zones,
        today: dt.date,
        rules: TrainingRules | None = None,
        planned: L.PlannedRIR | None = None,
        planned_reps: L.PlannedReps | None = None,
    ):
        self.planned = planned
        self.planned_reps = planned_reps
        self.lib = library
        self.loading = loading
        self.history = history
        self.zones = zones
        self.today = today
        self.rules = rules
        self._e1rm_cache: dict[str, float | None] = {}

    def e1rm(self, ex_id: str) -> float | None:
        if ex_id not in self._e1rm_cache:
            v, _why = L.current_e1rm(
                self.history, ex_id, self.today, planned=self.planned, planned_reps=self.planned_reps
            )
            lib_ex = self.lib.get(ex_id)
            est = lib_ex.estimate_from if lib_ex else None
            if v is None and est is not None:
                base, _ = L.current_e1rm(
                    self.history,
                    est.exercise,
                    self.today,
                    planned=self.planned,
                    planned_reps=self.planned_reps,
                )
                v = base * est.factor if base else None
            self._e1rm_cache[ex_id] = v
        return self._e1rm_cache[ex_id]

    def warmups(self, s: Session) -> None:
        """Warm-up sets before every strength exercise, sized to what its prime mover has already done this session:
        the full ramp for primary lifts, two build-up sets for the first loaded compound of a muscle group, one
        feeler set for a compound on a warm prime mover or isolation work on a fresh one (none for isolation
        on a warm one), and one easy set before bodyweight strength work
        on fresh muscles. Unknown working weights get percentage warm-ups and a note."""
        warm: set[str] = set()
        for b in s.blocks:
            if b.kind not in WARMUP_BLOCKS:
                continue
            for it in b.items:
                ex = self.lib.get(it.exercise_id)
                if ex is None or ex.has_tag(*NO_WARMUP_TAGS):
                    continue
                if it.reps is None and (it.duration_s or it.distance_m or it.calories):
                    continue  # timed/distance work
                loaded = ex.load_mode in LOADED_MODES
                if not loaded and (ex.load_mode != "bodyweight" or b.kind == "power"):
                    continue
                # warm = this exercise's prime mover (its first listed muscle) already led an earlier exercise;
                # secondary muscles don't count (a deadlift's back work doesn't warm the lats for pull-ups)
                prime = ex.muscles[0] if ex.muscles else ex.id
                fresh = prime not in warm
                warm.add(prime)
                if not loaded:
                    if fresh:
                        it.ramp = [RampSet(reps=L.bodyweight_warmup_reps(it.reps))]
                    continue
                if "primary" in ex.tags and b.kind in {"strength", "test", "power"}:
                    tier = "full"
                elif "isolation" not in ex.tags:
                    tier = "build" if fresh else "feeler"
                elif fresh:
                    tier = "feeler"
                else:
                    continue  # isolation for a prime mover that already worked: the first work set warms it
                reps = it.reps or 5
                if it.load_kg:
                    it.ramp = [
                        RampSet(reps=n, load_kg=kg, load_lb=lb)
                        for n, kg, lb in L.ramp_sets(it.load_kg, ex.implement, self.loading, reps, tier)
                    ]
                    continue
                steps = L.WARMUP_STEPS[tier]
                it.ramp = [RampSet(reps=min(r, reps), pct=p) for p, r in steps]
                plan = ", ".join(f"~{p:.0%} x{min(r, reps)}" for p, r in steps)
                base = re.sub(
                    r"(^|; )warm-up .*$", "", it.load_note or ""
                )  # never stack the plan on a refill
                it.load_note = f"{base}; warm-up {plan} of your working weight".lstrip("; ")

    def fill(
        self,
        s: Session,
        pace_adjust: tuple[int, int] = (0, 0),
        eccentric_families: set[str] | None = None,
        load_cap: dict[str, float] | None = None,
    ) -> list[str]:
        notes: list[str] = []
        ecc = eccentric_families or set()
        for b in s.blocks:
            if (
                self.rules is not None
            ):  # every set-based exercise gets a rest (metcon movements run on the clock)
                for it in b.items:
                    it.rest_s = rest_for(b.kind, self.lib.get(it.exercise_id), it, self.rules)
            items = list(b.items) + (list(b.metcon.movements) if b.metcon else [])
            for it in items:
                ex = self.lib.get(it.exercise_id)
                if ex is None:
                    continue
                it.load_kg = it.load_lb = None
                it.ramp = []  # code-filled: never carry a ramp over from an earlier fill or a swapped exercise
                if ex.load_mode == "e1rm" and it.reps:
                    est = self.e1rm(ex.id)
                    if est is None:
                        it.load_note = (
                            f"pick a load you can do for {it.reps} @ {it.rir:g} RIR"
                            if it.rir is not None
                            else "self-selected"
                        )
                        continue
                    rir = it.rir if it.rir is not None else 2.0
                    target = L.load_for(est, it.reps, rir)
                    prog = L.progression(
                        self.history,
                        ex.id,
                        it.reps,
                        rir,
                        self.today,
                        planned=self.planned,
                        planned_reps=self.planned_reps,
                    )
                    target *= prog.factor
                    if ex.family in ecc:
                        target = L.apply_eccentric_rule(target)
                        it.tempo = "3-0-1-0"
                        notes.append(f"{ex.name}: -15% and 3 s eccentric (pain rule)")
                    if load_cap and ex.id in load_cap:
                        target = min(target, load_cap[ex.id])
                    r = L.round_load(target, ex.implement, self.loading, down=True)
                    it.load_kg, it.load_lb, it.load_note = r.load_kg, r.load_lb, r.note
                elif ex.load_mode == "last_used":
                    last = L.last_used(self.history, ex.id, self.today)
                    if last:
                        lr = (
                            L.round_load(last, ex.implement, self.loading)
                            if ex.implement in {"dumbbell", "kettlebell"}
                            else None
                        )
                        it.load_kg = lr.load_kg if lr and lr.load_kg else round(last, 1)
                        it.load_note = (
                            f"start at last used ({lr.note if lr else f'{last:g} kg'}), adjust to {it.rir:g} RIR"
                            if it.rir is not None
                            else "last used"
                        )
                    else:
                        it.load_note = f"by RIR ({it.rir:g})" if it.rir is not None else "by feel"
                elif ex.load_mode == "kb":
                    r = L.kb_for_effort("moderate", self.loading)
                    it.load_kg, it.load_lb, it.load_note = r.load_kg, r.load_lb, r.note
                elif ex.load_mode == "bodyweight":
                    it.load_note = "bodyweight"
        self.warmups(s)
        for seg in s.run_segments():
            if seg.zone == "strides":
                seg.pace_s_per_mi = self.zones.pace("strides")
                continue
            fast, slow = self.zones.pace(seg.zone)
            seg.pace_s_per_mi = (fast + pace_adjust[0], slow + pace_adjust[1])
            if seg.modality in {"run", "walk"}:
                seg.hr_bpm = self.zones.hr(seg.zone)
            else:
                seg.pace_s_per_mi = None
                seg.hr_bpm = self.zones.hr(seg.zone)
        return notes
