"""과거 경기 배치를 실행하거나 게시·실패 이력을 조회한다."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.historic import run_pipeline, status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch-date', help='입력 스냅샷 배치 날짜 YYYY-MM-DD. 경기 날짜가 아닙니다.')
    parser.add_argument('--work-dir', type=Path, default=ROOT / '.local/pipeline')
    parser.add_argument('--source-dir', type=Path, default=ROOT / 'data/raw')
    parser.add_argument('--catalogue', type=Path, default=ROOT / 'service/data/catalogue.json')
    parser.add_argument('--demo', action='store_true', help='별도 demo 저장소에서 합성 데이터로 실행')
    parser.add_argument('--refresh-snapshot', action='store_true', help='해당 날짜의 입력·변환 버전을 명시적으로 갱신')
    parser.add_argument('--status', action='store_true', help='게시본과 최근 20개 단계 이력 조회')
    args = parser.parse_args()
    if args.demo:
        args.work_dir = args.work_dir / 'demo'
    if args.status:
        result = status(args.work_dir)
    else:
        if not args.batch_date:
            parser.error('--batch-date가 필요합니다.')
        if args.demo:
            from pipeline.demo import create_demo_inputs

            args.source_dir = create_demo_inputs(args.work_dir / 'inputs')
            args.catalogue = args.source_dir / 'catalogue.json'
        result = run_pipeline(
            args.source_dir, args.catalogue, args.work_dir, args.batch_date, refresh=args.refresh_snapshot
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
