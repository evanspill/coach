# Demo athlete (engine test data)

`config/` is a complete example athlete configuration and `fixtures/` is ~6 months of synthetic data for it, in raw
API shapes (Whoop, Hevy, Intervals.icu, Withings, Open-Meteo) plus `athlete_script.json`, which drives the
simulated athlete in `coach simulate` (missed days, test results, chat messages).

The engine's tests and `coach simulate` run against this demo, never against a real athlete's `config/`, so the
engine can live in its own repo. `coach simulate --config active` replays the same fixtures against the active
config instead (useful after editing your own config; dates must still line up with the fixtures).

Regenerate the fixtures with `python scripts/generate_fixtures.py`.
