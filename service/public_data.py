"""공개 표본 검증·집계. 개인 백분위나 실시간 승률 모델에는 사용하지 않는다."""

import csv
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PHASES = (20, 40, 60, 80, 100)
BUCKETS = ('large_deficit', 'deficit', 'balanced', 'lead', 'large_lead')
LABELS = ('2,000G 초과 열세', '500G 초과~2,000G 열세', '±500G 이내', '500G 초과~2,000G 우세', '2,000G 초과 우세')


def gold_bucket(gap):
    return BUCKETS[0 if gap < -2000 else 1 if gap < -500 else 2 if gap <= 500 else 3 if gap <= 2000 else 4]


def read_phase(path, phase):
    records: dict[str, tuple[float, float, float, float, bool]] = {}
    counts: Counter[str] = Counter()
    conflicts: set[str] = set()
    invalid_ids: set[str] = set()
    reasons: Counter[str] = Counter()
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        required = {'matchID', 'fullTimeMS', 'timePercent', 'blueTotalGold', 'redTotalGold', 'blueWin', 'redWin'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('공개 CSV의 필수 열이 없습니다.')
        for row in reader:
            counts['input_rows'] += 1
            match = row.get('matchID', '').strip()
            try:
                duration_ms = float(row['fullTimeMS'])
                minute = float(row['timePercent'])
                blue, red = float(row['blueTotalGold']), float(row['redTotalGold'])
                if not match or len(match) > 100 or not all(math.isfinite(v) for v in (duration_ms, minute, blue, red)):
                    raise ValueError('field_format')
                if not 300000 <= duration_ms <= 5400000:
                    raise ValueError('duration_outside_5_90_minutes')
                if (
                    not 0 <= minute <= math.ceil(duration_ms / 60000) + 1
                    or not 0 <= blue <= 1000000
                    or not 0 <= red <= 1000000
                ):
                    raise ValueError('value_out_of_range')
                # 파일명이 비율을 표시한다. timePercent 열은 실제로 분 단위 프레임 시각이다.
                if abs(minute - duration_ms / 60000 * phase / 100) > 1.1:
                    raise ValueError('frame_time_mismatch')
                wins = (row['blueWin'], row['redWin'])
                if wins not in {('True', 'False'), ('False', 'True')}:
                    raise ValueError('invalid_outcome')
                item = (duration_ms, minute, blue, red, wins[0] == 'True')
            except (ValueError, TypeError, KeyError) as error:
                counts['invalid_rows'] += 1
                reason = str(error)
                reasons[
                    reason
                    if reason
                    in {
                        'field_format',
                        'duration_outside_5_90_minutes',
                        'value_out_of_range',
                        'frame_time_mismatch',
                        'invalid_outcome',
                    }
                    else 'field_format'
                ] += 1
                if match:
                    invalid_ids.add(match)
                continue
            if match in records:
                counts['duplicate_rows'] += 1
                if records[match] != item:
                    conflicts.add(match)
            else:
                records[match] = item
    for match in conflicts | invalid_ids:
        records.pop(match, None)
    counts['conflicting_matches'] = len(conflicts)
    counts['invalid_matches'] = len(invalid_ids)
    counts['valid_unique_matches'] = len(records)
    result: dict[str, Any] = {
        key: counts[key]
        for key in [
            'input_rows',
            'invalid_rows',
            'duplicate_rows',
            'conflicting_matches',
            'invalid_matches',
            'valid_unique_matches',
        ]
    }
    result['invalid_reasons'] = dict(reasons)
    return records, result


def build_flow(files):
    frames, audits = {}, {}
    for phase in PHASES:
        frames[phase], audits[str(phase)] = read_phase(files[phase], phase)
    common = set.intersection(*(set(frames[p]) for p in PHASES))
    matched, inconsistent = [], 0
    for match in sorted(common):
        items = [frames[p][match] for p in PHASES]
        if len({(r[0], r[4]) for r in items}) != 1 or any(
            items[i][j] > items[i + 1][j] for i in range(4) for j in (1, 2, 3)
        ):
            inconsistent += 1
        else:
            matched.append(match)
    if not matched:
        raise ValueError('검증을 통과한 공통 경기가 없습니다.')
    phase_results = []
    # 최종 상태는 승패와 직접 연결되므로 결과 분석에서 제외한다.
    for phase in PHASES[:-1]:
        values = [frames[phase][match] for match in matched]
        bins = []
        for bucket, label in zip(BUCKETS, LABELS, strict=True):
            selected = [r for r in values if gold_bucket(r[2] - r[3]) == bucket]
            wins = sum(r[4] for r in selected)
            bins.append(
                {
                    'id': bucket,
                    'label': label,
                    'n': len(selected),
                    'blue_win_pct': round(100 * wins / len(selected), 1) if len(selected) >= 30 else None,
                }
            )
        phase_results.append(
            {
                'phase': phase,
                'n': len(values),
                'median_elapsed_minutes': round(median(r[1] for r in values), 1),
                'median_abs_gold_gap': round(median(abs(r[2] - r[3]) for r in values)),
                'buckets': bins,
            }
        )
    return {
        'schema_version': 1,
        'unit': '경기·팀',
        'is_current_match_data': False,
        'personal_comparison_eligible': False,
        'median_duration_minutes': round(median(frames[100][match][0] / 60000 for match in matched), 1),
        'audit': {
            'phases': audits,
            'common_matches': len(common),
            'inconsistent_matches': inconsistent,
            'included_matches': len(matched),
        },
        'phases': phase_results,
        'limitations': [
            '2023년 표본이며 현재 KR·동티어·개인 챔피언 기준이 아닙니다.',
            '공개 CSV에 지역·패치·참여자별 티어·챔피언·포지션이 없습니다.',
            '종료 경기 길이의 비율로 시점을 정합니다. 고정 10/15분 자료나 실시간 예측 입력이 아닙니다.',
            '골드 우위와 최종 승패의 관측 관계이며 골드 획득 행동의 인과효과가 아닙니다.',
            '반복 플레이어를 식별할 수 없어 독립 표본으로 검증하거나 개인 실력으로 해석하지 않습니다.',
        ],
    }


def public_flow():
    return json.loads((ROOT / 'service/data/public_flow.json').read_text(encoding='utf-8'))


def source_catalogue():
    return json.loads((ROOT / 'service/data/data_sources.json').read_text(encoding='utf-8'))
