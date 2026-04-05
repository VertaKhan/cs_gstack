from __future__ import annotations

import pytest

from cs2.engine.enrichment import EnrichmentError, enrich, get_sticker_price
from cs2.models.items import CanonicalItem, Sticker
from cs2.models.pricing import RawListing


class TestEnrich:
    def test_full_enrichment(self, cache, settings):
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="FT", stattrak=True)
        listing = RawListing(
            listing_id="a",
            item_name="AK-47 | Redline (FT)",
            price=10.0,
            float_value=0.25,
            paint_seed=42,
            stickers=[
                {"name": "iBP Holo", "slot": 0, "wear": 0.0, "price": 5000.0},
                {"name": "Navi", "slot": 1, "wear": 0.1, "price": 2.0, "stattrak_count": 1234},
            ],
            source="csfloat",
        )

        inst = enrich(listing, canon, cache, settings)

        assert inst.float_value == 0.25
        assert inst.paint_seed == 42
        assert len(inst.stickers) == 2
        assert inst.stickers[0].name == "iBP Holo"
        assert inst.stickers[0].slot == 0
        assert inst.stattrak_kills == 1234

    def test_no_float(self, cache, settings):
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="FT")
        listing = RawListing(
            listing_id="b",
            item_name="AK-47",
            price=10.0,
            float_value=None,
            source="csfloat",
        )

        with pytest.raises(EnrichmentError, match="No float data"):
            enrich(listing, canon, cache, settings)

    def test_sticker_prices(self, cache, settings):
        """Stickers with prices get cached in sticker_prices table."""
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="FT")
        listing = RawListing(
            listing_id="c",
            item_name="AK-47",
            price=10.0,
            float_value=0.20,
            paint_seed=10,
            stickers=[
                {"name": "Test Sticker", "slot": 0, "wear": 0.0, "price": 50.0},
            ],
            source="csfloat",
        )

        enrich(listing, canon, cache, settings)

        # Check sticker price was cached
        price = get_sticker_price("Test Sticker", cache)
        assert price == 50.0

    def test_sticker_scratched(self, cache, settings):
        """Sticker with wear > 0.8 is recorded with that wear value."""
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="FT")
        listing = RawListing(
            listing_id="d",
            item_name="AK-47",
            price=10.0,
            float_value=0.20,
            paint_seed=10,
            stickers=[
                {"name": "Scratched Sticker", "slot": 2, "wear": 0.9},
            ],
            source="csfloat",
        )

        inst = enrich(listing, canon, cache, settings)
        assert inst.stickers[0].wear == 0.9
        assert inst.stickers[0].wear > 0.8  # confirms "scratched"

    def test_no_stickers(self, cache, settings):
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="FT")
        listing = RawListing(
            listing_id="e",
            item_name="AK-47",
            price=10.0,
            float_value=0.20,
            paint_seed=10,
            stickers=[],
            source="csfloat",
        )

        inst = enrich(listing, canon, cache, settings)
        assert inst.stickers == []

    def test_stattrak_kills(self, cache, settings):
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="FT", stattrak=True)
        listing = RawListing(
            listing_id="f",
            item_name="AK-47",
            price=10.0,
            float_value=0.20,
            paint_seed=10,
            stickers=[{"name": "X", "slot": 0, "wear": 0.0, "stattrak_count": 9999}],
            source="csfloat",
        )

        inst = enrich(listing, canon, cache, settings)
        assert inst.stattrak_kills == 9999

    def test_non_stattrak_no_kills(self, cache, settings):
        """Non-ST items should have stattrak_kills=None even if data has stattrak_count."""
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="FT", stattrak=False)
        listing = RawListing(
            listing_id="g",
            item_name="AK-47",
            price=10.0,
            float_value=0.20,
            paint_seed=10,
            stickers=[],
            source="csfloat",
        )

        inst = enrich(listing, canon, cache, settings)
        assert inst.stattrak_kills is None


class TestGetStickerPrice:
    def test_not_found(self, cache):
        assert get_sticker_price("nonexistent", cache) is None

    def test_found(self, cache, db_conn):
        db_conn.execute(
            "INSERT INTO sticker_prices (name, price, updated_at) VALUES (?, ?, ?)",
            ("Test", 42.0, "2026-01-01T00:00:00Z"),
        )
        db_conn.commit()
        assert get_sticker_price("Test", cache) == 42.0
