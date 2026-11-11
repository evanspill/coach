"""Run zones from LTHR and threshold pace (from the 30-min time trial)."""

from dataclasses import dataclass

# HR as a fraction of LTHR; pace as a multiple of threshold pace (s/mi), i.e. >1 is slower.
HR_ZONES = {
    "Z1": (0.65, 0.75),
    "Z2": (0.75, 0.84),
    "Z3": (0.85, 0.92),
    "MP": (0.86, 0.91),
    "T": (0.95, 1.00),
    "Z5": (1.00, 1.06),
    "strides": (0.0, 0.0),
}
PACE_FACTORS = {
    "Z1": (1.38, 1.55),
    "Z2": (1.22, 1.35),
    "Z3": (1.08, 1.15),
    "MP": (1.06, 1.10),
    "T": (0.98, 1.02),
    "Z5": (0.90, 0.96),
    "strides": (0.80, 0.88),
}


@dataclass
class Zones:
    lthr: int
    threshold_pace_s_per_mi: int

    def hr(self, zone: str) -> tuple[int, int]:
        lo, hi = HR_ZONES[zone]
        return (round(self.lthr * lo), round(self.lthr * hi))

    def pace(self, zone: str) -> tuple[int, int]:
        lo, hi = PACE_FACTORS[zone]
        # fast end first
        return (round(self.threshold_pace_s_per_mi * lo), round(self.threshold_pace_s_per_mi * hi))

    def z2_ceiling(self) -> int:
        return self.hr("Z2")[1]

    def as_dict(self) -> dict:
        return {
            "lthr": self.lthr,
            "threshold_pace_s_per_mi": self.threshold_pace_s_per_mi,
            "hr": {z: self.hr(z) for z in HR_ZONES if z != "strides"},
            "pace": {z: self.pace(z) for z in PACE_FACTORS},
        }


def zone_minutes_from_hr(avg_hr: float, duration_min: float, lthr: int) -> list[float]:
    """Crude single-average allocation when only average HR is available (noted as approximate)."""
    frac = avg_hr / lthr
    out = [0.0] * 5
    bounds = [0.75, 0.85, 0.95, 1.0]
    idx = sum(1 for b in bounds if frac >= b)
    out[idx] = round(duration_min, 1)
    return out


def easy_hard_split(zone_minutes: list[list[float]]) -> tuple[float, float]:
    """80/20 check: minutes at/below Z2 vs above, over many sessions."""
    easy = sum(z[0] + z[1] for z in zone_minutes)
    hard = sum(sum(z[2:]) for z in zone_minutes)
    return easy, hard


def miles_for_segment(
    duration_min: float | None, distance_mi: float | None, pace_s: float, reps: int = 1
) -> float:
    if distance_mi is not None:
        return distance_mi * reps
    if duration_min is None:
        return 0.0
    return duration_min * 60 / pace_s * reps
