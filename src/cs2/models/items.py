from __future__ import annotations

from pydantic import BaseModel, field_validator


class Sticker(BaseModel):
    name: str
    slot: int  # 0-4
    wear: float = 0.0  # 0.0 = pristine, 1.0 = scraped off


class CanonicalItem(BaseModel):
    weapon: str
    skin: str
    quality: str
    stattrak: bool = False
    souvenir: bool = False


class ExactInstance(BaseModel):
    canonical: CanonicalItem
    float_value: float
    paint_seed: int
    stickers: list[Sticker] = []
    stattrak_kills: int | None = None

    @field_validator("stattrak_kills")
    @classmethod
    def validate_stattrak_kills(cls, v: int | None, info) -> int | None:
        canonical = info.data.get("canonical")
        if canonical is None:
            return v
        is_st = (
            canonical.get("stattrak", False)
            if isinstance(canonical, dict)
            else getattr(canonical, "stattrak", False)
        )
        if v is not None and not is_st:
            raise ValueError("stattrak_kills must be None for non-StatTrak items")
        return v
