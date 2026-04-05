from __future__ import annotations

import json
import warnings
from pathlib import Path

from cs2.config import Settings
from cs2.engine.enrichment import get_sticker_price
from cs2.models.items import CanonicalItem, ExactInstance, Sticker
from cs2.models.pricing import ItemClass, MarketData, PricingResult
from cs2.storage.cache import CacheStore

# Wear tier ranges: (min_float, max_float)
WEAR_TIERS: dict[str, tuple[float, float]] = {
    "Factory New": (0.00, 0.07),
    "Minimal Wear": (0.07, 0.15),
    "Field-Tested": (0.15, 0.38),
    "Well-Worn": (0.38, 0.45),
    "Battle-Scarred": (0.45, 1.00),
}

# Float factor table: (percentile_threshold, factor)
# Checked in order — first match wins
FLOAT_FACTORS: list[tuple[float, float]] = [
    (0.01, 0.50),   # top 1%
    (0.05, 0.20),   # top 5%
    (0.10, 0.10),   # top 10%
]
FLOAT_BOTTOM_FACTOR = -0.10  # bottom 5%

# Load special patterns
_SPECIAL_PATTERNS: dict | None = None


def _load_special_patterns() -> dict:
    global _SPECIAL_PATTERNS
    if _SPECIAL_PATTERNS is not None:
        return _SPECIAL_PATTERNS
    patterns_path = Path(__file__).parent.parent / "data" / "special_patterns.json"
    try:
        with open(patterns_path) as f:
            _SPECIAL_PATTERNS = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _SPECIAL_PATTERNS = {}
    return _SPECIAL_PATTERNS


def calculate_pricing(
    canonical: CanonicalItem,
    instance: ExactInstance | None,
    market_data: MarketData,
    settings: Settings,
    cache: CacheStore,
) -> PricingResult:
    """Calculate base price, classify item, and compute premiums."""
    base_price = _calculate_base_price(market_data, settings)
    incomplete = base_price is None

    if base_price is None:
        # Fallback: use median price even if insufficient data
        base_price = market_data.median_price
        if base_price <= 0:
            base_price = market_data.lowest_price or 0.0

    if instance is None:
        # No enrichment data — commodity mode
        return PricingResult(
            canonical=canonical,
            base_price=base_price,
            item_class=ItemClass.COMMODITY,
            estimated_value=base_price,
            premium_breakdown={},
            incomplete=incomplete,
        )

    # Classify item
    item_class, premium_breakdown = _classify_and_price(
        canonical, instance, base_price, settings, cache
    )

    total_premium = sum(premium_breakdown.values())
    estimated_value = base_price + total_premium

    return PricingResult(
        canonical=canonical,
        base_price=base_price,
        item_class=item_class,
        estimated_value=estimated_value,
        premium_breakdown=premium_breakdown,
        incomplete=incomplete,
    )


def _calculate_base_price(
    market_data: MarketData, settings: Settings
) -> float | None:
    """Calculate base price from market data. Returns None if insufficient data."""
    sales = market_data.recent_sales
    prices = [s["price"] for s in sales if isinstance(s.get("price"), (int, float))]

    if len(prices) < settings.min_sales_for_base_price:
        # Insufficient data
        if market_data.median_price > 0:
            return None  # Signal incomplete but use median as fallback upstream
        return None

    # Use up to last 50 sales
    prices = sorted(prices[:50])
    mid = len(prices) // 2
    if len(prices) % 2 == 0:
        return (prices[mid - 1] + prices[mid]) / 2
    return prices[mid]


