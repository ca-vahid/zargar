"""Identity of THIS process (KFIN-04, 2026-09-14).

One runtime = one engine process. Paid work it starts (Tips analyst runs) is stamped
with this identity so a later reader — restart readiness in the same process, or a
boot after a crash — can tell "owned by a live task here" from "owned by a process
that is gone" without guessing from the row's age. Leaf module: nothing here imports
the rest of the package.
"""
from __future__ import annotations

import datetime as dt
import os
import socket
import uuid

_BOOT_TOKEN = uuid.uuid4().hex[:12]
_STARTED_AT = dt.datetime.now(dt.timezone.utc)
RUNTIME_ID = f"{socket.gethostname()}:{os.getpid()}:{_BOOT_TOKEN}"


def runtime_id() -> str:
    """`host:pid:boot-token` — unique per process start (a pid alone is reused by the OS)."""
    return RUNTIME_ID


def runtime_identity() -> dict:
    return {"runtimeId": RUNTIME_ID, "host": socket.gethostname(), "pid": os.getpid(),
            "bootToken": _BOOT_TOKEN, "startedAt": _STARTED_AT.isoformat(timespec="seconds")}
