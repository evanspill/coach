"""The athlete data model as collections. Each collection maps to one database table later: the model is the
row schema, `key` is the primary key, and `path` is where the file backend keeps it today (athlete/data/).

Kinds:
  singleton  one document (a one-row table)
  doc        one document per key
  report     a rendered markdown document (a text column keyed by `key`)
  series     time-series rows in monthly JSON-lines files (metrics: daily wellness, sessions, check-ins)
"""

from dataclasses import dataclass

from pydantic import BaseModel

from coach.models import (
    BlockGoal,
    BlockOutline,
    DayRecord,
    Gear,
    Macrocycle,
    MovementReadiness,
    Proposal,
    TestSet,
    WeekPlan,
)
from coach.models.journal import (
    Availability,
    EventResult,
    HealthEvent,
    JournalEntry,
    LabResult,
    Measurement,
    MetconLog,
    Note,
)
from coach.models.metrics import Checkin
from coach.models.records import ConfigLock, Intake, NutritionTarget, SyncState, ThresholdZones


@dataclass(frozen=True)
class Collection:
    name: str
    kind: str  # singleton | doc | report | series
    path: str  # file layout; {key} is the primary key ({a}/{b} for composite keys "a:b")
    model: type[BaseModel] | None = None
    description: str = ""

    def file(self, key: str | None = None) -> str:
        if key is None:
            return self.path
        parts = key.split(":")
        if "{a}" in self.path:
            return self.path.format(a=parts[0], b=parts[1])
        return self.path.format(key=key)


COLLECTIONS: dict[str, Collection] = {
    c.name: c
    for c in [
        # --- athlete-reported (journal) ---
        Collection("checkins", "doc", "checkins/{key}.json", Checkin, "check-ins entered in chat, by date"),
        Collection("journal", "doc", "journal/{key}.json", JournalEntry, "athlete journal entries"),
        Collection("metcon_logs", "doc", "metcons/{key}.json", MetconLog, "mixed-modal results, by date"),
        Collection("health_events", "doc", "health/{key}.json", HealthEvent, "red flags, illness, injuries"),
        Collection(
            "availability", "doc", "availability/{key}.json", Availability, "travel, gym closures, busy days"
        ),
        Collection("lab_results", "doc", "labs/{key}.json", LabResult, "bloodwork markers"),
        Collection("measurements", "doc", "measurements/{key}.json", Measurement, "tape measurements"),
        Collection(
            "event_results", "doc", "events/{key}/result.json", EventResult, "race / competition results"
        ),
        Collection("intake", "singleton", "athlete_intake.json", Intake, "intake questionnaire"),
        Collection(
            "nutrition_target", "singleton", "nutrition_target.json", NutritionTarget, "weekly kcal target"
        ),
        # --- coach records ---
        Collection("macrocycle", "singleton", "macrocycle.json", Macrocycle, "the year (code-generated)"),
        Collection("block_goals", "doc", "blocks/{key}/goal.json", BlockGoal, "block goal + guardrails"),
        Collection("block_outlines", "doc", "blocks/{key}/outline.json", BlockOutline, "block outline"),
        Collection("test_sets", "doc", "blocks/{a}/tests_{b}.json", TestSet, "test results, key block:phase"),
        Collection("week_plans", "doc", "weeks/{key}/plan.json", WeekPlan, "weekly plan"),
        Collection(
            "day_records", "doc", "days/{key}.json", DayRecord, "daily readiness, adjustments, notification"
        ),
        Collection("proposals", "doc", "proposals/{key}.json", Proposal, "everything awaiting approval"),
        Collection("movement_readiness", "singleton", "movement_readiness.json", MovementReadiness, "rungs"),
        Collection("zones", "singleton", "zones.json", ThresholdZones, "LTHR + threshold pace"),
        Collection("notes", "doc", "notes/{key}.json", Note, "durable facts (rendered to notes.md)"),
        Collection(
            "config_lock", "singleton", "config_lock.json", ConfigLock, "approved-thresholds fingerprint"
        ),
        # --- reports (rendered markdown) ---
        Collection("week_reviews", "report", "weeks/{key}/review.md", description="weekly review"),
        Collection(
            "week_summaries", "report", "weeks/{key}/summary.md", description="human summary of a plan"
        ),
        Collection("block_reviews", "report", "blocks/{key}/review.md", description="block review"),
        Collection("annual_reviews", "report", "reviews/{key}.md", description="end-of-season review"),
        Collection("event_plans", "report", "events/{key}/plan.md", description="race plan / strategy"),
        Collection(
            "science", "report", "science/{key}.md", description="monthly science audit + calibration"
        ),
        Collection("notes_view", "report", "notes.md", description="rendered notes"),
        Collection("changelog", "report", "changelog.md", description="approved config/rule changes"),
        Collection("simulation_report", "report", "simulation_report.md", description="simulation summary"),
        # --- integration bookkeeping ---
        Collection(
            "metrics",
            "series",
            "metrics/{key}.jsonl",
            description="daily wellness, sessions, synced check-ins",
        ),
        Collection("gear", "singleton", "metrics/gear.json", description="shoe mileage snapshot"),
        Collection("sync_state", "singleton", "metrics/sync_state.json", SyncState, "last sync + report"),
        Collection(
            "push_ids", "singleton", "push_ids.json", description="external ids of pushed routines/events"
        ),
    ]
}
GEAR_MODEL = Gear
