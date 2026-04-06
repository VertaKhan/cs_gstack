from __future__ import annotations

import httpx
import pytest
import respx

from cs2.sources.base import SourceError, SourceFormatError
from cs2.sources.dmarket import DMARKET_API_BASE, DMarketClient


MARKET_RESPONSE = {
    "objects": [
        {"price": {"USD": "1000"}, "title": "AK-47 | Redline (Field-Tested)"},
        {"price": {"USD": "1100"}, "title": "AK-47 | Redline (Field-Tested)"},
        {"price": {"USD": "900"}, "title": "AK-47 | Redline (Field-Tested)"},
        {"price": {"USD": "1050"}, "title": "AK-47 | Redline (Field-Tested)"},
    ],
}


class TestDMarketClient:
    @respx.mock
    def test_fetch_market_data_success(self, settings, cache):
        respx.get(f"{DMARKET_API_BASE}/market/items").mock(
            return_value=httpx.Response(200, json=MARKET_RESPONSE)
        )

        client = DMarketClient(settings, cache)
        md = client.fetch_market_data("AK-47 | Redline (Field-Tested)")
        # prices: 9.0, 10.0, 10.5, 11.0 -> median = (10.0+10.5)/2 = 10.25
        assert md.median_price == 10.25
        assert md.lowest_price == 9.0
        assert md.volume_24h == 4
        assert md.source == "dmarket"
        client.close()

    @respx.mock
    def test_no_listings(self, settings, cache):
        respx.get(f"{DMARKET_API_BASE}/market/items").mock(
            return_value=httpx.Response(200, json={"objects": []})
        )

        client = DMarketClient(settings, cache)
        with pytest.raises(SourceError, match="No listings found"):
            client.fetch_market_data("NonExistent")
        client.close()

    @respx.mock
    def test_rate_limited(self, settings, cache):
        respx.get(f"{DMARKET_API_BASE}/market/items").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "1"})
        )

        client = DMarketClient(settings, cache)
        with pytest.raises(SourceError, match="failed to fetch"):
            client.fetch_market_data("AK-47")
        client.close()

    @respx.mock
    def test_bad_json(self, settings, cache):
        respx.get(f"{DMARKET_API_BASE}/market/items").mock(
            return_value=httpx.Response(200, content=b"not json")
        )

        client = DMarketClient(settings, cache)
        with pytest.raises(SourceFormatError, match="invalid JSON"):
            client.fetch_market_data("AK-47")
        client.close()

    @respx.mock
    def test_missing_objects_key(self, settings, cache):
        respx.get(f"{DMARKET_API_BASE}/market/items").mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        client = DMarketClient(settings, cache)
        with pytest.raises(SourceFormatError, match="expected 'objects'"):
            client.fetch_market_data("AK-47")
        client.close()

    @respx.mock
    def test_server_error(self, settings, cache):
        respx.get(f"{DMARKET_API_BASE}/market/items").mock(
            return_value=httpx.Response(500)
        )

        client = DMarketClient(settings, cache)
        with pytest.raises(SourceError, match="500"):
            client.fetch_market_data("AK-47")
        client.close()

    @respx.mock
    def test_timeout_retries_exhausted(self, settings, cache):
        respx.get(f"{DMARKET_API_BASE}/market/items").mock(
            side_effect=httpx.TimeoutException("timed out")
        )

        client = DMarketClient(settings, cache)
        with pytest.raises(SourceError, match="failed to fetch"):
            client.fetch_market_data("AK-47")
        client.close()

    @respx.mock
    def test_cache_hit(self, settings, cache):
        from cs2.models.pricing import MarketData

        md = MarketData(item_name="X", median_price=5.0, source="dmarket")
        cache.set("dmarket:market:X", md.model_dump_json(), ttl=3600, source="dmarket")

        route = respx.get(f"{DMARKET_API_BASE}/market/items").mock(
            return_value=httpx.Response(200, json=MARKET_RESPONSE)
        )

        client = DMarketClient(settings, cache)
        result = client.fetch_market_data("X")
        assert result.median_price == 5.0
        assert not route.called
        client.close()

    @respx.mock
    def test_no_valid_prices(self, settings, cache):
        """Listings exist but none have valid USD prices."""
        respx.get(f"{DMARKET_API_BASE}/market/items").mock(
            return_value=httpx.Response(200, json={
                "objects": [
                    {"price": {"EUR": "1000"}, "title": "AK-47"},
                    {"price": {}, "title": "AK-47"},
                ],
            })
        )

        client = DMarketClient(settings, cache)
        with pytest.raises(SourceError, match="No valid prices"):
            client.fetch_market_data("AK-47")
        client.close()
