"""AI Token Saver Gateway - lightweight semantic compression at agent communication edges."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
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

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))


def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _extract_list_by_keywords(text: str, keywords: Iterable[str]) -> List[str]:
    sents = _sentences(text)
    out: List[str] = []
    for s in sents:
        low = s.lower()
        if any(k in low for k in keywords):
            out.append(s)
    return out[:5]


def _top_keywords(text: str, k: int = 6) -> List[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
    freq: Dict[str, int] = {}
    for w in words:
        if w in STOPWORDS:
            continue
        freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:k]]


def compress_message(text: str) -> CompressedMessage:
    sents = _sentences(text)
    intent = sents[0] if sents else ""

    facts = _extract_list_by_keywords(text, ["fact", "data", "evidence", "结果", "观察", "发现"])
    action_items = _extract_list_by_keywords(text, ["need", "should", "must", "todo", "action", "next", "请", "需要", "下一步"])
    blockers = _extract_list_by_keywords(text, ["risk", "block", "issue", "error", "fail", "限制", "问题", "风险"])

    if not facts:
        facts = [f"keywords:{','.join(_top_keywords(text))}"] if text.strip() else []

    signal = len(facts) + len(action_items)
    noise = max(1, len(sents))
    confidence = min(0.99, round(0.4 + 0.5 * (signal / noise), 2))

    return CompressedMessage(
        intent=intent[:200],
        facts=facts,
        action_items=action_items,
        blockers=blockers,
        confidence=confidence,
    )


def gateway_transform(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Transform verbose upstream agent payload into minimal decision-ready JSON."""
    text = str(payload.get("message", ""))
    target = payload.get("target", "general_decision")
    compressed = compress_message(text)
    return {
        "target": target,
        "compressed": asdict(compressed),
        "token_saving_hint": "send compressed only unless downstream requests full context",
    }


if __name__ == "__main__":
    sample = {
        "target": "deploy_decision",
        "message": """We analyzed incident logs. Fact: memory spikes at 03:00 UTC correlate with retry storms.
        Next step: should cap retries and add circuit breaker. Risk: rollout may affect latency.""",
    }
    print(json.dumps(gateway_transform(sample), ensure_ascii=False, indent=2))
