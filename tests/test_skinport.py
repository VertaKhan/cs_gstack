from __future__ import annotations

import httpx
import pytest
import respx

from cs2.sources.base import SourceError, SourceFormatError
from cs2.sources.skinport import SKINPORT_API_BASE, SkinportClient


ITEMS_RESPONSE = [
    {
        "market_hash_name": "AK-47 | Redline (Field-Tested)",
        "min_price": 8.50,
        "median_price": 10.00,
        "quantity": 42,
    },
    {
        "market_hash_name": "AWP | Asiimov (Field-Tested)",
        "min_price": 25.00,
        "median_price": 28.00,
        "quantity": 15,
    },
]


class TestSkinportClient:
    @respx.mock
    def test_fetch_market_data_success(self, settings, cache):
        respx.get(f"{SKINPORT_API_BASE}/items").mock(
            return_value=httpx.Response(200, json=ITEMS_RESPONSE)
        )

        client = SkinportClient(settings, cache)
        md = client.fetch_market_data("AK-47 | Redline (Field-Tested)")
        assert md.median_price == 10.0
        assert md.lowest_price == 8.5
        assert md.volume_24h == 42
        assert md.source == "skinport"
        client.close()

    @respx.mock
    def test_item_not_found(self, settings, cache):
        respx.get(f"{SKINPORT_API_BASE}/items").mock(
            return_value=httpx.Response(200, json=ITEMS_RESPONSE)
        )

        client = SkinportClient(settings, cache)
        with pytest.raises(SourceError, match="not found on Skinport"):
            client.fetch_market_data("NonExistent Skin")
        client.close()

    @respx.mock
    def test_rate_limited(self, settings, cache):
        respx.get(f"{SKINPORT_API_BASE}/items").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "1"})
        )

        client = SkinportClient(settings, cache)
        with pytest.raises(SourceError, match="failed to fetch"):
            client.fetch_market_data("AK-47 | Redline (Field-Tested)")
        client.close()

    @respx.mock
    def test_bad_json(self, settings, cache):
        respx.get(f"{SKINPORT_API_BASE}/items").mock(
            return_value=httpx.Response(200, content=b"not json")
        )

        client = SkinportClient(settings, cache)
        with pytest.raises(SourceFormatError, match="invalid JSON"):
            client.fetch_market_data("AK-47")
        client.close()

    @respx.mock
    def test_server_error(self, settings, cache):
        respx.get(f"{SKINPORT_API_BASE}/items").mock(
            return_value=httpx.Response(500)
        )

        client = SkinportClient(settings, cache)
        with pytest.raises(SourceError, match="500"):
            client.fetch_market_data("AK-47")
        client.close()

    @respx.mock
    def test_timeout_retries_exhausted(self, settings, cache):
        respx.get(f"{SKINPORT_API_BASE}/items").mock(
            side_effect=httpx.TimeoutException("timed out")
        )

        client = SkinportClient(settings, cache)
        with pytest.raises(SourceError, match="failed to fetch"):
            client.fetch_market_data("AK-47")
        client.close()

    @respx.mock
    def test_cache_hit(self, settings, cache):
        from cs2.models.pricing import MarketData

        md = MarketData(item_name="X", median_price=5.0, source="skinport")
        cache.set("skinport:market:X", md.model_dump_json(), ttl=3600, source="skinport")

        route = respx.get(f"{SKINPORT_API_BASE}/items").mock(
            return_value=httpx.Response(200, json=ITEMS_RESPONSE)
        )

        client = SkinportClient(settings, cache)
        result = client.fetch_market_data("X")
        assert result.median_price == 5.0
        assert not route.called
        client.close()

    @respx.mock
    def test_not_list_response(self, settings, cache):
        respx.get(f"{SKINPORT_API_BASE}/items").mock(
            return_value=httpx.Response(200, json={"error": "bad"})
        )

        client = SkinportClient(settings, cache)
        with pytest.raises(SourceFormatError, match="expected list"):
            client.fetch_market_data("AK-47")
        client.close()
