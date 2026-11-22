"""과거 패치 공백을 채우는 솔로랭크 경기 연쇄 수집기 (EUN·KR).

알려진 경기의 참가자에서 출발해 인접 주간 구간의 경기를 찾는다. 활동이 적은 계정일수록
경기 목록이 과거까지 남아 있어, 현재 랭크 계정만으로는 닿지 않는 패치까지 이어진다.
주간 구간마다 경기 할당량을 두고 가장 적게 찬 구간부터 채워 패치별 표본을 고르게 만든다.

출력 (모두 비공개 .local/backfill/<지역>/):
- participants.csv: data/raw/2025.csv와 같은 컬럼 + 표본 추적 컬럼. PUUID 대신 지역별 salt 해시.
- raw.jsonl.gz: 재처리용 원본 응답. 공개 저장소에 올리지 않는다.
- state.json: 재시작용 체크포인트.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import hashlib
import json
import os
import random
import secrets
import sqlite3
import sys
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from dotenv import dotenv_values, load_dotenv  # noqa: E402

from scripts.backfill_store import inspect_sample  # noqa: E402
from service.riot import RiotError, RiotGateway  # noqa: E402

REGIONS = {'EUN': ('eun1', 'europe', 'EUN1'), 'KR': ('kr', 'asia', 'KR')}
ROLES = {'TOP': 'TOP', 'JUNGLE': 'JUNGLE', 'MIDDLE': 'MIDDLE', 'BOTTOM': 'BOTTOM', 'UTILITY': 'SUPPORT'}
BASE_COLUMNS = (
    'game_id,start_utc,duration,queue,platform_id,map_id,game_mode,game_version,participant_id,champion_id,'
    'champion_name,position,win,kills,deaths,assists,kda_ratio,kill_participation,gold_earned,gold_spent,'
    'gold_per_min,damage_dealt,damage_per_min,damage_to_champ,damage_champ_per_min,damage_taken,vision_score,'
    'item0,item1,item2,item3,item4,item5,item6,solo_tier,team_baronKills,team_dragonKills,team_towerKills,'
    'team_champKills,team_riftHeraldKills,team_inhibitorKills'
).split(',')
TRACE_COLUMNS = ['region', 'puuid_hash', 'sample_bucket', 'sample_hop']
COLUMNS = BASE_COLUMNS + TRACE_COLUMNS


def atomic_json(path: Path, value: Any) -> None:
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value), encoding='utf-8')
    os.replace(tmp, path)


def participant_rows(match: dict, salt: str, region: str, bucket: int, hop: int) -> list[dict] | None:
    """Match-V5 상세를 원본 스키마 행으로 바꾼다. 랭크 솔로·10인·포지션 완전성을 못 채우면 None."""
    info = match.get('info') or {}
    ps = info.get('participants') or []
    duration = info.get('gameDuration') or 0
    if info.get('queueId') != 420 or len(ps) != 10 or not 300 <= duration <= 5400:
        return None
    if any(p.get('gameEndedInEarlySurrender') for p in ps) or any(p.get('teamPosition') not in ROLES for p in ps):
        return None
    minutes = duration / 60
    team_kills = {t: sum(p['kills'] for p in ps if p['teamId'] == t) for t in (100, 200)}
    objectives = {t['teamId']: t.get('objectives', {}) for t in info.get('teams', [])}
    start = datetime.fromtimestamp(info['gameStartTimestamp'] / 1000, UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
    rows = []
    for p in ps:
        obj = objectives.get(p['teamId'], {})
        rows.append(
            {
                'game_id': info['gameId'],
                'start_utc': start,
                'duration': duration,
                'queue': 'Ranked Solo/Duo',
                'platform_id': info.get('platformId'),
                'map_id': info.get('mapId'),
                'game_mode': info.get('gameMode'),
                'game_version': info.get('gameVersion'),
                'participant_id': p['participantId'],
                'champion_id': p['championId'],
                'champion_name': p['championName'],
                'position': ROLES[p['teamPosition']],
                'win': p['win'],
                'kills': p['kills'],
                'deaths': p['deaths'],
                'assists': p['assists'],
                'kda_ratio': (p['kills'] + p['assists']) / max(p['deaths'], 1),
                'kill_participation': (p['kills'] + p['assists']) / team_kills[p['teamId']]
                if team_kills[p['teamId']]
                else 0.0,
                'gold_earned': p['goldEarned'],
                'gold_spent': p['goldSpent'],
                'gold_per_min': p['goldEarned'] / minutes,
                'damage_dealt': p['totalDamageDealt'],
                'damage_per_min': p['totalDamageDealt'] / minutes,
                'damage_to_champ': p['totalDamageDealtToChampions'],
                'damage_champ_per_min': p['totalDamageDealtToChampions'] / minutes,
                'damage_taken': p['totalDamageTaken'],
                'vision_score': p['visionScore'],
                **{f'item{i}': p.get(f'item{i}') for i in range(7)},
                'solo_tier': '',  # 경기 당시 티어는 API로 확인할 수 없다.
                **{
                    f'team_{name}Kills': obj.get(key, {}).get('kills', 0)
                    for name, key in [
                        ('baron', 'baron'),
                        ('dragon', 'dragon'),
                        ('tower', 'tower'),
                        ('champ', 'champion'),
                        ('riftHerald', 'riftHerald'),
                        ('inhibitor', 'inhibitor'),
                    ]
                },
                'region': region,
                'puuid_hash': hashlib.sha256((salt + p['puuid']).encode()).hexdigest()[:16],
                'sample_bucket': bucket,
                'sample_hop': hop,
            }
        )
    return rows


class MatchIdentityMismatch(ValueError):
    """상세 응답의 경기나 지역이 요청과 일치하지 않는다."""


class Crawler:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.platform, self.routing, self.prefix = REGIONS[args.region]
        self.dir = args.out_dir / args.region
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / 'state.json'
        self.start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
        self.end = datetime.fromisoformat(args.end).replace(tzinfo=UTC) if args.end else datetime.now(UTC)
        self.width = timedelta(days=args.bucket_days)
        if self.width <= timedelta(0) or self.end - self.start < self.width:
            raise ValueError('수집 기간에는 한 개 이상의 완전한 구간이 필요합니다.')
        self.buckets = int((self.end - self.start) / self.width)
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding='utf-8'))
        else:
            if any((self.dir / name).exists() for name in ('participants.csv', 'raw.jsonl.gz')):
                raise ValueError('기존 표본의 체크포인트가 없습니다. 원래 salt와 탐색 상태를 확인하세요.')
            self.state = {
                'salt': secrets.token_hex(16),
                'counts': {},
                'seen': [],
                'queried': [],
                'frontier': {},
                'calls': 0,
            }
        saved, counts, self.patches = inspect_sample(self.dir, args.region, self.prefix, self.state)
        self.recovered = len(saved) - sum(self.state['counts'].values())
        self.counts = self.state['counts'] = dict(counts)
        self.seen = set(self.state['seen'])
        self.seen.update(saved)
        self.queried = set(self.state['queried'])
        self.frontier: dict[str, list] = self.state['frontier']
        self.rng = random.Random(args.rng_seed + self.state['calls'])
        self.calls = 0
        self.last = 0.0

    def save(self) -> None:
        self.state.update(seen=sorted(self.seen), queried=sorted(self.queried), calls=self.state['calls'])
        atomic_json(self.state_path, self.state)

    async def fetch(self, path: str, params: dict | None = None) -> Any:
        backoff = 5
        while True:
            await asyncio.sleep(max(0.0, self.args.delay - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            self.calls += 1
            self.state['calls'] += 1
            try:
                return await self.gateway.get(self.client, self.routing, path, params)
            except RiotError as error:
                if error.status == 429:
                    wait = error.retry_after or 60
                    print(f'호출 한도 도달: {wait}초 대기', flush=True)
                    await asyncio.sleep(wait)
                    continue
                if error.status == 404:
                    return None
                if self.args.max_calls is None and error.status in (502, 503, 504):
                    wait = max(backoff, error.retry_after or 0)
                    print(f'[{self.args.region}] 연결 또는 서버 오류 {error.status} · {wait}초 후 재시도', flush=True)
                    await asyncio.sleep(wait)
                    backoff = min(300, 2 * backoff)
                    continue
                if self.args.max_calls is None and error.status in (401, 403) and self.uses_file_key:
                    print(f'[{self.args.region}] 인증 오류 {error.status} · service/.env의 키 갱신 대기', flush=True)
                    old = self.client.headers['X-Riot-Token']
                    while True:
                        new = (dotenv_values(ROOT / 'service/.env').get('RIOT_API_KEY') or '').strip()
                        if new and new != old:
                            self.client.headers['X-Riot-Token'] = new
                            break
                        await asyncio.sleep(60)
                    continue
                raise

    def bucket_of(self, start_ms: int) -> int:
        return (datetime.fromtimestamp(start_ms / 1000, UTC) - self.start) // self.width

    def add_frontier(self, match: dict, bucket: int, hop: int) -> None:
        for puuid in match['metadata']['participants']:
            for b in (bucket - 1, bucket, bucket + 1):
                key = hashlib.sha256(f'{puuid}|{b}'.encode()).hexdigest()[:20]
                if 0 <= b < self.buckets and key not in self.queried:
                    self.frontier.setdefault(str(b), []).append([puuid, hop + 1])

    async def take(self, match_id: str, hop: int) -> bool:
        """경기를 받아 저장하고 참가자를 탐색 후보에 넣는다. 저장하면 True."""
        match = await self.fetch(f'/lol/match/v5/matches/{match_id}')
        try:
            return self.store_match(match_id, match, hop)
        except MatchIdentityMismatch:
            if self.args.max_calls is not None:
                raise
            print(f'[{self.args.region}] 요청과 다른 경기 상세 응답 1건 제외', flush=True)
            return False

    def store_match(self, match_id: str, match: dict | None, hop: int) -> bool:
        if match_id in self.seen:
            return False
        if match:
            info = match.get('info') or {}
            if (
                match.get('metadata', {}).get('matchId') != match_id
                or f"{self.prefix}_{info.get('gameId')}" != match_id
                or str(info.get('platformId')).upper() != self.prefix
            ):
                raise MatchIdentityMismatch('요청한 경기와 응답의 경기 키 또는 지역이 다릅니다.')
        self.seen.add(match_id)
        if not match or 'info' not in match:
            return False
        bucket = self.bucket_of(match['info'].get('gameStartTimestamp', 0))
        if not 0 <= bucket < self.buckets:
            return False
        self.add_frontier(match, bucket, hop)
        if self.counts.get(str(bucket), 0) >= self.args.per_bucket:
            return False
        rows = participant_rows(match, self.state['salt'], self.args.region, bucket, hop)
        if not rows:
            return False
        new_file = not (self.dir / 'participants.csv').exists()
        with open(self.dir / 'participants.csv', 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, COLUMNS)
            if new_file:
                writer.writeheader()
            writer.writerows(rows)
        with gzip.open(self.dir / 'raw.jsonl.gz', 'at', encoding='utf-8') as f:
            f.write(json.dumps(match, separators=(',', ':')) + '\n')
        self.counts[str(bucket)] = self.counts.get(str(bucket), 0) + 1
        return True

    def next_bucket(self) -> str | None:
        open_buckets = [
            b
            for b, cands in self.frontier.items()
            if cands and self.counts.get(b, 0) < self.args.per_bucket and int(b) < self.buckets
        ]
        if not open_buckets:
            return None
        low = min(self.counts.get(b, 0) for b in open_buckets)
        return self.rng.choice([b for b in open_buckets if self.counts.get(b, 0) == low])

    async def run(self) -> None:
        load_dotenv(ROOT / 'service/.env', override=False)
        key = os.environ.get('RIOT_API_KEY', '').strip()
        if not key:
            raise SystemExit('RIOT_API_KEY 설정이 필요합니다.')
        self.uses_file_key = key == (dotenv_values(ROOT / 'service/.env').get('RIOT_API_KEY') or '').strip()
        self.gateway = RiotGateway()
        self.save()  # 첫 경기 저장 전에도 salt와 시작 상태를 복구할 수 있게 한다.
        async with httpx.AsyncClient(headers={'X-Riot-Token': key}, timeout=20) as self.client:
            try:
                if not self.quota_met():
                    for match_id in self.args.seed_ids:
                        if match_id not in self.seen:
                            await self.take(match_id, 0)
                await self._loop()
            finally:
                self.save()
        if self.args.max_calls is None:
            checkpoint = json.loads(self.state_path.read_bytes())
            saved, counts, _ = inspect_sample(self.dir, self.args.region, self.prefix, checkpoint)
            if counts != checkpoint['counts'] or not saved.issubset(checkpoint['seen']) or not self.quota_met():
                raise RuntimeError('목표 건수와 최종 저장본을 확인하세요.')
            print(
                f'[{self.args.region}] 목표 달성 · {self.buckets}구간 × {self.args.per_bucket}경기 검증 완료',
                flush=True,
            )
        print(f'[{self.args.region}] 종료 · 호출 {self.calls}', flush=True)

    def quota_met(self) -> bool:
        return all(self.counts.get(str(i), 0) >= self.args.per_bucket for i in range(self.buckets))

    async def _loop(self) -> None:
        saved, last_save = 0, 0
        while self.args.max_calls is None or self.calls < self.args.max_calls:
            bucket = self.next_bucket()
            if bucket is None:
                if self.args.max_calls is None and not self.quota_met():
                    missing = sum(
                        max(0, self.args.per_bucket - self.counts.get(str(i), 0)) for i in range(self.buckets)
                    )
                    raise SystemExit(
                        f'[{self.args.region}] 후보 소진 · 목표까지 {missing}경기 부족. 출발 경기 추가 필요.'
                    )
                print('채울 수 있는 구간이 더 없습니다.', flush=True)
                break
            cands = self.frontier[bucket]
            puuid, hop = cands.pop(self.rng.randrange(len(cands)))
            qkey = hashlib.sha256(f'{puuid}|{bucket}'.encode()).hexdigest()[:20]
            if qkey in self.queried:
                continue
            lo = self.start + int(bucket) * self.width
            try:
                ids = await self.fetch(
                    f'/lol/match/v5/matches/by-puuid/{puuid}/ids',
                    {
                        'queue': 420,
                        'startTime': int(lo.timestamp()),
                        'endTime': int((lo + self.width).timestamp()),
                        'count': 100,
                    },
                )
                fresh = [m for m in ids or [] if m.startswith(self.prefix + '_') and m not in self.seen]
                for match_id in self.rng.sample(fresh, min(self.args.per_player, len(fresh))):
                    saved += await self.take(match_id, hop)
            except BaseException:
                cands.append([puuid, hop])
                raise
            self.queried.add(qkey)
            if self.calls - last_save >= 50:
                last_save = self.calls
                # 탐색 후보가 너무 커지지 않게 구간별로 무작위 표본만 남긴다.
                for b, c in self.frontier.items():
                    if len(c) > 2000:
                        self.frontier[b] = self.rng.sample(c, 2000)
                self.save()
                filled = sum(min(v, self.args.per_bucket) for v in self.counts.values())
                print(
                    f'[{self.args.region}] 호출 {self.calls} · 이번 실행 저장 {saved}경기 · '
                    f'누적 {filled}/{self.buckets * self.args.per_bucket}',
                    flush=True,
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--region', choices=REGIONS, required=True)
    parser.add_argument('--seed-ids', nargs='*', default=[], help='출발 경기 ID 목록')
    parser.add_argument('--seed-file', type=Path, help='출발 경기 ID 목록 파일(한 줄에 하나)')
    parser.add_argument('--start', default='2025-01-06', help='첫 구간 시작일(UTC)')
    parser.add_argument('--end', help='마지막 구간 끝(UTC). 생략하면 지금')
    parser.add_argument('--bucket-days', type=int, default=7)
    parser.add_argument('--per-bucket', type=int, default=500, help='주간 구간당 경기 할당량')
    parser.add_argument('--per-player', type=int, default=2, help='계정·구간당 가져올 최대 경기 수')
    limit = parser.add_mutually_exclusive_group()
    limit.add_argument('--max-calls', type=int, default=3000)
    limit.add_argument(
        '--until-complete',
        dest='max_calls',
        action='store_const',
        const=None,
        help='모든 주간 할당량을 채우고 저장 파일 검증 후 종료',
    )
    parser.add_argument('--delay', type=float, default=1.25, help='앱 한도 100회/2분에 맞춘 최소 간격')
    parser.add_argument('--rng-seed', type=int, default=25)
    parser.add_argument('--out-dir', type=Path, default=ROOT / '.local/backfill', help='비공개 출력 폴더')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--audit-only', action='store_true', help='API 호출 없이 저장 파일과 패치별 표본 검사')
    mode.add_argument('--repair-checkpoint', action='store_true', help='저장 파일을 대조한 후 체크포인트만 동기화')
    args = parser.parse_args()
    if args.per_bucket <= 0:
        parser.error('구간당 목표 경기 수는 양수여야 합니다.')
    if args.delay < 1.2:
        parser.error('앱 한도(100회/2분) 때문에 요청 간격은 최소 1.2초입니다.')
    if args.seed_file:
        args.seed_ids += [x.strip() for x in args.seed_file.read_text(encoding='utf-8').split() if x.strip()]
    directory = args.out_dir / args.region
    if (args.audit_only or args.repair_checkpoint) and not (directory / 'state.json').is_file():
        parser.error('검사할 지역의 state.json이 없습니다.')
    directory.mkdir(parents=True, exist_ok=True)
    # 지역별 단일 작성자. 프로세스가 강제 종료되어도 SQLite가 잠금을 해제한다.
    with closing(sqlite3.connect(directory / 'writer.sqlite', timeout=0)) as lock:
        lock.execute('BEGIN IMMEDIATE')
        crawler = Crawler(args)
        if args.audit_only or args.repair_checkpoint:
            print(
                f'[{args.region}] {sum(crawler.counts.values())}경기 · {len(crawler.counts)}구간 · '
                f'{len(crawler.patches)}개 패치 · 체크포인트와 {crawler.recovered}경기 차이'
            )
            for patch, durations in sorted(
                crawler.patches.items(), key=lambda item: tuple(map(int, item[0].split('.')))
            ):
                print(f'{patch}  {len(durations)}경기  경기 시간 중앙값 {median(durations) / 60:.1f}분')
            if args.repair_checkpoint:
                crawler.save()
        else:
            asyncio.run(crawler.run())


if __name__ == '__main__':
    main()
