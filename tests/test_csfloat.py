from __future__ import annotations

import httpx
import pytest
import respx

from cs2.sources.base import (
    AuthError,
    ListingNotFoundError,
    RateLimitError,
    SourceError,
    SourceFormatError,
)
from cs2.sources.csfloat import CSFLOAT_API_BASE, CSFloatClient, parse_listing_id


LISTING_JSON = {
    "id": "abc-123",
    "price": 1250,
    "seller_id": "seller-1",
    "created_at": "2026-04-01T00:00:00Z",
    "item": {
        "market_hash_name": "AK-47 | Redline (Field-Tested)",
        "float_value": 0.25,
        "paint_seed": 42,
        "stickers": [
            {"name": "iBP Holo", "slot": 0, "wear": 0.0, "price": 5000},
        ],
        "inspect_link": "steam://rungame/730/...",
    },
}


class TestParseListingId:
    def test_url(self):
        assert parse_listing_id("https://csfloat.com/item/abc-123") == "abc-123"

    def test_raw_id(self):
        assert parse_listing_id("abc-123") == "abc-123"

    def test_url_with_params(self):
        assert parse_listing_id("https://csfloat.com/item/xyz-789?ref=1") == "xyz-789"


class TestCSFloatClient:
    @respx.mock
    def test_fetch_listing_success(self, settings, cache):
        respx.get(f"{CSFLOAT_API_BASE}/listings/abc-123").mock(
            return_value=httpx.Response(200, json=LISTING_JSON)
        )

        client = CSFloatClient(settings, cache)
        listing = client.fetch_listing("abc-123")

        assert listing.listing_id == "abc-123"
        assert listing.item_name == "AK-47 | Redline (Field-Tested)"
        assert listing.price == 12.50  # 1250 cents / 100
        assert listing.float_value == 0.25
        assert listing.source == "csfloat"
        assert len(listing.stickers) == 1
        client.close()

    @respx.mock
    def test_csfloat_auth_error(self, settings, cache):
        respx.get(f"{CSFLOAT_API_BASE}/listings/x").mock(
            return_value=httpx.Response(401)
        )

        client = CSFloatClient(settings, cache)
        with pytest.raises(AuthError, match="Invalid CSFloat API key"):
            client.fetch_listing("x")
        client.close()

    @respx.mock
    def test_csfloat_invalid_id(self, settings, cache):
        respx.get(f"{CSFLOAT_API_BASE}/listings/bad-id").mock(
            return_value=httpx.Response(404)
        )

        client = CSFloatClient(settings, cache)
        with pytest.raises(ListingNotFoundError, match="not found"):
            client.fetch_listing("bad-id")
        client.close()

    @respx.mock
    def test_csfloat_rate_limit(self, settings, cache):
        respx.get(f"{CSFLOAT_API_BASE}/listings/x").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "5"})
        )

        client = CSFloatClient(settings, cache)
        with pytest.raises(SourceError):
            client.fetch_listing("x")
        client.close()

    @respx.mock
    def test_csfloat_bad_json(self, settings, cache):
        respx.get(f"{CSFLOAT_API_BASE}/listings/x").mock(
            return_value=httpx.Response(200, content=b"not json at all")
        )

        client = CSFloatClient(settings, cache)
        with pytest.raises(SourceFormatError, match="invalid JSON"):
            client.fetch_listing("x")
        client.close()

    @respx.mock
    def test_csfloat_timeout(self, settings, cache):
        """Timeout on all attempts, no cache -> SourceError."""
        respx.get(f"{CSFLOAT_API_BASE}/listings/x").mock(
            side_effect=httpx.TimeoutException("timed out")
        )

        client = CSFloatClient(settings, cache)
        with pytest.raises(SourceError, match="Failed to fetch"):
            client.fetch_listing("x")
        client.close()

    @respx.mock
    def test_csfloat_network_error(self, settings, cache):
        """ConnectError on all attempts, no cache -> SourceError."""
        respx.get(f"{CSFLOAT_API_BASE}/listings/x").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        client = CSFloatClient(settings, cache)
        with pytest.raises(SourceError, match="Failed to fetch"):
            client.fetch_listing("x")
        client.close()

    @respx.mock
    def test_csfloat_timeout_cache_fallback(self, settings, cache):
        """Timeout but cache has data -> returns cached."""
        from cs2.models.pricing import RawListing

        cached_listing = RawListing(
            listing_id="x",
            item_name="Cached AK",
            price=10.0,
            source="csfloat",
        )
        cache.set("csfloat:listing:x", cached_listing.model_dump_json(), ttl=900, source="csfloat")

        respx.get(f"{CSFLOAT_API_BASE}/listings/x").mock(
            side_effect=httpx.TimeoutException("timed out")
        )

        client = CSFloatClient(settings, cache)
        listing = client.fetch_listing("x")
        assert listing.item_name == "Cached AK"
        client.close()

    @respx.mock
    def test_fetch_market_data(self, settings, cache):
        sales = [
            {"price": 1000, "sold_at": "2026-04-01"},
            {"price": 1100, "sold_at": "2026-04-01"},
            {"price": 900, "sold_at": "2026-04-01"},
        ]
        respx.get(f"{CSFLOAT_API_BASE}/history").mock(
            return_value=httpx.Response(200, json=sales)
        )

        client = CSFloatClient(settings, cache)
        md = client.fetch_market_data("AK-47 | Redline (Field-Tested)")
        assert md.median_price == 10.0  # sorted: 9, 10, 11 -> median = 10
        assert md.lowest_price == 9.0
        assert md.source == "csfloat"
        client.close()
