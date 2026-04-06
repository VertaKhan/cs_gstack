from __future__ import annotations

import statistics
import time

import httpx

from cs2.config import Settings
from cs2.models.pricing import MarketData
from cs2.sources.base import (
    RateLimitError,
    SourceError,
    SourceFormatError,
)
from cs2.storage.cache import CacheStore

DMARKET_API_BASE = "https://api.dmarket.com/exchange/v1"

RETRY_DELAYS = [1.0, 3.0]


class DMarketClient:
    def __init__(self, settings: Settings, cache: CacheStore) -> None:
        self.settings = settings
        self.cache = cache
        self.client = httpx.Client(
            base_url=DMARKET_API_BASE,
            timeout=10.0,
        )

    def close(self) -> None:
        self.client.close()

    def fetch_market_data(self, item_name: str) -> MarketData:
        """Fetch market data from DMarket API with retry and cache."""
        cache_key = f"dmarket:market:{item_name}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return MarketData.model_validate_json(cached)

        last_error: Exception | None = None
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                return self._do_fetch(item_name, cache_key)
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
                last_error = exc
                if attempt < len(RETRY_DELAYS):
                    time.sleep(RETRY_DELAYS[attempt])
            except RateLimitError as exc:
                last_error = exc
                wait = min(exc.retry_after, 30.0)
                if attempt < len(RETRY_DELAYS):
                    time.sleep(wait)
            except (SourceFormatError, SourceError):
                raise

        raise SourceError(
            f"DMarket: failed to fetch market data for {item_name} after retries: {last_error}"
        )

    def _do_fetch(self, item_name: str, cache_key: str) -> MarketData:
        resp = self.client.get(
            "/market/items",
            params={"gameId": "a8db", "title": item_name, "limit": "20"},
        )

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "30"))
            raise RateLimitError(retry_after)
        if resp.status_code != 200:
            raise SourceError(f"DMarket API error: {resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            raise SourceFormatError("DMarket returned invalid JSON")

        objects = data.get("objects") if isinstance(data, dict) else None
        if objects is None:
            raise SourceFormatError("DMarket: expected 'objects' in response")

        if not objects:
            raise SourceError(f"No listings found on DMarket for {item_name}")

        # Extract prices from listings (DMarket prices are in USD cents as strings)
        prices: list[float] = []
        for obj in objects:
            price_data = obj.get("price") or {}
            usd_str = price_data.get("USD")
            if usd_str is not None:
                try:
                    prices.append(float(usd_str) / 100)
                except (ValueError, TypeError):
                    continue

        if not prices:
            raise SourceError(f"No valid prices on DMarket for {item_name}")

        sorted_prices = sorted(prices)
        median_price = statistics.median(sorted_prices)
        lowest_price = sorted_prices[0]

        market = MarketData(
            item_name=item_name,
            median_price=median_price,
            lowest_price=lowest_price,
            volume_24h=len(prices),
            recent_sales=[],
            source="dmarket",
        )

        self.cache.set(
            cache_key,
            market.model_dump_json(),
            ttl=self.settings.cache_ttl_market_price,
            source="dmarket",
        )
        return market
