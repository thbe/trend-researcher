"""Bootstrap helpers — idempotent seed routines run on app startup.

Currently exposes:
- ``seed_frameworks`` — upserts the assessment_frameworks table from the
  framework registry so metadata changes (new ``prompt_version``, tweaked
  ``json_schema``, edited ``description``) propagate without a new migration.

Each function is safe to invoke on every startup; functions return a small
summary dict the lifespan handler logs.

The split between *migration seed* (cold-start) and *bootstrap seed* (ongoing)
is intentional:
- The migration row gets the schema into place on a fresh DB so foreign keys
  pointing to ``assessment_frameworks`` (department_frameworks, business_cases,
  assessment_jobs) have something to reference.
- This bootstrap step then keeps that table in sync with code on every restart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, Protocol

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_log = structlog.get_logger(__name__)


class _FrameworkDef(Protocol):
    """Structural type matching ``assessor.domain.frameworks.base.FrameworkDefinition``.

    Declared as a Protocol so ``core`` does not depend on ``assessor`` (would
    invert the established dep direction). The API lifespan injects the
    concrete list via ``registry.all_definitions()``.
    """

    key: str
    name: str
    description: str
    display_component: str
    prompt_version: str
    json_schema: dict


@dataclass
class SeedResult:
    """Summary returned by ``seed_frameworks`` for logging."""

    inserted: list[str]
    updated: list[str]
    unchanged: list[str]

    def summary(self) -> str:
        return (
            f"{len(self.inserted)} inserted, "
            f"{len(self.updated)} updated, "
            f"{len(self.unchanged)} unchanged"
        )


async def seed_frameworks(
    session: AsyncSession, definitions: Iterable[_FrameworkDef]
) -> SeedResult:
    """Upsert framework metadata from ``definitions`` into ``assessment_frameworks``.

    For each definition:
      - if no row exists with that ``key`` → INSERT.
      - if a row exists and every mutable field matches → leave it alone.
      - otherwise → UPDATE the row's ``name`` / ``description`` /
        ``display_component`` / ``json_schema`` / ``prompt_version`` and bump
        ``updated_at``.

    Idempotency: running this function twice back-to-back results in
    ``unchanged`` covering every definition on the second call (acceptance
    criterion for plan 10-03 T03).

    The function COMMITS its own changes so the caller's session can stay open
    for further seed steps. (Pattern matches ``ensure_seed_user``.)
    """
    defs = list(definitions)
    if not defs:
        return SeedResult(inserted=[], updated=[], unchanged=[])

    keys = [d.key for d in defs]
    existing_rows = await session.execute(
        text(
            """
            SELECT key, name, description, display_component,
                   json_schema, prompt_version
              FROM assessment_frameworks
             WHERE key = ANY(:keys)
            """
        ),
        {"keys": keys},
    )
    existing = {row.key: row for row in existing_rows.all()}

    inserted: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []

    for d in defs:
        current = existing.get(d.key)
        if current is None:
            await session.execute(
                text(
                    """
                    INSERT INTO assessment_frameworks
                        (key, name, description, display_component,
                         json_schema, prompt_version)
                    VALUES
                        (:key, :name, :description, :display_component,
                         (:json_schema)::jsonb, :prompt_version)
                    """
                ),
                {
                    "key": d.key,
                    "name": d.name,
                    "description": d.description,
                    "display_component": d.display_component,
                    "json_schema": json.dumps(d.json_schema),
                    "prompt_version": d.prompt_version,
                },
            )
            inserted.append(d.key)
            continue

        # Compare every mutable field. JSONB comes back as a Python dict from
        # asyncpg so direct equality works.
        if (
            current.name == d.name
            and (current.description or "") == (d.description or "")
            and current.display_component == d.display_component
            and current.json_schema == d.json_schema
            and current.prompt_version == d.prompt_version
        ):
            unchanged.append(d.key)
            continue

        await session.execute(
            text(
                """
                UPDATE assessment_frameworks
                   SET name = :name,
                       description = :description,
                       display_component = :display_component,
                       json_schema = (:json_schema)::jsonb,
                       prompt_version = :prompt_version,
                       updated_at = now()
                 WHERE key = :key
                """
            ),
            {
                "key": d.key,
                "name": d.name,
                "description": d.description,
                "display_component": d.display_component,
                "json_schema": json.dumps(d.json_schema),
                "prompt_version": d.prompt_version,
            },
        )
        updated.append(d.key)

    await session.commit()

    result = SeedResult(inserted=inserted, updated=updated, unchanged=unchanged)
    _log.info(
        "core.seed.frameworks",
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
    )
    return result


__all__ = ["SeedResult", "seed_frameworks"]
