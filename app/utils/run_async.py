"""Run async coroutines from sync code (e.g. FastAPI def endpoints)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import anyio

T = TypeVar("T")


def run_async_from_sync(coro_func: Callable[..., Awaitable[T]], /, **kwargs: Any) -> T:
    async def _wrapper() -> T:
        return await coro_func(**kwargs)

    return anyio.run(_wrapper)
