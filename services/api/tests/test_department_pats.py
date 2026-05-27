"""Tests for ``/api/departments/{dept_id}/pats`` (Plan 10-02 T09).

Covers the management endpoints (mint / list / revoke) and their RBAC
matrix. The runtime auth path (``require_dept_pat`` on the internal
crawl route) is exercised in :mod:`test_internal_dept_crawl`.

DB-touching; skip-gated via the :func:`seeded_db` fixture.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

import core
from core.models import DepartmentPAT

from .conftest import SeededDb


pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------
# Mint (POST)
# --------------------------------------------------------------------------


async def test_lead_can_mint_pat_plaintext_returned_once(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Dept_lead mints a PAT → 201, response includes plaintext token,
    DB row stores only the SHA-256 hash (not the plaintext)."""

    client = await make_authed_client(seeded_db.lead_a)
    response = await client.post(
        f"/api/departments/{seeded_db.default_dept_id}/pats",
        json={"name": "Cloud Scheduler"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Cloud Scheduler"
    assert "token" in body and body["token"]
    plaintext = body["token"]

    # Verify the DB row holds the hash, NOT the plaintext.
    engine = core.get_engine()
    sm = core.get_sessionmaker(engine)
    async with sm() as session:
        rows = (
            await session.execute(
                select(DepartmentPAT).where(
                    DepartmentPAT.department_id == seeded_db.default_dept_id
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].token_hash != plaintext
    assert len(rows[0].token_hash) == 64  # sha256 hex


async def test_superadmin_can_mint_pat_in_any_dept(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Superadmin is allowed even without explicit dept membership."""

    client = await make_authed_client(seeded_db.superadmin)
    response = await client.post(
        f"/api/departments/{seeded_db.other_dept_id}/pats",
        json={"name": "superadmin-mint"},
    )
    assert response.status_code == 201


async def test_analyst_cannot_mint_pat(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Analyst membership is NOT enough — only dept_lead+ may mint."""

    client = await make_authed_client(seeded_db.analyst_a)
    response = await client.post(
        f"/api/departments/{seeded_db.default_dept_id}/pats",
        json={"name": "should-fail"},
    )
    assert response.status_code == 403


async def test_non_member_cannot_mint_pat(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """``lead_a`` is not a member of Other → 403 even though they are a
    dept_lead elsewhere."""

    client = await make_authed_client(seeded_db.lead_a)
    response = await client.post(
        f"/api/departments/{seeded_db.other_dept_id}/pats",
        json={"name": "should-fail"},
    )
    assert response.status_code == 403


async def test_mint_pat_unknown_dept_returns_404(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Unknown dept_id → 404 (helper short-circuits before auth check)."""

    client = await make_authed_client(seeded_db.superadmin)
    response = await client.post(
        f"/api/departments/{uuid.uuid4()}/pats",
        json={"name": "ghost"},
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# List (GET) — viewer+ may read; plaintext / hash NEVER leak.
# --------------------------------------------------------------------------


async def test_list_includes_metadata_but_never_plaintext_or_hash(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """GET /pats returns id/name/created_by/created_at/last_used_at/
    revoked_at — but explicitly no ``token`` and no ``token_hash``."""

    lead_client = await make_authed_client(seeded_db.lead_a)
    mint = await lead_client.post(
        f"/api/departments/{seeded_db.default_dept_id}/pats",
        json={"name": "listed"},
    )
    assert mint.status_code == 201

    listing = await lead_client.get(
        f"/api/departments/{seeded_db.default_dept_id}/pats"
    )
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    pat = body["pats"][0]
    assert pat["name"] == "listed"
    assert "token" not in pat
    assert "token_hash" not in pat
    # Required metadata IS present.
    for key in ("id", "name", "created_by", "created_at"):
        assert key in pat


async def test_analyst_can_list_pats_viewer_can_too(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """``_assert_member_or_superadmin`` = viewer+; analyst (viewer+) sees
    the list."""

    super_client = await make_authed_client(seeded_db.superadmin)
    await super_client.post(
        f"/api/departments/{seeded_db.default_dept_id}/pats",
        json={"name": "seed"},
    )
    analyst_client = await make_authed_client(seeded_db.analyst_a)
    response = await analyst_client.get(
        f"/api/departments/{seeded_db.default_dept_id}/pats"
    )
    assert response.status_code == 200
    assert response.json()["total"] >= 1


async def test_non_member_cannot_list_pats(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """``viewer_b`` is not a member of Default → 403."""

    client = await make_authed_client(seeded_db.viewer_b)
    response = await client.get(
        f"/api/departments/{seeded_db.default_dept_id}/pats"
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------
# Revoke (DELETE) — soft-delete; idempotent; wrong-dept = 404 (anti-tamper).
# --------------------------------------------------------------------------


async def test_lead_can_revoke_pat_sets_revoked_at(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """DELETE returns 204; the DB row remains but ``revoked_at`` is set."""

    client = await make_authed_client(seeded_db.lead_a)
    mint = await client.post(
        f"/api/departments/{seeded_db.default_dept_id}/pats",
        json={"name": "to-revoke"},
    )
    pat_id = mint.json()["id"]
    revoke = await client.delete(
        f"/api/departments/{seeded_db.default_dept_id}/pats/{pat_id}"
    )
    assert revoke.status_code == 204

    engine = core.get_engine()
    sm = core.get_sessionmaker(engine)
    async with sm() as session:
        pat = await session.get(DepartmentPAT, pat_id)
    assert pat is not None
    assert pat.revoked_at is not None


async def test_revoke_is_idempotent(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Re-revoking a revoked PAT still returns 204."""

    client = await make_authed_client(seeded_db.lead_a)
    mint = await client.post(
        f"/api/departments/{seeded_db.default_dept_id}/pats",
        json={"name": "double-revoke"},
    )
    pat_id = mint.json()["id"]
    first = await client.delete(
        f"/api/departments/{seeded_db.default_dept_id}/pats/{pat_id}"
    )
    second = await client.delete(
        f"/api/departments/{seeded_db.default_dept_id}/pats/{pat_id}"
    )
    assert first.status_code == 204
    assert second.status_code == 204


async def test_revoke_wrong_dept_path_returns_404(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Anti-tamper: a PAT minted under Default cannot be revoked via the
    Other dept's path even by a superadmin."""

    super_client = await make_authed_client(seeded_db.superadmin)
    mint = await super_client.post(
        f"/api/departments/{seeded_db.default_dept_id}/pats",
        json={"name": "wrong-dept-revoke"},
    )
    pat_id = mint.json()["id"]
    response = await super_client.delete(
        f"/api/departments/{seeded_db.other_dept_id}/pats/{pat_id}"
    )
    assert response.status_code == 404


async def test_analyst_cannot_revoke_pat(
    seeded_db: SeededDb, make_authed_client
) -> None:
    """Analyst membership is NOT enough — only dept_lead+ may revoke."""

    lead_client = await make_authed_client(seeded_db.lead_a)
    mint = await lead_client.post(
        f"/api/departments/{seeded_db.default_dept_id}/pats",
        json={"name": "analyst-cant-touch"},
    )
    pat_id = mint.json()["id"]
    analyst_client = await make_authed_client(seeded_db.analyst_a)
    response = await analyst_client.delete(
        f"/api/departments/{seeded_db.default_dept_id}/pats/{pat_id}"
    )
    assert response.status_code == 403


async def test_revoke_unknown_pat_returns_404(
    seeded_db: SeededDb, make_authed_client
) -> None:
    client = await make_authed_client(seeded_db.lead_a)
    response = await client.delete(
        f"/api/departments/{seeded_db.default_dept_id}/pats/{uuid.uuid4()}"
    )
    assert response.status_code == 404
