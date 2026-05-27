"""Tests for :func:`api.dependencies.get_active_department` + :func:`require_role`.

These dependencies are exercised indirectly by `/api/departments` tests, but
the matrix that matters for downstream phases (10-02 ai_config / business_cases
scoping) is the one tested here: header missing, header for non-member, header
for non-existent dept, superadmin override path, role-gating, and the
fallback-to-oldest-membership behaviour for non-superadmin clients.

Pattern: we register a couple of throwaway routes on the in-process app inside
a fixture, exercise them via the existing client factory, then pop them off
the router so the rest of the suite is unaffected.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import Depends

from api.dependencies import (
    ActiveDepartment,
    get_active_department,
    require_role,
)
from api.main import app

from .conftest import SeededDb


pytestmark = pytest.mark.asyncio


_PROBE_PATH = "/api/_test/active-dept"
_LEAD_ONLY_PATH = "/api/_test/lead-only"


@pytest_asyncio.fixture(autouse=True)
async def _register_probe_routes() -> AsyncIterator[None]:
    """Add probe routes for the duration of this module, then remove them.

    ``get_active_department`` is normally consumed by per-dept routes that
    also hit the DB for their primary work; we want to assert dependency
    behaviour in isolation, so these probes just echo the resolved
    ``ActiveDepartment`` (and gate via :func:`require_role` for the second).
    """

    async def _echo(ad: ActiveDepartment = Depends(get_active_department)) -> dict:
        return {
            "department_id": ad.department.id,
            "slug": ad.department.slug,
            "role": ad.role,
            "is_superadmin_override": ad.is_superadmin_override,
        }

    async def _lead_only(
        ad: ActiveDepartment = Depends(require_role("dept_lead")),
    ) -> dict:
        return {"role": ad.role, "slug": ad.department.slug}

    app.add_api_route(_PROBE_PATH, _echo, methods=["GET"])
    app.add_api_route(_LEAD_ONLY_PATH, _lead_only, methods=["GET"])

    try:
        yield
    finally:
        app.router.routes = [
            r
            for r in app.router.routes
            if getattr(r, "path", None) not in {_PROBE_PATH, _LEAD_ONLY_PATH}
        ]


async def test_superadmin_without_header_returns_400(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Superadmin MUST set ``X-Active-Department`` explicitly (400 otherwise)."""

    client = await make_authed_client(seeded_db.superadmin)
    response = await client.get(_PROBE_PATH)
    assert response.status_code == 400
    assert "X-Active-Department" in response.json()["detail"]


async def test_superadmin_with_header_gets_override(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Superadmin without explicit membership → synthesised dept_lead override."""

    client = await make_authed_client(
        seeded_db.superadmin, active_dept=seeded_db.other_dept_id
    )
    response = await client.get(_PROBE_PATH)
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "dept_lead"
    assert body["is_superadmin_override"] is True
    assert body["slug"] == "other"


async def test_non_superadmin_falls_back_to_oldest_membership(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """``analyst_a`` belongs to Default (older) + Other → resolves to Default."""

    client = await make_authed_client(seeded_db.analyst_a)
    response = await client.get(_PROBE_PATH)
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "default"
    assert body["role"] == "analyst"
    assert body["is_superadmin_override"] is False


async def test_non_member_with_header_returns_403(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """``lead_a`` is not in Other → header pointing there → 403."""

    client = await make_authed_client(
        seeded_db.lead_a, active_dept=seeded_db.other_dept_id
    )
    response = await client.get(_PROBE_PATH)
    assert response.status_code == 403


async def test_unknown_department_header_returns_404(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """A header with a syntactically-valid UUID that doesn't exist → 404."""

    client = await make_authed_client(
        seeded_db.superadmin,
        active_dept="00000000-0000-0000-0000-0000000000ff",
    )
    response = await client.get(_PROBE_PATH)
    assert response.status_code == 404


async def test_require_role_blocks_analyst(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """``analyst_a`` against a dept_lead-gated route → 403."""

    client = await make_authed_client(
        seeded_db.analyst_a, active_dept=seeded_db.default_dept_id
    )
    response = await client.get(_LEAD_ONLY_PATH)
    assert response.status_code == 403
    assert "dept_lead" in response.json()["detail"]


async def test_require_role_allows_dept_lead(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Actual dept_lead passes the gate."""

    client = await make_authed_client(
        seeded_db.lead_a, active_dept=seeded_db.default_dept_id
    )
    response = await client.get(_LEAD_ONLY_PATH)
    assert response.status_code == 200
    assert response.json()["role"] == "dept_lead"


async def test_require_role_bypassed_by_superadmin(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Superadmin always passes role gates (via ``is_superadmin_override``)."""

    client = await make_authed_client(
        seeded_db.superadmin, active_dept=seeded_db.other_dept_id
    )
    response = await client.get(_LEAD_ONLY_PATH)
    assert response.status_code == 200
    assert response.json()["role"] == "dept_lead"
