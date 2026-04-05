from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


class ConfigError(Exception):
    """Configuration error — missing keys, invalid TOML, etc."""
    pass


class Settings(BaseModel, frozen=True):
    # API keys
    csfloat_api_key: str
    steam_api_key: str | None = None

    # Thresholds
    premium_float_top_pct: float = 0.05
    premium_sticker_min_value: float = 5.0
    confidence_review_threshold: float = 0.5
    min_sales_for_base_price: int = 5

    # Cache TTL (seconds)
    cache_ttl_market_price: int = 3600
    cache_ttl_listing: int = 900
    cache_ttl_identity: int = 604800
    cache_ttl_sticker_price: int = 86400
    cache_ttl_float_data: int = 2592000

    # Liquidity
    liquidity_high_threshold: float = 10.0
    liquidity_low_threshold: float = 1.0

    # Premium multipliers
    sticker_mult_kato14_holo: float = 0.12
    sticker_mult_kato14: float = 0.065
    sticker_mult_other_holo: float = 0.04
    sticker_best_position_bonus: float = 1.2
    sticker_scratched_penalty: float = 0.5


def load_settings(
    config_path: str | Path | None = None,
    env_path: str | Path | None = None,
) -> Settings:
    """Load settings from config.toml + .env files.

    Priority: .env (API keys) > config.toml (overrides) > defaults.
    """
    # Load .env for API keys
    if env_path is None:
        env_path = Path.cwd() / ".env"
    env_path = Path(env_path)
    if env_path.exists():
        load_dotenv(env_path)

    csfloat_api_key = os.environ.get("CSFLOAT_API_KEY", "")
    if not csfloat_api_key:
        raise ConfigError(
            "CSFLOAT_API_KEY not set. "
            "Create a .env file with your API key (see .env.example)."
        )

    steam_api_key = os.environ.get("STEAM_API_KEY") or None

    overrides: dict = {
        "csfloat_api_key": csfloat_api_key,
        "steam_api_key": steam_api_key,
    }

    # Load config.toml for threshold overrides
    if config_path is None:
        config_path = Path.cwd() / "config.toml"
    config_path = Path(config_path)

    if config_path.exists():
        try:
            with open(config_path, "rb") as f:
                toml_data = tomllib.load(f)
        except Exception as exc:
            raise ConfigError(f"Error reading {config_path}: {exc}")

        # Flatten TOML sections into Settings fields
        thresholds = toml_data.get("thresholds", {})
        cache_ttl = toml_data.get("cache_ttl", {})
        liquidity = toml_data.get("liquidity", {})
        sticker = toml_data.get("sticker_premiums", {})

        for key, val in thresholds.items():
            overrides[key] = val

        ttl_map = {
            "market_price": "cache_ttl_market_price",
            "listing": "cache_ttl_listing",
            "identity": "cache_ttl_identity",
            "sticker_price": "cache_ttl_sticker_price",
            "float_data": "cache_ttl_float_data",
        }
        for toml_key, settings_key in ttl_map.items():
            if toml_key in cache_ttl:
                overrides[settings_key] = cache_ttl[toml_key]

        liq_map = {
            "high_threshold": "liquidity_high_threshold",
            "low_threshold": "liquidity_low_threshold",
        }
        for toml_key, settings_key in liq_map.items():
            if toml_key in liquidity:
                overrides[settings_key] = liquidity[toml_key]

        sticker_map = {
            "mult_kato14_holo": "sticker_mult_kato14_holo",
            "mult_kato14": "sticker_mult_kato14",
            "mult_other_holo": "sticker_mult_other_holo",
            "best_position_bonus": "sticker_best_position_bonus",
            "scratched_penalty": "sticker_scratched_penalty",
        }
        for toml_key, settings_key in sticker_map.items():
            if toml_key in sticker:
                overrides[settings_key] = sticker[toml_key]

    return Settings(**overrides)
