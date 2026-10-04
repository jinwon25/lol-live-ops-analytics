"""공식 Riot API의 소량 본인 전적 조회. 원본 응답·식별자를 디스크에 저장하지 않는다."""
import asyncio
from collections import deque
from datetime import datetime, timezone
import hashlib
import os
import time
from urllib.parse import quote

import httpx

from service.evidence import catalogue


class RiotError(Exception):
    def __init__(self, status, message, retry_after=None):
        self.status, self.message, self.retry_after = status, message, retry_after


def key_configured():
    return bool(os.environ.get('RIOT_API_KEY', '').strip())


class RiotGateway:
    """단일 로컬 프로세스용 제한·60초 캐시. 다중 사용자 운영 구현은 별도 필요."""
    def __init__(self):
        self.calls = deque()
        self.cooldown = 0
        self.cache = {}
        self.lock = asyncio.Lock()

    async def get(self, client, host, path, params=None):
        now = time.monotonic()
        while self.calls and now - self.calls[0] >= 120:
            self.calls.popleft()
        short = [stamp for stamp in self.calls if now - stamp < 1]
        if now < self.cooldown or len(self.calls) >= 95 or len(short) >= 18:
            retry = max(1, int(max(self.cooldown-now, (120-(now-self.calls[0])) if len(self.calls) >= 95 else 1)) + 1)
            raise RiotError(429, '호출 제한에 도달했습니다. 잠시 뒤 다시 조회해주세요.', retry)
        self.calls.append(now)
        try:
            response = await client.get(f'https://{host}.api.riotgames.com{path}', params=params)
        except httpx.HTTPError:
            raise RiotError(502, 'Riot API 연결에 실패했습니다. 잠시 뒤 다시 조회해주세요.') from None
        if response.status_code == 429:
            try:
                retry = max(1, int(float(response.headers.get('Retry-After', '120'))))
            except (ValueError, OverflowError):
                retry = 120
            self.cooldown = time.monotonic() + retry
            raise RiotError(429, 'Riot API 호출 제한에 도달했습니다.', retry)
        messages = {401: '서버의 API 키를 확인해주세요.', 403: 'API 키가 만료됐거나 이 API에 대한 권한이 없습니다.',
                    404: 'Riot ID 또는 경기 정보를 찾지 못했습니다.'}
        if response.status_code != 200:
            raise RiotError(response.status_code if response.status_code in messages else 502,
                            messages.get(response.status_code, 'Riot API가 일시적으로 응답하지 않습니다.'))
        try:
            return response.json()
        except ValueError:
            raise RiotError(502, 'Riot API 응답 형식을 확인할 수 없습니다.') from None

    async def recent(self, game_name, tag_line, count=5):
        key = os.environ.get('RIOT_API_KEY', '').strip()
        if not key:
            raise RiotError(503, '서버에 RIOT_API_KEY가 설정되지 않았습니다. 서비스 실행 안내를 확인해주세요.')
        cache_key = hashlib.sha256(f'{key}|{game_name}|{tag_line}|{count}'.encode()).hexdigest()
        async with self.lock:
            now = time.monotonic()
            self.cache = {k: value for k, value in self.cache.items() if now - value[0] < 60}
            if cache_key in self.cache:
                return {**self.cache[cache_key][1], 'cached': True}
            async with httpx.AsyncClient(headers={'X-Riot-Token': key}, timeout=10, follow_redirects=False) as client:
                account = await self.get(client, 'asia', '/riot/account/v1/accounts/by-riot-id/' + quote(game_name, safe='') + '/' + quote(tag_line, safe=''))
                puuid = account.get('puuid') if isinstance(account, dict) else None
                if not isinstance(puuid, str) or not puuid:
                    raise RiotError(502, '계정 응답에서 PUUID를 확인할 수 없습니다.')
                ids = await self.get(client, 'asia', '/lol/match/v5/matches/by-puuid/' + quote(puuid, safe='') + '/ids', {'queue':420, 'type':'ranked', 'start':0, 'count':count})
                ranks = await self.get(client, 'kr', '/lol/league/v4/entries/by-puuid/' + quote(puuid, safe=''))
                if not isinstance(ids, list) or not isinstance(ranks, list):
                    raise RiotError(502, '경기 목록 또는 랭크 응답 형식이 다릅니다.')
                current_rank = next(({k: row.get(k) for k in ['tier','rank','leaguePoints','wins','losses']} for row in ranks if row.get('queueType') == 'RANKED_SOLO_5x5'), None)
                items, skipped = [], 0
                for match_id in list(dict.fromkeys(ids))[:count]:
                    if not isinstance(match_id, str) or not match_id.startswith('KR_') or not match_id[3:].isdigit():
                        raise RiotError(502, 'KR 경기 목록을 확인할 수 없습니다.')
                    detail = await self.get(client, 'asia', '/lol/match/v5/matches/' + match_id)
                    item = normalize_match(detail, puuid)
                    if item:
                        items.append(item)
                    else:
                        skipped += 1
                result = {'source':'Riot 공식 API · KR 솔로듀오', 'current_rank':current_rank,
                          'items':items, 'skipped':skipped, 'cached':False,
                          'checked_at':datetime.now(timezone.utc).isoformat(),
                          'caveat':'현재 랭크는 경기 당시 티어가 아닙니다. 누락·리메이크·미지원 역할 경기는 복기 입력에서 제외합니다.'}
                if len(self.cache) >= 10:
                    self.cache.pop(next(iter(self.cache)))
                self.cache[cache_key] = (time.monotonic(), result)
                return result


