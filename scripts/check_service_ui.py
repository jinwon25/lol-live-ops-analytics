"""로컬 임시 서버로 주요 UI 흐름을 검증한다. playwright + Chromium 필요."""
import argparse
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshot', type=Path, help='선택: 검증 후 보드 화면 PNG 경로')
    args = parser.parse_args()
    with socket.socket() as socket_:
        socket_.bind(('127.0.0.1', 0))
        port = socket_.getsockname()[1]
    command = [sys.executable, '-m', 'uvicorn', 'service.main:app', '--host', '127.0.0.1', '--port', str(port), '--log-level', 'error']
    server = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        base = f'http://127.0.0.1:{port}'
        for _ in range(50):
            try:
                with urlopen(base + '/api/overview', timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError('검증 서버 시작 실패')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1050})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base)
            page.wait_for_function("document.getElementById('data-status').textContent.includes('실시간 전적 미연결')")
            assert page.locator('#overview-metrics .metric').count() == 3
            page.locator('#tab-champions').click()
            page.locator('#champion-search').fill('Ezreal')
            page.locator('#champion-list button').click()
            page.wait_for_function("document.getElementById('champion-detail').textContent.includes('과거 코호트 관측')")
            assert page.locator('#champion-detail table tbody tr').count() > 0
            page.locator('#champion-search').fill('not-a-champion')
            assert page.locator('#champion-list').inner_text() == '검색 결과가 없습니다.'
            page.locator('#tab-review').click()
            page.locator('#fill-example').click()
            page.locator('#review-form button[type=submit]').click()
            page.wait_for_function("document.getElementById('review-result').textContent.includes('합성 예제')")
            assert page.locator('#review-result').get_by_text('400', exact=True).count() == 1
            page.locator('input[name=team_kills]').fill('1')
            page.locator('#review-form button[type=submit]').click()
            page.wait_for_function("document.getElementById('review-error').textContent.length > 0")
            page.locator('#practice-note').fill('<img src=x onerror=alert(1)>')
            page.locator('#note-form button').click()
            assert page.locator('#practice-list img').count() == 0
            assert '<img' in page.locator('#practice-list').inner_text()
            page.reload()
            page.locator('#tab-review').click()
            assert '<img' in page.locator('#practice-list').inner_text()
            page.locator('#clear-notes').click()
            assert page.locator('#practice-list li').count() == 0
            page.locator('#tab-assistant').click()
            page.locator('#assistant-question').fill('최신 추천 챔피언은?')
            page.locator('#assistant-form button[type=submit]').click()
            page.wait_for_function("document.getElementById('assistant-answer').textContent.includes('추가 자료가 필요한 답변')")
            assert page.locator('#assistant-answer .source-list a').count() == 2
            page.locator('#tab-overview').click()
            if args.screenshot:
                path = args.screenshot.resolve()
                if not path.is_relative_to(ROOT):
                    raise ValueError('스크린샷은 저장소 내부 경로를 사용하세요.')
                path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(path), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            for tab in ['champions', 'review', 'assistant']:
                page.locator('#tab-' + tab).click()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), tab
            assert not errors, errors
            browser.close()
        print('UI 검증 통과: 보드·탐색·빈 검색·복기·입력 오류·안전한 노트 저장/삭제·근거 보류·모바일 4화면')
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == '__main__':
    main()
