# A股全市场产业趋势与投资决策自动化

该目录包含一个联网盘前研究任务。它在每个工作日北京时间约 08:25 启动，抓取全 A 股行情、行业板块、上市公司公告、全球市场和新闻，再生成一份明确的账户决策单，并以 GitHub Issue 指派给仓库所有者，从而触发 GitHub 通知。

## 运行引擎

系统按以下顺序降级：

1. **OpenAI Responses API + Web Search**：仓库配置 `OPENAI_API_KEY` Secret 后启用，适合补充官方来源和过去 24 小时深度研究；
2. **GitHub Models + 公共数据采集器**：默认路径，使用 Actions 的 `GITHUB_TOKEN` 和 `models: read` 权限，无需额外粘贴密钥；
3. **安全降级报告**：两个模型都不可用时，仍推送数据状态，但唯一动作固定为保持现金。

## 推送方式

每天创建或更新标题为 `A股盘前决策 | YYYY-MM-DD` 的 Issue，并指派给 `schchit`。GitHub 是否通过 App、浏览器或邮件弹出，取决于账户的 Notifications 设置。完整报告同时保存到：

- `automation/a-share-daily/latest.md`
- `automation/a-share-daily/reports/YYYY-MM-DD.md`

## 可选：启用 OpenAI 深度联网研究

在仓库的 **Settings → Secrets and variables → Actions → New repository secret** 中添加：

- Name: `OPENAI_API_KEY`
- Secret: 你的 OpenAI API Key

不要把密钥写入代码、Issue、聊天或普通环境变量文件。可选仓库变量：

- `OPENAI_MODEL`，默认 `gpt-5.6-terra`
- `OPENAI_REASONING_EFFORT`，默认 `high`

## 手动测试

进入 **Actions → A股盘前全市场决策 → Run workflow**。手动运行会覆盖当天同名 Issue，而不会重复创建。

## 账户维护

`portfolio.json` 是账本来源。只有实际成交后才更新。自动报告不会连接券商，也不会把建议自动计为成交。

## 风险边界

- 不承诺 30% 收益；
- 不自动下单；
- 不使用杠杆；
- 数据或模型不完整时默认保持现金；
- 公开行情接口可能变化，报告会披露采集失败并自动降级。

GitHub 的定时任务可能因平台排队而延迟，所以工作流安排在开盘前约 65 分钟启动，而不是卡在 09:25。
