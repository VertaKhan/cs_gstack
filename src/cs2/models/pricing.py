from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from cs2.models.items import CanonicalItem


class ItemClass(str, Enum):
    COMMODITY = "commodity"
    EXACT_PREMIUM = "exact_premium"


class PricingResult(BaseModel):
    canonical: CanonicalItem
    base_price: float
    item_class: ItemClass
    estimated_value: float
    premium_breakdown: dict[str, float] = {}
    incomplete: bool = False


class RawListing(BaseModel):
    listing_id: str
    item_name: str
    price: float
    float_value: float | None = None
    paint_seed: int | None = None
    stickers: list[dict] = []
    inspect_link: str | None = None
    seller_id: str | None = None
    created_at: str | None = None
    source: str


class MarketData(BaseModel):
    item_name: str
    median_price: float
    lowest_price: float | None = None
    volume_24h: int | None = None
    recent_sales: list[dict] = []
    source: str
