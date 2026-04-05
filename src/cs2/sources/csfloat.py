from __future__ import annotations

import re
import time

import httpx

from cs2.config import Settings
from cs2.models.pricing import MarketData, RawListing
from cs2.sources.base import (
    AuthError,
    ListingNotFoundError,
    RateLimitError,
    SourceError,
    SourceFormatError,
)
from cs2.storage.cache import CacheStore

CSFLOAT_API_BASE = "https://csfloat.com/api/v1"
LISTING_URL_PATTERN = re.compile(r"csfloat\.com/item/([a-zA-Z0-9\-]+)")

RETRY_DELAYS = [1.0, 3.0]


def parse_listing_id(url_or_id: str) -> str:
    """Extract listing ID from CSFloat URL or return raw ID."""
    match = LISTING_URL_PATTERN.search(url_or_id)
    if match:
        return match.group(1)
    # Assume raw ID if no URL pattern matched
    return url_or_id.strip()


class CSFloatClient:
    def __init__(self, settings: Settings, cache: CacheStore) -> None:
        self.settings = settings
        self.cache = cache
        self.client = httpx.Client(
            base_url=CSFLOAT_API_BASE,
            headers={"Authorization": settings.csfloat_api_key},
            timeout=10.0,
        )

    def close(self) -> None:
        self.client.close()

    def fetch_listing(self, url_or_id: str) -> RawListing:
        """Fetch listing from CSFloat API with retry and cache fallback."""
        listing_id = parse_listing_id(url_or_id)
        cache_key = f"csfloat:listing:{listing_id}"

        # Try API with retries
        last_error: Exception | None = None
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                return self._do_fetch_listing(listing_id, cache_key)
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
                last_error = exc
                if attempt < len(RETRY_DELAYS):
                    time.sleep(RETRY_DELAYS[attempt])
            except RateLimitError as exc:
                last_error = exc
                wait = min(exc.retry_after, 30.0)
                if attempt < len(RETRY_DELAYS):
                    time.sleep(wait)
            except (AuthError, ListingNotFoundError, SourceFormatError):
                raise

        # All retries exhausted — try cache
        cached = self.cache.get(cache_key)
        if cached is not None:
            return RawListing.model_validate_json(cached)

        raise SourceError(
            f"Failed to fetch listing {listing_id} after retries: {last_error}"
        )

    def _do_fetch_listing(self, listing_id: str, cache_key: str) -> RawListing:
        resp = self.client.get(f"/listings/{listing_id}")

        if resp.status_code == 401:
            raise AuthError("Invalid CSFloat API key. Check CSFLOAT_API_KEY in .env")
        if resp.status_code == 404:
            raise ListingNotFoundError(
                f"Listing {listing_id} not found or no longer available"
            )
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "30"))
            raise RateLimitError(retry_after)
        if resp.status_code >= 400:
            raise SourceError(f"CSFloat API error: {resp.status_code}")
        if resp.status_code != 200:
            raise SourceError(f"CSFloat API unexpected status: {resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            raise SourceFormatError("CSFloat returned invalid JSON")

        listing = self._parse_listing(data, listing_id)

        # Cache the result
        self.cache.set(
            cache_key,
            listing.model_dump_json(),
            ttl=self.settings.cache_ttl_listing,
            source="csfloat",
        )
        return listing

    def _parse_listing(self, data: dict, listing_id: str) -> RawListing:
        try:
            item = data.get("item", data)
            stickers_raw = item.get("stickers") or []
            stickers = []
            for s in stickers_raw:
                stickers.append({
                    "name": s.get("name", ""),
                    "slot": s.get("slot", 0),
                    "wear": s.get("wear", 0.0),
                    "price": s.get("price"),
                })

            return RawListing(
                listing_id=str(data.get("id", listing_id)),
                item_name=item.get("market_hash_name", item.get("item_name", "")),
                price=float(data.get("price", 0)) / 100,  # CSFloat prices in cents
                float_value=item.get("float_value"),
                paint_seed=item.get("paint_seed"),
                stickers=stickers,
                inspect_link=item.get("inspect_link"),
                seller_id=str(data.get("seller_id", "")) or None,
                created_at=data.get("created_at"),
                source="csfloat",
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceFormatError(f"Unexpected CSFloat response format: {exc}")

    def fetch_market_data(self, item_name: str) -> MarketData:
        """Fetch market data (recent sales) for item from CSFloat."""
        cache_key = f"csfloat:market:{item_name}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return MarketData.model_validate_json(cached)

        try:
            resp = self.client.get(
                "/history",
                params={"market_hash_name": item_name},
            )
        except (httpx.TimeoutException, httpx.ConnectError):
            raise SourceError(f"Failed to fetch market data for {item_name}")

        if resp.status_code != 200:
            raise SourceError(
                f"CSFloat market data error: {resp.status_code}"
            )

        try:
            data = resp.json()
        except Exception:
            raise SourceFormatError("CSFloat market data: invalid JSON")

        sales = data if isinstance(data, list) else data.get("sales", [])
        prices = [float(s.get("price", 0)) / 100 for s in sales if s.get("price")]

        if not prices:
            raise SourceError(f"No sales data for {item_name}")

        sorted_prices = sorted(prices)
        median_price = sorted_prices[len(sorted_prices) // 2]
        lowest_price = sorted_prices[0] if sorted_prices else None

        recent_sales = [
            {"price": float(s.get("price", 0)) / 100, "timestamp": s.get("sold_at", "")}
            for s in sales[:50]
        ]

        market = MarketData(
            item_name=item_name,
            median_price=median_price,
            lowest_price=lowest_price,
            volume_24h=len(sales) if len(sales) < 100 else None,
            recent_sales=recent_sales,
            source="csfloat",
        )

        self.cache.set(
            cache_key,
            market.model_dump_json(),
            ttl=self.settings.cache_ttl_market_price,
            source="csfloat",
        )
        return market
