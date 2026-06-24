import asyncio
from typing import Awaitable, Callable, TypeVar

from core.utils.log_utils import get_log_buffer, append_to_buffer, start_log_buffer

T = TypeVar('T')


def run_and_close(coro: Awaitable[T], aclose: Callable[[], Awaitable[None]]) -> T:
    """Run a coroutine via asyncio.run, then await `aclose()` inside the SAME
    event loop before it is torn down.

    Closing the AsyncOpenAI/httpx client inside the loop avoids the harmless but
    noisy "RuntimeError: Event loop is closed" emitted when the httpx connection
    pool is finalized after the loop has already been closed.
    """
    async def _runner() -> T:
        try:
            return await coro
        finally:
            await aclose()

    return asyncio.run(_runner())


async def run_in_sync(func, *args):
    def run_and_get_log(*arguments):
        start_log_buffer()
        r = func(*arguments)
        buffer_value, buffer_started_at = get_log_buffer()

        return r, buffer_value

    loop = asyncio.get_running_loop()
    result, buffer_val = await loop.run_in_executor(None, run_and_get_log, *args)
    append_to_buffer(buffer_val)

    return result
