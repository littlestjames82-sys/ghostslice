"""Clean fixture: current stdlib APIs only, zero pack hits expected."""
import asyncio
import configparser
from collections.abc import Mapping
from math import gcd


async def fetch():
    await asyncio.sleep(0)
    return gcd(12, 18), Mapping, configparser.ConfigParser
