from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from cs2.cli import main
from cs2.storage.database import (
    add_portfolio_item,
    list_portfolio_items,
    sell_portfolio_item,
    portfolio_summary,
)


class TestPortfolioDB:
    def test_add_portfolio_item(self, db_conn):
        item_id = add_portfolio_item(
            db_conn,
            weapon="AK-47", skin="Redline", quality="Field-Tested",
            stattrak=False, float_value=0.25,
            purchase_price=45.0, source="csfloat", notes="Good deal",
        )
        assert item_id is not None
        assert item_id > 0

    def test_list_portfolio_active_only(self, db_conn):
        add_portfolio_item(
            db_conn, weapon="AK-47", skin="Redline", quality="Field-Tested",
            stattrak=False, float_value=None, purchase_price=45.0,
        )
        add_portfolio_item(
            db_conn, weapon="M4A1-S", skin="Hyper Beast", quality="Factory New",
            stattrak=False, float_value=0.01, purchase_price=30.0,
        )
        # Sell one
        sell_portfolio_item(db_conn, 1, 55.0)

        active = list_portfolio_items(db_conn, active_only=True)
        assert len(active) == 1
        assert active[0]["weapon"] == "M4A1-S"

        all_items = list_portfolio_items(db_conn, active_only=False)
        assert len(all_items) == 2

    def test_sell_portfolio_item(self, db_conn):
        item_id = add_portfolio_item(
            db_conn, weapon="AK-47", skin="Redline", quality="Field-Tested",
            stattrak=False, float_value=0.25, purchase_price=45.0,
        )
        result = sell_portfolio_item(db_conn, item_id, 55.0)
        assert result is not None
        assert result["sold_price"] == 55.0
        assert result["sold_date"] is not None

    def test_sell_nonexistent_item(self, db_conn):
        result = sell_portfolio_item(db_conn, 999, 55.0)
        assert result is None

    def test_portfolio_summary(self, db_conn):
        add_portfolio_item(
            db_conn, weapon="AK-47", skin="Redline", quality="Field-Tested",
            stattrak=False, float_value=None, purchase_price=45.0,
        )
        add_portfolio_item(
            db_conn, weapon="M4A1-S", skin="Hyper Beast", quality="Factory New",
            stattrak=False, float_value=None, purchase_price=30.0,
        )
        sell_portfolio_item(db_conn, 2, 40.0)

        summary = portfolio_summary(db_conn)
        assert summary["active_count"] == 1
        assert summary["sold_count"] == 1
        assert summary["active_invested"] == 45.0
        assert summary["sold_invested"] == 30.0
        assert summary["total_sold_revenue"] == 40.0
        assert summary["realized_pnl"] == 10.0

    def test_portfolio_summary_empty(self, db_conn):
        summary = portfolio_summary(db_conn)
        assert summary["active_count"] == 0
        assert summary["sold_count"] == 0

    def test_add_portfolio_item_no_price_raises(self, db_conn):
        """purchase_price is required — passing None should fail."""
        with pytest.raises(Exception):
            add_portfolio_item(
                db_conn, weapon="AK-47", skin="Redline", quality="Field-Tested",
                stattrak=False, float_value=None, purchase_price=None,  # type: ignore[arg-type]
            )


class TestPortfolioCLI:
    @patch("cs2.cli._run_portfolio")
    def test_portfolio_add_parse(self, mock_run):
        main(["portfolio", "add", "AK-47 Redline FT", "--price", "45.00", "--float", "0.25", "--source", "csfloat"])
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args.command == "portfolio"
        assert args.portfolio_action == "add"
        assert args.item_name == "AK-47 Redline FT"
        assert args.price == 45.0
        assert args.float_value == 0.25
        assert args.source == "csfloat"

    @patch("cs2.cli._run_portfolio")
    def test_portfolio_list_parse(self, mock_run):
        main(["portfolio", "list", "--all"])
        args = mock_run.call_args[0][0]
        assert args.portfolio_action == "list"
        assert args.show_all is True

    @patch("cs2.cli._run_portfolio")
    def test_portfolio_sell_parse(self, mock_run):
        main(["portfolio", "sell", "42", "--price", "55.00"])
        args = mock_run.call_args[0][0]
        assert args.portfolio_action == "sell"
        assert args.item_id == 42
        assert args.price == 55.0

    @patch("cs2.cli._run_portfolio")
    def test_portfolio_value_parse(self, mock_run):
        main(["portfolio", "value"])
        args = mock_run.call_args[0][0]
        assert args.portfolio_action == "value"

    def test_portfolio_add_no_price(self):
        """--price is required; omitting it should cause argparse to error."""
        with pytest.raises(SystemExit) as exc_info:
            main(["portfolio", "add", "AK-47 Redline FT"])
        assert exc_info.value.code == 2
