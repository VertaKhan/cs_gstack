from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cs2.cli import main, _compare_recommendation, _item_label
from cs2.models.decision import Decision, DecisionAction
from cs2.models.items import CanonicalItem
from cs2.models.liquidity import LiquidityGrade, LiquidityResult
from cs2.pipeline import PipelineError, PipelineResult


def _make_result(
    action: DecisionAction = DecisionAction.BUY,
    confidence: float = 0.8,
    margin_pct: float = 30.0,
    listing_price: float = 80.0,
    estimated_value: float = 104.0,
    safe_exit_price: float = 95.0,
    liquidity_grade: LiquidityGrade = LiquidityGrade.HIGH,
    weapon: str = "AK-47",
    skin: str = "Redline",
    quality: str = "Field-Tested",
) -> PipelineResult:
    canonical = CanonicalItem(
        weapon=weapon,
        skin=skin,
        quality=quality,
        stattrak=False,
        souvenir=False,
    )
    decision = Decision(
        action=action,
        confidence=confidence,
        listing_price=listing_price,
        estimated_value=estimated_value,
        margin_pct=margin_pct,
        safe_exit_price=safe_exit_price,
        reasons=[],
        risk_flags=[],
    )
    liquidity = LiquidityResult(
        canonical=canonical,
        avg_daily_volume=10.0,
        avg_spread_pct=5.0,
        min_sell_days=1,
        max_sell_days=7,
        safe_exit_price=safe_exit_price,
        grade=liquidity_grade,
    )
    return PipelineResult(
        decision=decision,
        canonical=canonical,
        liquidity=liquidity,
    )


class TestCompareParseArgs:
    @patch("cs2.cli._run_compare")
    def test_compare_parse_args(self, mock_run):
        """compare subcommand parses url1 and url2."""
        main(["compare", "https://csfloat.com/item/1", "https://csfloat.com/item/2"])
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args.command == "compare"
        assert args.url1 == "https://csfloat.com/item/1"
        assert args.url2 == "https://csfloat.com/item/2"

    @patch("cs2.cli._run_compare")
    def test_compare_with_config(self, mock_run):
        """compare subcommand accepts --config and --env."""
        main([
            "compare",
            "https://csfloat.com/item/1",
            "https://csfloat.com/item/2",
            "--config", "/tmp/c.toml",
            "--env", "/tmp/.env",
        ])
        args = mock_run.call_args[0][0]
        assert args.config == "/tmp/c.toml"
        assert args.env == "/tmp/.env"

    def test_compare_missing_args(self):
        """compare with missing URLs raises SystemExit."""
        with pytest.raises(SystemExit):
            main(["compare"])

        with pytest.raises(SystemExit):
            main(["compare", "https://csfloat.com/item/1"])


class TestCompareRecommendation:
    def test_buy_over_review(self):
        """BUY should be preferred over REVIEW."""
        r1 = _make_result(action=DecisionAction.BUY, confidence=0.5)
        r2 = _make_result(action=DecisionAction.REVIEW, confidence=0.9)
        rec = _compare_recommendation(r1, r2)
        assert "Item 1" in rec
        assert "better action verdict" in rec

    def test_review_over_no_buy(self):
        """REVIEW should be preferred over NO_BUY."""
        r1 = _make_result(action=DecisionAction.NO_BUY)
        r2 = _make_result(action=DecisionAction.REVIEW)
        rec = _compare_recommendation(r1, r2)
        assert "Item 2" in rec

    def test_higher_confidence_wins(self):
        """Same action -> higher confidence wins."""
        r1 = _make_result(action=DecisionAction.BUY, confidence=0.65, margin_pct=30.0)
        r2 = _make_result(action=DecisionAction.BUY, confidence=0.82, margin_pct=30.0)
        rec = _compare_recommendation(r1, r2)
        assert "Item 2" in rec
        assert "higher confidence" in rec

    def test_higher_margin_wins(self):
        """Same action + confidence -> higher margin wins."""
        r1 = _make_result(action=DecisionAction.BUY, confidence=0.8, margin_pct=50.0)
        r2 = _make_result(action=DecisionAction.BUY, confidence=0.8, margin_pct=20.0)
        rec = _compare_recommendation(r1, r2)
        assert "Item 1" in rec
        assert "higher margin" in rec

    def test_liquidity_tiebreaker(self):
        """Same action + confidence + margin -> better liquidity wins."""
        r1 = _make_result(
            action=DecisionAction.BUY, confidence=0.8, margin_pct=30.0,
            liquidity_grade=LiquidityGrade.MEDIUM,
        )
        r2 = _make_result(
            action=DecisionAction.BUY, confidence=0.8, margin_pct=30.0,
            liquidity_grade=LiquidityGrade.HIGH,
        )
        rec = _compare_recommendation(r1, r2)
        assert "Item 2" in rec
        assert "better liquidity" in rec

    def test_tie(self):
        """Identical items -> tie."""
        r1 = _make_result()
        r2 = _make_result()
        rec = _compare_recommendation(r1, r2)
        assert "Tie" in rec


class TestCompareOneFails:
    def test_one_item_fails(self):
        """If one item fails, show the other's analysis + error message."""
        mock_settings = MagicMock()
        result2 = _make_result()

        with (
            patch("cs2.cli.load_settings", return_value=mock_settings),
            patch("cs2.cli.get_connection") as mock_conn,
            patch("cs2.cli.CacheStore"),
            patch("cs2.cli.DecisionLogger"),
            patch("cs2.cli.Pipeline") as MockPipeline,
            patch("cs2.cli._render_decision_card") as mock_render,
            patch("cs2.cli.console") as mock_console,
        ):
            mock_pipeline = MockPipeline.return_value
            mock_pipeline.analyze_url.side_effect = [
                PipelineError("bad url"),
                result2,
            ]

            from cs2.cli import _run_compare
            from argparse import Namespace

            args = Namespace(
                command="compare",
                url1="bad-url",
                url2="https://csfloat.com/item/2",
                config=None,
                env=None,
            )
            _run_compare(args)

            mock_render.assert_called_once_with(result2)
            # Check that error message was printed
            calls = [str(c) for c in mock_console.print.call_args_list]
            assert any("Could not analyze Item 1" in c for c in calls)

    def test_both_items_fail(self):
        """If both items fail, sys.exit(1)."""
        mock_settings = MagicMock()

        with (
            patch("cs2.cli.load_settings", return_value=mock_settings),
            patch("cs2.cli.get_connection"),
            patch("cs2.cli.CacheStore"),
            patch("cs2.cli.DecisionLogger"),
            patch("cs2.cli.Pipeline") as MockPipeline,
        ):
            mock_pipeline = MockPipeline.return_value
            mock_pipeline.analyze_url.side_effect = PipelineError("fail")

            from cs2.cli import _run_compare
            from argparse import Namespace

            args = Namespace(
                command="compare",
                url1="bad1",
                url2="bad2",
                config=None,
                env=None,
            )
            with pytest.raises(SystemExit) as exc_info:
                _run_compare(args)
            assert exc_info.value.code == 1
