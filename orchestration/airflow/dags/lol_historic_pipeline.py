"""Airflow 3 TaskFlow: 스냅샷 고정 → 변환 → 품질 검사 → 게시. 기본 입력은 합성 예제."""

from datetime import timedelta

import pendulum
from airflow.sdk import Param, dag, get_current_context, task


@dag(
    dag_id='lol_historic_pipeline',
    schedule=None,
    start_date=pendulum.datetime(2026, 11, 1, tz='UTC'),
    catchup=False,
    max_active_runs=1,
    default_args={'retries': 2, 'retry_delay': timedelta(seconds=30), 'execution_timeout': timedelta(minutes=15)},
    params={
        'batch_date': Param('2026-11-17', type='string', format='date', title='입력 스냅샷 배치 날짜'),
        'demo': Param(True, type='boolean', title='합성 데이터로 실행'),
    },
    tags=['lol', 'etl', 'data-quality'],
    doc_md='과거 EUN 경기 자료의 수동 배치입니다. 배치 날짜는 경기 발생 날짜가 아닙니다. '
    '재시도는 최초 입력 스냅샷을 사용하며, 품질 실패 시 게시본을 보존합니다.',
)
def historic_pipeline():
    @task()
    def extract_snapshot() -> str:
        import os
        from pathlib import Path

        from pipeline.historic import extract

        params = get_current_context()['params']
        work = Path(os.environ.get('LOL_PIPELINE_WORK_DIR', '/opt/airflow/pipeline'))
        if params['demo']:
            from pipeline.demo import create_demo_inputs

            work = work / 'demo'
            source = create_demo_inputs(work / 'inputs')
            catalogue = source / 'catalogue.json'
        else:
            source = Path(os.environ.get('LOL_PIPELINE_SOURCE_DIR', '/opt/inputs/raw'))
            catalogue = Path(os.environ.get('LOL_PIPELINE_CATALOGUE', '/opt/inputs/catalogue.json'))
        return extract(source, catalogue, work, params['batch_date'])

    @task()
    def normalize_and_build_marts(manifest_path: str) -> str:
        from pipeline.historic import transform

        return transform(manifest_path)

    @task()
    def quality_gate(run_dir: str) -> str:
        from pipeline.historic import validate

        return validate(run_dir)

    @task()
    def publish_batch(run_dir: str) -> dict:
        from pipeline.historic import publish

        return publish(run_dir)

    publish_batch(quality_gate(normalize_and_build_marts(extract_snapshot())))


lol_historic_pipeline = historic_pipeline()
