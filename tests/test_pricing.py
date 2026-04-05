from __future__ import annotations

import json

import pytest

from cs2.engine.pricing import (
    _calc_float_premium,
    _calc_pattern_premium,
    _calc_sticker_premium,
    _get_sticker_multiplier,
    calculate_pricing,
)
from cs2.models.items import CanonicalItem, ExactInstance, Sticker
from cs2.models.pricing import ItemClass, MarketData


def _make_market_data(prices: list[float], median: float | None = None) -> MarketData:
    recent = [{"price": p, "timestamp": "2026-04-01"} for p in prices]
    if median is None:
        sorted_p = sorted(prices)
        median = sorted_p[len(sorted_p) // 2] if sorted_p else 0.0
    return MarketData(
        item_name="AK-47 | Redline (Field-Tested)",
        median_price=median,
        lowest_price=min(prices) if prices else None,
        volume_24h=len(prices),
        recent_sales=recent,
        source="csfloat",
    )


class TestBasePriceCommodity:
    def test_base_price_commodity(self, settings, cache):
        """Standard item with enough sales -> median price."""
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="Field-Tested")
        prices = [9.0, 9.5, 10.0, 10.5, 11.0, 10.0, 9.8, 10.2]
        md = _make_market_data(prices, median=10.0)

        result = calculate_pricing(canon, None, md, settings, cache)

        assert result.item_class == ItemClass.COMMODITY
        assert result.base_price > 0
        assert result.estimated_value == result.base_price
        assert result.premium_breakdown == {}

    def test_base_price_insufficient(self, settings, cache):
        """Less than 5 sales -> incomplete flag."""
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="Field-Tested")
        md = _make_market_data([10.0, 11.0], median=10.5)

        result = calculate_pricing(canon, None, md, settings, cache)
        assert result.incomplete is True


class TestBaseStatTrak:
    def test_base_price_stattrak(self, settings, cache):
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="Field-Tested", stattrak=True)
        prices = [20.0, 21.0, 22.0, 23.0, 24.0, 25.0]
        md = _make_market_data(prices, median=22.5)

        result = calculate_pricing(canon, None, md, settings, cache)
        assert result.base_price > 0


class TestClassifyPremium:
    def test_classify_commodity(self, settings, cache):
        """Normal float, no stickers -> COMMODITY."""
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="Field-Tested")
        inst = ExactInstance(canonical=canon, float_value=0.25, paint_seed=100)
        md = _make_market_data([10.0] * 10, median=10.0)

        result = calculate_pricing(canon, inst, md, settings, cache)
        assert result.item_class == ItemClass.COMMODITY

    def test_classify_premium_float(self, settings, cache):
        """Top 1% float -> EXACT_PREMIUM."""
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="Factory New")
        # Factory New range: 0.00-0.07, percentile 0.001/0.07 = 0.014 -> top 5%
        inst = ExactInstance(canonical=canon, float_value=0.0001, paint_seed=100)
        md = _make_market_data([10.0] * 10, median=10.0)

        result = calculate_pricing(canon, inst, md, settings, cache)
        assert result.item_class == ItemClass.EXACT_PREMIUM
        assert "float" in result.premium_breakdown


class TestFloatPremium:
    def test_float_premium_top1(self):
        """0.001 FN -> top 1% -> 50% premium."""
        premium, percentile = _calc_float_premium(0.001, "Factory New", 100.0)
        # percentile = 0.001 / 0.07 = 0.014 -> top 5% (0.05 threshold) -> 20%
        # Actually 0.014 > 0.01, so top 5% -> factor 0.20
        assert premium == pytest.approx(20.0, abs=0.01)
        assert percentile == pytest.approx(0.014, abs=0.001)

    def test_float_premium_actual_top1(self):
        """True top 1% float."""
        # FN range 0-0.07, top 1% = percentile <= 0.01 -> float <= 0.0007
        premium, percentile = _calc_float_premium(0.0005, "Factory New", 100.0)
        assert premium == pytest.approx(50.0, abs=0.01)
        assert percentile <= 0.01

    def test_float_premium_mid(self):
        """Mid-range float -> 0% premium."""
        premium, percentile = _calc_float_premium(0.25, "Field-Tested", 100.0)
        assert premium == 0.0

    def test_float_premium_bottom5(self):
        """Bottom 5% float -> -10% (penalty)."""
        # FT range: 0.15-0.38, bottom 5% = percentile >= 0.95
        # percentile = (0.375 - 0.15) / 0.23 = 0.978 -> bottom 5%
        premium, percentile = _calc_float_premium(0.375, "Field-Tested", 100.0)
        assert premium == pytest.approx(-10.0, abs=0.01)
        assert percentile >= 0.95

    def test_float_premium_unknown_quality(self):
        """Unknown quality -> no tier -> 0 premium."""
        premium, percentile = _calc_float_premium(0.25, "SomeRandomQuality", 100.0)
        assert premium == 0.0


