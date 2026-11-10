"""Shoe mileage alerts and shoe assignment."""

from coach.models import Gear


def shoe_alerts(gear: list[Gear], alert_miles: float) -> list[str]:
    out = []
    for g in gear:
        if g.kind == "shoe" and not g.retired and g.distance_mi >= alert_miles:
            out.append(
                f"{g.name} at {g.distance_mi:.0f} mi: plan a replacement (alert at {alert_miles:.0f} mi)"
            )
    return out


def shoe_for(session_type: str, gear: list[Gear]) -> str | None:
    shoes = [g for g in gear if g.kind == "shoe" and not g.retired]
    if not shoes:
        return None
    firm = [g for g in shoes if "firm" in g.name.lower() or "race" in g.name.lower()]
    cushioned = [g for g in shoes if g not in firm]
    if session_type in {"hyrox", "run_quality", "race"} and firm:
        return firm[0].name
    return (cushioned or shoes)[0].name
