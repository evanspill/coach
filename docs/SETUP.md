# Setup

## Local / mock (Phase 1)
```bash
pip install -e ".[dev]"
export COACH_MOCK=1
python -m coach simulate --days 120 --from 2026-11-16      # replay fixtures + per-skill scenarios
ruff check . && ruff format --check . && pytest
```
`coach simulate` writes into a temp directory and prints its path; the repo's `athlete/data/` is never touched.

## Phase 2: go live in shadow mode (setup session with the athlete)

### Before the baseline week (athlete checklist)
- [ ] Intake questionnaire with the coach in a chat session (`assess`; fills `athlete/data/athlete_intake.json`).
- [ ] Optional physical therapist assessment (back + shoulder) to set starting rungs.
- [ ] Running gait analysis and shoe fitting (two-shoe rotation: cushioned trainer + firmer shoe).
- [ ] Confirm treadmill (Woodway Curve) availability and the 9-10 AM schedule.
- [ ] Pair the Running Dynamics Pod with the fenix.
- [ ] Create Intervals.icu custom wellness fields `BackFeel`, `ShoulderFeel`, `KneeAchillesFeel` (and optionally
      `SessionRPE`, `Enjoyment`, `Soreness`, `BarSpeed`); enable "upload planned workouts" on the Garmin connection.
- [ ] Verify the bar weights assumed in `athlete/config/equipment.yaml` (trap bar 60 lb, SSB 65 lb) and list the lighter KBs.

### Cloud environment (done 2026-11-11: personal environment `coach`)
- [x] Network allowlist: `api.hevyapp.com`, `intervals.icu`, `api.open-meteo.com`, `eutils.ncbi.nlm.nih.gov`
      (science audit); package registries for the setup script. Add the broker host once it is deployed.
- [x] Network secrets: Hevy API key (`api-key` header), Intervals.icu API key (Basic auth `API_KEY:<key>`).
      Broker static key (`X-Broker-Key`) once deployed. Never as env vars or files.
- [x] Setup script: `pip install -e ".[dev]"`.
- [x] `COACH_MOCK=0` for live runs.

### Whoop: direct API through a token broker
Whoop is worn 24/7 and is the only HR source for gym sessions, so the coach reads it directly (recovery, HRV, RHR,
sleep, and HR/strain/zones for every workout). Whoop issues refresh tokens that change on every use, so they need a
small always-on place to live: the token broker, a free Cloudflare Worker with KV, in `broker/` (registration and
deploy steps in `broker/README.md`). Read WHOOP's API terms first: they restrict AI use and permanent copies, so the
coach never commits Whoop data (it refetches a rolling 75-day window into a git-ignored cache each run).

- [ ] Register a Whoop developer app (API v2); deploy the broker; connect your account once in a browser.
- [ ] Set `WHOOP_BROKER_URL` (non-secret) and the broker key (network secret) in the `coach` environment.
- [ ] Verify against the real API (`coach sync --pretty`) and fix field names in
      `src/coach/integrations/normalize.py` if they differ from the docs-based shapes.

### Whoop backup via Intervals.icu (optional)
Connect Whoop in Intervals.icu (Settings -> Connections). Once Intervals.icu shows Whoop's HRV / resting HR / sleep
(and not a watch's), set `whoop_backup: intervals` in `athlete/config/coach.yaml`: days the direct API misses are
then filled from Intervals.icu wellness (cache only, never committed). It has no per-workout HR or strain, and
Intervals.icu may import it hours after you wake.

### Scale (weight, body fat)
No direct scale API (the vendor's API terms rule out AI use). Route: scale app -> Apple Health -> HealthFit ->
Intervals.icu wellness (`weight`, `bodyFat`). In HealthFit, enable the Intervals.icu connection with weight and body
fat.

### Intervals.icu (runs + the route to the Garmin)
The Garmin is worn only on runs. Intervals.icu provides run detail (pace, Running Dynamics from the Pod), training
load and shoe mileage, and it is the only practical way to put planned run workouts on the watch: Garmin's own
Training API is for approved businesses, and its personal key is read-only. Use an Intervals.icu API key (static, no
broker needed) and enable "upload planned workouts" on its Garmin connection.

### Your config (all in `athlete/config/`)
- `athlete_context.json` (profile, races, thresholds, check-in regions, nutrition/recovery wording), `season.yaml`
  (blocks), `training.yaml` (sessions, warm-ups, rules), `equipment.yaml`, `exercises.yaml`, `tests.yaml`,
  `movement_progressions.yaml`, `skills.yaml`, `benchmarks.yaml`, `coach.yaml`. After editing:
  `python -m coach validate config` and `python -m coach simulate --config active --no-scenarios`.

### First live run
- [ ] `python -m coach init` (macrocycle, starting rungs, config lock, notes, intake template). Already run once in
      Phase 1 with today's date; re-run is idempotent.
- [ ] `python -m coach sync --pretty` and `python -m coach status --pretty`.
- [ ] Create the two scheduled tasks (push notifications on):
  Start times are deliberately off-round (never :00 / :30), and every scheduled sync waits a random 0-90 s first
  (`--jitter 90`), as Hevy's API docs ask; it applies to every integration.
  - ~8:25 AM ET daily: *"Run the coach-daily skill. Commit state to main and push. End with the athlete summary."*
  - ~9:05 AM ET daily (catch-up): *"Run the coach-daily skill in catch-up mode: only continue if today's day record
    is waiting_for_recovery. Commit state to main and push. End with the athlete summary."*
- [ ] Run the baseline week, approve the Block 1 goal, then **4 weeks of shadow mode** (`push.enabled: false`)
      comparing with the human coach.

## Phase 3
Turn on `push.enabled` (weekly plans `manual` at first), connect nutrition (MacroFactor -> Apple Health ->
Intervals.icu wellness), then switch `approval.weekly_plan` to `auto` once trusted.
