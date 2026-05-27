"""Tests for the per-department internal crawl endpoint (Plan 10-02 T09).

Validates the runtime auth contract for
``POST /api/internal/departments/{dept_slug}/crawl``:

1. A PAT minted under Default authorises a crawl against ``/default``.
2. The SAME PAT against ``/other`` → 403 (slug mismatch).
3. Revoking the PAT then re-using its plaintext → 403.
4. ``last_used_at`` is bumped on successful auth.
5. The legacy global env-PAT route (``POST /api/internal/crawl``) still
   works untouched (ARC-001 preserved).

The actual crawler is mocked out at module level — these tests exercise
the auth/scope path, not the source-fetch path (that's covered by the
crawler suite).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

import core
from api.routes import internal as internal_routes
from core.models import DepartmentPAT

from .conftest import SeededDb


pytestmark = pytest.mark.asyncio


_FAKE_STATS = {"crawl_run_id": "fake-run-id", "totals": {}}


@pytest.fixture(autouse=True)
def _mock_crawl(monkeypatch: pytest.MonkeyPatch):
    """Replace ``_run_crawl_isolated`` with a stub so tests never hit the
    network or build a real crawler engine. We record the kwargs the route
    passed so we can assert dept-scoping was forwarded correctly.
    """
    calls: list[dict] = []

    async def _stub(department_id=None):
        calls.append({"department_id": department_id})
        return dict(_FAKE_STATS)

    monkeypatch.setattr(internal_routes, "_run_crawl_isolated", _stub)
    return calls


async def _mint_pat(client, dept_id: str, name: str = "test-pat") -> str:
    """Helper: mint a PAT via the management endpoint and return plaintext."""

    response = await client.post(
        f"/api/departments/{dept_id}/pats",
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()["token"]


# --------------------------------------------------------------------------
# Happy path: PAT for Default → /default succeeds.
# --------------------------------------------------------------------------


async def test_dept_pat_authorises_matching_slug(
    seeded_db: SeededDb, make_authed_client, _mock_crawl
) -> None:
    """Lead mints PAT under Default → POST /internal/departments/default/
    crawl with that bearer → 200 + dept-scoped crawl invoked."""

    lead_client = await make_authed_client(seeded_db.lead_a)
    plaintext = await _mint_pat(lead_client, seeded_db.default_dept_id)

    # Use a clean client (no session cookie) so we exercise the PAT path,
    # not the session-cookie path.
    from httpx import ASGITransport, AsyncClient

    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {plaintext}"},
    ) as bearer_client:
        response = await bearer_client.post(
            "/api/internal/departments/default/crawl"
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["department"] == "default"
    # Crawl was invoked with the dept's id.
    assert len(_mock_crawl) == 1
    assert str(_mock_crawl[0]["department_id"]) == seeded_db.default_dept_id


# --------------------------------------------------------------------------
# Slug mismatch → 403, crawl NOT invoked.
# --------------------------------------------------------------------------


async def test_dept_pat_rejects_wrong_slug(
    seeded_db: SeededDb, make_authed_client, _mock_crawl
) -> None:
    """PAT minted under Default → POST against /other → 403."""

    super_client = await make_authed_client(seeded_db.superadmin)
    plaintext = await _mint_pat(
        super_client, seeded_db.default_dept_id, name="wrong-slug-pat"
    )
    from httpx import ASGITransport, AsyncClient

    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {plaintext}"},
    ) as bearer_client:
        response = await bearer_client.post(
            "/api/internal/departments/other/crawl"
        )

    assert response.status_code == 403
    assert "department" in response.json()["detail"].lower()
    # No crawl was invoked.
    assert _mock_crawl == []


# --------------------------------------------------------------------------
# Revoked PAT cannot authenticate.
# --------------------------------------------------------------------------


async def test_revoked_dept_pat_rejected(
    seeded_db: SeededDb, make_authed_client, _mock_crawl
) -> None:
    """Mint → revoke → reuse plaintext → 403 (no auth row matches)."""

    lead_client = await make_authed_client(seeded_db.lead_a)
    mint_response = await lead_client.post(
        f"/api/departments/{seeded_db.default_dept_id}/pats",
        json={"name": "to-revoke"},
    )
    assert mint_response.status_code == 201
    plaintext = mint_response.json()["token"]
    pat_id = mint_response.json()["id"]

    revoke = await lead_client.delete(
        f"/api/departments/{seeded_db.default_dept_id}/pats/{pat_id}"
    )
    assert revoke.status_code == 204

    from httpx import ASGITransport, AsyncClient

    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {plaintext}"},
    ) as bearer_client:
        response = await bearer_client.post(
            "/api/internal/departments/default/crawl"
        )

    assert response.status_code == 403
    assert _mock_crawl == []


# --------------------------------------------------------------------------
# last_used_at is bumped on successful auth.
# --------------------------------------------------------------------------


async def test_successful_auth_bumps_last_used_at(
    seeded_db: SeededDb, make_authed_client, _mock_crawl
) -> None:
    """First successful crawl populates ``last_used_at`` (was NULL)."""

    lead_client = await make_authed_client(seeded_db.lead_a)
    mint_response = await lead_client.post(
        f"/api/departments/{seeded_db.default_dept_id}/pats",
        json={"name": "last-used-test"},
    )
    plaintext = mint_response.json()["token"]
    pat_id = mint_response.json()["id"]

    # Pre-condition: last_used_at is NULL.
    engine = core.get_engine()
    sm = core.get_sessionmaker(engine)
    async with sm() as session:
        before = await session.get(DepartmentPAT, pat_id)
    assert before is not None and before.last_used_at is None

    from httpx import ASGITransport, AsyncClient

    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {plaintext}"},
    ) as bearer_client:
        response = await bearer_client.post(
            "/api/internal/departments/default/crawl"
        )
    assert response.status_code == 200

    async with sm() as session:
        after = await session.get(DepartmentPAT, pat_id)
    assert after is not None and after.last_used_at is not None


# --------------------------------------------------------------------------
# Missing / wrong-scheme bearer.
# --------------------------------------------------------------------------


async def test_missing_bearer_returns_401(_mock_crawl) -> None:
    from httpx import ASGITransport, AsyncClient

    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/internal/departments/default/crawl"
        )
    assert response.status_code == 401
    assert _mock_crawl == []


async def test_random_bearer_returns_403(seeded_db: SeededDb, _mock_crawl) -> None:
    """A bearer that doesn't match any row → 403 (not 401 — the scheme
    was correct, the credential just didn't authenticate)."""

    from httpx import ASGITransport, AsyncClient

    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer not-a-real-token"},
    ) as client:
        response = await client.post(
            "/api/internal/departments/default/crawl"
        )
    assert response.status_code == 403
    assert _mock_crawl == []


# --------------------------------------------------------------------------
# Legacy global env-PAT route still works (ARC-001 preserved).
# --------------------------------------------------------------------------


async def test_legacy_global_internal_crawl_with_env_pat_still_works(
    seeded_db: SeededDb, monkeypatch: pytest.MonkeyPatch, _mock_crawl
) -> None:
    """``POST /api/internal/crawl`` with ``TREND_INTERNAL_PAT`` env var
    is unchanged — Cloud Scheduler's existing integration must keep
    working alongside the new dept-scoped route."""

    monkeypatch.setenv("TREND_INTERNAL_PAT", "global-env-pat-xyz")

    from httpx import ASGITransport, AsyncClient

    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer global-env-pat-xyz"},
    ) as client:
        response = await client.post("/api/internal/crawl")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    # Global call → no department_id forwarded.
    assert len(_mock_crawl) == 1
    assert _mock_crawl[0]["department_id"] is None
