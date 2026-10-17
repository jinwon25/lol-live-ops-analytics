import json
import unittest
from unittest.mock import patch

import httpx

from service.local_coach import CoachInput, LocalCoach, messages, validate_choice
from service.main import app


def metrics():
    return dict(gpm=400, dpm=700, vision_per_minute=0.8, kill_participation=None, cs_per_minute=6, damage_share=0.35)


class LocalCoachTests(unittest.IsolatedAsyncioTestCase):
    def test_verified_focus_uses_canonical_questions_and_known_evidence(self):
        payload = CoachInput(role='BOT', metrics=metrics())
        result = validate_choice(
            json.dumps({'focus_id': 'resource', 'evidence_keys': ['gpm', 'cs_per_minute']}), payload
        )
        self.assertEqual(result['stage'], 'experimental')
        self.assertTrue(result['questions'])
        self.assertEqual(result['label'], '파밍과 귀환 선택')
        self.assertNotIn('win', str(messages(payload)))
        fenced = '```json\n' + json.dumps({'focus_id': 'resource', 'evidence_keys': ['gpm']}) + '\n```'
        self.assertEqual(validate_choice(fenced, payload)['focus_id'], 'resource')
        with self.assertRaises(ValueError):
            validate_choice('제안입니다.\n' + fenced, payload)

    def test_unknown_missing_evidence_and_freeform_claims_are_rejected(self):
        payload = CoachInput(role='BOT', metrics=metrics())
        for raw in [
            'not json',
            json.dumps({'focus_id': 'carry_score', 'evidence_keys': ['gpm']}),
            json.dumps({'focus_id': 'resource', 'evidence_keys': ['kill_participation']}),
            json.dumps({'focus_id': 'resource', 'evidence_keys': ['gpm'], 'summary': 'invented fact'}),
            json.dumps({'focus_id': 'resource', 'evidence_keys': ['gpm', 'gpm']}),
        ]:
            with self.assertRaises((ValueError, TypeError)):
                validate_choice(raw, payload)

    async def test_local_api_does_not_accept_identity_or_invent_on_failure(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 50000)), base_url='http://127.0.0.1'
        ) as client:
            payload = {'role': 'BOT', 'metrics': metrics()}
            self.assertEqual(
                (await client.post('/api/riot/coach', json={**payload, 'puuid': 'private'})).status_code, 422
            )
            with patch('service.main.coach.choose', side_effect=RuntimeError('합성 모델 검증 실패')):
                response = await client.post('/api/riot/coach', json=payload)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertNotIn('questions', response.json())

    def test_worker_failure_is_controlled_and_lock_released(self):
        import subprocess
        from types import SimpleNamespace

        coach = LocalCoach()
        payload = CoachInput(role='BOT', metrics=metrics())
        with (
            patch('service.local_coach.selection', return_value={'model': 'Qwen3-0.6B'}),
            patch('service.local_coach.subprocess.run') as run,
        ):
            run.side_effect = subprocess.TimeoutExpired('worker', 75)
            with self.assertRaisesRegex(RuntimeError, '기본 리포트'):
                coach.choose(payload)
            self.assertFalse(coach.lock.locked())
            run.side_effect = None
            run.return_value = SimpleNamespace(
                returncode=0, stdout=json.dumps({'raw': '{"focus_id":"resource","evidence_keys":["gpm"]}'})
            )
            self.assertEqual(coach.choose(payload)['model'], 'Qwen3-0.6B')
            self.assertNotIn('RIOT_API_KEY', run.call_args.kwargs['env'])

    def test_quantized_output_failure_preserves_boundary_and_releases_lock(self):
        coach = LocalCoach()
        payload = CoachInput(role='BOT', metrics=metrics())
        with (
            patch('service.local_coach.selection', return_value={'model': 'Qwen3-4B-Q4_K_M'}),
            patch('service.quantized_coach.local_server') as server,
            patch('service.quantized_coach.generate') as generate,
        ):
            server.return_value.__enter__.return_value = ('local-client', None, 0)
            generate.return_value = ('{"focus_id":"vision","evidence_keys":["kill_participation"]}', 12)
            with self.assertRaisesRegex(RuntimeError, '검증하지 못했습니다'):
                coach.choose(payload)
            self.assertFalse(coach.lock.locked())
            generate.return_value = ('{"focus_id":"vision","evidence_keys":["vision_per_minute"]}', 12)
            self.assertEqual(coach.choose(payload)['model'], 'Qwen3-4B-Q4_K_M')

    async def test_async_daemon_inference_and_centralized_settings(self):
        import asyncio
        import os

        from service.config import Settings

        with patch.dict(
            os.environ,
            {
                'RIOT_API_KEY': '  test-key  ',
                'ALLOWED_ORIGINS': 'http://localhost:8001, http://127.0.0.1:8001',
                'ALLOW_REMOTE_ACCESS': 'false',
                'LLAMA_SERVER_URL': 'http://localhost:8080/',
            },
            clear=False,
        ):
            cfg = Settings()
            self.assertEqual(cfg.RIOT_API_KEY, 'test-key')
            self.assertFalse(cfg.ALLOW_REMOTE_ACCESS)
            self.assertEqual(cfg.LLAMA_SERVER_URL, 'http://localhost:8080')
            self.assertIn('http://localhost:8001', cfg.ALLOWED_ORIGINS)

        observed_paths = []

        async def mock_llama_daemon(request: httpx.Request) -> httpx.Response:
            observed_paths.append(request.url.path)
            await asyncio.sleep(0.01)
            return httpx.Response(
                200,
                json={
                    'choices': [{'message': {'content': '{"focus_id":"resource","evidence_keys":["gpm"]}'}}],
                    'usage': {'completion_tokens': 14},
                },
            )

        coach_instance = LocalCoach()
        payload = CoachInput(role='BOT', metrics=metrics())
        async with httpx.AsyncClient(transport=httpx.MockTransport(mock_llama_daemon)) as shared_client:
            coach_instance.set_client(shared_client)
            with patch('service.local_coach.selection', return_value={'model': 'Qwen3-4B-Q4_K_M'}):
                first, second = await asyncio.gather(
                    coach_instance.choose_async(payload),
                    coach_instance.choose_async(payload),
                )
        self.assertEqual(first['focus_id'], 'resource')
        self.assertEqual(second['model'], 'Qwen3-4B-Q4_K_M')
        self.assertEqual(observed_paths, ['/v1/chat/completions', '/v1/chat/completions'])
