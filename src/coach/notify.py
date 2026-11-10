"""The push notification: short, plain, decision first. Detailed numbers stay in the repo."""

from coach.models import DayRecord

STATE_WORD = {"green": "GREEN", "yellow": "YELLOW", "red": "RED", "unknown": "PENDING"}


def _headline(rec: DayRecord) -> str:
    s = rec.session
    if s is None:
        return "No session planned."
    if s.type == "rest":
        return f"Rest. {s.intent}"
    main = ""
    for b in s.blocks:
        if b.kind in {"strength", "test"} and b.items:
            it = b.items[0]
            load = f" @ {it.load_note}" if it.load_note and it.load_kg else ""
            main = f" Main: {it.sets}x{it.reps or ''} {it.exercise_id.replace('_', ' ')}{load}."
            break
    runs = [seg for seg in s.run_segments() if seg.modality == "run"]
    if not main and runs:
        miles = sum(seg.distance_mi or 0 for seg in runs)
        main = f" {miles:.1f} mi" if miles else ""
    where = {
        "gym": "gym",
        "outdoor": s.route or "outdoors",
        "track": "track",
        "travel": "wherever you are",
        "home": "home",
    }[s.location]
    return f"{s.title} (~{s.expected_minutes} min, {where}).{main}"


def compose(rec: DayRecord, extras: dict | None = None, detail: str = "normal") -> str:
    extras = extras or {}
    lines = []
    if rec.status == "stopped_red_flag":
        lines.append(
            "STOP: red flag reported. No training until a doctor clears you. "
            + "; ".join(c.why for c in rec.changes)
        )
        return "\n".join(lines)
    if rec.status == "paused":
        return "Coach paused: data synced, no plan changes." + (
            f" Stale: {', '.join(extras.get('stale', []))}." if extras.get("stale") else ""
        )
    r = rec.readiness
    if r:
        top = r.reasons[0] if r.reasons else ""
        lines.append(f"{STATE_WORD[r.state]}: {top}.")
    if rec.status == "waiting_for_recovery":
        lines.append(
            "Whoop hasn't processed last night yet: train the planned session; I'll finalize at the 9:05 catch-up."
        )
    lines.append("Today: " + _headline(rec))
    if rec.weather and rec.session and any(seg.modality == "run" for seg in rec.session.run_segments()):
        lines.append(f"Weather: {rec.weather.decision}.")
    if rec.fueling_cue and detail == "normal":
        lines.append(f"Fuel: {rec.fueling_cue}")
    if rec.recovery_prescription:
        lines.append("Tonight: " + "; ".join(rec.recovery_prescription) + ".")
    if rec.changes:
        shown = rec.changes[:3]
        lines.append(
            "Changed: "
            + " | ".join(f"{c.what} ({c.why})" for c in shown)
            + (f" (+{len(rec.changes) - 3} more)" if len(rec.changes) > 3 else "")
        )
    for h in rec.handoffs:
        lines.append(h)
    if rec.approvals_pending:
        lines.append("Waiting for your OK: " + "; ".join(rec.approvals_pending[:3]))
    if rec.gear_alerts:
        lines.append("Gear: " + "; ".join(rec.gear_alerts))
    for k in ("weekly", "transition", "learn", "unconfirmed"):
        if extras.get(k):
            lines.append(extras[k])
    if extras.get("stale"):
        lines.append("Data: " + "; ".join(extras["stale"]))
    return "\n".join(lines)
