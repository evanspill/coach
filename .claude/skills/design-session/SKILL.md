---
name: design-session
description: Session craft. Builds one session from an intent (stimulus, time domain, location, equipment, readiness rungs, skill levels) - warm-up, primer, main work, accessories, conditioning (metcon/Hyrox design with intended stimulus and scaling), cool-down and expected length. Shared by every skill that creates or changes a session so the session rules live in one place.
---

# design-session

**When:** called by `plan-week`, `adjust-day`, `replan`, `compete`, or a chat request like "swap today's pressing".

**Context:** `coach context --week` (rungs, e1RMs, skills, zones), `config/exercises.yaml` (tags, equipment,
regressions, deload swaps), `config/equipment.yaml` (what's available at the location), `config/skills.yaml`,
active joint flags from `coach readiness`.

## Session rules (enforced by `coach validate`)
- Structure: **warm-up -> (skill primer) -> speed/power -> heavy strength -> hypertrophy -> conditioning ->
  (mobility) -> cool-down**. Warm-up first, cool-down last, always.
- Warm-ups: lower/run days = McGill Big 3 (curl-up, side plank, bird dog) + tib raises + pogo hops + couch
  stretch; upper/CrossFit days = band pull-aparts, scap push-ups, T-spine open books, bottoms-up KB press,
  Crossover Symmetry. Cool-down: ~3 min easy + slow breathing to HR < 110, then dead hangs.
- Exercises only from `config/exercises.yaml`, at or below the current rung (and its RIR cap), never with tags
  restricted by an active joint flag (use the exercise's `regressions`), only equipment available at the location.
- Skill work (Olympic lifts, gymnastics) 10-12 min while fresh, 1-3 reps/set, <= 70% effort; **never in a metcon
  or after fatiguing work until `skills.yaml` marks it competent**. Shoulder rules: no fatigued high-rep overhead
  snatching.
- Deload weeks: swap eccentric-heavy / high-impact work (`deload_swap`), cut volume ~40-50%, keep intensity.
- Metcons state the **intended stimulus**, format, time cap and scaling; Hyrox pieces state run pace and stations.
- Prescribe sets, reps, RIR (strength) and zones (runs). **Leave `load_kg` and paces empty**: `coach` fills them.
- Set `expected_minutes` to the session's purpose and the athlete's current capacity (shorter on Yellow/deload).

## Output
`Session` objects (see `src/coach/models/plans.py`). Example: `examples/lower_force_session.json`,
`examples/metcon_block.json`.

## Never
- Use an exercise that isn't in the library, above a rung, or restricted by a flag.
- Put an unmastered skill inside a metcon.
- Type loads or paces yourself.
