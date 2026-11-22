"""Real Redis Lua checks. Opt in with TEST_REDIS_URL; never flush shared databases."""

import asyncio
import os
import unittest
import uuid
from unittest.mock import patch

import httpx

from service.riot_transport import RequestBudget, SharedBudgetUnavailable

REDIS_URL = os.environ.get('TEST_REDIS_URL')


@unittest.skipUnless(REDIS_URL, 'TEST_REDIS_URL is not configured; real Redis checks skipped')
class RedisIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from redis.asyncio import Redis

        self.clients = [
            Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
            for _ in range(2)
        ]
        self.host = f'test-{uuid.uuid4().hex}'
        self.workers = [RequestBudget(redis_client=client) for client in self.clients]
        self.addAsyncCleanup(self.cleanup_redis)
        await asyncio.gather(*(client.ping() for client in self.clients))

    async def cleanup_redis(self):
        try:
            # Only this test's UUID namespace; production keys and other tests are untouched.
            keys = [key async for key in self.clients[0].scan_iter(match=f'riot:*:{self.host}*')]
            if keys:
                await self.clients[0].delete(*keys)
        finally:
            await asyncio.gather(*(client.aclose() for client in self.clients))

    async def test_concurrent_workers_share_one_app_budget(self):
        await self.workers[0].update_async(self.host, 'detail', httpx.Headers({'X-App-Rate-Limit': '7:60'}))
        waits = await asyncio.gather(*(self.workers[index % 2].reserve(self.host, 'detail') for index in range(40)))
        self.assertEqual(waits.count(None), 7)
        self.assertTrue(all(wait is None or 1 <= wait <= 60 for wait in waits))
        self.assertEqual(await self.clients[0].zcard(f'riot:calls:app:{self.host}'), 7)

    async def test_method_scope_and_zero_limit(self):
        await self.workers[0].update_async(
            self.host, 'detail', httpx.Headers({'X-App-Rate-Limit': '20:60', 'X-Method-Rate-Limit': '0:60'})
        )
        self.assertGreater(await self.workers[1].reserve(self.host, 'detail'), 0)
        self.assertIsNone(await self.workers[1].reserve(self.host, 'timeline'))
        await self.workers[0].update_async(self.host, 'detail', httpx.Headers({'X-Method-Rate-Limit': '2:60'}))
        waits = await asyncio.gather(*(self.workers[i % 2].reserve(self.host, 'detail') for i in range(8)))
        self.assertEqual(waits.count(None), 2)

    async def test_shorter_cooldown_cannot_erase_longer_wait_and_expiry_recovers(self):
        key = f'riot:cooldown:{self.host}'
        await self.workers[0].cooldown_async(self.host, 30)
        first_deadline = int(await self.clients[0].get(key))
        await self.workers[1].cooldown_async(self.host, 1)
        self.assertGreaterEqual(int(await self.clients[0].get(key)), first_deadline)
        self.assertGreater(await self.clients[0].pttl(key), 25000)
        # A fresh worker must observe shared state without a local cooldown.
        reader = RequestBudget(redis_client=self.clients[1])
        self.assertGreater(await reader.reserve(self.host, 'detail'), 25)
        await self.workers[1].cooldown_async(self.host, 45)
        self.assertGreater(int(await self.clients[0].get(key)), first_deadline)
        await self.clients[0].pexpire(key, 1)
        await asyncio.sleep(0.03)
        self.assertIsNone(await reader.reserve(self.host, 'detail'))

    async def test_shared_windows_ignore_worker_wall_clock_skew(self):
        with patch('service.riot_transport.time.time', return_value=1):
            await self.workers[0].update_async(self.host, 'detail', httpx.Headers({'X-App-Rate-Limit': '1:60'}))
            self.assertIsNone(await self.workers[0].reserve(self.host, 'detail'))
        with patch('service.riot_transport.time.time', return_value=9999999999):
            self.assertGreater(await self.workers[1].reserve(self.host, 'detail'), 0)
            await self.workers[0].cooldown_async(self.host, 10)
        self.assertLessEqual(await self.clients[0].pttl(f'riot:cooldown:{self.host}'), 10000)

    async def test_lua_failure_blocks_reservations_and_recovery_reuses_shared_state(self):
        key = f'riot:calls:app:{self.host}'
        # A wrong-type value forces a real Redis script error without stopping anyone's server.
        await self.clients[0].set(key, 'synthetic-invalid-type')
        for worker in self.workers:
            with self.assertRaises(SharedBudgetUnavailable):
                await worker.reserve(self.host, 'detail')
        await self.clients[0].delete(key)
        self.assertIsNone(await self.workers[1].reserve(self.host, 'detail'))
