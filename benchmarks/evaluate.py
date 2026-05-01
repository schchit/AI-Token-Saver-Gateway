import json, os, sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from gateway import transform_impl, TransformRequest

def load_cases():
    if os.path.exists('benchmarks/business_cases.jsonl'):
        with open('benchmarks/business_cases.jsonl', encoding='utf-8') as f:
            return [json.loads(x) for x in f if x.strip()]
    with open('benchmarks/benchmark_cases.json', encoding='utf-8') as f:
        return json.load(f)

cases=load_cases()
pass_n=0; fails=[]
for c in cases:
    out=transform_impl(TransformRequest(target=c['target'], message=c['message'], strategy='hybrid'), tenant='bench')
    text=' '.join(out['compressed']['action_items']+out['compressed']['facts']).lower()
    ok=c['expected_action'] in text
    pass_n += 1 if ok else 0
    if not ok: fails.append(c['id'])
ratio=pass_n/len(cases)
threshold=float(os.getenv('BENCHMARK_GATE','0.95'))
print(json.dumps({"total":len(cases),"decision_consistency":round(ratio,4),"threshold":threshold,"pass":ratio>=threshold,"failures":fails[:30]},ensure_ascii=False,indent=2))
if ratio < threshold: raise SystemExit(1)
