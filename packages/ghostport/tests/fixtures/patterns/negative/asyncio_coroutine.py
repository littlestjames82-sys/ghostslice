"""Look-alike negative: native async def is current, no legacy coroutine decorator."""
import asyncio


async def fetch():
    await asyncio.sleep(0)
    return "done"
