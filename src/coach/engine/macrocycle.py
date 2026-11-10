"""Macrocycle (year) generation: lays out the blocks in config/season.yaml around the race anchors in
config/athlete_context.json. Deterministic; regenerated when races or the season shape change."""

import datetime as dt

from coach.clock import monday_of
from coach.models import MacroBlock, Macrocycle
from coach.models.profile import AthleteProfile, Race
from coach.models.season import BlockSpec, SeasonConfig


def _sunday(d: dt.date) -> dt.date:
    return monday_of(d) + dt.timedelta(days=6)


def season_label(start: dt.date) -> str:
    return f"{start.year}-{str(start.year + 1)[-2:]}"


def _event_dates(race: Race) -> list[dt.date]:
    return sorted(race.workout_dates or [race.date])


def _fixed_weeks(spec: BlockSpec, profile: AthleteProfile, notes: list[str]) -> int | None:
    L = spec.length
    if L.weeks is not None:
        return L.weeks
    kind = L.end_after_event.kind if L.end_after_event else L.event.kind if L.event else None
    if kind and profile.race(kind) is None:
        if L.default_weeks is None:
            raise ValueError(f"block {spec.key}: no '{kind}' race and no default_weeks")
        notes.append(f"No {kind} in races: {spec.key} defaults to {L.default_weeks} weeks.")
        return L.default_weeks
    return None


def _forward_end(spec: BlockSpec, start: dt.date, profile: AthleteProfile, notes: list[str]) -> dt.date:
    """End date for a block laid out forward from `start`."""
    weeks = _fixed_weeks(spec, profile, notes)
    if weeks is not None:
        return start + dt.timedelta(weeks=weeks) - dt.timedelta(days=1)
    L = spec.length
    if L.end_after_event:
        race = profile.race(L.end_after_event.kind)
        return _sunday(_event_dates(race)[-1]) + dt.timedelta(weeks=L.end_after_event.weeks_after)
    assert L.event
    race = profile.race(L.event.kind)
    return _sunday(race.date) + dt.timedelta(weeks=L.event.reset_weeks)


def _backward_start(
    spec: BlockSpec, end: dt.date | None, profile: AthleteProfile, notes: list[str]
) -> tuple[dt.date, dt.date]:
    """(start, end) for a block laid out backward. `end` is the next block's start - 1 day (None for the last block)."""
    L = spec.length
    if L.event and profile.race(L.event.kind):
        race = profile.race(L.event.kind)
        start = monday_of(race.date) - dt.timedelta(weeks=L.event.taper_weeks - 1)
        return start, _sunday(race.date) + dt.timedelta(weeks=L.event.reset_weeks)
    if end is None:
        raise ValueError(
            f"block {spec.key}: the last block needs an event anchor (or put a fill block before it)"
        )
    weeks = _fixed_weeks(spec, profile, notes)
    if weeks is None:
        raise ValueError(f"block {spec.key}: can't lay out an end_after_event block after the fill block")
    return end - dt.timedelta(weeks=weeks) + dt.timedelta(days=1), end


def _block_events(spec: BlockSpec, start: dt.date, end: dt.date, profile: AthleteProfile) -> dict:
    comp, taper, reset, events = [], [], [], []
    for r in profile.races:
        if any(start <= d <= end for d in _event_dates(r)):
            events.append(r.id)
    if spec.competition_event and (race := profile.race(spec.competition_event)):
        comp = sorted({monday_of(d) for d in _event_dates(race) if start <= d <= end})
    if spec.length.event and (race := profile.race(spec.length.event.kind)) and start <= race.date <= end:
        rm = monday_of(race.date)
        comp = [rm]
        taper = [
            rm - dt.timedelta(weeks=spec.length.event.taper_weeks - 1 - i)
            for i in range(spec.length.event.taper_weeks)
        ]
        reset = [rm + dt.timedelta(weeks=i + 1) for i in range(spec.length.event.reset_weeks)]
    return {"competition_weeks": comp, "taper_weeks": taper, "reset_weeks": reset, "events": events}


def generate(profile: AthleteProfile, season: SeasonConfig, generated_on: dt.date) -> Macrocycle:
    s = season.season
    baseline_start = monday_of(s.start)
    baseline_end = baseline_start + dt.timedelta(weeks=s.baseline_weeks) - dt.timedelta(days=1)
    label = season_label(baseline_start)
    notes: list[str] = []
    specs = season.blocks
    fill_idx = next((i for i, b in enumerate(specs) if b.length.fill), None)
    spans: dict[int, tuple[dt.date, dt.date]] = {}
    cursor = baseline_end + dt.timedelta(days=1)
    forward = range(fill_idx if fill_idx is not None else len(specs))
    for i in forward:
        end = _forward_end(specs[i], cursor, profile, notes)
        spans[i] = (cursor, end)
        cursor = end + dt.timedelta(days=1)
    if fill_idx is not None:
        nxt_end: dt.date | None = None
        for i in range(len(specs) - 1, fill_idx, -1):
            start, end = _backward_start(specs[i], nxt_end, profile, notes)
            spans[i] = (start, end)
            nxt_end = start - dt.timedelta(days=1)
        fill_end = (
            nxt_end
            if nxt_end is not None
            else cursor
            + dt.timedelta(weeks=specs[fill_idx].length.default_weeks or 12)
            - dt.timedelta(days=1)
        )
        spans[fill_idx] = (cursor, fill_end)
        if (fill_end - cursor).days + 1 < 7 * s.min_block_weeks:
            raise ValueError(
                f"races too close together: block {specs[fill_idx].key} would be shorter than {s.min_block_weeks} weeks"
            )
    blocks = []
    for i, spec in enumerate(specs):
        start, end = spans[i]
        ev = _block_events(spec, start, end, profile)
        blocks.append(
            MacroBlock(
                id=f"{label}-{spec.key}",
                key=spec.key,
                index=i + 1,
                name=spec.name,
                focus=spec.focus,
                start=start,
                end=end,
                **ev,
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


def check(macro: Macrocycle, min_weeks: int = 4) -> list[str]:
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
        if b.end < b.start or b.weeks < min_weeks:
            errors.append(f"{b.id} shorter than {min_weeks} weeks")
        prev_end = b.end
    return errors
