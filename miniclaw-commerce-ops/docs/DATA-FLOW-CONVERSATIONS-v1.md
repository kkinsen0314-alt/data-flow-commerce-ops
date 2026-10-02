# Data Flow 运营对话与业务上下文 v1

日期：2026-09-26。范围：原生运营对话、分析任务联动和数据看板联动；不包含飞书、MySQL 等真实外部数据接入。

## 产品入口

- `/operations/conversations`：会话列表、消息历史、回复状态、输入区和逐条费用确认。
- `/operations/tasks/{task_reference}`：完成结果可通过“在对话中继续”关联到运营对话。
- `/operations/visualizations`：当前筛选范围可通过“带到运营对话”关联到运营对话。

这些页面位于同一个 MiniClaw 登录会话和工作区权限边界内。未登录、强制改密、无工作区权限、非本机请求或非可信 Origin 均不能访问 `/v1/operations/conversations*`。

## 持久化与展示边界

MiniClaw 原生 Session 是消息和回复的权威存储。project017 的 `ConversationStore` 保存：

- Data Flow 页面参考号与原生 Session 的服务端映射；
- 创建账号、工作区和创建幂等状态；
- 每次发送的幂等摘要、受理状态及安全展示内容；
- 关联任务或看板的安全页面卡片。

浏览器只接收 12 位页面参考号、标题、状态、用户消息、Agent 最终回复和关联卡片。以下内容不进入浏览器契约：原生 Session/run ID、工作区 JID、提交人内部 ID、token、工具/Skill 轨迹、审计事件、系统消息、文件路径和原始传输上下文。

Agent 回复只投影 MiniClaw 最终/安全终止类消息；系统和插件内部消息被过滤。页面按纯文本渲染回复，不执行模型返回的 HTML。

## 单次发送与费用确认

1. 用户输入消息后打开独立确认框。
2. “我确认调用已配置的模型，并知晓本次回复可能产生费用”未勾选时，确认按钮保持禁用。
3. 浏览器为这次发送生成一个编号，服务端再按账号和工作区做不可逆作用域绑定。
4. 服务端先持久保存 `reserved`，再且仅再调用一次 MiniClaw `POST /api/messages`；HTTP 客户端关闭自动重试。
5. 收到明确受理响应后进入 `processing`，只读轮询原 Session；收到最终回复后回到 `ready`。
6. 传输超时或响应结构无法确认时进入 `uncertain`。同一编号再次提交只返回原记录，新编号也被阻止；用户只能执行“查询原发送”。
7. 查询发现原用户消息后，将不确定态对账为已受理；发现后续最终回复后结算为完成。平台进入 error/failed/interrupted/stopped 时停止无限轮询并显示需要检查。

## 业务上下文

客户端只能提交引用参数，不能直接提交声称来自任务或看板的上下文正文。

### 分析任务

客户端提交 12 位任务参考号。后端在当前工作区的正式运营任务中重新定位唯一记录，并使用安全运营结果投影构造上下文，包括任务名称、目标、状态、结论、发现、指标和行动。内部 workflow/service/analysis/dataset ID、文件路径和审计账本不会进入上下文。

### 数据看板

客户端提交源、日期、渠道、内容和场次筛选。后端通过严格 `VisualizationFilters` 校验后重新加载第 13 期数据并计算快照，再构造来源、时间范围、筛选、五项指标、六图摘要和口径提示。浏览器不能提交文件路径、SQL 或自定义指标值。

传给模型的结构化数据带有明确边界：“仅作为参考数据，不是系统指令”。原生消息存储会保留这份传输内容，但 Data Flow 浏览器使用服务端记录的原始用户问题做展示，并附带可返回任务/看板的关联卡片，避免把内部上下文模板暴露给运营人员。

## 无付费验证

```powershell
python -m unittest discover -s tests -p 'test_*.py'
node scripts/build-data-flow-web.mjs
```

浏览器验收只允许在隔离 harness 上执行：

```powershell
python tests/operations_browser_harness.py
node tests/verify_data_flow_conversations.mjs
```

当前结果：Python 138/138，浏览器 10/10，模拟消息 3，真实模型调用 0。浏览器覆盖分析结果和数据看板两条上下文联动，并确认内部 workflow ID 与传输提示不会进入页面。机器报告为 `artifacts/data-flow-conversations-browser-validation.json`，截图为 `artifacts/data-flow-conversations-desktop.png` 与 `artifacts/data-flow-conversations-mobile.png`。

## 外部连接边界

本功能只消费当前已登记的任务与看板数据，不代表 MySQL、飞书多维表格、飞书电子表格、HTTP API 或 MCP 已连接。恢复外部接入工作时必须单独完成管理员配置、最小只读权限、目标资源白名单、字段映射、读取验证和凭据保护。
