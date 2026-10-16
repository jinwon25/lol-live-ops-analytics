import unittest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from service.main import app


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ability_patch=patch('service.main.abilities',new=AsyncMock(return_value={'available':False,'skills':[]}))
        cls.ability_patch.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.ability_patch.stop()

    def test_overview_separates_static_from_match_data(self):
        data = self.client.get('/api/overview').json()
        self.assertFalse(data['live_matches_connected'])
        self.assertFalse(data['match_scope']['is_current_match_data'])
        self.assertEqual(data['match_scope']['patches'], ['15.1', '15.3'])
        self.assertTrue(data['static_data']['source_url'].startswith('https://ddragon.leagueoflegends.com/'))

    def test_champion_search_and_unknown_id(self):
        self.assertEqual(self.client.get('/api/champions?q=Ezreal').json()['items'][0]['id'], 'Ezreal')
        self.assertEqual(self.client.get('/api/champions/does-not-exist').status_code, 404)
        self.assertIsNone(self.client.get('/api/champions/Ezreal').json()['current_win_rate'])

    def test_current_recommendation_is_not_invented(self):
        with patch('service.meta.current_meta',return_value={'available':False}):
            result = self.client.post('/api/assistant', json={'question': '최신 추천 챔피언은?'}).json()
        self.assertEqual(result['status'], 'insufficient_data')
        self.assertTrue(result['sources'])

    def test_historic_identifier_case_difference_is_matched(self):
        data = self.client.get('/api/champions/Fiddlesticks').json()
        self.assertTrue(data['history'])
        self.assertTrue(all(row['champion_en'] == 'FiddleSticks' for row in data['history']))

    def test_current_meta_answer_has_frontend_scope_and_stale_guard(self):
        sample={'available':True,'stale':False,'scope':{'patch':'16.19','region':'KR'},'games':100,
                'items':[{'champion_id':'Ezreal','role':'BOT','games':50,'win_rate':60,'interval':[46.2,72.4]}],
                'sources':[{'title':'Riot','url':'https://developer.riotgames.com/apis'}],'caveats':['제한 표본']}
        with patch('service.meta.current_meta',return_value=sample):
            result=self.client.post('/api/assistant',json={'question':'최신 추천 챔피언은?','champion_id':'Ezreal'}).json()
            self.assertEqual(result['status'],'documented')
            self.assertEqual(result['scope']['patches'],['16.19'])
            self.assertIn('cohort',result['scope'])
            self.assertIn('확정적인 챔피언 티어는 아닙니다',result['answer'])
        with patch('service.meta.current_meta',return_value={**sample,'stale':True}):
            result=self.client.post('/api/assistant',json={'question':'최신 추천 챔피언은?'}).json()
            self.assertEqual(result['status'],'insufficient_data')

    def test_historic_answer_has_scope_and_evidence(self):
        result = self.client.post('/api/assistant', json={'question': '패치 변화 설명', 'champion_id': 'Ezreal'}).json()
        self.assertEqual(result['scope']['region'], 'EUN')
        self.assertIn('15.1', result['answer'])
        self.assertTrue(result['sources'])

    def test_unknown_question_and_large_input(self):
        self.assertEqual(self.client.post('/api/assistant', json={'question': 'xxxxxxxx'}).json()['status'], 'insufficient_data')
        self.assertEqual(self.client.post('/api/assistant', json={'question': 'x' * 301}).status_code, 422)

    def test_review_zero_team_kills_is_undefined(self):
        payload = dict(role='MID', duration_minutes=20, gold=8000, damage=12000, vision=15,
                       kills=0, assists=0, team_kills=0, is_example=True)
        response = self.client.post('/api/review', json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['metrics']['kill_participation'])
        self.assertEqual(response.json()['source'], '합성 예제')
        self.assertIsNone(response.json()['peer_percentile'])

    def test_review_invalid_counts_and_duration(self):
        payload = dict(role='BOT', duration_minutes=20, gold=8000, damage=10000, vision=5,
                       kills=8, assists=5, team_kills=10)
        self.assertEqual(self.client.post('/api/review', json=payload).status_code, 422)

        payload.update(kills=0, assists=0, duration_minutes=0)
        self.assertEqual(self.client.post('/api/review', json=payload).status_code, 422)

    def test_personal_record_requires_context_and_excludes_examples(self):
        payload = dict(role='BOT', duration_minutes=20, gold=8000, damage=12000, vision=15,
                       kills=0, assists=0, team_kills=0)
        self.assertFalse(self.client.post('/api/review', json=payload).json()['personal_record_eligible'])
        payload.update(champion_id='Ezreal', region='KR', queue='RANKED_SOLO', tier='SILVER',
                       patch='16.19', played_at='2026-09-25T20:00:00+09:00', focus='resource')
        data = self.client.post('/api/review', json=payload).json()
        self.assertTrue(data['personal_record_eligible'])
        self.assertEqual(data['focus']['id'], 'resource')
        payload['is_example'] = True
        self.assertFalse(self.client.post('/api/review', json=payload).json()['personal_record_eligible'])

    def test_review_time_zone_future_and_unknown_champion(self):
        payload = dict(role='BOT', duration_minutes=20, gold=8000, damage=12000, vision=15,
                       kills=0, assists=0, team_kills=0, played_at='2026-09-25T20:00:00')
        self.assertEqual(self.client.post('/api/review', json=payload).status_code, 422)
        payload['played_at'] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        self.assertEqual(self.client.post('/api/review', json=payload).status_code, 422)
        payload.update(played_at=None, champion_id='not-valid')
        self.assertEqual(self.client.post('/api/review', json=payload).status_code, 404)

    def test_personal_question_does_not_use_historic_cohort(self):
        result = self.client.post('/api/assistant', json={'question':'내 전적에서 팀운이 문제야?'}).json()
        self.assertEqual(result['status'], 'insufficient_data')
        self.assertEqual(result['scope']['patches'], [])
        self.assertNotIn('EUN', result['answer'])

    def test_overview_and_champion_latency_under_5ms(self):
        # Warm up route/cache once, then verify server processing time (X-Response-Time-Ms) <= 5ms
        self.client.get('/api/overview')
        self.client.get('/api/champions/Ezreal')

        overview_times = []
        champion_times = []
        for _ in range(10):
            r1 = self.client.get('/api/overview')
            self.assertEqual(r1.status_code, 200)
            overview_times.append(float(r1.headers['X-Response-Time-Ms']))

            r2 = self.client.get('/api/champions/Ezreal')
            self.assertEqual(r2.status_code, 200)
            champion_times.append(float(r2.headers['X-Response-Time-Ms']))

        overview_times.sort()
        champion_times.sort()
        self.assertLessEqual(overview_times[len(overview_times) // 2], 5.0)
        self.assertLessEqual(champion_times[len(champion_times) // 2], 5.0)

    def test_structured_json_request_logging(self):
        import io
        import json
        import logging
        from service.riot_transport import StructuredJsonFormatter

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(StructuredJsonFormatter())
        http_logger = logging.getLogger('lol_live_ops.http')
        http_logger.addHandler(handler)
        try:
            response = self.client.get('/api/overview', headers={'X-Trace-Id': 'trace-test-123'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get('X-Trace-Id'), 'trace-test-123')
            lines = [line for line in stream.getvalue().splitlines() if line.strip()]
            self.assertTrue(lines)
            payload = json.loads(lines[-1])
            self.assertEqual(payload['trace_id'], 'trace-test-123')
            self.assertIn('duration_ms', payload)
            self.assertLessEqual(payload['duration_ms'], 5.0)
            self.assertIn('riot_api_calls', payload)
            self.assertIn('rate_limit_remaining', payload)
            self.assertIn('cache_hit', payload)
            self.assertEqual(payload['path'], '/api/overview')
        finally:
            http_logger.removeHandler(handler)


    def test_review_sync_crud_endpoints(self):
        import tempfile
        from pathlib import Path
        from service.evidence import ReviewSyncStore

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_store = ReviewSyncStore(db_path=Path(tmpdir) / 'sync_test.db')
            with patch('service.main.review_store', temp_store):
                created = self.client.post('/api/reviews/sync', json={
                    'client_id': 'client-alpha',
                    'champion_id': 'Ezreal',
                    'role': 'BOT',
                    'patch': '16.19',
                    'note': '초반 라인전 마나 관리 개선 필요',
                    'tags': ['laning', 'mana'],
                    'metrics': {'gold_per_min': 410},
                })
                self.assertEqual(created.status_code, 201)
                record = created.json()
                record_id = record['id']
                self.assertEqual(record['champion_id'], 'Ezreal')

                listed = self.client.get('/api/reviews/sync', params={'client_id': 'client-alpha'}).json()
                self.assertEqual(len(listed['items']), 1)

                updated = self.client.put(f'/api/reviews/sync/{record_id}', json={
                    'client_id': 'client-alpha',
                    'champion_id': 'Ezreal',
                    'role': 'BOT',
                    'patch': '16.19',
                    'note': '수정된 복기 노트',
                    'tags': ['updated'],
                    'metrics': {'gold_per_min': 435},
                })
                self.assertEqual(updated.status_code, 200)
                self.assertEqual(updated.json()['note'], '수정된 복기 노트')

                deleted = self.client.delete(f'/api/reviews/sync/{record_id}', params={'client_id': 'client-alpha'})
                self.assertEqual(deleted.status_code, 200)
                self.assertTrue(deleted.json()['deleted'])
                self.assertEqual(self.client.get(f'/api/reviews/sync/{record_id}').status_code, 404)

    def test_duckdb_adapter_queries_champion_history(self):
        from service.evidence import duckdb_adapter
        rows = duckdb_adapter.query_champion_history('Ezreal')
        self.assertTrue(rows)
        self.assertEqual(rows[0]['champion_en'], 'Ezreal')


if __name__ == '__main__':
    unittest.main()

