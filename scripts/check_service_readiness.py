"""계정 조회·모델 실행 없이 로컬 웹서비스의 기본 연결을 점검한다."""

import argparse
import json
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        path = (
            attrs.get('src')
            if tag == 'script'
            else attrs.get('href')
            if tag == 'link' and attrs.get('rel') == 'stylesheet'
            else None
        )
        if path:
            if not path.startswith('/assets/') or urlparse(path).netloc:
                raise ValueError('로컬 정적 파일 경로가 아닙니다.')
            self.paths.add(path)


def local_base(value):
    parsed = urlparse(value)
    if (
        parsed.scheme != 'http'
        or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
        or parsed.username
        or parsed.password
        or parsed.path not in {'', '/'}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError('계정·쿼리 없는 로컬 HTTP 서버 주소를 사용하세요.')
    return value.rstrip('/')


def inspect_service(base, get):
    base = local_base(base)
    checks = []

    def check(name, path, validate, optional=False):
        try:
            response = get(base + path)
            response.raise_for_status()
            ready = validate(response)
            if not ready and not optional:
                raise ValueError('응답 구조나 필수 자료가 올바르지 않습니다.')
            checks.append({'name': name, 'status': 'ok' if ready else 'limited'})
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            checks.append({'name': name, 'status': 'limited' if optional else 'failed'})

    assets = Assets()

    def home(response):
        assets.feed(response.text)
        return len(assets.paths) >= 6 and 'no-cache' in response.headers.get('cache-control', '')

    check('화면과 정적 파일 목록', '/', home)
    for path in sorted(assets.paths):

        def valid_asset(response, path=path):
            mime = response.headers.get('content-type', '')
            expected = 'css' if path.endswith('.css') else 'javascript'
            return (
                bool(response.content) and expected in mime and 'no-cache' in response.headers.get('cache-control', '')
            )

        check('정적 파일 ' + path.rsplit('/', 1)[-1], path, valid_asset)
    check(
        '기초 분석·공식 자료',
        '/api/overview',
        lambda r: bool(r.json()['static_data']['version'] and r.json()['segments']),
    )
    check('챔피언 목록', '/api/champions', lambda r: bool(r.json()['items']))
    check(
        '현재 패치 표본',
        '/api/meta',
        lambda r: bool(r.json().get('available') and not r.json().get('stale')),
        optional=True,
    )
    check(
        '공개 참고 분석',
        '/api/public-data',
        lambda r: bool(r.json()['flow']['phases'] and r.json()['sources']),
        optional=True,
    )
    check(
        '전적 연결 설정 (키 유효성 미검증)',
        '/api/riot/status',
        lambda r: r.json()['configured'] is True and 'no-store' in r.headers.get('cache-control', ''),
        optional=True,
    )
    check(
        '로컬 AI 설치 (실행·품질 미검증)',
        '/api/riot/coach/status',
        lambda r: r.json()['available'] is True,
        optional=True,
    )
    state = (
        'failed'
        if any(c['status'] == 'failed' for c in checks)
        else 'limited'
        if any(c['status'] == 'limited' for c in checks)
        else 'ok'
    )
    return {
        'status': state,
        'checks': checks,
        'scope': '계정 요청·키 출력·모델 실행 없이 로컬 연결만 검사. 실제 전적 수집·AI 품질·공개 운영 준비를 보장하지 않습니다.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8001')
    args = parser.parse_args()
    try:
        local_base(args.base)
    except ValueError as error:
        parser.error(str(error))
    with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
        result = inspect_service(args.base, client.get)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
