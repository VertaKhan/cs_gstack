from __future__ import annotations

import os
import sqlite3

import pytest

from cs2.config import Settings
from cs2.storage.cache import CacheStore
from cs2.storage.database import SCHEMA_SQL
from cs2.storage.logger import DecisionLogger


@pytest.fixture()
def settings() -> Settings:
    """Default Settings with fake API keys for testing."""
    return Settings(
        csfloat_api_key="test-csfloat-key-123",
        steam_api_key="test-steam-key-456",
    )


@pytest.fixture()
def db_conn(tmp_path):
    """Fresh SQLite database with schema applied."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.Connection(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture()
def cache(db_conn) -> CacheStore:
    """CacheStore backed by tmp database."""
    return CacheStore(db_conn)


@pytest.fixture()
def logger(db_conn) -> DecisionLogger:
    """DecisionLogger backed by tmp database."""
    return DecisionLogger(db_conn)


@pytest.fixture()
def canonical_ak():
    """AK-47 | Redline (Field-Tested) canonical item."""
    from cs2.models.items import CanonicalItem

    return CanonicalItem(
        weapon="AK-47",
        skin="Redline",
        quality="Field-Tested",
        stattrak=False,
        souvenir=False,
    )


@pytest.fixture()
def canonical_ak_st():
    """StatTrak AK-47 | Redline (Field-Tested) canonical item."""
    from cs2.models.items import CanonicalItem

    return CanonicalItem(
        weapon="AK-47",
        skin="Redline",
        quality="Field-Tested",
        stattrak=True,
        souvenir=False,
    )


@pytest.fixture()
def raw_listing():
    """Sample RawListing from CSFloat."""
    from cs2.models.pricing import RawListing

    return RawListing(
        listing_id="abc-123",
        item_name="AK-47 | Redline (Field-Tested)",
        price=12.50,
        float_value=0.25,
        paint_seed=42,
        stickers=[
            {"name": "Katowice 2014 (Holo) | iBUYPOWER", "slot": 0, "wear": 0.0, "price": 5000.0},
            {"name": "Navi | Cologne 2015", "slot": 1, "wear": 0.1, "price": 1.0},
        ],
        inspect_link="steam://rungame/730/...",
        seller_id="seller-1",
        created_at="2026-04-01T00:00:00Z",
        source="csfloat",
    )


@pytest.fixture()
def market_data():
    """Sample MarketData with sufficient sales."""
    from cs2.models.pricing import MarketData

    return MarketData(
        item_name="AK-47 | Redline (Field-Tested)",
        median_price=10.0,
        lowest_price=8.0,
        volume_24h=50,
        recent_sales=[{"price": p, "timestamp": "2026-04-01"} for p in
                      [9.0, 9.5, 10.0, 10.5, 11.0, 10.0, 9.8, 10.2, 9.9, 10.1]],
        source="csfloat",
    )
