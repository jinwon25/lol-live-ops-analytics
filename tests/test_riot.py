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
            match = synthetic_match(); match['info'].update(change)
            self.assertIsNone(normalize_match(match, 'synthetic-self'))
        match = synthetic_match(); match['info']['participants'][0]['teamPosition'] = ''
        self.assertIsNone(normalize_match(match, 'synthetic-self'))

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
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('192.0.2.10',50000)), base_url='http://127.0.0.1') as remote:
            self.assertEqual((await remote.get('/api/riot/status')).status_code, 403)


if __name__ == '__main__':
    unittest.main()
