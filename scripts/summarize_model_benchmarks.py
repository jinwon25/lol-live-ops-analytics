"""모든 원문 출력에 동일한 형식 검증을 적용한다. 원본 평가 JSON은 보존한다."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.benchmark_local_models import cases
from service.local_coach import CoachInput, validate_choice


def main():
    inputs={row['id']:CoachInput.model_validate(row['input']) for row in cases()}
    rows=[]
    audit_hashes=[]
    for path in sorted((ROOT/'outputs/model-benchmark').glob('*.json')):
        if path.name=='summary.json':
            continue
        data=json.loads(path.read_text(encoding='utf-8'))
        if path.name.endswith('-audit.json'):
            audit_hashes.append({row['case']:row.get('prompt_sha256') for row in data['results']})
        strict=normalized=0
        for row in data['results']:
            if row['task']!='routing':
                continue
            try:
                validate_choice(row['raw'],inputs[row['case']])
                normalized+=1
                json.loads(row['raw'])
                strict+=1
            except (ValueError,KeyError,TypeError):
                pass
        rows.append({'file':path.name,'model':data['model'],'adapter':data['adapter'],
                     'strict_valid':strict,'normalized_valid':normalized,'routing_total':data['routing_total'],
                     'load_seconds':data['load_seconds'],'median_seconds':data['median_seconds'],
                     'peak_working_set_gib':data['peak_working_set_gib'],
                     'narratives':[{'case':r['case'],'raw':r['raw']} for r in data['results'] if r['task']=='korean_summary']})
    result={'normalization':'Only an exact enclosing json Markdown fence may be removed. No prose or arbitrary extraction accepted.',
            'scope':'11 synthetic prompts per run; no statistically validated coaching quality or concurrency benchmark.',
            'audit_runs':len(audit_hashes),
            'audit_prompt_hashes_identical':bool(audit_hashes) and all(len(item)==11 and all(item.values()) and item==audit_hashes[0] for item in audit_hashes),
            'models':rows}
    (ROOT/'outputs/model-benchmark/summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
