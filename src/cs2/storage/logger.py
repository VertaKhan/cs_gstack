from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from cs2.models.decision import Decision
from cs2.models.items import CanonicalItem, ExactInstance
from cs2.models.liquidity import LiquidityResult
from cs2.models.pricing import PricingResult


class DecisionLogger:
    """Logs decisions to SQLite for history and future ML training."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def log(
        self,
        decision: Decision,
        canonical: CanonicalItem,
        pricing: PricingResult,
        liquidity: LiquidityResult,
        instance: ExactInstance | None = None,
        input_url: str | None = None,
    ) -> int:
        """Log a decision. Returns the row id."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            """INSERT INTO decision_log
               (timestamp, input_url, canonical_json, instance_json,
                pricing_json, liquidity_json, decision_json,
                action, confidence, listing_price, estimated_value)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now,
                input_url,
                canonical.model_dump_json(),
                instance.model_dump_json() if instance else None,
                pricing.model_dump_json(),
                liquidity.model_dump_json(),
                decision.model_dump_json(),
                decision.action.value,
                decision.confidence,
                decision.listing_price,
                decision.estimated_value,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_recent(self, limit: int = 20) -> list[dict]:
        """Get recent decisions."""
        rows = self.conn.execute(
            """SELECT id, timestamp, action, confidence, listing_price,
                      estimated_value, canonical_json, input_url
               FROM decision_log
               ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
