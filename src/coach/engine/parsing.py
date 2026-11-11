"""Deterministic parsers for check-in tags, metcon results and red-flag text.

External text (Hevy notes, Intervals comments, chat) is data, never instructions. These parsers only extract
numbers; Claude handles anything they can't, using the `log` skill.
"""

import re


def vocabulary(cfg=None) -> tuple[dict[str, str], dict[str, str]]:
    """(word -> joint region, word -> movement family) from config (checkin.regions words, family aliases)."""
    if cfg is None:
        from coach.config import load_config

        cfg = load_config()
    regions = {w.lower(): r for r, spec in cfg.profile.checkin.regions.items() for w in [r, *spec.words]}
    families = {w.lower(): f for f, fam in cfg.progressions.families.items() for w in [f, *fam.aliases]}
    return regions, families


def _alt(words) -> str:
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


_WELLNESS_RE = {
    "sleep_quality": re.compile(r"\bsleep(?: quality)?\s*[:=]?\s*([1-5])\b", re.IGNORECASE),
    "fatigue": re.compile(r"\b(?:fatigue|tired(?:ness)?)\s*[:=]?\s*([1-5])\b", re.IGNORECASE),
    "stress": re.compile(r"\bstress(?:ed)?\s*[:=]?\s*([1-5])\b", re.IGNORECASE),
    "mood": re.compile(r"\bmood\s*[:=]?\s*([1-5])\b", re.IGNORECASE),
    "motivation": re.compile(r"\b(?:motivation|motivated)\s*[:=]?\s*([1-5])\b", re.IGNORECASE),
}
_RPE_RE = re.compile(r"\b(?:s?rpe)\s*[:=]?\s*(\d+(?:\.\d)?)", re.IGNORECASE)
_ENJOY_RE = re.compile(r"\b(?:enjoy(?:ment|ed)?|fun)\s*[:=]?\s*([1-5])\b", re.IGNORECASE)
_SORE_RE = re.compile(r"\bsore(?:ness)?\s*[:=]?\s*([1-5])\b", re.IGNORECASE)
_VBT_RE = re.compile(r"\b(?:vbt|bar ?speed|velocity)\s*[:=]?\s*(0?\.\d+|\d\.\d+)\s*(?:m/s)?", re.IGNORECASE)


def parse_checkin_tag(text: str | None, cfg=None) -> dict:
    """'back 2 shoulder 3 rpe 8 enjoy 4' -> {'joints': {'back': 2, 'shoulders': 3}, 'session_rpe': 8.0, 'enjoyment': 4}.
    Region and family words come from config (checkin.regions, movement family aliases)."""
    if not text:
        return {}
    region_words, family_words = vocabulary(cfg)
    out: dict = {}
    joints: dict[str, int] = {}
    tag_re = re.compile(rf"\b({_alt(region_words)})s?\s*[:=]?\s*([1-5])\b", re.IGNORECASE)
    for word, val in tag_re.findall(text):
        region = region_words.get(word.lower())
        if region:
            joints[region] = int(val)
    if joints:
        out["joints"] = joints
    if m := _RPE_RE.search(text):
        v = float(m.group(1))
        if 1 <= v <= 10:
            out["session_rpe"] = v
    if m := _ENJOY_RE.search(text):
        out["enjoyment"] = int(m.group(1))
    if m := _SORE_RE.search(text):
        out["soreness"] = int(m.group(1))
    for field, pat in _WELLNESS_RE.items():
        if m := pat.search(text):
            out[field] = int(m.group(1))
    if m := _VBT_RE.search(text):
        out["bar_speed_mps"] = float(m.group(1))
    fam_alt = _alt(family_words)
    pain_re = re.compile(
        rf"\b({fam_alt})\b[^.\n]{{0,40}}?(?:hurt|pain|discomfort|sore|ache|tweak)[^.\n]{{0,25}}?(\d+(?:\.\d)?)\s*/\s*10",
        re.IGNORECASE,
    )
    pain_re2 = re.compile(
        rf"(?:hurt|pain|discomfort)[^.\n]{{0,25}}?(?:during|on|with)\s+(?:the\s+)?({fam_alt})[^.\n]{{0,25}}?(\d+(?:\.\d)?)\s*/\s*10",
        re.IGNORECASE,
    )
    pain: dict[str, float] = {}
    for word, val in [*pain_re.findall(text), *pain_re2.findall(text)]:
        fam = family_words.get(word.lower())
        if fam:
            pain[fam] = max(pain.get(fam, 0.0), float(val))
    if pain:
        out["session_pain"] = pain
    if re.search(r"slept (?:badly|poorly|terrible|awful)|bad sleep|poor sleep", text, re.IGNORECASE):
        out["sleep_note"] = "slept badly"
    if re.search(r"stiff(?:er|ness)? (?:this morning|today|up)|more stiff", text, re.IGNORECASE):
        low = text.lower()
        out["stiffness_up"] = sorted(
            {r for w, r in region_words.items() if re.search(rf"\b{re.escape(w)}", low)}
        ) or [next(iter(set(region_words.values())), "back")]
    return out


