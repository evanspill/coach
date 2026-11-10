"""Anything that needs the athlete's OK lives in state/proposals/<id>.json until approved or rejected."""

import datetime as dt
import json
from pathlib import Path

from coach.config import Config
from coach.engine.validator import thresholds_fingerprint
from coach.models import Proposal
from coach.models.records import ConfigLock, ProposalEvent
from coach.store import Store


def create(
    state: Store,
    kind: str,
    created_by: str,
    title: str,
    what: str,
    why: str,
    day: dt.date,
    *,
    before=None,
    after=None,
    target: str | None = None,
    payload: dict | None = None,
    supersede_same_target: bool = True,
) -> Proposal:
    if supersede_same_target and target:
        for p in state.proposals("pending"):
            if p.target == target and p.kind == kind:
                p.status = "superseded"
                p.history.append(
                    ProposalEvent(at=day, status="superseded", note="replaced by a newer proposal")
                )
                state.save_proposal(p)
    n = len([k for k in state.keys("proposals") if k.startswith(f"{day.isoformat()}-")]) + 1
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
        target=target,
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


def record_config_lock(state: Store, cfg: Config, approved_by: str, day: dt.date) -> None:
    state.put(
        "config_lock", ConfigLock(fingerprint=thresholds_fingerprint(cfg), approved_by=approved_by, at=day)
    )


def approve(state: Store, pid: str, day: dt.date, cfg: Config, note: str = "") -> list[str]:
    from coach.config import load_config

    p = state.proposal(pid)
    if p is None:
        raise KeyError(f"no proposal {pid}")
    if p.status != "pending":
        raise ValueError(f"proposal {pid} is {p.status}, not pending")
    actions = []
    if p.kind in {"weekly_plan", "baseline_battery"} and p.target:
        plan = state.get_ref(p.target)
        if plan:
            plan.approval = "approved"
            state.put_ref(p.target, plan)
            actions.append(f"approved {p.target}")
    elif p.kind == "block_goal" and p.target:
        goal = state.get_ref(p.target)
        if goal:
            goal.status = "approved"
            state.put_ref(p.target, goal)
            actions.append(f"approved goal {goal.block_id}")
    elif p.payload and "records" in p.payload:
        for ref, content in p.payload["records"].items():
            state.put_ref(ref, content)
            actions.append(f"wrote {ref}")
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


def reject(state: Store, pid: str, day: dt.date, reason: str) -> None:
    p = state.proposal(pid)
    if p is None:
        raise KeyError(f"no proposal {pid}")
    p.status = "rejected"
    p.history.append(ProposalEvent(at=day, status="rejected", note=reason))
    state.save_proposal(p)


def log_changelog(state: Store, day: dt.date, p: Proposal) -> None:
    state.append_report("changelog", f"- {day.isoformat()} [{p.id}] {p.title}: {p.what} (why: {p.why})\n")


def pending_summary(state: Store) -> list[str]:
    return [f"{p.id}: {p.title}" for p in state.proposals("pending")]
