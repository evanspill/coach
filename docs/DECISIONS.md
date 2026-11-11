# Decisions

Each entry: **decision** - why - how to reverse.

## Calendar and planning
1. **Block 1 ends one week after the final Open workout** (`season.yaml` B1 `end_after_event.weeks_after: 1`): Block 1 = 2026-11-23 -> 2027-03-14, transition week 03-08..03-14, Block 2 starts 03-15. - The Open itself is the peak; a retest the week after is realistic, and it lets the 120-day simulation (from 2026-11-16) include a full transition week with retest and review. - Set B1 `length.end_after_event.weeks_after: 2` in `athlete/config/season.yaml` and run `coach macrocycle regenerate`.
2. **Block 3 = 13 weeks; Block 4 = 3-week taper (race week included) + 2 reset weeks**; Block 2 fills the gap. - Matches the illustrative dates. - `athlete/config/season.yaml` block lengths.
3. **Deloads count back every 4th week from the transition week**, never in competition weeks, earliest in week 3, and a gap-filler guarantees no 5-week span without a deload-like week (the previous block's transition counts as week 0). - Brief's 3:1 rule. - `engine/deloads.py`.
4. **Reactive deload trigger**: Red on >= 3 of the last 5 days (`sustained_red_days/window`) or any joint >= 4. It turns *next* week into a deload and re-spaces later deloads; joint >= 4 applies immediately, otherwise it is a proposal. Not applied if this/next week is already a deload, transition, competition or taper week. - Brief section 2.4. - thresholds in `athlete_context.json`.
5. **"No hard lower-body lifting within 24 h before the long run" = not on the calendar day before.** - Sessions all start 09:00-10:00, so "24 h" is ambiguous by minutes. - `validator.py` `LONG_RUN_LOWER_24H`.
6. **Forbidden back-to-back pairs**: glycolytic/threshold/long-run combinations and heavy lower on consecutive days (list in `validator.FORBIDDEN_BACK_TO_BACK`). - Brief left the list open. - edit the list.
7. **Pillar rule read as "each pillar must reach its MED"** (the brief's "every pillar is below its MED" reads as a typo given "all four pillars are touched every week"). Competition and deload weeks use `deload_med`; baseline, transition, reset and illness weeks are exempt. - `validator.py` `PILLAR_MED`.
8. **Tests are spread so strength, run and engine never share a day.** Baseline: Mon power+lower, Tue upper, Thu run TT, Sat 2k row. Transition: Thu run TT, Fri strength+jump, Sat engine (deload Mon-Wed). Red on a test day moves the test within +/-2 days inside the week (never next to a conflicting test); otherwise it is postponed and flagged. - Brief section 2.5.
9. **Block-goal heuristic (fallback)**: primary = the block's focus test with the biggest gap to the hybrid benchmark (+7.5% e1RM for lifts, +25% pull-up reps, -3% threshold pace); guardrails: Block 1 threshold pace no slower than +10 s/mi plus a weight-loss-rate guardrail. With the fixtures this picks **pull-ups (9 -> 11)** for Block 1. Claude makes the real proposal and may choose differently with a stated trade-off.

## Running
10. **Long run <= 30% of weekly miles only from 20 mi/week; below that the limit is 40%.** - With 3 runs and 10-12 mi/week (return-to-running ramp) 30% is impossible. - set `long_run_rule_min_weekly_miles: 0`.
11. **Block 1's 75-110 min long run is reached with a Z2 bike extension after the run.** - 12-15 mi/week can't hold a 75+ min run; impact stays low. - `plan_week.long_run`.
12. **The +10% weekly rule uses the average of the last 3 "normal" weeks (deload/transition/taper/reset/illness weeks excluded) with the ramp start (10 mi) as a floor.** - Otherwise a deload would force a smaller week after it, and a returning runner could never reach the 10-12 mi start. - `engine/running.py`.
13. **Marathon-pace finish only on long runs >= 8 mi and capped at 25% of the run.** The long run may also grow at most **1 mi per week** over the last normal week (`long_run_max_increase_mi`); the planner moves any surplus to another run. - Common coaching practice; caps the single biggest impact session as volume ramps. - Avoids MP-heavy short long runs early in the ramp.
14. **Default zones until the first TT: LTHR 165, threshold 8:00/mi.** Zones: Z2 = 75-84% LTHR; T = 98-102% of threshold pace (`engine/paces.py`).

## Readiness and safety
15. **HRV band = 60-day mean of ln(rMSSD) +/- 0.5 x SD of the daily values**; needs >= 14 baseline days and >= 3 of the last 7. - Standard approach; with this SWC the 7-day trend is sensitive, so Red days from "HRV below band 3 days" happen after real dips. - `hrv_swc_sd`.
16. **A single joint rated 3 makes the day Yellow** (Green requires joints <= 2). **Joint flags clear after 2 consecutive check-ins <= 2.**
17. **Safety downgrades apply immediately** (Red -> Z1 + mobility, illness, red flags) even though `manual_if` lists `session_type_swap`; `manual_if` governs non-safety swaps (e.g. "swap today's pressing"). - Waiting for approval to *reduce* risk makes no sense.
18. **Missing Whoop recovery -> state `unknown`, day `waiting_for_recovery`**; the planned session stays in Hevy/Garmin, the 9:05 catch-up finalizes.
19. **Red flags are detected by keyword (chest pain, fainting, breathlessness, numbness/radiating pain, sharp/worsening joint pain, dark urine)** and write `athlete/data/health.json`; all training stops until the athlete says a doctor cleared them (`cleared_on`). Illness: below the neck -> rest; above -> easy only.

## Movement readiness and skills
20. **Advance = 3 clean exposures (pain <= 2/10, no next-morning stiffness rise) AND >= 14 days at the rung.** The unrestricted top rungs (floor deadlift, back squat, barbell bench, barbell strict/push press, Olympic lifts from the floor, kipping) also need **21 days at the rung below and a recorded form check** (coach video review or physio OK, `coach form-check <family>`). - Criteria-based progression with pain monitoring is standard rehab practice; connective tissue adapts more slowly than muscle, and with a back/shoulder history the last rungs deserve an outside look. In the first simulation the floor deadlift arrived by week 9, which a good coach wouldn't allow without a form check. - `min_days_before` / `form_check` per rung in `movement_progressions.yaml`.
21. **All families start at rung 0.** Starting rungs are re-set after the baseline week / physio assessment.
22. **A region flag (>= 3 twice) drops every family mapped to that region one rung, once per flare, with a one-week hold.**
23. **Skill levels move one step at a time; "competent" also needs the gating rung.** Skill levels are normal coaching progress (written by `technique`), not a locked config change.

## Loads, nutrition, data
24. **Loads are stored in kg (Hevy's unit) and rounded in lb** to what the gym has: 45 lb bar / 60 lb trap bar / 65 lb SSB (assumed; verify), 1.25 lb per side, DBs 5-100 lb in 5 lb steps, KBs 26/35/53/70 lb only (> 70 lb -> swap to DBs). Cable/machine work is RIR-based from the last used weight. - `athlete/config/equipment.yaml` `loading`.
25. **Progression**: +2.5% when every work set hit target reps at >= target RIR - 0.5; hold after one miss; -5% after two. The pain rule (-15%, 3 s eccentric for 2 weeks) overrides.
26. **Carb tiers**: high on lower/full/long/quality/Hyrox/metcon/test/competition days and the day before the long run; moderate on upper/easy/sprint days; low on recovery/rest. If MacroFactor's weekly total leaves room beyond the desired carbs, the surplus goes to fat (still calorie-neutral). Until nutrition data is connected the weekly target is `athlete/data/macrofactor.json` (told in chat) or 33 kcal/kg/day.
27. **Check-in source priority: Intervals.icu fields > Hevy-note tag > chat.**
28. **Metrics are JSON lines per month** (`athlete/data/metrics/YYYY-MM.jsonl`); daily values merge across sources; sessions are re-merged over a 3-day overlap each sync so late uploads merge without duplicates. Gear is a snapshot (`metrics/gear.json`).
29. **Session merge**: same day, start within +/-15 min, compatible activity type; HR/strain from Whoop, sets from Hevy, pace/dynamics from Intervals. Time-in-zone is approximated from average HR against LTHR until per-second data is used (noted as approximate).
30. **Config lock** fingerprints thresholds, weather rules, nutrition rules and progression rules. `coach.yaml` (pause, approval mode, push) is the athlete's own switchboard and is not locked.

## Integrations and simulation
31. **Mocks normalize raw-shaped fixtures with the same code as the live clients.** Fixtures (generated by `scripts/generate_fixtures.py`) span 2026-09-17 -> 2027-03-21: 60 days of pre-baseline history (baselines, starting loads) plus the season. Live clients are written against the public docs and must be verified in Phase 2.
32. **Live clients send no credentials**; the cloud proxy injects network secrets. Optional env vars exist only for local testing. Intervals.icu athlete id `0` = the key's owner.
33. **The simulation's athlete** does what the coach prescribed (or misses it per the script), logging raw Hevy/Intervals/Whoop payloads; lifting RPE comes from a hidden "true e1RM" that grows ~0.4%/week, so progression and holds are earned. Proposals are auto-approved by the simulated athlete, except `learn` trials (left pending to show the approval flow).
34. **Recovery sessions are at `home`** (own foam roller, bands, lacrosse ball, Theragun); a `home` location was added to `equipment.yaml`. A few bodyweight/band exercises were added for travel days.
35. **Open workouts are unknown until released**: the competition session ships with an empty movement list and a scaling rule; `compete` fills it in after Thursday's release.

## Generic engine (configuration split)
36. **The engine holds no athlete- or season-specific content.** The year's shape (blocks, anchors, run ranges, pillars, hard-set ranges, key sessions, main lifts, goal tests and guardrails, week templates per week type) is `athlete/config/season.yaml`; session content (session and week templates, warm-ups, cool-downs, item sets, metcon pools, accessory fillers, skill practice, training rules such as required warm-ups and forbidden back-to-back pairs, carb tiers, Yellow/Red replacements) is `athlete/config/training.yaml`. Test schedule days, test slots/stress/direction/goal size and the test-block prescriptions are in `tests.yaml`; related-lift e1RM estimates in `exercises.yaml` (`estimate_from`); skill drills and chat milestones in `skills.yaml`; family aliases in `movement_progressions.yaml`; check-in regions and their Intervals.icu fields, default zones, peri-workout and recovery wording, intake questions, notes seed, race gear checklist and emergency number in `athlete_context.json`. `config.py` cross-checks every reference. - Lets the engine move to its own repo; changing the training approach is a config change, not a code change.
37. **Check-ins store joints as a map** (`joints: {region: 1-5}`), with regions defined in `athlete_context.json`; readiness and joint flags work over whatever regions exist. - The three regions were specific to this athlete.
38. **The validator rule `WARMUP_MCGILL` is now `WARMUP_REQUIRED`**, checking `rules.required_warmup.lower_body` from `training.yaml`.
39. **A bundled demo athlete** (`src/coach/demo/config` + `demo/fixtures`) is what tests and `coach simulate` use, so engine tests never depend on the athlete's own `athlete/config/`. `coach simulate --config active` replays the demo fixtures against the active config; CI runs both, plus `coach validate config`. Right now the demo config is a copy of this athlete's config.
40. **Config refactor re-recorded the config lock as `initial`** (`athlete/data/config_lock.json`): adding `long_run_max_increase_mi` and the per-rung gates changed the locked fingerprint. This was an athlete-requested code change, not an unapproved threshold change.
41. **No hosted database for now; one repo.** Git keeps the records, but code and athlete data are separated inside
    the repo (`src/coach/` vs `athlete/config/` + `athlete/data/`) and all data goes through `coach.store`, so a
    database is one new backend later (`docs/DATA_MODEL.md`). Supersedes the earlier two-repo idea.

## Data sources
42. **Whoop stays a direct API integration, through a token broker.** Whoop is worn 24/7 (the Garmin only on runs), so
    it's the only HR/strain source for gym sessions, and the direct API has last night's recovery ready for the
    8:25 run. Intervals.icu's native Whoop sync was rejected: wellness only (no workouts) and it polls about every
    8 h. Cost: hosting the broker (a free Cloudflare Worker by default), which also serves Withings. - To reverse,
    read recovery from Intervals.icu wellness and drop per-session Whoop HR.
43. **Intervals.icu stays, for runs only.** It carries Garmin run detail (pace, Running Dynamics, training load,
    shoe mileage) and is the only practical way to put planned run workouts on the watch: Garmin's Training API is
    business-only and the personal key is read-only. Considered: Garmin personal key (read-only, could replace the
    run-data part later), unofficial Garmin libraries (fragile, outside Garmin's terms), TrainingPeaks (partner-only
    API), Strava (no workouts to the watch, no Running Dynamics).

## Data model
44. **Code / integrations / athlete data are separate packages and folders**: `models/` (schemas), `store/` (the only
    reader/writer of `athlete/data/`, via a collection registry), `integrations/` (+ sync and push), `engine/`
    (calculations + validator, no I/O), `coaching/` (daily run, context, proposals, skill stand-ins). Proposals target
    `collection/key` refs instead of file paths.
45. **Journal-style records added where they change decisions** (`docs/DATA_MODEL.md` has the reasoning): Hooper-style
    morning wellness (sleep quality, fatigue, stress, soreness, mood, motivation) on check-ins; Foster session load
    (sRPE x minutes, monotony, strain) in reports and the weekly review; `JournalEntry` (reflections, wins,
    struggles, life events); `HealthEvent` history (red flags, illness, injuries, with who cleared them) replacing
    `health.json`; `Availability` (travel, closures, busy days), applied automatically to the Sunday plan;
    `EventResult`, `LabResult` per marker, `Measurement`; `Note` records (rendered to `notes.md`). Morning wellness
    does **not** change the readiness colour yet: that would change the agreed rules, so it would start as a
    `learn` trial.
46. **The VBT baseline is computed** (median top-set bar speed over the last 6 weeks, at least 3 readings) instead of
    being a stored setting.

## Coaching audit (evidence pass)
47. **Loads come from what you can do now, not your best ever.** Working loads use the top set of the most recent
    exposure within 21 days; after a longer gap, the best of the last 8 weeks x 0.95 (strength detraining is small
    over 3-4 weeks but real). Warm-up sets never count. - Reverse: `current_e1rm(recent_days=..., layoff_factor=1.0)`.
48. **Primary lifts get a computed warm-up ramp** (~50% x5, 70% x3, 85% x1, rounded to real plates), pushed to Hevy
    as warm-up sets. Standard coaching practice; it removes a number the athlete would otherwise guess.
49. **New validator rules.** `SESSION_LENGTH` (training.yaml `max_session_minutes`, long runs/races exempt: quality
    drops and adherence suffers in very long gym sessions), `PRESCRIPTION_INCOMPLETE` (every item needs reps/time/
    distance; loaded strength work needs RIR, so loads can be computed and effort is explicit), `REST_DAY`
    (`min_recovery_days_per_week`, overridable only with a stated `rest_days` deviation).
50. **Review flags with an evidence basis**: low energy availability (< 30 kcal/kg FFM/day over 2 weeks, IOC REDs
    2023; asked about, never auto-acted on), easy-running share < 75% over 2 weeks (80/20 intensity distribution),
    sleep < 7 h average, training monotony > 2 (Foster). Each produces a question or a focus point, not a plan change.
51. **More red flags**: palpitations / irregular heartbeat and heat-illness signs (stopped sweating, confusion) stop
    training and create a `health_events` record. Return after a fever needs >= 24 h fever-free (`docs/SAFETY.md`).
52. **Extreme cold moves quality and long runs indoors** (`weather.extreme_cold_f`, default 0 F air temperature),
    alongside the existing heat and ice rules.
53. **Protein sits at the top of the range in a calorie deficit** (ISSN 2017 position stand; lean-mass retention),
    calorie-neutral redistribution unchanged.
54. **Test results are judged against each test's typical error** (`tests.yaml typical_error_pct`): a change smaller
    than the noise is reported as "no clear change", so a block isn't called a success or failure on measurement noise.
55. **One submit path for everything Claude writes** (`coaching/records.py`, `coach record add <collection> --file`):
    fills numbers, validates, saves, writes the summary and opens the proposal in one step, and refuses invalid
    drafts with the violation list. Skills no longer describe separate save steps.
56. **Repo tooling**: pre-commit (ruff, ruff-format, whitespace/EOF/YAML/JSON checks, private-key detection),
    `.editorconfig`, `.gitattributes`, `Makefile` (`make check` = what CI runs), mypy with the pydantic plugin (the
    scenario harness is exempt from Optional checks because a missing record fails the scenario anyway), coverage
    gate at 80%, CI matrix 3.11-3.13 with least-privilege permissions, PR template.
57. **Committed `.claude/settings.json` permission allowlist (approved by the athlete)** so the unattended daily run
    doesn't stall on prompts: allows `python -m coach` / `coach` and git status/diff/log/add/commit/pull/push; denies
    force-push, `git reset --hard` and reading `.env` files. Everything else still prompts. - Reverse: delete the file.
58. **Config lock re-recorded as the initial approval** after the audit added `weather.extreme_cold_f` and the session
    rules (pre-launch, no athlete history; approved by the athlete). From go-live, threshold changes need a proposal.

## Long-term goals (athlete-approved 2026-11-10)
59. **The marathon goal is a Boston qualifier, tracked as a long-term goal**, not a single "marathon target". Config
    holds the event, the target edition (Boston 2029 to start: 36 on race day, men's 35-39 standard 3:00:00), a
    5-minute margin for the oversubscription cut-off (2024-2027 cut-offs ranged 4:34-6:51) and the BAA source. Birth
    year and month replace a fixed age, so the age group follows the edition. - Reverse: remove `goals.long_term`.
60. **Feasibility is checked at every transition week** (`goal_progress`, `coach goals --check`): required threshold
    pace vs the measured trend (assumed 8%/yr until two run tests 8+ weeks apart; observed trend capped at 12%/yr,
    both coach assumptions to recalibrate). Behind on an observed trend (not the assumed rate) -> a `goal_timeline` proposal (config patch moving the edition);
    the run-focused-season alternative goes to the annual review. Never a silent change.
61. **Race targets are stepping stones set from fitness**, proposed per marathon after each test week and approved
    by the athlete (`race_targets`), re-proposed only when the prediction moves more than the run test's typical
    error. **Race-day pacing comes from current fitness**; an approved target faster than fitness supports is not
    paced, and a long-term goal is shown but never paced.
62. **Marathon predictions carry a 10-minute penalty until the athlete has a marathon result**: Riegel's formula
    underestimated recreational runners' marathon times by 10+ min for half the runners (Vickers & Vertosick 2016).
    This makes the Boston requirement stricter for now (2:55 needs ~5:57/mi threshold, vs ~6:17/mi on Riegel alone).
    After the first marathon the penalty drops and `learn` can calibrate the exponent from the real result.
63. **`config_change` proposals without a patch record the config lock when approved**, so a change made to the
    files with the athlete's OK (like this one) is still approved, locked and in the changelog.
64. **HYROX goal: sub-1:05 in the Open division** (athlete-approved 2026-11-11; replaces the World Championships
    age-group slot, which needs winning a Pro age group and was judged too aggressive). Third-party aggregates of
    HYROX results (HYROX publishes none) put the men's Open median at ~1:27, the top 10% at ~1:10 and the top 5% at
    ~1:07; a Boston qualifier is ~11% of US marathon finishers. So ~1:10 is the like-for-like level and 1:05 a step
    beyond it (the athlete's choice). Only Open-division results count; trend from the athlete's own results, no
    assumed rate; target by the end of the 2027/28 season. The placement kind stays in the code for later.
65. **CrossFit Quarterfinals as a long-term goal** (athlete-approved): top 25% worldwide of the division in the Open
    (CrossFit 2027 season guide), Rx. Status is `building` while the Rx prerequisites are missing (bar muscle-up,
    chest-to-bar, toes-to-bar, kipping pull-ups, the Olympic lifts, overhead squat, jerk; overhead/Olympic/kipping
    families unlocked), because for this athlete the limiter is skill and shoulder/back capacity, not engine. Then
    the Open percentile trend decides. Target 2028 Open (date an estimate). - Reverse: remove the goal.
66. **Only marathon goals get automatic timeline proposals.** Placement and percentile goals move in yearly steps
    and depend on season focus, so their checks are reported and the annual review decides with the athlete.
67. **Open gymnastics skills added with shoulder-gated progressions** (athlete-approved): double-unders, handstand
    push-ups, wall walks and ring muscle-ups, each drill gated by `requires` rungs in the overhead / press / kipping
    families and tagged so shoulder and Achilles flags remove it; competence is set one level later than the minimum
    (5 strict before kipping HSPU, 3+ linked ring muscle-ups). They are also Quarterfinals prerequisites. A jump rope
    was added to the gym inventory (assumed; remove it if the gym has none).