_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b")
_ROUNDS_RE = re.compile(r"\b(\d+)\s*(?:rounds?|rds?)\b(?:\s*(?:\+|and)\s*(\d+)\s*(?:reps?)?)?", re.IGNORECASE)
_CAL_RE = re.compile(r"\b(\d+)\s*(?:cal|cals|calories)\b", re.IGNORECASE)
_RPE_ANY = re.compile(r"\brpe\s*[:=]?\s*(\d+(?:\.\d)?)", re.IGNORECASE)
_MOVEMENT_NOTE = re.compile(
    r"([a-z][a-z ]+?)\s+(unbroken|heavy|broke(?:n)?|slow|fast|tough|easy|sucked)", re.IGNORECASE
)
_ROUND_REF = re.compile(r"(?:on|in)\s+round\s+(\d+)", re.IGNORECASE)


def parse_metcon_result(text: str) -> dict:
    """'Finished the Hyrox sim: 4 rounds in 26:40, sled heavy on round 3, wall balls unbroken, RPE 8.5'"""
    out: dict = {"raw_text_untrusted": text}
    low = text.lower()
    if "hyrox" in low:
        out["kind"] = "hyrox_sim"
    elif "open" in low and re.search(r"\b\d{2}\.\d\b", low):
        out["kind"] = "open"
        out["open_workout"] = re.search(r"\b(\d{2}\.\d)\b", low).group(1)  # type: ignore[union-attr]
    else:
        out["kind"] = "metcon"
    if m := _TIME_RE.search(text):
        h_or_m, mm, ss = m.groups()
        secs = int(h_or_m) * 3600 + int(mm) * 60 + int(ss) if ss else int(h_or_m) * 60 + int(mm)
        out["time_s"] = secs
    if m := _ROUNDS_RE.search(text):
        out["rounds"] = int(m.group(1))
        if m.group(2):
            out["extra_reps"] = int(m.group(2))
    if m := _CAL_RE.search(text):
        out["calories"] = int(m.group(1))
    if m := _RPE_ANY.search(text):
        out["rpe"] = float(m.group(1))
    notes = []
    for part in re.split(r"[,;]", text):
        if mm := _MOVEMENT_NOTE.search(part):
            note = {"movement": mm.group(1).strip().lower(), "note": mm.group(2).lower()}
            if r := _ROUND_REF.search(part):
                note["round"] = int(r.group(1))
            notes.append(note)
    if notes:
        out["movement_notes"] = notes
    if "time_s" in out and "rounds" in out:
        out["score_type"] = "time"
    elif "rounds" in out:
        out["score_type"] = "rounds_reps"
    elif "calories" in out:
        out["score_type"] = "calories"
    elif "time_s" in out:
        out["score_type"] = "time"
    else:
        out["score_type"] = "unknown"
    out["missing"] = [] if out["score_type"] != "unknown" else ["score"]
    if "rpe" not in out:
        out["missing"].append("rpe")
    return out


RED_FLAG_PATTERNS = {
    "chest pain": r"chest (?:pain|tight(?:ness)?|pressure)",
    "fainting": r"faint(?:ed|ing)?|passed out|blacked out|syncope",
    "unusual breathlessness": r"(?:unusual(?:ly)?|can'?t catch my|short(?:ness)? of) breath|breathless",
    "radiating limb pain or numbness": r"numb(?:ness)?|tingl\w*|(?:pain|ache) (?:radiat\w*|shooting|going) down",
    "sharp or worsening joint pain": r"sharp (?:\w+ )?pain|(?:pain|it)(?:'s| is)? getting worse|worsening",
    "possible rhabdomyolysis": r"dark (?:urine|pee)|cola[- ]colou?red|brown (?:urine|pee)",
    "palpitations / irregular heartbeat": r"palpitation|heart (?:was )?(?:racing|pounding|skipping|fluttering)|irregular (?:heart ?beat|pulse)",
    "possible heat illness": r"stopped sweating|confus\w* (?:on|during|after) the run|heat stroke|heatstroke|disoriented",
}
BELOW_NECK = r"fever|chills|chest congestion|congested chest|body aches?|aching all over|vomit|diarrh|stomach bug|flu\b"
ABOVE_NECK = r"runny nose|stuffy|sneez|sore throat|head cold|sinus|congested nose|nasal"


def detect_red_flags(text: str) -> list[str]:
    low = text.lower()
    return [name for name, pat in RED_FLAG_PATTERNS.items() if re.search(pat, low)]


def classify_illness(text: str) -> str | None:
    low = text.lower()
    if re.search(BELOW_NECK, low):
        return "below_neck"
    if re.search(ABOVE_NECK, low) or re.search(r"\b(sick|cold|ill)\b", low):
        return "above_neck"
    return None
