"""화면의 로컬 이미지 누락과 원본 해시·라이선스 누락을 확인한다."""

import hashlib
import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from service.main import app

ROOT = Path(__file__).resolve().parents[1]


class AssetsTest(unittest.TestCase):
    def test_image_delivery_and_updated_app_cache_policy(self):
        client = TestClient(app)
        for path in [
            '/',
            '/assets/app.js',
            '/assets/styles.css',
            '/assets/geng-theme.css',
            '/assets/journal.js',
            '/assets/draft.js',
            '/assets/analysis.js',
        ]:
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-cache')
        response = client.get('/assets/images/champions/Ezreal.png?v=16.19.1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'image/png')
        self.assertEqual(response.content, (ROOT / 'web/images/champions/Ezreal.png').read_bytes())

    def test_catalogue_portraits_and_manifest_integrity(self):
        catalogue = json.loads((ROOT / 'service/data/catalogue.json').read_text(encoding='utf-8'))
        assets = ROOT / 'web/images'
        manifest = json.loads((assets / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['version'], catalogue['version'])
        entries = {entry['path']: entry for entry in manifest['assets']}
        for champion in catalogue['champions']:
            self.assertIn(f'champions/{champion["id"]}.png', entries)
        for relative, entry in entries.items():
            file = (assets / relative).resolve()
            self.assertTrue(file.is_relative_to(assets.resolve()))
            data = file.read_bytes()
            self.assertEqual(len(data), entry['bytes'])
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'])
            self.assertTrue(
                entry['source'].startswith(
                    ('https://ddragon.leagueoflegends.com/', 'https://raw.githubusercontent.com/tabler/tabler-icons/')
                )
            )
        self.assertIn('MIT License', (assets / 'icons/LICENSE').read_text(encoding='utf-8'))
