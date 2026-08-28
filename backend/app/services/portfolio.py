from decimal import Decimal
from typing import Mapping

from app.domain.models import Bucket, PortfolioSummary

ZERO = Decimal("0")


class PortfolioService:
    def __init__(
        self,
        opening_equity: Decimal,
        balances: Mapping[Bucket, Decimal],
        deposits: Decimal = ZERO,
        withdrawals: Decimal = ZERO,
    ) -> None:
        if any(value < ZERO for value in (opening_equity, deposits, withdrawals)):
            raise ValueError("资金流金额不能为负数")
        if any(value < ZERO for value in balances.values()):
            raise ValueError("资金桶金额不能为负数")

        self.opening_equity = opening_equity
        self.deposits = deposits
        self.withdrawals = withdrawals
        self.balances = {bucket: ZERO for bucket in Bucket}
        self.balances.update(balances)

    def summary(self) -> PortfolioSummary:
        total_equity = sum(self.balances.values(), ZERO)
        external_capital = self.opening_equity + self.deposits - self.withdrawals
        return PortfolioSummary(
            total_equity=total_equity,
            net_external_capital=external_capital,
            investment_profit=total_equity - external_capital,
            balances=dict(self.balances),
        )

    def transfer(self, source: Bucket, target: Bucket, amount: Decimal) -> None:
        if amount <= ZERO:
            raise ValueError("转账金额必须大于零")
        if source == target:
            raise ValueError("来源和目标资金桶不能相同")
        if self.balances[source] < amount:
            raise ValueError("来源资金桶资金不足")

        self.balances[source] -= amount
        self.balances[target] += amount
