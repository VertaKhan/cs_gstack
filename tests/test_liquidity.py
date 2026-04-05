from __future__ import annotations

import pytest

from cs2.engine.liquidity import analyze_liquidity, _calc_spread, _calc_safe_exit
from cs2.models.items import CanonicalItem
from cs2.models.liquidity import LiquidityGrade
from cs2.models.pricing import MarketData


def _canon():
    return CanonicalItem(weapon="AK-47", skin="Redline", quality="Field-Tested")


def _market(n_sales: int, prices: list[float] | None = None) -> MarketData:
    if prices is None:
        prices = [10.0] * n_sales
    sales = [{"price": p, "timestamp": "2026-04-01"} for p in prices]
    median = sorted(prices)[len(prices) // 2] if prices else 0.0
    return MarketData(
        item_name="AK-47 | Redline (FT)",
        median_price=median,
        lowest_price=min(prices) if prices else None,
        volume_24h=n_sales,
        recent_sales=sales,
        source="csfloat",
    )


class TestLiquidityGrades:
    def test_high_liquidity(self, settings):
        """20 sales/day (600 in 30d) -> HIGH."""
        md = _market(600)
        result = analyze_liquidity(_canon(), md, 10.0, 10.0, settings)
        assert result.grade == LiquidityGrade.HIGH
        assert result.avg_daily_volume == 20.0
        assert result.min_sell_days == 0
        assert result.max_sell_days == 1

    def test_medium_liquidity(self, settings):
        """3 sales/day (90 in 30d) -> MEDIUM."""
        md = _market(90)
        result = analyze_liquidity(_canon(), md, 10.0, 10.0, settings)
        assert result.grade == LiquidityGrade.MEDIUM
        assert result.min_sell_days == 1
        assert result.max_sell_days == 7

    def test_low_liquidity(self, settings):
        """0.2 sales/day (6 in 30d) -> LOW."""
        md = _market(6)
        result = analyze_liquidity(_canon(), md, 10.0, 10.0, settings)
        assert result.grade == LiquidityGrade.LOW
        assert result.min_sell_days == 7
        assert result.max_sell_days == 30

    def test_unknown_liquidity(self, settings):
        """<5 sales in 30d -> UNKNOWN."""
        md = _market(3)
        result = analyze_liquidity(_canon(), md, 10.0, 10.0, settings)
        assert result.grade == LiquidityGrade.UNKNOWN
        assert result.min_sell_days == 0
        assert result.max_sell_days == 999


class TestSafeExit:
    def test_safe_exit_calculation(self, settings):
        """safe_exit = min(estimated * 0.85, p10) clamped to floor."""
        prices = [8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0]
        md = _market(len(prices), prices)

        result = analyze_liquidity(_canon(), md, 15.0, 10.0, settings)

        # haircut = 15 * 0.85 = 12.75
        # p10 = sorted[ceil(10*0.10)-1] = sorted[0] = 8.0
        # safe_exit = min(12.75, 8.0) = 8.0
        # floor = 10 * 0.90 = 9.0
        # final = max(8.0, 9.0) = 9.0
        assert result.safe_exit_price == 9.0

    def test_safe_exit_floor(self, settings):
        """safe_exit clamped to base_price * 0.90."""
        # All sales at 5.0, estimated 6.0, base 10.0
        md = _market(10, [5.0] * 10)
        result = analyze_liquidity(_canon(), md, 6.0, 10.0, settings)

        # haircut = 6 * 0.85 = 5.1
        # p10 = 5.0
        # safe_exit = min(5.1, 5.0) = 5.0
        # floor = 10 * 0.90 = 9.0
        # final = max(5.0, 9.0) = 9.0
        assert result.safe_exit_price == 9.0


class TestSpread:
    def test_spread_calculation(self):
        prices = [10.0, 20.0]
        spread = _calc_spread(prices)
        # n=2, p25=sorted[0]=10.0, p75=sorted[1]=20.0, mid=15
        # (20-10)/15*100 = 66.67
        assert spread == pytest.approx(66.67, abs=0.01)

    def test_spread_percentile_based(self):
        """With more data points, spread uses p25/p75 not full range."""
        prices = [5.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 20.0]
        spread = _calc_spread(prices)
        # n=8, p25=sorted[2]=9.0, p75=sorted[6]=13.0, mid=11.0
        # (13-9)/11*100 = 36.36
        assert spread == pytest.approx(36.36, abs=0.01)

    def test_spread_single_price(self):
        assert _calc_spread([10.0]) == 0.0

    def test_spread_empty(self):
        assert _calc_spread([]) == 0.0

    def test_spread_identical(self):
        assert _calc_spread([10.0, 10.0, 10.0]) == 0.0
