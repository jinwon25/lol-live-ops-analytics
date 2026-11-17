"""분모·재실행·품질 실패·과거 재처리가 실제 산출물과 게시 상태에 미치는 영향 검증."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from pipeline.demo import create_demo_inputs
from pipeline.historic import QualityError, extract, publish, run_pipeline, status, transform, validate


@pytest.fixture
def inputs(tmp_path):
    raw = create_demo_inputs(tmp_path / 'raw', games_per_patch=3)
    return raw, raw / 'catalogue.json', tmp_path / 'work'


def _run(inputs, batch='2026-11-17', **kwargs):
    return run_pipeline(*inputs, batch, **kwargs)


def _latest(inputs) -> Path:
    return inputs[2] / status(inputs[2])['latest']['run_dir']


def _rows(path: Path):
    with duckdb.connect(':memory:') as db:
        return db.read_parquet(str(path)).fetchall()


def test_end_to_end_counts_denominators_and_small_samples(inputs):
    result = _run(inputs)
    assert result['audit']['accepted_games'] == 6
    assert result['audit']['accepted_rows'] == 60
    assert result['audit']['quarantined_rows'] == 0
    path = _latest(inputs)
    quality = json.loads((path / 'quality.json').read_text(encoding='utf-8'))
    assert all(quality['checks'].values())
    with duckdb.connect(':memory:') as db:
        mart = db.read_parquet(str(path / 'champion_patch.parquet')).df()
    assert set(mart.cohort) == {'all', 'common_tiers'}
    assert (mart.role_participants == 6).all()
    assert (mart.pick_rate_pct == 50).all()
    assert mart.win_rate_pct.isna().all()
    assert mart.wilson_low_pct.isna().all()
    assert mart.champion_ko.notna().all()


def test_rates_use_wilson_after_minimum_sample(tmp_path):
    raw = create_demo_inputs(tmp_path / 'raw', games_per_patch=32)
    args = raw, raw / 'catalogue.json', tmp_path / 'work'
    _run(args)
    with duckdb.connect(':memory:') as db:
        mart = db.read_parquet(str(_latest(args) / 'champion_patch.parquet')).df()
    assert (mart.win_rate_pct == 50).all()
    assert (mart.wilson_low_pct < 50).all() and (mart.wilson_high_pct > 50).all()


def test_retry_uses_pinned_inputs_and_does_not_duplicate_publication(inputs):
    first = _run(inputs)
    expected = _rows(_latest(inputs) / 'participants.parquet')
    # 입력이 사라져도 동일 배치의 재시도는 최초 스냅샷을 사용한다.
    (inputs[0] / '2025.csv').unlink()
    second = _run(inputs)
    assert first == second
    assert expected == _rows(_latest(inputs) / 'participants.parquet')
    assert len(status(inputs[2])['publications']) == 1


def test_incomplete_match_is_quarantined_whole_and_metrics_are_recomputed(inputs):
    csv = inputs[0] / '2025.csv'
    frame = pd.read_csv(csv)
    frame = frame[~((frame.game_id == 1) & (frame.participant_id == 1))]
    frame.to_csv(csv, index=False)
    result = _run(inputs)
    assert result['audit']['quarantined_games'] == 1
    assert result['audit']['quarantined_rows'] == 9
    assert result['audit']['selected_rows'] == 59
    assert result['audit']['accepted_rows'] == 50
    assert len(_rows(_latest(inputs) / 'quarantine.parquet')) == 9
    assert result['audit']['quarantined_games_by_reason']['incomplete_participants'] == 1


def test_catalogue_case_variants_are_joined_without_losing_rows(inputs):
    csv = inputs[0] / '2025.csv'
    frame = pd.read_csv(csv)
    frame['champion_name'] = frame['champion_name'].str.swapcase()
    frame.to_csv(csv, index=False)
    assert _run(inputs)['audit']['unknown_champion_names'] == 0


@pytest.mark.parametrize('corruption', ['duplicate', 'negative', 'null', 'invalid_win', 'fractional_win', 'infinite'])
def test_failed_refresh_preserves_previous_publication_and_records_failure(inputs, corruption):
    _run(inputs)
    before = status(inputs[2])['latest']
    csv = inputs[0] / '2025.csv'
    frame = pd.read_csv(csv)
    if corruption == 'duplicate':
        frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    elif corruption == 'negative':
        frame.loc[0, 'gold_earned'] = -1
    elif corruption == 'null':
        frame.loc[0, 'gold_earned'] = float('nan')
    elif corruption == 'invalid_win':
        frame.loc[0, 'win'] = 2
    elif corruption == 'fractional_win':
        frame['win'] = frame['win'].astype(float)
        frame.loc[0, 'win'] = 0.5
    else:
        frame.loc[0, 'gold_earned'] = float('inf')
    frame.to_csv(csv, index=False)
    with pytest.raises(QualityError):
        _run(inputs, refresh=True)
    after = status(inputs[2])
    assert after['latest'] == before
    assert any(r['stage'] == 'transform' and r['status'] == 'failed' for r in after['recent_stages'])


def test_old_partition_backfill_does_not_replace_latest(inputs):
    _run(inputs)
    before = status(inputs[2])['latest']
    _run(inputs, batch='2026-11-16')
    assert status(inputs[2])['latest'] == before
    assert len(status(inputs[2])['publications']) == 2


def test_artifact_tampering_between_validation_and_publish_is_rejected(inputs):
    _run(inputs)
    before = status(inputs[2])['latest']
    path = Path(validate(transform(extract(*inputs, '2026-11-18'))))
    with (path / 'champion_patch.csv').open('a', encoding='utf-8') as stream:
        stream.write('corruption\n')
    with pytest.raises(QualityError, match='체크섬'):
        publish(path)
    assert status(inputs[2])['latest'] == before


def test_snapshot_tampering_is_rejected(inputs):
    receipt = Path(extract(*inputs, '2026-11-17'))
    manifest = json.loads(receipt.read_text(encoding='utf-8'))
    (inputs[2] / manifest['sources']['p153']['path']).write_text('corrupt', encoding='utf-8')
    with pytest.raises(QualityError, match='체크섬'):
        transform(receipt)
    assert status(inputs[2])['latest'] is None


def test_publish_requires_validation(inputs):
    path = transform(extract(*inputs, '2026-11-17'))
    with pytest.raises(FileNotFoundError):
        publish(path)
    assert status(inputs[2])['latest'] is None


def test_failed_extract_is_audited_without_creating_publication(inputs):
    (inputs[0] / '2024.xlsx').unlink()
    with pytest.raises(FileNotFoundError):
        _run(inputs)
    history = status(inputs[2])
    assert history['latest'] is None
    assert history['recent_stages'][0]['status'] == 'failed'
    # 개인·원본 값이 실패 메시지로 저장되지 않는다.
    with sqlite3.connect(inputs[2] / 'registry.sqlite') as db:
        assert db.execute('SELECT error_type FROM stage_runs').fetchone()[0] == 'FileNotFoundError'
