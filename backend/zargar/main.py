"""Entrypoint: python -m zargar.main"""
from __future__ import annotations

import atexit
import contextlib
import logging
import logging.handlers
import os
import signal
import sys
import pathlib

import uvicorn

from .api.app import create_app
from .config import get_config


def main() -> None:
    config = get_config()
    # Always keep a rotating file log next to the package: the app usually runs
    # detached/hidden on Windows, and the 2026-08-25 feed outage was
    # undiagnosable because stdout went to a hidden window and nothing else.
    log_path = pathlib.Path(__file__).resolve().parent.parent / f"zargar-{config.port}.log"
    # F69 (2026-09-08): 5 MB x 3 kept ~50 minutes of a market-hours day — the 14:24 stop had no
    # surviving evidence. 50 MB x 10 keeps days; httpx's per-poll INFO line is the bulk of it.
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=50_000_000, backupCount=10, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        handlers=[logging.StreamHandler(), file_handler],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    boot = logging.getLogger("zargar.process")
    boot.warning("process starting pid=%s parent=%s argv=%s", os.getpid(), os.getppid(), sys.argv)
    # the 2026-09-08 stop left no shutdown line at all: say goodbye on every path we can see
    atexit.register(lambda: boot.warning("process exiting (atexit) pid=%s", os.getpid()))

    def _on_signal(signum, _frame):
        boot.warning("signal %s received pid=%s — shutting down", signum, os.getpid())
        raise SystemExit(0)

    for _sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None), getattr(signal, "SIGBREAK", None)):
        if _sig is not None:
            with contextlib.suppress(Exception):
                signal.signal(_sig, _on_signal)
    # Exposed to a network (phones via LAN/Tailscale) the token is the only gate —
    # never start reachable-and-open. Loopback (Tailscale Serve proxies to it) is fine.
    if config.host not in ("127.0.0.1", "localhost", "::1") and not (config.auth_token or config.google_client_id):
        raise SystemExit(
            f"refusing to bind {config.host}:{config.port} without sign-in — set ZARGAR_GOOGLE_CLIENT_ID "
            "(+ ZARGAR_GOOGLE_ALLOWED_EMAILS) or ZARGAR_AUTH_TOKEN in backend/.env (docs/AUTH.md)")
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
