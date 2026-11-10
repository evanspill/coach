---
name: review
description: Check-in and reflection. Weekly - adherence, what went well and what didn't, progress toward the block goal, recovery/sleep/nutrition/joint trends, gear alerts, one or two focus points; block-level review at block end; annual review and intake refresh at the end of each macrocycle. Watches accountability and state of mind (slipping adherence, falling enjoyment, rising RPE at the same loads) and asks why before changing the plan.
---

# review

**When:** Sunday (before `plan-week`), block end (after `assess` scores tests), end of the macrocycle (annual),
"how am I doing?" in chat.

**Context:** `coach report <metric> --weeks N` (mileage, weight, hrv, rhr, recovery, sleep, e1rm, adherence,
hard_sets), `coach record list|get` for `week_plans`, `day_records`, `checkins`, `metcon_logs`, `journal`, `block_goals`, `test_sets`,
`athlete/data/notes.md`.

## Weekly review contents
Adherence (planned vs completed, where coach-initiated swaps aren't misses), running actual vs planned and 80/20,
readiness distribution, sleep, weight trend, peak joint ratings, hard sets, enjoyment and RPE trend, gear alerts,
what went well, what to fix, **one or two focus points** for next week. Also the week's session load
(Foster sRPE x minutes, monotony, strain; `coach report load`), the morning-wellness trend (sleep quality, fatigue,
stress, mood) and the athlete's `journal` entries - read them before judging the numbers.

**Flags the code raises:** sleep averaging < 7 h, training monotony > 2 (days too alike; a practitioner heuristic),
estimated energy availability < ~30 kcal/kg FFM/day, less than ~75% of running time easy over two weeks (80/20).
Treat them as questions, not verdicts.

**Burnout watch:** enjoyment falling, or session RPE rising at the same loads, or adherence slipping -> **ask
why first** ("What got in the way?", "How are you feeling about training?") and change the plan after the answer.

## Block review contents
Goal hit/missed (start vs end, comparable values across variants), guardrail outcomes, adherence, recovery/
nutrition/joint trends, % of movement families fully unlocked, and for a miss the likely limiting factors. It
feeds the next block's outline.

## Annual review
Year-over-year trends, what worked, what to change; trigger the intake refresh (`assess`).

## Writes
Reports `week_reviews`, `block_reviews`, `annual_reviews` via `coach record add <report> --key <id> --file review.md`.

## Never
- Prescribe before asking when adherence or enjoyment drops; hype; hide a missed goal.
