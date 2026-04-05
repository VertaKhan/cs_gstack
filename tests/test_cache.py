from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from cs2.storage.cache import CacheStore
from cs2.storage.database import SCHEMA_SQL


class TestCacheSetGet:
    def test_set_and_get(self, cache):
        cache.set("key1", "value1", ttl=3600, source="test")
        assert cache.get("key1") == "value1"

    def test_get_miss(self, cache):
        assert cache.get("nonexistent") is None

    def test_overwrite(self, cache):
        cache.set("key1", "v1", ttl=3600, source="test")
        cache.set("key1", "v2", ttl=3600, source="test")
        assert cache.get("key1") == "v2"

    def test_delete(self, cache):
        cache.set("key1", "v1", ttl=3600, source="test")
        cache.delete("key1")
        assert cache.get("key1") is None


class TestCacheTTL:
    def test_expired_entry(self, db_conn):
        """Entry with past expires_at returns None."""
        cache = CacheStore(db_conn)
        now = datetime.now(timezone.utc)
        past = now - timedelta(seconds=10)

        db_conn.execute(
            "INSERT INTO cache (key, value, created_at, expires_at, source) VALUES (?,?,?,?,?)",
            ("expired", "val", now.isoformat(), past.isoformat(), "test"),
        )
        db_conn.commit()

        assert cache.get("expired") is None

    def test_not_expired_entry(self, db_conn):
        """Entry with future expires_at returns value."""
        cache = CacheStore(db_conn)
        now = datetime.now(timezone.utc)
        future = now + timedelta(hours=1)

        db_conn.execute(
            "INSERT INTO cache (key, value, created_at, expires_at, source) VALUES (?,?,?,?,?)",
            ("fresh", "val", now.isoformat(), future.isoformat(), "test"),
        )
        db_conn.commit()

        assert cache.get("fresh") == "val"


class TestCacheCleanup:
    def test_cleanup_expired(self, db_conn):
        cache = CacheStore(db_conn)
        now = datetime.now(timezone.utc)

        # Insert expired
        db_conn.execute(
            "INSERT INTO cache (key, value, created_at, expires_at, source) VALUES (?,?,?,?,?)",
            ("old", "v", now.isoformat(), (now - timedelta(hours=1)).isoformat(), "test"),
        )
        # Insert fresh
        db_conn.execute(
            "INSERT INTO cache (key, value, created_at, expires_at, source) VALUES (?,?,?,?,?)",
            ("new", "v", now.isoformat(), (now + timedelta(hours=1)).isoformat(), "test"),
        )
        db_conn.commit()

        deleted = cache.cleanup_expired()
        assert deleted == 1
        assert cache.get("new") == "v"
        assert cache.get("old") is None


class TestCacheCorruption:
    def test_cache_corruption_get(self, tmp_path):
        """sqlite3.DatabaseError on get -> returns None (cache miss)."""
        db_path = tmp_path / "corrupt.db"
        conn = sqlite3.Connection(str(db_path))
        conn.executescript(SCHEMA_SQL)
        conn.commit()

        cache = CacheStore(conn)
        cache.set("k", "v", ttl=3600, source="test")
        conn.close()

        # Corrupt the DB file
        with open(db_path, "wb") as f:
            f.write(b"this is not a valid sqlite database")

        corrupt_conn = sqlite3.Connection(str(db_path))
        corrupt_cache = CacheStore(corrupt_conn)

        # Should return None (cache miss) instead of raising
        result = corrupt_cache.get("k")
        assert result is None
        corrupt_conn.close()

    def test_cache_corruption_set(self, tmp_path):
        """sqlite3.DatabaseError on set -> silently fails."""
        db_path = tmp_path / "corrupt2.db"

        # Corrupt it from the start
        with open(db_path, "wb") as f:
            f.write(b"corrupted")

        conn = sqlite3.Connection(str(db_path))
        cache = CacheStore(conn)

        # Should not raise
        cache.set("k", "v", ttl=3600, source="test")
        conn.close()

    def test_cache_corruption_cleanup(self, tmp_path):
        """sqlite3.DatabaseError on cleanup -> returns 0."""
        db_path = tmp_path / "corrupt3.db"

        with open(db_path, "wb") as f:
            f.write(b"corrupted")

        conn = sqlite3.Connection(str(db_path))
        cache = CacheStore(conn)

        assert cache.cleanup_expired() == 0
        conn.close()
