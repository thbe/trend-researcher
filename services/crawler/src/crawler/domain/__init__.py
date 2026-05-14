"""Crawler domain — pure types and dedup logic, zero I/O."""

from crawler.domain.dedup import dedup_key, is_duplicate
from crawler.domain.raw_item import RawItem

__all__ = ["RawItem", "dedup_key", "is_duplicate"]
