"""고정한 공개 GGUF 후보만 다운로드하고 원격 SHA256과 대조한다."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.quantized_candidates import CANDIDATES, weights


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=CANDIDATES, required=True)
    args = parser.parse_args()
    spec = CANDIDATES[args.model]
    folder = weights(args.model).parent
    if 'sha256' not in spec:
        raise ValueError('기존 모델은 setup_quantized_model.py로 준비합니다.')
    path = Path(hf_hub_download(spec['repo'], spec['file'], revision=spec['revision'], local_dir=folder, token=False))
    hf_hub_download(spec['repo'], 'README.md', revision=spec['revision'], local_dir=folder, token=False)
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != spec['sha256']:
        raise RuntimeError('고정한 원격 SHA256과 다릅니다.')
    manifest = {
        **spec,
        'bytes': path.stat().st_size,
        'runtime': json.loads((ROOT / '.local/llama-cpp/manifest.json').read_text(encoding='utf-8')),
    }
    (folder / 'download-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'model': args.model, 'bytes': manifest['bytes'], 'verified': True}), flush=True)


if __name__ == '__main__':
    main()
