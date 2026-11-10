"""Fill in the numbers Claude must not invent: loads (from e1RM, rounded to real plates/DBs/KBs) and paces/HR."""

import datetime as dt

from coach.engine import loads as L
from coach.engine.paces import Zones
from coach.models import Session, SessionRecord
from coach.models.library import ExerciseLibrary


class Filler:
    def __init__(
        self,
        library: ExerciseLibrary,
        loading: dict,
        history: list[SessionRecord],
        zones: Zones,
        today: dt.date,
    ):
        self.lib = library
        self.loading = loading
        self.history = history
        self.zones = zones
        self.today = today
        self._e1rm_cache: dict[str, float | None] = {}

    def e1rm(self, ex_id: str) -> float | None:
        if ex_id not in self._e1rm_cache:
            v = L.best_recent_e1rm(self.history, ex_id, self.today, weeks=8)
            est = self.lib.get(ex_id).estimate_from if self.lib.get(ex_id) else None
            if v is None and est is not None:
                base = L.best_recent_e1rm(self.history, est.exercise, self.today, weeks=8)
                v = base * est.factor if base else None
            self._e1rm_cache[ex_id] = v
        return self._e1rm_cache[ex_id]

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
            items = list(b.items) + (list(b.metcon.movements) if b.metcon else [])
            for it in items:
                ex = self.lib.get(it.exercise_id)
                if ex is None:
                    continue
                it.load_kg = it.load_lb = None
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
                    prog = L.progression(self.history, ex.id, it.reps, rir, self.today)
                    target *= prog.factor
                    if ex.family in ecc:
                        target = L.apply_eccentric_rule(target)
                        it.tempo = "3-0-1-0"
                        notes.append(f"{ex.name}: -15% and 3 s eccentric (pain rule)")
                    if load_cap and ex.id in load_cap:
                        target = min(target, load_cap[ex.id])
                    r = L.round_load(target, ex.implement, self.loading)
                    it.load_kg, it.load_lb, it.load_note = r.load_kg, r.load_lb, r.note
                elif ex.load_mode == "last_used":
                    last = L.last_used(self.history, ex.id, self.today)
                    if last:
                        r = (
                            L.round_load(last, ex.implement, self.loading)
                            if ex.implement in {"dumbbell", "kettlebell"}
                            else None
                        )
                        it.load_kg = r.load_kg if r and r.load_kg else round(last, 1)
                        it.load_note = (
                            f"start at last used ({r.note if r else f'{last:g} kg'}), adjust to {it.rir:g} RIR"
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
