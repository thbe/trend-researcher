"""DB-free tests for the conditional SPA StaticFiles mount (CONTEXT G2).

``api.main`` captures ``WEB_DIST_DIR`` at module-import time, so these tests
manipulate the env BEFORE re-importing the module under test.

Acceptance:
- ``WEB_DIST_DIR`` unset  -> no ``spa`` mount; ``GET /`` 404.
- ``WEB_DIST_DIR`` set    -> ``spa`` mount present; ``GET /`` 200 + body
  contains the marker we wrote to tmp index.html.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


def _reimport_api_main() -> object:
    """Drop cached ``api.main`` so env changes take effect, then re-import."""

    for name in [n for n in list(sys.modules) if n == "api.main"]:
        del sys.modules[name]
    return importlib.import_module("api.main")


@pytest.mark.asyncio
async def test_static_mount_skipped_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No 'spa' route + GET / returns 404 when WEB_DIST_DIR is unset."""

    monkeypatch.delenv("WEB_DIST_DIR", raising=False)
    main = _reimport_api_main()

    route_names = {getattr(r, "name", None) for r in main.app.routes}
    assert "spa" not in route_names

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_static_mount_active_when_env_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Setting WEB_DIST_DIR mounts SPA + GET / serves index.html."""

    marker = "TREND_RESEARCHER_TEST_MARKER_OK"
    (tmp_path / "index.html").write_text(
        f'<!doctype html><html><body><div id="app">{marker}</div></body></html>\n'
    )

    monkeypatch.setenv("WEB_DIST_DIR", str(tmp_path))
    main = _reimport_api_main()

    route_names = {getattr(r, "name", None) for r in main.app.routes}
    assert "spa" in route_names

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert marker in resp.text

    # Reset env so subsequent test files reimporting api.main see the default
    # (env-unset) state. monkeypatch will also revert on teardown.
    monkeypatch.delenv("WEB_DIST_DIR", raising=False)
    _reimport_api_main()
