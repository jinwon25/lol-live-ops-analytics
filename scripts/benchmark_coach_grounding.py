"""기본 비교 뒤 누락·극값·한국어 지시를 별도 검증한다. 코칭 정답률이 아니다."""
import argparse,hashlib,json,sys,time,statistics
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.quantized_candidates import CANDIDATES,weights
from service.local_coach import CoachInput,messages,validate_choice
from service.quantized_coach import local_server,generate

KOREAN_SYSTEM='주어진 경기 지표에서 돌아볼 초점 하나를 선택하세요. 실력이나 승패 원인을 판정하지 마세요. JSON만 반환하세요. 키는 focus_id와 evidence_keys 두 개입니다. focus_id는 vision, resource, fight_setup, matchup 중 하나입니다. evidence_keys는 null이 아닌 지표 이름 한두 개입니다. 없는 관측을 만들지 마세요.'

def probes():
 base=dict(gpm=400,dpm=700,vision_per_minute=.8,kill_participation=.54,cs_per_minute=6,damage_share=.35)
 variants=[('all-optional-missing',dict(kill_participation=None,cs_per_minute=None,damage_share=None)),('all-zero',dict(gpm=0,dpm=0,vision_per_minute=0,kill_participation=0,cs_per_minute=0,damage_share=0)),('kp-missing-high-vision',dict(kill_participation=None,vision_per_minute=3.2,cs_per_minute=1)),('resource-extreme',dict(gpm=1200,dpm=200,cs_per_minute=15)),('low-resource-high-damage',dict(gpm=180,dpm=2000,cs_per_minute=2)),('one-optional-valid',dict(kill_participation=None,cs_per_minute=None,damage_share=.85))]
 return [{'id':f'{lang}-{name}','input':{'role':'SUPPORT' if i%2 else 'BOT','metrics':{**base,**change}},'language':lang} for lang in ('en','ko') for i,(name,change) in enumerate(variants)]

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--model',choices=CANDIDATES,required=True);args=parser.parse_args()
 stop=['<|eot_id|>'] if args.model=='Kanana1.5-2.1B-Q4_K_M' else None
 results=[]
 with local_server(weights(args.model)) as (client,process,load):
  for probe in probes():
   payload=CoachInput.model_validate(probe['input']);prompt=messages(payload)
   if probe['language']=='ko':prompt[0]['content']=KOREAN_SYSTEM
   started=time.monotonic();error=None
   try:raw,tokens=generate(client,prompt,64,stop=stop)
   except (httpx.HTTPError,ValueError):raw,tokens,error='',0,'generation_failed_or_timed_out'
   elapsed=round(time.monotonic()-started,3);valid=False;choice=None
   try:choice=validate_choice(raw,payload);valid=True
   except (ValueError,TypeError,KeyError):pass
   results.append({'case':probe['id'],'input':probe['input'],'prompt_sha256':hashlib.sha256(json.dumps(prompt,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),'raw':raw,'valid':valid,'focus':choice['focus_id'] if choice else None,'evidence_keys':choice['evidence_keys'] if choice else None,'seconds':elapsed,'tokens':tokens,'error':error})
   print(json.dumps({k:v for k,v in results[-1].items() if k not in ('input','raw','prompt_sha256')},ensure_ascii=False),flush=True)
 result={'model':args.model,'runtime':'llama.cpp b11398','context':2048,'threads':4,'decoding':'greedy, non-thinking','max_tokens':64,'stop':stop,'total':len(results),'valid':sum(r['valid'] for r in results),'median_seconds':round(statistics.median(r['seconds'] for r in results),3),'scope':'schema and present evidence keys only; no expert focus labels or coaching quality claim','results':results}
 folder=ROOT/'outputs/model-grounding';folder.mkdir(parents=True,exist_ok=True);(folder/(args.model+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in result.items() if k!='results'},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
