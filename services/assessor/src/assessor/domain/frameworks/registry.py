"""Framework registry — central dispatch table for the assessment pipeline.

Single source of truth for the three frameworks shipped in v1. Look-ups by
``key`` are pure-Python and free; look-ups by ``id`` hit ``assessment_frameworks``
once to resolve the key, then dispatch in-process.

The ``all_definitions`` helper feeds ``packages/core/src/core/seed.py``
(see plan 10-03 T03) so framework metadata stays in ONE place — the registry —
and the seed function upserts it on every API startup.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from assessor.domain.frameworks.base import Framework, FrameworkDefinition
from assessor.domain.frameworks.pestle import PESTLE_FRAMEWORK_ID, PestleFramework
from assessor.domain.frameworks.swot import SWOT_FRAMEWORK_ID, SwotFramework
from assessor.domain.frameworks.verdict import VERDICT_FRAMEWORK_ID, VerdictFramework

# Eager instantiation — frameworks are stateless singletons.
_VERDICT = VerdictFramework()
_SWOT = SwotFramework()
_PESTLE = PestleFramework()

FRAMEWORKS: dict[str, Framework] = {
    "verdict": _VERDICT,
    "swot": _SWOT,
    "pestle": _PESTLE,
}

# Inverse mapping for id → framework lookup without a DB round-trip when the
# id is one of the well-known seeded IDs.
_BY_ID: dict[str, Framework] = {
    VERDICT_FRAMEWORK_ID: _VERDICT,
    SWOT_FRAMEWORK_ID: _SWOT,
    PESTLE_FRAMEWORK_ID: _PESTLE,
}


class FrameworkNotFoundError(LookupError):
    """Raised when a key or id does not match any registered framework."""


def get_by_key(key: str) -> Framework:
    """Return the framework registered under ``key``.

    Raises ``FrameworkNotFoundError`` if unknown.
    """
    try:
        return FRAMEWORKS[key]
    except KeyError as exc:
        raise FrameworkNotFoundError(f"unknown framework key: {key!r}") from exc


async def get_by_id(fw_id: str, session: AsyncSession) -> Framework:
    """Resolve ``fw_id`` (UUID string) to a framework.

    Fast path: well-known seeded IDs are matched in-process.
    Slow path: any other ID (e.g. operator-added framework in a future phase)
    falls back to a single SELECT on ``assessment_frameworks`` to map id → key.
    """
    cached = _BY_ID.get(fw_id)
    if cached is not None:
        return cached

    row = await session.execute(
        text("SELECT key FROM assessment_frameworks WHERE id = :id"),
        {"id": fw_id},
    )
    record = row.first()
    if record is None:
        raise FrameworkNotFoundError(f"no assessment_framework with id={fw_id!r}")
    return get_by_key(record[0])


def all_definitions() -> list[FrameworkDefinition]:
    """Return seed metadata for every registered framework.

    Consumed by ``core.seed.seed_frameworks`` (plan 10-03 T03).
    """
    return [fw.definition() for fw in FRAMEWORKS.values()]


def all_frameworks() -> Iterable[Framework]:
    return FRAMEWORKS.values()


__all__ = [
    "FRAMEWORKS",
    "FrameworkNotFoundError",
    "all_definitions",
    "all_frameworks",
    "get_by_id",
    "get_by_key",
]
