from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Sequence

ZERO = Decimal("0")
HUNDRED = Decimal("100")


@dataclass(frozen=True)
class DailyBar:
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass(frozen=True)
class SupportLevel:
    price: Decimal
    kind: str
    touches: int
    distance_pct: Decimal


def simple_moving_average(values: Sequence[Decimal], period: int) -> Decimal:
    if period <= 0:
        raise ValueError("周期必须大于零")
    if len(values) < period:
        raise ValueError("数据不足，无法计算移动平均线")
    return sum(values[-period:], ZERO) / Decimal(period)


def wilder_rsi(closes: Sequence[Decimal], period: int = 14) -> Decimal:
    if period <= 0 or len(closes) < period + 1:
        raise ValueError("数据不足，无法计算 RSI")

    changes = [current - previous for previous, current in zip(closes, closes[1:])]
    gains = [max(change, ZERO) for change in changes]
    losses = [max(-change, ZERO) for change in changes]
    average_gain = sum(gains[:period], ZERO) / Decimal(period)
    average_loss = sum(losses[:period], ZERO) / Decimal(period)

    for gain, loss in zip(gains[period:], losses[period:]):
        average_gain = (average_gain * (period - 1) + gain) / Decimal(period)
        average_loss = (average_loss * (period - 1) + loss) / Decimal(period)

    if average_loss == ZERO:
        return HUNDRED if average_gain > ZERO else Decimal("50")
    if average_gain == ZERO:
        return ZERO
    relative_strength = average_gain / average_loss
    return HUNDRED - HUNDRED / (Decimal("1") + relative_strength)


def drawdown_from_high(closes: Sequence[Decimal], window: int = 252) -> Decimal:
    if not closes:
        raise ValueError("缺少收盘价")
    relevant = closes[-window:]
    high = max(relevant)
    if high <= ZERO:
        raise ValueError("最高收盘价必须大于零")
    return (high - relevant[-1]) / high


def effective_ma200_break(closes: Sequence[Decimal]) -> bool:
    if len(closes) < 201:
        return False
    previous_ma = simple_moving_average(closes[:-1], 200)
    current_ma = simple_moving_average(closes, 200)
    return closes[-2] < previous_ma and closes[-1] < current_ma


def find_support_levels(
    bars: Sequence[DailyBar],
    current_price: Decimal,
    lookback: int = 120,
    tolerance: Decimal = Decimal("0.02"),
    pivot_window: int = 2,
) -> list[SupportLevel]:
    if current_price <= ZERO:
        raise ValueError("现价必须大于零")
    relevant = list(bars[-lookback:])
    if len(relevant) < pivot_window * 2 + 1:
        return []

    pivots: list[Decimal] = []
    for index in range(pivot_window, len(relevant) - pivot_window):
        candidate = relevant[index].low
        neighbors = (
            relevant[index - pivot_window : index]
            + relevant[index + 1 : index + pivot_window + 1]
        )
        if all(candidate < neighbor.low for neighbor in neighbors):
            pivots.append(candidate)

    clusters: list[list[Decimal]] = []
    for pivot in sorted(pivots, reverse=True):
        for cluster in clusters:
            average = sum(cluster, ZERO) / Decimal(len(cluster))
            if abs(pivot - average) / average <= tolerance:
                cluster.append(pivot)
                break
        else:
            clusters.append([pivot])

    levels: list[SupportLevel] = []
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        price = sum(cluster, ZERO) / Decimal(len(cluster))
        if price < current_price:
            levels.append(
                SupportLevel(
                    price=price,
                    kind="swing_cluster",
                    touches=len(cluster),
                    distance_pct=(current_price - price) / current_price,
                )
            )

    closes = [bar.close for bar in relevant]
    for period, kind in ((50, "ma50"), (200, "ma200")):
        if len(closes) >= period:
            price = simple_moving_average(closes, period)
            if price < current_price:
                levels.append(
                    SupportLevel(
                        price=price,
                        kind=kind,
                        touches=1,
                        distance_pct=(current_price - price) / current_price,
                    )
                )

    kind_priority = {"swing_cluster": 0, "ma50": 1, "ma200": 2}
    return sorted(
        levels,
        key=lambda level: (-level.touches, kind_priority[level.kind], level.distance_pct),
    )

