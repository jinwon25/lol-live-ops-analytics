"""현재 패치 KR 솔로랭크 표본을 티어별 층화 추출(Stratified Sampling)로 수집한다."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
import httpx

from service.evidence import catalogue, review_store
from service.meta import aggregate, clean_game
from service.riot import RiotError, RiotGateway
from service.riot_transport import configure_json_logger

TIERS = [
    'IRON',
    'BRONZE',
    'SILVER',
    'GOLD',
    'PLATINUM',
    'EMERALD',
    'DIAMOND',
    'MASTER',
]
DEFAULT_DIVISION = 'II'
APEX_TIERS = frozenset({'MASTER', 'GRANDMASTER', 'CHALLENGER'})
RANKED_SOLO_QUEUE = 'RANKED_SOLO_5x5'
RANKED_SOLO_QUEUE_ID = 420
MIN_REQUEST_DELAY_SECONDS = 1.6
TRANSIENT_RETRY_SLEEP_SECONDS = 2.0
DEFAULT_HTTP_TIMEOUT_SECONDS = 15.0

collector_logger = configure_json_logger('lol_live_ops.collector')


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def build_league_endpoint(
    tier_or_queue: str,
    tier_or_division: str = DEFAULT_DIVISION,
    division: str | None = None,
) -> str:
    """Return the Riot League-V4 endpoint path for the given tier (supports both 2-arg and 3-arg forms)."""
    if division is not None:
        queue = tier_or_queue
        normalized_tier = tier_or_division.upper()
        resolved_division = division
    else:
        queue = RANKED_SOLO_QUEUE
        normalized_tier = tier_or_queue.upper()
        resolved_division = tier_or_division

    if normalized_tier == 'MASTER':
        return f'/lol/league/v4/masterleagues/by-queue/{queue}'
    if normalized_tier == 'GRANDMASTER':
        return f'/lol/league/v4/grandmasterleagues/by-queue/{queue}'
    if normalized_tier == 'CHALLENGER':
        return f'/lol/league/v4/challengerleagues/by-queue/{queue}'
    return f'/lol/league/v4/entries/{queue}/{normalized_tier}/{resolved_division}'


def allocate_stratified_seeds(
    tier_seed_maps_or_total: dict[str, dict[str, int]] | int,
    total_seeds_or_tiers: int | list[str] | tuple[str, ...] = TIERS,
    tiers: list[str] | tuple[str, ...] = TIERS,
) -> dict[str, int] | list[tuple[str, str]]:
    """Compute equal stratified quotas per tier or select round-robin PUUIDs per tier."""
    if isinstance(tier_seed_maps_or_total, int):
        total_quota = tier_seed_maps_or_total
        target_tiers = list(total_seeds_or_tiers) if isinstance(total_seeds_or_tiers, (list, tuple)) else list(tiers)
        if not target_tiers or total_quota <= 0:
            return {}
        base_quota, remainder = divmod(total_quota, len(target_tiers))
        return {
            tier: base_quota + (1 if idx < remainder else 0)
            for idx, tier in enumerate(target_tiers)
        }

    tier_seed_maps = tier_seed_maps_or_total
    total_seeds = int(total_seeds_or_tiers) if isinstance(total_seeds_or_tiers, int) else 40
    active_tiers = [tier for tier in tiers if tier_seed_maps.get(tier)]
    if not active_tiers or total_seeds <= 0:
        return []

    per_tier_quota = max(1, math.ceil(total_seeds / len(active_tiers)))
    ordered_by_tier: dict[str, list[str]] = {}
    for tier in active_tiers:
        candidates = tier_seed_maps[tier]
        sorted_puuids = sorted(
            candidates,
            key=lambda puuid: (-candidates[puuid], hashlib.sha256(puuid.encode()).hexdigest()),
        )
        ordered_by_tier[tier] = sorted_puuids[:per_tier_quota]

    stratified_list: list[tuple[str, str]] = []
    seen_puuids: set[str] = set()
    for slot_index in range(per_tier_quota):
        for tier in active_tiers:
            tier_candidates = ordered_by_tier.get(tier, [])
            if slot_index < len(tier_candidates):
                puuid = tier_candidates[slot_index]
                if puuid not in seen_puuids:
                    seen_puuids.add(puuid)
                    stratified_list.append((tier, puuid))
                    if len(stratified_list) >= total_seeds:
                        return stratified_list
    return stratified_list


async def collect(args: argparse.Namespace) -> dict[str, Any]:
    load_dotenv(ROOT / 'service/.env', override=False)
    api_key = os.environ.get('RIOT_API_KEY', '').strip()
    if not api_key:
        raise SystemExit('RIOT_API_KEY 설정이 필요합니다.')

    cat = catalogue()
    patch = '.'.join(cat['version'].split('.')[:2])
    selected_tiers = list(args.tiers) if getattr(args, 'tiers', None) else list(TIERS)
    scope = {
        'region': 'KR',
        'queue': RANKED_SOLO_QUEUE_ID,
        'patch': patch,
        'seed_tiers': selected_tiers,
        'seed_division': DEFAULT_DIVISION,
        'days': args.days,
        'seed_pages': args.pages,
        'sampling': 'stratified_by_tier_season_games_desc_hash_tiebreak',
    }
    checkpoint = ROOT / '.local/meta-active-checkpoint.json'
    state: dict[str, Any] = {
        'scope': scope,
        'games': {},
        'attempted': [],
        'tier_counts': {tier: 0 for tier in selected_tiers},
    }
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding='utf-8'))
        # Do not bypass Retry-After cooldown from a previous 429 response.
        if saved.get('not_before', 0) > time.time():
            wait_seconds = int(saved['not_before'] - time.time()) + 1
            raise SystemExit(f'이전 429 응답의 Retry-After 대기 중입니다. {wait_seconds}초 뒤 다시 실행하세요.')
        if saved.get('scope') == scope and not args.fresh:
            state = saved
            state.setdefault('tier_counts', {tier: 0 for tier in selected_tiers})

    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    state['games'] = {key: game for key, game in state['games'].items() if game['played_at'] >= cutoff}
    attempted = set(state['attempted'])
    gateway_instance = RiotGateway()
    calls = 0
    last_call_ts = 0.0
    skipped = 0
    stopped = None

    async with httpx.AsyncClient(
        headers={'X-Riot-Token': api_key},
        timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
        follow_redirects=False,
    ) as client:

        async def fetch_riot(host: str, path: str, params: dict[str, Any] | None = None) -> Any:
            nonlocal calls, last_call_ts
            for attempt in range(2):
                if calls >= args.max_calls:
                    raise RiotError(429, '총 요청 예산에 도달했습니다.', 1)
                await asyncio.sleep(max(0.0, args.delay - (time.monotonic() - last_call_ts)))
                last_call_ts = time.monotonic()
                calls += 1
                try:
                    return await gateway_instance.get(client, host, path, params)
                except RiotError as error:
                    if error.status != 502 or attempt:
                        raise
                    await asyncio.sleep(TRANSIENT_RETRY_SLEEP_SECONDS)

        try:
            tier_seed_maps: dict[str, dict[str, int]] = {tier: {} for tier in selected_tiers}
            for tier in selected_tiers:
                endpoint = build_league_endpoint(tier, DEFAULT_DIVISION)
                max_pages = 1 if tier in APEX_TIERS else args.pages
                for page in range(1, max_pages + 1):
                    params = None if tier in APEX_TIERS else {'page': page}
                    seeds_payload = await fetch_riot('kr', endpoint, params)
                    seeds = seeds_payload.get('entries') if isinstance(seeds_payload, dict) else seeds_payload
                    if not isinstance(seeds, list):
                        raise RiotError(502, f'{tier} 랭크 출발 표본 응답 형식을 확인해주세요.')
                    for row in seeds:
                        if (
                            isinstance(row, dict)
                            and isinstance(row.get('puuid'), str)
                            and row['puuid']
                            and type(row.get('wins')) is int
                            and type(row.get('losses')) is int
                        ):
                            tier_seed_maps[tier][row['puuid']] = row['wins'] + row['losses']

            stratified_seeds = allocate_stratified_seeds(tier_seed_maps, args.seeds, selected_tiers)

            if not stratified_seeds:
                raise RiotError(502, '티어별 랭크 표본에서 PUUID를 확인하지 못했습니다.')

            start_epoch = int((datetime.now(timezone.utc) - timedelta(days=args.days)).timestamp())
            stop_collection = False
            for index, (seed_tier, puuid) in enumerate(stratified_seeds):
                match_ids = await fetch_riot(
                    'asia',
                    f'/lol/match/v5/matches/by-puuid/{quote(puuid, safe="")}/ids',
                    {
                        'queue': RANKED_SOLO_QUEUE_ID,
                        'type': 'ranked',
                        'start': 0,
                        'count': args.per_seed,
                        'startTime': start_epoch,
                    },
                )
                if not isinstance(match_ids, list):
                    raise RiotError(502, '경기 목록 응답 형식을 확인해주세요.')
                for match_id in match_ids:
                    if not isinstance(match_id, str) or not re.fullmatch(r'KR_[0-9]+', match_id):
                        continue
                    digest = hashlib.sha256(match_id.encode()).hexdigest()
                    if digest in attempted:
                        continue
                    if len(state['games']) >= args.matches:
                        stop_collection = True
                        break
                    raw_match = await fetch_riot('asia', '/lol/match/v5/matches/' + match_id)
                    cleaned_game = clean_game(raw_match, patch, cat)
                    attempted.add(digest)
                    if cleaned_game:
                        cleaned_game['seed_tier'] = seed_tier
                        state['games'][digest] = cleaned_game
                        state['tier_counts'][seed_tier] = state['tier_counts'].get(seed_tier, 0) + 1
                    else:
                        skipped += 1
                    state['attempted'] = sorted(attempted)
                    atomic_json(checkpoint, state)

                collector_logger.info(
                    'Seed collection progress',
                    extra={
                        'structured_data': {
                            'event': 'meta_seed_progress',
                            'seed_index': index + 1,
                            'seed_total': len(stratified_seeds),
                            'seed_tier': seed_tier,
                            'unique_games': len(state['games']),
                            'riot_api_calls': calls,
                        }
                    },
                )
                if stop_collection:
                    break
        except RiotError as error:
            stopped = {'status': error.status, 'retry_after': error.retry_after, 'reason': error.message}
            if error.status == 429:
                state['not_before'] = time.time() + (error.retry_after or 120)
                atomic_json(checkpoint, state)
            collector_logger.warning(
                'Meta collection stopped due to Riot API error',
                extra={
                    'structured_data': {
                        'event': 'meta_collection_stopped',
                        'status_code': error.status,
                        'retry_after': error.retry_after,
                        'reason': error.message,
                        'riot_api_calls': calls,
                    }
                },
            )

    report = aggregate(
        list(state['games'].values()),
        scope,
        {
            'calls_this_run': calls,
            'attempted_unique': len(attempted),
            'excluded_this_run': skipped,
            'max_calls': args.max_calls,
            'max_matches': args.matches,
            'tier_counts': state.get('tier_counts', {}),
            'stopped': stopped,
        },
    )
    if report['games']:
        atomic_json(ROOT / 'service/data/current_meta.json', report)
        snapshot_id = review_store.persist_meta_snapshot(report)
        report['snapshot_id'] = snapshot_id

    collector_logger.info(
        'Meta collection completed',
        extra={
            'structured_data': {
                'event': 'meta_collection_completed',
                'games': report['games'],
                'participants': report['participants'],
                'tier_counts': state.get('tier_counts', {}),
                'riot_api_calls': calls,
            }
        },
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, default=40, choices=range(1, 81))
    parser.add_argument('--per-seed', type=int, default=15, choices=range(1, 21))
    parser.add_argument('--matches', type=int, default=500, choices=range(1, 1001))
    parser.add_argument('--max-calls', type=int, default=650, choices=range(1, 1201))
    parser.add_argument('--days', type=int, default=7, choices=range(1, 15))
    parser.add_argument('--delay', type=float, default=1.7)
    parser.add_argument('--pages', type=int, default=1, choices=range(1, 6))
    parser.add_argument('--tiers', nargs='+', choices=TIERS, default=list(TIERS))
    parser.add_argument('--fresh', action='store_true')
    args = parser.parse_args()
    if args.delay < MIN_REQUEST_DELAY_SECONDS:
        parser.error('다른 로컬 조회의 여유를 위해 요청 간격은 최소 1.6초입니다.')
    asyncio.run(collect(args))


if __name__ == '__main__':
    main()
