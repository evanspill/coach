"""Deload placement (3:1 counting back from the transition week) and reactive deload shifting."""

DELOAD_LIKE = {"deload", "transition", "taper", "reset", "baseline"}


def plan_deloads(
    n_weeks: int, competition_weeks: set[int] | None = None, every: int = 4, min_first: int = 3
) -> list[int]:
    """Week numbers (1-based) of planned deloads. The last week is the transition week (not listed)."""
    comp = competition_weeks or set()
    transition = n_weeks
    deloads: list[int] = []
    w = transition - every
    while w >= min_first:
        cand = w
        while cand in comp and cand > min_first:
            cand -= 1
        if cand in comp:
            break
        deloads.append(cand)
        w = cand - every
    deloads.sort()
    return _fill_gaps(deloads, n_weeks, comp, every)


def _fill_gaps(deloads: list[int], n_weeks: int, comp: set[int], every: int) -> list[int]:
    """Guarantee no 5-week span without a deload-like week (week 0 = previous transition)."""
    out = sorted(set(deloads))
    changed = True
    while changed:
        changed = False
        marks = [0, *out, n_weeks]
        for a, b in zip(marks, marks[1:], strict=False):
            if b - a - 1 > every:
                # more than `every` training weeks in a row: insert a deload `every` weeks after a
                cand = a + every
                while cand in comp and cand > a + 1:
                    cand -= 1
                out = sorted(set(out) | {cand})
                changed = True
                break
    return out


def max_run_without_deload(week_types: list[str]) -> int:
    longest = run = 0
    for t in week_types:
        if t in DELOAD_LIKE:
            run = 0
        else:
            run += 1
            longest = max(longest, run)
    return longest


def pull_forward(
    deloads: list[int], new_deload: int, n_weeks: int, comp: set[int], every: int = 4
) -> list[int]:
    """Reactive deload: make `new_deload` a deload, drop the next planned one, re-space the rest."""
    before = [d for d in deloads if d < new_deload]
    after: list[int] = []
    w = new_deload + every
    while w < n_weeks:
        cand = w
        floor = (after[-1] if after else new_deload) + 2
        while cand in comp and cand > floor:
            cand -= 1
        if (
            cand in comp or n_weeks - cand < 2
        ):  # too close to the transition week: the transition is the deload
            break
        after.append(cand)
        w = cand + every
    return _fill_gaps(sorted({*before, new_deload, *after}), n_weeks, comp, every)
