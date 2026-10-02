# 功能演示后端 v1

## 目标

演示后端把现有五个确定性业务工具组织成可供前端消费的统一工作流。默认运行不需要 Provider、不创建 MiniClaw AgentSession，也不产生模型费用。

演示链路为：

`Supervisor 路由 → 三个专业角色检查数据 → 三域确定性分析 → 受限钻取 → 规则化复盘动作 → Supervisor 交付`

角色名称沿用目标一主四专配置，但返回结果固定声明：

- `mode=deterministic_demo`
- `provider_called=false`
- `agent_runtime_executed=false`
- `synthetic=true`

因此角色时间线只能用于展示业务分工与数据流，不能写成新的真实多 Agent 运行证据。

## API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/v1/demo/scenarios` | 返回可用演示场景和合成数据说明 |
| `POST` | `/v1/demo/runs/sample` | 运行内置全链路 synthetic 样例 |
| `POST` | `/v1/demo/runs/upload` | 上传声明为 synthetic 的 CSV/XLS/XLSX/XLSM 并运行 |
| `GET` | `/v1/demo/runs/{workflow_run_id}` | 读取当前进程缓存的演示结果 |
| `GET` | `/v1/demo/runs/{workflow_run_id}/report` | 下载结构化 JSON 报告 |

内置样例请求：

```json
{
  "scenario_id": "full_commerce_funnel",
  "requested_domains": [
    "content_growth",
    "live_conversion",
    "attribution_leads"
  ],
  "objective": "使用合成数据演示内容、直播、线索与订单的可追溯经营分析。",
  "top_n": 5,
  "include_drilldowns": true
}
```

上传接口使用 `multipart/form-data`：

- `metadata`：`DemoUploadRunRequest` JSON 字符串。
- `files`：与 `datasets.file_index` 一一对应的文件列表。
- 单文件最大 25 MB，最多 6 个文件，总大小最大 50 MB。
- 临时文件只保存在项目 `runtime/demo-uploads` 的临时子目录，运行结束后删除。
- 当前仍只允许 `synthetic=true`，不接收真实敏感经营数据。

## 返回结构

`DemoRunResult` 包含：

- `workflow_run_id`、开始/结束时间和终态。
- 标准化请求和 DatasetManifest。
- 三域 AnalysisPacket、Evidence、Finding 和可选 DrilldownResult。
- 规则化 DecisionPacket、Action 与 VerificationMetric。
- DeliveryPackage 和 Supervisor/专业角色/策略角色时间线。
- `unresolved_items` 与 `evidence_boundaries`。

默认五份 fixture 中有部分线索缺少首次跟进记录，因此完整样例按契约返回 `partial`，不会为界面效果改写成 `completed`。

运行结果只保存在当前 Python 进程的最近 20 条内存缓存中；服务重启后不可恢复。该设计适合本地演示，不是生产持久化方案。

## 当前验证

- project017 Python 完整回归为 49/49。
- JavaScript 语法检查通过。
- HTTP 与页面测试覆盖 `/demo`、静态资源、场景读取、样例运行、上传运行和报告下载。
- 默认样例产生 3 个 AnalysisPacket、3 个 DrilldownResult、3 个 Action、12 个 WorkflowStep 和 9 个 SummaryMetric。

## 界面检查点

演示页面已由同一 FastAPI 应用通过 `/demo` 提供，支持桌面与移动端布局、内置三域样例、合成表格上传、诊断域切换、证据卡片、维度钻取、角色工作流、行动复验和 JSON 下载。页面是 project017 的业务功能演示入口，不是 MiniClaw 平台全部管理功能的镜像。
