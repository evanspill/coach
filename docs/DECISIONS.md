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
    8 h. Cost: hosting the broker (a free Cloudflare Worker by default). - To reverse,
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
68. **HYROX goal set to sub-1:10 Open** (athlete-approved 2026-11-11, revising 64): ~1:10 is the men's Open top 10%,
    the like-for-like level for a Boston qualifier (~11% of US marathon finishers). 1:05 was a step beyond it.

## Phase 2 go-live (2026-11-11)
69. **Live HTTP calls send a fixed User-Agent (`omni-hybrid-coach/0.1`).** Intervals.icu is behind Cloudflare,
    which rejects urllib's default `Python-urllib/x.y` agent with error 1010 (403); curl worked, Python didn't.
    The agent names no person or account. - Reverse: drop `USER_AGENT` in `integrations/live.py`.
70. **`normalize.py` field mappings left on the docs-based shapes for now.** The live keys work (Hevy, Intervals,
    Open-Meteo all 200), but both accounts were empty on 2026-11-11 (0 Hevy workouts, 0 Intervals activities,
    wellness entries or gear), so there was no real record to compare. The envelopes that did come back match the
    code (Hevy `page`/`page_count`/`workouts`/`routines`; Intervals bare arrays; Open-Meteo `hourly`). Re-verify
    after the first logged Hevy workout and the first Garmin run synced through Intervals (baseline week).
