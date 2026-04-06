from __future__ import annotations

import sys
import warnings
from dataclasses import dataclass, field

from cs2.config import Settings
from cs2.engine.decision import decide
from cs2.engine.enrichment import EnrichmentError, enrich
from cs2.engine.identity import InvalidItemError, build_market_hash_name, resolve_identity
from cs2.engine.liquidity import analyze_liquidity
from cs2.engine.pricing import calculate_pricing
from cs2.models.decision import Decision, DecisionAction
from cs2.models.items import CanonicalItem, ExactInstance
from cs2.models.liquidity import LiquidityGrade, LiquidityResult
from cs2.models.pricing import ItemClass, MarketData, PricingResult, RawListing
from cs2.sources.base import SourceError
from cs2.sources.csfloat import CSFloatClient
from cs2.sources.dmarket import DMarketClient
from cs2.sources.skinport import SkinportClient
from cs2.sources.steam import SteamClient
from cs2.storage.cache import CacheStore
from cs2.storage.logger import DecisionLogger


@dataclass
class PipelineResult:
    """All intermediate and final results from pipeline execution."""
    decision: Decision
    canonical: CanonicalItem
    instance: ExactInstance | None = None
    pricing: PricingResult | None = None
    liquidity: LiquidityResult | None = None
    listing: RawListing | None = None
    market_data: MarketData | None = None
    warnings: list[str] = field(default_factory=list)


