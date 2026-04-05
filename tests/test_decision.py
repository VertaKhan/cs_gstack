from __future__ import annotations

import math

import pytest

from cs2.engine.decision import _calc_confidence, _sigmoid, decide
from cs2.models.decision import DecisionAction
from cs2.models.items import CanonicalItem
from cs2.models.liquidity import LiquidityGrade, LiquidityResult
from cs2.models.pricing import ItemClass, PricingResult


def _canon():
    return CanonicalItem(weapon="AK-47", skin="Redline", quality="Field-Tested")


def _pricing(
    base: float = 10.0,
    estimated: float = 10.0,
    incomplete: bool = False,
    premiums: dict | None = None,
) -> PricingResult:
    return PricingResult(
        canonical=_canon(),
        base_price=base,
        item_class=ItemClass.EXACT_PREMIUM if premiums else ItemClass.COMMODITY,
        estimated_value=estimated,
        premium_breakdown=premiums or {},
        incomplete=incomplete,
    )


def _liquidity(
    grade: LiquidityGrade = LiquidityGrade.HIGH,
    safe_exit: float = 12.0,
    volume: float = 20.0,
) -> LiquidityResult:
    sell_times = {
        LiquidityGrade.HIGH: (0, 1),
        LiquidityGrade.MEDIUM: (1, 7),
        LiquidityGrade.LOW: (7, 30),
        LiquidityGrade.UNKNOWN: (0, 999),
    }
    mn, mx = sell_times[grade]
    return LiquidityResult(
        canonical=_canon(),
        avg_daily_volume=volume,
        avg_spread_pct=5.0,
        min_sell_days=mn,
        max_sell_days=mx,
        safe_exit_price=safe_exit,
        grade=grade,
    )


class TestDecisionRules:
    def test_clear_buy(self, settings):
        """40% margin, safe exit positive, HIGH liquidity -> BUY."""
        pricing = _pricing(base=10.0, estimated=14.0, premiums={"float": 4.0})
        liq = _liquidity(grade=LiquidityGrade.HIGH, safe_exit=12.0)

        d = decide(pricing, liq, listing_price=10.0, settings=settings)

        assert d.action == DecisionAction.BUY
        assert d.margin_pct == pytest.approx(40.0, abs=0.1)
        assert d.confidence >= 0.5

    def test_clear_no_buy(self, settings):
        """-10% margin -> NO_BUY."""
        pricing = _pricing(base=10.0, estimated=9.0)
        liq = _liquidity(grade=LiquidityGrade.HIGH, safe_exit=8.0)

        d = decide(pricing, liq, listing_price=10.0, settings=settings)

        assert d.action == DecisionAction.NO_BUY
        assert d.margin_pct < 0

    def test_review_low_confidence(self, settings):
        """Incomplete data -> confidence capped at 0.49 -> REVIEW."""
        pricing = _pricing(base=10.0, estimated=14.0, incomplete=True, premiums={"float": 4.0})
        liq = _liquidity(grade=LiquidityGrade.HIGH, safe_exit=12.0)

        d = decide(pricing, liq, listing_price=10.0, settings=settings)

        assert d.action == DecisionAction.REVIEW
        assert d.confidence <= 0.49

    def test_review_unknown_liquidity(self, settings):
        """Unknown liquidity -> REVIEW."""
        pricing = _pricing(base=10.0, estimated=12.0, premiums={"float": 2.0})
        liq = _liquidity(grade=LiquidityGrade.UNKNOWN, safe_exit=11.0, volume=0.1)

        d = decide(pricing, liq, listing_price=10.0, settings=settings)

        assert d.action == DecisionAction.REVIEW

    def test_review_borderline(self, settings):
        """5% margin (< 15%) -> REVIEW (conservative)."""
        pricing = _pricing(base=10.0, estimated=10.5, premiums={"float": 0.5})
        liq = _liquidity(grade=LiquidityGrade.HIGH, safe_exit=10.2)

        d = decide(pricing, liq, listing_price=10.0, settings=settings)

        assert d.action == DecisionAction.REVIEW

    def test_review_no_safe_exit(self, settings):
        """Margin OK but safe_exit < listing -> not BUY."""
        pricing = _pricing(base=10.0, estimated=14.0, premiums={"float": 4.0})
        liq = _liquidity(grade=LiquidityGrade.HIGH, safe_exit=9.0)

        d = decide(pricing, liq, listing_price=10.0, settings=settings)

        # safe_margin = (9 - 10) / 10 = -10% -> BUY condition fails (safe_margin > 0)
        assert d.action != DecisionAction.BUY


