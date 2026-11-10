"""Movement readiness ladders: advance one rung after clean exposures, regress on pain or flares."""

import datetime as dt
from collections.abc import Callable

from coach.models import Exercise, MovementProgressions, MovementReadiness
from coach.models.library import ExerciseLibrary
from coach.models.records import Exposure, FamilyState, RungEvent


def initial_state(
    progressions: MovementProgressions, today: dt.date, rungs: dict[str, int] | None = None
) -> MovementReadiness:
    rungs = rungs or {}
    return MovementReadiness(
        updated=today,
        families={f: FamilyState(family=f, rung=rungs.get(f, 0)) for f in progressions.families},
        note="Conservative starting rungs; set from the baseline week (and a physio assessment if done).",
    )


def allowed(ex: Exercise, mr: MovementReadiness) -> tuple[bool, str]:
    if ex.family is not None and ex.rung is not None and ex.rung > mr.rung(ex.family):
        return False, f"{ex.name} is {ex.family} rung {ex.rung}; current rung is {mr.rung(ex.family)}"
    for fam, need in ex.requires.items():
        if mr.rung(fam) < need:
            return False, f"{ex.name} needs {fam} rung {need}; current rung is {mr.rung(fam)}"
    return True, ""


def exercise_for_rung(
    family: str, rung: int, progressions: MovementProgressions, prefer: str | None = None
) -> str | None:
    fam = progressions.families[family]
    for r in range(min(rung, len(fam.rungs) - 1), -1, -1):
        exs = fam.rungs[r].exercises
        if prefer and prefer in exs:
            return prefer
        if exs:
            return exs[0]
    return None


def safe_substitute(
    ex_id: str,
    library: ExerciseLibrary,
    ok: Callable[[Exercise | None], bool],
    max_depth: int = 6,
) -> str | None:
    """Walk the regression graph breadth-first until an exercise passes `ok`."""
    seen = {ex_id}
    frontier = [ex_id]
    for _ in range(max_depth):
        nxt = []
        for cur in frontier:
            ex = library.get(cur)
            if ex is None:
                continue
            for r in ex.regressions:
                if r in seen:
                    continue
                seen.add(r)
                if ok(library.get(r)):
                    return r
                nxt.append(r)
        frontier = nxt
    return None


def record_exposure(
    mr: MovementReadiness,
    family: str,
    day: dt.date,
    session_pain: float | None,
    stiffness_up: bool,
    progressions: MovementProgressions,
) -> list[RungEvent]:
    """Log one exposure; regress immediately on pain/flare, advance when the criteria are met."""
    rules = progressions.rules
    fs = mr.families[family]
    events: list[RungEvent] = []
    pain = session_pain or 0.0
    clean = pain <= rules.max_session_pain_to_advance and not stiffness_up
    fs.exposures.append(
        Exposure(date=day, rung=fs.rung, session_pain=session_pain, stiffness_up=stiffness_up, clean=clean)
    )
    if pain > rules.regress_on_session_pain_above or (stiffness_up and rules.regress_on_next_day_flare):
        if fs.rung > 0:
            why = (
                f"session pain {pain:g}/10"
                if pain > rules.regress_on_session_pain_above
                else "next-morning stiffness rose"
            )
            events.append(_move(fs, day, fs.rung - 1, f"regress: {why}"))
        if stiffness_up:
            fs.eccentric_tempo_until = day + dt.timedelta(days=14)
        fs.hold_until = day + dt.timedelta(days=7)
    elif advance_blocker(fs, day, progressions) == "form_check":
        fs.pending_form_check = fs.rung + 1
    elif can_advance(fs, day, progressions):
        events.append(
            _move(
                fs,
                day,
                fs.rung + 1,
                f"advance: {rules.exposures_to_advance} clean exposures (pain <= 2/10, no stiffness rise)",
            )
        )
    mr.updated = day
    return events


