"""Operational endpoints the restart scripts use (2026-09-09).

Loopback-only, like /api/health's `local` block: `scripts/start.ps1` and the scheduler's watchdog run
on this machine without a session token, and a remote caller has no business restarting the desk.
"""
import logging

from fastapi import HTTPException, Request

from ..ops import compare_states, restart_readiness, restart_state

log = logging.getLogger("zargar.api.ops")


def _local(request: Request) -> bool:
    return bool(request.client and request.client.host in ("127.0.0.1", "::1")) and not request.headers.get("x-forwarded-for")


def build_ops_routes(app, eng, auth, config) -> None:

    @app.get("/api/ops/restart-check")
    async def ops_restart_check(request: Request, caller: str = ""):
        if not _local(request):
            raise HTTPException(status_code=403, detail="local callers only")
        return await restart_readiness(eng, caller=caller or "api")

    @app.get("/api/ops/state")
    async def ops_state(request: Request):
        if not _local(request):
            raise HTTPException(status_code=403, detail="local callers only")
        return await restart_state(eng)

    class CompareBody(dict):
        pass

    @app.post("/api/ops/restore-check")
    async def ops_restore_check(request: Request):
        """Body = the state captured BEFORE a restart; the answer compares it with now."""
        if not _local(request):
            raise HTTPException(status_code=403, detail="local callers only")
        before = await request.json()
        after = await restart_state(eng)
        out = compare_states(before or {}, after)
        out["after"] = after
        if not out["ok"]:
            log.warning("restore check MISMATCH after restart: %s", out["missing"])
        return out
