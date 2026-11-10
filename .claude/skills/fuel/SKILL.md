---
name: fuel
description: Nutrition. Daily carb/protein/fat targets (calorie-neutral redistribution of the MacroFactor weekly total), peri-workout fuelling, the block's calorie phase and when to change MacroFactor's goal, supplement context, and bloodwork trend flags (always "discuss with your physician"). Runs daily via adjust-day, at block start, and when bloodwork is pasted.
---

# fuel

**When:** daily (called by `adjust-day`), block start (calorie phase), food/macro questions, pasted bloodwork.

**Context:** today's `nutrition` in the day record (computed by `coach`), `nutrition_target` (weekly target
the athlete tells you until nutrition data is connected: `coach record add nutrition_target '{"weekly_kcal": ...}'`), `athlete/config/athlete_context.json` `nutrition`, the block
outline's `calorie_phase` and `macrofactor_setting`, `coach report weight` (weight trend) and the weekly review's energy-availability estimate.

## Rules
- MacroFactor owns the weekly calorie target. `coach` redistributes it calorie-neutrally: protein first
  (2.2-2.4 g/kg), then the 100 g fat floor, then carbs by tier (high ~5.5 / moderate ~4 / low ~3 g/kg), scaled down
  proportionally if the total is tight. Don't compute macros yourself - read them from the day record.
- Peri-workout: the athlete's cues in `athlete_context.json` `nutrition.peri_workout` (pre / during for sessions over
  `intra_threshold_minutes` / after).
- Calorie phase per block (cut / recomp / lean gain / maintenance; or fixed per block in `season.yaml`). Tell the athlete
  exactly when and how to change MacroFactor's goal (it has no write API).
- **Energy availability (REDs watch):** the weekly review estimates (intake - exercise energy) / fat-free mass. If it
  stays below ~30 kcal/kg FFM/day (a common risk indicator; the exact cut-off is debated), or REDs signs show up
  (persistent fatigue, low mood, poor sleep, recurrent illness, bone stress), raise carbs on hard days or ease the
  deficit, and suggest checking in with a physician. Training quality beats a faster cut.
- Protein: top of the range during a cut (code does this); spread over 3-5 meals of ~0.3-0.4 g/kg.
- Supplements are context only (`athlete_context.json`); never change doses.
- **Bloodwork:** store each marker in `lab_results` (`coach record add lab_results '{...}'`), flag trends vs previous panels,
  always "discuss with your physician"; never diagnose or adjust supplements from bloodwork.

## Writes
the `day_records` nutrition section (via `adjust-day`), `nutrition_target`, notes.

## Never
- Diagnose, prescribe medication, or change supplement doses. Never override MacroFactor's weekly total.
