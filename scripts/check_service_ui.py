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
            # 개인 기본값을 공개 스크린샷·모의 테스트에서 제외한다.
            page.route('**/api/riot/preferences', lambda route: route.fulfill(json={}))
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
            assert page.locator('#save-session').is_disabled()
            page.locator('input[name=gold]').fill('12500')
            page.locator('#review-form button[type=submit]').click()
            page.wait_for_function("document.getElementById('review-result').textContent.includes('416.7')")
            assert page.locator('#save-session').is_disabled(), '수정한 예제도 개인 기록에서 제외'
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
              return {count:j.read().length, matching:comparison.count,recent:comparison.metrics.gpm.recent.value,previous:comparison.metrics.gpm.previous.value,kp:comparison.metrics.kill_participation.recent,exampleRejected,updated};
            }''')
            assert result == {'count':8,'matching':6,'recent':500,'previous':200,'kp':{'value':None,'n':0},'exampleRejected':True,'updated':True}, result
            page.reload()
            page.wait_for_function("document.querySelectorAll('#session-list li').length === 8")
            page.locator('#comparison-group').select_option('KR|RANKED_SOLO|16.19|GOLD|Ezreal|BOT')
            assert page.locator('#self-comparison table').count() == 1
            # 원본 관찰과 행동 문구는 HTML로 실행하지 않음.
            page.locator('#tab-review').click()
            page.locator('#start-personal').click()
            fields = {'champion_id':'Ezreal','region':'KR','queue':'RANKED_SOLO','tier':'GOLD','role':'BOT','focus':'resource'}
            for name, value in fields.items():
                page.locator(f'#review-form select[name={name}]').select_option(value)
            values = {'patch':'16.19','played_at':'2026-09-26T20:00','duration_minutes':'30','gold':'12000','damage':'21000','vision':'24','kills':'5','assists':'8','team_kills':'24'}
            for name, value in values.items():
                page.locator(f'#review-form input[name={name}]').fill(value)
            page.locator('#review-form button[type=submit]').click()
            page.wait_for_function("!document.getElementById('save-session').disabled")
            page.locator('#scene-note').fill('<img src=x onerror=alert(1)>')
            page.locator('#next-action').fill('합류 위치 확인')
            page.locator('#save-session').click()
            assert page.locator('#save-status').inner_text().startswith('내 경기 기록을 저장')
            page.locator('#tab-overview').click()
            assert page.locator('#session-list li').count() == 9
            assert page.locator('#session-list img').count() == 0
            page.locator('#session-list button').first.click()
            assert page.locator('#session-list li').count() == 8
            # 연결 UI는 네트워크 요청 없이 모의 공식 응답으로 확인.
            page.route('**/api/riot/recent', lambda route: route.fulfill(json={
                'source':'모의 Riot API 응답','current_rank':{'tier':'GOLD','rank':'IV','leaguePoints':30},
                'skipped':0,'cached':False,'caveat':'현재 랭크와 경기 당시 티어를 구분',
                'items':[{'champion_id':'Ezreal','champion_name':'이즈리얼','role':'BOT','region':'KR','queue':'RANKED_SOLO','patch':'16.19','played_at':'2026-09-25T12:00:00Z','duration_minutes':30,'gold':12000,'damage':21000,'vision':24,'kills':5,'assists':8,'team_kills':24,'tier':None,'win':True}]}))
            page.locator('#tab-review').click()
            page.locator('#riot-form input[name=game_name]').fill('synthetic-name')
            page.locator('#riot-form input[name=tag_line]').fill('KR1')
            page.locator('#riot-form button').click()
            page.wait_for_function("document.querySelectorAll('#riot-matches button').length === 1")
            page.locator('#riot-matches button').click()
            assert page.locator('#review-form select[name=tier]').input_value() == ''
            assert page.locator('#review-form select[name=role]').input_value() == 'BOT'
            assert page.locator('#review-form input[name=patch]').input_value() == '16.19'
            page.locator('#tab-assistant').click()
            page.locator('#assistant-question').fill('최신 추천 챔피언은?')
            page.locator('#assistant-form button[type=submit]').click()
            page.wait_for_function("document.getElementById('assistant-answer').textContent.includes('추가 자료가 필요한 답변')")
            assert page.locator('#assistant-answer .source-list a').count() == 2
            assert page.locator('#assistant-answer .external-references a').count() == 2
            page.locator('#assistant-question').fill('내 전적에서 팀운이 문제야?')
            page.locator('#assistant-form button[type=submit]').click()
            page.wait_for_function("document.getElementById('assistant-answer').textContent.includes('브라우저')")
            assert 'EUN' not in page.locator('#assistant-answer').inner_text()
            page.evaluate("localStorage.removeItem('lol-ranked-reviews-v1')")
            page.reload()
            page.wait_for_function("document.getElementById('data-status').textContent.includes('실시간 전적 미연결')")
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
        print('UI 검증 통과: 4화면·합성 예제 제외·개인 기록 저장/삭제·조건/일시 비교·KP 미정의·API 모의 가져오기·개인 질문 보류·모바일')
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == '__main__':
    main()
