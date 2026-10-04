"""추적 가능한 집계만 읽는다. 원본 DB·참여자 행·API 키에 접근하지 않는다."""
import csv
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = 'https://github.com/jinwon25/lol-live-ops-analytics/blob/main/'
SCOPE = {'patches': ['15.1', '15.3'], 'region': 'EUN',
         'queue': '솔로듀오', 'cohort': 'PLATINUM·EMERALD·DIAMOND',
         'unit': '경기×참여자', 'is_current_match_data': False}


def rows(filename):
    with (ROOT / 'outputs' / filename).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


@lru_cache(maxsize=1)
def catalogue():
    return json.loads((ROOT / 'service/data/catalogue.json').read_text(encoding='utf-8'))


def champion_history(champion_id):
    return [row for row in rows('champion_meta.csv') if row['champion_en'].casefold() == champion_id.casefold()]


def answer(question, champion_id=None):
    q = question.casefold()
    result = {'status': 'documented', 'scope': SCOPE, 'sources': [],
              'caveats': ['기존 경기 표본은 2025년 초 패치 15.1·15.3이며 현재 메타를 대표하지 않습니다.'],
              'next_step': '근거와 비교 조건을 확인한 뒤 검토할 질문 한 가지를 복기 노트에 남겨보세요.'}
    if any(word in q for word in ['최신', '지금', '현재', '추천', '사기', '티어리스트', '아이템', '룬', '빌드']):
        cat = catalogue()
        result.update(status='insufficient_data', answer=f'확인된 공식 챔피언 정적 자료는 {cat["version"]}입니다. 챔피언 이름·분류·기본 수치를 확인할 수 있지만 최신 승률·추천 빌드를 계산할 경기 표본은 연결되지 않았습니다. 과거 승률을 현재 추천으로 바꾸어 답하지 않습니다.',
                      sources=[{'title': '공식 Data Dragon 정적 자료', 'url': cat['source_url']},
                               {'title': 'Riot API와 정적 자료의 구분', 'url': 'https://developer.riotgames.com/docs/lol'}])
    elif any(word in q for word in ['패치', '메타', '변화', '승률', '챔피언']):
        history = champion_history(champion_id) if champion_id else []
        if history:
            eligible = [r for r in history if int(r['pick_count']) >= 30]
            detail = ' / '.join(f'{r["patch"]} {r["role"]}: {r["pick_count"]}행, 관측 승률 {r["win_rate_pct"]}%' for r in eligible[:5])
            result['answer'] = ('선택한 챔피언의 과거 코호트 집계입니다. ' + detail + '. 표본 수·역할을 함께 확인하세요. 다른 챔피언·상대·숙련도 차이는 남아 있습니다.') if eligible else '선택한 챔피언은 과거 역할별 표본이 모두 30행 미만이라 승률로 강함을 판단하지 않습니다.'
            if len(eligible) < len(history): result['caveats'].append('30행 미만인 역할·패치의 승률 설명은 보류했습니다. 30행은 표시용 최소 기준이며 충분한 정밀도를 보장하지 않습니다.')
        else:
            result['answer'] = '기존 분석에서 이즈리얼의 픽 비중 변화는 전체 표본 +0.35%p, 공통 티어 표본 +0.13%p였습니다. 비교 조건에 민감한 신호라는 뜻이며 티어가 변화를 전부 설명하거나 패치의 인과효과를 측정했다는 뜻은 아닙니다.'
            if champion_id:
                result['status'] = 'insufficient_data'
                result['answer'] = '선택한 챔피언에 대한 과거 집계가 없습니다. 현재 공식 목록에 있다는 사실만으로 승률이나 추천을 만들 수 없습니다.'
        result['sources'] = [{'title': '챔피언별 역할·패치 집계', 'url': REPO + 'outputs/champion_meta.csv'}, {'title': '메타 분석 설계와 해석', 'url': REPO + 'docs/02_phase2_notes.md'}]
        result['caveats'].append('여러 챔피언 비교의 다중검정과 경기 내 관측 의존성은 후속 검증 대상입니다.')
    elif any(word in q for word in ['군집', '유형', '성향', '스타일', '페르소나']):
        result['answer'] = 'K=4 군집은 한 경기의 행동 유형을 요약합니다. 분당 골드·딜, 시야 점수, 킬 관여율을 역할 안에서 표준화했습니다. 같은 사람을 여러 경기에서 추적한 성격 검사가 아니며, 승패와 경기 흐름의 영향도 남아 있습니다.'
        result['sources'] = [{'title': '행동 군집의 입력과 한계', 'url': REPO + 'docs/03_phase3_notes.md'}, {'title': '군집 집계', 'url': REPO + 'outputs/segment_summary.csv'}]
    elif any(word in q for word in ['복기', '시야', '연습', '교전', '골드']):
        result['answer'] = '완료된 경기에서 확인할 질문을 하나 정해보세요. 예를 들어 오브젝트 직전의 시야 확보 과정이나 교전 전 자원 차이를 기록할 수 있습니다. 집계 수치 하나로 잘못된 플레이나 실력을 판정할 수 없어, 현재 복기 화면은 수동 입력의 요약과 질문만 제공합니다.'
        result['sources'] = [{'title': '복기 데이터와 검증 계획', 'url': REPO + 'docs/06_companion_plan.md'}]
        result['caveats'].append('연습 과제는 검증할 가설입니다. 승률 향상 효과가 입증된 처방은 아닙니다.')
    else:
        result.update(status='insufficient_data', answer='현재 등록된 근거로는 이 질문에 답하기 어렵습니다. 패치 변화, 선택한 챔피언의 과거 집계, 행동 유형, 경기 복기 질문을 물어보세요. 최신 룬·빌드나 개인 전적은 아직 연결되지 않았습니다.')
    return result
