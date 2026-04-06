from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone


class CacheStore:
    """TTL-based cache backed by SQLite."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, key: str, ignore_ttl: bool = False) -> str | None:
        """Get cached value if not expired. Returns None on miss or corruption.

        If *ignore_ttl* is True, return value even when the entry has expired
        (useful for offline mode).
        """
        try:
            if ignore_ttl:
                row = self.conn.execute(
                    "SELECT value FROM cache WHERE key = ?",
                    (key,),
                ).fetchone()
            else:
                now = datetime.now(timezone.utc).isoformat()
                row = self.conn.execute(
                    "SELECT value FROM cache WHERE key = ? AND expires_at > ?",
                    (key, now),
                ).fetchone()
        except sqlite3.DatabaseError:
            # Cache corruption — treat as miss
            return None
        if row is None:
            return None
        return row[0]

    def set(self, key: str, value: str, ttl: int, source: str) -> None:
        """Set cache entry with TTL in seconds."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl)
        try:
            self.conn.execute(
                """INSERT OR REPLACE INTO cache (key, value, created_at, expires_at, source)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, value, now.isoformat(), expires.isoformat(), source),
            )
            self.conn.commit()
        except sqlite3.DatabaseError:
            pass  # Cache write failure is non-critical

    def delete(self, key: str) -> None:
        """Delete a cache entry."""
        try:
            self.conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            self.conn.commit()
        except sqlite3.DatabaseError:
            pass

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count of deleted rows."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            cursor = self.conn.execute(
                "DELETE FROM cache WHERE expires_at <= ?", (now,)
            )
            self.conn.commit()
            return cursor.rowcount
        except sqlite3.DatabaseError:
            return 0
