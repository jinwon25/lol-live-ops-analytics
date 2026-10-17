"""로컬 임시 서버로 주요 UI 흐름을 검증한다. playwright + Chromium 필요."""

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx

from scripts.check_service_readiness import inspect_service
from service.local_coach import CoachInput, validate_choice
from service.match_report import match_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshot', type=Path, help='선택: 검증 후 보드 화면 PNG 경로')
    args = parser.parse_args()
    screenshot_path = args.screenshot.resolve() if args.screenshot else None
    if screenshot_path:
        if not screenshot_path.is_relative_to(ROOT):
            raise ValueError('스크린샷은 저장소 내부 경로를 사용하세요.')
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    with socket.socket() as socket_:
        socket_.bind(('127.0.0.1', 0))
        port = socket_.getsockname()[1]
    command = [
        sys.executable,
        '-m',
        'uvicorn',
        'service.main:app',
        '--host',
        '127.0.0.1',
        '--port',
        str(port),
        '--log-level',
        'error',
    ]
    server = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    try:
        base = f'http://127.0.0.1:{port}'
        for _ in range(50):
            try:
                with urlopen(base + '/api/overview', timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError('검증 서버 시작 실패')
        with httpx.Client(timeout=5, trust_env=False) as client:
            readiness = inspect_service(base, client.get)
        assert readiness['status'] != 'failed', readiness
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 1050})
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            # 개인 기본값을 공개 스크린샷·모의 테스트에서 제외한다.
            page.route('**/api/riot/preferences', lambda route: route.fulfill(json={}))
            page.route(
                '**/api/riot/coach/status',
                lambda route: route.fulfill(
                    json={'available': True, 'stage': 'experimental', 'model': 'synthetic-model'}
                ),
            )
            page.goto(base)
            assert page.locator('#tab-review').get_attribute('aria-selected') == 'true'
            assert page.locator('#review-form, .manual-review').count() == 0, '직접 입력 경로를 제거한다'
            assert page.locator('nav [role=tab]').count() == 3
            page.evaluate("document.fonts.load('500 14px \"Pretendard Variable\"')")
            assert page.evaluate("document.fonts.check('500 14px \"Pretendard Variable\"')")
            page.locator('#tab-overview').click()
            page.wait_for_function("document.getElementById('data-status').textContent.includes('KR 완료 전적')")
            assert page.locator('#overview-metrics .metric').count() == 3
            page.locator('#tab-champions').click()
            page.locator('#show-champion-guide').click()
            assert page.locator('#champion-detail').is_hidden(), '선택 전에는 빈 상세 칼럼을 두지 않는다'
            page.locator('#champion-search').fill('Ezreal')
            page.locator('#champion-list button').click()
            page.wait_for_function(
                "document.getElementById('champion-detail').textContent.includes('과거 코호트 관측')"
            )
            assert page.locator('#champion-detail table tbody tr').count() > 0
            page.get_by_role('button', name='챔피언 상세 닫기', exact=True).click()
            assert page.locator('#champion-detail').is_hidden()
            assert page.locator('#champion-list button').evaluate('(el)=>el===document.activeElement')
            page.locator('#champion-list button').click()
            page.wait_for_function("!document.getElementById('champion-detail').hidden")
            page.locator('#champion-search').fill('not-a-champion')
            assert page.locator('#champion-list').inner_text() == '검색 결과가 없습니다.'
            page.locator('#tab-review').click()
            # 제거한 입력 화면이 과거 초안을 지우거나 다시 저장하지 않는다.
            page.evaluate("localStorage.setItem('lol-review-draft-v1', 'preserved-legacy-draft')")
            page.reload()
            page.wait_for_function("document.querySelectorAll('#champion-list button').length > 1")
            assert page.evaluate("localStorage.getItem('lol-review-draft-v1')") == 'preserved-legacy-draft'
            page.evaluate(
                "localStorage.setItem('lol-insight-notes-v1', JSON.stringify([null,{date:'모의 날짜',text:'보존할 노트'}]))"
            )
            page.locator('#practice-note').fill('<img src=x onerror=alert(1)>')
            page.locator('#note-form button').click()
            assert page.locator('#practice-list img').count() == 0
            assert '<img' in page.locator('#practice-list').inner_text()
            page.reload()
            page.locator('#tab-overview').click()
            page.locator('#tab-review').click()
            assert '<img' in page.locator('#practice-list').inner_text()
            assert '보존할 노트' in page.locator('#practice-list').inner_text()
            page.locator('#clear-notes').click()
            assert page.locator('#practice-list li').count() == 0
            # 저장 순서와 경기 일시가 다르고 다른 챔피언·패치가 섞인 모의 기록.
            result = page.evaluate('''() => {
              const j = window.ReviewJournal;
              const base = {context:{region:'KR',queue:'RANKED_SOLO',patch:'16.19',tier:'GOLD',role:'BOT',champion_id:'Ezreal',champion_name:'이즈리얼',played_at:'2026-09-20T12:00:00Z'},metrics:{gpm:100,dpm:200,vision_per_minute:1,kill_participation:null},focus:'vision',is_example:false,scene:'모의 관찰',action:'모의 행동'};
              localStorage.setItem('lol-ranked-reviews-v1', '[]');
              for (const day of [5,0,4,1,3,2]) { const r = structuredClone(base); r.context.played_at = `2026-09-${20+day}T12:00:00Z`; r.metrics.gpm = (day+1)*100; j.save(r); }
              const foreign = structuredClone(base); foreign.context.patch = '16.18'; foreign.metrics.gpm=9999; j.save(foreign);
              const different = structuredClone(base); different.context.champion_id='Lucian'; j.save(different);
              let exampleRejected = false;
              try {j.save({...base,is_example:true});} catch {exampleRejected=true;}
              const updated = j.save(base), all = j.read(), comparison = j.compare(all,j.group(base.context));
              localStorage.setItem('lol-ranked-reviews-v1',JSON.stringify([...all,{garbage:true},{...base,is_example:true}]));
              const count = j.read().length;
              localStorage.setItem('lol-ranked-reviews-v1',JSON.stringify(j.read()));
              return {count, matching:comparison.count,recent:comparison.metrics.gpm.recent.value,previous:comparison.metrics.gpm.previous.value,kp:comparison.metrics.kill_participation.recent,exampleRejected,updated};
            }''')
            assert result == {
                'count': 8,
                'matching': 6,
                'recent': 500,
                'previous': 200,
                'kp': {'value': None, 'n': 0},
                'exampleRejected': True,
                'updated': True,
            }, result
            page.reload()
            page.locator('#tab-overview').click()
            page.wait_for_function("document.querySelectorAll('#session-list li').length === 8")
            assert page.locator('.analysis-layout').evaluate(
                '(report)=>report.nextElementSibling.classList.contains("board-layout")'
            ), '분석의 시각·DOM 순서 일치'
            page.locator('#comparison-group').select_option('KR|RANKED_SOLO|16.19|GOLD|Ezreal|BOT')
            assert page.locator('#self-comparison table').count() == 1
            assert page.locator('#personal-analysis .trend-column').count() == 6
            assert '최근 평균 500' in page.locator('#personal-analysis').inner_text()
            page.locator('#report-metric').select_option('kill_participation')
            assert '평균을 계산할 수 없습니다.' in page.locator('#personal-analysis').inner_text()
            assert page.locator('#personal-analysis .trend-column .value').all_text_contents() == ['—'] * 6
            page.locator('#report-metric').select_option('gpm')
            page.locator('#next-game-tasks').get_by_role('button', name='행동 노트에 가져오기').first.click()
            assert page.locator('#practice-note').input_value() == '모의 행동'
            assert page.locator('#practice-note').evaluate('(el)=>el===document.activeElement')
            assert page.evaluate("localStorage.getItem('lol-review-draft-v1')") == 'preserved-legacy-draft'
            page.locator('#note-form button').click()
            assert '모의 행동' in page.locator('#practice-list').inner_text()
            page.locator('#tab-overview').click()
            page.locator('#next-game-tasks').get_by_role('button', name='기록 열어 돌아보기').first.click()
            assert page.locator('#session-list form').count() == 1
            page.locator('#session-list form').get_by_role('button', name='취소').click()
            # 과거 버전의 기록을 불러와도 원본 관찰·행동은 HTML로 실행하지 않는다.
            page.evaluate('''() => {
              const j = window.ReviewJournal, base = j.read()[0];
              j.save({...base,context:{...base.context,played_at:'2026-09-26T11:00:00Z'},scene:'<img src=x onerror=alert(1)>',action:'합류 위치 확인'});
            }''')
            page.reload()
            page.locator('#tab-overview').click()
            page.wait_for_function("document.querySelectorAll('#session-list li').length === 9")
            assert page.locator('#session-list li').count() == 9
            assert page.locator('#session-list [onerror], #session-list img[src=x]').count() == 0
            assert page.locator('#session-list img.champion-portrait').count() == 9
            page.wait_for_function(
                "[...document.querySelectorAll('#session-list img')].every(i => i.complete && i.naturalWidth > 0)"
            )
            page.locator('#session-list').get_by_role('button', name='이 경기 삭제').first.click()
            assert page.locator('#session-list li').count() == 8
            page.locator('#undo-delete').click()
            assert page.locator('#session-list li').count() == 9
            page.locator('#session-list').get_by_role('button', name='이 경기 삭제').first.click()
            assert page.locator('#session-list li').count() == 8
            # 다운로드한 파일을 다시 선택해 미리보기·비파괴 병합·실패 보존을 확인.
            page.locator('summary').get_by_text('경기 기록 백업·복원').click()
            with page.expect_download() as downloaded:
                page.locator('#export-journal').click()
            backup = Path(downloaded.value.path()).read_bytes()
            assert len(json.loads(backup)['records']) == 8
            page.locator('#session-list').get_by_role('button', name='이 경기 삭제').first.click()
            assert page.locator('#session-list li').count() == 7
            page.locator('#import-journal').set_input_files(
                {'name': 'invalid.json', 'mimeType': 'application/json', 'buffer': b'{bad'}
            )
            page.wait_for_function("document.getElementById('backup-status').textContent.includes('읽을 수 없습니다')")
            assert page.locator('#restore-journal').is_disabled()
            assert page.locator('#session-list li').count() == 7
            page.locator('#import-journal').set_input_files(
                {'name': 'backup.json', 'mimeType': 'application/json', 'buffer': backup}
            )
            page.wait_for_function(
                "document.getElementById('backup-status').textContent.includes('미리보기: 추가 1개')"
            )
            assert page.locator('#session-list li').count() == 7
            page.locator('#restore-journal').click()
            assert page.locator('#session-list li').count() == 8
            assert page.locator('#backup-status').inner_text().startswith('복원 완료')
            page.locator('#journal-search').fill('모의 관찰')
            assert page.locator('#session-list li').count() == 8
            page.locator('#journal-search').fill('없는 장면')
            assert page.locator('#session-list li').count() == 0
            page.locator('#journal-search').fill('')
            original_context = page.evaluate('window.ReviewJournal.read().at(-1).context')
            original_metrics = page.evaluate('window.ReviewJournal.read().at(-1).metrics')
            page.locator('#session-list').get_by_role('button', name='복기 기록 수정').first.click()
            if screenshot_path:
                page.locator('#session-list form').scroll_into_view_if_needed()
                page.screenshot(path=str(screenshot_path.with_name(screenshot_path.stem + '-edit.png')))
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), '모바일 기록 수정'
                page.locator('#session-list form').scroll_into_view_if_needed()
                page.screenshot(path=str(screenshot_path.with_name(screenshot_path.stem + '-mobile-edit.png')))
                page.set_viewport_size({'width': 1440, 'height': 1050})
            page.locator('#session-list form').get_by_label('다음 경기에서 확인할 행동').fill('취소할 수정')
            page.locator('#session-list form').get_by_role('button', name='취소').click()
            assert '취소할 수정' not in page.locator('#session-list').inner_text()
            page.locator('#session-list').get_by_role('button', name='복기 기록 수정').first.click()
            page.locator('#session-list form').get_by_label('다음 경기에서 확인할 행동').fill(
                '수정한 행동 <img src=x onerror=alert(1)>'
            )
            page.locator('#session-list form').get_by_label('복기 초점').select_option('resource')
            page.locator('#session-list form').get_by_label('행동 진행 상태').select_option('tried')
            page.locator('#session-list form').get_by_label('시도 후 돌아본 내용').fill('다음 교전에서 합류를 확인했다')
            page.locator('#session-list form').get_by_role('button', name='수정 저장').click()
            assert page.locator('#session-list li').count() == 8
            assert page.locator('#session-list [onerror], #session-list img[src=x]').count() == 0
            assert page.evaluate('window.ReviewJournal.read().at(-1).context') == original_context
            assert page.evaluate('window.ReviewJournal.read().at(-1).metrics') == original_metrics
            page.reload()
            page.locator('#tab-overview').click()
            page.wait_for_function("document.querySelectorAll('#session-list li').length === 8")
            assert '수정한 행동 <img' in page.locator('#session-list').inner_text()
            page.locator('#session-list details summary').first.click()
            assert '다음 교전에서 합류를 확인했다' in page.locator('#session-list').inner_text()
            page.locator('#journal-state').select_option('tried')
            assert page.locator('#session-list li').count() == 1
            page.locator('#journal-state').select_option('planned')
            assert page.locator('#session-list li').count() == 7
            page.locator('#journal-state').select_option('')
            page.locator('#journal-search').fill('수정한 행동')
            assert page.locator('#session-list li').count() == 1
            page.locator('#journal-search').fill('')
            # 같은 Origin의 다른 탭에서 바뀐 기록을 오래된 편집 화면으로 덮어쓰지 않음.
            page.locator('#session-list').get_by_role('button', name='복기 기록 수정').first.click()
            other = page.context.new_page()
            other.route('**/api/riot/preferences', lambda route: route.fulfill(json={}))
            other.goto(base)
            other.wait_for_function("document.querySelectorAll('#champion-list button').length > 1")
            other.evaluate(
                "const r = window.ReviewJournal.read().at(-1); window.ReviewJournal.save({...r,action:'다른 탭에서 쓴 행동'})"
            )
            page.wait_for_function("document.getElementById('journal-status').textContent.includes('다른 탭')")
            page.locator('#session-list form').get_by_label('다음 경기에서 확인할 행동').fill('오래된 화면의 수정')
            page.locator('#session-list form').get_by_role('button', name='수정 저장').click()
            assert '다른 탭에서 이 기록이 바뀌었습니다' in page.locator('#session-list form').inner_text()
            page.locator('#session-list form').get_by_role('button', name='취소').click()
            assert '다른 탭에서 쓴 행동' in page.locator('#session-list').inner_text()
            other.close()
            # 연결 UI는 네트워크 요청 없이 모의 공식 응답으로 확인.
            imported = {
                'champion_id': 'Ezreal',
                'champion_name': '이즈리얼',
                'role': 'BOT',
                'region': 'KR',
                'queue': 'RANKED_SOLO',
                'patch': '16.19',
                'played_at': '2026-09-25T12:00:37.123Z',
                'duration_minutes': 30.07,
                'gold': 12000,
                'damage': 21000,
                'vision': 24,
                'kills': 5,
                'assists': 8,
                'team_kills': 24,
                'tier': None,
                'win': True,
            }
            # 누락된 승패·데스도 목록을 깨뜨리거나 패배/0으로 표시하지 않는다.
            imported['win'] = None
            imported['deaths'] = None
            imported['report'] = match_report(imported)
            page.route(
                '**/api/riot/recent',
                lambda route: route.fulfill(
                    json={
                        'source': '모의 Riot API 응답',
                        'current_rank': {'tier': 'GOLD', 'rank': 'IV', 'leaguePoints': 30},
                        'skipped': 0,
                        'cached': False,
                        'caveat': '현재 랭크와 경기 당시 티어를 구분',
                        'items': [imported],
                    }
                ),
            )
            page.locator('#tab-review').click()
            page.locator('#riot-form input[name=game_name]').fill('synthetic-name')
            page.locator('#riot-form input[name=tag_line]').fill('KR1')
            page.locator('#riot-form button').click()
            page.wait_for_function("document.querySelectorAll('#riot-matches button').length === 1")
            page.wait_for_function(
                "document.querySelector('#auto-report').textContent.includes('수치에서 확인한 사실')"
            )
            assert page.locator('#auto-report .auto-report-metrics .metric').count() == 6
            assert '이즈리얼' in page.locator('#auto-report').inner_text()
            assert '결과 미확인' in page.locator('.match-select').inner_text()
            assert '5 / — / 8' in page.locator('.match-select').inner_text()
            assert page.locator('#auto-report .outcome').inner_text() == '결과 미확인'
            assert '0승 0패' in page.locator('.recent-summary').inner_text()
            assert '승률 —' in page.locator('.recent-summary').inner_text()
            assert '결과 미확인 1경기' in page.locator('.recent-summary').inner_text()
            page.locator('#auto-report').get_by_role('button', name='이 리포트 보관', exact=True).click()
            assert page.evaluate("JSON.parse(localStorage.getItem('lol-match-reports-v1')).length") == 1
            assert 'synthetic-name' not in page.evaluate("localStorage.getItem('lol-match-reports-v1')")
            # 모델 실행은 모의 응답으로 격리하고 실제 평가와 구분한다.
            model_requests = []

            def mock_coach(route):
                body = route.request.post_data_json
                model_requests.append(body)
                payload = CoachInput.model_validate(body)
                answer = validate_choice('{"focus_id":"resource","evidence_keys":["gpm"]}', payload)
                answer['model'] = 'synthetic-model'
                route.fulfill(json=answer)

            page.route('**/api/riot/coach', mock_coach)
            page.locator('[data-local-coach]').click()
            page.wait_for_function(
                "document.querySelector('.local-coach-panel').textContent.includes('synthetic-model')"
            )
            assert model_requests == [{'role': 'BOT', 'metrics': imported['report']['metrics']}]
            assert 'synthetic-name' not in json.dumps(model_requests)
            page.unroute('**/api/riot/coach')
            page.route(
                '**/api/riot/coach',
                lambda route: route.fulfill(status=503, json={'detail': '합성 모델 출력 검증 실패'}),
            )
            page.locator('[data-local-coach]').click()
            page.wait_for_function(
                "document.querySelector('.local-coach-panel').textContent.includes('출력 검증 실패')"
            )
            assert page.locator('#auto-report .auto-report-metrics .metric').count() == 6
            page.unroute('**/api/riot/coach')
            assert page.get_by_role('button', name='수치를 수정하며 복기하기', exact=True).count() == 0
            assert page.locator('#review-form, .manual-review').count() == 0
            assert page.evaluate("localStorage.getItem('lol-review-draft-v1')") == 'preserved-legacy-draft'
            page.locator('#tab-champions').click()
            page.locator('#show-champion-guide').click()
            page.locator('#tab-assistant').click()
            page.locator('#assistant-question').fill('최신 룬 빌드 추천은?')
            page.locator('#assistant-form button[type=submit]').click()
            page.wait_for_function(
                "document.getElementById('assistant-answer').textContent.includes('추가 자료가 필요한 답변')"
            )
            assert page.locator('#assistant-answer .source-list a').count() == 2
            assert page.locator('#assistant-answer .external-references a').count() == 2
            page.locator('#assistant-question').fill('내 전적에서 팀운이 문제야?')
            page.locator('#assistant-form button[type=submit]').click()
            page.wait_for_function("document.getElementById('assistant-answer').textContent.includes('브라우저')")
            assert 'EUN' not in page.locator('#assistant-answer').inner_text()
            page.evaluate('''() => {
              const j = window.ReviewJournal, base = j.read()[0];
              localStorage.setItem('lol-ranked-reviews-v1','[]');
              for (let i=0;i<21;i++) j.save({...base,context:{...base.context,played_at:new Date(Date.UTC(2026,8,1,0,i)).toISOString()},scene:`장기 보관 장면 ${i}`});
            }''')
            page.reload()
            page.locator('#tab-overview').click()
            page.wait_for_function("document.querySelectorAll('#session-list li').length === 20")
            page.locator('#more-sessions').click()
            assert page.locator('#session-list li').count() == 21
            page.locator('#journal-search').fill('장기 보관 장면 0')
            assert page.locator('#session-list li').count() == 1, '첫 화면 밖의 오래된 기록도 검색'
            page.locator('#journal-search').fill('')
            page.evaluate("localStorage.removeItem('lol-ranked-reviews-v1')")
            page.reload()
            page.locator('#tab-overview').click()
            page.wait_for_function("document.getElementById('data-status').textContent.includes('KR 완료 전적')")
            page.locator('#tab-overview').click()
            if screenshot_path:
                page.evaluate('window.scrollTo(0,0)')
                page.screenshot(path=str(screenshot_path), full_page=True)
            # 공개 자료는 개인 기록과 별도로 표시하고 시점 변경·출처 표시를 제공한다.
            page.locator('#tab-champions').click()
            page.locator('#show-champion-guide').click()
            page.locator('.reference-drawer > summary').click()
            page.wait_for_function("document.querySelector('#public-data-status').textContent.includes('검증 경기')")
            public_data = page.request.get(base + '/api/public-data').json()
            assert '개인 비교 기준 아님' in page.locator('#public-data-status').inner_text()
            assert page.locator('#public-flow-table tbody tr').count() == 5
            before = page.evaluate("localStorage.getItem('lol-ranked-reviews-v1')")
            page.locator('#public-phase').select_option('80')
            selected = next(item for item in public_data['flow']['phases'] if item['phase'] == 80)
            assert f"{selected['median_elapsed_minutes']:g}분" in page.locator('#public-flow-metrics').inner_text()
            assert before == page.evaluate("localStorage.getItem('lol-ranked-reviews-v1')"), (
                '공개 표본은 개인 기록에 섞이지 않는다'
            )
            page.locator('.public-provenance > summary').click()
            assert (
                page.locator('#public-flow-source a').first.get_attribute('href')
                == 'https://zenodo.org/records/8303397'
            )
            assert 'CC BY 4.0' in page.locator('#public-flow-source').inner_text()
            page.locator('.public-source-drawer > summary').click()
            assert page.locator('.data-source-row').count() == 13
            page.locator('.public-provenance > summary').click()
            page.locator('.public-source-drawer > summary').click()
            for width in [320, 390, 768, 1440]:
                page.set_viewport_size({'width': width, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('public-data', width)
            page.locator('.reference-drawer > summary').click()
            # 참고 자료 연결 실패가 계정 전적 조회를 막지 않는다.
            page.route('**/api/public-data', lambda route: route.fulfill(status=503, json={'detail': '합성 연결 실패'}))
            page.reload()
            page.locator('#tab-overview').click()
            page.wait_for_function(
                "document.querySelector('#public-data-status').textContent.includes('불러오지 못했습니다')"
            )
            page.locator('#tab-review').click()
            assert page.locator('#riot-form').is_visible()
            page.locator('#riot-form [name=game_name]').fill('synthetic-name')
            page.locator('#riot-form [name=tag_line]').fill('KR1')
            page.locator('#riot-form button[type=submit]').click()
            page.wait_for_function("document.querySelectorAll('#auto-report .metric').length === 6")
            page.unroute('**/api/public-data')
            page.reload()
            page.locator('#tab-overview').click()
            page.wait_for_function("document.querySelectorAll('#champion-list button').length > 1")
            # 숨겨진 탭에서도 모든 초상을 로드해 두고 전환 직후 표시한다.
            page.wait_for_function(
                "[...document.querySelectorAll('#champion-list img')].every(i => i.complete && i.naturalWidth > 0)"
            )
            assert page.locator('#champion-list img').count() == 173
            # 로컬 이미지 실패 시 공식 경로로 한 번 재시도한다. 외부 호출은 모의 응답.
            local_portrait = '**/assets/images/champions/Ezreal.png*'
            official_portrait = 'https://ddragon.leagueoflegends.com/cdn/*/img/champion/Ezreal.png'
            page.route(local_portrait, lambda route: route.abort())
            page.route(
                official_portrait,
                lambda route: route.fulfill(
                    path=str(ROOT / 'web/images/champions/Ezreal.png'),
                    content_type='image/png',
                    headers={'Cache-Control': 'no-store'},
                ),
            )
            page.reload()
            page.locator('#tab-overview').click()
            page.wait_for_function("document.querySelectorAll('#champion-list button').length > 1")
            page.locator('#tab-champions').click()
            page.locator('#show-champion-guide').click()
            page.locator('#champion-search').fill('Ezreal')
            page.wait_for_function(
                "(()=>{const i=document.querySelector('#champion-list img');return i.src.startsWith('https://ddragon.leagueoflegends.com/') && i.complete && i.naturalWidth>0 && !i.hidden})()"
            )
            assert page.locator('#champion-list button').inner_text() == '이즈리얼'
            # 양쪽 경로 모두 실패해도 이름과 선택은 보존하고 재시도를 반복하지 않는다.
            page.unroute(official_portrait)
            page.route(official_portrait, lambda route: route.abort())
            page.locator('#champion-search').fill('Ez')
            page.wait_for_function("document.querySelector('#champion-list img').hidden")
            page.locator('#champion-list button').click()
            page.wait_for_function("document.querySelector('#champion-detail h2')?.textContent==='이즈리얼'")
            page.unroute(local_portrait)
            page.unroute(official_portrait)
            page.locator('#champion-search').fill('')
            for width in [320, 390, 768, 1024, 1440, 1920, 2560]:
                page.set_viewport_size({'width': width, 'height': 844})
                for tab in ['overview', 'champions', 'review']:
                    page.locator('#tab-' + tab).click()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (
                        width,
                        tab,
                        page.evaluate(
                            "[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().width && e.getBoundingClientRect().right>innerWidth+1).map(e=>[e.tagName,e.id,e.className,e.getBoundingClientRect().right])"
                        ),
                    )
                    margins = page.locator('main').evaluate(
                        '(el)=>{const r=el.getBoundingClientRect();return [r.left,innerWidth-r.right]}'
                    )
                    assert abs(margins[0] - margins[1]) <= 1, (width, tab, margins)
            # 검색 단축키와 데스크톱/모바일 분류 필터는 같은 상태를 사용한다.
            page.set_viewport_size({'width': 1440, 'height': 844})
            page.locator('#tab-champions').click()
            page.locator('#show-champion-guide').click()
            page.keyboard.press('Control+k')
            assert page.locator('#champion-search').evaluate('(el)=>el===document.activeElement')
            page.locator('#champion-search').fill('Ezreal')
            marksman = page.locator('.champion-filter[data-category=Marksman]')
            marksman.click()
            assert marksman.get_attribute('aria-pressed') == 'true'
            assert marksman.evaluate('(el)=>el===document.activeElement'), '필터 선택 후 키보드 초점을 보존'
            assert page.locator('#champion-class').input_value() == 'Marksman'
            assert page.locator('#champion-list button').inner_text() == '이즈리얼'
            page.locator('.champion-filter[data-category=Fighter]').click()
            assert '검색 결과가 없습니다.' in page.locator('#champion-list').inner_text()
            page.set_viewport_size({'width': 390, 'height': 844})
            page.locator('#champion-class').select_option('Marksman')
            assert marksman.get_attribute('aria-pressed') == 'true'
            assert page.locator('#champion-list button').inner_text() == '이즈리얼'
            page.locator('#champion-search').fill('')
            page.locator('#champion-class').select_option('')
            page.locator('#tab-review').click()
            page.keyboard.press('Control+k')
            assert page.locator('#riot-form input[name=game_name]').evaluate('(el)=>el===document.activeElement')
            page.locator('#tab-overview').click()
            page.keyboard.press('Control+k')
            assert page.locator('#journal-search').evaluate('(el)=>el===document.activeElement')
            page.locator('#tab-overview').focus()
            page.keyboard.press('End')
            assert page.locator('#tab-champions').get_attribute('aria-selected') == 'true'
            page.keyboard.press('ArrowLeft')
            assert page.locator('#tab-overview').get_attribute('aria-selected') == 'true'
            # 현재 메타 보기는 과거 코호트와 분리하며 소표본 승률을 만들지 않는다.
            mock_meta = {
                'available': True,
                'stale': False,
                'scope': {'patch': '16.19'},
                'games': 100,
                'collected_at': '2026-10-04T12:00:00Z',
                'period': {'first': '2026-10-01T12:00:00Z', 'last': '2026-10-04T12:00:00Z'},
                'role_denominators': {'BOT': 200, 'TOP': 200},
                'minimum_games': 30,
                'caveats': ['화면 검증용 합성 표본'],
                'sources': [],
                'items': [
                    {
                        'champion_id': 'Ezreal',
                        'role': 'BOT',
                        'games': 50,
                        'wins': 30,
                        'win_rate': 60,
                        'interval': [46.2, 72.4],
                        'pick_rate': 25,
                        'ban_rate': 5,
                        'signal': 'uncertain',
                    },
                    {
                        'champion_id': 'Jhin',
                        'role': 'BOT',
                        'games': 40,
                        'wins': 25,
                        'win_rate': 62.5,
                        'interval': [47, 75.8],
                        'pick_rate': 20,
                        'ban_rate': 2,
                        'signal': 'uncertain',
                    },
                    {
                        'champion_id': 'Lucian',
                        'role': 'BOT',
                        'games': 20,
                        'wins': 10,
                        'win_rate': None,
                        'interval': None,
                        'pick_rate': 10,
                        'ban_rate': 1,
                        'signal': 'small_sample',
                    },
                    {
                        'champion_id': 'Yone',
                        'role': 'TOP',
                        'games': 35,
                        'wins': 21,
                        'win_rate': 60,
                        'interval': [43.6, 74.4],
                        'pick_rate': 17.5,
                        'ban_rate': 12,
                        'signal': 'uncertain',
                    },
                ],
            }
            page.route('**/api/meta', lambda route: route.fulfill(json=mock_meta))
            page.reload()
            page.wait_for_function("document.querySelectorAll('#champion-list button').length>1")
            page.locator('#tab-champions').click()
            assert page.locator('#meta-panel').is_visible()
            page.wait_for_function("document.querySelectorAll('#meta-table tbody tr').length===2")
            page.keyboard.press('Control+k')
            assert page.locator('#meta-search').evaluate('(el)=>el===document.activeElement')
            page.locator('#meta-minimum').uncheck()
            assert page.locator('#meta-table tbody tr').count() == 3
            assert '30회 미만' in page.locator('#meta-table tbody tr').last.inner_text()
            assert '—' in page.locator('#meta-table tbody tr').last.inner_text()
            page.locator('#meta-minimum').check()
            page.locator('#meta-sort').select_option('lower')
            assert '진' in page.locator('#meta-table tbody tr').first.inner_text()
            page.locator('#meta-search').fill('Ezreal')
            assert page.locator('#meta-table tbody tr').count() == 1
            page.locator('#meta-search').fill('not-a-champion')
            assert '조건에 맞는 챔피언이 없습니다' in page.locator('#meta-table').inner_text()
            page.locator('#meta-search').fill('')
            page.locator('#meta-roles [data-role=TOP]').click()
            assert '요네' in page.locator('#meta-table tbody tr').inner_text()
            page.locator('#meta-roles [data-role=BOT]').click()
            page.locator('#meta-table .meta-champion').first.click()
            page.wait_for_function("document.querySelector('#champion-detail h2')?.textContent==='진'")
            assert page.locator('#champion-guide-panel').is_visible() and page.locator('#meta-panel').is_hidden()
            page.locator('#show-meta-data').click()
            for width in [320, 390, 768, 1024, 1440, 1920, 2560]:
                page.set_viewport_size({'width': width, 'height': 844})
                for view in ['show-meta-data', 'show-champion-guide']:
                    page.locator('#' + view).click()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), (width, view)
            # 팀 비교·타임라인은 한 번 요청하고 탭 이동에서 기존 요약을 보존한다.
            imported['timeline_ref'] = 'synthetic-reference'
            imported['scoreboard'] = [
                {
                    'champion_id': 'Ezreal',
                    'champion_name': '이즈리얼',
                    'role': 'BOT',
                    'is_self': True,
                    'is_ally': True,
                    'kills': 5,
                    'deaths': None,
                    'assists': 8,
                    'gold': 12000,
                    'damage': 21000,
                    'vision': 24,
                }
            ]
            timeline_requests = []

            def mock_timeline(route):
                timeline_requests.append(route.request.url)
                route.fulfill(
                    json={
                        'available': True,
                        'points': [
                            {
                                'minute': 0,
                                'gold': 500,
                                'opponent_gold': 500,
                                'gold_difference': 0,
                                'cs': 0,
                                'opponent_cs': 0,
                                'cs_difference': 0,
                            },
                            {
                                'minute': 10.01,
                                'gold': 4000,
                                'opponent_gold': 4200,
                                'gold_difference': -200,
                                'cs': 80,
                                'opponent_cs': 90,
                                'cs_difference': -10,
                            },
                        ],
                        'deaths': [9.999],
                        'caveat': '실제 시각을 흉내 낸 합성 프레임',
                    }
                )

            page.route('**/api/riot/timeline/*', mock_timeline)
            page.locator('#tab-review').click()
            page.locator('#riot-form [name=game_name]').fill('synthetic-name')
            page.locator('#riot-form [name=tag_line]').fill('DEMO')
            page.locator('#riot-form button[type=submit]').click()
            page.wait_for_function("document.querySelectorAll('.match-select').length===1")
            page.get_by_role('tab', name='팀 비교', exact=True).click()
            assert page.locator('.scoreboard-self').is_visible()
            page.get_by_role('tab', name='시간대별 흐름', exact=True).click()
            page.wait_for_selector('.timeline-chart')
            assert '10:00' in page.locator('#auto-report').inner_text(), '데스 분·초는 반올림 이월한다'
            page.get_by_role('tab', name='핵심 요약', exact=True).click()
            assert page.locator('.report-insights').is_visible()
            page.get_by_role('tab', name='시간대별 흐름', exact=True).click()
            assert len(timeline_requests) == 1
            page.get_by_role('tab', name='시간대별 흐름', exact=True).focus()
            page.keyboard.press('Home')
            assert page.locator('.report-insights').is_visible()
            page.locator('#recent-role').select_option('TOP')
            assert '해당 포지션 경기가 없습니다' in page.locator('#auto-report').inner_text()
            page.locator('#recent-role').select_option('')
            assert page.locator('.match-select[aria-pressed=true]').count() == 1
            for width in [320, 390, 768, 1024, 1440, 1920, 2560]:
                page.set_viewport_size({'width': width, 'height': 844})
                for name in ['핵심 요약', '팀 비교', '시간대별 흐름']:
                    page.get_by_role('tab', name=name, exact=True).click()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), (width, name)
                for select in page.locator('select:visible').all():
                    style = select.evaluate(
                        '(el)=>{const s=getComputedStyle(el);return {right:s.paddingRight,position:s.backgroundPosition,appearance:s.appearance}}'
                    )
                    assert style['right'] == '40px' and style['appearance'] == 'none', (width, style)
            # 조회 장애에서 이전 경기를 새 결과처럼 남기지 않고 재시도할 수 있다.
            page.set_viewport_size({'width': 1440, 'height': 1050})
            page.unroute('**/api/riot/recent')
            for code, detail, headers in [(503, '합성 연결 실패', {}), (429, '합성 요청 제한', {'Retry-After': '17'})]:
                page.route(
                    '**/api/riot/recent',
                    lambda route, request, code=code, detail=detail, headers=headers: route.fulfill(
                        status=code, json={'detail': detail}, headers=headers
                    ),
                )
                page.locator('#riot-form button[type=submit]').click()
                page.wait_for_function("document.getElementById('riot-error').textContent.length > 0")
                assert detail in page.locator('#riot-error').inner_text()
                if code == 429:
                    assert '17초' in page.locator('#riot-error').inner_text()
                assert page.locator('#riot-form button[type=submit]').is_enabled()
                assert page.locator('.match-select, #auto-report .metric').count() == 0
                assert page.locator('#account-summary').is_hidden()
                page.unroute('**/api/riot/recent')
            page.route(
                '**/api/riot/recent',
                lambda route: route.fulfill(
                    json={
                        'source': '합성 빈 응답',
                        'current_rank': None,
                        'skipped': 0,
                        'cached': False,
                        'caveat': '모의 응답',
                        'items': [],
                    }
                ),
            )
            page.locator('#riot-form button[type=submit]').click()
            page.wait_for_function("!document.querySelector('#riot-form button[type=submit]').disabled")
            assert page.locator('.match-select, #auto-report .metric').count() == 0
            page.unroute('**/api/riot/recent')
            page.route(
                '**/api/riot/recent',
                lambda route: route.fulfill(
                    json={
                        'source': '합성 복구 응답',
                        'current_rank': None,
                        'skipped': 0,
                        'cached': False,
                        'caveat': '모의 응답',
                        'items': [imported],
                    }
                ),
            )
            page.locator('#riot-form button[type=submit]').click()
            page.wait_for_function("document.querySelectorAll('#auto-report .metric').length===6")
            assert page.locator('#riot-error').inner_text() == ''
            assert not errors, errors
            browser.close()
        print(
            'UI 검증 통과: 3개 주 메뉴·자동 리포트/보관·로컬 폰트·기존 초안 보존·기록/검색/수정/삭제 취소·다른 탭 충돌·백업/복원·조건별 추이/평균/KP 미정의·과제 재사용·API 모의 가져오기·이미지 로딩/실패 대응·320~2560px 가로 넘침/대칭 여백·키보드 메뉴/상세 초점 복귀'
        )
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == '__main__':
    main()
