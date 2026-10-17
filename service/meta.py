"""개인 식별자를 제거한 Match-V5 표본 집계. 티어 점수는 만들지 않는다."""

import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeGuard

ROOT = Path(__file__).resolve().parents[1]
ROLES = {'TOP': 'TOP', 'JUNGLE': 'JUNGLE', 'MIDDLE': 'MID', 'BOTTOM': 'BOT', 'UTILITY': 'SUPPORT'}
MINIMUM = 30


def _is_number(value: object) -> TypeGuard[int | float]:
    """Return True for plain int/float values (bool is intentionally excluded)."""
    return type(value) in (int, float)


def clean_game(data, patch, catalogue):
    info = data.get('info', {}) if isinstance(data, dict) else {}
    if not isinstance(info, dict):
        return None
    ps = info.get('participants')
    version = '.'.join(str(info.get('gameVersion', '')).split('.')[:2])
    if info.get('queueId') != 420 or info.get('platformId') != 'KR' or version != patch:
        return None
    duration, ended = info.get('gameDuration'), info.get('gameEndTimestamp')
    if not _is_number(duration) or not 300 <= duration <= 5400 or not _is_number(ended) or not math.isfinite(ended):
        return None
    if not isinstance(ps, list) or len(ps) != 10 or not all(isinstance(p, dict) for p in ps):
        return None
    if any(p.get('gameEndedInEarlySurrender') for p in ps):
        return None
    ids = {int(c['key']): c['id'] for c in catalogue['champions']}
    rows = []
    for p in ps:
        if (
            type(p.get('championId')) is not int
            or p['championId'] not in ids
            or p.get('teamPosition') not in ROLES
            or type(p.get('win')) is not bool
            or p.get('teamId') not in (100, 200)
        ):
            return None
        rows.append(
            {
                'champion_id': ids[p['championId']],
                'role': ROLES[p['teamPosition']],
                'win': p['win'],
                'team': p['teamId'],
            }
        )
    if len({(r['team'], r['role']) for r in rows}) != 10 or len({r['champion_id'] for r in rows}) != 10:
        return None
    for team in (100, 200):
        if len({r['win'] for r in rows if r['team'] == team}) != 1:
            return None
    if sum(r['win'] for r in rows) != 5:
        return None
    teams = info.get('teams', [])
    bans = []
    bans_known = False
    if (
        isinstance(teams, list)
        and len(teams) == 2
        and all(isinstance(t, dict) and isinstance(t.get('bans'), list) for t in teams)
    ):
        values = [b.get('championId') for t in teams for b in t['bans'] if isinstance(b, dict)]
        if len(values) == 10 and all(type(v) is int and (v in ids or v == -1) for v in values):
            bans = [ids[v] for v in values if v in ids]
            bans_known = True
    try:
        played_at = datetime.fromtimestamp(ended / 1000, UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        return None
    return {
        'played_at': played_at,
        'rows': [{k: r[k] for k in ('champion_id', 'role', 'win')} for r in rows],
        'bans': bans,
        'bans_known': bans_known,
    }


def wilson(wins, n):
    z = 1.96
    p = wins / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [round(100 * (center - spread), 1), round(100 * (center + spread), 1)]


def aggregate(games, scope, collection):
    picks: Counter[tuple[str, str]] = Counter()
    wins: Counter[tuple[str, str]] = Counter()
    roles: Counter[str] = Counter()
    bans: Counter[str] = Counter()
    for game in games:
        for r in game['rows']:
            key = (r['champion_id'], r['role'])
            picks[key] += 1
            wins[key] += int(r['win'])
            roles[r['role']] += 1
        bans.update(set(game['bans']))
    ban_games = sum(bool(g['bans_known']) for g in games)
    items = []
    for (champion, role), n in picks.items():
        eligible = n >= MINIMUM
        interval = wilson(wins[(champion, role)], n) if eligible else None
        items.append(
            {
                'champion_id': champion,
                'role': role,
                'games': n,
                'wins': wins[(champion, role)],
                'win_rate': round(wins[(champion, role)] / n * 100, 1) if eligible else None,
                'interval': interval,
                'pick_rate': round(n / roles[role] * 100, 2),
                'ban_rate': round(bans[champion] / ban_games * 100, 2) if ban_games else None,
                'signal': 'positive'
                if eligible and interval is not None and interval[0] > 50
                else 'uncertain'
                if eligible
                else 'small_sample',
            }
        )
    return {
        'schema_version': 1,
        'collected_at': datetime.now(UTC).isoformat(),
        'scope': scope,
        'games': len(games),
        'participants': sum(roles.values()),
        'role_denominators': dict(roles),
        'ban_denominator': ban_games,
        'minimum_games': MINIMUM,
        'collection': collection,
        'period': {
            'first': min((g['played_at'] for g in games), default=None),
            'last': max((g['played_at'] for g in games), default=None),
        },
        'items': sorted(items, key=lambda r: (r['role'], -r['games'], r['champion_id'])),
        'sources': [
            {'title': 'Riot Match-V5', 'url': 'https://developer.riotgames.com/apis#match-v5'},
            {'title': 'Riot League-V4', 'url': 'https://developer.riotgames.com/apis#league-v4'},
        ],
        'caveats': [
            'KR 실버 II 현재 랭크 계정을 출발점으로 수집한 편의 표본입니다. 모든 참가자의 경기 당시 티어를 확인하지 않았습니다.',
            '출발 계정은 랭크 목록의 제한된 페이지에서 시즌 경기 수가 많은 순으로 선택합니다. 활동적인 선수·반복 선수의 영향이 남습니다.',
            '픽 비중은 해당 포지션의 참여 행 대비 비중, 밴 비중은 밴 정보가 확인된 경기 대비 비중입니다.',
            '승률 구간은 Wilson 95% 참고 구간입니다. 반복 선수·경기 내 의존성과 다중 비교를 보정하지 않아 확정 추천이나 실력 점수가 아닙니다.',
        ],
    }


def current_meta():
    path = ROOT / 'service/data/current_meta.json'
    if not path.exists():
        return {'available': False, 'items': [], 'reason': '현재 패치 표본을 수집 중입니다.'}
    from service.evidence import catalogue

    data = json.loads(path.read_text(encoding='utf-8'))
    patch = '.'.join(catalogue()['version'].split('.')[:2])
    age = (datetime.now(UTC) - datetime.fromisoformat(data['collected_at'])).total_seconds()
    return {
        **data,
        'available': bool(data['games']),
        'stale': age > 3 * 86400 or data['scope']['patch'] != patch,
        'static_patch': patch,
    }
