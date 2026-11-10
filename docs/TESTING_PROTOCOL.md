# Testing protocol

Generated from `athlete/config/tests.yaml` (the source of truth; edit there, then update this file).

**Principles:** rep-maxes only (no true 1RMs), at the current movement-readiness rung; the variant is recorded and
converted to the reference variant so blocks stay comparable. Tests need Green or Yellow readiness; on Red they move
within +/-2 days. Strength, the run time trial and engine tests are on separate days.

## Standard conditions
- **time_of_day**: 09:00-10:30, same as training
- **readiness_required**: ['green', 'yellow']
- **reschedule_window_days**: 2
- **warmup**: General: 5 min easy erg, then the session's joint-specific warm-up (McGill Big 3 before lower-body tests).

## When
- **Baseline week** (once, before Block 1): broad_jump, hinge_rm, squat_rm, db_press_5rm, pullups_max, run_tt_30, row_2k, body_comp, vitals.
- **Transition week** (last week of every block): deload Mon-Wed; Thu run TT, Fri strength + power, Sat engine. Retest the outgoing block's goal/guardrail tests and run the next block's entry tests.
- **Tracked every block**: hinge_rm, db_press_5rm, body_comp, vitals, plus RHR/HRV baselines, threshold pace/CTL, joint-rating trends.
- **Block candidates**: B1: hinge_rm, squat_rm, db_press_5rm, pullups_max, broad_jump, row_2k, run_tt_30; B2: hinge_rm, squat_rm, db_press_5rm, run_tt_30, body_comp; B3: run_tt_30, z2_drift_60, hyrox_sim, row_2k; B4: run_tt_30, hyrox_sim

## Standing broad jump (`broad_jump`)
- Quality: neural power (pillar: neural, category: power)
- Procedure: 3 attempts, measured heel-to-start line, best counts. 2 practice jumps at ~80%.
- Rest: 90 s between attempts
- Equipment / location: bodyweight / gym
- Safety: Stop if any knee/Achilles pain. Stick the landing; no attempt counts if you fall back.
- Metric: distance (cm); scoring: `best_of`
- Conditions: Same floor (gym turf), same shoes, fresh: first after warm-up.

## Hinge 3-5RM (current hinge rung) (`hinge_rm`)
- Quality: maximal strength (posterior chain) (pillar: force, category: strength)
- Procedure: Work up in 4-6 sets to a 3-5RM at RPE 9 (1 rep in reserve). No grinding, stop on any technique break or back discomfort > 2/10.
- Rest: 3 min
- Equipment / location: trap_bar / gym
- Safety: Rep-max only, never a true 1RM. Belt optional. Stop on pain > 2/10.
- Metric: e1rm (kg); scoring: `epley_e1rm`
- Variant factors (to reference `trap_bar_deadlift_high`): trap_bar_deadlift_high x1.0, trap_bar_deadlift_low x1.05, block_pull x1.08, conventional_deadlift x1.1

## Squat 5RM (current squat rung) (`squat_rm`)
- Quality: maximal strength (knee dominant) (pillar: force, category: strength)
- Procedure: Work up to a 5RM at RPE 9 on the current squat rung (box height recorded).
- Rest: 3 min
- Equipment / location: safety_squat_bar, power_rack, plyo_box / gym
- Safety: Safeties set. Stop on back discomfort > 2/10.
- Metric: e1rm (kg); scoring: `epley_e1rm`
- Variant factors (to reference `ssb_box_squat`): ssb_box_squat x1.0, ssb_squat x0.97, high_bar_back_squat x0.92

## Neutral-grip DB press 5RM (`db_press_5rm`)
- Quality: upper-body pressing strength (pillar: force, category: strength)
- Procedure: Work up to a 5RM (per-hand dumbbell) at RPE 9.
- Rest: 2-3 min
- Equipment / location: dumbbells, flat_bench / gym
- Safety: Shoulder pain > 2/10 ends the test.
- Metric: e1rm (kg); scoring: `epley_e1rm`
- Variant factors (to reference `db_bench_press_neutral`): db_bench_press_neutral x1.0

## Strict pull-ups, max reps (`pullups_max`)
- Quality: relative pulling strength (pillar: force, category: strength)
- Procedure: One set, dead hang start, chin over bar, full lockout each rep. No kipping.
- Rest: n/a
- Equipment / location: pullup_bar / gym
- Safety: Stop on shoulder pain > 2/10.
- Metric: reps (reps); scoring: `max_reps`

## 30-minute solo time trial (`run_tt_30`)
- Quality: threshold (LTHR, threshold pace) (pillar: aerobic, category: run)
- Procedure: 15 min easy + 4 strides, then run 30 min as hard as you can sustain evenly. Lap at 10:00. Avg HR and pace of the final 20 min give LTHR and threshold pace.
- Rest: n/a
- Equipment / location: bodyweight / outdoor
- Safety: If you have not run consistently, the coach may substitute run_submax_drift. Stop with any chest pain, dizziness or calf/Achilles pain.
- Metric: threshold_pace (s_per_mi); scoring: `lthr_from_last20`
- Indoor variant: {'route': 'gym_treadmill', 'incline_pct': 1.0, 'location': 'gym'}

