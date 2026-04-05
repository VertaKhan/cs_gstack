from __future__ import annotations

import re

from cs2.models.items import CanonicalItem

# Quality name normalization
QUALITY_ALIASES: dict[str, str] = {
    "FN": "Factory New",
    "MW": "Minimal Wear",
    "FT": "Field-Tested",
    "WW": "Well-Worn",
    "BS": "Battle-Scarred",
    "Factory New": "Factory New",
    "Minimal Wear": "Minimal Wear",
    "Field-Tested": "Field-Tested",
    "Well-Worn": "Well-Worn",
    "Battle-Scarred": "Battle-Scarred",
}

# Items that are NOT weapon skins
REJECTED_PREFIXES = [
    "Sticker |",
    "Sealed Graffiti |",
    "Graffiti |",
    "Music Kit |",
    "Patch |",
    "Agent |",
    "Pin |",
    "Collectible |",
]

# Pattern: optional star + optional StatTrak/Souvenir + weapon | skin (quality)
ITEM_PATTERN = re.compile(
    r"^"
    r"(?:★\s*)?"                          # optional star for knives/gloves
    r"(?:(?P<stattrak>StatTrak™)\s+)?"    # optional StatTrak
    r"(?:(?P<souvenir>Souvenir)\s+)?"     # optional Souvenir
    r"(?P<weapon>[^|]+?)"                 # weapon name (non-greedy)
    r"(?:\s*\|\s*(?P<skin>[^(]+?))?"      # optional skin after pipe
    r"(?:\s*\((?P<quality>[^)]+)\))?"     # optional quality in parens
    r"\s*$"
)


class InvalidItemError(Exception):
    """Raised when the item cannot be identified as a CS2 weapon skin."""
    pass


def resolve_identity(item_name: str) -> CanonicalItem:
    """Parse item name string into canonical identity.

    Handles formats like:
    - "AK-47 | Redline (Field-Tested)"
    - "★ StatTrak™ Karambit | Doppler (Factory New)"
    - "★ Karambit" (vanilla knife)
    - "M4A1-S | Hyper Beast (FN)"
    """
    name = item_name.strip()

    # Reject non-weapon items
    for prefix in REJECTED_PREFIXES:
        if name.startswith(prefix) or name.startswith(f"★ {prefix}"):
            raise InvalidItemError(f"Not a weapon skin: {name}")

    match = ITEM_PATTERN.match(name)
    if not match:
        raise InvalidItemError(f"Cannot parse item name: {name}")

    weapon = match.group("weapon").strip()
    skin = (match.group("skin") or "").strip()
    quality_raw = (match.group("quality") or "").strip()
    stattrak = match.group("stattrak") is not None
    souvenir = match.group("souvenir") is not None

    # Normalize quality
    quality = _normalize_quality(quality_raw)

    # Vanilla knives have no skin and no quality
    if not skin and not quality:
        quality = ""  # vanilla

    return CanonicalItem(
        weapon=weapon,
        skin=skin,
        quality=quality,
        stattrak=stattrak,
        souvenir=souvenir,
    )


def _normalize_quality(raw: str) -> str:
    """Normalize quality string using aliases."""
    if not raw:
        return ""
    normalized = QUALITY_ALIASES.get(raw)
    if normalized:
        return normalized
    # Try case-insensitive match
    for alias, full in QUALITY_ALIASES.items():
        if raw.lower() == alias.lower():
            return full
    # Unknown quality — warn but default to Field-Tested
    import warnings
    warnings.warn(f"Unknown quality '{raw}', defaulting to Field-Tested")
    return "Field-Tested"


def build_market_hash_name(canonical: CanonicalItem) -> str:
    """Reconstruct the Steam market_hash_name from canonical identity."""
    parts = []

    # Knives/gloves get the star
    knife_keywords = [
        "Karambit", "Bayonet", "Butterfly", "Flip", "Gut", "Huntsman",
        "Falchion", "Shadow Daggers", "Bowie", "Navaja", "Stiletto",
        "Talon", "Ursus", "Classic", "Paracord", "Survival", "Nomad",
        "Skeleton", "Kukri",
        "Sport Gloves", "Driver Gloves", "Hand Wraps", "Moto Gloves",
        "Specialist Gloves", "Hydra Gloves", "Broken Fang Gloves",
    ]
    is_knife = any(kw in canonical.weapon for kw in knife_keywords)

    if is_knife:
        parts.append("★")

    if canonical.stattrak:
        parts.append("StatTrak™")
    if canonical.souvenir:
        parts.append("Souvenir")

    parts.append(canonical.weapon)

    name = " ".join(parts)
    if canonical.skin:
        name += f" | {canonical.skin}"
    if canonical.quality:
        name += f" ({canonical.quality})"
    return name
