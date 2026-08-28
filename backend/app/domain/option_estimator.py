import math
from decimal import Decimal

ZERO = Decimal("0")
PRICE = Decimal("0.0001")


def black_scholes_put(
    spot: Decimal,
    strike: Decimal,
    dte: int,
    implied_volatility: Decimal,
    annual_rate: Decimal = Decimal("0.04"),
) -> Decimal:
    if spot <= ZERO or strike <= ZERO or implied_volatility <= ZERO:
        raise ValueError("期权估值参数必须大于零")
    if dte <= 0:
        return max(strike - spot, ZERO).quantize(Decimal("0.01"))
    s = float(spot)
    k = float(strike)
    t = dte / 365
    sigma = float(implied_volatility)
    rate = float(annual_rate)
    denominator = sigma * math.sqrt(t)
    d1 = (math.log(s / k) + (rate + sigma * sigma / 2) * t) / denominator
    d2 = d1 - denominator
    value = k * math.exp(-rate * t) * _normal_cdf(-d2) - s * _normal_cdf(-d1)
    return Decimal(str(max(value, 0))).quantize(PRICE)


def implied_volatility_from_put(
    spot: Decimal,
    strike: Decimal,
    dte: int,
    premium: Decimal,
    annual_rate: Decimal = Decimal("0.04"),
) -> Decimal | None:
    if spot <= ZERO or strike <= ZERO or premium <= ZERO or dte <= 0:
        return None
    discounted_strike = strike * Decimal(str(math.exp(-float(annual_rate) * dte / 365)))
    minimum = max(discounted_strike - spot, ZERO)
    maximum = discounted_strike
    if premium < minimum or premium >= maximum:
        return None
    low = Decimal("0.01")
    high = Decimal("5.00")
    low_price = black_scholes_put(spot, strike, dte, low, annual_rate)
    high_price = black_scholes_put(spot, strike, dte, high, annual_rate)
    if not low_price <= premium <= high_price:
        return None
    for _ in range(80):
        middle = (low + high) / 2
        value = black_scholes_put(spot, strike, dte, middle, annual_rate)
        if abs(value - premium) <= PRICE:
            return middle.quantize(Decimal("0.000001"))
        if value < premium:
            low = middle
        else:
            high = middle
    return ((low + high) / 2).quantize(Decimal("0.000001"))


def estimate_put_range(
    spot: Decimal,
    strike: Decimal,
    dte: int,
    implied_volatility: Decimal,
    annual_rate: Decimal = Decimal("0.04"),
) -> tuple[Decimal, Decimal, Decimal]:
    values = tuple(
        black_scholes_put(
            spot,
            strike,
            dte,
            implied_volatility * factor,
            annual_rate,
        )
        for factor in (Decimal("0.80"), Decimal("1.00"), Decimal("1.20"))
    )
    return values


def _normal_cdf(value: float) -> float:
    return (1 + math.erf(value / math.sqrt(2))) / 2
