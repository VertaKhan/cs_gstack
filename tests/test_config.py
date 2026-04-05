from __future__ import annotations

import os
import textwrap

import pytest

from cs2.config import ConfigError, Settings, load_settings


class TestDefaultConfig:
    def test_defaults(self):
        s = Settings(csfloat_api_key="test-key")
        assert s.premium_float_top_pct == 0.05
        assert s.cache_ttl_market_price == 3600
        assert s.liquidity_high_threshold == 10.0
        assert s.sticker_mult_kato14_holo == 0.12
        assert s.steam_api_key is None

    def test_frozen(self):
        s = Settings(csfloat_api_key="test-key")
        with pytest.raises(Exception):
            s.csfloat_api_key = "other"  # type: ignore[misc]


class TestCustomConfig:
    def test_custom_values(self):
        s = Settings(
            csfloat_api_key="k",
            premium_float_top_pct=0.10,
            cache_ttl_market_price=7200,
            liquidity_high_threshold=20.0,
        )
        assert s.premium_float_top_pct == 0.10
        assert s.cache_ttl_market_price == 7200
        assert s.liquidity_high_threshold == 20.0


class TestLoadSettings:
    def test_env_loading(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("CSFLOAT_API_KEY=my-key-123\nSTEAM_API_KEY=steam-456\n")
        config_file = tmp_path / "config.toml"
        # no config.toml — use defaults
        monkeypatch.delenv("CSFLOAT_API_KEY", raising=False)
        monkeypatch.delenv("STEAM_API_KEY", raising=False)

        s = load_settings(config_path=config_file, env_path=env_file)
        assert s.csfloat_api_key == "my-key-123"
        assert s.steam_api_key == "steam-456"

    def test_missing_env(self, tmp_path, monkeypatch):
        """Missing .env and no env var set -> ConfigError."""
        monkeypatch.delenv("CSFLOAT_API_KEY", raising=False)
        monkeypatch.delenv("STEAM_API_KEY", raising=False)
        env_file = tmp_path / ".env"  # does not exist
        config_file = tmp_path / "config.toml"

        with pytest.raises((SystemExit, ConfigError)):
            load_settings(config_path=config_file, env_path=env_file)

    def test_invalid_toml(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("CSFLOAT_API_KEY=test\n")
        config_file = tmp_path / "config.toml"
        config_file.write_text("this is not valid toml {{{{")
        monkeypatch.delenv("CSFLOAT_API_KEY", raising=False)

        with pytest.raises((SystemExit, ConfigError)):
            load_settings(config_path=config_file, env_path=env_file)

    def test_partial_config(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("CSFLOAT_API_KEY=key\n")
        config_file = tmp_path / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [thresholds]
            premium_float_top_pct = 0.10
        """))
        monkeypatch.delenv("CSFLOAT_API_KEY", raising=False)

        s = load_settings(config_path=config_file, env_path=env_file)
        assert s.premium_float_top_pct == 0.10
        # Other values stay default
        assert s.cache_ttl_market_price == 3600
        assert s.liquidity_high_threshold == 10.0

    def test_custom_config_sections(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("CSFLOAT_API_KEY=key\n")
        config_file = tmp_path / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [cache_ttl]
            market_price = 1800
            listing = 300

            [liquidity]
            high_threshold = 25.0

            [sticker_premiums]
            mult_kato14_holo = 0.15
        """))
        monkeypatch.delenv("CSFLOAT_API_KEY", raising=False)

        s = load_settings(config_path=config_file, env_path=env_file)
        assert s.cache_ttl_market_price == 1800
        assert s.cache_ttl_listing == 300
        assert s.liquidity_high_threshold == 25.0
        assert s.sticker_mult_kato14_holo == 0.15
