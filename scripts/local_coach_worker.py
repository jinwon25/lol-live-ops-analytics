"""격리된 환경에서 검증한 로컬 모델을 한 번 실행한다. 입력·출력을 저장하지 않는다."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service.local_coach import MODEL_IDS, CoachInput, messages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True, choices=[model for model in MODEL_IDS if model != 'Qwen3-4B-Q4_K_M'])
    args = parser.parse_args()
    raw_input = sys.stdin.read(4097)
    if len(raw_input) > 4096:
        raise ValueError('input too long')
    payload = CoachInput.model_validate_json(raw_input)
    import torch
    from transformers import AutoModelForCausalLM, AutoModelForImageTextToText, AutoTokenizer

    torch.set_num_threads(4)
    torch.manual_seed(17)
    folder = ROOT / '.local/models' / args.model
    tokenizer = AutoTokenizer.from_pretrained(folder, local_files_only=True, trust_remote_code=False)
    cls = AutoModelForImageTextToText if args.model == 'Qwen3.5-0.8B' else AutoModelForCausalLM
    model = cls.from_pretrained(folder, local_files_only=True, trust_remote_code=False, dtype=torch.float32)
    model.eval()
    text = tokenizer.apply_chat_template(
        messages(payload), tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    inputs = tokenizer(text, return_tensors='pt')
    with torch.inference_mode():
        output = model.generate(
            **inputs, max_new_tokens=64, max_time=30, do_sample=False, pad_token_id=tokenizer.eos_token_id
        )
    raw = tokenizer.decode(output[0][inputs.input_ids.shape[-1] :], skip_special_tokens=True).strip()
    print(json.dumps({'raw': raw}, ensure_ascii=False))


if __name__ == '__main__':
    main()
