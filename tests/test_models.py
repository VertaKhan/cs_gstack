from __future__ import annotations

import pytest
from pydantic import ValidationError

from cs2.models.items import CanonicalItem, ExactInstance, Sticker
from cs2.models.pricing import ItemClass, MarketData, PricingResult, RawListing
from cs2.models.liquidity import LiquidityGrade, LiquidityResult
from cs2.models.decision import Decision, DecisionAction


class TestSticker:
    def test_defaults(self):
        s = Sticker(name="iBP Holo", slot=0)
        assert s.wear == 0.0

    def test_full(self):
        s = Sticker(name="Navi", slot=2, wear=0.5)
        assert s.name == "Navi"
        assert s.slot == 2
        assert s.wear == 0.5


class TestCanonicalItem:
    def test_basic(self):
        item = CanonicalItem(weapon="AK-47", skin="Redline", quality="Field-Tested")
        assert item.stattrak is False
        assert item.souvenir is False

    def test_stattrak(self):
        item = CanonicalItem(weapon="AK-47", skin="Redline", quality="FT", stattrak=True)
        assert item.stattrak is True

    def test_vanilla_knife(self):
        item = CanonicalItem(weapon="Karambit", skin="", quality="")
        assert item.skin == ""
        assert item.quality == ""


class TestExactInstance:
    def test_full_instance(self):
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="FT", stattrak=True)
        inst = ExactInstance(
            canonical=canon,
            float_value=0.25,
            paint_seed=42,
            stickers=[Sticker(name="iBP", slot=0)],
            stattrak_kills=1234,
        )
        assert inst.float_value == 0.25
        assert inst.stattrak_kills == 1234

    def test_non_stattrak_kills_rejected(self):
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="FT", stattrak=False)
        with pytest.raises(ValidationError, match="stattrak_kills must be None"):
            ExactInstance(
                canonical=canon,
                float_value=0.25,
                paint_seed=42,
                stattrak_kills=100,
            )

    def test_non_stattrak_none_kills_ok(self):
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="FT", stattrak=False)
        inst = ExactInstance(
            canonical=canon,
            float_value=0.25,
            paint_seed=42,
            stattrak_kills=None,
        )
        assert inst.stattrak_kills is None


class TestRawListing:
    def test_minimal(self):
        rl = RawListing(listing_id="x", item_name="AK-47", price=10.0, source="csfloat")
        assert rl.float_value is None
        assert rl.stickers == []

    def test_full(self):
        rl = RawListing(
            listing_id="x",
            item_name="AK-47",
            price=10.0,
            float_value=0.15,
            paint_seed=100,
            stickers=[{"name": "a", "slot": 0}],
            inspect_link="steam://...",
            seller_id="s1",
            created_at="2026-01-01",
            source="csfloat",
        )
        assert rl.float_value == 0.15
        assert len(rl.stickers) == 1


class TestMarketData:
    def test_minimal(self):
        md = MarketData(item_name="AK-47", median_price=10.0, source="steam")
        assert md.volume_24h is None
        assert md.recent_sales == []


class TestPricingResult:
    def test_commodity(self):
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="FT")
        pr = PricingResult(
            canonical=canon,
            base_price=10.0,
            item_class=ItemClass.COMMODITY,
            estimated_value=10.0,
        )
        assert pr.incomplete is False
        assert pr.premium_breakdown == {}


class TestLiquidityResult:
    def test_grades(self):
        assert LiquidityGrade.HIGH.value == "high"
        assert LiquidityGrade.UNKNOWN.value == "unknown"


class TestDecision:
    def test_buy(self):
        d = Decision(
            action=DecisionAction.BUY,
            confidence=0.85,
            listing_price=10.0,
            estimated_value=15.0,
            margin_pct=50.0,
            safe_exit_price=12.0,
            reasons=["Underpriced"],
            risk_flags=[],
        )
        assert d.action == DecisionAction.BUY
        assert d.confidence == 0.85

    def test_action_values(self):
        assert DecisionAction.BUY.value == "buy"
        assert DecisionAction.NO_BUY.value == "no_buy"
        assert DecisionAction.REVIEW.value == "review"
