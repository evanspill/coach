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


def test_out_of_order_input_and_same_day_end():
    readings = [(day(2), 95.0), (day(0), 97.0), (day(1), 96.0)]
    assert BC.ewma_series(readings) == BC.ewma_series(sorted(readings))
    t = BC.trend(readings)
    assert t.day == day(2) and t.age_days(day(2)) == 0 and not t.is_stale(day(2))


def test_rate_needs_five_readings_and_fourteen_days():
    four = [(day(i * 5), 96.0 - i) for i in range(4)]  # 15 days span, only 4 readings
    assert BC.trend(four).rate_per_week is None
    short = [(day(i), 96.0) for i in range(14)]  # 13 days of history: no reading 14 days back
    assert BC.trend(short).rate_per_week is None
    exact = [(day(i), 96.0 - 0.1 * i) for i in range(15)]  # first reading exactly 14 days back
    assert BC.trend(exact).rate_per_week is not None and BC.trend(exact).rate_per_week < 0


def test_staleness_window():
    t = BC.trend([(day(0), 96.0)])
    assert not t.is_stale(day(BC.STALE_DAYS)) and t.is_stale(day(BC.STALE_DAYS + 1))


# ---------- callers: Context, calorie phase, reviews, report ----------


def _weigh(dates_values, field="weight_kg"):
    from coach.store import Store

    Store().upsert_metrics(
        [("daily", d.isoformat(), d, {"date": d.isoformat(), field: v}) for d, v in dates_values]
    )


def test_context_trend_weight_default_and_age(home):
    from coach.coaching.context import build

    ctx = build(today=day(10))
    assert ctx.bodyweight_kg() == 95.0 and ctx.bodyweight_age_days() is None
    _weigh([(day(i), 96.0) for i in range(5)] + [(day(5), 99.0)])
    ctx = build(today=day(10))
    assert ctx.bodyweight_kg() == pytest.approx(96.3, abs=0.05)  # one high reading only nudges it
    assert ctx.bodyweight_age_days() == 5
    assert ctx.body_trend("weight_kg", day(3)).value == 96.0  # `until` cuts the history
    assert ctx.body_trend("body_fat_pct") is None


def test_calorie_phase_uses_fresh_body_fat_trend_only(home):
    from types import SimpleNamespace

    from coach.coaching.context import build
    from coach.coaching.skills.plan_block import calorie_phase_from

    block = SimpleNamespace(key="B1")  # demo B1: calorie_phase auto, goal 10-12%
    assert calorie_phase_from(build(today=day(10)), block)[0] == "recomp"  # no trend yet
    _weigh([(day(i), 18.0) for i in range(7)], "body_fat_pct")
    phase, why = calorie_phase_from(build(today=day(10)), block)
    assert phase == "cut" and "18.0%" in why
    phase, why = calorie_phase_from(build(today=day(6 + BC.STALE_DAYS + 1)), block)
    assert phase == "recomp" and "days old" in why  # stale trend no longer decides


def test_reviews_and_report_show_trend_weight(b1):
    import argparse

    from coach.cli import cmd_report
    from coach.coaching.skills.review import block_review, weekly_review

    ctx, plan, _ = b1
    md, _ = weekly_review(ctx, plan)
    assert "Trend weight:" in md
    assert isinstance(block_review(ctx, ctx.block.id), str)
    out = cmd_report(argparse.Namespace(date=ctx.today.isoformat(), metric="weight", weeks=2))
    rows = out["rows"] if isinstance(out, dict) else out
    assert all("trend_weight_kg" in r for r in rows)


def test_block_review_trend_starts_once_settled(home):
    from coach.coaching.context import build

    _weigh([(day(i), 100.0 - i) for i in range(10)])  # weigh-ins start on the block's first day
    ctx = build(today=day(9))
    t = ctx.settled_trend("weight_kg", day(0))
    assert t.day == day(BC.MIN_READINGS - 1) and t.readings == BC.MIN_READINGS
    assert ctx.settled_trend("weight_kg", day(7)).day == day(7)  # enough history already: start where asked
    assert ctx.settled_trend("body_fat_pct", day(0)) is None


def test_weekly_review_rate_label(b1):
    from coach.coaching.skills.review import weekly_review

    ctx, plan, _ = b1
    md, _ = weekly_review(ctx, plan)
    assert "over 2 weeks)" not in md.split("Trend weight:")[1].splitlines()[0]
