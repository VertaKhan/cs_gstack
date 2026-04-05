from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class DecisionAction(str, Enum):
    BUY = "buy"
    NO_BUY = "no_buy"
    REVIEW = "review"


class Decision(BaseModel):
    action: DecisionAction
    confidence: float
    listing_price: float
    estimated_value: float
    margin_pct: float
    safe_exit_price: float
    reasons: list[str] = []
    risk_flags: list[str] = []
