"""공식 챔피언 초상·게임 아이콘과 고정 버전 Tabler 아이콘을 로컬에 보관한다."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'web' / 'images'
TABLER_VERSION = '3.46.0'


def fetch(url):
    with urlopen(Request(url, headers={'User-Agent': 'LoL-Insight-Notes-Assets/1.0'}), timeout=30) as response:
        return response.read()


def main():
    catalogue = json.loads((ROOT / 'service/data/catalogue.json').read_text(encoding='utf-8'))
    version = catalogue['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('정적 자료 버전을 확인하세요.')
    base = f'https://ddragon.leagueoflegends.com/cdn/{version}'
    jobs = []
    for champion in catalogue['champions']:
        champion_id = champion['id']
        if not re.fullmatch(r'[A-Za-z0-9]{1,40}', champion_id):
            raise ValueError('공식 챔피언 ID를 확인하세요.')
        jobs.append((f'champions/{champion_id}.png', f'{base}/img/champion/{champion_id}.png', 'Riot Games'))
    items = json.loads(fetch(f'{base}/data/ko_KR/item.json'))['data']
    for item_id in ['3340','1055','1054']:
        jobs.append((f'game/{item_id}.png',f'{base}/img/item/{items[item_id]["image"]["full"]}', 'Riot Games'))
    jobs.append(('game/SummonerFlash.png',f'{base}/img/spell/SummonerFlash.png','Riot Games'))
    for icon in ['notebook','layout-dashboard','users','swords','message-circle','search','arrow-right','chart-line','target','download','chevron-right','check','clock','book-2']:
        jobs.append((f'icons/{icon}.svg',f'https://raw.githubusercontent.com/tabler/tabler-icons/v{TABLER_VERSION}/icons/outline/{icon}.svg','Tabler Icons / MIT'))
    jobs.append(('icons/LICENSE',f'https://raw.githubusercontent.com/tabler/tabler-icons/v{TABLER_VERSION}/LICENSE','Tabler Icons / MIT'))

    def save(job):
        path, url, owner = job
        target = DEST / path
        data = fetch(url)
        if path.endswith('.png') and not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError(f'PNG 검증 실패: {path}')
        if path.endswith('.svg') and b'<svg' not in data:
            raise ValueError(f'SVG 검증 실패: {path}')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {'path':path,'source':url,'owner':owner,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}

    with ThreadPoolExecutor(max_workers=6) as executor:
        entries = list(executor.map(save, jobs))
    manifest = {'version':version,'tabler_version':TABLER_VERSION,'reference':'https://developer.riotgames.com/docs/lol#data-dragon','assets':entries}
    (DEST / 'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Assets: {len(entries)} / {sum(e["bytes"] for e in entries):,} bytes')
    print(json.dumps({item_id:items[item_id]['name'] for item_id in ['3340','1055','1054']},ensure_ascii=True))


if __name__ == '__main__':
    main()
