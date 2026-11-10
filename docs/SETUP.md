# Setup

## Local / mock (Phase 1)
```bash
pip install -e ".[dev]"
export COACH_MOCK=1
python -m coach simulate --days 120 --from 2026-11-16      # replay fixtures + per-skill scenarios
ruff check . && ruff format --check . && pytest
```
`coach simulate` writes into a temp directory and prints its path; the repo's `state/` is never touched.

## Phase 2: go live in shadow mode (setup session with the athlete)

### Before the baseline week (athlete checklist)
- [ ] Intake questionnaire with the coach in a chat session (`assess`; fills `state/athlete_intake.json`).
- [ ] Optional physical therapist assessment (back + shoulder) to set starting rungs.
- [ ] Running gait analysis and shoe fitting (two-shoe rotation: cushioned trainer + firmer shoe).
- [ ] Confirm treadmill (Woodway Curve) availability and the 9-10 AM schedule.
- [ ] Pair the Running Dynamics Pod with the fenix.
- [ ] Create Intervals.icu custom wellness fields `BackFeel`, `ShoulderFeel`, `KneeAchillesFeel` (and optionally
      `SessionRPE`, `Enjoyment`, `Soreness`, `BarSpeed`); enable "upload planned workouts" on the Garmin connection.
- [ ] Verify the bar weights assumed in `config/equipment.yaml` (trap bar 60 lb, SSB 65 lb) and list the lighter KBs.

### Cloud environment
- [ ] Network allowlist: `api.hevyapp.com`, `intervals.icu`, `api.open-meteo.com`, the Whoop/Withings broker host,
      `eutils.ncbi.nlm.nih.gov` (science audit). Package registries for the setup script.
- [ ] Network secrets: Hevy API key (`api-key` header), Intervals.icu API key (Basic auth `API_KEY:<key>`),
      broker static key. Never as env vars or files.
- [ ] Setup script: `pip install -e ".[dev]"`.
- [ ] Unset `COACH_MOCK` for live runs.

### Whoop (and Withings): two options
- **No hosting (simplest):** Whoop wellness (recovery, HRV, RHR, sleep) through Intervals.icu's native Whoop
  connection, and Withings through Apple Health -> HealthFit -> Intervals.icu wellness. Everything then comes from one
  static Intervals.icu key. Costs: no per-workout Whoop strain/zones (Garmin HR from Intervals covers sessions), and
  Intervals polls Whoop only every ~8 h, so the 8:25 run may not see last night's recovery (the 9:05 catch-up helps;
  opening the Intervals calendar triggers a poll). Needs a small change: read recovery from Intervals wellness.
- **Direct APIs (fuller data):** the steps below.

- [ ] Register a Whoop developer app (API v2) and a Withings developer app.
- [ ] Deploy the token broker (e.g. a free Cloudflare Worker) that holds the rotating refresh tokens and exposes
      read-only endpoints (`/v2/recovery`, `/v2/activity/sleep`, `/v2/cycle`, `/v2/activity/workout`,
      `/withings/measure`) behind a static key. Set `WHOOP_BROKER_URL` (non-secret) in the environment.
- [ ] Backup: enable Intervals.icu's native Whoop wellness sync.
- [ ] Verify each live client against the real API (`coach sync --pretty`) and fix field names in
      `src/coach/integrations/normalize.py` if they differ from the docs-based shapes.

### Your config (all in `config/`)
- `athlete_context.json` (profile, races, thresholds, check-in regions, nutrition/recovery wording), `season.yaml`
  (blocks), `training.yaml` (sessions, warm-ups, rules), `equipment.yaml`, `exercises.yaml`, `tests.yaml`,
  `movement_progressions.yaml`, `skills.yaml`, `benchmarks.yaml`, `coach.yaml`. After editing:
  `python -m coach validate config` and `python -m coach simulate --config active --no-scenarios`.

### First live run
- [ ] `python -m coach init` (macrocycle, starting rungs, config lock, notes, intake template). Already run once in
      Phase 1 with today's date; re-run is idempotent.
- [ ] `python -m coach sync --pretty` and `python -m coach status --pretty`.
- [ ] Create the two scheduled tasks (push notifications on):
  - ~8:25 AM ET daily: *"Run the coach-daily skill. Commit state to main and push. End with the athlete summary."*
  - ~9:05 AM ET daily (catch-up): *"Run the coach-daily skill in catch-up mode: only continue if today's day record
    is waiting_for_recovery. Commit state to main and push. End with the athlete summary."*
- [ ] Run the baseline week, approve the Block 1 goal, then **4 weeks of shadow mode** (`push.enabled: false`)
      comparing with the human coach.

## Phase 3
Turn on `push.enabled` (weekly plans `manual` at first), connect nutrition (MacroFactor -> Apple Health ->
Intervals.icu wellness), then switch `approval.weekly_plan` to `auto` once trusted.
