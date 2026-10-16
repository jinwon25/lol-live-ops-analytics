"""공식 Riot API의 소량 본인 전적 조회. 원본 응답·식별자를 디스크에 저장하지 않는다."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
import random
import re
import secrets
import time
from typing import Any
from urllib.parse import quote

import httpx

from service.config import get_settings
from service.evidence import catalogue
from service.match_report import match_report
from service.riot_transport import (
    RequestBudget,
    method_key,
    record_cache_hit,
    record_riot_api_call,
)
from service.timeline import timeline_summary

logger = logging.getLogger(__name__)

# HTTP and retry constants
DEFAULT_HTTP_TIMEOUT_SECONDS = 10.0
TIMELINE_HTTP_TIMEOUT_SECONDS = 15.0
MAX_RETRY_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 0.05
MAX_JITTER_SECONDS = 0.05
RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})

# Concurrency and cache constants
MATCH_DETAIL_CONCURRENCY = 5
RECENT_CACHE_TTL_SECONDS = 60
RECENT_CACHE_MAX_ENTRIES = 10
RESPONSE_CACHE_MAX_ENTRIES = 128
TIMELINE_CONTEXT_TTL_SECONDS = 1800
TIMELINE_CONTEXT_MAX_ENTRIES = 100

# Domain validation constants
RANKED_SOLO_QUEUE_ID = 420
MIN_GAME_DURATION_SECONDS = 300
MAX_GAME_DURATION_SECONDS = 5400
MAX_GOLD_EARNED = 100000
MAX_CHAMPION_DAMAGE = 500000
MAX_VISION_SCORE = 1000
MAX_KILLS = 200
MAX_DEATHS = 200
MAX_ASSISTS = 300
MAX_TEAM_KILLS = 500
MAX_MINIONS_KILLED = 2000
VALID_TEAM_IDS = (100, 200)


class RiotError(Exception):
    def __init__(self, status, message, retry_after=None):
        self.status, self.message, self.retry_after = status, message, retry_after


def _resolve_api_key() -> str:
    """Resolve RIOT_API_KEY giving priority to dynamic os.environ overrides."""
    if 'RIOT_API_KEY' in os.environ:
        return os.environ['RIOT_API_KEY'].strip()
    return get_settings().RIOT_API_KEY


def key_configured() -> bool:
    return bool(_resolve_api_key())


class RiotGateway:
    """헤더 기반 요청 예산·캐시. REDIS_URL 설정 시 다중 워커와 예산·캐시·토큰을 공유한다."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        redis_client: Any | None = None,
    ):
        self.cooldown = 0
        self.cache = {}
        self.budget = RequestBudget(redis_client=redis_client)
        self.response_cache = {}
        self.match_context = {}
        self.http_client: httpx.AsyncClient | None = client
        self.redis_client: Any | None = redis_client

    def set_client(self, client: httpx.AsyncClient | None) -> None:
        """Bind a shared lifespan httpx.AsyncClient connection pool."""
        self.http_client = client

    def set_redis(self, redis_client: Any | None) -> None:
        """Bind a shared async Redis client for distributed rate limits, caches, and timeline tokens."""
        self.redis_client = redis_client
        self.budget.set_redis(redis_client)

    async def _redis_get_json(self, key: str) -> Any | None:
        if self.redis_client is None:
            return None
        try:
            raw_value = await self.redis_client.get(key)
            if raw_value is None:
                return None
            if isinstance(raw_value, bytes):
                raw_value = raw_value.decode('utf-8')
            return json.loads(raw_value)
        except Exception as error:
            logger.warning('Redis GET failed for %s, using in-memory fallback: %s', key, error)
            return None

    async def _redis_set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        if self.redis_client is None:
            return
        try:
            serialized = json.dumps(value, ensure_ascii=False)
            await self.redis_client.set(key, serialized, ex=ttl_seconds)
        except Exception as error:
            logger.warning('Redis SET failed for %s, keeping in-memory fallback: %s', key, error)

    @asynccontextmanager
    async def _borrow_client(self, api_key: str, timeout_seconds: float):
        """Yield the shared lifespan client if available, or a scoped client as fallback."""
        client_class_patched = hasattr(httpx.AsyncClient, 'side_effect') or hasattr(httpx.AsyncClient, 'return_value')
        if (
            self.http_client is not None
            and not getattr(self.http_client, 'is_closed', False)
            and not client_class_patched
        ):
            yield self.http_client
            return

        async with httpx.AsyncClient(
            headers={'X-Riot-Token': api_key},
            timeout=timeout_seconds,
            follow_redirects=False,
        ) as scoped_client:
            yield scoped_client

    async def _get(
        self,
        client: httpx.AsyncClient,
        host: str,
        path: str,
        params: dict | None = None,
        api_key: str | None = None,
    ):
        """Execute a GET request against Riot API with rate-limit reservation and exponential backoff."""
        now = time.monotonic()
        token = api_key if api_key is not None else client.headers.get('X-Riot-Token', '')
        cache_key = hashlib.sha256(
            json.dumps([token, host, path, params], sort_keys=True).encode()
        ).hexdigest()

        redis_resp_key = f'riot:resp:{cache_key}'
        redis_cached = await self._redis_get_json(redis_resp_key)
        if redis_cached is not None:
            record_cache_hit(True)
            return redis_cached

        cached_entry = self.response_cache.get(cache_key)
        if cached_entry and now < cached_entry[0]:
            record_cache_hit(True)
            return cached_entry[1]

        method = method_key(path)
        response = None
        for attempt in range(MAX_RETRY_ATTEMPTS):
            retry_wait = await self.budget.reserve(host, method)
            if retry_wait:
                raise RiotError(429, '호출 제한에 도달했습니다. 잠시 뒤 다시 조회해주세요.', retry_wait)
            record_riot_api_call(1)
            try:
                request_headers = (
                    {'X-Riot-Token': token}
                    if token and 'X-Riot-Token' not in client.headers
                    else None
                )
                if request_headers is not None:
                    response = await client.get(
                        f'https://{host}.api.riotgames.com{path}',
                        params=params,
                        headers=request_headers,
                    )
                else:
                    response = await client.get(
                        f'https://{host}.api.riotgames.com{path}',
                        params=params,
                    )
            except httpx.HTTPError as error:
                logger.warning(
                    'Riot API network error on %s%s (attempt %d/%d): %s',
                    host,
                    path,
                    attempt + 1,
                    MAX_RETRY_ATTEMPTS,
                    error,
                )
                if attempt + 1 < MAX_RETRY_ATTEMPTS:
                    backoff_delay = (BASE_BACKOFF_SECONDS * (2 ** attempt)) + random.uniform(0.0, MAX_JITTER_SECONDS)
                    await asyncio.sleep(backoff_delay)
                    continue
                raise RiotError(502, 'Riot API 연결에 실패했습니다. 잠시 뒤 다시 조회해주세요.') from None

            await self.budget.update_async(host, method, response.headers)
            if response.status_code in RETRYABLE_STATUS_CODES and attempt + 1 < MAX_RETRY_ATTEMPTS:
                logger.warning(
                    'Riot API transient status %d on %s%s (attempt %d/%d), retrying',
                    response.status_code,
                    host,
                    path,
                    attempt + 1,
                    MAX_RETRY_ATTEMPTS,
                )
                backoff_delay = (BASE_BACKOFF_SECONDS * (2 ** attempt)) + random.uniform(0.0, MAX_JITTER_SECONDS)
                await asyncio.sleep(backoff_delay)
                continue
            break

        if response.status_code == 429:
            try:
                retry_seconds = max(1, math.ceil(float(response.headers.get('Retry-After', '120'))))
            except (ValueError, OverflowError):
                retry_seconds = 120
            self.cooldown = time.monotonic() + retry_seconds
            await self.budget.cooldown_async(host, retry_seconds)
            raise RiotError(429, 'Riot API 호출 제한에 도달했습니다.', retry_seconds)

        error_messages = {
            401: '서버의 API 키를 확인해주세요.',
            403: 'API 키가 만료됐거나 이 API에 대한 권한이 없습니다.',
            404: 'Riot ID 또는 경기 정보를 찾지 못했습니다.',
        }
        if response.status_code != 200:
            raise RiotError(
                response.status_code if response.status_code in error_messages else 502,
                error_messages.get(response.status_code, 'Riot API가 일시적으로 응답하지 않습니다.'),
            )
        try:
            payload_data = response.json()
        except ValueError:
            raise RiotError(502, 'Riot API 응답 형식을 확인할 수 없습니다.') from None

        ttl_seconds = (
            86400
            if method in {'match-detail', 'match-timeline'}
            else 60
            if method == 'match-ids'
            else 120
            if '/league/' in path
            else 600
        )
        current_mono = time.monotonic()
        self.response_cache = {
            key: value for key, value in self.response_cache.items() if current_mono < value[0]
        }
        if len(self.response_cache) >= RESPONSE_CACHE_MAX_ENTRIES:
            self.response_cache.pop(next(iter(self.response_cache)))
        self.response_cache[cache_key] = (current_mono + ttl_seconds, payload_data)
        await self._redis_set_json(redis_resp_key, payload_data, ttl_seconds)
        return payload_data

    async def get(
        self,
        client: httpx.AsyncClient,
        host: str,
        path: str,
        params: dict | None = None,
        api_key: str | None = None,
    ):
        """Public wrapper delegating to _get."""
        return await self._get(client, host, path, params=params, api_key=api_key)

    async def recent(self, game_name: str, tag_line: str, count: int = 5):
        api_key = _resolve_api_key()
        if not api_key:
            raise RiotError(503, '서버에 RIOT_API_KEY가 설정되지 않았습니다. 서비스 실행 안내를 확인해주세요.')

        cache_key = hashlib.sha256(f'{api_key}|{game_name}|{tag_line}|{count}'.encode()).hexdigest()
        redis_recent_key = f'riot:recent:{cache_key}'
        redis_recent = await self._redis_get_json(redis_recent_key)
        if isinstance(redis_recent, dict):
            record_cache_hit(True)
            return {**redis_recent, 'cached': True}

        now = time.monotonic()
        self.cache = {
            key: value for key, value in self.cache.items() if now - value[0] < RECENT_CACHE_TTL_SECONDS
        }
        if cache_key in self.cache:
            record_cache_hit(True)
            return {**self.cache[cache_key][1], 'cached': True}

        async with self._borrow_client(api_key, DEFAULT_HTTP_TIMEOUT_SECONDS) as client:
            account = await self._get(
                client,
                'asia',
                '/riot/account/v1/accounts/by-riot-id/' + quote(game_name, safe='') + '/' + quote(tag_line, safe=''),
                api_key=api_key,
            )
            puuid = account.get('puuid') if isinstance(account, dict) else None
            if not isinstance(puuid, str) or not puuid:
                raise RiotError(502, '계정 응답에서 PUUID를 확인할 수 없습니다.')

            match_ids = await self._get(
                client,
                'asia',
                '/lol/match/v5/matches/by-puuid/' + quote(puuid, safe='') + '/ids',
                {'queue': RANKED_SOLO_QUEUE_ID, 'type': 'ranked', 'start': 0, 'count': count},
                api_key=api_key,
            )
            ranks = await self._get(
                client,
                'kr',
                '/lol/league/v4/entries/by-puuid/' + quote(puuid, safe=''),
                api_key=api_key,
            )
            if not isinstance(match_ids, list) or not isinstance(ranks, list):
                raise RiotError(502, '경기 목록 또는 랭크 응답 형식이 다릅니다.')
            if any(not isinstance(row, dict) for row in ranks):
                raise RiotError(502, '랭크 응답 형식을 확인할 수 없습니다.')
            if any(not isinstance(value, str) or not re.fullmatch(r'KR_[0-9]+', value) for value in match_ids):
                raise RiotError(502, 'KR 경기 목록을 확인할 수 없습니다.')

            current_rank = next(
                (
                    {field: row.get(field) for field in ['tier', 'rank', 'leaguePoints', 'wins', 'losses']}
                    for row in ranks
                    if row.get('queueType') == 'RANKED_SOLO_5x5'
                ),
                None,
            )

            target_match_ids = list(dict.fromkeys(match_ids))[:count]
            semaphore = asyncio.Semaphore(MATCH_DETAIL_CONCURRENCY)

            async def fetch_match_detail(match_id: str):
                async with semaphore:
                    detail = await self._get(
                        client,
                        'asia',
                        '/lol/match/v5/matches/' + match_id,
                        api_key=api_key,
                    )
                    return match_id, detail

            fetched_details = await asyncio.gather(
                *(fetch_match_detail(match_id) for match_id in target_match_ids)
            )

            items, skipped_count, excluded_reasons = [], 0, {}
            for match_id, detail in fetched_details:
                normalized_item = normalize_match(detail, puuid)
                if normalized_item:
                    normalized_item['report'] = match_report(normalized_item)
                    participants = detail['info']['participants']
                    player = next(participant for participant in participants if participant.get('puuid') == puuid)
                    opponent = next(
                        (
                            participant
                            for participant in participants
                            if participant.get('teamId') != player.get('teamId')
                            and participant.get('teamPosition') == player.get('teamPosition')
                        ),
                        {},
                    )
                    if type(player.get('participantId')) is int and type(opponent.get('participantId')) is int:
                        token = secrets.token_urlsafe(24)
                        current_mono = time.monotonic()
                        self.match_context = {
                            key: value
                            for key, value in self.match_context.items()
                            if current_mono - value[0] < TIMELINE_CONTEXT_TTL_SECONDS
                        }
                        if len(self.match_context) >= TIMELINE_CONTEXT_MAX_ENTRIES:
                            self.match_context.pop(next(iter(self.match_context)))
                        context_tuple = (
                            current_mono,
                            match_id,
                            player['participantId'],
                            opponent['participantId'],
                            player['teamId'],
                        )
                        self.match_context[token] = context_tuple
                        await self._redis_set_json(
                            f'riot:timeline:{token}',
                            [match_id, player['participantId'], opponent['participantId'], player['teamId']],
                            TIMELINE_CONTEXT_TTL_SECONDS,
                        )
                        normalized_item['timeline_ref'] = token
                    items.append(normalized_item)
                else:
                    skipped_count += 1
                    reason = exclusion_reason(detail, puuid)
                    excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1

            result = {
                'source': 'Riot 공식 API · KR 솔로듀오',
                'current_rank': current_rank,
                'items': items,
                'skipped': skipped_count,
                'exclusion_counts': excluded_reasons,
                'cached': False,
                'checked_at': datetime.now(timezone.utc).isoformat(),
                'caveat': '현재 랭크는 경기 당시 티어가 아닙니다. 누락·리메이크·미지원 역할 경기는 리포트에서 제외합니다.',
            }
            if len(self.cache) >= RECENT_CACHE_MAX_ENTRIES:
                self.cache.pop(next(iter(self.cache)))
            self.cache[cache_key] = (time.monotonic(), result)
            await self._redis_set_json(redis_recent_key, result, RECENT_CACHE_TTL_SECONDS)
            return result

    async def timeline(self, token: str):
        api_key = _resolve_api_key()
        redis_context = await self._redis_get_json(f'riot:timeline:{token}')
        if isinstance(redis_context, list) and len(redis_context) == 4:
            match_id, player_id, opponent_id, team_id = redis_context
        else:
            context = self.match_context.get(token)
            if not context or time.monotonic() - context[0] >= TIMELINE_CONTEXT_TTL_SECONDS:
                raise RiotError(410, '경기 흐름 연결이 만료됐습니다. 전적을 다시 조회해주세요.')
            match_id, player_id, opponent_id, team_id = context[1], context[2], context[3], context[4]

        if not api_key:
            raise RiotError(503, '서버의 Riot API 연결을 확인해주세요.')

        async with self._borrow_client(api_key, TIMELINE_HTTP_TIMEOUT_SECONDS) as client:
            raw_timeline = await self._get(
                client,
                'asia',
                '/lol/match/v5/matches/' + str(match_id) + '/timeline',
                api_key=api_key,
            )
        return timeline_summary(raw_timeline, player_id, opponent_id, team_id)


