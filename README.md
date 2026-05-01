# AI-Token-Saver-Gateway

Compress agent-to-agent messages into minimal decision-ready JSON to cut LLM token cost.

## What this is

A lightweight edge interceptor for multi-agent pipelines:

- Accepts verbose upstream agent output.
- Extracts target-relevant intent, facts, actions, and blockers.
- Emits compact JSON for downstream agents.

Goal: reduce token spend by only forwarding the minimum needed for correct downstream decisions.

## Quick start

```bash
python gateway.py
```

Run tests:

```bash
python -m unittest -v
```

## Input / Output

Input payload:

```json
{
  "target": "deploy_decision",
  "message": "Long natural-language output from upstream agent..."
}
```

Output payload:

```json
{
  "target": "deploy_decision",
  "compressed": {
    "intent": "...",
    "facts": ["..."],
    "action_items": ["..."],
    "blockers": ["..."],
    "confidence": 0.78
  },
  "token_saving_hint": "send compressed only unless downstream requests full context"
}
```

## Notes

This MVP uses deterministic heuristics and is model-agnostic. It is designed as a drop-in first pass before invoking expensive LLM calls.
