"""Deterministic Chinese script normalization for workflow text identity."""

import unicodedata

from opencc import OpenCC

_TRADITIONAL_TO_SIMPLIFIED = OpenCC("t2s")


def normalize_chinese_script(text: str) -> str:
    """Fold Unicode compatibility forms and Traditional Chinese to Simplified."""
    return _TRADITIONAL_TO_SIMPLIFIED.convert(
        unicodedata.normalize("NFKC", str(text)),
    )
