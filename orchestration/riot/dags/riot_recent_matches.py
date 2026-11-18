"""KR 솔로랭크 최근 경기 표본을 수집하고 게시할 집계를 검증한다."""

import json
import os
import subprocess
from pathlib import Path

import pendulum
from airflow.sdk import dag, task


@dag(schedule=None, start_date=pendulum.datetime(2026, 11, 1, tz='UTC'), catchup=False)
def riot_recent_matches():
    @task
    def sync_catalogue():
        subprocess.run([os.environ['SERVICE_PYTHON'], 'scripts/sync_catalogue.py'], check=True)

    @task
    def collect_matches():
        Path('service/data/current_meta.json').unlink(missing_ok=True)
        subprocess.run(
            [os.environ['SERVICE_PYTHON'], 'scripts/collect_riot_meta.py', '--tiers', 'SILVER',
             '--seeds', '8', '--per-seed', '5', '--matches', '40', '--max-calls', '55'],
            check=True,
        )

    @task
    def validate_report():
        report = json.loads(Path('service/data/current_meta.json').read_text())
        if report['collection']['stopped'] or not report['games'] or report['participants'] != 10 * report['games']:
            raise ValueError('수집 중단 또는 경기·참여자 수 불일치')

    sync_catalogue() >> collect_matches() >> validate_report()


riot_recent_matches_dag = riot_recent_matches()
