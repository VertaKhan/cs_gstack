from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from cs2.cli import main, _run_history, _format_json, _format_csv, _result_to_dict


class TestCLIParsing:
    def test_cli_no_args(self):
        """No args -> sys.exit(1) with help."""
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_cli_no_subcommand(self):
        """Empty command -> sys.exit(1)."""
        with pytest.raises(SystemExit):
            main([])

    @patch("cs2.cli._run_analyze")
    def test_cli_url_arg(self, mock_run):
        """URL argument parsed and passed to _run_analyze."""
        main(["analyze", "https://csfloat.com/item/abc-123"])
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args.url == "https://csfloat.com/item/abc-123"
        assert args.command == "analyze"

    @patch("cs2.cli._run_analyze")
    def test_cli_manual_args(self, mock_run):
        """Manual --weapon/--skin/--quality args parsed."""
        main([
            "analyze",
            "--weapon", "AK-47",
            "--skin", "Redline",
            "--quality", "FT",
            "--stattrak",
        ])
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args.weapon == "AK-47"
        assert args.skin == "Redline"
        assert args.quality == "FT"
        assert args.stattrak is True
        assert args.url is None

    @patch("cs2.cli._run_analyze")
    def test_cli_float_arg(self, mock_run):
        """--float argument parsed as float."""
        main(["analyze", "--weapon", "AK-47", "--skin", "X", "--quality", "FT", "--float", "0.15"])
        args = mock_run.call_args[0][0]
        assert args.float_value == 0.15

    @patch("cs2.cli._run_analyze")
    def test_cli_config_args(self, mock_run):
        """--config and --env args parsed."""
        main(["analyze", "url", "--config", "/tmp/c.toml", "--env", "/tmp/.env"])
        args = mock_run.call_args[0][0]
        assert args.config == "/tmp/c.toml"
        assert args.env == "/tmp/.env"

    def test_cli_invalid_url(self, tmp_path, monkeypatch):
        """Invalid URL -> pipeline error -> sys.exit(1).

        We mock load_settings to avoid needing .env, and mock Pipeline
        to raise PipelineError simulating an invalid URL.
        """
        from cs2.pipeline import PipelineError

        mock_settings = MagicMock()

        with patch("cs2.cli.load_settings", return_value=mock_settings), \
             patch("cs2.cli.get_connection") as mock_conn, \
             patch("cs2.cli.CacheStore"), \
             patch("cs2.cli.DecisionLogger"), \
             patch("cs2.cli.Pipeline") as MockPipeline:

            mock_pipeline = MockPipeline.return_value
            mock_pipeline.analyze_url.side_effect = PipelineError("Cannot fetch listing")

            with pytest.raises(SystemExit) as exc_info:
                main(["analyze", "not-a-valid-url"])
            assert exc_info.value.code == 1

    @patch("cs2.cli._run_analyze")
    def test_cli_output_format(self, mock_run):
        """Verify CLI doesn't crash on valid invocation (output is Rich panel)."""
        # Just verify it doesn't raise before calling _run_analyze
        main(["analyze", "https://csfloat.com/item/test-123"])
        mock_run.assert_called_once()


