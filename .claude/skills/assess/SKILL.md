---
name: assess
description: Intake, testing and goal setting. Runs the intake questionnaire (once, refreshed yearly), schedules and scores the baseline and transition-week tests, does the gap analysis against benchmarks and proposes each block's primary goal + 1-2 guardrails (always pending the athlete's approval). Use for the baseline week, transition weeks, "retest X", and goal changes.
---

# assess

**When:** first setup (intake), baseline week, transition week scoring (Sunday before a new block), "retest X",
"change my goal".

**Context:** `coach status`, `coach context --block`, `coach test schedule --kind baseline|transition --week <monday>`,
`coach test score --phase baseline|end --week <monday>`, `config/tests.yaml`, `config/benchmarks.yaml`,
`docs/TESTING_PROTOCOL.md`, `state/athlete_intake.json`.

## Procedure
1. **Intake** (chat, once; refresh yearly via `review`): ask the questions in `state/athlete_intake.json` a few at a
   time, store answers there, set `completed: true`. Durable facts also go to `state/notes.md`.
2. **Baseline battery proposal:** pick tests from `batteries.baseline` (a subset is fine). Decide TT vs submax:
   if recent running is very low or the athlete reports calf/Achilles niggles, use `run_submax_drift` and say why.
   Schedule with `coach test schedule` (strength, run, engine on separate days), build the baseline week via
   `plan-week`, write it as a proposal (`baseline_battery`). Athlete approves before anything is pushed.
3. **Scoring:** `coach test score ...` writes `state/blocks/<id>/tests_<phase>.json` and updates `state/zones.json`
   (LTHR + threshold pace). Check variants (rung changes) and the conditions (weather adjustment).
4. **Gap analysis + goal:** compare against benchmarks (the score output includes `gaps`). Propose **one primary goal
   + 1-2 guardrails** for the next block, considering both the block's planned focus and the biggest gap; explain
   the trade-off in `rationale`. Also propose the calorie phase (cut / recomp / lean gain / maintenance) from the
   body-composition trend. Write `state/blocks/<id>/goal.json` (`BlockGoal`, `status: pending`) and a
   `block_goal` proposal. **Block goals always need approval.**
5. Starting rungs after the baseline week: conservative; only advance a family's starting rung with a physio's
   recommendation or clean test exposures (via `rehab`).

## Writes
- `state/athlete_intake.json`
- `state/blocks/<id>/tests_{baseline,start,end}.json` (`TestSet`)
- `state/blocks/<id>/goal.json` (`BlockGoal`) + `state/proposals/<id>.json` (`Proposal`, kind `block_goal`)
- `state/zones.json`

## May call
`plan-week` (baseline/transition week), `design-session` (test sessions), `rehab` (starting rungs).

## Never
- Schedule true 1RMs, or a test above the current rung.
- Approve its own goal, or let plan-block finalize before approval.
- Put a full-effort TT in the baseline when the coach judged it too risky without saying so in the proposal.
- Invent a test result: missing data is reported, and the test is rescheduled.
