"""로컬 LoL 분석 도우미. 실행: python -m uvicorn service.main:app --reload"""

import ipaddress
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from service.champion_details import abilities
from service.config import get_settings
from service.evidence import (
    SCOPE,
    answer,
    catalogue,
    catalogue_by_id,
    champion_history,
    preload_evidence,
    review_store,
    rows,
)
from service.local_coach import CoachInput, coach
from service.local_coach import status as coach_status
from service.meta import current_meta
from service.public_data import public_flow, source_catalogue
from service.review import FOCUSES, review_summary
from service.riot import RiotError, gateway, key_configured
from service.riot_transport import (
    configure_json_logger,
    init_request_telemetry,
    reset_request_telemetry,
)

logger = logging.getLogger(__name__)
http_logger = configure_json_logger('lol_live_ops.http')

# Warm up in-memory evidence caches on module import so cold requests are sub-millisecond.
preload_evidence()

ROOT = Path(__file__).resolve().parents[1]
LOCAL_HOSTS = frozenset({'127.0.0.1', 'localhost', '::1'})
TRUSTED_PRIVATE_NETWORKS = (
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('::1/128'),
    ipaddress.ip_network('fc00::/7'),
)
SHARED_HTTP_TIMEOUT_SECONDS = 15.0
MAX_PREFERENCES_BYTES = 4096
MAX_TIMELINE_TOKEN_LENGTH = 64
MINIMUM_DISPLAY_ROWS = 30


def is_trusted_network_host(host_value: str | None) -> bool:
    """Return True if host_value is localhost or within RFC1918/loopback private ranges."""
    if not host_value:
        return False
    normalized = host_value.strip()
    if normalized in LOCAL_HOSTS:
        return True
    try:
        parsed_ip = ipaddress.ip_address(normalized)
        return any(parsed_ip in network for network in TRUSTED_PRIVATE_NETWORKS)
    except ValueError:
        return False


