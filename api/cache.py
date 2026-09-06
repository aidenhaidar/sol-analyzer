"""In-memory TTL cache that also de-duplicates concurrent identical requests."""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")
_store: dict[str, tuple[float, asyncio.Future]] = {}


async def cached(key: str, ttl: float, fn: Callable[[], Awaitable[T]]) -> T:
    now = time.monotonic()
    hit = _store.get(key)
    if hit and hit[0] > now:
        return await asyncio.shield(hit[1])
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    _store[key] = (now + ttl, fut)
    try:
        value = await fn()
    except BaseException as e:  # noqa: BLE001 - propagate after evicting
        _store.pop(key, None)
        fut.set_exception(e)
        raise
    fut.set_result(value)
    return value
