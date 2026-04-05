from __future__ import annotations

import math

from cs2.config import Settings
from cs2.models.items import CanonicalItem
from cs2.models.liquidity import LiquidityGrade, LiquidityResult
from cs2.models.pricing import MarketData


# Time-to-sell ranges by grade (min_days, max_days)
SELL_TIME: dict[LiquidityGrade, tuple[int, int]] = {
    LiquidityGrade.HIGH: (0, 1),
    LiquidityGrade.MEDIUM: (1, 7),
    LiquidityGrade.LOW: (7, 30),
    LiquidityGrade.UNKNOWN: (0, 999),
}


def analyze_liquidity(
    canonical: CanonicalItem,
    market_data: MarketData,
    estimated_value: float,
    base_price: float,
    settings: Settings,
) -> LiquidityResult:
    """Analyze liquidity for a canonical item based on market data."""
    sales = market_data.recent_sales
    sale_prices = [
        s["price"] for s in sales if isinstance(s.get("price"), (int, float))
    ]

    # Volume: assume recent_sales covers ~30 days
    total_sales = len(sale_prices)
    avg_daily_volume = total_sales / 30.0

    # Spread: (highest - lowest) / midpoint
    avg_spread_pct = _calc_spread(sale_prices)

    # Grade
    grade = _determine_grade(avg_daily_volume, total_sales, settings)

    # Time to sell
    min_sell_days, max_sell_days = SELL_TIME[grade]

    # Safe exit price
    safe_exit_price = _calc_safe_exit(
        estimated_value, base_price, sale_prices
    )

    return LiquidityResult(
        canonical=canonical,
        avg_daily_volume=round(avg_daily_volume, 2),
        avg_spread_pct=round(avg_spread_pct, 2),
        min_sell_days=min_sell_days,
        max_sell_days=max_sell_days,
        safe_exit_price=round(safe_exit_price, 2),
        grade=grade,
    )


def _calc_spread(prices: list[float]) -> float:
    """Calculate average spread percentage from recent sale prices."""
    if len(prices) < 2:
        return 0.0
    sorted_prices = sorted(prices)
    lowest = sorted_prices[0]
    highest = sorted_prices[-1]
    midpoint = (lowest + highest) / 2
    if midpoint <= 0:
        return 0.0
    return ((highest - lowest) / midpoint) * 100


def _determine_grade(
    avg_daily_volume: float,
    total_sales: int,
    settings: Settings,
) -> LiquidityGrade:
    """Determine liquidity grade based on volume."""
    if total_sales < 5:
        return LiquidityGrade.UNKNOWN
    if avg_daily_volume >= settings.liquidity_high_threshold:
        return LiquidityGrade.HIGH
    if avg_daily_volume >= settings.liquidity_low_threshold:
        return LiquidityGrade.MEDIUM
    return LiquidityGrade.LOW


def _calc_safe_exit(
    estimated_value: float,
    base_price: float,
    sale_prices: list[float],
) -> float:
    """Calculate safe exit price.

    safe_exit = min(estimated_value * 0.85, p10(comparable_sales))
    floor = base_price * 0.90
    """
    haircut = estimated_value * 0.85

    # 10th percentile of comparable sales
    if sale_prices:
        sorted_prices = sorted(sale_prices)
        p10_idx = max(0, math.ceil(len(sorted_prices) * 0.10) - 1)
        p10 = sorted_prices[p10_idx]
    else:
        p10 = haircut  # No data — fall through to haircut

    safe_exit = min(haircut, p10)
    floor = base_price * 0.90
    return max(safe_exit, floor)
