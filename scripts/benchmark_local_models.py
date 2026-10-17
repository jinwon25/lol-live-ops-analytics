"""동일 합성 경기로 CPU 모델을 비교한다. 개인 자료·외부 추론 API를 사용하지 않는다."""

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service.local_coach import CoachInput, messages, validate_choice


def cases():
    base = dict(gpm=400, dpm=700, vision_per_minute=0.8, kill_participation=0.542, cs_per_minute=6, damage_share=0.35)
    rows = [
        {'id': role.lower(), 'input': {'role': role, 'metrics': dict(base)}}
        for role in ['TOP', 'JUNGLE', 'MID', 'BOT', 'SUPPORT']
    ]
    rows += [
        {'id': 'zero-team-kills', 'input': {'role': 'BOT', 'metrics': {**base, 'kill_participation': None}}},
        {
            'id': 'missing-cs-share',
            'input': {'role': 'SUPPORT', 'metrics': {**base, 'cs_per_minute': None, 'damage_share': None}},
        },
        {'id': 'zero-vision', 'input': {'role': 'JUNGLE', 'metrics': {**base, 'vision_per_minute': 0}}},
    ]
    return rows


NARRATIVE_CASES = [
    {
        'id': 'normal',
        'fact': '경기 시간 30분, 획득 골드 12000, 분당 골드 400.',
        'required': ['400'],
        'allowed': ['30', '12000', '400'],
    },
    {
        'id': 'missing',
        'fact': '팀 킬 0, 내 킬 0, 내 도움 0. 킬 관여율은 계산 불가.',
        'required': ['계산'],
        'allowed': ['0'],
    },
    {
        'id': 'comparison',
        'fact': '같은 조건 이전 경기 평균 분당 골드 375, 이번 경기 400, 차이 +25. 경기 당시 티어는 알 수 없음.',
        'required': ['375', '400'],
        'allowed': ['375', '400', '25'],
    },
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--model', required=True, choices=['Qwen3-0.6B', 'Qwen3-1.7B', 'Qwen3.5-0.8B', 'LFM2.5-1.2B-Instruct']
    )
    parser.add_argument('--adapter', action='store_true')
    args = parser.parse_args()
    if args.adapter and args.model != 'Qwen3-0.6B':
        parser.error('기존 LoRA 실험 어댑터는 Qwen3-0.6B 전용입니다.')
    if args.adapter:
        sys.path.insert(0, str(ROOT / '.local/llm-deps'))
    import psutil
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoModelForImageTextToText, AutoTokenizer

    torch.set_num_threads(4)
    torch.manual_seed(17)
    folder = ROOT / '.local/models' / args.model
    manifest = json.loads((folder / 'download-manifest.json').read_text())
    tokenizer = AutoTokenizer.from_pretrained(folder, local_files_only=True, trust_remote_code=False)
    cls = AutoModelForImageTextToText if args.model == 'Qwen3.5-0.8B' else AutoModelForCausalLM
    loaded = time.monotonic()
    model = cls.from_pretrained(folder, local_files_only=True, trust_remote_code=False, dtype=torch.float32)
    if args.adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, ROOT / '.local/models/lol-coach-smoke', local_files_only=True)
    model.eval()
    load_seconds = time.monotonic() - loaded

    def generate(msgs, limit):
        text = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        inputs = tokenizer(text, return_tensors='pt')
        started = time.monotonic()
        with torch.inference_mode():
            output = model.generate(
                **inputs, max_new_tokens=limit, max_time=30, do_sample=False, pad_token_id=tokenizer.eos_token_id
            )
        ids = output[0][inputs.input_ids.shape[-1] :]
        raw = tokenizer.decode(ids, skip_special_tokens=True).strip()
        return raw, round(time.monotonic() - started, 3), len(ids)

    results = []
    for row in cases():
        raw, elapsed, tokens = generate(messages(row['input']), 64)
        valid = False
        strict_json = False
        focus = None
        try:
            strict_json = isinstance(json.loads(raw), dict)
        except ValueError:
            pass
        try:
            choice = validate_choice(raw, CoachInput.model_validate(row['input']))
            valid = True
            focus = choice['focus_id']
        except (ValueError, TypeError, KeyError):
            pass
        results.append(
            {
                'case': row['id'],
                'task': 'routing',
                'strict_json': strict_json,
                'valid': valid,
                'focus': focus,
                'seconds': elapsed,
                'tokens': tokens,
                'raw': raw,
            }
        )
        print(json.dumps({k: v for k, v in results[-1].items() if k != 'raw'}), flush=True)
    for row in NARRATIVE_CASES:
        prompt = [
            {
                'role': 'system',
                'content': '주어진 경기 사실만 한국어 두 문장으로 요약하세요. 원인·실력·승률·장면을 추정하지 마세요. 표본이나 모르는 정보는 덧붙이지 마세요.',
            },
            {'role': 'user', 'content': row['fact']},
        ]
        raw, elapsed, tokens = generate(prompt, 96)
        hangul = len(re.findall('[가-힣]', raw))
        foreign = len(re.findall('[A-Za-z\u3040-\u30ff\u4e00-\u9fff]', raw))
        numbers = set(re.findall(r'\d+(?:\.\d+)?', raw.replace(',', '')))
        required = all(v in raw for v in row['required'])
        no_extra = numbers.issubset(set(row['allowed']))
        results.append(
            {
                'case': row['id'],
                'task': 'korean_summary',
                'required_facts_present': required,
                'no_extra_numbers': no_extra,
                'hangul_ratio': round(hangul / max(1, hangul + foreign), 3),
                'seconds': elapsed,
                'tokens': tokens,
                'raw': raw,
                'automatic_checks_are_not_semantic_review': True,
            }
        )
        print(json.dumps({k: v for k, v in results[-1].items() if k != 'raw'}, ensure_ascii=False), flush=True)
    memory = psutil.Process().memory_info()
    result = {
        'model': manifest['repo'],
        'revision': manifest['revision'],
        'adapter': args.adapter,
        'transformers': transformers.__version__,
        'torch': torch.__version__,
        'dtype': 'float32',
        'device': 'cpu',
        'threads': 4,
        'decoding': 'greedy, non-thinking',
        'per_call_time_cap': 30,
        'load_seconds': round(load_seconds, 2),
        'peak_working_set_gib': round(getattr(memory, 'peak_wset', memory.rss) / 1024**3, 3),
        'routing_valid': sum(x['valid'] for x in results if x['task'] == 'routing'),
        'routing_total': 8,
        'median_seconds': round(statistics.median(x['seconds'] for x in results), 3),
        'results': results,
        'coaching_effect_validated': False,
    }
    out = ROOT / 'outputs/model-benchmark'
    out.mkdir(parents=True, exist_ok=True)
    (out / (args.model + ('-lora' if args.adapter else '') + '.json')).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(json.dumps({k: v for k, v in result.items() if k != 'results'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
