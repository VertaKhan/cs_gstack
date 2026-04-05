from __future__ import annotations

import warnings

import pytest

from cs2.engine.identity import (
    InvalidItemError,
    build_market_hash_name,
    resolve_identity,
)
from cs2.models.items import CanonicalItem


class TestResolveIdentity:
    def test_basic_parse(self):
        item = resolve_identity("AK-47 | Redline (Field-Tested)")
        assert item.weapon == "AK-47"
        assert item.skin == "Redline"
        assert item.quality == "Field-Tested"
        assert item.stattrak is False
        assert item.souvenir is False

    def test_stattrak(self):
        item = resolve_identity("★ StatTrak™ AK-47 | Redline (Field-Tested)")
        assert item.stattrak is True
        assert item.weapon == "AK-47"
        assert item.skin == "Redline"

    def test_souvenir(self):
        item = resolve_identity("Souvenir M4A4 | Howl (Minimal Wear)")
        assert item.souvenir is True
        assert item.weapon == "M4A4"
        assert item.skin == "Howl"
        assert item.quality == "Minimal Wear"

    def test_vanilla_knife(self):
        item = resolve_identity("★ Karambit")
        assert item.weapon == "Karambit"
        assert item.skin == ""
        assert item.quality == ""
        assert item.stattrak is False

    def test_m4a1s(self):
        item = resolve_identity("M4A1-S | Hyper Beast (Factory New)")
        assert item.weapon == "M4A1-S"
        assert item.skin == "Hyper Beast"
        assert item.quality == "Factory New"

    def test_quality_abbreviation(self):
        item = resolve_identity("AK-47 | Redline (FT)")
        assert item.quality == "Field-Tested"

    def test_quality_fn(self):
        item = resolve_identity("M4A1-S | Hyper Beast (FN)")
        assert item.quality == "Factory New"

    def test_reject_sticker(self):
        with pytest.raises(InvalidItemError, match="Not a weapon skin"):
            resolve_identity("Sticker | Katowice 2014")

    def test_reject_agent(self):
        with pytest.raises(InvalidItemError, match="Not a weapon skin"):
            resolve_identity("Agent | Ava")

    def test_reject_graffiti(self):
        with pytest.raises(InvalidItemError, match="Not a weapon skin"):
            resolve_identity("Sealed Graffiti | Welcome to the Clutch")

    def test_reject_music_kit(self):
        with pytest.raises(InvalidItemError, match="Not a weapon skin"):
            resolve_identity("Music Kit | Daniel Sadowski, Crimson Assault")

    def test_unknown_quality(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            item = resolve_identity("AK-47 | Redline (Unknown)")
            assert item.quality == "Field-Tested"  # default
            assert len(w) == 1
            assert "Unknown quality" in str(w[0].message)

    def test_stattrak_knife(self):
        item = resolve_identity("★ StatTrak™ Karambit | Doppler (Factory New)")
        assert item.stattrak is True
        assert item.weapon == "Karambit"
        assert item.skin == "Doppler"
        assert item.quality == "Factory New"


class TestBuildMarketHashName:
    def test_basic(self):
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="Field-Tested")
        assert build_market_hash_name(canon) == "AK-47 | Redline (Field-Tested)"

    def test_stattrak(self):
        canon = CanonicalItem(weapon="AK-47", skin="Redline", quality="FT", stattrak=True)
        name = build_market_hash_name(canon)
        assert "StatTrak™" in name
        assert "AK-47" in name

    def test_knife_star(self):
        canon = CanonicalItem(weapon="Karambit", skin="Doppler", quality="Factory New")
        name = build_market_hash_name(canon)
        assert name.startswith("★")

    def test_vanilla_knife(self):
        canon = CanonicalItem(weapon="Karambit", skin="", quality="")
        name = build_market_hash_name(canon)
        assert "★" in name
        assert "|" not in name