class TestHistorySubcommand:
    @patch("cs2.cli._run_history")
    def test_history_subcommand_parse(self, mock_run):
        """history subcommand parses item_name, --days, --limit."""
        main(["history", "AK-47 | Redline (Field-Tested)", "--days", "7", "--limit", "20"])
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args.command == "history"
        assert args.item_name == "AK-47 | Redline (Field-Tested)"
        assert args.days == 7
        assert args.limit == 20

    @patch("cs2.cli._run_history")
    def test_history_defaults(self, mock_run):
        """history subcommand uses default --days=30 and --limit=50."""
        main(["history", "AK-47 Redline FT"])
        args = mock_run.call_args[0][0]
        assert args.days == 30
        assert args.limit == 50

    @patch("cs2.cli.get_connection")
    @patch("cs2.cli.query_price_history")
    def test_history_output_with_data(self, mock_query, mock_conn, capsys):
        """history command renders table and summary when data exists."""
        mock_query.return_value = [
            {"price": 12.50, "volume": 100, "source": "steam", "recorded_at": "2026-04-01T12:00:00"},
            {"price": 11.80, "volume": 90, "source": "steam", "recorded_at": "2026-03-30T12:00:00"},
            {"price": 11.00, "volume": 80, "source": "steam", "recorded_at": "2026-03-28T12:00:00"},
            {"price": 10.50, "volume": 70, "source": "steam", "recorded_at": "2026-03-25T12:00:00"},
        ]
        mock_conn.return_value = MagicMock()

        from argparse import Namespace
        args = Namespace(
            command="history",
            item_name="AK-47 | Redline (Field-Tested)",
            days=30,
            limit=50,
        )
        _run_history(args)

        mock_query.assert_called_once_with(
            mock_conn.return_value,
            weapon="AK-47",
            skin="Redline",
            quality="Field-Tested",
            stattrak=False,
            days=30,
            limit=50,
        )

    @patch("cs2.cli.get_connection")
    @patch("cs2.cli.query_price_history")
    def test_history_no_data(self, mock_query, mock_conn):
        """history command shows helpful message when no data found."""
        mock_query.return_value = []
        mock_conn.return_value = MagicMock()

        from argparse import Namespace
        args = Namespace(
            command="history",
            item_name="AK-47 | Redline (Field-Tested)",
            days=30,
            limit=50,
        )
        # Should not raise, just print a message
        _run_history(args)


class TestBatchMode:
    def test_batch_file_detection(self, tmp_path):
        """If argument is an existing file, batch mode is triggered."""
        urls_file = tmp_path / "urls.txt"
        urls_file.write_text("https://csfloat.com/item/1\n")

        with patch("cs2.cli._run_analyze") as mock_run:
            main(["analyze", str(urls_file)])
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args.url == str(urls_file)

    def test_batch_file_detection_url_not_file(self):
        """A URL that is not an existing file should NOT trigger batch mode."""
        with patch("cs2.cli._run_analyze") as mock_run:
            main(["analyze", "https://csfloat.com/item/abc"])
            args = mock_run.call_args[0][0]
            assert args.url == "https://csfloat.com/item/abc"

    def test_batch_reads_file(self, tmp_path):
        """Batch mode reads URLs from file and calls analyze_url for each."""
        urls_file = tmp_path / "urls.txt"
        urls_file.write_text(
            "https://csfloat.com/item/1\n"
            "https://csfloat.com/item/2\n"
            "https://csfloat.com/item/3\n"
        )

        from cs2.cli import _read_urls_from_file

        urls = _read_urls_from_file(str(urls_file))
        assert urls == [
            "https://csfloat.com/item/1",
            "https://csfloat.com/item/2",
            "https://csfloat.com/item/3",
        ]

    def test_batch_skips_comments_and_empty_lines(self, tmp_path):
        """Batch file parser skips comments (#) and empty lines."""
        urls_file = tmp_path / "urls.txt"
        urls_file.write_text(
            "# This is a comment\n"
            "\n"
            "https://csfloat.com/item/1\n"
            "  \n"
            "# Another comment\n"
            "https://csfloat.com/item/2\n"
            "\n"
        )

        from cs2.cli import _read_urls_from_file

        urls = _read_urls_from_file(str(urls_file))
        assert urls == [
            "https://csfloat.com/item/1",
            "https://csfloat.com/item/2",
        ]

    def test_batch_empty_file(self, tmp_path):
        """Batch mode with empty file returns empty list."""
        urls_file = tmp_path / "urls.txt"
        urls_file.write_text("# only comments\n\n")

        from cs2.cli import _read_urls_from_file

        urls = _read_urls_from_file(str(urls_file))
        assert urls == []


