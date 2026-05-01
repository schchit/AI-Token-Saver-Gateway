# AI-Token-Saver-Gateway

生产级 v0.2 目标：在多智能体通信边缘拦截长文本，压缩为目标相关 JSON，并提供成本评估与安全回退。

## 已实现能力（对应 1-6）

1. HTTP 网关接口：`/health`、`/compress`、`/transform`
2. Target-aware 压缩策略接口：`CompressionStrategy` + `KeywordHeuristicStrategy`
3. 低置信度安全回退：自动补充关键上下文句
4. 成本评估：压缩前后 token 与成本估算
5. 可扩展策略结构：便于后续接入 LLM 判定器
6. 扩展测试：策略、回退、指标、输出结构

## 快速启动

```bash
python gateway.py
```

默认监听 `0.0.0.0:8080`。

## API 示例

```bash
curl -X POST http://127.0.0.1:8080/transform \
  -H "Content-Type: application/json" \
  -d '{"target":"deploy_decision","message":"Fact: memory spike at 03:00 UTC. Next step: cap retries. Risk: latency impact."}'
```

## 测试

```bash
python -m unittest -v
```
