"""동일 합성 과제로 공식 4B Q4_K_M CPU 실행 구성을 비교한다."""
import json
import argparse
import hashlib
import httpx
from pathlib import Path
import re
import statistics
import sys
import time
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.benchmark_local_models import cases,NARRATIVE_CASES
from service.local_coach import CoachInput,messages,validate_choice
from service.quantized_coach import local_server,generate
from scripts.quantized_candidates import CANDIDATES,weights


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--model',choices=CANDIDATES,default='Qwen3-4B-Q4_K_M');parser.add_argument('--audit',action='store_true',help='이전 측정을 보존하고 별도 결과 기록');parser.add_argument('--kanana-eos',action='store_true',help='공식 tokenizer의 종료 토큰을 런타임에 지정');args=parser.parse_args()
    if args.kanana_eos and args.model!='Kanana1.5-2.1B-Q4_K_M':parser.error('종료 토큰 보정은 검토한 Kanana 변환 구성 전용입니다.')
    stop=['<|eot_id|>'] if args.kanana_eos else None
    manifest=json.loads((weights(args.model).parent/'download-manifest.json').read_text(encoding='utf-8'))
    results=[]
    def call(prompt,limit):
        started=time.monotonic()
        try:
            raw,tokens=generate(client,prompt,limit,stop=stop); error=None
        except (httpx.HTTPError,ValueError):
            raw,tokens,error='',0,'generation_failed_or_timed_out'
        return raw,tokens,round(time.monotonic()-started,3),error,hashlib.sha256(json.dumps(prompt,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    with local_server(weights(args.model)) as (client,process,load_seconds):
        for row in cases():
            raw,tokens,elapsed,error,prompt_hash=call(messages(row['input']),64)
            valid=strict=False; focus=None
            try:
                choice=validate_choice(raw,CoachInput.model_validate(row['input'])); valid=True; focus=choice['focus_id']
                json.loads(raw); strict=True
            except (ValueError,TypeError,KeyError):
                pass
            results.append({'case':row['id'],'task':'routing','strict_json':strict,'valid':valid,'focus':focus,'seconds':elapsed,'tokens':tokens,'raw':raw,'error':error,'prompt_sha256':prompt_hash})
            print(json.dumps({k:v for k,v in results[-1].items() if k!='raw'}),flush=True)
        for row in NARRATIVE_CASES:
            prompt=[{'role':'system','content':'주어진 경기 사실만 한국어 두 문장으로 요약하세요. 원인·실력·승률·장면을 추정하지 마세요. 분모나 모르는 정보를 빠뜨리지 마세요.'},{'role':'user','content':row['fact']}]
            raw,tokens,elapsed,error,prompt_hash=call(prompt,96)
            hangul=len(re.findall('[가-힣]',raw)); foreign=len(re.findall('[A-Za-z\u3040-\u30ff\u4e00-\u9fff]',raw))
            numbers=set(re.findall(r'\d+(?:\.\d+)?',raw.replace(',','')))
            results.append({'case':row['id'],'task':'korean_summary','required_facts_present':all(v in raw for v in row['required']),
                'no_extra_numbers':numbers.issubset(set(row['allowed'])),'hangul_ratio':round(hangul/max(1,hangul+foreign),3),
                'seconds':elapsed,'tokens':tokens,'raw':raw,'error':error,'prompt_sha256':prompt_hash,'automatic_checks_are_not_semantic_review':True})
            print(json.dumps({k:v for k,v in results[-1].items() if k!='raw'}),flush=True)
        memory=psutil.Process(process.pid).memory_info()
        peak=round(getattr(memory,'peak_wset',memory.rss)/1024**3,3)
    result={'model':manifest['repo'],'revision':manifest['revision'],'adapter':False,'runtime':'llama.cpp '+manifest['runtime']['tag'],
        'dtype':CANDIDATES[args.model]['quantization']+' weights; runtime-managed activations/KV','device':'cpu','threads':4,'context':2048,'decoding':'greedy, non-thinking',
        'per_call_time_cap':'HTTP 30 seconds, unlike Transformers max_time token-boundary checks','load_seconds':round(load_seconds,2),
        'peak_working_set_gib':peak,'memory_scope':'llama-server process; excludes small Python HTTP client',
        'routing_valid':sum(r['valid'] for r in results if r['task']=='routing'),'routing_total':8,'stop':stop,
        'median_seconds':round(statistics.median(r['seconds'] for r in results),3),'results':results,'coaching_effect_validated':False}
    (ROOT/f'outputs/model-benchmark/{args.model}{"-eos" if args.kanana_eos else ""}{"-audit" if args.audit else ""}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='results'}),flush=True)


if __name__=='__main__':
    main()
