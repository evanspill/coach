---
name: plan-block
description: Periodization. Turns an approved block goal into the block outline - main lifts and rep schemes, progression path, weekly targets per pillar (mileage, hard sets per muscle, key sessions), deload and competition weeks, calorie phase and the MacroFactor setting. Uses the code-generated macrocycle. Use for a new block, a race added or moved, or a major disruption.
---

# plan-block

**When:** a new block (after the goal is approved), a race added/moved (after `coach macrocycle regenerate`),
or a major disruption that changes the block's shape.

**Context:** `coach context --block`, `macrocycle`, `coach record get block_goals --key <id>`,
`coach record get block_reviews --key <prev>`, `docs/TRAINING_ARCHITECTURE.md` (pillar table, hard-set ranges, ramp rules).

## Procedure
1. Take block dates, competition/taper/reset weeks from the macrocycle (code-generated; never edit dates by hand).
1b. Evidence anchors: deloads every 4-6 weeks with volume cut and intensity kept are common practice; hypertrophy
   responds to weekly volume (~10+ hard sets/muscle); strength and endurance can be maintained on far less volume
   if intensity is kept (MED blocks); tapers cut volume ~40-60% while keeping intensity and frequency. See
   `docs/TRAINING_ARCHITECTURE.md` "Evidence basis".
2. Week types: deloads every ~4th week counting back from the transition week (3:1), never in competition weeks;
   the last week is the transition week. No 5-week span without a deload.
3. Weekly targets: run miles (return-to-running ramp: <= +10%/week over the trailing 3 normal weeks, hold flat on
   deloads, block mileage range), long run, key sessions (as stress categories: `lower_heavy`, `upper_heavy`,
   `glycolytic`, `run_quality`, `long_run`, `test`, `competition`, `race`), hard-set ranges per muscle (deload
   weeks have their own ranges).
4. Pillars: build/maintain dose and the MED for each (every pillar is touched every week).
5. Main lifts fixed for the block (per family, at the current rung), rep schemes, progression rule; accessories,
   metcon formats, modalities and routes rotate for variety.
6. Calorie phase from the approved goal; state the **MacroFactor setting** to use and tell the athlete when to change
   it (MacroFactor has no write API).
7. Submit: `coach record add block_outlines --file /tmp/outline.json` (validates; refused outlines aren't saved).

## Writes
`block_outlines` (`BlockOutline`). Revisions append to `revisions` with a reason.

## May call
`compete` (competition/taper weeks), `assess` (if the goal is missing).

## Never
- Change macrocycle dates (code owns them) or skip the transition week.
- Finalize an outline for a block whose goal is still pending (mark it provisional).
- Set mileage jumps the ramp rules forbid.
