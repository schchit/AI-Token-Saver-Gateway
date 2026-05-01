# AI-Token-Saver-Gateway (v2.1)

补齐“最后一公里”：真实 LLM 调用、Redis 多实例限流、一键部署和业务 benchmark 接入。

## 重点
- `llm_semantic` 真实接 OpenAI Chat Completions（带 Circuit Breaker）
- FastAPI + Uvicorn 生产服务
- Redis 限流（`REDIS_URL`）
- tiktoken 真实 token 计数
- benchmark 支持 `business_cases.jsonl` 业务样本优先
- 一键启动：`docker compose up --build`

## 快速开始
```bash
make quickstart
make test
make bench
```

## 生产启动
```bash
docker compose up --build
```

## 环境变量
- `OPENAI_API_KEY`
- `OPENAI_MODEL=gpt-4o-mini`
- `GATEWAY_API_KEYS=tenant:key`
- `REDIS_URL=redis://redis:6379/0`
- `TOKENIZER_PROVIDER=openai`
- `TOKENIZER_MODEL=gpt-4o-mini`
