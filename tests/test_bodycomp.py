import datetime as dt

import pytest

from coach.engine import bodycomp as BC

D0 = dt.date(2026, 11, 16)


def day(i: int) -> dt.date:
    return D0 + dt.timedelta(days=i)


def test_steady_weight_stays_flat():
    t = BC.trend([(day(i), 96.0) for i in range(20)])
    assert t.value == 96.0 and t.rate_per_week == 0.0 and t.readings == 20


def test_one_high_reading_only_nudges_the_trend():
    readings = [(day(i), 96.0) for i in range(10)] + [(day(10), 98.0)]
    assert BC.trend(readings).value == pytest.approx(96.2)  # 10% of the 2 kg jump


def test_a_gap_counts_as_several_smoothing_steps():
    after_gap = BC.ewma_series([(day(0), 96.0), (day(7), 94.0)])[-1][1]
    next_day = BC.ewma_series([(day(0), 96.0), (day(1), 94.0)])[-1][1]
    assert after_gap == pytest.approx(96 - 2 * (1 - 0.9**7)) and after_gap < next_day


def test_weekly_rate_on_a_steady_loss():
    # 0.5 kg/week loss with +/-0.4 kg daily noise; the trend lags but sees the direction and size
    readings = [(day(i), 96.0 - 0.5 * i / 7 + (0.4 if i % 2 else -0.4)) for i in range(42)]
    t = BC.trend(readings)
    assert -0.6 < t.rate_per_week < -0.35


def test_duplicates_are_averaged_and_empty_is_none():
    assert BC.ewma_series([(day(0), 95.0), (day(0), 97.0)]) == [(day(0), 96.0)]
    assert BC.trend([]) is None
    assert BC.trend([(day(0), 96.0)]).rate_per_week is None
