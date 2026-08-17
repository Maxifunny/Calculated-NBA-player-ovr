"""Name normalization used to join NBA / Basketball-Reference rows with 2K cards."""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz, process

_SUFFIXES = (
    " jr",
    " sr",
    " iii",
    " ii",
    " iv",
    " v",
)

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def normalize_name(name: str | None) -> str:
    """Lowercase, strip accents/punctuation/generational suffixes."""
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(name))
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = ascii_only.lower().replace(".", "")
    cleaned = _NON_ALNUM.sub(" ", cleaned)
    cleaned = " ".join(cleaned.split())
    for suffix in _SUFFIXES:
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].rstrip()
    return cleaned


def best_name_match(
    query: str,
    candidates: list[str],
    score_cutoff: int = 90,
) -> tuple[str, float] | None:
    """Return the best fuzzy match above ``score_cutoff``, or None."""
    if not query or not candidates:
        return None
    result = process.extractOne(
        query,
        candidates,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=score_cutoff,
    )
    if result is None:
        return None
    match, score, _index = result
    return match, float(score)
