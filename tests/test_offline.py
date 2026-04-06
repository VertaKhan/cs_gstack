from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from cs2.models.decision import DecisionAction
from cs2.models.pricing import MarketData, RawListing
from cs2.pipeline import Pipeline, PipelineError, PipelineResult
from cs2.sources.csfloat import CSFLOAT_API_BASE
from cs2.storage.cache import CacheStore


# --- Helpers -------------------------------------------------------------


@pytest.fixture()
def settings_offline():
    """Settings with extra sources disabled (avoids unmocked API calls)."""
    from cs2.config import Settings

    return Settings(
        csfloat_api_key="test-key",
        steam_api_key="test-key",
        skinport_enabled=False,
        dmarket_enabled=False,
    )


LISTING_JSON = {
    "id": "offline-1",
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


# --- CLI flag parsing ----------------------------------------------------


class TestOfflineFlagParse:
    @patch("cs2.cli._run_analyze")
    def test_offline_flag_analyze(self, mock_run):
        from cs2.cli import main

        main(["analyze", "https://csfloat.com/item/test-1", "--offline"])
        args = mock_run.call_args[0][0]
        assert args.offline is True

    @patch("cs2.cli._run_analyze")
    def test_no_offline_flag_default(self, mock_run):
        from cs2.cli import main

        main(["analyze", "https://csfloat.com/item/test-1"])
        args = mock_run.call_args[0][0]
        assert args.offline is False

    @patch("cs2.cli._run_compare")
    def test_offline_flag_compare(self, mock_run):
        from cs2.cli import main

        main(["compare", "url1", "url2", "--offline"])
        args = mock_run.call_args[0][0]
        assert args.offline is True


# --- Offline pipeline: cache hit -----------------------------------------


class TestOfflineCacheHit:
    @respx.mock
    def test_offline_uses_cached_data(self, settings_offline, cache, logger):
        """Pre-populate cache online, then analyze offline with no API calls."""
        # 1) Online pass to populate cache
        respx.get(f"{CSFLOAT_API_BASE}/listings/offline-1").mock(
            return_value=httpx.Response(200, json=LISTING_JSON)
        )
        respx.get(f"{CSFLOAT_API_BASE}/history").mock(
            return_value=httpx.Response(200, json=MARKET_SALES_JSON)
        )

        online_pipeline = Pipeline(settings_offline, cache, logger, offline=False)
        online_result = online_pipeline.analyze_url("offline-1")
        assert online_result.decision is not None
        online_pipeline.close()

        # 2) Offline pass — should work from cache, no new API calls
        respx.reset()
        # Mock routes that should NOT be called
        listing_route = respx.get(f"{CSFLOAT_API_BASE}/listings/offline-1").mock(
            return_value=httpx.Response(500)
        )
        market_route = respx.get(f"{CSFLOAT_API_BASE}/history").mock(
            return_value=httpx.Response(500)
        )

        offline_pipeline = Pipeline(settings_offline, cache, logger, offline=True)
        result = offline_pipeline.analyze_url("offline-1")

        assert result.decision is not None
        assert result.canonical.weapon == "AK-47"
        assert listing_route.call_count == 0
        assert market_route.call_count == 0
        offline_pipeline.close()


# --- Offline pipeline: cache miss ----------------------------------------


class TestOfflineCacheMiss:
    def test_offline_listing_cache_miss(self, settings_offline, cache, logger):
        """Offline mode with no cached listing raises clear error."""
        pipeline = Pipeline(settings_offline, cache, logger, offline=True)
        with pytest.raises(PipelineError, match="No cached data for listing"):
            pipeline.analyze_url("nonexistent-id")
        pipeline.close()

    @respx.mock
    def test_offline_market_data_cache_miss(self, settings_offline, cache, logger):
        """Offline: listing cached but market data missing -> PipelineError."""
        # Populate only listing in cache (online)
        respx.get(f"{CSFLOAT_API_BASE}/listings/miss-market").mock(
            return_value=httpx.Response(200, json=LISTING_JSON)
        )
        respx.get(f"{CSFLOAT_API_BASE}/history").mock(
            return_value=httpx.Response(500)  # market data fails
        )
        from cs2.sources.steam import STEAM_MARKET_BASE

        respx.get(f"{STEAM_MARKET_BASE}/priceoverview/").mock(
            return_value=httpx.Response(500)
        )

        online_pipeline = Pipeline(settings_offline, cache, logger, offline=False)
        # This will succeed in degraded mode (no market data)
        online_pipeline.analyze_url("miss-market")
        online_pipeline.close()

        # Now offline — listing is cached but market data is NOT
        offline_pipeline = Pipeline(settings_offline, cache, logger, offline=True)
        with pytest.raises(PipelineError, match="No cached market data"):
            offline_pipeline.analyze_url("miss-market")
        offline_pipeline.close()


# --- Offline pipeline: stale cache ---------------------------------------


class TestOfflineStaleCache:
    def test_offline_uses_stale_cache(self, settings_offline, db_conn, logger):
        """Offline mode returns expired cache entries."""
        cache = CacheStore(db_conn)
        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=24)  # expired 24h ago

        # Insert expired listing
        listing = RawListing(
            listing_id="stale-1",
            item_name="AK-47 | Redline (Field-Tested)",
            price=10.0,
            float_value=0.25,
            paint_seed=42,
            stickers=[],
            inspect_link="steam://...",
            seller_id="s1",
            created_at="2026-04-01",
            source="csfloat",
        )
        db_conn.execute(
            "INSERT INTO cache (key, value, created_at, expires_at, source) VALUES (?,?,?,?,?)",
            (
                "csfloat:listing:stale-1",
                listing.model_dump_json(),
                now.isoformat(),
                past.isoformat(),
                "csfloat",
            ),
        )

        # Insert expired market data
        market = MarketData(
            item_name="AK-47 | Redline (Field-Tested)",
            median_price=10.0,
            lowest_price=8.0,
            volume_24h=50,
            recent_sales=[{"price": 10.0, "timestamp": "2026-04-01"}],
            source="csfloat",
        )
        db_conn.execute(
            "INSERT INTO cache (key, value, created_at, expires_at, source) VALUES (?,?,?,?,?)",
            (
                "csfloat:market:AK-47 | Redline (Field-Tested)",
                market.model_dump_json(),
                now.isoformat(),
                past.isoformat(),
                "csfloat",
            ),
        )
        db_conn.commit()

        # Verify normal cache.get returns None (expired)
        assert cache.get("csfloat:listing:stale-1") is None

        # Offline pipeline should still work with stale data
        pipeline = Pipeline(settings_offline, cache, logger, offline=True)
        result = pipeline.analyze_url("stale-1")
        assert result.decision is not None
        assert result.canonical.weapon == "AK-47"
        pipeline.close()


