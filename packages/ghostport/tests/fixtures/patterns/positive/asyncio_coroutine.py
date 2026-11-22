"""Positive: asyncio.coroutine decorator was removed in Python 3.11."""
import asyncio


@asyncio.coroutine
def fetch():
    yield from asyncio.sleep(0)
