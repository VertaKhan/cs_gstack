from __future__ import annotations

import re

import httpx

from cs2.config import Settings
from cs2.models.pricing import MarketData
from cs2.sources.base import SourceError
from cs2.storage.cache import CacheStore

STEAM_MARKET_BASE = "https://steamcommunity.com/market"
STEAM_LISTING_PATTERN = re.compile(
    r"steamcommunity\.com/market/listings/730/(.+)"
)


def parse_steam_item_name(url_or_name: str) -> str:
    """Extract item name from Steam Market URL or return as-is."""
    match = STEAM_LISTING_PATTERN.search(url_or_name)
    if match:
        from urllib.parse import unquote
        return unquote(match.group(1))
    return url_or_name.strip()


def _parse_price(price_str: str) -> float:
    """Parse Steam price string like '$45.00' or '45,00€' to float."""
    cleaned = re.sub(r"[^\d.,]", "", price_str)
    # Handle European format: 1.234,56 → 1234.56
    if "," in cleaned and "." in cleaned:
        if cleaned.index(",") > cleaned.index("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # Could be decimal separator or thousands
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) == 2:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


class SteamClient:
    def __init__(self, settings: Settings, cache: CacheStore) -> None:
        self.settings = settings
        self.cache = cache
        self.client = httpx.Client(
            timeout=10.0,
            headers={"Accept-Language": "en-US"},
        )

    def close(self) -> None:
        self.client.close()

    def fetch_market_data(self, item_name: str) -> MarketData:
        """Fetch market price data from Steam Community Market.

        This is a best-effort source — Steam Market API is unofficial
        and rate-limited. Failures are expected and handled gracefully.
        """
        cache_key = f"steam:market:{item_name}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return MarketData.model_validate_json(cached)

        try:
            resp = self.client.get(
                f"{STEAM_MARKET_BASE}/priceoverview/",
                params={
                    "appid": "730",
                    "currency": "1",  # USD
                    "market_hash_name": item_name,
                },
            )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise SourceError(f"Steam Market unavailable: {exc}")

        if resp.status_code == 429:
            raise SourceError("Steam Market rate limited")
        if resp.status_code != 200:
            raise SourceError(f"Steam Market error: {resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            raise SourceError("Steam Market returned invalid JSON")

        if not data.get("success"):
            raise SourceError(f"Item not found on Steam Market: {item_name}")

        median_price = _parse_price(data.get("median_price", "$0.00"))
        lowest_price_str = data.get("lowest_price")
        lowest_price = _parse_price(lowest_price_str) if lowest_price_str else None
        volume_str = data.get("volume", "0")
        volume_24h = int(volume_str.replace(",", "")) if volume_str else None

        market = MarketData(
            item_name=item_name,
            median_price=median_price,
            lowest_price=lowest_price,
            volume_24h=volume_24h,
            recent_sales=[],
            source="steam",
        )

        self.cache.set(
            cache_key,
            market.model_dump_json(),
            ttl=self.settings.cache_ttl_market_price,
            source="steam",
        )
        return market