class TestConfidence:
    def test_confidence_calculation(self, settings):
        """Verify weighted average formula components."""
        pricing = _pricing(base=10.0, estimated=14.0, premiums={"float": 4.0})
        liq = _liquidity(grade=LiquidityGrade.HIGH)
        margin_pct = 40.0

        conf = _calc_confidence(pricing, liq, margin_pct, settings)

        # data_completeness = 1.0 (not incomplete)
        # price_quality = 1.0 (has premiums)
        # margin_strength = sigmoid(40/20) = sigmoid(2.0) ~ 0.88
        # liquidity_score = 1.0 (HIGH)
        expected = 1.0 * 0.3 + 1.0 * 0.25 + _sigmoid(2.0) * 0.25 + 1.0 * 0.2
        assert conf == pytest.approx(expected, abs=0.01)

    def test_confidence_cap(self, settings):
        """Incomplete data -> capped at 0.49."""
        pricing = _pricing(base=10.0, estimated=20.0, incomplete=True, premiums={"float": 10.0})
        liq = _liquidity(grade=LiquidityGrade.HIGH, safe_exit=18.0)

        d = decide(pricing, liq, listing_price=10.0, settings=settings)
        assert d.confidence <= 0.49


class TestReasons:
    def test_reasons_generation(self, settings):
        pricing = _pricing(base=10.0, estimated=14.0, premiums={"float": 4.0})
        liq = _liquidity(grade=LiquidityGrade.HIGH, safe_exit=12.0)

        d = decide(pricing, liq, listing_price=10.0, settings=settings)

        assert d.action == DecisionAction.BUY
        assert len(d.reasons) > 0
        assert any("Underpriced" in r for r in d.reasons)

    def test_risk_flags(self, settings):
        """Low liquidity adds risk flag."""
        pricing = _pricing(base=10.0, estimated=14.0, premiums={"float": 4.0})
        liq = _liquidity(grade=LiquidityGrade.LOW, safe_exit=12.0, volume=0.5)

        d = decide(pricing, liq, listing_price=10.0, settings=settings)

        assert any("Low liquidity" in f for f in d.risk_flags)

    def test_overpriced_risk_flag(self, settings):
        pricing = _pricing(base=10.0, estimated=8.0)
        liq = _liquidity(grade=LiquidityGrade.HIGH, safe_exit=7.0)

        d = decide(pricing, liq, listing_price=10.0, settings=settings)

        assert any("Overpriced" in f for f in d.risk_flags)

    def test_incomplete_risk_flag(self, settings):
        pricing = _pricing(base=10.0, estimated=10.0, incomplete=True)
        liq = _liquidity(grade=LiquidityGrade.HIGH, safe_exit=9.0)

        d = decide(pricing, liq, listing_price=10.0, settings=settings)

        assert any("Incomplete" in f for f in d.risk_flags)


class TestSigmoid:
    def test_sigmoid_zero(self):
        assert _sigmoid(0) == pytest.approx(0.5, abs=0.001)

    def test_sigmoid_positive(self):
        assert _sigmoid(5) > 0.99

    def test_sigmoid_negative(self):
        assert _sigmoid(-5) < 0.01