def is_trusted_client_request(request: Request) -> bool:
    """Validate direct client IP and optional X-Forwarded-For chain from trusted private networks."""
    direct_host = request.client.host if request.client else None
    if not is_trusted_network_host(direct_host):
        return False
    forwarded_for = request.headers.get('x-forwarded-for')
    if not forwarded_for:
        return True
    hops = [hop.strip() for hop in forwarded_for.split(',') if hop.strip()]
    return bool(hops) and all(is_trusted_network_host(hop) for hop in hops)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Manage preloaded evidence, shared httpx.AsyncClient, and optional Redis connection pools."""
    preload_evidence()
    current_settings = get_settings()
    redis_client = None
    if current_settings.REDIS_URL:
        try:
            import redis.asyncio as aioredis

            redis_client = aioredis.from_url(
                current_settings.REDIS_URL,
                decode_responses=True,
            )
            gateway.set_redis(redis_client)
        except Exception as error:
            logger.warning('Failed to initialize Redis client (%s); using in-memory fallback.', error)
            redis_client = None

    async with httpx.AsyncClient(
        timeout=SHARED_HTTP_TIMEOUT_SECONDS,
        follow_redirects=False,
    ) as shared_http_client:
        application.state.http_client = shared_http_client
        application.state.redis_client = redis_client
        gateway.set_client(shared_http_client)
        coach.set_client(shared_http_client)
        try:
            yield
        finally:
            gateway.set_client(None)
            gateway.set_redis(None)
            coach.set_client(None)
            if redis_client is not None:
                try:
                    await redis_client.aclose()
                except Exception as error:
                    logger.warning('Error closing Redis client: %s', error)


app = FastAPI(title='LoL 인사이트 노트', version='0.4.0', lifespan=lifespan)
app.mount('/assets', StaticFiles(directory=ROOT / 'web'), name='assets')


@app.get('/')
def home():
    return FileResponse(ROOT / 'web/index.html')


def _emit_http_log(
    request: Request,
    status_code: int,
    duration_ms: float,
    telemetry: dict[str, Any],
) -> None:
    """Emit a structured JSON log record for every completed HTTP request."""
    structured_fields = {
        'event': 'http_request',
        'trace_id': telemetry['trace_id'],
        'method': request.method,
        'path': request.url.path,
        'status_code': status_code,
        'duration_ms': duration_ms,
        'riot_api_calls': telemetry['riot_api_calls'],
        'rate_limit_remaining': gateway.budget.remaining_budget('asia'),
        'cache_hit': telemetry['cache_hit'],
    }
    http_logger.info(
        'HTTP %s %s -> %d (%.3fms)',
        request.method,
        request.url.path,
        status_code,
        duration_ms,
        extra={'structured_data': structured_fields},
    )


@app.middleware('http')
async def guard_personal_api(request: Request, call_next):
    incoming_trace_id = request.headers.get('x-trace-id') or request.headers.get('x-request-id') or uuid.uuid4().hex
    telemetry, context_token = init_request_telemetry(incoming_trace_id)
    started_at = time.perf_counter()
    try:
        if request.url.path.startswith('/api/riot/'):
            current_settings = get_settings()
            origin = request.headers.get('origin')
            normalized_origin = origin.rstrip('/') if origin else None
            base_origin = str(request.base_url).rstrip('/')
            if current_settings.ALLOW_REMOTE_ACCESS:
                allowed_origin = not normalized_origin or (
                    urlparse(normalized_origin).scheme in {'http', 'https'}
                    and (normalized_origin == base_origin or normalized_origin in current_settings.ALLOWED_ORIGINS)
                )
                if not allowed_origin:
                    blocked_response = JSONResponse(
                        {'detail': '전적 연결이 허용되지 않은 Origin입니다.'},
                        status_code=403,
                    )
                    blocked_response.headers['X-Trace-Id'] = telemetry['trace_id']
                    duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
                    _emit_http_log(request, blocked_response.status_code, duration_ms, telemetry)
                    return blocked_response
            else:
                allowed_origin = not normalized_origin or (
                    urlparse(normalized_origin).scheme in {'http', 'https'} and normalized_origin == base_origin
                )
                if (
                    not is_trusted_network_host(request.url.hostname)
                    or not is_trusted_client_request(request)
                    or not allowed_origin
                ):
                    blocked_response = JSONResponse(
                        {'detail': '전적 연결은 이 컴퓨터의 로컬 화면에서만 사용할 수 있습니다.'},
                        status_code=403,
                    )
                    blocked_response.headers['X-Trace-Id'] = telemetry['trace_id']
                    duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
                    _emit_http_log(request, blocked_response.status_code, duration_ms, telemetry)
                    return blocked_response
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Trace-Id'] = telemetry['trace_id']
            response.headers['X-Response-Time-Ms'] = str(duration_ms)
            _emit_http_log(request, response.status_code, duration_ms, telemetry)
            return response

        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
        if request.url.path == '/' or request.url.path in {
            '/assets/app.js',
            '/assets/styles.css',
            '/assets/geng-theme.css',
            '/assets/journal.js',
            '/assets/draft.js',
            '/assets/analysis.js',
            '/assets/reports.js',
            '/assets/workspace.css',
            '/assets/insights.js',
            '/assets/match_views.js',
        }:
            # Ensure active browser tabs re-validate static UI assets on reload.
            response.headers['Cache-Control'] = 'no-cache'
        response.headers['X-Trace-Id'] = telemetry['trace_id']
        response.headers['X-Response-Time-Ms'] = str(duration_ms)
        _emit_http_log(request, response.status_code, duration_ms, telemetry)
        return response

    finally:
        reset_request_telemetry(context_token)


@app.get('/api/riot/status')
def riot_status():
    return {
        'configured': key_configured(),
        'region': 'KR',
        'queue': 'RANKED_SOLO',
        'stage': 'local_connector',
    }


@app.get('/api/riot/coach/status')
def local_coach_status():
    return coach_status()


@app.post('/api/riot/coach')
async def local_coach(request: CoachInput):
    try:
        return await coach.choose_async(request)
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from None
    except (ImportError, OSError, ValueError):
        raise HTTPException(
            503,
            '로컬 모델 실행 환경을 확인해주세요. 기본 리포트는 계속 사용할 수 있습니다.',
        ) from None


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
    # Personal default settings are read from a git-ignored local file without storing PII or API keys.
    path = ROOT / '.local/companion.json'
    try:
        if path.stat().st_size > MAX_PREFERENCES_BYTES:
            return {}
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return {}
        prefs = {key: data[key] for key in ['region', 'queue', 'tier', 'division', 'role', 'champions']}
        if (
            prefs['region'] != 'KR'
            or prefs['queue'] != 'RANKED_SOLO'
            or prefs['role'] not in {'TOP', 'JUNGLE', 'MID', 'BOT', 'SUPPORT'}
            or prefs['tier']
            not in {
                'IRON',
                'BRONZE',
                'SILVER',
                'GOLD',
                'PLATINUM',
                'EMERALD',
                'DIAMOND',
                'MASTER',
                'GRANDMASTER',
                'CHALLENGER',
            }
            or prefs['division'] not in {'I', 'II', 'III', 'IV', ''}
        ):
            return {}
        if (
            not isinstance(prefs['champions'], list)
            or not 1 <= len(prefs['champions']) <= 3
            or not all(any(champ['id'] == item for champ in catalogue()['champions']) for item in prefs['champions'])
        ):
            return {}
        return prefs
    except (OSError, ValueError, KeyError, TypeError):
        return {}


@app.post('/api/riot/recent')
async def riot_recent(request: RiotLookup):
    try:
        return await gateway.recent(request.game_name.strip(), request.tag_line.strip(), request.count)
    except RiotError as error:
        headers = {'Retry-After': str(error.retry_after)} if error.retry_after else None
        raise HTTPException(error.status, error.message, headers=headers) from None


@app.get('/api/riot/timeline/{token}')
async def riot_timeline(token: str):
    if len(token) > MAX_TIMELINE_TOKEN_LENGTH:
        raise HTTPException(404, '경기 연결을 확인해주세요.')
    try:
        return await gateway.timeline(token)
    except RiotError as error:
        headers = {'Retry-After': str(error.retry_after)} if error.retry_after else None
        raise HTTPException(error.status, error.message, headers=headers) from None


@lru_cache(maxsize=1)
def _cached_overview() -> dict[str, Any]:
    cat = catalogue()
    return {
        'name': 'LoL 인사이트 노트',
        'stage': 'local_prototype',
        'live_matches_connected': False,
        'match_scope': SCOPE,
        'historic_matches': 8358,
        'historic_participant_rows': 83566,
        'static_data': {key: cat[key] for key in ['version', 'checked_at', 'source_url', 'realm', 'locale']},
        'diversity': rows('diversity.csv'),
        'segments': rows('segment_summary.csv'),
        'review_focuses': [{'id': key, **value} for key, value in FOCUSES.items()],
        'patch_notes': {
            'patch': '26.19',
            'published': '2026-09-22',
            'checked': '2026-10-04',
            'url': 'https://www.leagueoflegends.com/ko-kr/news/game-updates/league-of-legends-patch-26-19-notes/',
        },
    }


@app.get('/api/overview')
async def overview():
    return _cached_overview()


@app.get('/api/champions')
async def champions(q: str = Query(default='', max_length=80)):
    cat = catalogue()
    query = q.strip().casefold()
    selected = [
        champ for champ in cat['champions'] if query in champ['name'].casefold() or query in champ['id'].casefold()
    ]
    return {
        'version': cat['version'],
        'source_url': cat['source_url'],
        'items': sorted(selected, key=lambda champ: champ['name']),
    }


@app.get('/api/meta')
async def meta():
    try:
        return current_meta()
    except (OSError, ValueError, KeyError):
        raise HTTPException(503, '현재 메타 집계 파일을 확인해주세요.') from None


@app.get('/api/public-data')
async def public_data():
    try:
        return {'flow': public_flow(), 'sources': source_catalogue()}
    except (OSError, ValueError):
        raise HTTPException(503, '공개 참고 자료의 집계 파일을 확인해주세요.') from None


@app.get('/api/champions/{champion_id}')
async def champion(champion_id: str):
    champ = catalogue_by_id().get(champion_id)
    if champ is None:
        raise HTTPException(404, '공식 목록에 없는 챔피언입니다.')
    return {
        'champion': champ,
        'abilities': await abilities(champion_id),
        'static_version': catalogue()['version'],
        'history': champion_history(champion_id),
        'history_scope': SCOPE,
        'pick_rate_denominator': '공통 티어 전체 참여 행. 역할별 픽률이 아닙니다.',
        'minimum_display_rows': MINIMUM_DISPLAY_ROWS,
        'current_win_rate': None,
    }


class Ask(BaseModel):
    question: str = Field(min_length=2, max_length=300)
    champion_id: str | None = Field(default=None, max_length=40)


@app.post('/api/assistant')
async def assistant(request: Ask):
    if request.champion_id and request.champion_id not in catalogue_by_id():
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
    tier: (
        Literal[
            'IRON',
            'BRONZE',
            'SILVER',
            'GOLD',
            'PLATINUM',
            'EMERALD',
            'DIAMOND',
            'MASTER',
            'GRANDMASTER',
            'CHALLENGER',
        ]
        | None
    ) = None
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
            if self.played_at > datetime.now(UTC) + timedelta(minutes=5):
                raise ValueError('완료된 경기의 일시를 입력하세요. 미래 경기는 저장할 수 없습니다.')
        return self


@app.post('/api/review')
async def review(request: Review):
    champion_entry = catalogue_by_id().get(request.champion_id) if request.champion_id else None
    if request.champion_id and champion_entry is None:
        raise HTTPException(404, '공식 목록에 없는 챔피언입니다.')
    return review_summary(request, champion_entry)


class SyncedReviewRequest(BaseModel):
    record_id: str | None = Field(default=None, max_length=64)
    client_id: str = Field(default='default', min_length=1, max_length=64)
    champion_id: str | None = Field(default=None, max_length=40)
    role: str | None = Field(default=None, max_length=20)
    patch: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=500)
    tags: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    focus: Literal['vision', 'fight_setup', 'resource', 'matchup'] = 'vision'
    scene: str = Field(default='', max_length=500)
    action: str = Field(default='', max_length=500)
    status: Literal['planned', 'tried', 'kept'] = 'planned'
    reflection: str = Field(default='', max_length=500)
    played_at: str | None = Field(default=None, max_length=64)


@app.get('/api/reviews/sync')
async def list_synced_reviews(client_id: str = Query(default='default', min_length=1, max_length=64)):
    return {'items': review_store.list_reviews(client_id=client_id)}


@app.get('/api/reviews/sync/{record_id}')
async def get_synced_review(record_id: str):
    found = review_store.get_review(record_id=record_id)
    if found is None:
        raise HTTPException(404, '복기 기록을 찾지 못했습니다.')
    return found


@app.post('/api/reviews/sync', status_code=201)
async def create_synced_review(request: SyncedReviewRequest):
    return review_store.upsert_review(request.model_dump())


@app.put('/api/reviews/sync/{record_id}')
async def update_synced_review(record_id: str, request: SyncedReviewRequest):
    return review_store.upsert_review(request.model_dump(), record_id=record_id)


@app.delete('/api/reviews/sync/{record_id}')
async def delete_synced_review(
    record_id: str,
    client_id: str = Query(default='default', min_length=1, max_length=64),
):
    deleted = review_store.delete_review(record_id=record_id, client_id=client_id)
    if not deleted:
        raise HTTPException(404, '삭제할 복기 기록을 찾지 못했습니다.')
    return {'deleted': True, 'record_id': record_id}
