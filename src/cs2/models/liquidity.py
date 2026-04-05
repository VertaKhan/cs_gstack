from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from cs2.models.items import CanonicalItem


class LiquidityGrade(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class LiquidityResult(BaseModel):
    canonical: CanonicalItem
    avg_daily_volume: float
    avg_spread_pct: float
    min_sell_days: int
    max_sell_days: int
    safe_exit_price: float
    grade: LiquidityGrade
