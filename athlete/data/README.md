# athlete/data - the coach's database (committed)

Records the coach and the athlete create over time. Don't edit these files by hand: everything goes through
`coach.store` (`coach record add|list|get`, `coach log`, the skills), which validates each record against its model.

The full list of collections, their models and file layout is in `docs/DATA_MODEL.md` (`coach collections` prints it).
Progress photos and raw API dumps never go in git.