class TestStickerPremium:
    def test_sticker_premium_kato14_holo(self, settings, cache, db_conn):
        """Katowice 2014 Holo -> 12% of sticker price."""
        db_conn.execute(
            "INSERT INTO sticker_prices (name, price, updated_at) VALUES (?, ?, ?)",
            ("Katowice 2014 (Holo) | iBUYPOWER", 5000.0, "2026-01-01"),
        )
        db_conn.commit()

        stickers = [Sticker(name="Katowice 2014 (Holo) | iBUYPOWER", slot=0, wear=0.0)]
        premium = _calc_sticker_premium(stickers, 10.0, settings, cache)

        # 5000 * 0.12 * 1.2 (best position) = 720
        assert premium == pytest.approx(720.0, abs=0.01)

    def test_sticker_premium_scratched(self, settings, cache, db_conn):
        """Scratched sticker -> 50% penalty."""
        db_conn.execute(
            "INSERT INTO sticker_prices (name, price, updated_at) VALUES (?, ?, ?)",
            ("Katowice 2014 (Holo) | Navi", 3000.0, "2026-01-01"),
        )
        db_conn.commit()

        stickers = [Sticker(name="Katowice 2014 (Holo) | Navi", slot=1, wear=0.9)]
        premium = _calc_sticker_premium(stickers, 10.0, settings, cache)

        # 3000 * 0.12 * 0.5 (scratched) = 180 (no best position bonus since slot=1)
        assert premium == pytest.approx(180.0, abs=0.01)

    def test_sticker_premium_below_min(self, settings, cache, db_conn):
        """Sticker below min value threshold -> no premium."""
        db_conn.execute(
            "INSERT INTO sticker_prices (name, price, updated_at) VALUES (?, ?, ?)",
            ("Cheap Holo Sticker", 2.0, "2026-01-01"),
        )
        db_conn.commit()

        stickers = [Sticker(name="Cheap Holo Sticker", slot=0, wear=0.0)]
        premium = _calc_sticker_premium(stickers, 10.0, settings, cache)
        assert premium == 0.0

    def test_sticker_best_position(self, settings, cache, db_conn):
        """Slot 0 -> 1.2x bonus."""
        db_conn.execute(
            "INSERT INTO sticker_prices (name, price, updated_at) VALUES (?, ?, ?)",
            ("Katowice 2014 | Team", 100.0, "2026-01-01"),
        )
        db_conn.commit()

        slot0 = [Sticker(name="Katowice 2014 | Team", slot=0, wear=0.0)]
        slot2 = [Sticker(name="Katowice 2014 | Team", slot=2, wear=0.0)]

        premium_slot0 = _calc_sticker_premium(slot0, 10.0, settings, cache)
        premium_slot2 = _calc_sticker_premium(slot2, 10.0, settings, cache)

        assert premium_slot0 > premium_slot2
        assert premium_slot0 == pytest.approx(premium_slot2 * 1.2, abs=0.01)


class TestStickerMultiplier:
    def test_kato14_holo(self, settings):
        assert _get_sticker_multiplier("Katowice 2014 (Holo) | iBUYPOWER", settings) == 0.12

    def test_kato14_non_holo(self, settings):
        assert _get_sticker_multiplier("Katowice 2014 | Team LDLC", settings) == 0.065

    def test_other_holo(self, settings):
        assert _get_sticker_multiplier("Fnatic (Holo) | Cologne 2016", settings) == 0.04

    def test_common(self, settings):
        assert _get_sticker_multiplier("Random Sticker", settings) == 0.0


class TestPatternPremium:
    def test_pattern_premium_blue_gem(self):
        # AK-47 Case Hardened seed 661 -> 5.0x base
        premium = _calc_pattern_premium("AK-47", "Case Hardened", 661, 100.0)
        assert premium == pytest.approx(500.0, abs=0.01)

    def test_pattern_unknown(self):
        premium = _calc_pattern_premium("AK-47", "Case Hardened", 999999, 100.0)
        assert premium == 0.0

    def test_pattern_non_case_hardened(self):
        premium = _calc_pattern_premium("AK-47", "Redline", 42, 100.0)
        assert premium == 0.0


class TestDegradedNoFloat:
    def test_degraded_no_float(self, settings, cache):
        """No enrichment data -> commodity pricing only."""
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="Field-Tested")
        md = _make_market_data([10.0] * 10, median=10.0)

        result = calculate_pricing(canon, None, md, settings, cache)
        assert result.item_class == ItemClass.COMMODITY
        assert result.premium_breakdown == {}


class TestStatTrakCollectorPremium:
    def test_st_low_float_premium(self, settings, cache):
        """ST + float < 0.01 -> 15% stattrak collector premium."""
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="Factory New", stattrak=True)
        inst = ExactInstance(canonical=canon, float_value=0.005, paint_seed=100)
        md = _make_market_data([10.0] * 10, median=10.0)

        result = calculate_pricing(canon, inst, md, settings, cache)
        assert "stattrak_collector" in result.premium_breakdown
