"""공식 완료 경기의 설명 가능한 요약. 집계만으로 플레이 원인을 단정하지 않는다."""
from service.review import FOCUSES


def match_report(item):
    minutes = item['duration_minutes']
    kp = (item['kills'] + item['assists']) / item['team_kills'] if item['team_kills'] else None
    metrics = {
        'gpm': round(item['gold'] / minutes, 1),
        'dpm': round(item['damage'] / minutes, 1),
        'vision_per_minute': round(item['vision'] / minutes, 2),
        'kill_participation': round(kp, 3) if kp is not None else None,
        'cs_per_minute': round(item['cs'] / minutes, 2) if item.get('cs') is not None else None,
        'damage_share': round(item['damage'] / item['team_damage'], 3) if item.get('team_damage') else None,
    }
    # 역할에 맞는 확인 질문이지, 점수에 따른 좋음/나쁨 판정이 아니다.
    focus_id = 'vision' if item['role'] in {'SUPPORT', 'JUNGLE'} else 'resource'
    focus = FOCUSES[focus_id]
    facts = [f"{minutes:g}분 동안 골드 {item['gold']:,}, 챔피언 피해량 {item['damage']:,}을 기록했습니다."]
    if kp is None:
        facts.append('팀 킬이 0이라 킬 관여율은 계산할 수 없습니다.')
    else:
        facts.append(f"팀 {item['team_kills']}킬 중 킬·도움으로 {item['kills'] + item['assists']}회 관여했습니다 ({kp * 100:.1f}%).")
    if item.get('deaths') is not None:
        facts.append(f"데스 {item['deaths']}회를 기록했습니다. 위치·시점·교환 이득은 종료 수치만으로 판단할 수 없습니다.")
    return {'version': 1, 'metrics': metrics, 'facts': facts,
            'focus': {'id': focus_id, 'label': focus['label']},
            'questions': [focus['observation'], focus['hypothesis']],
            'next_step': focus['action'], 'peer_percentile': None,
            'limitations': ['핵심 요약은 공식 Match-V5 종료 수치로 만듭니다. 시간대별 흐름은 별도 공식 타임라인이며 리플레이 장면 분석은 포함하지 않습니다.',
                            '현재 랭크를 경기 당시 티어로 대체하지 않습니다. 동티어 점수·승패 원인은 산출하지 않습니다.']}
