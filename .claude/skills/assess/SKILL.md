---
name: assess
description: Intake, testing and goal setting. Runs the intake questionnaire (once, refreshed yearly), schedules and scores the baseline and transition-week tests, does the gap analysis against benchmarks and proposes each block's primary goal + 1-2 guardrails (always pending the athlete's approval). Use for the baseline week, transition weeks, "retest X", and goal changes.
---

# assess

**When:** first setup (intake), baseline week, transition week scoring (Sunday before a new block), "retest X",
"change my goal".

**Context:** `coach status`, `coach context --block`, `coach test schedule --kind baseline|transition --week <monday>`,
`coach test score --phase baseline|end --week <monday>`, `athlete/config/tests.yaml`, `athlete/config/benchmarks.yaml`,
`docs/TESTING_PROTOCOL.md`, `intake` (`coach record get intake`).

## Procedure
1. **Intake** (chat, once; refresh yearly via `review`): ask the questions in `intake` (`coach record get intake`) a few at a
   time, store answers there, set `completed: true`. Durable facts go to `notes` (`coach record add notes '{"date": ..., "category": ..., "text": ...}'`).
2. **Baseline battery proposal:** pick tests from `batteries.baseline` (a subset is fine). Decide TT vs submax:
   if recent running is very low or the athlete reports calf/Achilles niggles, use `run_submax_drift` and say why.
   Schedule with `coach test schedule` (strength, run, engine on separate days), build the baseline week via
   `plan-week`, write it as a proposal (`baseline_battery`). Athlete approves before anything is pushed.
3. **Scoring:** `coach test score ...` writes the `test_sets` record and updates `zones`
   (LTHR + threshold pace). Check variants (rung changes) and the conditions (weather adjustment).
3b. **Real change vs noise:** each test has a `typical_error_pct` in `tests.yaml`; changes smaller than that are
   reported as "within test noise", not progress or regression.
4. **Gap analysis + goal:** compare against benchmarks (the score output includes `gaps`). Propose **one primary goal
   + 1-2 guardrails** for the next block, considering both the block's planned focus and the biggest gap; explain
   the trade-off in `rationale`. Also propose the calorie phase (cut / recomp / lean gain / maintenance) from the
   body-composition trend. Submit with `coach record add block_goals --file /tmp/goal.json` (saved as pending and a
   `block_goal` proposal is opened). **Block goals always need approval.**
5. Starting rungs after the baseline week: conservative; only advance a family's starting rung with a physio's
   recommendation or clean test exposures (via `rehab`).

## Writes
- `intake` (`coach record get intake`)
- `test_sets` (via `coach test score`)
- `block_goals` (`BlockGoal`) + its `block_goal` proposal (via `coach record add block_goals --file ...`)
- `zones`

## May call
`plan-week` (baseline/transition week), `design-session` (test sessions), `rehab` (starting rungs).

## Never
- Schedule true 1RMs, or a test above the current rung.
- Approve its own goal, or let plan-block finalize before approval.
- Put a full-effort TT in the baseline when the coach judged it too risky without saying so in the proposal.
- Invent a test result: missing data is reported, and the test is rescheduled.
