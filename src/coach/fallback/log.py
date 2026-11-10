"""log fallback: turn chat messages into clean records; red flags stop training immediately."""

import datetime as dt
import re

from coach.context import Context
from coach.engine.parsing import classify_illness, detect_red_flags, parse_checkin_tag, parse_metcon_result
from coach.fallback.technique import skill_from_message
from coach.models import Checkin

STOP_MESSAGE = (
    "Stop training now and get checked by a doctor today ({flags}). If it's chest pain, fainting or severe breathlessness, "
    "call 911. I've paused all sessions until you tell me a doctor has cleared you."
)


def handle(ctx: Context, text: str, day: dt.date) -> dict:
    """Returns {'records': [...paths], 'reply': str, 'follow_up': str|None, 'red_flags': [...]}"""
    out: dict = {"records": [], "reply": "", "follow_up": None, "red_flags": []}
    flags = detect_red_flags(text)
    if flags:
        health = ctx.state.health()
        for f in flags:
            health.setdefault("red_flags", []).append(
                {"date": day.isoformat(), "flag": f, "text_untrusted": text[:200], "cleared_on": None}
            )
        ctx.state.write_json("health.json", health)
        ctx.health = health
        out["red_flags"] = flags
        out["records"].append("health.json")
        out["reply"] = STOP_MESSAGE.format(flags=", ".join(flags))
        return out
    illness = (
        classify_illness(text)
        if re.search(r"\b(sick|ill|cold|flu|fever|sore throat|runny|congest|aches?)\b", text, re.I)
        else None
    )
    if illness:
        health = ctx.state.health()
        health["illness"] = {
            "start": day.isoformat(),
            "symptoms": illness,
            "resolved_on": None,
            "text_untrusted": text[:200],
        }
        ctx.state.write_json("health.json", health)
        ctx.health = health
        out["records"].append("health.json")
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
        res = parse_metcon_result(text)
        path = f"metcons/{day.isoformat()}.json"
        existing = ctx.state.read_json(path) or {"date": day.isoformat(), "results": []}
        existing["results"].append(res)
        ctx.state.write_json(path, existing)
        out["records"].append(path)
        if res["missing"]:
            out["follow_up"] = {
                "score": "What was the final score (time, or rounds + reps)?",
                "rpe": "What was the session RPE (1-10)?",
            }[res["missing"][0]]
        out["reply"] = f"Logged {res['kind']}: " + ", ".join(
            f"{k}={v}" for k, v in res.items() if k in {"time_s", "rounds", "extra_reps", "calories", "rpe"}
        )
    tag = parse_checkin_tag(text)
    if tag and not (is_metcon and set(tag) <= {"session_rpe"}):
        path = f"checkins/{day.isoformat()}.json"
        prev = ctx.state.read_json(path) or {"date": day.isoformat(), "source": "chat"}
        merged = {**prev, **{k: v for k, v in tag.items() if k != "session_pain"}}
        if "session_pain" in tag:
            merged["session_pain"] = {**prev.get("session_pain", {}), **tag["session_pain"]}
        Checkin.model_validate(merged)
        ctx.state.write_json(path, merged)
        out["records"].append(path)
        parts = [f"{k} {v}" for k, v in tag.items() if k in {"back", "shoulders", "knees_achilles"}]
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
    for skill, level in skill_from_message(text):
        out.setdefault("skill_updates", []).append((skill, level))
    m = re.search(
        r"\b([a-z ]{3,30}?)\s+(?:aggravates?|bothers?|irritates?|hurts?)\s+my\s+((?:left|right|l|r)\s+)?(shoulder|back|knee|achilles|hip)",
        lower,
    )
    if m:
        fact = f"- {day}: {m.group(1).strip()} aggravates {(m.group(2) or '').strip()} {m.group(3)}".replace(
            "  ", " "
        )
        ctx.state.append_text("notes.md", fact + "\n")
        out["records"].append("notes.md")
    if not out["records"]:
        out["follow_up"] = (
            "I couldn't find data to log in that. Was it a check-in (joint ratings 1-5), a workout result, or something else?"
        )
    return out
