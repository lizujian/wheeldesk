from decimal import Decimal
from typing import Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db_models import BucketBalance, LedgerEvent, PortfolioProfile
from app.domain.allocation import allocation_targets
from app.domain.models import Bucket

ZERO = Decimal("0")


class PortfolioStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def initialize(
        self,
        age: int,
        opening_equity: Decimal,
        opening_date,
        allocations: Mapping[Bucket, Decimal] | None = None,
    ) -> dict:
        if self.profile() is not None:
            raise ValueError("账户已经初始化")
        fractions = allocation_targets(age)
        balances = {
            bucket: (opening_equity * fraction).quantize(Decimal("0.01"))
            for bucket, fraction in fractions.items()
        }
        balances[Bucket.UNALLOCATED] = opening_equity - sum(
            balances.values(), ZERO
        )
        profile = PortfolioProfile(
            id=1,
            age=age,
            opening_equity=opening_equity,
            opening_date=opening_date,
            currency="USD",
        )
        self.session.add(profile)
        for bucket, amount in balances.items():
            self.session.add(BucketBalance(bucket=bucket.value, amount=amount))
            if amount:
                self.session.add(
                    LedgerEvent(
                        event_type="opening_balance",
                        bucket=bucket.value,
                        amount=amount,
                        occurred_on=opening_date,
                        details={},
                    )
                )
        self.session.commit()
        return self.summary()

    def profile(self) -> PortfolioProfile | None:
        return self.session.get(PortfolioProfile, 1)

    def balances(self) -> dict[Bucket, Decimal]:
        values = {bucket: ZERO for bucket in Bucket}
        for row in self.session.scalars(select(BucketBalance)):
            values[Bucket(row.bucket)] = row.amount
        return values

    def summary(self) -> dict:
        profile = self.profile()
        if profile is None:
            return {"initialized": False}
        from app.services.capital_accounting import CapitalAccountingService

        balances = self.balances()
        total = sum(balances.values(), ZERO)
        deposits = self.session.scalar(
            select(func.coalesce(func.sum(LedgerEvent.amount), 0)).where(
                LedgerEvent.event_type == "deposit"
            )
        )
        withdrawals = self.session.scalar(
            select(func.coalesce(func.sum(LedgerEvent.amount), 0)).where(
                LedgerEvent.event_type == "withdrawal"
            )
        )
        external = profile.opening_equity + Decimal(deposits) + Decimal(withdrawals)
        target_fractions = allocation_targets(profile.age)
        targets = {}
        for bucket, fraction in target_fractions.items():
            target_amount = total * fraction
            actual = balances[bucket]
            targets[bucket.value] = {
                "fraction": fraction,
                "amount": target_amount.quantize(Decimal("0.01")),
                "actual": actual,
                "variance": actual - target_amount,
            }
        option_fraction = (
            target_fractions[Bucket.WHEEL] + target_fractions[Bucket.LEAPS]
        )
        option_actual = balances[Bucket.WHEEL] + balances[Bucket.LEAPS]
        option_target = total * option_fraction
        targets["options"] = {
            "fraction": option_fraction,
            "amount": option_target.quantize(Decimal("0.01")),
            "actual": option_actual,
            "variance": option_actual - option_target,
        }
        accounting = CapitalAccountingService(self.session)
        return {
            "initialized": True,
            "age": profile.age,
            "currency": profile.currency,
            "total_equity": total,
            "net_external_capital": external,
            "investment_profit": total - external,
            "other_holdings_value": profile.other_holdings_value,
            "balances": {bucket.value: value for bucket, value in balances.items()},
            "targets": targets,
            "capital": accounting.snapshot().payload(),
            "deployments": accounting.deployments(),
        }

    def update_other_holdings(self, amount: Decimal) -> dict:
        profile = self.profile()
        if profile is None:
            raise ValueError("请先初始化账户")
        profile.other_holdings_value = amount
        self.session.commit()
        return self.summary()

    def deposit(self, amount: Decimal, occurred_on, note: str = "") -> dict:
        self._change(Bucket.CASH, amount)
        self.session.add(
            LedgerEvent(
                event_type="deposit",
                bucket=Bucket.CASH.value,
                amount=amount,
                occurred_on=occurred_on,
                details={"note": note},
            )
        )
        self.session.commit()
        return self.summary()

    def transfer(self, source: Bucket, target: Bucket, amount: Decimal, occurred_on, note: str = "") -> dict:
        if source == target:
            raise ValueError("来源和目标资金桶不能相同")
        balances = self.balances()
        if source == Bucket.CASH:
            from app.services.capital_accounting import CapitalAccountingService

            available_cash = CapitalAccountingService(self.session).snapshot().cash.available
            if amount > available_cash:
                raise ValueError(f"可用现金不足，当前仅可使用 {available_cash}")
        if source in {Bucket.WHEEL, Bucket.LEAPS}:
            from app.services.capital_accounting import CapitalAccountingService

            snapshot = CapitalAccountingService(self.session).snapshot()
            available_principal = snapshot.options.available
            if amount > available_principal:
                raise ValueError(
                    f"{source.value} 未占用本金不足，当前仅可转出 {available_principal}"
                )
        if balances[source] < amount:
            raise ValueError("来源资金桶资金不足")
        self._change(source, -amount)
        self._change(target, amount)
        for bucket, signed in ((source, -amount), (target, amount)):
            self.session.add(
                LedgerEvent(
                    event_type="internal_transfer",
                    bucket=bucket.value,
                    amount=signed,
                    occurred_on=occurred_on,
                    details={"note": note, "counterparty": (target if bucket == source else source).value},
                )
            )
        self.session.commit()
        return self.summary()

    def auto_fund_core(self, purchase_cost: Decimal, occurred_on) -> Decimal:
        from app.services.capital_accounting import CapitalAccountingService

        snapshot = CapitalAccountingService(self.session).snapshot()
        shortfall = max(purchase_cost - snapshot.core.available, ZERO).quantize(
            Decimal("0.01")
        )
        if shortfall <= ZERO:
            return ZERO
        if shortfall > snapshot.cash.available:
            raise ValueError(
                f"核心仓资金不足，尚需 {shortfall}；可用现金不足，当前仅 {snapshot.cash.available}"
            )
        self._change(Bucket.CASH, -shortfall)
        self._change(Bucket.CORE, shortfall)
        for bucket, signed in (
            (Bucket.CASH, -shortfall),
            (Bucket.CORE, shortfall),
        ):
            self.session.add(
                LedgerEvent(
                    event_type="core_auto_funding",
                    bucket=bucket.value,
                    amount=signed,
                    occurred_on=occurred_on,
                    details={
                        "counterparty": (
                            Bucket.CORE.value
                            if bucket == Bucket.CASH
                            else Bucket.CASH.value
                        )
                    },
                )
            )
        return shortfall

    def _change(self, bucket: Bucket, amount: Decimal) -> None:
        row = self.session.get(BucketBalance, bucket.value)
        if row is None:
            row = BucketBalance(bucket=bucket.value, amount=ZERO)
            self.session.add(row)
        row.amount += amount