# --- CacheStore.get(ignore_ttl=True) unit test ---------------------------


class TestCacheIgnoreTTL:
    def test_ignore_ttl_returns_expired(self, db_conn):
        """get(key, ignore_ttl=True) returns value even when expired."""
        cache = CacheStore(db_conn)
        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=1)

        db_conn.execute(
            "INSERT INTO cache (key, value, created_at, expires_at, source) VALUES (?,?,?,?,?)",
            ("expired-key", "expired-value", now.isoformat(), past.isoformat(), "test"),
        )
        db_conn.commit()

        # Normal get -> None
        assert cache.get("expired-key") is None
        # ignore_ttl -> value returned
        assert cache.get("expired-key", ignore_ttl=True) == "expired-value"

    def test_ignore_ttl_returns_fresh(self, db_conn):
        """get(key, ignore_ttl=True) also works for non-expired entries."""
        cache = CacheStore(db_conn)
        cache.set("fresh-key", "fresh-value", ttl=3600, source="test")

        assert cache.get("fresh-key", ignore_ttl=True) == "fresh-value"

    def test_ignore_ttl_miss(self, db_conn):
        """get(key, ignore_ttl=True) returns None when key doesn't exist."""
        cache = CacheStore(db_conn)
        assert cache.get("no-such-key", ignore_ttl=True) is None
