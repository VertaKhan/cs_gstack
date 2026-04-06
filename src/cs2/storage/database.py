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

CREATE TABLE IF NOT EXISTS portfolio (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    weapon          TEXT NOT NULL,
    skin            TEXT NOT NULL,
    quality         TEXT NOT NULL,
    stattrak        INTEGER NOT NULL DEFAULT 0,
    float_value     REAL,
    purchase_price  REAL NOT NULL,
    purchase_date   TEXT NOT NULL,
    source          TEXT,
    notes           TEXT,
    sold_price      REAL,
    sold_date       TEXT
);
CREATE INDEX IF NOT EXISTS idx_portfolio_item ON portfolio(weapon, skin, quality);
"""


def add_portfolio_item(
    conn: sqlite3.Connection,
    weapon: str,
    skin: str,
    quality: str,
    stattrak: bool,
    float_value: float | None,
    purchase_price: float,
    source: str | None = None,
    notes: str | None = None,
) -> int:
    """Insert a portfolio item. Returns the new row id."""
    from datetime import datetime, timezone

    cursor = conn.execute(
        """
        INSERT INTO portfolio (weapon, skin, quality, stattrak, float_value,
                               purchase_price, purchase_date, source, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            weapon, skin, quality, int(stattrak), float_value,
            purchase_price, datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            source, notes,
        ),
    )
    conn.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def list_portfolio_items(
    conn: sqlite3.Connection,
    active_only: bool = True,
) -> list[dict]:
    """List portfolio items. If active_only, exclude sold items."""
    if active_only:
        sql = "SELECT * FROM portfolio WHERE sold_price IS NULL ORDER BY purchase_date DESC"
    else:
        sql = "SELECT * FROM portfolio ORDER BY purchase_date DESC"
    cursor = conn.execute(sql)
    return [dict(row) for row in cursor.fetchall()]


def sell_portfolio_item(
    conn: sqlite3.Connection,
    item_id: int,
    sold_price: float,
) -> dict | None:
    """Mark a portfolio item as sold. Returns updated row or None if not found."""
    from datetime import datetime, timezone

    sold_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        "UPDATE portfolio SET sold_price = ?, sold_date = ? WHERE id = ? AND sold_price IS NULL",
        (sold_price, sold_date, item_id),
    )
    conn.commit()
    cursor = conn.execute("SELECT * FROM portfolio WHERE id = ?", (item_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def portfolio_summary(conn: sqlite3.Connection) -> dict:
    """Calculate portfolio summary: total_invested, total_sold, total_pnl, item_count, sold_count."""
    cursor = conn.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE sold_price IS NULL) AS active_count,
            COUNT(*) FILTER (WHERE sold_price IS NOT NULL) AS sold_count,
            COALESCE(SUM(CASE WHEN sold_price IS NULL THEN purchase_price END), 0) AS active_invested,
            COALESCE(SUM(CASE WHEN sold_price IS NOT NULL THEN purchase_price END), 0) AS sold_invested,
            COALESCE(SUM(sold_price), 0) AS total_sold_revenue
        FROM portfolio
        """
    )
    row = dict(cursor.fetchone())
    return {
        "active_count": row["active_count"],
        "sold_count": row["sold_count"],
        "active_invested": row["active_invested"],
        "sold_invested": row["sold_invested"],
        "total_sold_revenue": row["total_sold_revenue"],
        "realized_pnl": row["total_sold_revenue"] - row["sold_invested"],
    }


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
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
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
