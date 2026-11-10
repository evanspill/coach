"""log fallback: turn chat messages into clean records; red flags stop training immediately."""

import datetime as dt
import re

from coach.coaching.context import Context
from coach.coaching.skills.technique import skill_from_message
from coach.engine.parsing import (
    classify_illness,
    detect_red_flags,
    parse_checkin_tag,
    parse_metcon_result,
    vocabulary,
)
from coach.models import Checkin
from coach.models.journal import HealthEvent, JournalEntry, MetconLog, MetconResult

STOP_MESSAGE = (
    "Stop training now and get checked by a doctor today ({flags}). If it's chest pain, fainting or severe breathlessness, "
    "call {emergency}. I've paused all sessions until you tell me a doctor has cleared you."
)


def handle(ctx: Context, text: str, day: dt.date) -> dict:
    """Returns {'records': [...paths], 'reply': str, 'follow_up': str|None, 'red_flags': [...]}"""
    out: dict = {"records": [], "reply": "", "follow_up": None, "red_flags": []}
    flags = detect_red_flags(text)
    if flags:
        for f in flags:
            ev = HealthEvent(
                id=ctx.state.new_id("health_events", day, "red-flag"),
                kind="red_flag",
                start=day,
                flag=f,
                description_untrusted=text[:200],
            )
            ctx.state.put("health_events", ev)
            out["records"].append(ctx.state.ref("health_events", ev.id))
        ctx.health = ctx.state.health_events()
        out["red_flags"] = flags
        out["reply"] = STOP_MESSAGE.format(flags=", ".join(flags), emergency=ctx.cfg.profile.emergency_number)
        return out
    illness = (
        classify_illness(text)
        if re.search(r"\b(sick|ill|cold|flu|fever|sore throat|runny|congest|aches?)\b", text, re.I)
        else None
    )
    if illness:
        ev = HealthEvent(
            id=ctx.state.new_id("health_events", day, "illness"),
            kind="illness",
            start=day,
            symptoms=illness,
            description_untrusted=text[:200],
        )
        ctx.state.put("health_events", ev)
        ctx.health = ctx.state.health_events()
        out["records"].append(ctx.state.ref("health_events", ev.id))
        out["reply"] = (
            "Below-the-neck symptoms: no training until they're gone, then a graded return. Rest, fluids, sleep."
            if illness == "below_neck"
            else "Above-the-neck only: easy movement (walk, mobility) is fine; nothing hard until it clears."
        )
        out["handoff"] = "replan"
        return out
    lower = text.lower()
    is_metcon = bool(re.search(r"\b(metcon|amrap|emom|for time|hyrox|open \d|rounds?|wod)\b", lower))
    if is_metcon:
        res = MetconResult.model_validate(parse_metcon_result(text))
        log = ctx.state.get("metcon_logs", day.isoformat()) or MetconLog(date=day)
        log.results.append(res)
        ctx.state.put("metcon_logs", log)
        out["records"].append(ctx.state.ref("metcon_logs", day.isoformat()))
        if res.missing:
            out["follow_up"] = {
                "score": "What was the final score (time, or rounds + reps)?",
                "rpe": "What was the session RPE (1-10)?",
            }[res.missing[0]]
        shown = {
            k: v
            for k, v in res.model_dump().items()
            if k in {"time_s", "rounds", "extra_reps", "calories", "rpe"} and v is not None
        }
        out["reply"] = f"Logged {res.kind}: " + ", ".join(f"{k}={v}" for k, v in shown.items())
    tag = parse_checkin_tag(text, ctx.cfg)
    if tag and not (is_metcon and set(tag) <= {"session_rpe"}):
        prev = ctx.state.get("checkins", day.isoformat()) or Checkin(date=day, source="chat")
        merged = prev.model_dump()
        merged.update({k: v for k, v in tag.items() if k not in {"session_pain", "joints"}})
        merged["joints"] = {**prev.joints, **tag.get("joints", {})}
        merged["session_pain"] = {**prev.session_pain, **tag.get("session_pain", {})}
        ctx.state.put("checkins", Checkin.model_validate(merged))
        out["records"].append(ctx.state.ref("checkins", day.isoformat()))
        parts = [f"{k} {v}" for k, v in tag.get("joints", {}).items()]
        parts += [
            f"{k.replace('_', ' ')} {tag[k]}"
            for k in ("sleep_quality", "fatigue", "stress", "mood", "motivation")
            if k in tag
        ]
        if "session_pain" in tag:
            fam, p = next(iter(tag["session_pain"].items()))
            parts.append(f"{fam} pain {p:g}/10")
            if p > ctx.cfg.progressions.rules.regress_on_session_pain_above:
                out["reply"] = (
                    f"Logged {fam} pain {p:g}/10. Pain rule: next time we regress range of motion or switch to an isometric; "
                    "if it's stiffer tomorrow morning, that lift drops ~15% with a 3 s eccentric for 2 weeks. "
                    "How does it feel at rest right now?"
                )
        out["reply"] = out["reply"] or ("Check-in logged: " + ", ".join(parts) if parts else "Logged.")
    for skill, level in skill_from_message(text, ctx.cfg):
        out.setdefault("skill_updates", []).append((skill, level))
    region_words, _ = vocabulary(ctx.cfg)
    m = re.search(
        r"\b([a-z ]{3,30}?)\s+(?:aggravates?|bothers?|irritates?|hurts?)\s+my\s+((?:left|right|l|r)\s+)?("
        + "|".join(re.escape(w) for w in sorted(region_words, key=len, reverse=True))
        + r")",
        lower,
    )
    if m:
        fact = f"{m.group(1).strip()} aggravates {(m.group(2) or '').strip()} {m.group(3)}".replace("  ", " ")
        note = ctx.state.add_note(day, fact, "injury", "log")
        out["records"].append(ctx.state.ref("notes", note.id))
    kind = journal_kind(lower)
    if kind and not is_metcon:
        entry = JournalEntry(
            id=ctx.state.new_id("journal", day, kind.replace("_", "-")), date=day, kind=kind, text=text[:2000]
        )  # type: ignore[arg-type]
        ctx.state.put("journal", entry)
        out["records"].append(ctx.state.ref("journal", entry.id))
        out["reply"] = out["reply"] or "Noted in your journal."
    if not out["records"]:
        out["follow_up"] = (
            "I couldn't find data to log in that. Was it a check-in (joint ratings 1-5), a workout result, or something else?"
        )
    return out


JOURNAL_PATTERNS = [
    (
        "win",
        r"\b(pr\b|personal (?:best|record)|proud|nailed|crushed|felt (?:great|strong|amazing)|best (?:run|session))",
    ),
    (
        "struggle",
        r"\b(struggl\w*|frustrat\w*|rough (?:week|day)|felt (?:flat|awful|terrible|heavy)|unmotivated|dreading|burn(?:ed|t) out)",
    ),
    (
        "life_event",
        r"\b(work (?:trip|deadline|stress)|new job|moved|moving|wedding|baby|travel(?:l)?ing|family|vacation)",
    ),
    ("reflection", r"\b(i (?:feel|felt|think|noticed|realized)|lately|this week)"),
]


def journal_kind(lower: str) -> str | None:
    for kind, pat in JOURNAL_PATTERNS:
        if re.search(pat, lower):
            return kind
    return None
