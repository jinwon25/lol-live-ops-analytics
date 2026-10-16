import unittest
import httpx

from scripts.check_service_readiness import inspect_service, local_base


class ReadinessTests(unittest.TestCase):
    def diagnose(self, broken=None):
        def respond(request):
            path = request.url.path
            if path == broken:
                return httpx.Response(503, text='응답 본문이나 인증정보를 보고서에 포함하면 안 됩니다.')
            if path == '/':
                return httpx.Response(200, text=''.join(f'<script src="/assets/{i}.js"></script>' for i in range(6)), headers={'cache-control':'no-cache'})
            if path.startswith('/assets/'):
                return httpx.Response(200, text='// local asset', headers={'content-type':'application/javascript','cache-control':'no-cache'})
            data = {
                '/api/overview':{'static_data':{'version':'16.19.1'},'segments':[{}]},
                '/api/champions':{'items':[{}]},
                '/api/meta':{'available':False},
                '/api/public-data':{'flow':{'phases':[{}]},'sources':{'items':[{}]}},
                '/api/riot/status':{'configured':False},
                '/api/riot/coach/status':{'available':False},
            }
            return httpx.Response(200, json=data[path], headers={'cache-control':'no-store'})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            return inspect_service('http://127.0.0.1:8001', client.get)

    def test_optional_dependencies_do_not_block_basic_service(self):
        result = self.diagnose()
        self.assertEqual(result['status'], 'limited')
        self.assertFalse(any(c['status']=='failed' for c in result['checks']))

    def test_required_asset_or_analysis_failure_is_reported_without_body(self):
        for path in ['/assets/0.js', '/api/overview', '/api/champions']:
            result = self.diagnose(path)
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('응답 본문이나 인증정보', str(result))

    def test_optional_analysis_failure_is_separate_from_core_failure(self):
        self.assertEqual(self.diagnose('/api/public-data')['status'], 'limited')

    def test_external_or_identity_bearing_base_is_rejected_before_requests(self):
        for value in ['https://example.com','http://127.0.0.1:8001?key=secret','http://user:pass@localhost:8001','http://localhost:8001/account']:
            with self.assertRaises(ValueError):
                local_base(value)
