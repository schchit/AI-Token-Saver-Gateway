# AI-Token-Saver-Gateway

生产级 v0.3：在多智能体通信边缘拦截长文本，压缩为目标相关 JSON，并提供成本评估、安全回退、鉴权、限流与可观测性。

## 当前能力

- HTTP 网关接口：`/health`、`/compress`、`/transform`、`/metrics`
- Target-aware 压缩策略接口：`CompressionStrategy` + `KeywordHeuristicStrategy`
- 低置信度安全回退：自动补充关键上下文句
- 成本评估：压缩前后 token 与成本估算
- API Key 鉴权（可选）：`GATEWAY_API_KEY`
- 限流（每分钟请求数）：`GATEWAY_RPM`（默认 120）
- 请求追踪：支持 `X-Request-Id`，响应带 `request_id`

## 快速启动

```bash
python gateway.py
```

## 环境变量

- `GATEWAY_API_KEY`：设置后启用鉴权，请求头需带 `X-API-Key`
- `GATEWAY_RPM`：每客户端 IP 每分钟请求上限

## API 示例

```bash
curl -X POST http://127.0.0.1:8080/transform \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: demo-001" \
  -d '{"target":"deploy_decision","message":"Fact: memory spike at 03:00 UTC. Next step: cap retries. Risk: latency impact."}'
```

## 测试

```bash
python -m unittest -v
```
