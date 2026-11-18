"""지역별 수집 파일을 읽어 저장된 경기와 패치별 표본 수를 대조한다."""

import csv
import gzip
import json
from collections import Counter, defaultdict
from itertools import groupby
from pathlib import Path


def inspect_sample(directory: Path, region: str, prefix: str, state: dict) -> tuple[set[str], Counter, dict]:
    csv_path = directory / 'participants.csv'
    raw_path = directory / 'raw.jsonl.gz'
    if csv_path.exists() != raw_path.exists():
        raise ValueError('참여자 CSV와 압축 원본 중 한 파일이 누락되었습니다.')

    saved: set[str] = set()
    counts: Counter[str] = Counter()
    patches: dict[str, list[int]] = defaultdict(list)
    if csv_path.exists():
        with csv_path.open(newline='', encoding='utf-8') as stream:
            for game_id, group in groupby(csv.DictReader(stream), key=lambda row: row['game_id']):
                rows = list(group)
                first = rows[0]
                match_id = f'{prefix}_{game_id}'
                fields = ('region', 'platform_id', 'sample_bucket', 'duration', 'game_version')
                if (
                    match_id in saved
                    or not game_id.isdecimal()
                    or len(rows) != 10
                    or {int(row['participant_id']) for row in rows} != set(range(1, 11))
                    or any(row[field] != first[field] for row in rows for field in fields)
                    or first['region'] != region
                    or first['platform_id'].upper() != prefix
                ):
                    raise ValueError('CSV의 경기 키, 참가자 10명 또는 경기 단위 값이 일치하지 않습니다.')
                saved.add(match_id)
                counts[first['sample_bucket']] += 1
                patch = '.'.join(first['game_version'].split('.')[:2])
                patches[patch].append(int(first['duration']))

        remaining = saved.copy()
        with gzip.open(raw_path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                match = json.loads(line)
                match_id = match['metadata']['matchId']
                if match_id != f"{prefix}_{match['info']['gameId']}" or match_id not in remaining:
                    raise ValueError('압축 원본에 중복 경기 또는 CSV와 다른 경기 키가 있습니다.')
                remaining.remove(match_id)
        if remaining:
            raise ValueError('CSV의 일부 경기가 압축 원본에 없습니다.')

    if any(n > counts[b] for b, n in state['counts'].items()):
        raise ValueError('체크포인트에 기록된 경기 수보다 저장 파일의 구간별 경기 수가 적습니다.')
    return saved, counts, dict(patches)
