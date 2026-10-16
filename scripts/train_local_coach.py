"""합성 지표로 Qwen3 0.6B LoRA 연결을 검증한다. 코칭 품질 학습과 구분한다."""
import argparse
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'.local/llm-deps'))
from service.local_coach import MODEL, ADAPTER, SYSTEM, CoachInput, messages, validate_choice


def examples():
    rows=[]
    for group in range(10):
        for role in ['TOP','JUNGLE','MID','BOT','SUPPORT']:
            metrics=dict(gpm=round(200+group*31.7,1),dpm=round(210+group*53.4,1),vision_per_minute=round(.3+group*.13,2),kill_participation=None if group==0 else round(.15+group*.07,2),cs_per_minute=None if role=='SUPPORT' else round(3+group*.45,2),damage_share=round(.1+group*.02,2))
            # 구조 학습용 작성 규칙. 이상적 코칭 정답이나 실력 평가 라벨이 아니다.
            focus='vision' if role in {'JUNGLE','SUPPORT'} else 'resource'
            target={'focus_id':focus,'evidence_keys':['vision_per_minute'] if focus=='vision' else ['gpm']}
            rows.append({'group':group,'synthetic':True,'label_kind':'role_prior_fixture','input':{'role':role,'metrics':metrics},'target':target})
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--steps',type=int,default=10,choices=range(1,101))
    parser.add_argument('--evaluate-only',action='store_true')
    args=parser.parse_args()
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model, PeftModel
    torch.set_num_threads(4); torch.manual_seed(17); random.seed(17)
    tokenizer=AutoTokenizer.from_pretrained(MODEL,local_files_only=True,trust_remote_code=False)
    base=AutoModelForCausalLM.from_pretrained(MODEL,local_files_only=True,trust_remote_code=False,dtype=torch.float32)
    rows=examples(); train=[r for r in rows if r['group']<8]; test=[r for r in rows if r['group']>=8]
    out=ROOT/'.local/coach-experiment'; out.mkdir(parents=True,exist_ok=True)
    (out/'seed-data.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    started=time.monotonic(); losses=[]
    if args.evaluate_only:
        model=PeftModel.from_pretrained(base,ADAPTER,local_files_only=True)
    else:
        if (ADAPTER/'adapter_model.safetensors').exists():
            raise RuntimeError('기존 어댑터를 보존합니다. 평가만 하려면 --evaluate-only를 사용하세요.')
        model=get_peft_model(base,LoraConfig(r=8,lora_alpha=16,lora_dropout=.05,target_modules=['q_proj','v_proj'],task_type='CAUSAL_LM'))
        model.train(); model.config.use_cache=False
        optimizer=torch.optim.AdamW((p for p in model.parameters() if p.requires_grad),lr=2e-4)
        for step in range(args.steps):
            row=train[step%len(train)]
            prompt=tokenizer.apply_chat_template(messages(row['input']),tokenize=False,add_generation_prompt=True,enable_thinking=False)
            prefix=tokenizer(prompt,add_special_tokens=False)['input_ids']
            target=tokenizer(json.dumps(row['target'],separators=(',',':'))+tokenizer.eos_token,add_special_tokens=False)['input_ids']
            if len(prefix)+len(target)>384:
                raise RuntimeError('학습 예제가 허용 길이를 넘었습니다. 정답을 잘라서 학습하지 않습니다.')
            ids=torch.tensor([prefix+target]); labels=ids.clone(); labels[:,:len(prefix)]=-100
            loss=model(input_ids=ids,attention_mask=torch.ones_like(ids),labels=labels).loss
            loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),1); optimizer.step(); optimizer.zero_grad()
            losses.append(round(loss.item(),4)); print(json.dumps({'step':step+1,'loss':losses[-1],'seconds':round(time.monotonic()-started,1)}),flush=True)
        ADAPTER.mkdir(parents=True,exist_ok=True); model.save_pretrained(ADAPTER); tokenizer.save_pretrained(ADAPTER)
        model.config.use_cache=True
    model.eval(); checks=[]
    for row in test:
        text=tokenizer.apply_chat_template(messages(row['input']),tokenize=False,add_generation_prompt=True,enable_thinking=False)
        inputs=tokenizer(text,return_tensors='pt')
        with torch.inference_mode():
            output=model.generate(**inputs,max_new_tokens=64,max_time=30,do_sample=False,pad_token_id=tokenizer.eos_token_id)
        raw=tokenizer.decode(output[0][inputs.input_ids.shape[-1]:],skip_special_tokens=True).strip()
        valid=False; correct=False
        try:
            choice=validate_choice(raw,CoachInput.model_validate(row['input'])); valid=True; correct=choice['focus_id']==row['target']['focus_id']
        except (ValueError,TypeError,KeyError):
            pass
        checks.append({'group':row['group'],'role':row['input']['role'],'schema_valid':valid,'fixture_label_match':correct,'raw':raw})
        print(json.dumps({'eval_role':row['input']['role'],'schema_valid':valid,'fixture_label_match':correct}),flush=True)
    result={'model':'Qwen/Qwen3-0.6B','revision':json.loads((MODEL/'download-manifest.json').read_text())['revision'],'device':'cpu','threads':4,'steps':len(losses),'losses':losses,'train_examples':len(train),'test_examples':len(test),'split':'metric regime groups 0-7 train, 8-9 held out','schema_pass':sum(r['schema_valid'] for r in checks),'fixture_label_match':sum(r['fixture_label_match'] for r in checks),'elapsed_seconds':round(time.monotonic()-started,1),'coaching_quality_validated':False,'checks':checks}
    (out/'evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'checks','losses'}},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
