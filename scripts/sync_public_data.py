"""CC BY 4.0 공개 자료의 해시 확인·시점 결합·비식별 집계. 실행: python scripts/sync_public_data.py"""

import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service.public_data import PHASES, build_flow

RECORD = '8303397'
EXPECTED = {
    20: 'a4758f4f04fbb1237059d9f74e1f56b1',
    40: 'd8981ac98e6d8fd6582e73f965a04f34',
    60: '27fd49aaf6c05bfbafc3856991d4c8c6',
    80: '773db73d8b3fc2c6b1ca7272e62f26bd',
    100: '26488b7f639a44fa476eab97cd8928d7',
}
RAW = ROOT / 'data/raw/public/zenodo-8303397'


def fetch(phase):
    filename = f'full_data_{phase}.csv'
    path = RAW / filename
    url = f'https://zenodo.org/api/records/{RECORD}/files/{filename}/content'
    if not path.exists() or hashlib.md5(path.read_bytes()).hexdigest() != EXPECTED[phase]:
        with urlopen(url, timeout=45) as response:
            data = response.read(12000001)
        if len(data) > 12000000 or hashlib.md5(data).hexdigest() != EXPECTED[phase]:
            raise ValueError(f'{filename}: 제공자 해시 또는 크기 제한 불일치')
        path.write_bytes(data)
    data = path.read_bytes()
    return (
        phase,
        path,
        {
            'path': filename,
            'url': url,
            'bytes': len(data),
            'md5': EXPECTED[phase],
            'sha256': hashlib.sha256(data).hexdigest(),
        },
    )


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    with urlopen(f'https://zenodo.org/api/records/{RECORD}', timeout=30) as response:
        metadata = json.load(response)
    if metadata['metadata']['license']['id'] != 'cc-by-4.0':
        raise ValueError('제공자 라이선스가 변경되어 자동 반영을 중단했습니다.')
    provided = {f['key']: f['checksum'] for f in metadata['files']}
    if any(provided.get(f'full_data_{p}.csv') != 'md5:' + EXPECTED[p] for p in PHASES):
        raise ValueError('고정 자료 버전과 제공자 메타데이터가 다릅니다.')
    with ThreadPoolExecutor(max_workers=3) as pool:
        files = list(pool.map(fetch, PHASES))
    result = build_flow({phase: path for phase, path, _ in files})
    result['source'] = {
        'id': 'zenodo-ranked-flow-2023',
        'title': metadata['metadata']['title'],
        'authors': [a['name'] for a in metadata['metadata']['creators']],
        'url': f'https://zenodo.org/records/{RECORD}',
        'doi': '10.5281/zenodo.8303397',
        'license': 'CC BY 4.0',
        'license_url': 'https://creativecommons.org/licenses/by/4.0/',
        'period': '2023-01-12~2023-05-18',
        'cohort': '제공자 설명: IRON~DIAMOND · CSV에 개별 티어 없음',
        'checked_at': datetime.now(UTC).isoformat(),
        'files': [manifest for _, _, manifest in files],
        'transformation': '5개 시점 파일을 matchID로 결합, 중복·결측·불일치 제거, 경기별 식별자를 제외한 집계만 배포',
    }
    target = ROOT / 'service/data/public_flow.json'
    # 모든 다운로드·검증·집계가 성공한 뒤 기존 결과를 갱신한다.
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(target)
    print(
        json.dumps(
            {'included_matches': result['audit']['included_matches'], 'audit': result['audit'], 'output': str(target)},
            ensure_ascii=False,
        )
    )


if __name__ == '__main__':
    main()
