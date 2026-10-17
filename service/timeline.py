"""타임라인에서 관측한 골드·CS·데스만 반환한다. 식별자·좌표는 노출하지 않는다."""

import math


def timeline_summary(raw, participant_id, opponent_id, team_id):
    info = raw.get('info', {}) if isinstance(raw, dict) else {}
    frames = info.get('frames', []) if isinstance(info, dict) else []
    if not isinstance(frames, list):
        return {'available': False, 'points': [], 'deaths': []}
    points = []
    deaths = []

    def number(value):
        return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None

    for frame in frames:
        if not isinstance(frame, dict):
            continue
        timestamp = number(frame.get('timestamp'))
        pf = frame.get('participantFrames', {})
        if timestamp is None or not isinstance(pf, dict):
            continue
        own = pf.get(str(participant_id), {})
        other = pf.get(str(opponent_id), {})
        if not isinstance(own, dict) or not isinstance(other, dict):
            continue
        gold = number(own.get('totalGold'))
        enemy_gold = number(other.get('totalGold'))
        cs_values = [number(p.get(k)) for p in (own, other) for k in ('minionsKilled', 'jungleMinionsKilled')]
        own_cs = sum(cs_values[:2]) if all(v is not None for v in cs_values[:2]) else None
        enemy_cs = sum(cs_values[2:]) if all(v is not None for v in cs_values[2:]) else None
        # 실제 프레임 시각을 표시하며 고정 시각으로 보간하지 않는다.
        points.append(
            {
                'minute': round(timestamp / 60000, 2),
                'gold': gold,
                'opponent_gold': enemy_gold,
                'gold_difference': gold - enemy_gold if gold is not None and enemy_gold is not None else None,
                'cs': own_cs,
                'opponent_cs': enemy_cs,
                'cs_difference': own_cs - enemy_cs if own_cs is not None and enemy_cs is not None else None,
            }
        )
        events = frame.get('events', [])
        if isinstance(events, list):
            for event in events:
                if (
                    isinstance(event, dict)
                    and event.get('type') == 'CHAMPION_KILL'
                    and event.get('victimId') == participant_id
                ):
                    stamp = number(event.get('timestamp'))
                    if stamp is not None:
                        deaths.append(round(stamp / 60000, 2))
    return {
        'available': bool(points),
        'points': points,
        'deaths': deaths[:200],
        'caveat': '같은 포지션 상대와 비교한 실제 프레임 수치입니다. 라인 교대·로밍·정글 개입과 교환 이득은 이 차이만으로 판단할 수 없습니다.',
    }
