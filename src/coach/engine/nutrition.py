"""Calorie-neutral macro distribution across the week + peri-workout fuelling cues."""

import datetime as dt

from coach.models import NutritionDay, Session
from coach.models.profile import NutritionRules

# Generic default; config/training.yaml rules.carb_tiers overrides it.
DEFAULT_TIERS = {
    "high": [
        "lower",
        "full_body",
        "run_long",
        "run_quality",
        "hyrox",
        "metcon",
        "test",
        "competition",
        "race",
    ],
    "moderate": ["upper", "sprint_upper", "run_easy"],
    "low": ["recovery", "rest"],
}


def carb_tier_for(
    session: Session | None, tomorrow: Session | None = None, tiers: dict[str, list[str]] | None = None
) -> str:
    """High on hard days and the day before the long run; moderate on other training days; low on rest days."""
    if tomorrow is not None and tomorrow.type in {"run_long", "race"}:
        return "high"
    if session is None:
        return "low"
    for tier, types in (tiers or DEFAULT_TIERS).items():
        if session.type in types:
            return tier
    return "moderate"


def distribute_week(
    week_kcal: float,
    bodyweight_kg: float,
    tiers: dict[dt.date, str],
    rules: NutritionRules,
    cutting: bool = False,
) -> list[NutritionDay]:
    """MacroFactor owns the weekly total; we only redistribute it (protein first, fat floor, then carbs)."""
    days = sorted(tiers)
    lo_p, hi_p = rules.protein_g_per_kg
    protein = round(bodyweight_kg * (hi_p if cutting else (lo_p + hi_p) / 2))
    fat_floor = rules.fat_floor_g
    fixed_kcal_day = protein * 4 + fat_floor * 9
    available_carb_kcal = week_kcal - fixed_kcal_day * len(days)
    desired = {d: bodyweight_kg * rules.carb_g_per_kg[tiers[d]] for d in days}  # type: ignore[index]
    desired_kcal = sum(desired.values()) * 4
    scaled = False
    extra_fat_day = 0.0
    if available_carb_kcal <= 0:
        carbs = {d: 0.0 for d in days}
        scaled = True
    elif desired_kcal > available_carb_kcal:
        factor = available_carb_kcal / desired_kcal
        carbs = {d: desired[d] * factor for d in days}
        scaled = True
    else:
        carbs = dict(desired)
        extra_fat_day = (available_carb_kcal - desired_kcal) / 9 / len(days)
    out = []
    for d in days:
        fat = fat_floor + extra_fat_day
        c = carbs[d]
        out.append(
            NutritionDay(
                date=d,
                carb_tier=tiers[d],
                kcal=round(protein * 4 + fat * 9 + c * 4),
                protein_g=round(protein),
                fat_g=round(fat),
                carbs_g=round(c),
                scaled=scaled,
                note="carbs scaled down proportionally: weekly target is tight" if scaled else "",
            )
        )
    return out


DEFAULT_PERI = {
    "pre": "Pre: 30-60 g carbs + sodium 60-90 min out",
    "during": "during: {lo}-{hi} g carbs/h + sodium (session > {minutes} min)",
    "after": "after: 30-40 g protein + carbs within 2 h",
    "easy_day": "Easy day: normal meals, protein at each.",
    "rest_day": "Rest day: protein spread over 4 meals.",
}


def peri_workout(session: Session | None, rules: NutritionRules) -> str:
    text = {**DEFAULT_PERI, **rules.peri_workout}
    if session is None or session.type in {"rest"}:
        return text["rest_day"]
    if session.type == "recovery":
        return text["easy_day"]
    parts = [text["pre"]]
    if session.expected_minutes > rules.intra_threshold_minutes:
        lo, hi = rules.intra_session_carbs_g_per_h
        parts.append(text["during"].format(lo=lo, hi=hi, minutes=rules.intra_threshold_minutes))
    parts.append(text["after"])
    return "; ".join(parts) + "."
