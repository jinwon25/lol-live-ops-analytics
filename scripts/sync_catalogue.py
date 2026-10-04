"""API 키 없이 공식 한국어 챔피언 정적 자료를 갱신한다. 경기 통계 수집과 별개다."""
from datetime import datetime, timezone
from hashlib import sha256
import argparse
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://ddragon.leagueoflegends.com'


def fetch(url):
    with urlopen(url, timeout=30) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', help='생략하면 공식 KR realm의 챔피언 버전')
    args = parser.parse_args()
    realm_url = BASE + '/realms/kr.json'
    version = args.version or fetch(realm_url)['n']['champion']
    if version not in fetch(BASE + '/api/versions.json'):
        raise SystemExit('공식 버전 목록에 없는 버전입니다.')
    url = f'{BASE}/cdn/{version}/data/ko_KR/champion.json'
    raw = fetch(url)
    result = {
        'version': version, 'locale': 'ko_KR', 'realm': 'KR',
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'source_url': url, 'realm_url': realm_url,
        'source_sha256': sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        'champions': [
            {k: champ[k] for k in ['id', 'key', 'name', 'tags', 'info', 'stats']}
            for champ in raw['data'].values()
        ],
    }
    path = ROOT / 'service/data/catalogue.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'공식 챔피언 정적 자료: {version}, {len(result["champions"])}개. 경기 통계 변경 없음.')


if __name__ == '__main__':
    main()