class Pipeline:
    """Sequential pipeline orchestrator."""

    def __init__(
        self,
        settings: Settings,
        cache: CacheStore,
        logger: DecisionLogger,
        offline: bool = False,
    ) -> None:
        self.settings = settings
        self.cache = cache
        self.logger = logger
        self.offline = offline
        self.csfloat = CSFloatClient(settings, cache)
        self.steam = SteamClient(settings, cache)
        self.skinport: SkinportClient | None = (
            SkinportClient(settings, cache) if settings.skinport_enabled else None
        )
        self.dmarket: DMarketClient | None = (
            DMarketClient(settings, cache) if settings.dmarket_enabled else None
        )

    def close(self) -> None:
        self.csfloat.close()
        self.steam.close()
        if self.skinport is not None:
            self.skinport.close()
        if self.dmarket is not None:
            self.dmarket.close()

    def analyze_url(self, url: str) -> PipelineResult:
        """Run full pipeline from a URL."""
        result_warnings: list[str] = []

        # Step 1: Source Ingest
        listing: RawListing | None = None
        if self.offline:
            listing = self._offline_fetch_listing(url)
        else:
            try:
                listing = self.csfloat.fetch_listing(url)
            except SourceError as exc:
                raise PipelineError(f"Cannot fetch listing: {exc}")

        # Step 2: Identity
        try:
            canonical = resolve_identity(listing.item_name)
        except InvalidItemError as exc:
            raise PipelineError(f"Cannot identify item: {exc}")

        # Step 3: Market data
        market_name = build_market_hash_name(canonical)
        market_data = self._fetch_market_data(market_name, result_warnings)

        # Step 4: Enrichment
        instance = self._enrich(listing, canonical, result_warnings)

        # Step 5: Pricing
        pricing = self._price(canonical, instance, market_data, result_warnings)

        # Step 6: Liquidity
        liquidity = self._analyze_liquidity(
            canonical, market_data, pricing, result_warnings
        )

        # Step 7: Decision
        decision = self._decide(pricing, liquidity, listing.price, result_warnings)

        # Step 8: Log
        self.logger.log(
            decision=decision,
            canonical=canonical,
            pricing=pricing,
            liquidity=liquidity,
            instance=instance,
            input_url=url,
        )

        return PipelineResult(
            decision=decision,
            canonical=canonical,
            instance=instance,
            pricing=pricing,
            liquidity=liquidity,
            listing=listing,
            market_data=market_data,
            warnings=result_warnings,
        )

    def analyze_manual(
        self,
        weapon: str,
        skin: str,
        quality: str,
        float_value: float | None = None,
        stattrak: bool = False,
    ) -> PipelineResult:
        """Run pipeline from manual item spec (skips source ingest)."""
        result_warnings: list[str] = []

        canonical = CanonicalItem(
            weapon=weapon,
            skin=skin,
            quality=quality,
            stattrak=stattrak,
            souvenir=False,
        )

        # Fetch market data
        market_name = build_market_hash_name(canonical)
        market_data = self._fetch_market_data(market_name, result_warnings)

        # Build ExactInstance if float_value is provided
        instance: ExactInstance | None = None
        if float_value is not None:
            instance = ExactInstance(
                canonical=canonical,
                float_value=float_value,
                paint_seed=0,
                stickers=[],
                stattrak_kills=None,
            )

        # Pricing
        pricing = self._price(canonical, instance, market_data, result_warnings)

        # Liquidity
        liquidity = self._analyze_liquidity(
            canonical, market_data, pricing, result_warnings
        )

        # Use market median as listing price for manual analysis
        listing_price = market_data.median_price if market_data else 0.0
        decision = self._decide(pricing, liquidity, listing_price, result_warnings)

        self.logger.log(
            decision=decision,
            canonical=canonical,
            pricing=pricing,
            liquidity=liquidity,
            instance=instance,
        )

        return PipelineResult(
            decision=decision,
            canonical=canonical,
            instance=instance,
            pricing=pricing,
            liquidity=liquidity,
            market_data=market_data,
            warnings=result_warnings,
        )

    def _fetch_market_data(
        self, market_name: str, warns: list[str]
    ) -> MarketData:
        """Fetch market data from CSFloat, fallback to Steam, aggregate extras."""
        if self.offline:
            return self._offline_fetch_market_data(market_name)

        primary: MarketData | None = None

        try:
            primary = self.csfloat.fetch_market_data(market_name)
        except SourceError:
            warns.append("CSFloat market data unavailable, trying Steam")

        if primary is None:
            try:
                primary = self.steam.fetch_market_data(market_name)
            except SourceError:
                warns.append("Steam market data unavailable — using degraded mode")

        # Collect additional source prices for aggregation
        extra_prices: list[float] = []

        if self.skinport is not None:
            try:
                sp = self.skinport.fetch_market_data(market_name)
                if sp.median_price > 0:
                    extra_prices.append(sp.median_price)
            except SourceError:
                warns.append("Skinport market data unavailable")

        if self.dmarket is not None:
            try:
                dm = self.dmarket.fetch_market_data(market_name)
                if dm.median_price > 0:
                    extra_prices.append(dm.median_price)
            except SourceError:
                warns.append("DMarket market data unavailable")

        if primary is None:
            if extra_prices:
                # Use extra sources as primary
                import statistics
                median = statistics.median(extra_prices)
                return MarketData(
                    item_name=market_name,
                    median_price=median,
                    lowest_price=min(extra_prices),
                    volume_24h=None,
                    recent_sales=[],
                    source="aggregated",
                )
            # Fallback: minimal market data
            return MarketData(
                item_name=market_name,
                median_price=0.0,
                lowest_price=None,
                volume_24h=None,
                recent_sales=[],
                source="none",
            )

        # Aggregate: median across primary + extra sources
        if extra_prices and primary.median_price > 0:
            import statistics
            all_prices = [primary.median_price] + extra_prices
            primary = primary.model_copy(
                update={"median_price": statistics.median(all_prices)}
            )

        return primary

    # ------------------------------------------------------------------
    # Offline helpers
    # ------------------------------------------------------------------

    def _offline_fetch_listing(self, url: str) -> RawListing:
        """Load listing from cache only (ignore TTL). Raise on miss."""
        from cs2.sources.csfloat import parse_listing_id

        listing_id = parse_listing_id(url)
        cache_key = f"csfloat:listing:{listing_id}"
        cached = self.cache.get(cache_key, ignore_ttl=True)
        if cached is not None:
            return RawListing.model_validate_json(cached)
        raise PipelineError(
            f"No cached data for listing '{listing_id}'. Run online analysis first."
        )

    def _offline_fetch_market_data(self, market_name: str) -> MarketData:
        """Load market data from cache only (ignore TTL). Raise on miss."""
        for prefix in ("csfloat:market:", "steam:market:"):
            cached = self.cache.get(f"{prefix}{market_name}", ignore_ttl=True)
            if cached is not None:
                return MarketData.model_validate_json(cached)
        raise PipelineError(
            f"No cached market data for '{market_name}'. Run online analysis first."
        )

    def _enrich(
        self,
        listing: RawListing,
        canonical: CanonicalItem,
        warns: list[str],
    ) -> ExactInstance | None:
        """Enrich with exact data. Returns None on failure (commodity mode)."""
        try:
            return enrich(listing, canonical, self.cache, self.settings)
        except EnrichmentError as exc:
            warns.append(str(exc))
            return None

    def _price(
        self,
        canonical: CanonicalItem,
        instance: ExactInstance | None,
        market_data: MarketData,
        warns: list[str],
    ) -> PricingResult:
        """Calculate pricing. Falls back to base-price-only on error."""
        try:
            return calculate_pricing(
                canonical, instance, market_data, self.settings, self.cache
            )
        except Exception as exc:
            warns.append(f"Pricing error: {exc}")
            return PricingResult(
                canonical=canonical,
                base_price=market_data.median_price,
                item_class=ItemClass.COMMODITY,
                estimated_value=market_data.median_price,
                premium_breakdown={},
                incomplete=True,
            )

    def _analyze_liquidity(
        self,
        canonical: CanonicalItem,
        market_data: MarketData,
        pricing: PricingResult,
        warns: list[str],
    ) -> LiquidityResult:
        """Analyze liquidity. Falls back to UNKNOWN on error."""
        try:
            return analyze_liquidity(
                canonical,
                market_data,
                pricing.estimated_value,
                pricing.base_price,
                self.settings,
            )
        except Exception as exc:
            warns.append(f"Liquidity error: {exc}")
            return LiquidityResult(
                canonical=canonical,
                avg_daily_volume=0.0,
                avg_spread_pct=0.0,
                min_sell_days=0,
                max_sell_days=999,
                safe_exit_price=pricing.base_price * 0.9,
                grade=LiquidityGrade.UNKNOWN,
            )

    def _decide(
        self,
        pricing: PricingResult,
        liquidity: LiquidityResult,
        listing_price: float,
        warns: list[str],
    ) -> Decision:
        """Make decision. Falls back to REVIEW on error."""
        try:
            return decide(pricing, liquidity, listing_price, self.settings)
        except Exception as exc:
            warns.append(f"Decision error: {exc}")
            return Decision(
                action=DecisionAction.REVIEW,
                confidence=0.0,
                listing_price=listing_price,
                estimated_value=pricing.estimated_value,
                margin_pct=0.0,
                safe_exit_price=liquidity.safe_exit_price,
                reasons=[f"Decision engine error: {exc}"],
                risk_flags=["Decision engine failed"],
            )


class PipelineError(Exception):
    """Hard pipeline failure — cannot proceed."""
    pass