## Submaximal Zone 2 drift run (40 min) (`run_submax_drift`)
- Quality: aerobic fitness estimate (low risk) (pillar: aerobic, category: run)
- Procedure: 10 min easy, then 30 min at a locked HR (≈ 75% of estimated max). Record pace for each half.
- Rest: n/a
- Equipment / location: bodyweight / outdoor
- Safety: Use when a full 30-min TT is judged too risky after a low-volume period.
- Metric: threshold_pace_estimate (s_per_mi); scoring: `submax_estimate`

## 60-minute Zone 2 cardiac drift test (`z2_drift_60`)
- Quality: aerobic durability (pillar: aerobic, category: run)
- Procedure: 60 min at a locked Zone 2 pace (flat course or treadmill 1%). Compare HR:pace between halves.
- Rest: n/a
- Equipment / location: bodyweight / outdoor
- Safety: Abort if HR exceeds the Z2 ceiling + 10 bpm.
- Metric: drift_pct (pct); scoring: `cardiac_drift`

## 2 km row (`row_2k`)
- Quality: engine (aerobic power) (pillar: glycolytic, category: engine)
- Procedure: Damper 5-6 (drag factor 120-130 recorded). Even split strategy.
- Rest: n/a
- Equipment / location: rowerg / gym
- Safety: Neutral spine at the catch; stop on back pain.
- Metric: time (s); scoring: `row_watts`

## Echo bike 10-minute max calories (`bike_10min`)
- Quality: engine (glycolytic power) (pillar: glycolytic, category: engine)
- Procedure: 10 min for max calories, even pacing.
- Rest: n/a
- Equipment / location: echo_bike / gym
- Safety: None beyond standard.
- Metric: calories (cal); scoring: `max_reps`

## Coach Benchmark A (repeated exactly) (`benchmark_wod`)
- Quality: mixed-modal capacity (pillar: glycolytic, category: engine)
- Procedure: 4 rounds for time: 500 m row, 15 KB swings (53 lb), 10 box step-overs (24 in), 10 burpees. 20 min cap.
- Rest: n/a
- Equipment / location: rowerg, kettlebells, plyo_box / gym
- Safety: No overhead work, back-friendly hinge.
- Metric: time (s); scoring: `time`

## Past CrossFit Open workout repeat (`open_repeat`)
- Quality: Open readiness (pillar: glycolytic, category: engine)
- Procedure: Workout chosen by assess at block start; must pass the shoulder rules (no fatigued high-rep overhead snatching; substitute if needed). Repeat exactly at block end.
- Rest: n/a
- Equipment / location: bodyweight / gym
- Safety: Movement substitutions respect current rungs and skills.yaml.
- Metric: score (reps); scoring: `max_reps`

## Hyrox simulation segment (fixed) (`hyrox_sim`)
- Quality: compromised running / Hyrox engine (pillar: glycolytic, category: engine)
- Procedure: 4 x [1 km treadmill run + station]: 1000 m SkiErg, 50 m sled push (Torque Tank M1, fixed resistance), 50 m sled pull, 1000 m row. For time.
- Rest: n/a
- Equipment / location: treadmill, skierg, sled, rowerg / gym
- Safety: Standard.
- Metric: time (s); scoring: `time`

## Body composition (7-day average) (`body_comp`)
- Quality: body composition (pillar: body, category: body)
- Procedure: Withings scale every morning after the bathroom, before food. 7-day average weight and body fat %; waist at the navel, relaxed exhale; optional progress photos (never in git).
- Rest: n/a
- Equipment / location: n/a / home
- Safety: Bioimpedance body fat is noisy: use the trend. Optional DEXA for an anchor.
- Metric: weight_kg (kg); scoring: `seven_day_avg`

## RHR / HRV baselines (28-day) (`vitals`)
- Quality: autonomic baseline (pillar: body, category: body)
- Procedure: Computed from Whoop: 28-day mean RHR and ln(rMSSD).
- Rest: n/a
- Equipment / location: n/a / home
- Safety: n/a
- Metric: rhr_bpm (bpm); scoring: `rolling_baseline`

## Scoring formulas
- `epley_e1rm`: e1RM = load x (1 + (reps + RIR)/30); RPE 9 => RIR 1.
- `lthr_from_last20`: LTHR = average HR of the final 20 min; threshold pace = average pace of the final 20 min; heat/cold adjustment 0.6 s/mi per F above 60 F, 0.3 s/mi per F below 40 F (comparable value only).
- `submax_estimate`: threshold pace ~ Z2 pace / 1.25, LTHR ~ avg HR / 0.80 (low confidence).
- `cardiac_drift`: HR:pace drift between halves, pass < 5%.
- `row_watts`: watts = 2.80 / (s per m)^3.
- `seven_day_avg`: Withings 7-day average weight and body fat % (trend over absolute; optional DEXA anchor).

## Gap analysis
Results are compared with `athlete/config/benchmarks.yaml` (relative to bodyweight; e.g. trap bar ~2.0-2.25 x BW, SSB squat ~1.6-1.75 x BW, 12-15 strict pull-ups, ~7:00/mi threshold, ~3.4 W/kg 2k row). The weakest pillar(s) inform the next block's primary goal, weighed against the block's planned focus; the proposal states the trade-off and needs approval.
