from __future__ import annotations

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

SKINPORT_API_BASE = "https://api.skinport.com/v1"

RETRY_DELAYS = [1.0, 3.0]


class SkinportClient:
    def __init__(self, settings: Settings, cache: CacheStore) -> None:
        self.settings = settings
        self.cache = cache
        self.client = httpx.Client(
            base_url=SKINPORT_API_BASE,
            timeout=10.0,
        )

    def close(self) -> None:
        self.client.close()

    def fetch_market_data(self, item_name: str) -> MarketData:
        """Fetch market data from Skinport API with retry and cache."""
        cache_key = f"skinport:market:{item_name}"
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
            f"Skinport: failed to fetch market data for {item_name} after retries: {last_error}"
        )

    def _do_fetch(self, item_name: str, cache_key: str) -> MarketData:
        resp = self.client.get(
            "/items",
            params={"app_id": "730", "currency": "USD"},
        )

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "30"))
            raise RateLimitError(retry_after)
        if resp.status_code != 200:
            raise SourceError(f"Skinport API error: {resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            raise SourceFormatError("Skinport returned invalid JSON")

        if not isinstance(data, list):
            raise SourceFormatError("Skinport: expected list response")

        # Find matching item
        match = None
        for entry in data:
            if entry.get("market_hash_name") == item_name:
                match = entry
                break

        if match is None:
            raise SourceError(f"Item not found on Skinport: {item_name}")

        min_price = match.get("min_price")
        median_price = match.get("median_price")
        quantity = match.get("quantity")

        if median_price is None and min_price is None:
            raise SourceError(f"No price data for {item_name} on Skinport")

        market = MarketData(
            item_name=item_name,
            median_price=median_price if median_price is not None else min_price,
            lowest_price=min_price,
            volume_24h=quantity,
            recent_sales=[],
            source="skinport",
        )

        self.cache.set(
            cache_key,
            market.model_dump_json(),
            ttl=self.settings.cache_ttl_market_price,
            source="skinport",
        )
        return market
