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
    def collect_matches(logical_date=None):
        # 같은 6시간 구간의 재실행은 같은 조회 기간 [end-7일, end)를 쓴다.
        moment = (logical_date or pendulum.now('UTC')).in_timezone('UTC')
        end = moment.start_of('day').add(hours=moment.hour // 6 * 6)
        Path('service/data/current_meta.json').unlink(missing_ok=True)
        subprocess.run(
            [
                os.environ['SERVICE_PYTHON'],
                'scripts/collect_riot_meta.py',
                '--tiers',
                'SILVER',
                '--seeds',
                '8',
                '--per-seed',
                '5',
                # 체크포인트에 누적된 7일 경기 수 상한. 실행당 비용은 --max-calls로 제한한다.
                '--matches',
                '1000',
                '--max-calls',
                '55',
                '--end',
                end.isoformat(),
            ],
            check=True,
        )

    @task
    def validate_report():
        report = json.loads(Path('service/data/current_meta.json').read_text())
        if report['collection']['stopped'] or not report['games'] or report['participants'] != 10 * report['games']:
            raise ValueError('수집 중단 또는 경기·참여자 수 불일치')

    sync_catalogue() >> collect_matches() >> validate_report()


riot_recent_matches_dag = riot_recent_matches()
