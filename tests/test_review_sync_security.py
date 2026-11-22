import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from service.evidence import ReviewSyncStore
from service.main import app


class ReviewSyncSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_remote_sync_is_blocked_even_when_riot_remote_access_is_enabled(self):
        with patch.dict(os.environ, {'ALLOW_REMOTE_ACCESS': 'true'}):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=('198.51.100.10', 50000)),
                base_url='http://127.0.0.1',
            ) as client:
                for method, path in [
                    ('GET', ''),
                    ('POST', ''),
                    ('GET', '/synthetic'),
                    ('PUT', '/synthetic'),
                    ('DELETE', '/synthetic'),
                ]:
                    response = await client.request(method, '/api/reviews/sync' + path)
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')

    async def test_local_sync_rejects_cross_origin_and_public_forwarded_client(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 50000)),
            base_url='http://127.0.0.1',
        ) as client:
            for headers in [{'Origin': 'https://untrusted.example'}, {'X-Forwarded-For': '198.51.100.10'}]:
                response = await client.get('/api/reviews/sync', headers=headers)
                self.assertEqual(response.status_code, 403)

    async def test_client_partition_cannot_read_replace_or_delete_another_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewSyncStore(Path(directory) / 'synthetic.db')
            with patch('service.main.review_store', store):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 50000)),
                    base_url='http://127.0.0.1',
                ) as client:
                    record = {'record_id': 'synthetic', 'client_id': 'alpha', 'scene': '보존할 장면'}
                    self.assertEqual((await client.post('/api/reviews/sync', json=record)).status_code, 201)
                    path = '/api/reviews/sync/synthetic'
                    self.assertEqual((await client.get(path, params={'client_id': 'beta'})).status_code, 404)
                    self.assertEqual((await client.get(path)).status_code, 404)
                    self.assertEqual((await client.put(path, json={**record, 'client_id': 'beta'})).status_code, 404)
                    collision = await client.post('/api/reviews/sync', json={**record, 'client_id': 'beta'})
                    self.assertEqual(collision.status_code, 409)
                    self.assertEqual((await client.delete(path, params={'client_id': 'beta'})).status_code, 404)
                    response = await client.get(path, params={'client_id': 'alpha'})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()['scene'], '보존할 장면')
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                    updated = await client.put(path, json={**record, 'scene': '수정한 장면'})
                    self.assertEqual(updated.status_code, 200)
                    self.assertEqual(updated.json()['scene'], '수정한 장면')
