"""Tests for ``/api/departments`` + member-management endpoints (Phase 10).

Covers the auth matrix documented in :mod:`api.routes.departments`:

1. ``GET /api/departments`` — non-superadmin sees only memberships;
   superadmin sees both seeded departments.
2. ``POST /api/departments`` — 201 for superadmin, 403 for analyst,
   409 on duplicate slug.
3. ``DELETE /api/departments/{default}`` — 409 (the Default seed is
   protected by slug).
4. ``GET /api/departments/{other}`` as ``lead_a`` → 403 (non-member,
   non-superadmin).
5. ``PUT /api/departments/{default}/members/{lead_a}`` to demote to
   ``analyst`` → 409 (would leave dept with zero leads).
6. ``DELETE /api/departments/{default}/members/{lead_a}`` → 409 (same
   last-lead protection on the remove path).
7. ``GET /api/departments/{default}/members`` as ``analyst_a`` → 403
   (analyst is not dept_lead and not superadmin).

DB-touching; skip-gated via ``seeded_db``.
"""

from __future__ import annotations

import uuid

import pytest

from .conftest import SeededDb


pytestmark = pytest.mark.asyncio


async def test_list_filtered_for_non_superadmin(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """``lead_a`` is only in Default → should see exactly 1 department."""

    client = await make_authed_client(seeded_db.lead_a)
    response = await client.get("/api/departments")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["departments"][0]["slug"] == "default"


async def test_list_shows_all_for_superadmin(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Superadmin sees both seeded departments regardless of memberships."""

    client = await make_authed_client(seeded_db.superadmin)
    response = await client.get("/api/departments")
    assert response.status_code == 200
    slugs = {d["slug"] for d in response.json()["departments"]}
    assert slugs == {"default", "other"}


async def test_create_requires_superadmin(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Analyst attempt → 403; superadmin attempt → 201."""

    analyst_client = await make_authed_client(seeded_db.analyst_a)
    forbidden = await analyst_client.post(
        "/api/departments",
        json={"name": "Marketing", "slug": "marketing"},
    )
    assert forbidden.status_code == 403

    super_client = await make_authed_client(seeded_db.superadmin)
    created = await super_client.post(
        "/api/departments",
        json={"name": "Marketing", "slug": "marketing"},
    )
    assert created.status_code == 201
    assert created.json()["slug"] == "marketing"


async def test_create_duplicate_slug_returns_409(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Re-creating the Default slug → 409 (unique constraint trip)."""

    client = await make_authed_client(seeded_db.superadmin)
    response = await client.post(
        "/api/departments",
        json={"name": "Default Two", "slug": "default"},
    )
    assert response.status_code == 409


async def test_delete_default_department_returns_409(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """The Default seed must never be deletable (handler enforces by slug)."""

    client = await make_authed_client(seeded_db.superadmin)
    response = await client.delete(
        f"/api/departments/{seeded_db.default_dept_id}"
    )
    assert response.status_code == 409
    assert "Default" in response.json()["detail"]


async def test_get_other_department_as_non_member_returns_403(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """``lead_a`` is not a member of Other → 403."""

    client = await make_authed_client(seeded_db.lead_a)
    response = await client.get(
        f"/api/departments/{seeded_db.other_dept_id}"
    )
    assert response.status_code == 403


async def test_demote_last_lead_returns_409(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Default has exactly one dept_lead (``lead_a``). Demoting → 409."""

    client = await make_authed_client(seeded_db.superadmin)
    lead_user_id = seeded_db.user_ids[seeded_db.lead_a]
    response = await client.put(
        f"/api/departments/{seeded_db.default_dept_id}/members/{lead_user_id}",
        json={"role": "analyst"},
    )
    assert response.status_code == 409


async def test_remove_last_lead_returns_409(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Same last-lead invariant on the DELETE path."""

    client = await make_authed_client(seeded_db.superadmin)
    lead_user_id = seeded_db.user_ids[seeded_db.lead_a]
    response = await client.delete(
        f"/api/departments/{seeded_db.default_dept_id}/members/{lead_user_id}"
    )
    assert response.status_code == 409


async def test_list_members_requires_lead_or_superadmin(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Analyst tries to read the membership roster → 403."""

    client = await make_authed_client(seeded_db.analyst_a)
    response = await client.get(
        f"/api/departments/{seeded_db.default_dept_id}/members"
    )
    assert response.status_code == 403


async def test_add_member_to_nonexistent_user_returns_404(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """POST /members with an unknown user_id → 404."""

    client = await make_authed_client(seeded_db.superadmin)
    response = await client.post(
        f"/api/departments/{seeded_db.default_dept_id}/members",
        json={"user_id": str(uuid.uuid4()), "role": "viewer"},
    )
    assert response.status_code == 404
