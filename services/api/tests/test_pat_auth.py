"""DB-free tests for the PAT bearer-auth dependency (CONTEXT G10).

Mounts ``require_pat`` on a throwaway FastAPI app and asserts the full
status-code matrix:
  - env unset            -> 503
  - header missing       -> 401
  - wrong scheme         -> 401
  - wrong token          -> 403
  - correct token        -> 200

Constant-time compare is exercised implicitly via the 403 and 200 paths.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from api.middleware.pat_auth import require_pat


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/probe", dependencies=[Depends(require_pat)])
    async def probe() -> dict[str, str]:
        return {"ok": "yes"}

    return app


async def _get(app: FastAPI, headers: dict[str, str] | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get("/probe", headers=headers or {})


@pytest.mark.asyncio
async def test_503_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TREND_INTERNAL_PAT", raising=False)
    resp = await _get(_make_app(), headers={"Authorization": "Bearer anything"})
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_401_when_header_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TREND_INTERNAL_PAT", "secret-pat-value")
    resp = await _get(_make_app())
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_401_when_scheme_wrong(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TREND_INTERNAL_PAT", "secret-pat-value")
    resp = await _get(
        _make_app(), headers={"Authorization": "Basic secret-pat-value"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_403_when_token_wrong(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TREND_INTERNAL_PAT", "secret-pat-value")
    resp = await _get(
        _make_app(), headers={"Authorization": "Bearer the-wrong-value"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_200_when_token_correct(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TREND_INTERNAL_PAT", "secret-pat-value")
    resp = await _get(
        _make_app(), headers={"Authorization": "Bearer secret-pat-value"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": "yes"}
