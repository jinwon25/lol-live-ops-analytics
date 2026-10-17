import unittest
from unittest.mock import patch

import httpx

from service.riot import RiotError, RiotGateway
from service.riot_transport import RequestBudget, windows
from service.timeline import timeline_summary


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_headers_reserve_remote_usage_and_regions_independently(self):
        b = RequestBudget()
        with patch('service.riot_transport.time.monotonic', return_value=1000):
            b.update(
                'asia', 'detail', httpx.Headers({'X-App-Rate-Limit': '100:120', 'X-App-Rate-Limit-Count': '99:120'})
            )
            self.assertIsNone(await b.reserve('asia', 'detail'))
            self.assertEqual(await b.reserve('asia', 'detail'), 120)
            self.assertIsNone(await b.reserve('kr', 'league'))
        with patch('service.riot_transport.time.monotonic', return_value=1121):
            self.assertIsNone(await b.reserve('asia', 'detail'))

    async def test_method_budget_is_specific_and_bad_headers_ignored(self):
        b = RequestBudget()
        self.assertEqual(windows('bad,20:1,1:-1,inf:2'), {1: 20})
        b.update(
            'asia', 'timeline', httpx.Headers({'X-Method-Rate-Limit': '1:10', 'X-Method-Rate-Limit-Count': '1:10'})
        )
        self.assertGreater(await b.reserve('asia', 'timeline'), 0)
        self.assertIsNone(await b.reserve('asia', 'detail'))

    async def test_429_halts_future_calls_and_completion_cache_saves_calls(self):
        calls = []

        def response(request):
            calls.append(request)
            return httpx.Response(429, headers={'Retry-After': '17'})

        gateway = RiotGateway()
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as c:
            for _ in range(2):
                with self.assertRaises(RiotError):
                    await gateway.get(c, 'asia', '/lol/match/v5/matches/KR_1')
        self.assertEqual(len(calls), 1)
        calls.clear()
        gateway = RiotGateway()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200, json={'info': {}}))
        ) as c:
            await gateway.get(c, 'asia', '/lol/match/v5/matches/KR_1')
            await gateway.get(c, 'asia', '/lol/match/v5/matches/KR_1')
        self.assertEqual(len(calls), 1)

    def test_timeline_uses_actual_frame_and_missing_cs_not_zero(self):
        raw = {
            'info': {
                'frames': [
                    {
                        'timestamp': 600000,
                        'participantFrames': {
                            '1': {'totalGold': 4000, 'minionsKilled': 80, 'jungleMinionsKilled': 2},
                            '6': {'totalGold': 4400, 'minionsKilled': 90},
                        },
                        'events': [
                            {'type': 'CHAMPION_KILL', 'victimId': 1, 'timestamp': 590000, 'position': {'x': 123}}
                        ],
                    }
                ]
            }
        }
        result = timeline_summary(raw, 1, 6, 100)
        self.assertEqual(result['points'][0]['gold_difference'], -400)
        self.assertEqual(result['points'][0]['cs'], 82)
        self.assertIsNone(result['points'][0]['cs_difference'])
        self.assertNotIn('position', str(result))
        self.assertEqual(result['deaths'], [9.83])

    async def test_redis_multi_worker_budget_and_cross_worker_timeline_token(self):
        import time

        from service.riot_transport import SLIDING_WINDOW_RESERVE_LUA, UPDATE_HEADERS_LUA

        class FakeAsyncRedis:
            """In-memory async Redis emulator executing Lua scripts and TTL KV operations."""

            def __init__(self):
                self.kv = {}
                self.zsets = {}

            async def get(self, key):
                entry = self.kv.get(key)
                if not entry:
                    return None
                value, expire_at = entry
                if expire_at and time.time() * 1000 >= expire_at:
                    del self.kv[key]
                    return None
                return value

            async def set(self, key, value, ex=None, px=None):
                now_ms = time.time() * 1000
                expire_at = now_ms + (ex * 1000) if ex else (now_ms + px if px else None)
                self.kv[key] = (str(value), expire_at)
                return True

            async def eval(self, script, numkeys, *keys_and_args):
                keys = keys_and_args[:numkeys]
                args = keys_and_args[numkeys:]
                if script == UPDATE_HEADERS_LUA:
                    limits_key, obs_prefix = keys[0], keys[1]
                    now_ms, limits_raw, counts_raw = int(args[0]), str(args[1]), str(args[2])
                    if limits_raw:
                        self.kv[limits_key] = (limits_raw, now_ms + 86400000)
                    for pair in counts_raw.split(','):
                        if ':' in pair:
                            cnt, sec = map(int, pair.split(':'))
                            target_until = now_ms + sec * 1000
                            self.kv[f'{obs_prefix}:{sec}'] = (f'{cnt}:{target_until}', target_until)
                    return 1
                if script == SLIDING_WINDOW_RESERVE_LUA:
                    (
                        cooldown_key,
                        app_calls_key,
                        method_calls_key,
                        app_limits_key,
                        method_limits_key,
                        app_obs_prefix,
                        method_obs_prefix,
                    ) = keys
                    now_ms, req_id, default_app_raw = int(args[0]), str(args[1]), str(args[2])
                    max_wait_ms = 0
                    cd_raw = await self.get(cooldown_key)
                    if cd_raw and int(cd_raw) > now_ms:
                        max_wait_ms = int(cd_raw) - now_ms

                    app_limits = windows((await self.get(app_limits_key)) or default_app_raw)
                    method_limits = windows((await self.get(method_limits_key)) or '')

                    for calls_key, lims, obs_prefix in [
                        (app_calls_key, app_limits, app_obs_prefix),
                        (method_calls_key, method_limits, method_obs_prefix),
                    ]:
                        zset = self.zsets.setdefault(calls_key, [])
                        for sec, limit in lims.items():
                            win_ms = sec * 1000
                            recent = [score for score, _ in zset if score > now_ms - win_ms]
                            if len(recent) >= limit and recent:
                                max_wait_ms = max(max_wait_ms, win_ms - (now_ms - min(recent)))
                            obs_raw = await self.get(f'{obs_prefix}:{sec}')
                            if obs_raw:
                                obs_c, obs_u = map(int, obs_raw.split(':'))
                                if now_ms < obs_u and obs_c >= limit:
                                    max_wait_ms = max(max_wait_ms, obs_u - now_ms)

                    if max_wait_ms > 0:
                        return max(1, int((max_wait_ms + 999) // 1000))
                    self.zsets.setdefault(app_calls_key, []).append((now_ms, req_id))
                    self.zsets.setdefault(method_calls_key, []).append((now_ms, req_id))
                    return 0
                return 0

        fake_redis = FakeAsyncRedis()
        worker1_budget = RequestBudget(redis_client=fake_redis)
        worker2_budget = RequestBudget(redis_client=fake_redis)

        await worker1_budget.update_async(
            'asia',
            'detail',
            httpx.Headers({'X-App-Rate-Limit': '2:60', 'X-App-Rate-Limit-Count': '0:60'}),
        )
        # Worker 1 and Worker 2 share the 2-request budget across processes.
        self.assertIsNone(await worker1_budget.reserve('asia', 'detail'))
        self.assertIsNone(await worker2_budget.reserve('asia', 'detail'))
        self.assertGreater(await worker1_budget.reserve('asia', 'detail'), 0)
        self.assertGreater(await worker2_budget.reserve('asia', 'detail'), 0)

        # Cross-worker timeline token resolution via Redis
        worker1_gw = RiotGateway(redis_client=FakeAsyncRedis())
        worker2_gw = RiotGateway(redis_client=worker1_gw.redis_client)
        await worker1_gw._redis_set_json('riot:timeline:shared-token-123', ['KR_1', 1, 6, 100], 1800)

        raw_tl = {
            'info': {
                'frames': [
                    {
                        'timestamp': 600000,
                        'participantFrames': {
                            '1': {'totalGold': 4000, 'minionsKilled': 80, 'jungleMinionsKilled': 2},
                            '6': {'totalGold': 4400, 'minionsKilled': 90, 'jungleMinionsKilled': 0},
                        },
                        'events': [],
                    }
                ]
            }
        }
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=raw_tl))
        ) as client:
            worker2_gw.set_client(client)
            with patch.dict('os.environ', {'RIOT_API_KEY': 'synthetic-key'}):
                tl_result = await worker2_gw.timeline('shared-token-123')
        self.assertEqual(tl_result['points'][0]['gold_difference'], -400)
