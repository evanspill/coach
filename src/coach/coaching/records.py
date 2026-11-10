"""Submitting records the coach (Claude) writes. One path for every collection, so plans can't be saved without the
code-computed numbers and the guardrails:

  week_plans          fill loads/paces/minutes/carb tiers -> validate the week -> save -> summary -> approval proposal
  day_records         fill today's session -> validate it -> save
  block_outlines      validate the outline -> save
  block_goals         save as pending -> block_goal proposal (goals always need the athlete's OK)
  movement_readiness  validate the rung changes against the stored state -> save
  macrocycle          check gaps/overlaps -> save
  reports             save the markdown
  everything else     validate against the model -> save
"""

import datetime as dt
from typing import Any

from coach.coaching import proposals
from coach.config import Config
from coach.engine.validator import (
    Violation,
    validate_macrocycle,
    validate_movement_change,
    validate_outline,
    validate_session,
    validate_week,
)
from coach.store import Store


class SubmitRefused(Exception):
    def __init__(self, violations: list[Violation]):
        super().__init__("record refused: fails validation")
        self.violations = violations


def submit(
    store: Store, cfg: Config, collection: str, payload, today: dt.date, key: str | None = None
) -> dict:
    from coach.coaching.context import build
    from coach.coaching.daily import week_summary_md
    from coach.coaching.skills.plan_week import finalize

    c = store.collection(collection)
    if c.kind == "report":
        store.save_report(collection, str(payload), key)
        return {"saved": store.ref(collection, key), "kind": "report"}
    obj: Any = c.model.model_validate(payload) if c.model is not None else payload
    actions: list[str] = []

    if collection == "week_plans":
        ctx = build(store, cfg, today)
        finalize(ctx, obj.sessions)
        actions.append("filled loads, paces, minutes and carb tiers")
        v = validate_week(obj, ctx.validation(obj))
        if v:
            raise SubmitRefused(v)
        if cfg.settings.approval.weekly_plan == "auto":
            obj.approval = "auto"
        store.put(collection, obj)
        store.save_report("week_summaries", week_summary_md(ctx, obj), obj.week_id)
        if obj.approval == "pending":
            p = proposals.create(
                store,
                "baseline_battery" if obj.week_type == "baseline" else "weekly_plan",
                "plan-week",
                f"Week {obj.week_id} plan ({obj.week_type})",
                f"see {store.ref(collection, obj.week_id)}",
                obj.rationale,
                today,
                target=store.ref(collection, obj.week_id),
            )
            actions.append(f"proposal {p.id} waiting for approval")
    elif collection == "day_records":
        ctx = build(store, cfg, today)
        plan = ctx.week_plan(obj.date)
        if obj.session is not None:
            finalize(ctx, [obj.session])
            v = validate_session(
                obj.session, ctx.validation(plan), plan.week_type if plan else "training", plan
            )
            if v:
                raise SubmitRefused(v)
            actions.append("filled and validated today's session")
        store.put(collection, obj)
    elif collection == "block_outlines":
        v = validate_outline(obj)
        if v:
            raise SubmitRefused(v)
        store.put(collection, obj)
    elif collection == "block_goals":
        obj.status = "pending" if obj.status != "approved" or not store.goal(obj.block_id) else obj.status
        store.put(collection, obj)
        if obj.status == "pending":
            p = proposals.create(
                store,
                "block_goal",
                "assess",
                f"Block goal for {obj.block_id}",
                f"{obj.primary.test_id}: {obj.primary.baseline_value} -> {obj.primary.target_value} {obj.primary.unit}",
                obj.rationale,
                today,
                after=obj.model_dump(mode="json"),
                target=store.ref(collection, obj.block_id),
            )
            actions.append(f"proposal {p.id} waiting for approval")
    elif collection == "movement_readiness":
        before = store.movement_readiness()
        if before is not None:
            v = validate_movement_change(before, obj, cfg)
            if v:
                raise SubmitRefused(v)
        store.put(collection, obj)
    elif collection == "macrocycle":
        v = validate_macrocycle(obj)
        if v:
            raise SubmitRefused(v)
        store.put(collection, obj)
    else:
        store.put(collection, obj, key)
    k = key if key or c.kind == "singleton" else store.key_of(collection, obj)
    return {
        "saved": store.ref(collection, k),
        "actions": actions,
        "record": obj.model_dump(mode="json", exclude_none=True) if hasattr(obj, "model_dump") else obj,
    }
