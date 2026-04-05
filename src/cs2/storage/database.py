from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path.cwd() / "cs2_data.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    source      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at);

CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    weapon      TEXT NOT NULL,
    skin        TEXT NOT NULL,
    quality     TEXT NOT NULL,
    stattrak    INTEGER NOT NULL DEFAULT 0,
    price       REAL NOT NULL,
    volume      INTEGER,
    source      TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_history_item
    ON price_history(weapon, skin, quality, stattrak);
CREATE INDEX IF NOT EXISTS idx_price_history_time
    ON price_history(recorded_at);

CREATE TABLE IF NOT EXISTS decision_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    input_url       TEXT,
    canonical_json  TEXT NOT NULL,
    instance_json   TEXT,
    pricing_json    TEXT NOT NULL,
    liquidity_json  TEXT NOT NULL,
    decision_json   TEXT NOT NULL,
    action          TEXT NOT NULL,
    confidence      REAL NOT NULL,
    listing_price   REAL NOT NULL,
    estimated_value REAL NOT NULL,
    user_override   TEXT,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_decision_log_time ON decision_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_decision_log_action ON decision_log(action);

CREATE TABLE IF NOT EXISTS sticker_prices (
    name        TEXT PRIMARY KEY,
    price       REAL NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def query_price_history(
    conn: sqlite3.Connection,
    weapon: str,
    skin: str,
    quality: str,
    stattrak: bool = False,
    days: int = 30,
    limit: int = 50,
) -> list[dict]:
    """Query price history for a canonical item.

    Returns list of dicts with keys: price, volume, source, recorded_at.
    """
    from datetime import datetime, timedelta

    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    cursor = conn.execute(
        """
        SELECT price, volume, source, recorded_at
        FROM price_history
        WHERE weapon = ? AND skin = ? AND quality = ? AND stattrak = ?
              AND recorded_at >= ?
        ORDER BY recorded_at DESC
        LIMIT ?
        """,
        (weapon, skin, quality, int(stattrak), cutoff, limit),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Create or open SQLite database with schema migrations applied."""
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Apply schema
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
