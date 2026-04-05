from __future__ import annotations

import httpx
import pytest
import respx

from cs2.sources.base import SourceError
from cs2.sources.steam import STEAM_MARKET_BASE, SteamClient, _parse_price, parse_steam_item_name


class TestParseSteamItemName:
    def test_url(self):
        url = "https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline%20(Field-Tested)"
        result = parse_steam_item_name(url)
        assert result == "AK-47 | Redline (Field-Tested)"

    def test_plain_name(self):
        assert parse_steam_item_name("AK-47 | Redline (FT)") == "AK-47 | Redline (FT)"


class TestParsePrice:
    def test_usd(self):
        assert _parse_price("$45.00") == 45.0

    def test_euro(self):
        assert _parse_price("45,00\u20ac") == 45.0

    def test_european_thousands(self):
        assert _parse_price("1.234,56\u20ac") == 1234.56

    def test_usd_thousands(self):
        assert _parse_price("$1,234.56") == 1234.56

    def test_garbage(self):
        assert _parse_price("free") == 0.0


class TestSteamClient:
    @respx.mock
    def test_fetch_market_data_success(self, settings, cache):
        respx.get(f"{STEAM_MARKET_BASE}/priceoverview/").mock(
            return_value=httpx.Response(200, json={
                "success": True,
                "median_price": "$10.00",
                "lowest_price": "$8.50",
                "volume": "42",
            })
        )

        client = SteamClient(settings, cache)
        md = client.fetch_market_data("AK-47 | Redline (Field-Tested)")
        assert md.median_price == 10.0
        assert md.lowest_price == 8.5
        assert md.volume_24h == 42
        assert md.source == "steam"
        client.close()

    @respx.mock
    def test_steam_unavailable(self, settings, cache):
        respx.get(f"{STEAM_MARKET_BASE}/priceoverview/").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        client = SteamClient(settings, cache)
        with pytest.raises(SourceError, match="unavailable"):
            client.fetch_market_data("AK-47 | Redline (FT)")
        client.close()

    @respx.mock
    def test_steam_rate_limited(self, settings, cache):
        respx.get(f"{STEAM_MARKET_BASE}/priceoverview/").mock(
            return_value=httpx.Response(429)
        )

        client = SteamClient(settings, cache)
        with pytest.raises(SourceError, match="rate limited"):
            client.fetch_market_data("AK-47")
        client.close()

    @respx.mock
    def test_steam_item_not_found(self, settings, cache):
        respx.get(f"{STEAM_MARKET_BASE}/priceoverview/").mock(
            return_value=httpx.Response(200, json={"success": False})
        )

        client = SteamClient(settings, cache)
        with pytest.raises(SourceError, match="not found"):
            client.fetch_market_data("NonExistent Skin")
        client.close()

    @respx.mock
    def test_steam_bad_json(self, settings, cache):
        respx.get(f"{STEAM_MARKET_BASE}/priceoverview/").mock(
            return_value=httpx.Response(200, content=b"not json")
        )

        client = SteamClient(settings, cache)
        with pytest.raises(SourceError, match="invalid JSON"):
            client.fetch_market_data("AK-47")
        client.close()

    @respx.mock
    def test_steam_server_error(self, settings, cache):
        respx.get(f"{STEAM_MARKET_BASE}/priceoverview/").mock(
            return_value=httpx.Response(500)
        )

        client = SteamClient(settings, cache)
        with pytest.raises(SourceError, match="500"):
            client.fetch_market_data("AK-47")
        client.close()

    @respx.mock
    def test_steam_cache_hit(self, settings, cache):
        """If data is cached, no HTTP call should be made."""
        from cs2.models.pricing import MarketData

        md = MarketData(item_name="X", median_price=5.0, source="steam")
        cache.set("steam:market:X", md.model_dump_json(), ttl=3600, source="steam")

        # This route should NOT be called
        route = respx.get(f"{STEAM_MARKET_BASE}/priceoverview/").mock(
            return_value=httpx.Response(200, json={"success": True, "median_price": "$99.00"})
        )

        client = SteamClient(settings, cache)
        result = client.fetch_market_data("X")
        assert result.median_price == 5.0
        assert not route.called
        client.close()

    @respx.mock
    def test_steam_timeout(self, settings, cache):
        respx.get(f"{STEAM_MARKET_BASE}/priceoverview/").mock(
            side_effect=httpx.TimeoutException("timed out")
        )

        client = SteamClient(settings, cache)
        with pytest.raises(SourceError, match="unavailable"):
            client.fetch_market_data("AK-47")
        client.close()
