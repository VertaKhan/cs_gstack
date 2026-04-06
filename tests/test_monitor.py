from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from cs2.engine.monitor import Monitor, MonitorCriteria, MonitorStats
from cs2.models.decision import Decision, DecisionAction
from cs2.models.items import CanonicalItem
from cs2.models.pricing import RawListing, MarketData, PricingResult, ItemClass
from cs2.models.liquidity import LiquidityGrade, LiquidityResult
from cs2.pipeline import PipelineResult


def _make_listing(listing_id: str, price: float) -> RawListing:
    return RawListing(
        listing_id=listing_id,
        item_name="AK-47 | Redline (Field-Tested)",
        price=price,
        float_value=0.25,
        paint_seed=42,
        stickers=[],
        source="csfloat",
    )


def _make_pipeline_result(action: DecisionAction, margin: float, price: float = 40.0) -> PipelineResult:
    canonical = CanonicalItem(
        weapon="AK-47", skin="Redline", quality="Field-Tested",
        stattrak=False, souvenir=False,
    )
    decision = Decision(
        action=action,
        confidence=0.8,
        listing_price=price,
        estimated_value=price * (1 + margin / 100),
        margin_pct=margin,
        safe_exit_price=price * 1.1,
        reasons=["test"],
        risk_flags=[],
    )
    return PipelineResult(decision=decision, canonical=canonical)


class TestMonitorCriteria:
    def test_criteria_defaults(self):
        c = MonitorCriteria(weapon="AK-47", skin="Redline")
        assert c.quality == "Field-Tested"
        assert c.stattrak is False
        assert c.max_price is None
        assert c.min_margin == 15.0

    def test_criteria_custom(self):
        c = MonitorCriteria(
            weapon="AWP", skin="Asiimov", quality="Battle-Scarred",
            stattrak=True, max_price=30.0, min_margin=25.0,
        )
        assert c.weapon == "AWP"
        assert c.stattrak is True
        assert c.max_price == 30.0


class TestMonitorFindsUnderpriced:
    """Monitor detects BUY items and alerts."""

    @patch("cs2.engine.monitor.Pipeline")
    def test_alert_on_buy_decision(self, MockPipeline, settings, cache, logger):
        criteria = MonitorCriteria(weapon="AK-47", skin="Redline", max_price=50.0)
        monitor = Monitor(criteria, settings, cache, logger, interval=1)

        buy_result = _make_pipeline_result(DecisionAction.BUY, margin=30.0, price=42.0)
        listing = _make_listing("listing-1", 42.0)

        mock_pipeline = MagicMock()
        MockPipeline.return_value = mock_pipeline
        mock_pipeline.analyze_url.return_value = buy_result
        mock_pipeline.csfloat.client.get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[{
                "id": "listing-1",
                "price": 4200,
                "item": {"market_hash_name": "AK-47 | Redline (Field-Tested)", "float_value": 0.25, "paint_seed": 42},
            }]),
        )
        mock_pipeline.csfloat._parse_listing.return_value = listing

        # Stop after first check
        def stop_after_delay():
            time.sleep(0.5)
            monitor.stop()

        t = threading.Thread(target=stop_after_delay)
        t.start()
        stats = monitor.run()
        t.join()

        assert stats.checks >= 1
        assert stats.alerts >= 1


class TestMonitorSkipsOverpriced:
    """Monitor does not alert on NO_BUY items with low margin."""

    @patch("cs2.engine.monitor.Pipeline")
    def test_no_alert_on_no_buy(self, MockPipeline, settings, cache, logger):
        criteria = MonitorCriteria(weapon="AK-47", skin="Redline", min_margin=20.0)
        monitor = Monitor(criteria, settings, cache, logger, interval=1)

        no_buy_result = _make_pipeline_result(DecisionAction.NO_BUY, margin=5.0, price=60.0)
        listing = _make_listing("listing-2", 60.0)

        mock_pipeline = MagicMock()
        MockPipeline.return_value = mock_pipeline
        mock_pipeline.analyze_url.return_value = no_buy_result
        mock_pipeline.csfloat.client.get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[{
                "id": "listing-2",
                "price": 6000,
                "item": {"market_hash_name": "AK-47 | Redline (Field-Tested)"},
            }]),
        )
        mock_pipeline.csfloat._parse_listing.return_value = listing

        def stop_after_delay():
            time.sleep(0.5)
            monitor.stop()

        t = threading.Thread(target=stop_after_delay)
        t.start()
        stats = monitor.run()
        t.join()

        assert stats.checks >= 1
        assert stats.alerts == 0


class TestMonitorRespectsMaxPrice:
    """Listings above max_price are filtered out before analysis."""

    @patch("cs2.engine.monitor.Pipeline")
    def test_filters_expensive_listings(self, MockPipeline, settings, cache, logger):
        criteria = MonitorCriteria(weapon="AK-47", skin="Redline", max_price=50.0)
        monitor = Monitor(criteria, settings, cache, logger, interval=1)

        cheap_listing = _make_listing("cheap-1", 40.0)
        expensive_listing = _make_listing("expensive-1", 80.0)

        buy_result = _make_pipeline_result(DecisionAction.BUY, margin=30.0, price=40.0)

        mock_pipeline = MagicMock()
        MockPipeline.return_value = mock_pipeline
        mock_pipeline.analyze_url.return_value = buy_result
        mock_pipeline.csfloat.client.get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[
                {"id": "cheap-1", "price": 4000, "item": {"market_hash_name": "AK-47 | Redline (Field-Tested)"}},
                {"id": "expensive-1", "price": 8000, "item": {"market_hash_name": "AK-47 | Redline (Field-Tested)"}},
            ]),
        )

        def parse_side_effect(data, lid):
            price = data["price"] / 100
            return _make_listing(lid, price)

        mock_pipeline.csfloat._parse_listing.side_effect = parse_side_effect

        def stop_after_delay():
            time.sleep(0.5)
            monitor.stop()

        t = threading.Thread(target=stop_after_delay)
        t.start()
        stats = monitor.run()
        t.join()

        # Only the cheap listing should have been analyzed
        assert mock_pipeline.analyze_url.call_count >= 1
        # expensive listing (80.0 > 50.0) should be filtered, so only 1 call per check
        for call in mock_pipeline.analyze_url.call_args_list:
            assert call.args[0] == "cheap-1"


class TestMonitorStop:
    """Stop flag breaks the polling loop."""

    @patch("cs2.engine.monitor.Pipeline")
    def test_stop_flag(self, MockPipeline, settings, cache, logger):
        criteria = MonitorCriteria(weapon="AK-47", skin="Redline")
        monitor = Monitor(criteria, settings, cache, logger, interval=60)

        mock_pipeline = MagicMock()
        MockPipeline.return_value = mock_pipeline
        mock_pipeline.csfloat.client.get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[]),
        )

        # Stop immediately
        def stop_quickly():
            time.sleep(0.2)
            monitor.stop()

        t = threading.Thread(target=stop_quickly)
        t.start()
        start = time.time()
        stats = monitor.run()
        elapsed = time.time() - start
        t.join()

        # Should not have waited the full 60s interval
        assert elapsed < 5.0
        assert stats.checks >= 1
