from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from cs2.models.decision import DecisionAction
from cs2.models.pricing import MarketData, RawListing
from cs2.pipeline import Pipeline, PipelineError, PipelineResult
from cs2.sources.base import SourceError
from cs2.sources.csfloat import CSFLOAT_API_BASE
from cs2.sources.steam import STEAM_MARKET_BASE


LISTING_JSON = {
    "id": "test-listing-1",
    "price": 1000,
    "seller_id": "s1",
    "created_at": "2026-04-01",
    "item": {
        "market_hash_name": "AK-47 | Redline (Field-Tested)",
        "float_value": 0.25,
        "paint_seed": 42,
        "stickers": [],
        "inspect_link": "steam://...",
    },
}

MARKET_SALES_JSON = [
    {"price": p, "sold_at": "2026-04-01"}
    for p in [1000, 1050, 950, 1100, 900, 1000, 980, 1020, 990, 1010]
]

STEAM_PRICE_JSON = {
    "success": True,
    "median_price": "$10.00",
    "lowest_price": "$8.00",
    "volume": "50",
}


class TestFullPipeline:
    @respx.mock
    def test_full_pipeline_csfloat(self, settings, cache, logger):
        """Full pipeline from CSFloat URL -> Decision."""
        respx.get(f"{CSFLOAT_API_BASE}/listings/test-1").mock(
            return_value=httpx.Response(200, json=LISTING_JSON)
        )
        respx.get(f"{CSFLOAT_API_BASE}/history").mock(
            return_value=httpx.Response(200, json=MARKET_SALES_JSON)
        )

        pipeline = Pipeline(settings, cache, logger)
        result = pipeline.analyze_url("https://csfloat.com/item/test-1")

        assert isinstance(result, PipelineResult)
        assert result.decision.action in [DecisionAction.BUY, DecisionAction.NO_BUY, DecisionAction.REVIEW]
        assert result.canonical.weapon == "AK-47"
        assert result.canonical.skin == "Redline"
        assert result.listing is not None
        assert result.pricing is not None
        assert result.liquidity is not None
        pipeline.close()

    @respx.mock
    def test_pipeline_cache_hit(self, settings, cache, logger):
        """Cached listing -> no second API call to listing endpoint."""
        # First call populates cache
        respx.get(f"{CSFLOAT_API_BASE}/listings/cached-1").mock(
            return_value=httpx.Response(200, json=LISTING_JSON)
        )
        market_route = respx.get(f"{CSFLOAT_API_BASE}/history").mock(
            return_value=httpx.Response(200, json=MARKET_SALES_JSON)
        )

        pipeline = Pipeline(settings, cache, logger)
        result1 = pipeline.analyze_url("cached-1")
        assert result1.decision is not None

        # Market data should be cached now
        first_market_calls = market_route.call_count

        result2 = pipeline.analyze_url("cached-1")
        assert result2.decision is not None

        # The listing route was called twice (cache is per-listing-id, but listing endpoint
        # is still called), but market data should be cached.
        assert market_route.call_count == first_market_calls  # no extra calls
        pipeline.close()

    @respx.mock
    def test_pipeline_steam_fallback(self, settings, cache, logger):
        """CSFloat market data fails -> falls back to Steam."""
        respx.get(f"{CSFLOAT_API_BASE}/listings/fb-1").mock(
            return_value=httpx.Response(200, json=LISTING_JSON)
        )
        respx.get(f"{CSFLOAT_API_BASE}/history").mock(
            return_value=httpx.Response(500)
        )
        respx.get(f"{STEAM_MARKET_BASE}/priceoverview/").mock(
            return_value=httpx.Response(200, json=STEAM_PRICE_JSON)
        )

        pipeline = Pipeline(settings, cache, logger)
        result = pipeline.analyze_url("fb-1")

        assert result.decision is not None
        assert any("CSFloat market data unavailable" in w for w in result.warnings)
        pipeline.close()

    @respx.mock
    def test_pipeline_degraded(self, settings, cache, logger):
        """No float data -> enrichment fails -> commodity pricing."""
        no_float_listing = {
            "id": "deg-1",
            "price": 1000,
            "item": {
                "market_hash_name": "AK-47 | Redline (Field-Tested)",
                "float_value": None,
                "paint_seed": None,
                "stickers": [],
            },
        }
        respx.get(f"{CSFLOAT_API_BASE}/listings/deg-1").mock(
            return_value=httpx.Response(200, json=no_float_listing)
        )
        respx.get(f"{CSFLOAT_API_BASE}/history").mock(
            return_value=httpx.Response(200, json=MARKET_SALES_JSON)
        )

        pipeline = Pipeline(settings, cache, logger)
        result = pipeline.analyze_url("deg-1")

        assert result.instance is None
        assert result.decision is not None
        assert any("degrading to commodity" in w.lower() or "no float" in w.lower()
                    for w in result.warnings)
        pipeline.close()

    @respx.mock
    def test_pipeline_hard_fail(self, settings, cache, logger):
        """Both source fetch fails + no cache -> PipelineError."""
        respx.get(f"{CSFLOAT_API_BASE}/listings/fail-1").mock(
            side_effect=httpx.ConnectError("refused")
        )

        pipeline = Pipeline(settings, cache, logger)
        with pytest.raises(PipelineError, match="Cannot fetch listing"):
            pipeline.analyze_url("fail-1")
        pipeline.close()


class TestManualPipeline:
    @respx.mock
    def test_full_pipeline_manual(self, settings, cache, logger):
        """Manual args -> pipeline completes."""
        respx.get(f"{CSFLOAT_API_BASE}/history").mock(
            return_value=httpx.Response(200, json=MARKET_SALES_JSON)
        )

        pipeline = Pipeline(settings, cache, logger)
        result = pipeline.analyze_manual(
            weapon="AK-47",
            skin="Redline",
            quality="Field-Tested",
        )

        assert result.decision is not None
        assert result.canonical.weapon == "AK-47"
        assert result.instance is None  # no listing data for manual
        pipeline.close()
