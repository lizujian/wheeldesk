from decimal import Decimal

import pytest

from app.domain.models import Bucket
from app.services.portfolio import PortfolioService


def test_deposits_increase_external_capital_not_investment_profit() -> None:
    service = PortfolioService(
        opening_equity=Decimal("100000"),
        balances={
            Bucket.CORE: Decimal("50000"),
            Bucket.CASH: Decimal("15000"),
            Bucket.WHEEL: Decimal("32000"),
            Bucket.LEAPS: Decimal("8000"),
            Bucket.UNALLOCATED: Decimal("5000"),
        },
        deposits=Decimal("10000"),
    )

    summary = service.summary()

    assert summary.total_equity == Decimal("110000")
    assert summary.net_external_capital == Decimal("110000")
    assert summary.investment_profit == Decimal("0")


def test_internal_transfer_keeps_total_equity_and_profit_unchanged() -> None:
    service = PortfolioService(
        opening_equity=Decimal("100000"),
        balances={Bucket.CASH: Decimal("10000"), Bucket.WHEEL: Decimal("90000")},
    )
    before = service.summary()

    service.transfer(Bucket.WHEEL, Bucket.CASH, Decimal("5000"))
    after = service.summary()

    assert after.total_equity == before.total_equity
    assert after.investment_profit == before.investment_profit
    assert after.balances[Bucket.CASH] == Decimal("15000")
    assert after.balances[Bucket.WHEEL] == Decimal("85000")


def test_internal_transfer_rejects_insufficient_bucket_cash() -> None:
    service = PortfolioService(
        opening_equity=Decimal("100"),
        balances={Bucket.CASH: Decimal("100")},
    )

    with pytest.raises(ValueError, match="资金不足"):
        service.transfer(Bucket.CASH, Bucket.WHEEL, Decimal("101"))
