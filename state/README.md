# state/ - the coach's database (committed)

| Path | What | Written by |
|---|---|---|
| `macrocycle.json` | the year: baseline week + blocks (code-generated from races) | `coach macrocycle regenerate` |
| `movement_readiness.json` | current rung per movement family + exposure history | `rehab` |
| `notes.md` | durable facts the coach reads every run | any skill |
| `health.json` | red flags, illness, travel | `log`, `replan` |
| `athlete_intake.json` | intake questionnaire | `assess` |
| `zones.json` | LTHR + threshold pace from the latest TT | `assess` / `coach test score` |
| `config_lock.json` | fingerprint of approved thresholds | `coach approve` |
| `metrics/YYYY-MM.jsonl`, `metrics/gear.json`, `metrics/sync_state.json` | normalized daily data, sessions, check-ins | `coach sync` |
| `blocks/<id>/{goal,outline,tests_start,tests_end}.json`, `review.md` | block layer | `assess`, `plan-block`, `review` |
| `weeks/<iso-week>/plan.json`, `summary.md`, `review.md` | week layer | `plan-week`, `review` |
| `days/<date>.json` | day layer (readiness, adjustments, what was pushed, the notification) | `adjust-day` / `coach-daily` |
| `checkins/<date>.json`, `metcons/<date>.json` | data logged from chat | `log` |
| `proposals/<id>.json` | everything awaiting approval, with status history | all skills; `coach approve/reject` |
| `events/<event>.md` | race plans + post-event reviews | `compete` |
| `science/YYYY-MM.md` | monthly science audit + calibration | `learn` |
| `changelog.md` | approved config/rule changes | `coach approve` |

Phase 1 ran `coach init` only (macrocycle, starting rungs, config lock, notes, intake template). Live data starts
in Phase 2. Progress photos and raw API dumps never go in git.
