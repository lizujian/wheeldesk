from datetime import date, timedelta
from decimal import Decimal

from app.domain.indicators import (
    DailyBar,
    drawdown_from_high,
    effective_ma200_break,
    find_support_levels,
    simple_moving_average,
    wilder_rsi,
)


def bar(day: int, close: str, low: str | None = None, open_: str | None = None) -> DailyBar:
    close_value = Decimal(close)
    return DailyBar(
        date=date(2025, 1, 1) + timedelta(days=day),
        open=Decimal(open_ or close),
        high=close_value + Decimal("2"),
        low=Decimal(low) if low is not None else close_value - Decimal("2"),
        close=close_value,
        volume=1_000_000,
    )


def test_simple_moving_average_uses_latest_period() -> None:
    assert simple_moving_average([Decimal(value) for value in range(1, 6)], 3) == Decimal("4")


def test_wilder_rsi_reports_gain_and_loss_extremes() -> None:
    rising = [Decimal(value) for value in range(1, 17)]
    falling = list(reversed(rising))

    assert wilder_rsi(rising, 14) == Decimal("100")
    assert wilder_rsi(falling, 14) == Decimal("0")


def test_drawdown_uses_highest_close_in_window() -> None:
    closes = [Decimal("80"), Decimal("100"), Decimal("90"), Decimal("80")]

    assert drawdown_from_high(closes, 4) == Decimal("0.20")


def test_effective_ma200_break_requires_two_completed_closes() -> None:
    confirmed = [Decimal("100")] * 200 + [Decimal("99"), Decimal("98")]
    one_day_only = [Decimal("100")] * 201 + [Decimal("99")]

    assert effective_ma200_break(confirmed) is True
    assert effective_ma200_break(one_day_only) is False


def test_support_levels_cluster_repeated_tqqq_swing_lows() -> None:
    bars = [bar(index, "100", low="97") for index in range(30)]
    bars[8] = bar(8, "94", low="90")
    bars[9] = bar(9, "97", low="95")
    bars[20] = bar(20, "95", low="90.8")
    bars[21] = bar(21, "98", low="96")

    levels = find_support_levels(bars, current_price=Decimal("100"), tolerance=Decimal("0.02"))

    assert levels[0].kind == "swing_cluster"
    assert levels[0].touches == 2
    assert Decimal("90") <= levels[0].price <= Decimal("91")
    assert levels[0].distance_pct >= Decimal("0.09")
