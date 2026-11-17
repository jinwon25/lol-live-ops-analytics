"""Linux CI에서 실제 Airflow 파서·Task SDK로 합성 배치를 검증한다."""

import runpy
from pathlib import Path

from airflow.dag_processing.dagbag import DagBag

ROOT = Path(__file__).resolve().parents[2]
bag = DagBag(dag_folder=str(ROOT / 'orchestration/airflow/dags'))
assert not bag.import_errors, bag.import_errors
assert 'lol_historic_pipeline' in bag.dags
# Airflow 3.4의 DagBag은 scheduler용 BaggedDAG를 돌려준다. 실행 검사는 원본 Task SDK DAG로 한다.
dag = runpy.run_path(str(ROOT / 'orchestration/airflow/dags/lol_historic_pipeline.py'))['lol_historic_pipeline']
assert set(dag.task_ids) == {'extract_snapshot', 'normalize_and_build_marts', 'quality_gate', 'publish_batch'}
assert dag.get_task('publish_batch').upstream_task_ids == {'quality_gate'}
assert dag.max_active_runs == 1
result = dag.test(run_conf={'batch_date': '2026-11-17', 'demo': True})
assert result.state == 'success', result.state
print('Airflow 파싱·합성 배치 실행 성공')
