"""Run zones: HR from LTHR (default) or from heart rate reserve (Whoop's model); pace from threshold pace."""

import math
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
# HR as a fraction of heart rate reserve (resting + f * (max - resting)), the model Whoop uses for its zones.
# Z1-Z5 are Whoop's zones 1-5 (its zone 1 starts at 40% on the athlete's settings screen); MP sits in Whoop zone 3
# and T is Whoop zone 4. Rounded up to whole bpm, Z2 matches Whoop's displayed zone 2 exactly and the other
# boundaries are within 1 bpm (Whoop starts each zone 1 bpm above the one below).
HRR_ZONES = {
    "Z1": (0.40, 0.60),
    "Z2": (0.60, 0.70),
    "Z3": (0.70, 0.80),
    "MP": (0.72, 0.80),
    "T": (0.80, 0.90),
    "Z5": (0.90, 1.00),
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


def _up(bpm: float) -> int:
    return math.ceil(bpm - 1e-9)  # round up, ignoring float noise (52 + 0.5 * 142 is 123, not 124)


@dataclass
class Zones:
    lthr: int
    threshold_pace_s_per_mi: int
    hr_model: str = "lthr"  # "lthr" | "hrr"
    max_hr: int | None = None
    resting_hr: int | None = None

    @property
    def uses_hrr(self) -> bool:
        return self.hr_model == "hrr" and self.max_hr is not None and self.resting_hr is not None

    def hr(self, zone: str) -> tuple[int, int]:
        if self.uses_hrr:
            assert self.max_hr is not None and self.resting_hr is not None
            lo, hi = HRR_ZONES[zone]
            if (lo, hi) == (0.0, 0.0):
                return (0, 0)
            reserve = self.max_hr - self.resting_hr
            return (_up(self.resting_hr + lo * reserve), _up(self.resting_hr + hi * reserve))
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
            "hr_model": "hrr" if self.uses_hrr else "lthr",
            "max_hr": self.max_hr,
            "resting_hr": self.resting_hr,
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
