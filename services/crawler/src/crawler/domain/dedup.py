"""Pure-Python dedup primitives for the ingest pipeline.

`dedup_key` produces a deterministic normalized form of a title — useful as
a cheap pre-filter (e.g. trigram index in the repo) before the more
expensive fuzzy comparison.

`is_duplicate` decides whether two titles refer to the same topic, using
rapidfuzz's `token_set_ratio` (order-insensitive, set-based, robust to
trailing punctuation and reordered words).

REQ ING-007 fixes the default threshold at 85.

This module has ZERO I/O — no DB, no HTTP, no env, no logging. It must stay
pure so adapters can be swapped freely.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")
_WHITESPACE_RE = re.compile(r"\s+")


def dedup_key(title: str) -> str:
    """Normalize a title to a deterministic key for cheap pre-filtering.

    Steps: lowercase, normalize all whitespace to single spaces,
    strip non-alphanumerics (keeping spaces), trim.

    Whitespace normalization happens BEFORE punctuation stripping so that
    e.g. tabs aren't silently removed (which would glue adjacent words
    together with no separator).
    """
    lowered = title.lower()
    spaced = _WHITESPACE_RE.sub(" ", lowered)
    no_punct = _NON_ALNUM_RE.sub("", spaced)
    return no_punct.strip()


def is_duplicate(
    new_title: str,
    existing_title: str,
    threshold: int = 85,
) -> bool:
    """Return True iff `new_title` matches `existing_title` at or above `threshold`.

    Uses `rapidfuzz.fuzz.token_set_ratio` on the normalized (`dedup_key`)
    forms of both titles. The default threshold of 85 matches REQ ING-007.
    """
    score = fuzz.token_set_ratio(dedup_key(new_title), dedup_key(existing_title))
    return score >= threshold
