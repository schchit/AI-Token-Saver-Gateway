 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/gateway.py b/gateway.py
new file mode 100644
index 0000000000000000000000000000000000000000..254693bd861a660a34e9271d752aaee7ca3361d1
--- /dev/null
+++ b/gateway.py
@@ -0,0 +1,204 @@
+from __future__ import annotations
+import json, os, re, time, urllib.request
+from dataclasses import dataclass, asdict
+from typing import Any, Dict, List, Optional
+
+from fastapi import FastAPI, Header, HTTPException
+from pydantic import BaseModel
+
+try:
+    import redis  # type: ignore
+except Exception:
+    redis = None
+
+try:
+    import tiktoken  # type: ignore
+except Exception:
+    tiktoken = None
+
+API_VERSION = "v2.1"
+app = FastAPI(title="AI Token Saver Gateway", version=API_VERSION)
+
+class TransformRequest(BaseModel):
+    target: str = "general_decision"
+    message: str
+    strategy: str = "heuristic"
+    min_confidence: float = 0.65
+
+@dataclass
+class CompressedMessage:
+    intent: str
+    facts: List[str]
+    action_items: List[str]
+    blockers: List[str]
+    confidence: float
+    strategy: str
+    fallback_used: bool = False
+
+STOPWORDS = {"the","a","an","is","are","was","were","be","to","of","and","or","in","on","for","with"}
+
+def _sentences(text: str) -> List[str]:
+    return [x.strip() for x in re.split(r"(?<=[.!?。！？])\s+", text.strip()) if x.strip()]
+
+def _extract(text: str, keys: List[str]) -> List[str]:
+    out=[]
+    for s in _sentences(text):
+        if any(k in s.lower() for k in keys): out.append(s)
+    return out[:5]
+
+def _kw(text: str, k=6) -> List[str]:
+    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
+    freq={}
+    for w in words:
+        if w not in STOPWORDS: freq[w]=freq.get(w,0)+1
+    return [w for w,_ in sorted(freq.items(), key=lambda x:x[1], reverse=True)[:k]]
+
+def redact_pii(text: str) -> str:
+    text=re.sub(r"[\w.-]+@[\w.-]+", "[REDACTED_EMAIL]", text)
+    text=re.sub(r"\b\d{3}[-.]?\d{2}[-.]?\d{4}\b", "[REDACTED_SSN]", text)
+    return text
+
+class TokenCounter:
+    def __init__(self):
+        self.provider = os.getenv("TOKENIZER_PROVIDER", "openai")
+        model = os.getenv("TOKENIZER_MODEL", "gpt-4o-mini")
+        self.enc = None
+        if self.provider == "openai" and tiktoken is not None:
+            try: self.enc = tiktoken.encoding_for_model(model)
+            except Exception: self.enc = tiktoken.get_encoding("cl100k_base")
+    def count(self, text: str) -> int:
+        if self.enc is not None: return max(1, len(self.enc.encode(text)))
+        return max(1, (len(text)+3)//4)
+
+TOKEN_COUNTER = TokenCounter()
+
+class CircuitBreaker:
+    def __init__(self, fail_threshold=3, reset_seconds=30):
+        self.fail_threshold=fail_threshold; self.reset_seconds=reset_seconds; self.fail_count=0; self.open_until=0.0
+    def allow(self): return time.time() >= self.open_until
+    def record_success(self): self.fail_count=0
+    def record_failure(self):
+        self.fail_count += 1
+        if self.fail_count >= self.fail_threshold: self.open_until = time.time() + self.reset_seconds
+
+CB = CircuitBreaker()
+
+class Strategy:
+    name="base"
+    def compress(self, text: str, target: str) -> CompressedMessage: raise NotImplementedError
+
+class HeuristicStrategy(Strategy):
+    name="heuristic"
+    def compress(self, text: str, target: str) -> CompressedMessage:
+        s=_sentences(text)
+        facts=_extract(text,["fact","data","结果","发现"])
+        actions=_extract(text,["need","should","must","next","需要","下一步","deploy","pause"])
+        blockers=_extract(text,["risk","issue","error","fail","风险","问题"])
+        if not facts: facts=[f"keywords:{','.join(_kw(text))}"] if text.strip() else []
+        conf=min(0.99, round(0.45+0.45*((len(facts)+len(actions))/max(1,len(s))),2))
+        return CompressedMessage(s[0] if s else "", facts, actions, blockers, conf, self.name)
+
+class LLMSemanticStrategy(Strategy):
+    name="llm_semantic"
+    def _call_openai(self, text: str, target: str) -> CompressedMessage:
+        api_key=os.getenv("OPENAI_API_KEY","")
+        model=os.getenv("OPENAI_MODEL","gpt-4o-mini")
+        if not api_key: raise RuntimeError("missing OPENAI_API_KEY")
+        prompt=(
+            "You are a compression gateway. Return strict JSON with keys: intent,facts,action_items,blockers,confidence. "
+            f"Target:{target}. Message:{text}"
+        )
+        body={"model":model,"messages":[{"role":"user","content":prompt}],"temperature":0,"response_format":{"type":"json_object"}}
+        req=urllib.request.Request(
+            "https://api.openai.com/v1/chat/completions",
+            data=json.dumps(body).encode(),
+            headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},
+            method="POST",
+        )
+        with urllib.request.urlopen(req, timeout=20) as r:
+            out=json.loads(r.read().decode())
+        content=out["choices"][0]["message"]["content"]
+        parsed=json.loads(content)
+        return CompressedMessage(
+            intent=str(parsed.get("intent","")),
+            facts=list(parsed.get("facts",[]))[:6],
+            action_items=list(parsed.get("action_items",[]))[:6],
+            blockers=list(parsed.get("blockers",[]))[:6],
+            confidence=float(parsed.get("confidence",0.7)),
+            strategy=self.name,
+        )
+
+    def compress(self, text: str, target: str) -> CompressedMessage:
+        if not CB.allow():
+            h=HeuristicStrategy().compress(text,target); h.strategy="llm_semantic_fallback_open_circuit"; return h
+        try:
+            c=self._call_openai(text,target)
+            CB.record_success()
+            return c
+        except Exception:
+            CB.record_failure()
+            h=HeuristicStrategy().compress(text,target); h.strategy="llm_semantic_fallback_error"; return h
+
+class HybridStrategy(Strategy):
+    name="hybrid"
+    def compress(self, text: str, target: str) -> CompressedMessage:
+        h=HeuristicStrategy().compress(text,target)
+        l=LLMSemanticStrategy().compress(text,target)
+        facts=list(dict.fromkeys(h.facts+l.facts))[:6]
+        return CompressedMessage(h.intent,facts,h.action_items,l.blockers,max(h.confidence,l.confidence),self.name)
+
+STRATEGIES={"heuristic":HeuristicStrategy(),"llm_semantic":LLMSemanticStrategy(),"hybrid":HybridStrategy()}
+
+class RedisRateLimiter:
+    def __init__(self):
+        self.url=os.getenv("REDIS_URL",""); self.rpm=int(os.getenv("GATEWAY_RPM","120"))
+        self.client=redis.from_url(self.url, decode_responses=True) if (self.url and redis is not None) else None
+        self.local: Dict[str, List[float]] = {}
+    def allow(self, key: str) -> bool:
+        now=time.time()
+        if self.client is not None:
+            bucket=f"rl:{key}:{int(now//60)}"; c=self.client.incr(bucket)
+            if c==1: self.client.expire(bucket,70)
+            return c<=self.rpm
+        arr=[t for t in self.local.get(key,[]) if now-t<=60]
+        if len(arr)>=self.rpm: self.local[key]=arr; return False
+        arr.append(now); self.local[key]=arr; return True
+
+LIMITER=RedisRateLimiter()
+METRICS={"requests":0,"errors":0,"latency_ms_sum":0.0,"benchmark_gate":0.95}
+
+def estimate_cost(tokens:int, price=0.01): return round(tokens/1000*price,6)
+
+def transform_impl(payload: TransformRequest, tenant: str) -> Dict[str, Any]:
+    text=redact_pii(payload.message)
+    c=STRATEGIES.get(payload.strategy, STRATEGIES["heuristic"]).compress(text,payload.target)
+    if c.confidence < payload.min_confidence:
+        c.facts=list(dict.fromkeys(c.facts+_sentences(text)[:2]))[:6]; c.fallback_used=True; c.confidence=min(0.99, round(c.confidence+0.15,2))
+    bt=TOKEN_COUNTER.count(text); at=TOKEN_COUNTER.count(json.dumps(asdict(c), ensure_ascii=False))
+    ratio=round(max(0,bt-at)/max(1,bt),4)
+    return {"version":API_VERSION,"tenant":tenant,"target":payload.target,"compressed":asdict(c),"metrics":{"tokens_before":bt,"tokens_after":at,"saving_ratio":ratio,"cost_before_usd":estimate_cost(bt),"cost_after_usd":estimate_cost(at)}}
+
+def api_keys()->Dict[str,str]:
+    raw=os.getenv("GATEWAY_API_KEYS",""); out={}
+    for pair in [x for x in raw.split(",") if x.strip()]:
+        if ":" in pair: t,k=pair.split(":",1); out[k.strip()]=t.strip()
+    return out
+
+@app.get('/health')
+def health(): return {"status":"ok","version":API_VERSION}
+
+@app.get('/metrics')
+def metrics():
+    avg=METRICS['latency_ms_sum']/METRICS['requests'] if METRICS['requests'] else 0
+    return {"requests":METRICS['requests'],"errors":METRICS['errors'],"avg_latency_ms":avg,"benchmark_gate":METRICS['benchmark_gate'],"redis_enabled":bool(LIMITER.client)}
+
+@app.post('/transform')
+def transform(req: TransformRequest, x_api_key: Optional[str] = Header(default=None), x_request_id: Optional[str] = Header(default=None)):
+    t0=time.time(); METRICS['requests']+=1
+    keys=api_keys(); tenant='public'
+    if keys:
+        if not x_api_key or x_api_key not in keys: METRICS['errors']+=1; raise HTTPException(status_code=401, detail='unauthorized')
+        tenant=keys[x_api_key]
+    k=f"{tenant}:{x_request_id or 'no-rid'}"
+    if not LIMITER.allow(k): METRICS['errors']+=1; raise HTTPException(status_code=429, detail='rate limited')
+    out=transform_impl(req,tenant); METRICS['latency_ms_sum']+=(time.time()-t0)*1000; return out
 
EOF
)
