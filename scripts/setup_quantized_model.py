"""공식 Qwen GGUF와 llama.cpp Windows CPU 릴리스를 고정해 로컬에 준비한다."""

import hashlib
import json
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from huggingface_hub import hf_hub_download

ROOT = Path(__file__).resolve().parents[1]


def main():
    runtime = ROOT / '.local/llama-cpp'
    runtime.mkdir(parents=True, exist_ok=True)
    manifest_path = runtime / 'manifest.json'
    if manifest_path.is_file():
        release = json.loads(manifest_path.read_text(encoding='utf-8'))
    else:
        r = json.load(
            urlopen(
                Request(
                    'https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/b11398',
                    headers={'User-Agent': 'local-model-review'},
                ),
                timeout=30,
            )
        )
        match = next((a for a in r['assets'] if a['name'].endswith('bin-win-cpu-x64.zip') and a.get('digest')), None)
        if match is None:
            raise RuntimeError('공식 CPU 릴리스와 SHA256을 찾지 못했습니다.')
        a = match
        if a['digest'] != 'sha256:a5b932cb28b2f17da93bf7111c7cbd1324cffa3a6f474aa10b616908868037a2':
            raise RuntimeError('검증한 CPU 실행 파일과 다른 릴리스입니다.')
        release = {'tag': r['tag_name'], 'url': a['browser_download_url'], 'digest': a['digest']}
        archive = runtime / 'release.zip'
        digest = hashlib.sha256()
        with urlopen(release['url'], timeout=60) as response, archive.open('wb') as target:
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                target.write(chunk)
                digest.update(chunk)
        if 'sha256:' + digest.hexdigest() != release['digest']:
            raise RuntimeError('공식 릴리스 해시가 다릅니다.')
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                if not (runtime / item.filename).resolve().is_relative_to(runtime.resolve()):
                    raise RuntimeError('허용하지 않는 압축 경로입니다.')
            z.extractall(runtime)
        manifest_path.write_text(json.dumps(release, indent=2), encoding='utf-8')
    repo = 'Qwen/Qwen3-4B-GGUF'
    revision = 'bc640142c66e1fdd12af0bd68f40445458f3869b'
    folder = ROOT / '.local/models/Qwen3-4B-Q4_K_M'
    path = Path(hf_hub_download(repo, 'Qwen3-4B-Q4_K_M.gguf', revision=revision, local_dir=folder, token=False))
    hf_hub_download(repo, 'README.md', revision=revision, local_dir=folder, token=False)
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    model = {
        'repo': repo,
        'revision': revision,
        'license': 'apache-2.0',
        'file': path.name,
        'bytes': path.stat().st_size,
        'sha256': digest.hexdigest(),
        'runtime': release,
    }
    (folder / 'download-manifest.json').write_text(json.dumps(model, indent=2), encoding='utf-8')
    print(json.dumps(model), flush=True)


if __name__ == '__main__':
    main()
