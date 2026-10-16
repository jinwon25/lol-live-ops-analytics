"""실제 키·실제 전적 없이 공식 연결의 라우팅·누출·실패 처리를 검증한다."""
import json
import os
import unittest
from unittest.mock import patch

import httpx

from service.main import app
from service.riot import RiotGateway, RiotError, normalize_match


def synthetic_match():
    return {'info':{'queueId':420, 'platformId':'KR', 'gameDuration':1800,
                    'gameEndTimestamp':1780000000000, 'gameVersion':'16.19.123.1',
                    'participants':[{'puuid':'synthetic-self', 'teamId':100, 'championId':81,
                                     'teamPosition':'BOTTOM', 'goldEarned':12000,
                                     'totalDamageDealtToChampions':21000, 'visionScore':24,
                                     'kills':5, 'assists':8, 'win':True},
                                    {'puuid':'synthetic-other', 'teamId':100, 'kills':19}]}}


class RiotTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_excludes_identity_and_uses_seconds(self):
        result = normalize_match(synthetic_match(), 'synthetic-self')
        self.assertEqual(result['duration_minutes'], 30)
        self.assertEqual(result['team_kills'], 24)
        self.assertEqual(result['role'], 'BOT')
        self.assertEqual(result['patch'], '16.19')
        self.assertIsNone(result['tier'])  # 현재 랭크를 과거 경기의 티어로 쓰지 않음
        self.assertNotIn('synthetic', json.dumps(result))
        self.assertNotIn('puuid', result)

    def test_excludes_wrong_queue_remake_missing_end_and_role(self):
        for change in [{'queueId':440}, {'gameDuration':120}, {'gameEndTimestamp':None}]:
            match_payload = synthetic_match()
            match_payload['info'].update(change)
            self.assertIsNone(normalize_match(match_payload, 'synthetic-self'))
        match_payload = synthetic_match()
        match_payload['info']['participants'][0]['teamPosition'] = ''
        self.assertIsNone(normalize_match(match_payload, 'synthetic-self'))

    def test_missing_or_invalid_metrics_are_not_zero_filled(self):
        for field in ['goldEarned', 'totalDamageDealtToChampions', 'visionScore', 'kills', 'assists']:
            match = synthetic_match()
            del match['info']['participants'][0][field]
            self.assertIsNone(normalize_match(match, 'synthetic-self'), field)
        for field, value in [('kills', True), ('kills', 1.5), ('goldEarned', 100001),
                             ('visionScore', float('nan')), ('assists', 25)]:
            match = synthetic_match()
            match['info']['participants'][0][field] = value
            self.assertIsNone(normalize_match(match, 'synthetic-self'), (field, value))

    def test_malformed_participants_and_missing_team_kills_are_excluded(self):
        for participants in [None, {}, [None], ['invalid']]:
            match = synthetic_match()
            match['info']['participants'] = participants
            self.assertIsNone(normalize_match(match, 'synthetic-self'))
        match = synthetic_match()
        del match['info']['participants'][1]['kills']
        self.assertIsNone(normalize_match(match, 'synthetic-self'))

    async def test_malformed_lists_return_controlled_error(self):
        for ids, ranks in [([{}], []), (['KR_123'], [None])]:
            def response(request):
                if '/accounts/' in request.url.path:
                    data = {'puuid': 'synthetic-self'}
                elif request.url.path.endswith('/ids'):
                    data = ids
                elif '/league/' in request.url.path:
                    data = ranks
                else:
                    data = synthetic_match()
                return httpx.Response(200, json=data)
            original_client = httpx.AsyncClient
            with patch.dict(os.environ, {'RIOT_API_KEY': 'synthetic-test-key'}), patch(
                    'service.riot.httpx.AsyncClient',
                    side_effect=lambda **kw: original_client(transport=httpx.MockTransport(response), **kw)):
                with self.assertRaises(RiotError) as caught:
                    await RiotGateway().recent('synthetic-name', 'KR1', 1)
            self.assertEqual(caught.exception.status, 502)

    async def test_429_stops_and_does_not_expose_body(self):
        def response(request):
            return httpx.Response(429, headers={'Retry-After':'17'}, text='private-response')
        gateway = RiotGateway()
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            with self.assertRaises(RiotError) as caught:
                await gateway.get(client, 'asia', '/test')
        self.assertEqual(caught.exception.retry_after, 17)
        self.assertNotIn('private-response', caught.exception.message)

    async def test_routing_safe_response_and_cache(self):
        requests = []
        def response(request):
            requests.append(request)
            path = request.url.path
            if '/accounts/by-riot-id/' in path:
                data = {'puuid':'synthetic-self', 'gameName':'synthetic-name'}
            elif path.endswith('/ids'):
                data = ['KR_123']
            elif '/league/' in path:
                data = [{'queueType':'RANKED_SOLO_5x5','tier':'GOLD','rank':'IV','leaguePoints':30,
                         'puuid':'synthetic-self'}]
            else:
                data = synthetic_match()
            return httpx.Response(200, json=data)
        original_client = httpx.AsyncClient
        with patch.dict(os.environ, {'RIOT_API_KEY':'synthetic-test-key'}), patch('service.riot.httpx.AsyncClient', side_effect=lambda **kw: original_client(transport=httpx.MockTransport(response), **kw)):
            gateway = RiotGateway()
            result = await gateway.recent('synthetic/name', 'KR1', 1)
            cached = await gateway.recent('synthetic/name', 'KR1', 1)
        self.assertEqual(len(requests), 4)
        self.assertTrue(cached['cached'])
        self.assertEqual([r.url.host for r in requests], ['asia.api.riotgames.com','asia.api.riotgames.com','kr.api.riotgames.com','asia.api.riotgames.com'])
        self.assertIn('%2F', requests[0].url.raw_path.decode())
        self.assertTrue(all(r.headers['X-Riot-Token'] == 'synthetic-test-key' for r in requests))
        self.assertFalse(any('synthetic' in str(r.url.query) for r in requests))
        self.assertNotIn('synthetic', json.dumps(result))

    async def test_local_boundary_no_key_and_no_store(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1',50000)), base_url='http://127.0.0.1') as client:
            with patch.dict(os.environ, {'RIOT_API_KEY':''}):
                response = await client.post('/api/riot/recent', json={'game_name':'synthetic','tag_line':'KR1'})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertFalse((await client.get('/api/riot/status')).json()['configured'])
            self.assertEqual((await client.get('/api/riot/status', headers={'Origin':'https://other.example'})).status_code, 403)
            self.assertEqual((await client.get('/api/riot/status', headers={'Host':'other.example'})).status_code, 403)
            self.assertEqual((await client.post('/api/riot/recent', json={'game_name':'x','tag_line':'y','count':100})).status_code, 422)
            expired=await client.get('/api/riot/timeline/unknown-token')
            self.assertEqual(expired.status_code,410)
            self.assertEqual(expired.headers['Cache-Control'],'no-store')
            self.assertEqual((await client.get('/api/riot/timeline/'+'x'*65)).status_code,404)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('192.0.2.10',50000)), base_url='http://127.0.0.1') as remote:
            self.assertEqual((await remote.get('/api/riot/status')).status_code, 403)

    async def test_exponential_backoff_retries_transient_5xx_and_recovers(self):
        attempt_counter = 0

        def transient_then_ok(request):
            nonlocal attempt_counter
            attempt_counter += 1
            if attempt_counter < 3:
                return httpx.Response(503, text='service unavailable')
            return httpx.Response(200, json={'ok': True})

        gateway = RiotGateway()
        async with httpx.AsyncClient(transport=httpx.MockTransport(transient_then_ok)) as client:
            payload = await gateway._get(client, 'asia', '/lol/match/v5/matches/KR_999')
        self.assertEqual(payload, {'ok': True})
        self.assertEqual(attempt_counter, 3)

    async def test_parallel_match_detail_fetching_and_shared_lifespan_client(self):
        import asyncio

        in_flight = 0
        max_in_flight = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal in_flight, max_in_flight
            path = request.url.path
            if '/accounts/by-riot-id/' in path:
                return httpx.Response(200, json={'puuid': 'synthetic-self'})
            if path.endswith('/ids'):
                return httpx.Response(200, json=['KR_1', 'KR_2', 'KR_3'])
            if '/league/' in path:
                return httpx.Response(200, json=[])
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.03)
            in_flight -= 1
            return httpx.Response(200, json=synthetic_match())

        gateway = RiotGateway()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as shared_client:
            gateway.set_client(shared_client)
            with patch.dict(os.environ, {'RIOT_API_KEY': 'synthetic-test-key'}):
                result = await gateway.recent('synthetic-name', 'KR1', 3)
        self.assertEqual(len(result['items']), 3)
        self.assertGreaterEqual(max_in_flight, 2)

    async def test_network_guard_supports_private_subnet_forwarded_for_and_remote_access_flag(self):
        # Docker bridge private IP (172.18.0.5) with trusted X-Forwarded-For is accepted
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=('172.18.0.5', 50000)),
            base_url='http://172.18.0.2:8001',
        ) as docker_client:
            ok_resp = await docker_client.get(
                '/api/riot/status',
                headers={'X-Forwarded-For': '192.168.1.25, 172.18.0.1'},
            )
            self.assertEqual(ok_resp.status_code, 200)
            # Untrusted public IP in X-Forwarded-For is blocked when ALLOW_REMOTE_ACCESS=false
            blocked_resp = await docker_client.get(
                '/api/riot/status',
                headers={'X-Forwarded-For': '192.0.2.99'},
            )
            self.assertEqual(blocked_resp.status_code, 403)

        # When ALLOW_REMOTE_ACCESS=true, external client with allowed origin is accepted
        with patch.dict(
            os.environ,
            {
                'ALLOW_REMOTE_ACCESS': 'true',
                'ALLOWED_ORIGINS': 'https://analytics.example.com',
            },
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=('192.0.2.10', 50000)),
                base_url='https://api.example.com',
            ) as remote_client:
                allowed = await remote_client.get(
                    '/api/riot/status',
                    headers={'Origin': 'https://analytics.example.com'},
                )
                self.assertEqual(allowed.status_code, 200)
                disallowed = await remote_client.get(
                    '/api/riot/status',
                    headers={'Origin': 'https://evil.example.com'},
                )
                self.assertEqual(disallowed.status_code, 403)


if __name__ == '__main__':
    unittest.main()
