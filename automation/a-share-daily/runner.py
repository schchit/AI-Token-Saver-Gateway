#!/usr/bin/env python3
"""Production entrypoint: connected data + OpenAI web search or auditable rules."""
from __future__ import annotations

import main as core
import decision_rules
import source_fallback


def run() -> int:
    core.collect_quotes = source_fallback.collect_quotes
    core.select_candidates = decision_rules.select_candidates
    packet = core.gather()
    prompt = core.llm_prompt(packet)
    report, error = core.openai_engine(prompt)
    engine = "OpenAI Responses + Web Search"
    if error or not report:
        if error:
            core.log(f"OpenAI unavailable, using rule engine: {error}")
        report = decision_rules.rule_engine(packet)
        engine = "联网数据 + 可审计规则引擎"
    report = core.validate(report) + f"\n<!-- generation_engine: {engine} -->\n"
    core.publish(report)
    core.log(f"published with {engine}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
