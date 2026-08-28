from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Bucket(StrEnum):
    CORE = "core"
    CASH = "cash"
    WHEEL = "wheel"
    LEAPS = "leaps"
    UNALLOCATED = "unallocated"


@dataclass(frozen=True)
class PortfolioSummary:
    total_equity: Decimal
    net_external_capital: Decimal
    investment_profit: Decimal
    balances: dict[Bucket, Decimal]

