"""직접 입력한 완료 경기의 요약과 복기 질문. 실력 점수나 원인 판정을 만들지 않는다."""
FOCUSES = {
    'vision': {
        'label': '오브젝트 전 시야 준비',
        'observation': '오브젝트 전 와드·제거·복귀·합류를 리플레이의 시각과 함께 기록해보세요.',
        'hypothesis': '시야를 준비할 기회와 안전한 접근 경로가 있었는지 확인합니다.',
        'action': '다음 경기에서 오브젝트 전에 확인할 경로와 합류 조건 한 가지를 정해보세요.',
        'measurement': '분당 시야 점수는 요약 지표입니다. 와드의 위치·시점·생존은 별도로 확인합니다.',
    },
    'fight_setup': {
        'label': '교전 전 합류와 자원',
        'observation': '기억에 남는 교전 하나의 시각, 아군 합류와 내 위치를 적어보세요.',
        'hypothesis': '참여 직전 인원·체력·아이템·합류 조건을 확인했는지 검토합니다.',
        'action': '다음 교전에 들어가기 전 확인할 조건 한 가지를 골라보세요.',
        'measurement': '킬 관여율은 참여 결과입니다. 교전을 잘 선택했는지는 리플레이로 확인합니다.',
    },
    'resource': {
        'label': '파밍과 귀환 선택',
        'observation': '귀환 또는 이동으로 자원을 놓친 장면의 시각과 당시 선택을 적어보세요.',
        'hypothesis': '귀환·웨이브·합류 선택에 다른 대안이 있었는지 검토합니다.',
        'action': '다음 경기에서 귀환이나 웨이브 처리 전에 확인할 조건 하나를 정해보세요.',
        'measurement': '경기 전체 GPM으로 특정 시점의 파밍 실수나 귀환 원인을 판단할 수 없습니다.',
    },
    'matchup': {
        'label': '라인전 상대와 선택',
        'observation': '라인전에서 손해를 본 장면의 시각, 거리·웨이브·내 선택을 적어보세요.',
        'hypothesis': '챔피언 상성 설명과 실제 장면이 맞는지 따로 확인합니다.',
        'action': '같은 상대를 만났을 때 확인할 거리·웨이브 조건 하나를 정해보세요.',
        'measurement': '상대 정보와 최신 매치업 표본이 연결되지 않아 유불리 점수는 계산하지 않습니다.',
    },
}


def review_summary(request, champion):
    focus = FOCUSES[request.focus]
    context = {
        'region': request.region, 'queue': request.queue, 'tier': request.tier,
        'role': request.role, 'patch': request.patch,
        'champion_id': request.champion_id,
        'champion_name': champion['name'] if champion else None,
        'played_at': request.played_at.isoformat() if request.played_at else None,
    }
    complete = all(context.values())
    return {
        'source': '합성 예제' if request.is_example else '직접 입력 · 전적 검증 전',
        'role': request.role, 'is_example': request.is_example,
        'context': context, 'personal_record_eligible': complete and not request.is_example,
        'focus': {'id': request.focus, **focus},
        'metrics': {
            'gpm': round(request.gold / request.duration_minutes, 1),
            'dpm': round(request.damage / request.duration_minutes, 1),
            'vision_per_minute': round(request.vision / request.duration_minutes, 2),
            'kill_participation': round((request.kills + request.assists) / request.team_kills, 3) if request.team_kills else None,
        },
        'peer_percentile': None,
        'explanation': '한 경기의 직접 입력을 요약했습니다. 지표·리플레이에서 확인한 사실·내 가설을 구분해 복기하세요. 동티어 백분위와 승리 원인은 판정하지 않습니다.',
        'questions': [focus['observation'], focus['hypothesis'], focus['action']],
    }