def normalize_match(data, puuid):
    """11.20 이후 완료 KR 솔로 경기만. 식별자·타인 원본은 반환하지 않는다."""
    if not isinstance(data, dict) or not isinstance(data.get('info'), dict):
        return None
    info = data['info']
    if info.get('queueId') != 420 or info.get('platformId') != 'KR' or not info.get('gameEndTimestamp'):
        return None
    participants = info.get('participants', [])
    player = next((p for p in participants if p.get('puuid') == puuid), None)
    if not player or player.get('gameEndedInEarlySurrender'):
        return None
    roles = {'TOP':'TOP','JUNGLE':'JUNGLE','MIDDLE':'MID','BOTTOM':'BOT','UTILITY':'SUPPORT'}
    role = roles.get(player.get('teamPosition'))
    champion = next((c for c in catalogue()['champions'] if c['key'] == str(player.get('championId'))), None)
    seconds = info.get('gameDuration')
    version = str(info.get('gameVersion', '')).split('.')
    if not role or not champion or not isinstance(seconds, (int, float)) or not 300 <= seconds <= 5400 or len(version) < 2 or not all(part.isdigit() for part in version[:2]):
        return None
    try:
        ended = datetime.fromtimestamp(info['gameEndTimestamp']/1000, timezone.utc).isoformat()
        metrics = {key: player.get(field, 0) for key, field in [('gold','goldEarned'),('damage','totalDamageDealtToChampions'),('vision','visionScore'),('kills','kills'),('assists','assists')]}
        if any(not isinstance(value, (int,float)) or value < 0 for value in metrics.values()):
            return None
        team_kills = sum(p.get('kills', 0) for p in participants if p.get('teamId') == player.get('teamId'))
    except (ValueError, TypeError, OverflowError, OSError):
        return None
    return {'champion_id':champion['id'], 'champion_name':champion['name'], 'role':role, 'region':'KR',
            'queue':'RANKED_SOLO', 'patch':'.'.join(version[:2]), 'played_at':ended,
            'duration_minutes':round(seconds/60, 2), **metrics, 'team_kills':team_kills,
            'win':player.get('win'), 'tier':None}


gateway = RiotGateway()