71. **Whoop offline is not the same as Whoop late.** `sync` reports `whoop_offline` when the Whoop fetch failed or
    there has been no recovery for 2+ days; then the daily run finalizes the day (status `complete`) with readiness
    `unknown`, no guessed score, joint check-ins still applied, the plan as written, and the notification leads
    "NO SCORE: Whoop offline". Only a recovery that is merely late (yesterday's present) waits for the 9:05
    catch-up. Without this, a missing broker left every day `waiting_for_recovery` and the catch-up never closed it.
72. **Token broker = Cloudflare Worker + KV (`broker/`), plain JS, no dependencies.** Read-only GET allowlist,
    static `X-Broker-Key`, browser OAuth onboarding (`/auth/<provider>/start?key=`), access tokens cached until
    5 min before expiry, a 60 s KV lock around refresh, new tokens written before use, and a failed refresh marks
    `needs_reauth` instead of retrying (a rotated token can't be reused). KV is eventually consistent, so this is
    safe for one daily caller, not many; a Durable Object is the upgrade if that ever changes. Tests run with
    `node --test` against fake upstreams and are not part of `make check` (Python CI).
73. **Whoop data is never committed** (athlete-approved 2026-11-11). WHOOP's API Terms forbid permanent copies and
    databases of WHOOP data. `sync` writes Whoop's daily numbers and the Whoop part of each workout (HR, strain,
    zones, kJ) to a git-ignored cache (`athlete/data/.cache/whoop/`), keyed like the committed rows;
    `Store.daily_metrics()` / `Store.sessions()` merge it in, so no reader changed. When the cache is cold (a fresh
    container) or more than the overlap behind, sync refetches a rolling 75-day window (60-day HRV/RHR baselines +
    the 7-day trend + margin; ~20 API calls) and prunes older rows. Committed workouts keep Hevy/Garmin data only
    (run HR is Garmin's). Stored day records keep the readiness state and reasons but not recovery/HRV/RHR values;
    reasons name the rule ("recovery <= 33 two days running"), never Whoop's numbers, which also keeps them out of
    notifications. Weekly reviews say "Sleep: under 7 h on average" instead of averages; the block review drops the
    RHR trend; the `vitals` test (a stored 28-day Whoop RHR/HRV mean) is retired, since readiness computes those
    baselines live. Trade-offs: reports and reviews can only see the last 75 days of Whoop data; an old decision's
    exact numbers can't be audited; the energy-availability estimate in reviews still uses Whoop kJ as one input.
    This does not settle the AI clause of the same terms (written confirmation requested from WHOOP).
    - Reverse: write the cache rows to `metrics/` again (one flag in `sync`).
74. **No direct scale API.** The scale vendor's API terms forbid giving its data to an AI model and require a business
    account, so the scale integration, its broker endpoints and its fixtures were removed. Weigh-ins now arrive
    as Intervals.icu wellness `weight` / `bodyFat` (scale app -> Apple Health -> HealthFit -> Intervals.icu);
    field names are from the Intervals.icu docs, to verify on the first real weigh-in. The demo fixtures carry the
    same weigh-ins in wellness (same random sequence, so simulations are unchanged apart from the source). The
    broker is Whoop-only.
75. **Intervals.icu's Whoop connection as a backup** (athlete-approved 2026-11-11), off until enabled
    (`coach.yaml whoop_backup: intervals`). Intervals.icu wellness `readiness` / `hrv` / `restingHR` / `sleepSecs`
    / `sleepScore` map to recovery / HRV / RHR / sleep (docs-based names, verify once connected). They fill only
    days the direct API left without a recovery score, go to the same git-ignored cache (never committed, whatever
    the source: sync strips recovery-type fields from every committed daily row), and carry the source
    `intervals_whoop`. Off by default because Intervals.icu doesn't say which device a wellness value came from: if
    a watch worn part-time also feeds HRV/RHR, the baselines would mix devices. Trade-offs vs the direct API: no
    per-workout HR/strain/zones (gym sessions fall back to session RPE), and the import may land hours after
    waking; Intervals.icu, not the athlete, is the party bound by WHOOP's API terms on this route.
    - Reverse: `whoop_backup: none`.
76. **No API request on the minute.** Hevy's API docs ask scheduled clients not to call exactly at xx:00; applied to
    every integration: the scheduled tasks start at off-round minutes, and scheduled syncs (`coach sync --jitter 90`,
    `coach daily --fallback --jitter 90`) wait a random 0-90 s first. Interactive syncs don't wait; mock mode never
    waits. - Reverse: drop `--jitter` from the coach-daily skill.
77. **Whoop v2 verified live** (2026-11-12, via the broker). Recovery, sleep and cycle fields match the docs-based
    mapping (recovery, HRV, RHR, sleep hours/performance, day strain all present). Two fixes: sport names are
    snake_case variants (`weightlifting_msk`), so `whoop_sport()` normalises separators and the `_msk` suffix; and
    recovery activities (`air-compression-normatec`) arrive as SCORED with `score: null`, so workouts without a
    score are skipped. A 75-day refetch is 75 daily rows and ~60 workouts through the broker.
78. **Whoop backup on** (athlete-approved 2026-11-12, `whoop_backup: intervals`), after Garmin wellness download was
    turned off in Intervals.icu so its HRV / resting HR / sleep come only from Whoop. Field names verified live
    (`readiness`, `hrv`, `restingHR`, `sleepSecs`, `sleepScore`), and the values matched the direct API on all 7
    days checked (recovery, HRV, RHR, sleep). Direct data still wins; backup days are cache-only.
79. **Baseline battery reviewed against testing standards** (athlete-approved 2026-11-12). Kept: rep-maxes rather
    than 1RMs (1RM predicted from a 3-5RM within ~3 kg), high-handle trap bar for the hinge (lower lumbar moment,
    Swinton 2011), broad jump first, pull-ups, 7-day body comp. Changed: hinge and squat rep-maxes on separate days
    72 h apart (disc history; new slots `strength_lower_b`, `strength_upper_push`), durability tests after strength
    (NSCA order: power, strength, local muscular endurance, conditioning); the submax run is pace-locked on a
    motorized treadmill at 1% instead of HR-locked at 75% of an age-predicted max (~10 bpm error, Tanaka 2001), and
    its threshold estimate stays low confidence until a 30-min TT (validated to ~8 bpm, McGehee 2005); engine test
    = 10-min Echo bike instead of the 2k row (low back load, more repeatable for a non-rower; 2k reliability is high
    only in trained rowers). Added: Biering-Sorensen hold and side bridge (trunk endurance; low-back relevance,
    noisy below ~43 s), dead hang (practical grip proxy; grip strength predicts mortality, PURE 2015), an unscored
    mobility screen for starting rungs (FMS-style screens don't predict injury, Moran 2017). New scoring `max_hold`
    and `coach test score --result` for results reported in chat. Baseline hinge capped at RPE 8 this time.
80. **Carried-forward weights are not weigh-ins.** Intervals.icu repeats the last known weight on days without a
    reading (seen live: 35 of 42 consecutive days identical to the gram; every real reading came with body fat). A
    wellness weight counts only when it changes or comes with body fat; sync reads 7 extra days so the first day of
    its window can be judged. Otherwise the 7-day average and the "no weigh-in" flag would count filler.
81. **Hevy routines are built from Hevy's exercise catalog** (verified against the live API spec, 2026-11-12). Hevy
    requires an `exercise_template_id` per exercise and accepts only its schema's fields, and the coach sent neither
    ids nor a valid shape. Each library exercise now carries a reviewed `hevy_title` (a built-in Hevy exercise where
    one exists); warm-up and mobility drills share the generic "Warm Up" / "Stretching" with the drill named in the
    note; titles with no equivalent (back-extension hold, broad jump, Copenhagen planks, low-handle trap bar, SSB
    squat, metcons) become custom exercises on first push only, because free accounts allow 7. A title shared by
    several library exercises maps back to none when reading logs, so a generic set is never credited to a drill
    or a test, and `SetRecord.exercise_id` defaults to None (an unmatched set used to make the stored workout
    unreadable).
82. **Hevy push verified live: two fixes.** Creating a custom exercise returns the new id as plain text, not the
    documented JSON, so the client accepts both (one custom was created before the reply failed to parse; a
    catalog check confirmed no duplicate, and nothing is retried blindly). A test exercise's custom type follows
    its scoring (`best_of` -> distance, `max_hold` -> duration), so the athlete can log what the test scores. Dry
    runs read Hevy's catalog (no writes) so they report the custom exercises a push would really create.
83. **Planned runs carry absolute pace targets** ("9:46-10:48/mi Pace"), from the coach's zones, instead of % of
    threshold pace: the athlete's Intervals.icu run threshold pace is unset (verified live), so % targets would
    reach the watch without real paces, and the coach owns the zones anyway. Intervals.icu parses them as
    `secs/mi` steps (verified live); % of threshold remains the fallback when a segment has no pace. Test-block
    notes (e.g. "motorized treadmill at 1%") go into the event description.
84. **Code goes through pull requests; athlete state commits directly** (athlete decision, 2026-11-13). The daily
    run and chat sessions keep committing `athlete/data/` (and approved `athlete/config/` changes) straight to
    `main`, because a PR per check-in would stall the loop. Code and docs go on a branch and a PR the athlete
    merges. `main` is protected against force pushes and deletion only (GitHub ruleset set by the athlete):
    "require a pull request" or "require status checks" would block the direct state commits.
85. **Claude reviews every pull request** (`.github/workflows/claude-code-review.yml`, athlete-requested
    2026-11-13). Runs `anthropics/claude-code-action` (pinned to the v1.0.275 commit; Dependabot bumps actions weekly)
    on non-draft PRs with read-only contents and PR-comment rights, authenticated by the athlete's
    `CLAUDE_CODE_OAUTH_TOKEN` (personal Claude subscription, no separate billing). The prompt checks this repo's own
    rules (code calculates numbers, push re-validates, safety and approval rules, no Whoop data or secrets in git,
    decisions recorded) rather than generic style, which ruff already covers. It comments only; merging stays
    with the athlete.
86. **PR reviews must leave evidence** (athlete-requested, 2026-11-14). After the token fix, a re-review of PR #5
    ran 15 s and 5 turns and posted nothing, so a quiet pass could not be told apart from a skipped one. The
    review workflow now sets `show_full_output: true` (the repo is private; the log shows what was read), reviews
    the whole PR diff, re-checks every earlier finding, and always posts one summary comment that names the head
    commit it reviewed. No summary for the head commit = the review did not really happen. Workflow changes take
    effect only once on `main` (the action checks the workflow against the default branch).
    - Reverse: drop `show_full_output` and the summary rule from the prompt.
87. **Trend weight = EWMA of daily weigh-ins** (spec section 7; built 2026-11-14). `engine/bodycomp.py`: 10%/day
    exponential smoothing (the classic "Hacker's Diet" trend), a gap of n days counted as n steps, duplicates on a
    day averaged; the weekly rate is the trend change over the last 14 days. It replaces 7-day means in
    `Context.bodyweight_kg()` (macros and grams-per-kg), the calorie-phase choice (body fat trend), the weekly review
    ("Trend weight ... kg/week"), the block review, and `coach report weight` (`trend_weight_kg`). The
    `body_comp` test keeps its 7-day average (its protocol). Staleness (`STALE_DAYS` = 21): a body-fat trend whose
    last reading is older than that no longer picks the calorie phase (falls back to recomp and says why); trend
    weight is still used for macros when stale (it beats the 95 kg default): `coach context` shows its age
    (`bodyweight_trend_age_days`), and after 3 days without a weigh-in sync adds "weight: no weigh-in since ..." to
    the day's stale sources, which the morning notification prints on its "Data:" line. A block review starts the
    trend at block start, or at the first day with `MIN_READINGS` (5) readings if the block began with the first
    weigh-ins, and says so; it names an end trend older than `STALE_DAYS` as stale. The history is read once per
    `Context`.
    - Reverse: point `bodyweight_kg()` back at the mean.
88. **Shadow mode ended after the supervised push test** (athlete decision, 2026-11-14): `push.enabled: true`.
    The push paths were verified live (Hevy routines and custom exercises, Intervals.icu events with absolute
    paces), weekly plans still need the athlete's approval before anything is pushed, and there is no parallel
    human-coach program to compare against. The scheduled-task prompts were updated to match. Approval: the
    athlete's own instruction in the setup session ("Turn off shadow mode"), committed to main as 717821c; an
    athlete-initiated config change is its own approval, so no coach proposal was opened. docs/BUILD_PROMPT.md is
    the original build brief and keeps its 4-week shadow plan as history.
89. **Engine review fixes** (code review of `src/coach/engine`, 2026-11-14):
    - Progression: a work set logged without RPE/RIR is judged on reps alone (its e1RM already assumes 0 RIR);
      before, a missing RIR counted as a miss, so an athlete who skipped RPE had loads cut 5% every session.
      This loosens progression for an athlete who never logs RPE: loads then rise +2.5% whenever the target reps
      are hit, with no effort check. Accepted because the e1RM behind each prescription treats an unlogged set as
      all-out, which keeps the starting load conservative; logging RPE restores the RIR check.
      Sessions with only warm-up sets of the exercise no longer count as exposures.
    - Illness parsing: a bare "cold" is weather; "a/my/have cold", "caught (a/the) cold", "cold symptoms",
      "cold and/with ...", "head cold", "cough" and the other above-neck symptoms count, and "flu" stays
      below-neck. "Sick"/"ill" still do. "A cold run/shower" still matches, which fails safe.
    - `RUN_INCREASE` uses `thresholds.weekly_run_increase_pct` instead of a hard-coded 10% (same value today).
    - Test stress for lower-body rules comes from the config being validated, not the active athlete config.
    - Unnamed next-morning stiffness goes to the first configured region (was hash-order dependent); an AMRAP
      score with "+ N reps" is `rounds_reps` even when a time cap is in the text; a 5th-weekday race date rolls to
      the last such weekday next year; Red-day test rescheduling sees every test slot on a shared date.
    - Reverse: revert the commit; no data migration.
90. **Store and model review fixes** (code review of `src/coach/store` and `src/coach/models`, 2026-11-15):
    - `new_id` returns one past the highest `<day>-<kind>-<n>` in use. Counting the keys handed out an existing id
      after a gap (a deleted or hand-numbered record), and the next `put` overwrote it.
    - A `red_flag` health event resolves only with `cleared_by: doctor` (docs/SAFETY.md: a doctor's clearance
      ends one), and no event resolves before it starts. Before, `coach health resolve` defaulted to
      `--by athlete` and cleared a red flag with no doctor. The check runs when JSON is validated
      (`coach record add`, loading from disk), and `coach health resolve` re-validates the resolved record and
      returns an error instead of saving. A stored record that breaks the rule now fails to load, loudly, rather
      than being treated as cleared; there are none today.
    - Availability rejects `end < start`; check-in `session_pain` must be 0-10.
    - Collection keys can't contain `/`, `\`, a null byte or a leading `.`, and composite keys must be `a:b`, so a
      record id can't write outside its collection.
    - Report collections (`event_plans/<race>`) go through `put`/`get` as markdown, not JSON.
    - Deleting a note re-renders notes.md; `same_as` chains in training item sets are followed (a cycle is an
      error); metric reads skip month files outside the date range.
    - Left as is: `query()` loads a whole collection before filtering by date. Filtering by key only works for
      date-keyed collections, so it stays generic.
    - Reverse: revert the commit; current athlete data passes the new checks (no health events or availability
      records yet).
91. **Integrations review fixes** (code review of `src/coach/integrations`, 2026-11-15):
    - Sessions are re-merged and the window replaced only when both Hevy and Intervals answered. Before, a Hevy
      failure became an empty list, Intervals' activities alone triggered the replace, and committed Hevy
      sessions in the window were deleted. With either missing, nothing is deleted: the answered source's sessions
      are added, except any starting within 15 min of a committed session (possibly the stored half of a
      Hevy/Garmin twin), and the report's `sessions_partial` names the missing source. `last_sync` is held, so
      the next sync where both answer replaces the window and merges any twin. A source that never answers (an
      expired key) therefore doesn't block the other's sessions; it shows up in `errors` and `window_held_by`.
      Whether a source is configured can't be read from its key variable: in the cloud environment the proxy
      injects the Hevy and Intervals credentials, so the variables are unset while the APIs work.
    - `last_sync` only advances when every committed source (nutrition, wellness, Hevy, Intervals activities)
      answered, so an outage longer than the 3-day overlap no longer loses those days. The window is capped at
      a first sync's 75 days so a source that never recovers (an expired key) can't grow it without limit, and
      the report's `window_held_by` names the sources holding it back.
    - The nutrition fetch contributes kcal and macros only. It has no weight lead-in, so its carried-forward
      first-day weight was being stored as a weigh-in.
    - A Hevy/Intervals twin keeps every field either half has (pace, dynamics, training load, notes from both),
      and the Hevy check-in tag is read from Hevy's own notes. Before, a Garmin activity started a few minutes
      before the Hevy workout dropped the tag.
    - `coach push` saves Hevy routine ids even when a later routine fails, so a re-push doesn't duplicate them.
      A routine deleted in the Hevy app (PUT answers 404) is created again instead of failing the whole push.
    - Whoop: day strain only from a finished cycle (live matched the mock); `nextToken` is URL-encoded.
      Intervals laps without HR or distance are skipped instead of failing the whole activities fetch.
    - Left as is: the live nutrition source refetches the Intervals wellness endpoint the sync already read (one
      extra HTTP call per sync); sharing it would couple two sources for little gain.
    - Reverse: revert the commit.
92. **Coaching, CLI and config review fixes** (code review of `src/coach/coaching`, `cli.py`, `config.py`,
    2026-11-15):
    - Approvals can't be bypassed by a draft: `coach record add week_plans` saves a draft as pending unless that
      week's stored plan is already approved and every session keeps its date and type (a swap within a day,
      like adjust-day's small changes). Moving, adding or dropping a session needs the athlete's OK again.
      Content inside a same-day session (exercises, run volume) can still change without re-approval, as
      adjust-day's swaps always could; `coach validate` still runs on every save and push. A block-goal draft stays approved
      only if it is identical to an approved stored goal. `coach approve initial-config` works once; after that
      only an approved proposal moves the config lock. Only pending proposals can be rejected.
    - Movement exposures are logged at most once per family per day (`FamilyState.last_exposure_date`); before,
      the 9:05 catch-up re-logged yesterday's sets, so a painful session regressed two rungs and clean sessions
      counted twice. A later report that makes a logged clean exposure unclean (pain or stiffness filed after the
      first run) replaces it, so the pain rule still applies, once. If that clean exposure had advanced the
      family, the advance is withdrawn (back to the rung trained, held 7 days); a further regression waits for
      the next painful exposure, since one run moves a family one rung at most. The catch-up still runs rehab (for late
      reports and joint flags) but skips the Sunday and monthly work the 8:25 run already did.
    - A config patch that leaves the config unloadable is undone and the proposal stays pending.
    - An approved race target stays in force until a new one is approved (the new one waits in the proposal).
    - A transition week with no scored tests skips the block goal (logged) instead of crashing the daily run.
    - The weekly and block mileage ramps use `thresholds.weekly_run_increase_pct` (10% today, unchanged).
    - The log skill's neck check uses `classify_illness` directly (cough, chills, vomiting, stomach bug ...), but
      exertional nausea tied to a named workout ("almost threw up during the burpees") is effort, not illness;
      "threw up after dinner" still counts.
    - Smaller: a refill clears stale warm-up ramps; carb tier on a day record accounts for tomorrow; tests on
      the day after a Red day are rescheduled, not dropped; skills never demote from a chat milestone; family
      metcon movements get the competence gate; CLI errors return JSON; config cache keyed per file.
    - Left as is (config-defined or cosmetic): skills.yaml and YAML config patches lose comments when rewritten;
      a few messages hard-code the cadence range and heat numbers instead of reading config.
    - Reverse: revert the commit; `last_exposure_date` defaults to None, so stored data loads either way.
93. **Simulation and demo review fixes** (code review of `src/coach/sim` and `src/coach/demo`, 2026-11-15):
    - `coach simulate` fails on day-level problems (a plan that fails validation after the fallback, a refused
      push), not only on failed scenarios. Before, CI's active-config run logged a failing plan and still passed.
    - That exposed a real planner gap: a deload (or heavily capped) week could fall below the aerobic pillar's
      minimum effective dose, because the long-run erg extension only runs in training weeks. plan-week now covers
      the shortfall with zero-impact Z2 bike after the long run (or an easy run), rounded up to 5 min.
    - Scenarios that couldn't fail now can: empty lists no longer pass the sick-day, travel and pillar checks,
      the deload check needs volume in the normal week, and the adherence dip logs real sessions.
    - `sandbox(out_dir)` refuses a folder whose `athlete/` it didn't create (it used to delete it), clears a
      caller's pretend date, and removes temp homes in tests; the catch-up keeps the 08:25 run's log; simulated
      runs log the shoe the coach picked.
    - Left as is: the demo's late-recovery day 2026-12-10 never exercises the catch-up (HRV alone rates it
      Yellow), and the 120-day demo window has no quality runs. Both are fixture coverage, not code bugs.
    - Reverse: revert the commit.
94. **Hevy logging: how-to notes, left/right supersets, inch-logged jumps** (athlete request, 2026-11-16):
    - Hevy's public API can create a custom exercise (title, type, equipment, muscles) but can't set its description
      or media. So library exercises take an optional `description` and `video_url`, and `coach push` appends them
      to that exercise's routine notes ("How ... Video: url"). The how-to text and links live in `exercises.yaml`.
    - Per-side work (`per_side: true`) is pushed as two exercises in a superset, `X (Left)` and `X (Right)` (custom
      exercises, the same pattern Whoop uses), instead of one exercise with "per side" in the note. Sync strips the
      suffix, maps both to the library exercise and stores `SetRecord.side`; per-side holds (side bridge) score
      left/right from the sides, falling back to logged order for older logs.
    - Hevy's API returns `distance_meters` as an integer, so a 2.13 m broad jump came back as 2 m. Exercises with
      `hevy_log: inches` (broad jump, standing reach, jump-and-touch) are logged as a separate custom exercise
      `Name (in)` of type reps-only, with the measurement in inches in the reps box; sync converts it to metres.
    - Test extraction ignores warm-up sets (the 20 s warm-up side planks were being read as side-bridge attempts).
    - Hevy has no official per-hand/total convention for dumbbells; the coach stays per hand (one dumbbell), which
      is what the routine pre-fills.
    - Reverse: revert the commit. Old logs still map (no suffix = no side); custom exercises already created in
      Hevy stay and can be archived in the app.
95. **Rest on every exercise, belt guidance, DB/KB pairs logged as totals** (athlete request, 2026-11-16):
    - Every set-based exercise gets a rest: the plan's `rest_s` wins; otherwise `training.yaml rules.rest_s` by block
      kind (the stimulus) and `rest_primary_s` for primary lifts. `Filler` writes it into the plan and `coach push`
      uses the same rule, so older plans without rests still push with them. Per-side supersets rest
      `side_switch_s` after the left side and the full rest after the right.
    - Belt (`rules.belt`, `engine/prescribe.belt_for`): only exercises with all of `tags_all` (primary + spine_load:
      hinge and squat main lifts), in strength blocks on work sets at RIR <= 2 and <= 8 reps, and the heaviest
      `test_sets` of a rep-max test. Never on warm-up or ramp sets. The routine note says which sets.
    - `coach.yaml pair_weight_logging: total`: the athlete logs a pair of dumbbells/kettlebells as the total (as in
      Whoop). Library exercises with `implements: 2` are pushed at 2x the per-implement load (the note names both),
      and sync divides logged weights back, so e1RMs, rounding and the DB rack stay per implement.
    - `pair_weight_total_since` (2026-11-16, the first workout logged as totals) gates the conversion by workout
      date, so any per-hand logs from before the switch are never halved on a later sync.
    - Review follow-ups: both sides of a per-side superset carry the full note (prefixed "Left side."/"Right side.");
      `superset_id` is sent only for those pairs (live Hevy accepted numeric ids on 2026-11-16 pushes); a per-side
      hold with only one side logged is not scored; `max_reps` also ignores warm-up sets; a library title that
      itself ends in "(Left)" maps as is; the belt needs an explicit rep count.
    - Reverse: revert the commits; `pair_weight_logging: per_implement` restores per-hand logging.
96. **Warm-up sets on every strength exercise** (athlete request, 2026-11-17; extends 48):
    - `Filler.warmups` sizes warm-ups to what the exercise's prime mover (its first listed muscle) has already done
      in the session (strength, hypertrophy, test and power blocks): primary lifts keep the full ramp (~50% x5,
      70% x3, 85% x1); the first loaded compound for a prime mover gets two build-up sets (~50% x5, 75% x3);
      isolation work or a prime mover already warm gets one feeler set (~60% x5); bodyweight strength work on a
      fresh prime mover gets one easy set of about a third of the target (2 reps before a max-reps test).
      Warm-up reps never exceed the work reps.
    - Prime mover, not every listed muscle: a deadlift's secondary back work doesn't warm the lats for pull-ups.
      Common coaching practice: the first exercise for a muscle needs a ramp, later ones a feeler at most; extra
      warm-up volume beyond that only costs work-set performance.
    - No warm-up sets for timed holds, carries, jumps/plyos, core/prehab/mobility drills and conditioning
      movements: the session's warm-up block primes those, and extra holds or jumps before a test add fatigue.
    - Machine/cable warm-ups round to 5 lb stack steps. Unknown working weights (no e1RM or history yet) get
      percentage warm-ups (`RampSet.pct`) and a load note ("warm-up ~50% x5, ~75% x3 of your working weight");
      they and bodyweight warm-ups are pushed to Hevy as warm-up sets without a weight.
    - Reverse: revert the commit (only primary lifts with a known load get a ramp again).
    - Refined after the athlete's review (2026-11-18): isolation work for a prime mover that already worked in the
      session gets no warm-up set (the first work set does that job; extra sets only add fatigue). A compound on a
      warm prime mover keeps one feeler set to check the load jump.
97. **Per-side work: split vs alternating** (athlete request, 2026-11-18):
    - Library `sides`: `split` (all reps on one side, then the other: Left/Right Hevy exercises in a superset, as
      in 94), `alternating` (sides alternate within the set: one Hevy exercise, reps logged per side), `either`
      (e.g. DB reverse lunges, step-ups: the prescription's `alternating: true` alternates, default split) and
      `none`. Every per-side exercise in the library is classified; an unclassified one still splits.
    - Every per-side note states it in plain words ("One side at a time: finish all of this side, then switch" /
      "Alternate sides each rep: 8 reps per side"). The validator (`SIDES`) rejects `alternating` on non-per-side work or against the
      library.
    - The library how-to is no longer appended when the plan's own note already carries it (same video link or
      description), which printed two descriptions on the 2026-11-17 screen redos.
    - Reverse: revert the commits; per-side work splits again everywhere.
98. **One daily scheduled run; no 9:05 catch-up** (athlete request, 2026-11-18):
    - The catch-up task fired every day but only had work when the 8:25 run left the day `waiting_for_recovery`
      (none so far), so it was a near-empty session daily. The athlete deleted it.
    - A late-recovery day still finishes everything else, stays `waiting_for_recovery` with the planned session in
      Hevy, and the notification now says "tell me when recovery is in and I'll finalize today". The athlete says so
      in chat and `coach-daily` runs in finish mode (same steps as the old catch-up; `coach daily --catchup` remains
      the deterministic version). If the session was already trained by then, finish mode records readiness,
      fuel and recovery only and doesn't re-push. Whoop offline (2+ days or a failed fetch) is unchanged: finalize unscored.
    - The simulation still models a late-recovery day finished later the same morning (its "09:05" phase stands in
      for the athlete's message).
    - Reverse: recreate the ~9:05 scheduled task and restore the notification text.
99. **HR zones from Whoop's heart rate reserve** (athlete request, 2026-11-18):
    - The athlete wants Whoop as the source of truth for HR zones. Whoop uses heart rate reserve (resting +
      fraction x (max - resting)) with its own max HR and resting-HR baseline; the coach had only LTHR-based zones from
      a placeholder LTHR of 165 (Z2 124-139), which put an easy run at 150 bpm (inside Whoop's Z2, 138-152) above Z2.
    - `running.default_zones.hr_model: hrr` (+ `max_hr`, `resting_hr` fallbacks) switches HR zones to HRR. Z1-Z5 are
      Whoop's zones 1-5 (40/60/70/80/90/100%), MP 72-80%, T 80-90%; bounds round up, so Z2 matches Whoop exactly
      and the rest are within 1 bpm. Paces still come from threshold pace; `lthr` stays as the LTHR model's value.
    - Values: max HR from Whoop's body measurement (new broker route `/v2/user/measurement/body`, cached like all
      Whoop data, never committed, decision 73), resting HR = median Whoop RHR over `rhr_baseline_days` once there is
      a week of nights; otherwise the configured fallbacks. A failed body fetch reports `whoop_body`, never Whoop offline.
    - Under `hrr` a submax drift run sets only threshold pace: its LTHR (avg HR / 0.80) assumes the run was at 80% of
      LTHR, which an easy run by HRR zones need not be (on 2026-11-18 it would have given ~188). A 30-min TT's LTHR is
      still stored. Threshold work may move to a TT-based model once there is a running base.
    - Switching the athlete's config is a threshold change: proposal, then `coach approve`. The threshold fingerprint
      covers `hr_model`, `max_hr` and `resting_hr` whenever `hr_model` isn't `lthr` (LTHR configs keep their old
      fingerprint, so existing locks stay valid). The broker must be redeployed for the max HR to sync (until then the
      configured max_hr is used).
    - The synced values move the zones without a proposal, by design: the athlete chose Whoop's auto-adjusting zones
      as the source of truth. The movement is small and slow (max HR changes only when Whoop's does; resting HR is a
      60-day median), and the daily push refreshes today's targets. The fallbacks themselves are locked.
    - Zone minutes estimated from a session's average HR (when no zone breakdown exists) use the same HRR zones.
    - Reverse: set `hr_model: lthr` (the default) or revert the commits.
100. **Standing Hevy routines** (athlete request, 2026-11-19):
    - The athlete wants the evening mobility routine in Hevy to follow along. It's the same every evening, so it is a
      standing routine, not a dated session: `coach push --routine <item_set>` builds it from a `training.yaml` item
      set (picker at location `home`), refuses anything not in the library or needing equipment the athlete doesn't
      have at home, and creates or updates one Hevy routine (id kept in `push_ids` as `hevy:routine-<name>`), titled
      "<title> (coach)". Dry-run unless `push.enabled`, like every push. It runs the session validator (the health
      gates apply; recovery-type sessions skip the structure rules) plus a library and home-equipment check.
    - Changing the item set (an approved config change) and re-running the push updates the routine in place.
    - Reverse: revert the commit; delete the routine in Hevy.
101. **Calorie efforts logged as reps in Hevy** (athlete request, 2026-11-22):
    - Hevy has no calories field (the Echo bike is a timed exercise), so the 10-min bike test score (119 cal) had
      nowhere to go and had to be reported in chat. Calorie efforts now go to Hevy as a reps-only custom exercise
      '<name> (cal)' (e.g. 'Echo bike (cal)'), the same trick as the inch-logged jumps (decision 94,
      `hevy_log: inches`): the reps box holds the calories.
    - Which items: a test-block item whose test is scored in `cal` (on the test's own exercise), or any prescription
      with `calories` set (the target is prefilled; a max-effort test leaves it empty). Warm-ups and other timed
      work on the same erg stay on the built-in timed exercise. No config change: the test's unit decides.
    - Hevy's reps-only type has no timer, so a calorie item's duration (the test's 10 min, an interval's cap) is not
      a Hevy timer any more: it is printed in the note ("10:00 effort") and the athlete times it on the erg. Calories
      are the score, so the trade is deliberate.
    - Sync maps '<name> (cal)' (also with ' (Left)'/' (Right)') back to the library exercise and stores
      `SetRecord.calories` (reps cleared); `max_reps` tests in `cal` score from the calories.
    - Also fixed: `coach test score` crashed printing its result (the zones model wasn't JSON-serialisable) after it
      had saved; the JSON encoder now serialises any nested model.
    - Reverse: revert the commit; the '(cal)' exercises can be deleted in Hevy.
102. **One home per session: the day record** (athlete request, 2026-11-22):
    - Before: the week plan held full copies of its seven sessions and each day record held its own copy of the
      adjusted session, with no rule for which one a reader used. Push read the day record; test scoring, the
      weekly review, mileage totals and the week validator read the week. A test added on the day (the 2026-11-16
      reach and jump-and-touch) was invisible to `coach test score`.
    - Now: `DayRecord` is the only place a session lives. `planned_session` is the session as the week plan wrote it;
      `session` is the session as it stands after the day's adjustments (`current_session()` = session or planned).
      New status `planned`: a day the week plan wrote that the daily run hasn't run yet.
    - The week file (`weeks/<id>/plan.json`) keeps only the week's own facts (type, targets, deviations, approval,
      rationale, focus). `Store` assembles `WeekPlan.sessions` from the seven day records when it loads a week, and
      saving a week writes each session into its day record: a day not run yet takes it as its plan; a day already
      run whose session the week changes gets it as its new plan and current session, with a `replan` change recorded
      (the old title is in the change; a re-run of the daily run or finish mode starts from the revised plan, never
      from the one the replan replaced); an
      unchanged session is a no-op. So every reader of a week sees each day's current session, and a change to a
      day is the week's change too. One session per day, inside the week (the store refuses others).
    - Planned and current stay separate on purpose: adherence (a coach-made Red-day swap is not a miss), the monthly
      calibration and the "why did Tuesday change?" answer all need what was planned as well as what was done.
      `adjust-day` starts from the planned session, never from an earlier adjustment, so a re-run or finish mode
      can't apply the same change twice. A fresh day record written without its planned session keeps the stored one.
    - Guards (review of #18): a day stopped for a red flag is never overwritten by a week save (only `coach health
      resolve` clears a stop); a week can't drop the session of a day that already ran (the save fails: replace it,
      e.g. with a rest session, so adherence and totals stay honest); every check runs before anything is written. `coach record add week_plans` reports any stopped day it kept. The save
      writes the day records one by one, then the week file: an I/O failure partway leaves some days updated (the
      logical checks all run first; git shows and reverts a partial write).
    - Deliberate consequences: the approval-shape check (a revised approved week stays approved only if every day
      keeps its type) compares against the assembled week, i.e. each day's current session, which is what the
      athlete has now; `coach push --week` pushes current sessions too (a day already adjusted goes out as
      adjusted), and `push` still re-validates. `coach status` reports `planned_session` from the day record and
      adds `current_session` when they differ; `test_day`/`tests_today` follow the current session.
    - The block outline already held per-week targets, not sessions, and finds its weeks by their start dates; it
      is unchanged.
    - Migration: `coach migrate` (also run by the daily bootstrap; idempotent) moves each old week file's sessions
      into its day records as planned sessions (a day already run keeps its adjusted session) and drops the copy.
      Reading an unmigrated week still works (its sessions fill days with no record).
    - Reverse: revert the commit; week files would need their sessions back (rebuild from the day records'
      planned sessions).
103. **Hevy routine folders: this week, one archive per block, standing** (athlete request, 2026-11-23):
    - Before: every pushed routine landed at the top level of Hevy, so the list grew by about 7 a week.
    - Verified live (2026-11-23): Hevy folders are one level deep (a folder has only id, index and title; a routine
      has one `folder_id`), so block folders can't hold week folders. The public API has no DELETE for routines or
      folders ("Cannot DELETE"). `PUT /v1/routines/{id}` with a `folder_id` moves a routine.
    - Now: `coach push` puts the current week's routines in "This week (coach)", and standing routines in
      "Standing (coach)". Each week or day push first moves routines of sessions dated before the push week (never
      today's) into their block's archive folder ("Baseline (coach)", "Block 1 (coach)", ...). Folders are created
      on first use, or found by title if they already exist. Their ids live in `push_ids` (`hevy-folder:<title>`),
      and each moved routine is marked `hevy-archived:<session id>`, so moves happen once. A routine deleted in the
      app is skipped and marked. Dry runs report the folders and moves they would make.
    - A move reads the routine from Hevy and writes the same content back with the new folder, so edits made in the
      app survive. Verified live 2026-11-23 on the baseline-week test routine (many custom exercises): the GET's set
      fields (type, weight_kg, reps, distance_meters, duration_seconds, custom_metric) went back unchanged and the
      routine read back identical apart from the folder.
    - Review of #19: a failed move (any HTTP error, a rate limit) never blocks the push. It is reported under
      `hevy_archive_errors` and retried on the next push. A session pushed again after it was archived (a
      rescheduled day) loses its archived mark, so it is archived again later. Dates outside the season or in a gap
      go to "Other (coach)", not "Baseline (coach)". Logged workouts are separate Hevy records, and the coach reads workouts, not routines, so moving
      or deleting a routine by hand loses no training data.
    - Reverse: revert the commit. Folders can be deleted or emptied in the app.
104. **Re-evaluation audit: the coach questions its own rules** (athlete request, 2026-11-22):
    - Why: `learn` brings in new evidence, but nothing re-checked the rules already in place. Many of them came from
      the original planning chat or practitioner habit. The first one examined, HRV trend 3 days below its band ->
      Red, had no trial behind it and was costing training days (changed in 2026-11-22-config-change-2). Coach
      development research describes expert coaches as reflective practitioners who notice, try and evaluate, and
      notes that reflection doesn't come from experience alone.
    - `coach audit` (deterministic) lists every rule: the config sections that hold rules (thresholds, weather,
      nutrition, running, training rules, skill practice, deloads, ladder rules, benchmarks, test noise and goal
      sizes) are walked automatically, so a new number shows up unreviewed without anyone remembering to add it.
      Rules that live in code are named in `engine/audit.py` CODE_RULES. It compares the list with the `evidence`
      records and returns the queue: changed since review, unreviewed, due again, weak evidence with high impact,
      and records whose rule no longer exists. Rules in code carry a version string in CODE_RULES that is bumped
      whenever the rule changes, so code edits show up as "changed since review" too. Safety rules (joint, pain,
      Red-day and sustained-Red rules) are flagged; the queue lists them under `safety_rules_queued` so their
      verdicts always reach the athlete (review of #20), including any safety rule whose verdict is change, retire
      or trial. Yellow-tier thresholds are deliberately not safety rules: Yellow only swaps intensity work for
      Zone 2, and the Red, joint and pain rules stay the safety net.
    - The `audit` skill does the judging: signals from use first (how often a rule fired, what followed, how often
      the athlete overrode it), then a literature search citing retrieved sources only, an evidence grade, an impact
      grade and a verdict (keep / keep_flagged / change / retire / trial). Changes go through proposals or PRs. A
      4-week trial is offered, not required (the athlete may take a well-supported change directly). An audit never
      loosens a safety rule on its own authority: a change to one is put to the athlete with its evidence and needs
      their explicit approval, recorded as a proposal (decision 105 is the first such case).
    - Cadence: every block transition Sunday (after the block review, before the next goal), plus up to 3 high-impact
      items in the monthly `learn`, plus on demand.
    - Reverse: revert the commit; evidence records and audit reports are plain athlete data.
105. **Audit changes: Red-day carry, single-run spikes, resting-HR median, readiness log, nutrition** (athlete
     approved all, 2026-11-22 ET; from the first re-evaluation, decision 104):
    - The day after a Red day follows its own readiness. The carry (Z1 + mobility the next day too) stays only when
      the Red came from a joint rated at the Red level; illness and red flags have their own gates. HRV-guided
      trials lower intensity on the day the signal is low, not for 48 h. The athlete overrode the 48 h carry the
      first time it fired, while recovery was rising. `code.red_carry_48h` v2. This loosens a
      safety-listed rule, so it was put to the athlete with the evidence and approved explicitly (proposal recorded
      2026-11-22). The check reads structured fields (yesterday's joint ratings vs `joint_red`, and joint flags), not
      reason text; a region flag (a region rated 3+ on two check-ins) still carries.
    - Running: a single-run spike cap replaces the long-run "+1 mi/week" step. No run may be more than
      `run_spike_max_pct` (10%) longer than the longest run of the previous 30 days, the week's own earlier runs
      included. A minimum step of `run_spike_min_step_mi` (0.25 mi) lets a very low base grow. A 5200-runner
      cohort (Frandsen 2025) linked single-session spikes over 10% to overuse injuries, while week-to-week change
      was not linked; the 10%-per-week rule didn't reduce injuries in an RCT (Buist 2008). The weekly cap stays
      as a looser backstop. It is a config value, loosened to 20% in a separate approved config change. plan-week
      caps each run and moves the surplus to shorter runs; what doesn't fit is dropped, with a deviation.
      `long_run_max_increase_mi` is kept only so older configs load. The 30-day longest counts planned
      runs only on days without a logged run. The new thresholds join the config fingerprint only once set away from
      their defaults (as in decision 99), so moving one back to its default is caught only if the lock held another
      value.
    - Resting HR trend: 7-day median vs baseline median, so one outlier morning can't hold it up for a week (the
      same flaw the HRV mean showed).
    - The weekly review logs each day's readiness colour next to the outcome: session done, RPE, next-day joint
      max. After 8-12 weeks `learn` tests whether Yellow and Red days actually went worse, and proposes
      recalibrating the cut-offs if they didn't (the colours are a vendor score plus coaching cut-offs).
    - Duplicates: `running.max_weekly_increase_pct` is now optional and unused, and `gear.shoe_alert_miles` leaves
      the audit inventory. `thresholds.*` are the ones the code reads; the config copies are removed separately.
    - Config side, approved separately: protein 1.6-2.4 g/kg (2.0 outside a cut), fat floor 72 g, benchmarks
      labelled as unsourced coach targets.