def exclusion_reason(data, puuid):
    info = data.get('info', {}) if isinstance(data, dict) else {}
    if not isinstance(info, dict):
        return '응답 형식 확인 필요'
    if info.get('queueId') != RANKED_SOLO_QUEUE_ID or info.get('platformId') != 'KR':
        return '지원 범위 밖 경기'
    if not info.get('gameEndTimestamp'):
        return '종료 기록 미확인'
    participants = info.get('participants', [])
    player = (
        next((participant for participant in participants if isinstance(participant, dict) and participant.get('puuid') == puuid), None)
        if isinstance(participants, list)
        else None
    )
    if not player:
        return '본인 참여 정보 미확인'
    duration = info.get('gameDuration')
    if player.get('gameEndedInEarlySurrender') or (type(duration) in (int, float) and duration < MIN_GAME_DURATION_SECONDS):
        return '짧은 경기·조기 종료'
    if player.get('teamPosition') not in {'TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY'}:
        return '포지션 미확인'
    return '챔피언·패치·수치 검증 미통과'


def normalize_match(data, puuid):
    """11.20 이후 완료 KR 솔로 경기만. 식별자·타인 원본은 반환하지 않는다."""
    if not isinstance(data, dict) or not isinstance(data.get('info'), dict):
        return None
    info = data['info']
    if info.get('queueId') != RANKED_SOLO_QUEUE_ID or info.get('platformId') != 'KR' or not info.get('gameEndTimestamp'):
        return None
    participants = info.get('participants', [])
    if not isinstance(participants, list) or not all(isinstance(participant, dict) for participant in participants):
        return None
    player = next((participant for participant in participants if participant.get('puuid') == puuid), None)
    if not player or player.get('gameEndedInEarlySurrender'):
        return None
    roles = {'TOP': 'TOP', 'JUNGLE': 'JUNGLE', 'MIDDLE': 'MID', 'BOTTOM': 'BOT', 'UTILITY': 'SUPPORT'}
    role = roles.get(player.get('teamPosition'))
    champion = next((champ for champ in catalogue()['champions'] if champ['key'] == str(player.get('championId'))), None)
    seconds = info.get('gameDuration')
    version = str(info.get('gameVersion', '')).split('.')
    if (
        not role
        or not champion
        or type(seconds) not in (int, float)
        or not MIN_GAME_DURATION_SECONDS <= seconds <= MAX_GAME_DURATION_SECONDS
        or len(version) < 2
        or not re.fullmatch(r'[0-9]{2}\.[0-9]{1,2}', '.'.join(version[:2]))
    ):
        return None
    try:
        if type(info['gameEndTimestamp']) not in (int, float) or not math.isfinite(info['gameEndTimestamp']):
            return None
        ended = datetime.fromtimestamp(info['gameEndTimestamp'] / 1000, timezone.utc).isoformat()
        metrics = {
            key: player.get(field)
            for key, field in [
                ('gold', 'goldEarned'),
                ('damage', 'totalDamageDealtToChampions'),
                ('vision', 'visionScore'),
                ('kills', 'kills'),
                ('assists', 'assists'),
            ]
        }
        limits = {
            'gold': MAX_GOLD_EARNED,
            'damage': MAX_CHAMPION_DAMAGE,
            'vision': MAX_VISION_SCORE,
            'kills': MAX_KILLS,
            'assists': MAX_ASSISTS,
        }
        if any(
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not 0 <= value <= limits[key]
            or (key != 'vision' and int(value) != value)
            for key, value in metrics.items()
        ):
            return None
        team = [participant for participant in participants if participant.get('teamId') == player.get('teamId')]
        if player.get('teamId') not in VALID_TEAM_IDS or any(
            type(participant.get('kills')) is not int or not 0 <= participant['kills'] <= MAX_KILLS for participant in team
        ):
            return None
        team_kills = sum(participant['kills'] for participant in team)
        if team_kills > MAX_TEAM_KILLS or metrics['kills'] + metrics['assists'] > team_kills:
            return None
    except (ValueError, TypeError, OverflowError, OSError):
        return None

    def optional_count(field, maximum):
        value = player.get(field)
        return value if type(value) is int and 0 <= value <= maximum else None

    lane_cs = optional_count('totalMinionsKilled', MAX_MINIONS_KILLED)
    jungle_cs = optional_count('neutralMinionsKilled', MAX_MINIONS_KILLED)
    team_damage = [participant.get('totalDamageDealtToChampions') for participant in team]
    valid_damage = all(type(value) is int and 0 <= value <= MAX_CHAMPION_DAMAGE for value in team_damage)
    scoreboard = []
    for participant in participants:
        champ = next((item for item in catalogue()['champions'] if item['key'] == str(participant.get('championId'))), None)
        if not champ or participant.get('teamId') not in VALID_TEAM_IDS:
            continue

        def safe(field, maximum):
            value = participant.get(field)
            return value if type(value) is int and 0 <= value <= maximum else None

        scoreboard.append(
            {
                'champion_id': champ['id'],
                'champion_name': champ['name'],
                'role': roles.get(participant.get('teamPosition'), '—'),
                'is_self': participant is player,
                'is_ally': participant.get('teamId') == player['teamId'],
                'kills': safe('kills', MAX_KILLS),
                'deaths': safe('deaths', MAX_DEATHS),
                'assists': safe('assists', MAX_ASSISTS),
                'gold': safe('goldEarned', MAX_GOLD_EARNED),
                'damage': safe('totalDamageDealtToChampions', MAX_CHAMPION_DAMAGE),
                'vision': safe('visionScore', MAX_VISION_SCORE),
            }
        )
    return {
        'champion_id': champion['id'],
        'champion_name': champion['name'],
        'role': role,
        'region': 'KR',
        'queue': 'RANKED_SOLO',
        'patch': '.'.join(version[:2]),
        'played_at': ended,
        'duration_minutes': round(seconds / 60, 2),
        **metrics,
        'team_kills': team_kills,
        'win': player.get('win') if type(player.get('win')) is bool else None,
        'tier': None,
        'deaths': optional_count('deaths', MAX_DEATHS),
        'scoreboard': scoreboard,
        'cs': lane_cs + jungle_cs if lane_cs is not None and jungle_cs is not None else None,
        'team_damage': sum(team_damage) if valid_damage else None,
    }


gateway = RiotGateway()
