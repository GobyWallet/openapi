import asyncio
from functools import wraps, partial
from typing import Callable


class SingleFlight:

    def __init__(self):
        self.key_future = {}
        
    async def do(self, key, coro_lambda):
        if key in self.key_future:
            return await self.key_future[key]
        
        fut = asyncio.ensure_future(coro_lambda())
        self.key_future[key] = fut
        try:
            res = await fut
            return res
        finally:
            del self.key_future[key]
