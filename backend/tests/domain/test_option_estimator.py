from decimal import Decimal

from app.domain.option_estimator import (
    black_scholes_put,
    estimate_put_range,
    implied_volatility_from_put,
)


def test_implied_volatility_reprices_the_opening_put() -> None:
    iv = implied_volatility_from_put(
        spot=Decimal("55"),
        strike=Decimal("50"),
        dte=35,
        premium=Decimal("1.50"),
        annual_rate=Decimal("0.04"),
    )

    assert iv is not None
    repriced = black_scholes_put(
        Decimal("55"), Decimal("50"), 35, iv, Decimal("0.04")
    )
    assert abs(repriced - Decimal("1.50")) < Decimal("0.01")


def test_put_range_is_ordered_and_falls_after_underlying_rally() -> None:
    iv = implied_volatility_from_put(
        Decimal("55"), Decimal("50"), 35, Decimal("1.50"), Decimal("0.04")
    )
    assert iv is not None

    low, base, high = estimate_put_range(
        spot=Decimal("60"),
        strike=Decimal("50"),
        dte=25,
        implied_volatility=iv,
        annual_rate=Decimal("0.04"),
    )

    assert Decimal("0") <= low <= base <= high
    assert high < Decimal("1.50")


def test_invalid_opening_premium_cannot_produce_implied_volatility() -> None:
    iv = implied_volatility_from_put(
        spot=Decimal("40"),
        strike=Decimal("50"),
        dte=35,
        premium=Decimal("5"),
        annual_rate=Decimal("0.04"),
    )

    assert iv is None


def test_expired_put_returns_intrinsic_value() -> None:
    value = black_scholes_put(
        Decimal("40"), Decimal("50"), 0, Decimal("0.50"), Decimal("0.04")
    )

    assert value == Decimal("10.00")
