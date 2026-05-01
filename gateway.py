"""AI Token Saver Gateway - production-oriented v0.3."""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock
from typing import Any, Dict, Iterable, List

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "and", "or", "in", "on", "for", "with",
}


@dataclass
class CompressedMessage:
    intent: str
    facts: List[str]
    action_items: List[str]
    blockers: List[str]
    confidence: float
    strategy: str = "keyword_heuristic"
    fallback_used: bool = False


class CompressionStrategy:
    name = "base"

    def compress(self, text: str, target: str = "general_decision") -> CompressedMessage:
        raise NotImplementedError


def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _extract_list_by_keywords(text: str, keywords: Iterable[str]) -> List[str]:
    out = []
    for s in _sentences(text):
        low = s.lower()
        if any(k in low for k in keywords):
            out.append(s)
    return out[:5]


def _top_keywords(text: str, k: int = 6) -> List[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
    freq: Dict[str, int] = {}
    for w in words:
        if w not in STOPWORDS:
            freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:k]]


class KeywordHeuristicStrategy(CompressionStrategy):
    name = "keyword_heuristic"

    TARGET_KEYWORDS = {
        "deploy_decision": ["deploy", "release", "rollback", "latency", "error", "risk"],
        "incident_triage": ["incident", "root cause", "impact", "mitigation", "severity"],
        "general_decision": ["fact", "need", "next", "risk", "decision"],
    }

    def compress(self, text: str, target: str = "general_decision") -> CompressedMessage:
        sents = _sentences(text)
        intent = sents[0] if sents else ""

        target_words = self.TARGET_KEYWORDS.get(target, self.TARGET_KEYWORDS["general_decision"])
        facts = _extract_list_by_keywords(text, ["fact", "data", "evidence", "结果", "观察", "发现"] + target_words)
        action_items = _extract_list_by_keywords(text, ["need", "should", "must", "todo", "action", "next", "请", "需要", "下一步"])
        blockers = _extract_list_by_keywords(text, ["risk", "block", "issue", "error", "fail", "限制", "问题", "风险"])

        if not facts:
            facts = [f"keywords:{','.join(_top_keywords(text))}"] if text.strip() else []

        signal = len(facts) + len(action_items)
        noise = max(1, len(sents))
        confidence = min(0.99, round(0.4 + 0.5 * (signal / noise), 2))

        return CompressedMessage(intent[:200], facts, action_items, blockers, confidence, strategy=self.name)


def estimate_token_count(text: str) -> int:
    return max(1, len(re.findall(r"\S+", text)))


def estimate_cost_usd(token_count: int, price_per_1k_tokens: float = 0.01) -> float:
    return round((token_count / 1000.0) * price_per_1k_tokens, 6)


def evaluate_cost_saving(original_text: str, compressed: CompressedMessage, price_per_1k_tokens: float = 0.01) -> Dict[str, float]:
    before_tokens = estimate_token_count(original_text)
    compressed_text = json.dumps(asdict(compressed), ensure_ascii=False)
    after_tokens = estimate_token_count(compressed_text)
    saved = max(0, before_tokens - after_tokens)
    return {
        "tokens_before": before_tokens,
        "tokens_after": after_tokens,
        "tokens_saved": saved,
        "saving_ratio": round(saved / before_tokens, 4) if before_tokens else 0.0,
        "cost_before_usd": estimate_cost_usd(before_tokens, price_per_1k_tokens),
        "cost_after_usd": estimate_cost_usd(after_tokens, price_per_1k_tokens),
    }


def apply_safe_fallback(original_text: str, compressed: CompressedMessage, min_confidence: float = 0.65) -> CompressedMessage:
    if compressed.confidence >= min_confidence:
        return compressed
    backup = _sentences(original_text)[:2]
    compressed.facts = list(dict.fromkeys(compressed.facts + backup))[:6]
    compressed.fallback_used = True
    compressed.confidence = round(min(0.99, compressed.confidence + 0.15), 2)
    return compressed


def gateway_transform(payload: Dict[str, Any], strategy: CompressionStrategy | None = None) -> Dict[str, Any]:
    strategy = strategy or KeywordHeuristicStrategy()
    text = str(payload.get("message", ""))
    target = payload.get("target", "general_decision")
    min_conf = float(payload.get("min_confidence", 0.65))

    compressed = strategy.compress(text, target)
    compressed = apply_safe_fallback(text, compressed, min_confidence=min_conf)
    metrics = evaluate_cost_saving(text, compressed, float(payload.get("price_per_1k_tokens", 0.01)))

    return {
        "target": target,
        "compressed": asdict(compressed),
        "metrics": metrics,
        "token_saving_hint": "send compressed only unless downstream requests full context",
    }


class RateLimiter:
    def __init__(self, requests_per_minute: int = 120):
        self.requests_per_minute = requests_per_minute
        self._hits: Dict[str, List[float]] = {}
        self._lock = Lock()

    def allow(self, client_id: str) -> bool:
        now = time.time()
        with self._lock:
            arr = [t for t in self._hits.get(client_id, []) if now - t <= 60]
            if len(arr) >= self.requests_per_minute:
                self._hits[client_id] = arr
                return False
            arr.append(now)
            self._hits[client_id] = arr
            return True


RATE_LIMITER = RateLimiter(int(os.getenv("GATEWAY_RPM", "120")))
API_KEY = os.getenv("GATEWAY_API_KEY", "")


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "AITokenSaverGateway/0.3"

    def _json_response(self, code: int, data: Dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _request_id(self) -> str:
        return self.headers.get("X-Request-Id", f"req-{int(time.time()*1000)}")

    def _client_id(self) -> str:
        return self.client_address[0] if self.client_address else "unknown"

    def _authorized(self) -> bool:
        if not API_KEY:
            return True
        return self.headers.get("X-API-Key", "") == API_KEY

    def _guard(self) -> bool:
        rid = self._request_id()
        if not self._authorized():
            self._json_response(401, {"error": "unauthorized", "request_id": rid})
            return False
        if not RATE_LIMITER.allow(self._client_id()):
            self._json_response(429, {"error": "rate limit exceeded", "request_id": rid})
            return False
        return True

    def do_GET(self):
        rid = self._request_id()
        if self.path == "/health":
            self._json_response(200, {"status": "ok", "request_id": rid})
            return
        if self.path == "/metrics":
            self._json_response(200, {
                "service": "ai-token-saver-gateway",
                "rate_limit_rpm": RATE_LIMITER.requests_per_minute,
                "auth_enabled": bool(API_KEY),
                "request_id": rid,
            })
            return
        self._json_response(404, {"error": "not found", "request_id": rid})

    def do_POST(self):
        rid = self._request_id()
        if self.path not in ("/compress", "/transform"):
            self._json_response(404, {"error": "not found", "request_id": rid})
            return
        if not self._guard():
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._json_response(400, {"error": "invalid json", "request_id": rid})
            return

        result = gateway_transform(payload)
        result["request_id"] = rid
        self._json_response(200, result)


def run_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    server = HTTPServer((host, port), GatewayHandler)
    print(f"Gateway server running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
