from __future__ import annotations

import math

from cs2.config import Settings
from cs2.models.decision import Decision, DecisionAction
from cs2.models.liquidity import LiquidityGrade, LiquidityResult
from cs2.models.pricing import PricingResult


def decide(
    pricing: PricingResult,
    liquidity: LiquidityResult,
    listing_price: float,
    settings: Settings,
) -> Decision:
    """Apply rule-based decision logic.

    Returns Decision with action, confidence, reasons, and risk flags.
    """
    estimated_value = pricing.estimated_value
    safe_exit_price = liquidity.safe_exit_price

    # Margins
    if listing_price <= 0:
        listing_price = 0.01  # avoid division by zero
    margin_pct = ((estimated_value - listing_price) / listing_price) * 100
    safe_margin = ((safe_exit_price - listing_price) / listing_price) * 100

    # Confidence calculation
    confidence = _calc_confidence(
        pricing, liquidity, margin_pct, settings
    )

    # Cap confidence if incomplete data
    if pricing.incomplete:
        confidence = min(confidence, 0.49)

    # Decision rules
    reasons: list[str] = []
    risk_flags: list[str] = []

    # Collect reasons and risks
    if margin_pct > 0:
        reasons.append(f"Underpriced by {margin_pct:.1f}% vs estimated value")
    if safe_margin > 0:
        reasons.append(f"Safe exit above listing price (+{safe_margin:.1f}%)")
    if liquidity.grade == LiquidityGrade.HIGH:
        reasons.append(f"Good daily volume ({liquidity.avg_daily_volume}/day)")
    if liquidity.grade == LiquidityGrade.MEDIUM:
        reasons.append(f"Moderate volume ({liquidity.avg_daily_volume}/day)")

    if margin_pct < 0:
        risk_flags.append(f"Overpriced by {abs(margin_pct):.1f}%")
    if safe_margin < 0:
        risk_flags.append("Safe exit below listing price")
    if liquidity.grade == LiquidityGrade.LOW:
        risk_flags.append("Low liquidity — may take 7-30 days to sell")
    if liquidity.grade == LiquidityGrade.UNKNOWN:
        risk_flags.append("Unknown liquidity — insufficient market data")
    if pricing.incomplete:
        risk_flags.append("Incomplete pricing data — confidence capped")

    # Apply rules
    if confidence < settings.confidence_review_threshold:
        action = DecisionAction.REVIEW
        reasons.append("Low confidence — manual review recommended")
    elif (
        margin_pct > 15
        and safe_margin > 0
        and liquidity.grade not in (LiquidityGrade.LOW, LiquidityGrade.UNKNOWN)
    ):
        action = DecisionAction.BUY
    elif margin_pct < -5:
        action = DecisionAction.NO_BUY
        reasons.append(f"Negative margin ({margin_pct:.1f}%)")
    elif liquidity.grade == LiquidityGrade.UNKNOWN:
        action = DecisionAction.REVIEW
        reasons.append("Unknown liquidity — review recommended")
    else:
        action = DecisionAction.REVIEW
        reasons.append("Borderline case — manual review recommended")

    return Decision(
        action=action,
        confidence=round(confidence, 3),
        listing_price=round(listing_price, 2),
        estimated_value=round(estimated_value, 2),
        margin_pct=round(margin_pct, 1),
        safe_exit_price=round(safe_exit_price, 2),
        reasons=reasons,
        risk_flags=risk_flags,
    )


def _calc_confidence(
    pricing: PricingResult,
    liquidity: LiquidityResult,
    margin_pct: float,
    settings: Settings,
) -> float:
    """Calculate confidence as weighted average of four factors."""
    # 1. Data completeness (0.3 weight)
    data_completeness = 0.5 if pricing.incomplete else 1.0

    # 2. Price data quality (0.25 weight)
    if not pricing.incomplete and pricing.base_price > 0:
        price_quality = 1.0
    elif pricing.base_price > 0:
        price_quality = 0.5
    else:
        price_quality = 0.3

    # 3. Margin strength: sigmoid(margin / 20%) (0.25 weight)
    margin_strength = _sigmoid(margin_pct / 20.0)

    # 4. Liquidity score (0.2 weight)
    liq_scores = {
        LiquidityGrade.HIGH: 1.0,
        LiquidityGrade.MEDIUM: 0.5,
        LiquidityGrade.LOW: 0.2,
        LiquidityGrade.UNKNOWN: 0.1,
    }
    liquidity_score = liq_scores[liquidity.grade]

    confidence = (
        data_completeness * 0.3
        + price_quality * 0.25
        + margin_strength * 0.25
        + liquidity_score * 0.2
    )

    return max(0.0, min(1.0, confidence))


def _sigmoid(x: float) -> float:
    """Sigmoid function clamped to [0, 1]."""
    return 1.0 / (1.0 + math.exp(-x))
