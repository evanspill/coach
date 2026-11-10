"""Macrocycle (year) generation from race anchors. Deterministic; regenerated when races change."""

import datetime as dt

from coach.clock import monday_of
from coach.models import MacroBlock, Macrocycle
from coach.models.profile import AthleteProfile

BLOCK_INFO = {
    1: ("Strength base -> CrossFit Open", "force build, then metcon/gymnastics sharpening into the Open"),
    2: ("Hypertrophy + run ramp", "hypertrophy emphasis (12-16 hard sets/muscle/wk), run 15 -> 25 mi/wk"),
    3: ("Marathon build + Hyrox engine", "35-50 mi/wk, compromised running, lifting at MED"),
    4: ("Taper -> marathon -> reset", "3-week taper, race, 2-week structural reset"),
}


def _sunday(d: dt.date) -> dt.date:
    return monday_of(d) + dt.timedelta(days=6)


def season_label(start: dt.date) -> str:
    return f"{start.year}-{str(start.year + 1)[-2:]}"


def generate(profile: AthleteProfile, generated_on: dt.date) -> Macrocycle:
    s = profile.season
    baseline_start = monday_of(s.start)
    baseline_end = baseline_start + dt.timedelta(days=6)
    b1_start = baseline_end + dt.timedelta(days=1)
    label = season_label(baseline_start)
    notes: list[str] = []

    open_race = next((r for r in profile.races if r.kind == "crossfit_open"), None)
    marathon = next((r for r in profile.races if r.kind == "marathon"), None)

    comp_weeks: list[dt.date] = []
    if open_race:
        dates = open_race.workout_dates or [open_race.date]
        comp_weeks = sorted({monday_of(d) for d in dates})
        b1_end = _sunday(max(dates)) + dt.timedelta(weeks=s.post_open_weeks)
    else:
        b1_end = b1_start + dt.timedelta(weeks=16) - dt.timedelta(days=1)
        notes.append("No CrossFit Open in races: Block 1 defaults to 16 weeks.")

    if marathon:
        race_monday = monday_of(marathon.date)
        b4_start = race_monday - dt.timedelta(weeks=s.taper_weeks - 1)
        b4_end = _sunday(marathon.date) + dt.timedelta(weeks=s.reset_weeks)
        taper = [b4_start + dt.timedelta(weeks=i) for i in range(s.taper_weeks)]
        reset = [race_monday + dt.timedelta(weeks=i + 1) for i in range(s.reset_weeks)]
        b3_start = b4_start - dt.timedelta(weeks=s.marathon_build_weeks)
    else:
        b4_start = b1_end + dt.timedelta(days=1) + dt.timedelta(weeks=28)
        b4_end = b4_start + dt.timedelta(weeks=5) - dt.timedelta(days=1)
        taper, reset = [], []
        b3_start = b4_start - dt.timedelta(weeks=13)
        notes.append("No marathon in races: Blocks 2-4 use default lengths.")

    b2_start = b1_end + dt.timedelta(days=1)
    b2_end = b3_start - dt.timedelta(days=1)
    if (b2_end - b2_start).days + 1 < 28:
        raise ValueError("races too close together: Block 2 would be shorter than 4 weeks")

    spans = [
        (b1_start, b1_end),
        (b2_start, b2_end),
        (b3_start, b4_start - dt.timedelta(days=1)),
        (b4_start, b4_end),
    ]
    blocks = []
    for i, (start, end) in enumerate(spans, start=1):
        name, focus = BLOCK_INFO[i]
        events = []
        if i == 1 and open_race:
            events.append(open_race.id)
        if i == 4 and marathon:
            events.append(marathon.id)
        blocks.append(
            MacroBlock(
                id=f"{label}-B{i}",
                index=i,
                name=name,
                focus=focus,
                start=start,
                end=end,
                competition_weeks=comp_weeks
                if i == 1
                else ([monday_of(marathon.date)] if i == 4 and marathon else []),
                taper_weeks=taper if i == 4 else [],
                reset_weeks=reset if i == 4 else [],
                events=events,
            )
        )
    unconfirmed = [r.name for r in profile.races if not r.confirmed]
    if unconfirmed:
        notes.append("Plan depends on unconfirmed race dates: " + ", ".join(unconfirmed))
    return Macrocycle(
        season=label,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        blocks=blocks,
        generated_on=generated_on,
        unconfirmed_races=unconfirmed,
        notes=notes,
    )


def check(macro: Macrocycle) -> list[str]:
    """Gaps, overlaps, week alignment."""
    errors = []
    prev_end = macro.baseline_end
    if macro.baseline_start.weekday() != 0:
        errors.append("baseline week must start on a Monday")
    for b in macro.blocks:
        if b.start != prev_end + dt.timedelta(days=1):
            kind = "gap" if b.start > prev_end + dt.timedelta(days=1) else "overlap"
            errors.append(
                f"macrocycle {kind} before {b.id}: previous ends {prev_end}, {b.id} starts {b.start}"
            )
        if b.start.weekday() != 0 or b.end.weekday() != 6:
            errors.append(f"{b.id} must run Monday to Sunday")
        if b.end < b.start or b.weeks < 4:
            errors.append(f"{b.id} shorter than 4 weeks")
        prev_end = b.end
    return errors
