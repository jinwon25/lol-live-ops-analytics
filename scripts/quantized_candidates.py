"""검토한 CPU 비교 후보. 원본 작성자와 GGUF 변환 작성자를 구분한다."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = {
    'Kanana1.5-2.1B-Q4_K_M': dict(
        repo='DevQuasar/kakaocorp.kanana-1.5-2.1b-instruct-2505-GGUF',
        base='kakaocorp/kanana-1.5-2.1b-instruct-2505',
        revision='4d3b6203857d893ebfcaca6c51901e3ea1d00d00',
        file='kakaocorp.kanana-1.5-2.1b-instruct-2505.Q4_K_M.gguf',
        license='apache-2.0 (base); converter metadata absent',
        quantization='Q4_K_M',
        sha256='24d3db59d0af2c85c0afc0bbc99da1174b73ef6728bce2650bd91bec28ad1c81',
    ),
    'Granite4-H-1B-Q4_K_M': dict(
        repo='ibm-granite/granite-4.0-h-1b-GGUF',
        base='ibm-granite/granite-4.0-h-1b',
        revision='c2cb1972f511add21f3bae244990b8ff3a3ffb23',
        file='granite-4.0-h-1b-Q4_K_M.gguf',
        license='apache-2.0',
        quantization='Q4_K_M',
        sha256='da3d737121a96f3c9a316685212376257a7f167b74380855666dd488d6af3bcb',
    ),
    'Qwen3-4B-Q4_K_M': dict(
        repo='Qwen/Qwen3-4B-GGUF',
        base='Qwen/Qwen3-4B',
        revision='bc640142c66e1fdd12af0bd68f40445458f3869b',
        file='Qwen3-4B-Q4_K_M.gguf',
        license='apache-2.0',
        quantization='Q4_K_M',
    ),
    'Gemma4-E2B-QAT-Q4_0': dict(
        repo='google/gemma-4-E2B-it-qat-q4_0-gguf',
        base='google/gemma-4-E2B-it',
        revision='675cff42a74c774d6cb76f76d8eacb49b48c9b93',
        file='gemma-4-E2B_q4_0-it.gguf',
        license='apache-2.0',
        quantization='QAT Q4_0',
        sha256='fa401b55b07ee70a54c6dae3903c783a6e65064312529ea57175cb5f8dec6634',
    ),
    'Qwen3.5-4B-Q4_K_M': dict(
        repo='unsloth/Qwen3.5-4B-GGUF',
        base='Qwen/Qwen3.5-4B',
        revision='e87f176479d0855a907a41277aca2f8ee7a09523',
        file='Qwen3.5-4B-Q4_K_M.gguf',
        license='apache-2.0',
        quantization='Q4_K_M',
        sha256='00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4',
    ),
    'Qwen3-4B-2507-Q4_K_M': dict(
        repo='unsloth/Qwen3-4B-Instruct-2507-GGUF',
        base='Qwen/Qwen3-4B-Instruct-2507',
        revision='a06e946bb6b655725eafa393f4a9745d460374c9',
        file='Qwen3-4B-Instruct-2507-Q4_K_M.gguf',
        license='apache-2.0',
        quantization='Q4_K_M',
        sha256='3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597',
    ),
    'Phi4-mini-Q4_K_M': dict(
        repo='bartowski/microsoft_Phi-4-mini-instruct-GGUF',
        base='microsoft/Phi-4-mini-instruct',
        revision='7ff82c2aaa4dde30121698a973765f39be5288c0',
        file='microsoft_Phi-4-mini-instruct-Q4_K_M.gguf',
        license='mit (base); converter metadata absent',
        quantization='Q4_K_M',
        sha256='01999f17c39cc3074afae5e9c539bc82d45f2dd7faa3917c66cbef76fce8c0c2',
    ),
    'Ministral3-3B-Q4_K_M': dict(
        repo='bartowski/mistralai_Ministral-3-3B-Instruct-2512-GGUF',
        base='mistralai/Ministral-3-3B-Instruct-2512',
        revision='0a9035302dea19872c96076896304552890a73c2',
        file='mistralai_Ministral-3-3B-Instruct-2512-Q4_K_M.gguf',
        license='apache-2.0',
        quantization='Q4_K_M',
        sha256='fec9d28c7f8dab7c6857d54b56c8264cce57d6f6d9003bd4110f6457f071c65a',
    ),
}


def weights(model):
    return ROOT / '.local/models' / model / CANDIDATES[model]['file']