def _classify_and_price(
    canonical: CanonicalItem,
    instance: ExactInstance,
    base_price: float,
    settings: Settings,
    cache: CacheStore,
) -> tuple[ItemClass, dict[str, float]]:
    """Classify item and calculate premium breakdown."""
    premiums: dict[str, float] = {}
    is_premium = False

    # 1. Float premium
    float_premium = _calc_float_premium(instance.float_value, canonical.quality, base_price)
    if float_premium != 0:
        premiums["float"] = round(float_premium, 2)
        if float_premium > 0:
            is_premium = True

    # 2. Sticker premium
    sticker_premium = _calc_sticker_premium(
        instance.stickers, base_price, settings, cache
    )
    if sticker_premium > 0:
        premiums["sticker"] = round(sticker_premium, 2)
        is_premium = True

    # 3. Pattern premium
    pattern_premium = _calc_pattern_premium(
        canonical.weapon, canonical.skin, instance.paint_seed, base_price
    )
    if pattern_premium > 0:
        premiums["pattern"] = round(pattern_premium, 2)
        is_premium = True
    elif pattern_premium is None:
        # Pattern DB unavailable — flag for manual review
        premiums["pattern"] = 0.0
        warnings.warn("Pattern DB unavailable — pattern premium not calculated")

    # 4. StatTrak collector premium (ST + float < 0.01)
    if canonical.stattrak and instance.float_value < 0.01:
        st_premium = round(base_price * 0.15, 2)
        premiums["stattrak_collector"] = st_premium
        is_premium = True

    item_class = ItemClass.EXACT_PREMIUM if is_premium else ItemClass.COMMODITY
    return item_class, premiums


def _calc_float_premium(
    float_value: float, quality: str, base_price: float
) -> float:
    """Calculate float premium based on percentile within wear tier."""
    tier_range = WEAR_TIERS.get(quality)
    if tier_range is None:
        return 0.0

    tier_min, tier_max = tier_range
    tier_width = tier_max - tier_min
    if tier_width <= 0:
        return 0.0

    # Percentile: 0.0 = best float in tier, 1.0 = worst
    percentile = (float_value - tier_min) / tier_width
    percentile = max(0.0, min(1.0, percentile))

    # Top percentiles (low float = good)
    for threshold, factor in FLOAT_FACTORS:
        if percentile <= threshold:
            return base_price * factor

    # Bottom 5% (high float within tier = worst)
    if percentile >= 0.95:
        return base_price * FLOAT_BOTTOM_FACTOR

    # Middle — no premium
    return 0.0


def _calc_sticker_premium(
    stickers: list[Sticker],
    base_price: float,
    settings: Settings,
    cache: CacheStore,
) -> float:
    """Calculate total sticker premium."""
    total = 0.0

    for sticker in stickers:
        sticker_price = get_sticker_price(sticker.name, cache)
        if sticker_price is None or sticker_price < settings.premium_sticker_min_value:
            continue

        # Determine multiplier based on sticker type
        mult = _get_sticker_multiplier(sticker.name, settings)
        if mult <= 0:
            continue

        premium = sticker_price * mult

        # Position bonus (slot 0 is best for most weapons)
        if sticker.slot == 0:
            premium *= settings.sticker_best_position_bonus

        # Scratched penalty
        if sticker.wear > 0.8:
            premium *= settings.sticker_scratched_penalty

        total += premium

    return total


def _get_sticker_multiplier(name: str, settings: Settings) -> float:
    """Get sticker premium multiplier based on sticker type."""
    name_lower = name.lower()

    if "katowice 2014" in name_lower:
        if "holo" in name_lower:
            return settings.sticker_mult_kato14_holo
        return settings.sticker_mult_kato14

    if "holo" in name_lower:
        return settings.sticker_mult_other_holo

    # Common stickers — no premium
    return 0.0


def _calc_pattern_premium(
    weapon: str, skin: str, paint_seed: int, base_price: float
) -> float | None:
    """Look up pattern premium from special_patterns.json.

    Returns premium amount, 0 if not special, None if DB unavailable.
    """
    patterns = _load_special_patterns()
    if not patterns:
        return None

    weapon_patterns = patterns.get(weapon, {})
    skin_patterns = weapon_patterns.get(skin, {})

    seed_str = str(paint_seed)
    if seed_str in skin_patterns:
        entry = skin_patterns[seed_str]
        premium_pct = entry.get("premium_pct", 0)
        return base_price * premium_pct

    return 0.0
