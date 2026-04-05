from __future__ import annotations

from typing import Protocol

from cs2.models.pricing import MarketData, RawListing


class ListingSource(Protocol):
    """Protocol for listing data sources."""

    def fetch_listing(self, listing_id: str) -> RawListing:
        """Fetch a single listing by ID."""
        ...


class MarketSource(Protocol):
    """Protocol for market data sources."""

    def fetch_market_data(self, item_name: str) -> MarketData:
        """Fetch market data for a canonical item name."""
        ...


class SourceError(Exception):
    """Base error for source failures."""

    pass


class AuthError(SourceError):
    """API authentication failed."""

    pass


class RateLimitError(SourceError):
    """API rate limit exceeded."""

    def __init__(self, retry_after: float = 30.0):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s")


class ListingNotFoundError(SourceError):
    """Listing not found or sold."""

    pass


class SourceFormatError(SourceError):
    """Unexpected response format from source."""

    pass
