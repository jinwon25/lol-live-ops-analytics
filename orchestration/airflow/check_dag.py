"""Linux CI에서 실제 Airflow 파서·Task SDK로 합성 배치를 검증한다."""

from pathlib import Path

from airflow.models.dagbag import DagBag

ROOT = Path(__file__).resolve().parents[2]
bag = DagBag(dag_folder=str(ROOT / 'orchestration/airflow/dags'), include_examples=False)
assert not bag.import_errors, bag.import_errors
dag = bag.dags['lol_historic_pipeline']
assert set(dag.task_ids) == {'extract_snapshot', 'normalize_and_build_marts', 'quality_gate', 'publish_batch'}
assert dag.get_task('publish_batch').upstream_task_ids == {'quality_gate'}
assert dag.max_active_runs == 1
result = dag.test(run_conf={'batch_date': '2026-11-17', 'demo': True})
assert result.state == 'success', result.state
print('Airflow 파싱·합성 배치 실행 성공')