def advance_blocker(fs: FamilyState, day: dt.date, progressions: MovementProgressions) -> str | None:
    """None if the family may move up one rung today, else why not ('top', 'hold', 'time', 'exposures', 'form_check')."""
    rungs = progressions.families[fs.family].rungs
    if fs.rung >= len(rungs) - 1:
        return "top"
    if fs.hold_until and day < fs.hold_until:
        return "hold"
    target = rungs[fs.rung + 1]
    min_days = (
        target.min_days_before if target.min_days_before is not None else progressions.rules.min_days_at_rung
    )
    since = fs.history[-1].date if fs.history else None
    if since is not None and (day - since).days < min_days:
        return "time"
    if fs.clean_exposures() < progressions.rules.exposures_to_advance:
        return "exposures"
    if target.form_check and (fs.form_check_cleared is None or fs.form_check_cleared < fs.rung + 1):
        return "form_check"
    return None


def can_advance(fs: FamilyState, day: dt.date, progressions: MovementProgressions) -> bool:
    return advance_blocker(fs, day, progressions) is None


def clear_form_check(mr: MovementReadiness, family: str, day: dt.date, by: str) -> int:
    """Record that a form check (coach video review or physio) cleared the next rung. Returns the cleared rung."""
    fs = mr.families[family]
    target = fs.pending_form_check or fs.rung + 1
    fs.form_check_cleared = max(target, fs.form_check_cleared or 0)
    fs.pending_form_check = None
    mr.note = f"{day}: form check for {family} rung {target} cleared by {by}"
    return target


def _move(fs: FamilyState, day: dt.date, to: int, reason: str) -> RungEvent:
    ev = RungEvent(date=day, from_rung=fs.rung, to_rung=to, reason=reason, evidence=fs.clean_exposures())
    fs.history.append(ev)
    fs.pending_form_check = None
    fs.rung = to
    fs.exposures = []
    return ev


def apply_region_flag(
    mr: MovementReadiness, region: str, day: dt.date, progressions: MovementProgressions
) -> list[RungEvent]:
    """Region >= 3 on 2 consecutive check-ins: mapped families drop a rung for the next week."""
    events = []
    for fam in progressions.families_for_region(region):
        fs = mr.families[fam]
        if (
            fs.hold_until
            and fs.hold_until > day
            and fs.history
            and fs.history[-1].date >= day - dt.timedelta(days=6)
        ):
            continue  # already regressed for this flare
        if fs.rung > 0:
            events.append(_move(fs, day, fs.rung - 1, f"regress: {region} flagged on consecutive check-ins"))
        fs.hold_until = day + dt.timedelta(days=7)
    return events


def validate_change(
    before: MovementReadiness, after: MovementReadiness, progressions: MovementProgressions
) -> list[str]:
    errors = []
    for fam, b in before.families.items():
        a = after.families.get(fam)
        if a is None:
            errors.append(f"family {fam} missing after change")
            continue
        delta = a.rung - b.rung
        if abs(delta) > 1:
            errors.append(f"{fam}: rung {b.rung} -> {a.rung} moves more than one rung")
        if delta == 1:
            ev = a.history[-1] if a.history else None
            need = progressions.rules.exposures_to_advance
            held = b.hold_until is not None and ev is not None and ev.date < b.hold_until
            target = progressions.families[fam].rungs[min(a.rung, len(progressions.families[fam].rungs) - 1)]
            cleared = max(a.form_check_cleared or 0, b.form_check_cleared or 0)
            if target.form_check and cleared < a.rung:
                errors.append(
                    f"{fam}: rung {a.rung} ({target.name}) needs a recorded form check before advancing"
                )
            last = b.history[-1].date if b.history else None
            min_days = (
                target.min_days_before
                if target.min_days_before is not None
                else progressions.rules.min_days_at_rung
            )
            if ev is not None and last is not None and (ev.date - last).days < min_days:
                errors.append(f"{fam}: only {(ev.date - last).days} days at rung {b.rung} (needs {min_days})")
            if ev is None or ev.to_rung != a.rung or ev.evidence < need or held:
                have = ev.evidence if ev else b.clean_exposures()
                errors.append(
                    f"{fam}: advance to rung {a.rung} without criteria ({have}/{need} clean exposures"
                    + (", regression hold active" if held else "")
                    + ")"
                )
    return errors


def unlocked_pct(mr: MovementReadiness, progressions: MovementProgressions) -> float:
    total = len(progressions.families)
    top = sum(1 for f, fam in progressions.families.items() if mr.rung(f) >= len(fam.rungs) - 1)
    return round(100 * top / total, 1)
