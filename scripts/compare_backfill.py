"""검증된 EUN·KR 표본으로 같은 패치의 경기 시간과 챔피언·포지션별 승률을 비교한다."""

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter
from contextlib import ExitStack, closing
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.backfill_matches import REGIONS
from scripts.backfill_store import inspect_sample
from service.meta import MINIMUM, wilson


def compare(directory: Path) -> dict:
    region_totals = {}
    durations = {}
    picks, wins = {}, {}
    names = {}
    with ExitStack() as stack:
        for region in REGIONS:
            folder = directory / region
            lock = stack.enter_context(closing(sqlite3.connect(folder / 'writer.sqlite', timeout=0)))
            lock.execute('BEGIN IMMEDIATE')
        for region, (_, _, prefix) in REGIONS.items():
            folder = directory / region
            state = json.loads((folder / 'state.json').read_bytes())
            saved, counts, durations[region] = inspect_sample(folder, region, prefix, state)
            if counts != Counter(state['counts']) or not saved.issubset(state['seen']):
                raise ValueError(f'{region} 체크포인트와 저장 파일을 먼저 동기화하세요.')
            region_totals[region] = len(saved)
            picks[region], wins[region] = Counter(), Counter()
            with (folder / 'participants.csv').open(encoding='utf-8', newline='') as stream:
                for row in csv.DictReader(stream):
                    patch = '.'.join(row['game_version'].split('.')[:2])
                    key = (patch, row['position'], int(row['champion_id']))
                    if row['win'] not in ('True', 'False'):
                        raise ValueError('승패 값이 올바르지 않습니다.')
                    names[key] = row['champion_name']
                    picks[region][key] += 1
                    wins[region][key] += row['win'] == 'True'

    differences = [
        median(eun) - median(durations['KR'][patch])
        for patch, eun in durations['EUN'].items()
        if min(len(eun), len(durations['KR'].get(patch, []))) >= MINIMUM
    ]
    eligible = []
    for key in sorted(picks['EUN'] & picks['KR']):
        if min(picks[region][key] for region in REGIONS) < MINIMUM:
            continue
        patch, role, champion = key
        item = {'patch': patch, 'position': role, 'champion_id': champion, 'champion_name': names[key]}
        for region in REGIONS:
            n, w = picks[region][key], wins[region][key]
            item[region] = {'picks': n, 'wins': w, 'win_pct': round(100 * w / n, 1), 'wilson_95_pct': wilson(w, n)}
        eligible.append(item)
    return {
        'games': region_totals,
        'minimum_per_region': MINIMUM,
        'paired_patches': len(differences),
        'patches_with_longer_eun_median': sum(diff > 0 for diff in differences),
        'median_patch_difference_eun_minus_kr_seconds': median(differences) if differences else None,
        'paired_champion_positions': eligible,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / '.local/backfill')
    print(json.dumps(compare(parser.parse_args().data_dir), ensure_ascii=False, indent=2))
