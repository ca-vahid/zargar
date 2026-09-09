"""A1 read/write identity and worker state; A2 atomic replacement fault points."""
import os

import pytest
from zargar.tools.discord_gateway import GatewayStore

from .test_gateway_envelope import _gateway, _msg


def test_acknowledged_edit_stays_acknowledged_after_restart(tmp_path):
    store = GatewayStore(tmp_path)
    env = {"kind": "update", "cid": "c1", "mid": "111",
           "msg": {"edited_timestamp": "2026-09-09T10:00:00Z", "content": "edited"}}
    store.accept(env)
    store.ack(env)
    assert store.counts() == (0, 0)
    assert GatewayStore(tmp_path).drain_spool() == []


async def test_duplicate_worker_receives_preserved_retry_and_destination_state(tmp_path):
    gateway = _gateway(tmp_path)
    gateway._enqueue("create", _msg())
    previous = gateway._queue.get_nowait()
    previous.update(attempts=2, emDone=True)
    gateway._store.spool(previous, "tips unavailable")  # third failed attempt
    gateway._enqueue("create", _msg())                 # repeated delivery
    captured = []

    async def process(http, headers, env):
        captured.append((env.get("attempts"), env.get("emDone", False)))
        raise RuntimeError("still unavailable")

    gateway._process_envelope = process
    await gateway._deliver(None, {}, gateway._queue.get_nowait())
    assert captured == [(3, True)], captured


@pytest.mark.parametrize("fault", ["fsync", "replace"])
def test_compaction_fault_before_swap_preserves_committed_ledger(tmp_path, monkeypatch, fault):
    store = GatewayStore(tmp_path)
    store.accept({"kind": "create", "cid": "c1", "mid": "111"})

    def interrupted(*args, **kwargs):
        raise OSError("injected compaction fault")

    with monkeypatch.context() as patch:
        patch.setattr(os, fault, interrupted)
        store._compact()
    assert len(GatewayStore(tmp_path).drain_spool()) == 1
