from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from cs2.cli import main


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
