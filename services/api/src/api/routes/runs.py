"""Runs route stub (T02).

The actual ``GET /runs`` endpoint lands in T04; this file exists now so
``api.main`` can import the router at app construction time without import
errors. Keeping the stub explicit avoids ``import-time AttributeError`` and
makes the T04 diff purely additive (drop-in endpoint on the existing router).
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


__all__ = ["router"]
