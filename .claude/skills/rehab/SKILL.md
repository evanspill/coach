---
name: rehab
description: Return to unrestricted training and durability. Manages the movement readiness ladders (advance, hold, regress one rung at a time), the in-session pain rule, capacity and mobility work (trunk, shoulder, hips/ankles/T-spine), tendon load during the running ramp, and when to recommend a physio.
---

# rehab

**When:** after each session that touched a gated movement family (daily run), pain reports, "can I deadlift from
the floor yet?", region flags.

**Context:** `state/movement_readiness.json`, `config/movement_progressions.yaml`, check-ins (`session_pain`,
`stiffness_up`, joint ratings), `coach readiness` (joint flags), `docs/SAFETY.md`.

## Rules
- **Advance one rung** after 3 clean exposures at the current rung (pain <= 2/10 in session, no rise in next-morning
  stiffness) and at least 14 days at the rung. Never more than one rung.
- **Regress one rung** on session pain > 2/10 or a next-day flare. Pain rule: regress ROM or switch to an
  isometric next time; if stiffness rose, -15% load and a 3 s eccentric for 2 weeks.
- **Region flag** (>= 3 on 2 consecutive check-ins): the region's families drop one rung for the next week and the
  region's tags are restricted until it's <= 2 twice in a row.
- Track "% of movement families fully unlocked" (reported in every block review).
- Capacity work is part of every week (trunk, shoulder/scapular, hips/ankles/T-spine, tendon load during any
  running ramp), using the warm-ups and item sets in `config/training.yaml` for the athlete's flagged regions.
- Recommend a physiotherapist when a family regresses twice in 4 weeks, pain persists > 2 weeks, or anything
  matches a red flag.

## Writes
`state/movement_readiness.json` - validate the change first: `coach validate state/movement_readiness.json`
(rejects > 1-rung moves and advances without criteria).

## Never
- Jump rungs, advance during a regression hold, or treat a red flag as a rehab problem.
