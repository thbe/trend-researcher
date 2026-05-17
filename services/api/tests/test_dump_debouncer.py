"""DB-free tests for the post-write dump debouncer (CONTEXT G9).

We exercise ``DumpDebouncer`` + ``DumpDebouncerMiddleware`` directly against a
throwaway tmp bash script (writes a marker file when invoked) rather than
wiring a real write endpoint into the production app. This keeps the tests:
- DB-free (no postgres needed)
- Subprocess-only (no real pg_dump)
- Fast (debounce window scaled to ~100ms)

The third test asserts coalescing: a burst of 5 schedule() calls collapses to
a single subprocess invocation at the tail of the debounce window.
"""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.middleware.dump_debouncer import (
    DumpDebouncer,
    DumpDebouncerMiddleware,
    build_dump_debouncer,
)


def _make_marker_script(tmp_path: Path) -> tuple[Path, Path]:
    """Create an executable script that appends a line to a marker file."""

    marker = tmp_path / "dump-marker.log"
    script = tmp_path / "fake-dump.sh"
    script.write_text(
        "#!/bin/bash\n"
        f'echo "dump $$" >> "{marker}"\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script, marker


def test_build_debouncer_skipped_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_dump_debouncer() returns None when DB_DUMP_SCRIPT is unset."""

    monkeypatch.delenv("DB_DUMP_SCRIPT", raising=False)
    assert build_dump_debouncer() is None


def test_build_debouncer_skipped_when_script_not_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """build_dump_debouncer() returns None when path exists but isn't +x."""

    script = tmp_path / "not-exec.sh"
    script.write_text("#!/bin/bash\necho hi\n")
    # deliberately NOT chmod +x
    monkeypatch.setenv("DB_DUMP_SCRIPT", str(script))
    assert build_dump_debouncer() is None


@pytest.mark.asyncio
async def test_debouncer_schedules_on_write_response(tmp_path: Path) -> None:
    """A successful POST triggers a dump after the debounce window."""

    script, marker = _make_marker_script(tmp_path)
    debouncer = DumpDebouncer(script, debounce_seconds=0.05)

    app = FastAPI()

    @app.post("/echo")
    async def _echo() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(DumpDebouncerMiddleware, debouncer=debouncer)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/echo")
        assert resp.status_code == 200

    # Deterministically wait for the scheduled task to finish (sleep + subprocess).
    assert debouncer._pending is not None
    await debouncer._pending

    assert marker.exists(), "fake-dump script should have written marker"
    lines = marker.read_text().strip().splitlines()
    assert len(lines) == 1, f"expected 1 dump invocation, got {len(lines)}"


@pytest.mark.asyncio
async def test_debouncer_coalesces_burst(tmp_path: Path) -> None:
    """5 rapid schedule() calls within the window collapse to 1 invocation."""

    script, marker = _make_marker_script(tmp_path)
    debouncer = DumpDebouncer(script, debounce_seconds=0.1)

    # Burst: schedule 5 times within ~50ms (well inside the 100ms window).
    for _ in range(5):
        await debouncer.schedule()
        await asyncio.sleep(0.01)

    # Deterministically wait for the (single, surviving) scheduled task.
    assert debouncer._pending is not None
    await debouncer._pending

    assert marker.exists(), "burst should have produced exactly one dump"
    lines = marker.read_text().strip().splitlines()
    assert len(lines) == 1, f"expected 1 coalesced dump, got {len(lines)}"


@pytest.mark.asyncio
async def test_debouncer_skips_failed_write_response(tmp_path: Path) -> None:
    """A 4xx response on a write method does NOT schedule a dump."""

    script, marker = _make_marker_script(tmp_path)
    debouncer = DumpDebouncer(script, debounce_seconds=0.05)

    app = FastAPI()

    @app.post("/boom")
    async def _boom() -> dict[str, str]:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="nope")

    app.add_middleware(DumpDebouncerMiddleware, debouncer=debouncer)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/boom")
        assert resp.status_code == 400

    # No task should have been scheduled at all.
    assert debouncer._pending is None
    # And just to be sure, give the loop a tick.
    await asyncio.sleep(0.15)
    assert not marker.exists(), "failed write must not trigger a dump"
