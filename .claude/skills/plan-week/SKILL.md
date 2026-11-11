---
name: plan-week
description: Weekly programming. Distributes next week from the block outline and last week's review - which days, which session types, the right volume - and calls design-session for each session. Runs Sunday after review. Output must pass coach validate; deviations from the outline need a stated reason.
---

# plan-week

**When:** Sunday (after `review`), or when `replan` asks for a rebuilt week.

**Context:** `coach context --week` (outline week target, pillars, trailing miles, e1RMs at current rungs, recent
check-ins, last week's review), `athlete/data/notes.md`, `health_events` (`coach record list health_events`), the athlete's schedule changes (ask on
Sunday: travel? gym closures?).

## Procedure
1. Start from the outline week: type, run miles, long run, key sessions, hard-set ranges, pillar MEDs.
1b. Check `coach record list availability --from <monday> --to <sunday>` (travel, gym closures, busy days) and
   plan around it (`replan` travel rules for no-gym days).
2. Adjust for last week's review (focus points, adherence, flags). Any deviation from the outline goes in
   `deviations` with a reason (e.g. "held mileage at 28 instead of 31: three yellow days").
3. Lay out days using the default microcycle in `docs/TRAINING_ARCHITECTURE.md` and the week templates in `athlete/config/training.yaml` (sessions/day and start window from `athlete_context.json` `schedule`,
   session length sized to purpose and capacity). Respect spacing: no forbidden back-to-back hard days, no hard
   lower lifting the day before the long run.
3b. Every week has at least one rest/recovery day and sessions stay under the `max_session_minutes` cap (long runs,
   races and tests excepted); about 80% of running time is easy.
4. Call `design-session` for each session (intent, stimulus, location, equipment, rungs, skill levels).
5. Write the draft `WeekPlan` (`generated_by: "claude"`, loads/paces left empty) to a scratch file and submit it:
   `coach record add week_plans --file /tmp/plan.json`. This fills loads (from current e1RM, incl. warm-up ramps),
   paces, minutes and carb tiers, validates the week, saves it, writes the summary and opens the `weekly_plan`
   proposal (manual mode). If it's refused, fix the listed violations and resubmit; after 3 refusals use the
   deterministic fallback (`coach daily --fallback` builds it) and flag it in the summary.
6. Approval follows `athlete/config/coach.yaml` `approval.weekly_plan`: `manual` -> say it's waiting
   (`coach approve week` pushes it); `auto` -> `coach push --week --next`.

## Writes
`week_plans` (+ the `week_summaries` report and the proposal), all via `coach record add week_plans --file ...`.

## May call
`design-session` (every session), `compete` (competition weeks), `fuel` (carb tiers are set by code).

## Never
- Invent loads or paces; put tests outside the baseline/transition week; push an unvalidated plan.
- Push anything but the current week's sessions to Hevy/Intervals.
