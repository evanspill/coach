---
name: fuel
description: Nutrition. Daily carb/protein/fat targets (calorie-neutral redistribution of the MacroFactor weekly total), peri-workout fuelling, the block's calorie phase and when to change MacroFactor's goal, supplement context, and bloodwork trend flags (always "discuss with your physician"). Runs daily via adjust-day, at block start, and when bloodwork is pasted.
---

# fuel

**When:** daily (called by `adjust-day`), block start (calorie phase), food/macro questions, pasted bloodwork.

**Context:** today's `nutrition` in the day record (computed by `coach`), `nutrition_target` (weekly target
the athlete tells you until nutrition data is connected: `coach record add nutrition_target '{"weekly_kcal": ...}'`), `athlete/config/athlete_context.json` `nutrition`, the block
outline's `calorie_phase` and `macrofactor_setting`, `athlete/data/metrics/` weight trend.

## Rules
- MacroFactor owns the weekly calorie target. `coach` redistributes it calorie-neutrally: protein first
  (2.2-2.4 g/kg), then the 100 g fat floor, then carbs by tier (high ~5.5 / moderate ~4 / low ~3 g/kg), scaled down
  proportionally if the total is tight. Don't compute macros yourself - read them from the day record.
- Peri-workout: the athlete's cues in `athlete_context.json` `nutrition.peri_workout` (pre / during for sessions over
  `intra_threshold_minutes` / after).
- Calorie phase per block (cut / recomp / lean gain / maintenance; or fixed per block in `season.yaml`). Tell the athlete
  exactly when and how to change MacroFactor's goal (it has no write API).
- Supplements are context only (`athlete_context.json`); never change doses.
- **Bloodwork:** store each marker in `lab_results` (`coach record add lab_results '{...}'`), flag trends vs previous panels,
  always "discuss with your physician"; never diagnose or adjust supplements from bloodwork.

## Writes
`athlete/data/days/<date>.json` nutrition section (via `adjust-day`), `nutrition_target`, notes.

## Never
- Diagnose, prescribe medication, or change supplement doses. Never override MacroFactor's weekly total.
