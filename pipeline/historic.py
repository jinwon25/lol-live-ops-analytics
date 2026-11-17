"""CSV·Excel·공식 도감 스냅샷을 검증된 Parquet/CSV 분석 마트로 적재한다."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'historic-v1'
FILES = (
    'participants.parquet',
    'quarantine.parquet',
    'champion_patch.parquet',
    'champion_patch.csv',
    'patch_health.csv',
)
REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS batch_inputs (
    batch_date TEXT PRIMARY KEY, manifest_path TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stage_runs (
    attempt_id TEXT PRIMARY KEY, batch_date TEXT NOT NULL, stage TEXT NOT NULL,
    status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, error_type TEXT
);
CREATE TABLE IF NOT EXISTS publications (
    batch_date TEXT PRIMARY KEY, dataset_id TEXT NOT NULL,
    run_dir TEXT NOT NULL, published_at TEXT NOT NULL
);
"""


class QualityError(ValueError):
    """공개 조건을 만족하지 못한 배치."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def _atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _code_sha() -> str:
    files = [
        Path(__file__),
        ROOT / 'src/load.py',
        ROOT / 'sql/pipeline/champion_patch.sql',
        ROOT / 'sql/pipeline/patch_health.sql',
    ]
    return hashlib.sha256(''.join(_sha(p) for p in files).encode()).hexdigest()


@contextmanager
def _registry(work: Path):
    work.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(work / 'registry.sqlite', timeout=30)) as con:
        con.row_factory = sqlite3.Row
        con.executescript(REGISTRY_SCHEMA)
        with con:
            yield con


@contextmanager
def _stage(work: Path, batch_date: str, stage: str):
    attempt = uuid.uuid4().hex
    with _registry(work) as con:
        con.execute(
            'INSERT INTO stage_runs VALUES (?, ?, ?, ?, ?, NULL, NULL)', (attempt, batch_date, stage, 'running', _now())
        )
    try:
        yield
    except Exception as error:
        with _registry(work) as con:
            con.execute(
                'UPDATE stage_runs SET status=?, finished_at=?, error_type=? WHERE attempt_id=?',
                ('failed', _now(), type(error).__name__, attempt),
            )
        raise
    else:
        with _registry(work) as con:
            con.execute(
                'UPDATE stage_runs SET status=?, finished_at=? WHERE attempt_id=?', ('success', _now(), attempt)
            )


def _snapshot(source: Path, work: Path, filename: str) -> dict[str, str | int]:
    """복사한 바이트 자체를 해시한다. 수집 도중 원본이 바뀌어도 영수증과 내용이 일치한다."""
    temporary = work / f'.extract-{uuid.uuid4().hex}.tmp'
    digest = hashlib.sha256()
    try:
        with source.open('rb') as reader, temporary.open('wb') as writer:
            for chunk in iter(lambda: reader.read(1024 * 1024), b''):
                digest.update(chunk)
                writer.write(chunk)
        relative = Path('bronze') / digest.hexdigest() / filename
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(target)
        return {'path': relative.as_posix(), 'sha256': digest.hexdigest(), 'bytes': target.stat().st_size}
    finally:
        temporary.unlink(missing_ok=True)


def extract(
    source_dir: str | Path,
    catalogue_path: str | Path,
    work_dir: str | Path,
    batch_date: str,
    *,
    refresh: bool = False,
) -> str:
    """최초 입력을 배치 날짜에 고정한다. 명시적 refresh만 정정 입력을 허용한다."""
    if date.fromisoformat(batch_date).isoformat() != batch_date:
        raise ValueError('batch_date는 YYYY-MM-DD 형식이어야 합니다.')
    work, source = Path(work_dir).resolve(), Path(source_dir)
    with _stage(work, batch_date, 'extract'):
        with _registry(work) as con:
            saved = con.execute('SELECT manifest_path FROM batch_inputs WHERE batch_date=?', (batch_date,)).fetchone()
        if saved and not refresh:
            return str(work / saved['manifest_path'])
        sources = {
            'p153': _snapshot(source / '2025.csv', work, '2025.csv'),
            'p151': _snapshot(source / '2024.xlsx', work, '2024.xlsx'),
            'catalogue': _snapshot(Path(catalogue_path), work, 'catalogue.json'),
        }
        # 변환 코드·SQL 변경도 데이터셋 식별자에 반영한다.
        identity = {'batch_date': batch_date, 'version': VERSION, 'code_sha256': _code_sha(), 'sources': sources}
        dataset_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        relative = Path('snapshots') / f'{dataset_id}.json'
        _atomic_json(work / relative, {**identity, 'dataset_id': dataset_id})
        with _registry(work) as con:
            if refresh:
                con.execute(
                    'INSERT INTO batch_inputs VALUES (?, ?) ON CONFLICT(batch_date) '
                    'DO UPDATE SET manifest_path=excluded.manifest_path',
                    (batch_date, relative.as_posix()),
                )
            else:
                con.execute('INSERT OR IGNORE INTO batch_inputs VALUES (?, ?)', (batch_date, relative.as_posix()))
            selected = con.execute(
                'SELECT manifest_path FROM batch_inputs WHERE batch_date=?', (batch_date,)
            ).fetchone()
        return str(work / selected['manifest_path'])


def transform(manifest_path: str | Path) -> str:
    """기존 정규화·지표 공식을 재사용하고 완전한 경기만 새 마트에 반영한다."""
    import duckdb
    import numpy as np
    import pandas as pd

    from src.load import COMMON_COLS, derive_metrics, load_p151, load_p153

    manifest_path = Path(manifest_path).resolve()
    work, manifest = manifest_path.parent.parent, _json(manifest_path)
    with _stage(work, manifest['batch_date'], 'transform'):
        if manifest['code_sha256'] != _code_sha():
            raise QualityError('변환 코드가 바뀌었습니다. 정정 배치는 refresh-snapshot으로 명시하세요.')
        sources = manifest['sources']
        for entry in sources.values():
            if _sha(work / entry['path']) != entry['sha256']:
                raise QualityError('원본 스냅샷의 체크섬이 다릅니다.')
        try:
            frames = [
                load_p151(work / sources['p151']['path'], strict=True),
                load_p153(work / sources['p153']['path'], strict=True),
            ]
        except (ValueError, KeyError, TypeError) as error:
            raise QualityError('입력 스키마 또는 승패 형식을 확인하세요.') from error
        if not frames[0]['team_side'].isin([100, 200]).all() or not frames[1]['team_side'].isin([0, 1]).all():
            raise QualityError('원본별 팀 구분 값이 허용 범위를 벗어났습니다.')
        base_columns = [c for c in COMMON_COLS if c not in {'kda', 'gpm', 'dpm_champ', 'kill_participation'}]
        full = pd.concat([f[base_columns] for f in frames], ignore_index=True)
        if full.empty or full.duplicated(['patch', 'game_id', 'participant_id']).any():
            raise QualityError('정규화 행이 없거나 참여자 기본키가 중복됩니다.')
        required = [c for c in base_columns if c != 'solo_tier']
        numeric = [
            'game_id',
            'participant_id',
            'duration_sec',
            'win',
            'kills',
            'deaths',
            'assists',
            'gold_earned',
            'dmg_to_champ',
            'dmg_taken',
            'vision_score',
        ]
        if full[required].isna().any().any() or not full['win'].isin([0, 1]).all():
            raise QualityError('필수 값 누락 또는 승패 형식 오류입니다.')
        values = full[numeric].to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values < 0).any() or not (values == np.floor(values)).all():
            raise QualityError('수치 필드에 음수·비유한 값·정수가 아닌 값이 있습니다.')
        if not full['participant_id'].between(1, 10).all():
            raise QualityError('참여자 번호가 1부터 10 사이가 아닙니다.')
        grouped = full.groupby(['patch', 'game_id'])
        stats = grouped.agg(
            players=('participant_id', 'size'),
            winners=('win', 'sum'),
            durations=('duration_sec', 'nunique'),
            duration=('duration_sec', 'first'),
        )
        reasons = {
            'incomplete_participants': stats.players != 10,
            'invalid_winner_count': stats.winners != 5,
            'inconsistent_duration': stats.durations != 1,
            'duration_outside_5_90_minutes': ~stats.duration.between(300, 5400),
        }
        # 각 팀에 역할 5종이 정확히 한 번씩 있어야 한다.
        role_counts = full.groupby(['patch', 'game_id', 'team_side', 'role']).size()
        duplicate_roles = role_counts[role_counts != 1].index.droplevel([2, 3])
        team_stats = full.groupby(['patch', 'game_id', 'team_side']).agg(
            size=('win', 'size'), outcomes=('win', 'nunique')
        )
        bad_teams = team_stats[(team_stats['size'] != 5) | (team_stats.outcomes != 1)].index.droplevel(2)
        team_counts = team_stats.groupby(level=[0, 1]).size()
        reasons['duplicate_team_role'] = pd.Series(stats.index.isin(duplicate_roles), index=stats.index)
        reasons['invalid_team_structure'] = pd.Series(stats.index.isin(bad_teams), index=stats.index) | (
            team_counts != 2
        )
        bad = pd.DataFrame(reasons).any(axis=1)
        rejected = full.set_index(['patch', 'game_id']).index.isin(stats[bad].index)
        quarantine = full[rejected].copy()
        reason_by_game = {
            key: ','.join(name for name, mask in reasons.items() if mask.loc[key]) for key in stats[bad].index
        }
        quarantine['quarantine_reason'] = [
            reason_by_game[(patch, game)] for patch, game in zip(quarantine.patch, quarantine.game_id, strict=True)
        ]
        clean = derive_metrics(full[~rejected].copy())[COMMON_COLS]
        if clean.empty or set(clean['patch']) != {'15.1', '15.3'}:
            raise QualityError('두 패치 모두에 검증 가능한 완전한 경기가 필요합니다.')
        cat = _json(work / sources['catalogue']['path'])
        names = {c['id']: c['name'] for c in cat['champions']}
        canonical = {name.casefold(): name for name in names}
        clean['champion_name'] = clean['champion_name'].map(lambda name: canonical.get(name.casefold(), name))
        clean['champion_ko'] = clean['champion_name'].map(names)
        run = work / 'runs' / manifest['batch_date'] / uuid.uuid4().hex
        run.mkdir(parents=True)
        with duckdb.connect(':memory:') as db:
            db.register('normalized', clean)
            db.register('quarantined', quarantine)
            db.execute(
                'COPY (SELECT * FROM normalized ORDER BY patch, game_id, participant_id) TO ? (FORMAT PARQUET)',
                [str(run / 'participants.parquet')],
            )
            db.execute('COPY quarantined TO ? (FORMAT PARQUET)', [str(run / 'quarantine.parquet')])
            db.execute('CREATE VIEW participants AS SELECT * FROM normalized')
            for name in ('champion_patch', 'patch_health'):
                sql = (ROOT / f'sql/pipeline/{name}.sql').read_text(encoding='utf-8')
                db.execute(f'CREATE TEMP TABLE {name} AS {sql}')
                db.execute(f'COPY {name} TO ? (HEADER, FORMAT CSV)', [str(run / f'{name}.csv')])
            db.execute('COPY champion_patch TO ? (FORMAT PARQUET)', [str(run / 'champion_patch.parquet')])
        audit = {
            'selected_rows_by_patch': {str(k): len(f) for k, f in zip(('15.1', '15.3'), frames, strict=True)},
            'selected_rows': len(full),
            'accepted_rows': len(clean),
            'accepted_games': int((~bad).sum()),
            'quarantined_rows': len(quarantine),
            'quarantined_games': int(bad.sum()),
            'quarantined_games_by_reason': {reason: int(mask.sum()) for reason, mask in reasons.items()},
            'unknown_champion_names': int(clean['champion_ko'].isna().sum()),
            'catalogue_version': cat['version'],
            'minimum_picks_for_rates': 30,
            'unit': '경기×참여자',
            'region': 'EUN',
            'is_current_match_data': False,
            'partition_semantics': '입력 스냅샷의 수집 배치 날짜이며 경기 발생 날짜가 아님',
        }
        _atomic_json(
            run / 'manifest.json', {**manifest, 'audit': audit, 'artifacts': {name: _sha(run / name) for name in FILES}}
        )
        return str(run)


def _verify(run: Path) -> dict[str, Any]:
    import duckdb

    manifest = _json(run / 'manifest.json')
    for name in FILES:
        if manifest['artifacts'].get(name) != _sha(run / name):
            raise QualityError('분석 산출물의 체크섬이 다릅니다.')
    with duckdb.connect(':memory:') as db:
        db.read_parquet(str(run / 'participants.parquet')).create_view('participants')
        db.read_parquet(str(run / 'champion_patch.parquet')).create_view('mart')
        rows, games = db.execute('SELECT count(*), count(DISTINCT (patch, game_id)) FROM participants').fetchone()
        duplicate_keys = db.execute(
            'SELECT count(*) - count(DISTINCT (patch, game_id, participant_id)) FROM participants'
        ).fetchone()[0]
        invalid = db.execute('''SELECT count(*) FROM participants WHERE
            role NOT IN ('TOP','JUNGLE','MID','BOT','SUPPORT') OR win NOT IN (0,1)
            OR duration_sec NOT BETWEEN 300 AND 5400
            OR NOT isfinite(gpm) OR NOT isfinite(dpm_champ) OR gpm < 0 OR dpm_champ < 0
            OR kill_participation < 0 OR kill_participation > 1.001''').fetchone()[0]
        # 각 패치·코호트·역할의 픽 비중 합은 100%, 승수는 표본 수 이하.
        bad_denominators = db.execute('''SELECT count(*) FROM (
            SELECT patch, cohort, role FROM mart GROUP BY ALL
            HAVING abs(sum(pick_rate_pct) - 100) > 0.00001 OR sum(games) != max(role_participants)
        )''').fetchone()[0]
        bad_rates = db.execute('''SELECT count(*) FROM mart WHERE wins > games OR wins < 0
            OR (games < 30 AND (win_rate_pct IS NOT NULL OR wilson_low_pct IS NOT NULL OR wilson_high_pct IS NOT NULL))
            OR (games >= 30 AND (win_rate_pct IS NULL OR wilson_low_pct IS NULL OR wilson_high_pct IS NULL))''').fetchone()[
            0
        ]
        null_kp = db.execute('SELECT count(*) FROM participants WHERE kill_participation IS NULL').fetchone()[0]
        missing_mart_rows = db.execute('''WITH expected AS (
                SELECT patch, role, count(*) AS n FROM participants GROUP BY ALL
            ), actual AS (
                SELECT patch, role, sum(games) AS n FROM mart WHERE cohort='all' GROUP BY ALL
            ) SELECT count(*) FROM expected FULL OUTER JOIN actual USING (patch,role)
              WHERE expected.n IS DISTINCT FROM actual.n''').fetchone()[0]
    audit = manifest['audit']
    checks = {
        'nonempty': rows > 0,
        'counts_match': rows == audit['accepted_rows'] and games == audit['accepted_games'],
        'complete_games': rows == games * 10,
        'unique_keys': duplicate_keys == 0,
        'metric_ranges': invalid == 0,
        'mart_denominators': bad_denominators == 0,
        'mart_covers_participants': missing_mart_rows == 0,
        'small_sample_suppression': bad_rates == 0,
        'row_reconciliation': audit['selected_rows'] == rows + audit['quarantined_rows'],
    }
    if not all(checks.values()):
        raise QualityError('품질 검사 실패: ' + ', '.join(k for k, v in checks.items() if not v))
    return {
        'passed': True,
        'checks': checks,
        'null_kill_participation': null_kp,
        'audit': audit,
        'dataset_id': manifest['dataset_id'],
    }


def validate(run_dir: str | Path) -> str:
    run = Path(run_dir).resolve()
    manifest = _json(run / 'manifest.json')
    with _stage(run.parents[2], manifest['batch_date'], 'validate'):
        report = _verify(run)
        _atomic_json(run / 'quality.json', report)
    return str(run)


def publish(run_dir: str | Path) -> dict[str, Any]:
    """검증 파일만 레지스트리에 원자적으로 게시한다. 이전 날짜 재처리는 최신본을 내리지 않는다."""
    run = Path(run_dir).resolve()
    manifest, work = _json(run / 'manifest.json'), run.parents[2]
    with _stage(work, manifest['batch_date'], 'publish'):
        quality = _json(run / 'quality.json')
        if not quality.get('passed') or quality['dataset_id'] != manifest['dataset_id']:
            raise QualityError('검증 완료 기록이 필요합니다.')
        _verify(run)  # 검증 이후 파일이 바뀌었는지도 게시 직전에 확인한다.
        with _registry(work) as con:
            con.execute(
                'INSERT INTO publications VALUES (?, ?, ?, ?) ON CONFLICT(batch_date) DO UPDATE '
                'SET dataset_id=excluded.dataset_id, run_dir=excluded.run_dir, published_at=excluded.published_at',
                (manifest['batch_date'], manifest['dataset_id'], str(run.relative_to(work)), _now()),
            )
    return {'batch_date': manifest['batch_date'], 'dataset_id': manifest['dataset_id'], 'audit': manifest['audit']}


def status(work_dir: str | Path) -> dict[str, Any]:
    work = Path(work_dir).resolve()
    with _registry(work) as con:
        publications = [dict(r) for r in con.execute('SELECT * FROM publications ORDER BY batch_date DESC')]
        attempts = [dict(r) for r in con.execute('SELECT * FROM stage_runs ORDER BY started_at DESC LIMIT 20')]
    return {
        'latest': publications[0] if publications else None,
        'publications': publications,
        'recent_stages': attempts,
    }


def run_pipeline(
    source_dir: str | Path, catalogue_path: str | Path, work_dir: str | Path, batch_date: str, *, refresh: bool = False
) -> dict[str, Any]:
    return publish(validate(transform(extract(source_dir, catalogue_path, work_dir, batch_date, refresh=refresh))))
