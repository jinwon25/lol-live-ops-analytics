"""EUN·KR의 마지막 체크포인트까지 저장된 참여 행을 분석용 gzip pickle로 내보낸다."""

import argparse
import json
import os
import sqlite3
import sys
import time
from contextlib import ExitStack, closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.backfill_matches import COLUMNS, REGIONS, atomic_json
from scripts.backfill_store import inspect_sample

CATEGORICAL = ['region', 'queue', 'platform_id', 'game_mode', 'game_version', 'champion_name', 'position', 'solo_tier']


def read_checkpoint_rows(directory: Path, region: str) -> pd.DataFrame:
    state = json.loads((directory / 'state.json').read_bytes())
    counts = {int(bucket): n for bucket, n in state['counts'].items() if n}
    games = sum(counts.values())
    # 수집기가 CSV 뒤에 추가하는 동안에도 이미 체크포인트에 반영된 행까지만 읽는다.
    frame = pd.read_csv(
        directory / 'participants.csv',
        nrows=games * 10,
        dtype=dict.fromkeys(['puuid_hash', 'start_utc', *CATEGORICAL], str),
        float_precision='round_trip',
        keep_default_na=False,
        low_memory=False,
    )
    if list(frame.columns) != COLUMNS or len(frame) != games * 10 or not frame['region'].eq(region).all():
        raise ValueError(f'{region} CSV 스키마·지역·참여 행 수가 체크포인트와 일치하지 않습니다.')
    participants = frame['participant_id']
    if not participants.isin(range(1, 11)).all() or frame.duplicated(['game_id', 'participant_id']).any():
        raise ValueError(f'{region} 참가자 번호가 잘못됐거나 중복됐습니다.')
    groups = frame.groupby(['game_id', 'sample_bucket'], sort=False).size()
    ids = groups.index.get_level_values('game_id')
    prefix = REGIONS[region][2]
    if (
        not groups.eq(10).all()
        or not ids.is_unique
        or groups.groupby(level='sample_bucket').size().to_dict() != counts
        or not {f'{prefix}_{game_id}' for game_id in ids}.issubset(state['seen'])
    ):
        raise ValueError(f'{region} 경기 키 또는 구간별 경기 수가 체크포인트와 일치하지 않습니다.')
    return frame


def export_snapshot(source: Path, output: Path) -> pd.DataFrame:
    output.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(output.with_suffix('.writer.sqlite'), timeout=60)) as lock:
        lock.execute('BEGIN IMMEDIATE')
        frame = pd.concat([read_checkpoint_rows(source / region, region) for region in REGIONS], ignore_index=True)
        for column in CATEGORICAL:
            frame[column] = frame[column].astype('category')
        with TemporaryDirectory(dir=output.parent) as tmp:
            candidate = Path(tmp) / 'participants.pkl.gz'
            frame.to_pickle(candidate, protocol=5, compression={'method': 'gzip', 'compresslevel': 6, 'mtime': 0})
            pd.testing.assert_frame_equal(frame, pd.read_pickle(candidate), check_exact=True)
            os.replace(candidate, output)
    return frame


def final_export(source: Path, output: Path, weeks: int, per_week: int) -> int | None:
    """목표 도달 후 두 수집기가 쓰기를 마친 시점의 파일만 검증·게시한다."""

    def ready(counts: dict) -> bool:
        return all(counts.get(str(i), 0) >= per_week for i in range(weeks))

    for region in REGIONS:
        checkpoint = source / region / 'state.json'
        if not checkpoint.is_file() or not ready(json.loads(checkpoint.read_bytes())['counts']):
            return None

    with ExitStack() as stack:
        for region in REGIONS:
            conn = stack.enter_context(closing(sqlite3.connect(source / region / 'writer.sqlite', timeout=0)))
            try:
                conn.execute('BEGIN IMMEDIATE')
            except sqlite3.OperationalError as error:
                if error.sqlite_errorcode == sqlite3.SQLITE_BUSY:
                    return None
                raise
        for region, (_, _, prefix) in REGIONS.items():
            folder = source / region
            state = json.loads((folder / 'state.json').read_bytes())
            if not ready(state['counts']):
                return None
            games, counts, _ = inspect_sample(folder, region, prefix, state)
            if dict(counts) != state['counts'] or not games.issubset(state['seen']):
                raise ValueError(f'{region} 체크포인트와 저장된 경기 키 또는 구간별 경기 수가 다릅니다.')
        return len(export_snapshot(source, output))


def watch_completion(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(output.parent / 'backfill_export_watcher.sqlite', timeout=0)) as lock:
        try:
            lock.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError as error:
            if error.sqlite_errorcode == sqlite3.SQLITE_BUSY:
                print('최종 PKL 생성을 대기하는 프로세스가 이미 실행 중입니다.')
                return
            raise
        status_path = output.parent / 'backfill_export_status.json'

        def report(status: str, **details) -> None:
            atomic_json(status_path, dict(status=status, pid=os.getpid(), utc=datetime.now(UTC).isoformat(), **details))

        report('waiting')
        while True:
            try:
                rows = final_export(source, output, weeks=97, per_week=500)
                if rows is not None:
                    report('complete', rows=rows, bytes=output.stat().st_size)
                    print(f'최종 PKL 저장 완료 · {rows:,}행 · {output.name}', flush=True)
                    return
            except (OSError, ValueError, EOFError, AssertionError, sqlite3.OperationalError) as error:
                report('retry', error=type(error).__name__)
                print(f'최종 PKL 검증·저장 재시도 대기 · {type(error).__name__}: {error}', flush=True)
            time.sleep(300)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--when-complete', action='store_true', help='두 지역의 97주 × 500경기 수집 완료 후 최종본 저장'
    )
    args = parser.parse_args()
    output = ROOT / '.local/exports/backfill_participants.pkl.gz'
    source = ROOT / '.local/backfill'
    if args.when_complete:
        watch_completion(source, output)
    else:
        data = export_snapshot(source, output)
        print(f'{len(data):,}행 · {len(data.columns)}열 · {output.stat().st_size:,}바이트 · {output.name}')