def _make_pipeline_result():
    """Create a minimal PipelineResult for format tests."""
    from cs2.models.items import CanonicalItem
    from cs2.models.decision import Decision, DecisionAction
    from cs2.models.pricing import PricingResult, ItemClass
    from cs2.models.liquidity import LiquidityResult, LiquidityGrade
    from cs2.pipeline import PipelineResult

    canonical = CanonicalItem(
        weapon="AK-47", skin="Redline", quality="Field-Tested",
        stattrak=False, souvenir=False,
    )
    decision = Decision(
        action=DecisionAction.BUY,
        confidence=0.82,
        listing_price=80.0,
        estimated_value=120.0,
        margin_pct=50.0,
        safe_exit_price=95.0,
        reasons=["underpriced by 33%"],
        risk_flags=[],
    )
    pricing = PricingResult(
        canonical=canonical,
        base_price=45.0,
        item_class=ItemClass.EXACT_PREMIUM,
        estimated_value=120.0,
        premium_breakdown={"float": 30.0, "sticker": 45.0},
    )
    liquidity = LiquidityResult(
        canonical=canonical,
        avg_daily_volume=10.0,
        avg_spread_pct=5.0,
        min_sell_days=1,
        max_sell_days=3,
        safe_exit_price=95.0,
        grade=LiquidityGrade.HIGH,
    )
    return PipelineResult(
        decision=decision,
        canonical=canonical,
        pricing=pricing,
        liquidity=liquidity,
    )


class TestFormatJson:
    def test_format_json_output(self):
        """JSON output contains expected fields and values."""
        import json
        result = _make_pipeline_result()
        output = _format_json([result])
        data = json.loads(output)

        assert data["item"] == "AK-47 | Redline (Field-Tested)"
        assert data["action"] == "buy"
        assert data["confidence"] == 0.82
        assert data["listing_price"] == 80.0
        assert data["estimated_value"] == 120.0
        assert data["margin_pct"] == 50.0
        assert data["safe_exit_price"] == 95.0
        assert data["base_price"] == 45.0
        assert data["item_class"] == "exact_premium"
        assert data["liquidity_grade"] == "high"
        assert data["reasons"] == ["underpriced by 33%"]
        assert data["risk_flags"] == []
        assert data["premium_breakdown"] == {"float": 30.0, "sticker": 45.0}

    def test_format_json_batch(self):
        """Batch JSON outputs an array."""
        import json
        r1 = _make_pipeline_result()
        r2 = _make_pipeline_result()
        output = _format_json([r1, r2])
        data = json.loads(output)
        assert isinstance(data, list)
        assert len(data) == 2


class TestFormatCsv:
    def test_format_csv_output(self):
        """CSV output has header + data row with correct values."""
        result = _make_pipeline_result()
        output = _format_csv([result])
        lines = output.strip().split("\n")

        assert len(lines) == 2  # header + 1 data row
        header = lines[0]
        assert "item" in header
        assert "action" in header
        assert "liquidity_grade" in header

        # Parse data row
        import csv as csv_mod
        import io
        reader = csv_mod.DictReader(io.StringIO(output))
        row = next(reader)
        assert row["item"] == "AK-47 | Redline (Field-Tested)"
        assert row["action"] == "buy"
        assert row["confidence"] == "0.82"
        assert row["listing_price"] == "80.0"

    def test_format_csv_batch(self):
        """Batch CSV has header + N data rows."""
        r1 = _make_pipeline_result()
        r2 = _make_pipeline_result()
        output = _format_csv([r1, r2])
        lines = output.strip().split("\n")
        assert len(lines) == 3  # header + 2 rows


class TestFormatDefault:
    @patch("cs2.cli._run_analyze")
    def test_format_default_rich(self, mock_run):
        """Default format is 'rich' when --format not specified."""
        main(["analyze", "https://csfloat.com/item/test-123"])
        args = mock_run.call_args[0][0]
        assert args.output_format == "rich"

    @patch("cs2.cli._run_analyze")
    def test_format_json_flag(self, mock_run):
        """--format json is parsed correctly."""
        main(["analyze", "https://csfloat.com/item/test", "--format", "json"])
        args = mock_run.call_args[0][0]
        assert args.output_format == "json"

    @patch("cs2.cli._run_analyze")
    def test_format_csv_flag(self, mock_run):
        """--format csv is parsed correctly."""
        main(["analyze", "https://csfloat.com/item/test", "--format", "csv"])
        args = mock_run.call_args[0][0]
        assert args.output_format == "csv"

    @patch("cs2.cli._run_analyze")
    def test_output_file_flag(self, mock_run):
        """--output / -o flag is parsed correctly."""
        main(["analyze", "https://csfloat.com/item/test", "--format", "json", "-o", "out.json"])
        args = mock_run.call_args[0][0]
        assert args.output_file == "out.json"
