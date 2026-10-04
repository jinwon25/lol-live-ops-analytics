import unittest
from fastapi.testclient import TestClient
from service.main import app


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

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
        result = self.client.post('/api/assistant', json={'question': '최신 추천 챔피언은?'}).json()
        self.assertEqual(result['status'], 'insufficient_data')
        self.assertTrue(result['sources'])

    def test_historic_identifier_case_difference_is_matched(self):
        data = self.client.get('/api/champions/Fiddlesticks').json()
        self.assertTrue(data['history'])
        self.assertTrue(all(row['champion_en'] == 'FiddleSticks' for row in data['history']))

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


if __name__ == '__main__':
    unittest.main()
