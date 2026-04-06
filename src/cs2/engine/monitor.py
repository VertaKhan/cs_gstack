from __future__ import annotations

import signal
import time
from dataclasses import dataclass, field
from datetime import datetime

from rich.console import Console
from rich.panel import Panel

from cs2.config import Settings
from cs2.engine.identity import build_market_hash_name
from cs2.models.decision import DecisionAction
from cs2.models.items import CanonicalItem
from cs2.models.pricing import RawListing
from cs2.pipeline import Pipeline, PipelineError, PipelineResult
from cs2.sources.base import SourceError
from cs2.storage.cache import CacheStore
from cs2.storage.logger import DecisionLogger

console = Console()


@dataclass
class MonitorCriteria:
    """Criteria for monitoring listings."""
    weapon: str
    skin: str
    quality: str = "Field-Tested"
    stattrak: bool = False
    max_price: float | None = None
    min_margin: float = 15.0


@dataclass
class MonitorStats:
    """Running statistics for a monitoring session."""
    checks: int = 0
    total_listings: int = 0
    alerts: int = 0


class Monitor:
    """Polling monitor for underpriced CS2 listings."""

    def __init__(
        self,
        criteria: MonitorCriteria,
        settings: Settings,
        cache: CacheStore,
        logger: DecisionLogger,
        interval: int = 300,
    ) -> None:
        self.criteria = criteria
        self.settings = settings
        self.cache = cache
        self.logger = logger
        self.interval = interval
        self.stats = MonitorStats()
        self._stop = False

    def stop(self) -> None:
        """Signal the monitor to stop after current iteration."""
        self._stop = True

    def run(self) -> MonitorStats:
        """Run the polling loop. Blocks until stopped or Ctrl+C."""
        canonical = CanonicalItem(
            weapon=self.criteria.weapon,
            skin=self.criteria.skin,
            quality=self.criteria.quality,
            stattrak=self.criteria.stattrak,
            souvenir=False,
        )
        market_name = build_market_hash_name(canonical)

        # Display monitoring header
        max_price_str = f"max ${self.criteria.max_price:.0f}" if self.criteria.max_price else "no price limit"
        console.print(
            f"[bold]Monitoring {self.criteria.weapon} | {self.criteria.skin} "
            f"({self.criteria.quality})"
            f"{' StatTrak' if self.criteria.stattrak else ''}"
            f" ({max_price_str}, every {self.interval}s)...[/bold]"
        )
        console.print("[dim]Press Ctrl+C to stop[/dim]\n")

        # Install SIGINT handler
        original_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, lambda *_: self.stop())

        try:
            while not self._stop:
                self._check_once(canonical, market_name)
                if self._stop:
                    break
                # Sleep in short chunks so stop flag is responsive
                for _ in range(self.interval * 10):
                    if self._stop:
                        break
                    time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            signal.signal(signal.SIGINT, original_handler)

        # Summary
        console.print(
            f"\n[bold]Monitoring stopped.[/bold] "
            f"{self.stats.checks} checks, "
            f"{self.stats.total_listings} listings scanned, "
            f"{self.stats.alerts} alerts found."
        )
        return self.stats

    def _check_once(self, canonical: CanonicalItem, market_name: str) -> None:
        """Perform a single check cycle."""
        self.stats.checks += 1
        now = datetime.now().strftime("%H:%M:%S")

        pipeline = Pipeline(self.settings, self.cache, self.logger)
        try:
            listings = self._fetch_listings(pipeline, market_name)

            # Filter by max_price before full analysis
            if self.criteria.max_price is not None:
                listings = [l for l in listings if l.price <= self.criteria.max_price]

            check_alerts = 0
            for listing in listings:
                try:
                    result = pipeline.analyze_url(listing.listing_id)
                    if self._should_alert(result):
                        self._render_alert(result, listing)
                        check_alerts += 1
                        self.stats.alerts += 1
                except PipelineError:
                    pass

            self.stats.total_listings += len(listings)
            console.print(
                f"[dim]Check #{self.stats.checks} at {now} -- "
                f"{len(listings)} listings scanned, {check_alerts} alerts[/dim]"
            )
        except SourceError as exc:
            console.print(
                f"[yellow]Check #{self.stats.checks} at {now} -- "
                f"Error fetching listings: {exc}[/yellow]"
            )
        finally:
            pipeline.close()

    def _fetch_listings(
        self, pipeline: Pipeline, market_name: str
    ) -> list[RawListing]:
        """Fetch current listings from CSFloat search endpoint."""
        params: dict = {"market_hash_name": market_name}
        if self.criteria.max_price is not None:
            # CSFloat expects price in cents
            params["max_price"] = int(self.criteria.max_price * 100)

        try:
            resp = pipeline.csfloat.client.get("/listings", params=params)
        except Exception as exc:
            raise SourceError(f"Failed to search listings: {exc}")

        if resp.status_code != 200:
            raise SourceError(f"CSFloat listings search error: {resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            raise SourceError("CSFloat listings: invalid JSON")

        raw_listings = data if isinstance(data, list) else data.get("data", [])
        results: list[RawListing] = []
        for item_data in raw_listings:
            try:
                listing = pipeline.csfloat._parse_listing(item_data, str(item_data.get("id", "")))
                results.append(listing)
            except Exception:
                continue

        return results

    def _should_alert(self, result: PipelineResult) -> bool:
        """Determine if this result warrants an alert."""
        if result.decision.action == DecisionAction.BUY:
            return True
        if result.decision.margin_pct >= self.criteria.min_margin:
            return True
        return False

    def _render_alert(self, result: PipelineResult, listing: RawListing) -> None:
        """Render an alert panel for an underpriced item."""
        decision = result.decision
        canonical = result.canonical

        item_name = canonical.weapon
        if canonical.skin:
            item_name += f" | {canonical.skin}"
        if canonical.quality:
            item_name += f" ({canonical.quality})"
        if canonical.stattrak:
            item_name = f"StatTrak {item_name}"

        margin_sign = "+" if decision.margin_pct >= 0 else ""

        lines = [
            f"{item_name} -- ${decision.listing_price:.2f}",
            f"Estimated: ${decision.estimated_value:.2f} ({margin_sign}{decision.margin_pct:.1f}%)  "
            f"Safe Exit: ${decision.safe_exit_price:.2f}",
            f"Confidence: {int(decision.confidence * 100)}%  Action: {decision.action.value.upper()}",
        ]

        if listing.listing_id:
            lines.append(f"URL: https://csfloat.com/item/{listing.listing_id}")

        panel = Panel(
            "\n".join(lines),
            title="ALERT: Underpriced Item Found!",
            border_style="green bold",
            padding=(0, 2),
        )
        console.print(panel)
        # System beep
        print("\a")
