"""Debounced post-write pg_dump trigger.

Strategy (CONTEXT G9):
- Any successful mutating HTTP response (2xx/3xx on POST/PUT/PATCH/DELETE)
  schedules a dump after ``DB_DUMP_DEBOUNCE_MS`` of quiet time.
- Subsequent writes within the window cancel the pending dump and reschedule,
  so a burst of writes collapses into a single dump at the tail.
- The dump itself runs the external ``DB_DUMP_SCRIPT`` (pg-dump-rotate.sh)
  which holds a ``flock -n`` so concurrent invocations are safe.

This middleware is only registered when ``DB_DUMP_SCRIPT`` resolves to an
executable path — local dev and tests typically run without it.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_log = logging.getLogger("api.middleware.dump_debouncer")


class DumpDebouncer:
    """Single in-flight pending dump task; reschedules on new writes."""

    def __init__(self, script: Path, debounce_seconds: float) -> None:
        self._script = script
        self._debounce_s = debounce_seconds
        self._pending: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def schedule(self) -> None:
        """Cancel any pending dump and queue a fresh one ``debounce_s`` from now."""

        async with self._lock:
            if self._pending is not None and not self._pending.done():
                self._pending.cancel()
            self._pending = asyncio.create_task(self._run_after_delay())

    async def _run_after_delay(self) -> None:
        try:
            await asyncio.sleep(self._debounce_s)
        except asyncio.CancelledError:
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                str(self._script),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                _log.warning(
                    "pg-dump-rotate exited %s: stdout=%r stderr=%r",
                    proc.returncode,
                    stdout.decode(errors="replace"),
                    stderr.decode(errors="replace"),
                )
        except Exception:  # pragma: no cover - defensive
            _log.exception("Failed to launch pg-dump-rotate")


class DumpDebouncerMiddleware(BaseHTTPMiddleware):
    """ASGI middleware: schedule a dump after each successful write response."""

    def __init__(self, app, *, debouncer: DumpDebouncer) -> None:
        super().__init__(app)
        self._debouncer = debouncer

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        if (
            request.method in _WRITE_METHODS
            and 200 <= response.status_code < 400
        ):
            await self._debouncer.schedule()
        return response


def build_dump_debouncer() -> DumpDebouncer | None:
    """Construct a debouncer from env, or return ``None`` if not configured.

    Reads:
        DB_DUMP_SCRIPT       - path to executable script (required)
        DB_DUMP_DEBOUNCE_MS  - debounce window in ms (default 30000)

    Returns ``None`` when ``DB_DUMP_SCRIPT`` is unset or doesn't resolve to
    an executable file, so ``api.main`` can skip registering the middleware.
    """

    raw = os.environ.get("DB_DUMP_SCRIPT", "").strip()
    if not raw:
        return None
    script = Path(raw)
    if not script.is_file() or not os.access(script, os.X_OK):
        _log.warning("DB_DUMP_SCRIPT=%s is not an executable file; debouncer disabled", raw)
        return None
    try:
        debounce_ms = int(os.environ.get("DB_DUMP_DEBOUNCE_MS", "30000"))
    except ValueError:
        debounce_ms = 30000
    return DumpDebouncer(script, debounce_ms / 1000.0)


__all__ = [
    "DumpDebouncer",
    "DumpDebouncerMiddleware",
    "build_dump_debouncer",
]
