from __future__ import annotations

import warnings
from datetime import datetime, timezone

from cs2.config import Settings
from cs2.models.items import CanonicalItem, ExactInstance, Sticker
from cs2.models.pricing import RawListing
from cs2.storage.cache import CacheStore


class EnrichmentError(Exception):
    """Non-fatal enrichment failure — degrade to commodity."""
    pass


def enrich(
    listing: RawListing,
    canonical: CanonicalItem,
    cache: CacheStore,
    settings: Settings,
) -> ExactInstance:
    """Build ExactInstance from raw listing data + canonical identity.

    If enrichment fails partially, returns what we have and warns.
    If float_value is missing, raises EnrichmentError (degrade to commodity).
    """
    if listing.float_value is None:
        raise EnrichmentError("No float data available — degrading to commodity mode")

    stickers = _build_stickers(listing.stickers, cache, settings)

    stattrak_kills: int | None = None
    if canonical.stattrak:
        # CSFloat may provide stattrak_count in the raw data
        for s_data in listing.stickers:
            if "stattrak_count" in s_data:
                stattrak_kills = int(s_data["stattrak_count"])
                break

    return ExactInstance(
        canonical=canonical,
        float_value=listing.float_value,
        paint_seed=listing.paint_seed or 0,
        stickers=stickers,
        stattrak_kills=stattrak_kills,
    )


def _build_stickers(
    stickers_raw: list[dict],
    cache: CacheStore,
    settings: Settings,
) -> list[Sticker]:
    """Convert raw sticker dicts to Sticker models with prices cached."""
    stickers = []
    for s in stickers_raw:
        name = s.get("name", "")
        if not name:
            continue

        slot = int(s.get("slot", 0))
        wear = float(s.get("wear", 0.0))

        stickers.append(Sticker(name=name, slot=slot, wear=wear))

        # Cache sticker price if provided
        price = s.get("price")
        if price is not None:
            try:
                cache.conn.execute(
                    """INSERT OR REPLACE INTO sticker_prices (name, price, updated_at)
                       VALUES (?, ?, ?)""",
                    (name, float(price), datetime.now(timezone.utc).isoformat()),
                )
                cache.conn.commit()
            except Exception:
                warnings.warn(f"Failed to cache sticker price for {name}")

    return stickers


def get_sticker_price(name: str, cache: CacheStore) -> float | None:
    """Look up cached sticker price. Returns None if not found."""
    try:
        row = cache.conn.execute(
            "SELECT price FROM sticker_prices WHERE name = ?", (name,)
        ).fetchone()
        if row:
            return float(row[0])
    except Exception:
        pass
    return None
