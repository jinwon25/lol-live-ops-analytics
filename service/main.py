"""로컬 LoL 분석 도우미. 실행: python -m uvicorn service.main:app --reload"""
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from service.evidence import SCOPE, answer, catalogue, champion_history, rows

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title='LoL 인사이트 노트', version='0.1.0')
app.mount('/assets', StaticFiles(directory=ROOT / 'web'), name='assets')


@app.get('/')
def home():
    return FileResponse(ROOT / 'web/index.html')


@app.get('/api/overview')
def overview():
    cat = catalogue()
    return {'name': 'LoL 인사이트 노트', 'stage': 'local_prototype', 'live_matches_connected': False,
            'match_scope': SCOPE, 'historic_matches': 8358, 'historic_participant_rows': 83566,
            'static_data': {k: cat[k] for k in ['version', 'checked_at', 'source_url', 'realm', 'locale']},
            'diversity': rows('diversity.csv'), 'segments': rows('segment_summary.csv'),
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

    @model_validator(mode='after')
    def check_team_counts(self):
        if self.kills + self.assists > self.team_kills:
            raise ValueError('킬+도움은 팀 킬 수를 초과할 수 없습니다.')
        return self


@app.post('/api/review')
def review(request: Review):
    return {'source': '합성 예제' if request.is_example else '직접 입력 · 전적 검증 전', 'role': request.role,
            'metrics': {'gpm': round(request.gold / request.duration_minutes, 1),
                        'dpm': round(request.damage / request.duration_minutes, 1),
                        'vision_per_minute': round(request.vision / request.duration_minutes, 2),
                        'kill_participation': round((request.kills + request.assists) / request.team_kills, 3) if request.team_kills else None},
            'peer_percentile': None,
            'explanation': '한 경기의 입력을 요약했습니다. 최신 동티어·포지션 비교 표본이 연결되지 않아 실력·분위·승리 원인을 판정하지 않습니다.',
            'questions': ['오브젝트 직전 시야를 확보하거나 지우는 과정은 어땠나요?', '교전 참여 전 아군 합류와 자원 차이를 확인했나요?', '다음 경기에서 확인할 행동 한 가지를 정해보세요.']}
