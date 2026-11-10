"""Anything that needs the athlete's OK lives in state/proposals/<id>.json until approved or rejected."""

import datetime as dt
import json
from pathlib import Path

from coach.config import Config
from coach.models import Proposal
from coach.models.records import ProposalEvent
from coach.state import State
from coach.validator import thresholds_fingerprint


def create(
    state: State,
    kind: str,
    created_by: str,
    title: str,
    what: str,
    why: str,
    day: dt.date,
    *,
    before=None,
    after=None,
    target_path: str | None = None,
    payload: dict | None = None,
    supersede_same_target: bool = True,
) -> Proposal:
    if supersede_same_target and target_path:
        for p in state.proposals("pending"):
            if p.target_path == target_path and p.kind == kind:
                p.status = "superseded"
                p.history.append(
                    ProposalEvent(at=day, status="superseded", note="replaced by a newer proposal")
                )
                state.save_proposal(p)
    n = (
        len(list(state.path("proposals").glob(f"{day.isoformat()}-*.json"))) + 1
        if state.path("proposals").exists()
        else 1
    )
    p = Proposal(
        id=f"{day.isoformat()}-{kind.replace('_', '-')}-{n}",
        kind=kind,
        created=day,
        created_by=created_by,
        title=title,  # type: ignore[arg-type]
        what=what,
        why=why,
        before=before,
        after=after,
        target_path=target_path,
        payload=payload,
        history=[ProposalEvent(at=day, status="pending")],
    )
    state.save_proposal(p)
    return p


def _apply_config_patch(cfg_dir: Path, patch: dict) -> None:
    """patch = {"file": "athlete_context.json", "path": ["thresholds", "recovery_green_min"], "value": 70}"""
    import yaml

    f = cfg_dir / patch["file"]
    data = json.loads(f.read_text()) if f.suffix == ".json" else yaml.safe_load(f.read_text())
    node = data
    for k in patch["path"][:-1]:
        node = node[k]
    node[patch["path"][-1]] = patch["value"]
    if f.suffix == ".json":
        f.write_text(json.dumps(data, indent=2) + "\n")
    else:
        f.write_text(yaml.safe_dump(data, sort_keys=False))


def record_config_lock(state: State, cfg: Config, approved_by: str, day: dt.date) -> None:
    state.write_json(
        "config_lock.json",
        {"fingerprint": thresholds_fingerprint(cfg), "approved_by": approved_by, "at": day.isoformat()},
    )


def approve(state: State, pid: str, day: dt.date, cfg: Config, note: str = "") -> list[str]:
    from coach.config import load_config
    from coach.models import BlockGoal, WeekPlan

    p = state.proposal(pid)
    if p is None:
        raise KeyError(f"no proposal {pid}")
    if p.status != "pending":
        raise ValueError(f"proposal {pid} is {p.status}, not pending")
    actions = []
    if p.kind in {"weekly_plan", "baseline_battery"} and p.target_path:
        plan = state.read_model(p.target_path, WeekPlan)
        if plan:
            plan.approval = "approved"
            state.write_json(p.target_path, plan)
            actions.append(f"approved {p.target_path}")
    elif p.kind == "block_goal" and p.target_path:
        goal = state.read_model(p.target_path, BlockGoal)
        if goal:
            goal.status = "approved"
            state.write_json(p.target_path, goal)
            actions.append(f"approved goal {goal.block_id}")
    elif p.payload and "files" in p.payload:
        for rel, content in p.payload["files"].items():
            state.write_json(rel, content)
            actions.append(f"wrote {rel}")
    if p.payload and "config_patch" in p.payload:
        _apply_config_patch(cfg.root, p.payload["config_patch"])
        new_cfg = load_config(cfg.root)
        record_config_lock(state, new_cfg, p.id, day)
        actions.append(
            f"config patched: {'.'.join(p.payload['config_patch']['path'])} = {p.payload['config_patch']['value']}"
        )
        log_changelog(state, day, p)
    p.status = "approved"
    p.history.append(ProposalEvent(at=day, status="approved", note=note))
    state.save_proposal(p)
    return actions


def reject(state: State, pid: str, day: dt.date, reason: str) -> None:
    p = state.proposal(pid)
    if p is None:
        raise KeyError(f"no proposal {pid}")
    p.status = "rejected"
    p.history.append(ProposalEvent(at=day, status="rejected", note=reason))
    state.save_proposal(p)


def log_changelog(state: State, day: dt.date, p: Proposal) -> None:
    state.append_text("changelog.md", f"- {day.isoformat()} [{p.id}] {p.title}: {p.what} (why: {p.why})\n")


def pending_summary(state: State) -> list[str]:
    return [f"{p.id}: {p.title}" for p in state.proposals("pending")]
