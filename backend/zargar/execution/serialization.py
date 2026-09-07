"""Per-position serialization for opt-in policy adapters, including nested fills."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from functools import wraps
from weakref import WeakKeyDictionary

_guards = WeakKeyDictionary()


class _Guard:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.owner = None

    @asynccontextmanager
    async def hold(self):
        task = asyncio.current_task()
        if self.owner is task:
            yield
            return
        async with self.lock:
            self.owner = task
            try:
                yield
            finally:
                self.owner = None


def position_guard(manager, position_id):
    guards = _guards.setdefault(manager, {})
    return guards.setdefault(position_id, _Guard()).hold()


def serialized_adapter(method):
    """Legacy policies keep their existing path; adapters serialize mutable state."""
    @wraps(method)
    async def wrapped(manager, item, *args, **kwargs):
        if isinstance(item, str):
            position = manager.get(item)
        elif isinstance(item, dict):
            position = manager.get(manager._order_index.get(item.get("id")))
        else:
            position = item
        if position is None or not position.policy.get("adapter"):
            return await method(manager, item, *args, **kwargs)
        async with position_guard(manager, position.id):
            return await method(manager, item, *args, **kwargs)
    return wrapped
