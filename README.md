# Omni-Hybrid Coach

An automated hybrid-athlete coach that lives in this repo and runs as a Claude Code scheduled task every morning.
It reads training, recovery and nutrition data (Whoop, Hevy, Intervals.icu/Garmin, Withings, Open-Meteo), plans the
year -> block -> week -> day, runs testing at the start and end of every block, and updates workouts in Hevy and on
the Garmin (via Intervals.icu). No website, server or database: **git is the database**.

**Claude decides, code calculates and enforces.** Claude (following `CLAUDE.md` and `.claude/skills/`) makes the
coaching decisions; the `coach` Python package computes every number, validates every plan and is the only thing
that writes to external services.

## Quick start (mock data, no keys)
```bash
pip install -e ".[dev]"
export COACH_MOCK=1
python -m coach simulate --days 120 --from 2026-11-16   # baseline -> Block 1 -> transition -> Block 2, + per-skill scenarios
python -m coach --date 2026-11-16 status --pretty
pytest
```

## Docs
- `CLAUDE.md` - how sessions coach (routing table, conventions)
- `docs/ARCHITECTURE.md` - diagrams and code map
- `docs/TRAINING_ARCHITECTURE.md` - the training rules
- `docs/SAFETY.md`, `docs/COACH_VOICE.md`, `docs/TESTING_PROTOCOL.md`
- `docs/DECISIONS.md` - every judgment call and how to reverse it
- `docs/SECURITY.md`, `docs/SETUP.md` - data handling and the Phase 2 go-live checklist
- `docs/BUILD_PROMPT.md` - the original brief
