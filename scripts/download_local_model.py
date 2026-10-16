"""공식 후보 모델을 프로젝트 내부에 고정 revision으로 내려받는다."""
import hashlib
import argparse
import json
from pathlib import Path
from urllib.request import urlopen

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    models={'Qwen3-0.6B':'Qwen/Qwen3-0.6B','Qwen3-1.7B':'Qwen/Qwen3-1.7B','Qwen3.5-0.8B':'Qwen/Qwen3.5-0.8B','LFM2.5-1.2B-Instruct':'LiquidAI/LFM2.5-1.2B-Instruct'}
    parser.add_argument('--model',choices=list(models),default='Qwen3-0.6B')
    args=parser.parse_args(); repo=models[args.model]
    with urlopen('https://huggingface.co/api/models/'+repo, timeout=30) as response:
        metadata = json.load(response)
    target = ROOT / '.local/models'/args.model
    manifest_path=target/'download-manifest.json'
    revision = json.loads(manifest_path.read_text(encoding='utf-8'))['revision'] if manifest_path.is_file() else metadata['sha']
    snapshot_download(repo, revision=revision, local_dir=target, token=False,
                      allow_patterns=['*.json','*.jinja','*.safetensors','merges.txt','vocab.json','LICENSE','README.md'], max_workers=2)
    files = []
    for path in target.iterdir():
        if path.is_file() and path.name!='download-manifest.json':
            digest = hashlib.sha256()
            with path.open('rb') as handle:
                for part in iter(lambda:handle.read(1024*1024),b''):
                    digest.update(part)
            files.append({'file':path.name,'bytes':path.stat().st_size,'sha256':digest.hexdigest()})
    (target/'download-manifest.json').write_text(json.dumps({'repo':repo,'revision':revision,'license':metadata.get('cardData',{}).get('license'),'files':files},indent=2),encoding='utf-8')
    print(json.dumps({'repo':repo,'revision':revision,'files':len(files),'bytes':sum(x['bytes'] for x in files)}))


if __name__ == '__main__':
    main()
