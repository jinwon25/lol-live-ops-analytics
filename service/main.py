"""로컬 LoL 분석 도우미. 실행: python -m uvicorn service.main:app --reload"""
from pathlib import Path
import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from urllib.parse import urlparse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from service.evidence import SCOPE, answer, catalogue, champion_history, rows
from service.review import FOCUSES, review_summary
from service.riot import RiotError, gateway, key_configured

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title='LoL 인사이트 노트', version='0.2.0')
app.mount('/assets', StaticFiles(directory=ROOT / 'web'), name='assets')


@app.get('/')
def home():
    return FileResponse(ROOT / 'web/index.html')


@app.middleware('http')
async def guard_personal_api(request: Request, call_next):
    if request.url.path.startswith('/api/riot/'):
        local = {'127.0.0.1', 'localhost', '::1'}
        origin = request.headers.get('origin')
        allowed_origin = not origin or (urlparse(origin).scheme in {'http','https'} and origin == str(request.base_url).rstrip('/'))
        if request.url.hostname not in local or not request.client or request.client.host not in local or not allowed_origin:
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail':'전적 연결은 이 컴퓨터의 로컬 화면에서만 사용할 수 있습니다.'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response
    return await call_next(request)


@app.get('/api/riot/status')
def riot_status():
    return {'configured':key_configured(), 'region':'KR', 'queue':'RANKED_SOLO', 'stage':'local_connector'}


class RiotLookup(BaseModel):
    game_name: str = Field(min_length=1, max_length=70)
    tag_line: str = Field(min_length=1, max_length=16)
    count: int = Field(default=5, ge=1, le=10)

    @model_validator(mode='after')
    def trim_id(self):
        self.game_name, self.tag_line = self.game_name.strip(), self.tag_line.strip()
        if not self.game_name or not self.tag_line:
            raise ValueError('게임 이름과 태그를 입력해주세요.')
        return self


@app.get('/api/riot/preferences')
def personal_preferences():
    # 개인 기본값은 Git 제외 파일에서 읽는다. ID·전적·키는 여기에 저장하지 않는다.
    path = ROOT / '.local/companion.json'
    try:
        if path.stat().st_size > 4096:
            return {}
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return {}
        prefs = {k:data[k] for k in ['region','queue','tier','division','role','champions']}
        if prefs['region'] != 'KR' or prefs['queue'] != 'RANKED_SOLO' or prefs['role'] not in {'TOP','JUNGLE','MID','BOT','SUPPORT'} or prefs['tier'] not in {'IRON','BRONZE','SILVER','GOLD','PLATINUM','EMERALD','DIAMOND','MASTER','GRANDMASTER','CHALLENGER'} or prefs['division'] not in {'I','II','III','IV',''}:
            return {}
        if not isinstance(prefs['champions'], list) or not 1 <= len(prefs['champions']) <= 3 or not all(any(c['id'] == item for c in catalogue()['champions']) for item in prefs['champions']):
            return {}
        return prefs
    except (OSError, ValueError, KeyError, TypeError):
        return {}


@app.post('/api/riot/recent')
async def riot_recent(request: RiotLookup):
    try:
        return await gateway.recent(request.game_name.strip(), request.tag_line.strip(), request.count)
    except RiotError as error:
        headers = {'Retry-After':str(error.retry_after)} if error.retry_after else None
        raise HTTPException(error.status, error.message, headers=headers) from None


@app.get('/api/overview')
def overview():
    cat = catalogue()
    return {'name': 'LoL 인사이트 노트', 'stage': 'local_prototype', 'live_matches_connected': False,
            'match_scope': SCOPE, 'historic_matches': 8358, 'historic_participant_rows': 83566,
            'static_data': {k: cat[k] for k in ['version', 'checked_at', 'source_url', 'realm', 'locale']},
            'diversity': rows('diversity.csv'), 'segments': rows('segment_summary.csv'),
            'review_focuses': [{'id': key, **value} for key, value in FOCUSES.items()],
            'patch_notes': {'patch': '26.19', 'published': '2026-09-22', 'checked': '2026-10-04',
                            'url': 'https://www.leagueoflegends.com/ko-kr/news/game-updates/league-of-legends-patch-26-19-notes/'}}


@app.get('/api/champions')
def champions(q: str = Query(default='', max_length=80)):
    cat = catalogue()
    query = q.strip().casefold()
    selected = [c for c in cat['champions'] if query in c['name'].casefold() or query in c['id'].casefold()]
    return {'version': cat['version'], 'source_url': cat['source_url'], 'items': sorted(selected, key=lambda c: c['name'])}


@app.get('/api/champions/{champion_id}')
def champion(champion_id: str):
    champ = next((c for c in catalogue()['champions'] if c['id'] == champion_id), None)
    if champ is None:
        raise HTTPException(404, '공식 목록에 없는 챔피언입니다.')
    return {'champion': champ, 'static_version': catalogue()['version'], 'history': champion_history(champion_id),
            'history_scope': SCOPE, 'pick_rate_denominator': '공통 티어 전체 참여 행. 역할별 픽률이 아닙니다.',
            'minimum_display_rows': 30, 'current_win_rate': None}


class Ask(BaseModel):
    question: str = Field(min_length=2, max_length=300)
    champion_id: str | None = Field(default=None, max_length=40)


@app.post('/api/assistant')
def assistant(request: Ask):
    if request.champion_id and not any(c['id'] == request.champion_id for c in catalogue()['champions']):
        raise HTTPException(404, '공식 목록에 없는 챔피언입니다.')
    return answer(request.question, request.champion_id)


class Review(BaseModel):
    role: Literal['TOP', 'JUNGLE', 'MID', 'BOT', 'SUPPORT']
    duration_minutes: float = Field(ge=5, le=90)
    gold: int = Field(ge=0, le=100000)
    damage: int = Field(ge=0, le=500000)
    vision: float = Field(ge=0, le=1000)
    kills: int = Field(ge=0, le=200)
    assists: int = Field(ge=0, le=300)
    team_kills: int = Field(ge=0, le=500)
    is_example: bool = False
    champion_id: str | None = Field(default=None, max_length=40)
    region: Literal['KR', 'EUN', 'EUW', 'NA'] | None = None
    queue: Literal['RANKED_SOLO', 'RANKED_FLEX'] | None = None
    tier: Literal['IRON', 'BRONZE', 'SILVER', 'GOLD', 'PLATINUM', 'EMERALD', 'DIAMOND', 'MASTER', 'GRANDMASTER', 'CHALLENGER'] | None = None
    patch: str | None = Field(default=None, pattern=r'^\d{2}\.\d{1,2}$')
    played_at: datetime | None = None
    focus: Literal['vision', 'fight_setup', 'resource', 'matchup'] = 'vision'

    @model_validator(mode='after')
    def check_team_counts(self):
        if self.kills + self.assists > self.team_kills:
            raise ValueError('킬+도움은 팀 킬 수를 초과할 수 없습니다.')
        if self.played_at:
            if self.played_at.tzinfo is None:
                raise ValueError('플레이 일시에는 시간대가 필요합니다.')
            if self.played_at > datetime.now(timezone.utc) + timedelta(minutes=5):
                raise ValueError('완료된 경기의 일시를 입력하세요. 미래 경기는 저장할 수 없습니다.')
        return self


@app.post('/api/review')
def review(request: Review):
    champion = next((c for c in catalogue()['champions'] if c['id'] == request.champion_id), None)
    if request.champion_id and champion is None:
        raise HTTPException(404, '공식 목록에 없는 챔피언입니다.')
    return review_summary(request, champion)
