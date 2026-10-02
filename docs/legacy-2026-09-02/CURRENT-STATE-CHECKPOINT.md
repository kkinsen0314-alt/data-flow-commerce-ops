# 当前状态检查点

## 检查时间与目录关系

- 最近复验时间：2026-09-02
- 本轮工作目录：`D:\Workspace\project017-miniclaw-commerce-ops`
- 当前工作目录就是 project017 根目录。
- `project014-miniclaw-deployment` 与 `project015-miniclaw-live-ops` 仅作为只读来源。

## 来源项目状态

### project014-miniclaw-deployment

- 上游 checkout：`D:\Workspace\project014-miniclaw-deployment\upstream\miniclaw`
- 分支：`main`
- commit：`3ff1c8d6a0707f4a9f0957ff411758e5e141583a`
- 工作树：干净
- 处理方式：只读核对 Schema、Pi Runtime、pi-subagents 和生命周期源码，不修改平台正本

### project015-miniclaw-live-ops

- 不是 Git 仓库。
- 处理方式：继续冻结为直播业务、MiniClaw 适配方法和历史证据来源。
- 本轮没有修改、覆盖、重命名或删除 project015。
- project015 的静态检查、评测、Loader 与隔离启动不继承为 project017 结果。

## project017 当前状态

- project017 不是 Git 仓库；未初始化或提交 Git。
- 一主四专角色配置、五工具 Pi extension、Profile/Workspace authored 模板和 Plugin Catalog 静态资产已建立。
- 30 条评测用例、7 个专用 fixture、H01—H12、`preflight/score/compare` 和回归模板已建立；30/30 fixture preflight 通过。
- Python 完整回归为 49/49；extension harness 为 15/15；Pi Loader harness 为 14/14；Subagent compatibility bridge fail-closed 验证为 25/25。
- 静态验证当前为 128/128；历史 90/90、105/105、110/110、118/118 报告继续保留为阶段快照。
- project017 extension 依赖锁定 Pi `0.84.2`、MCP SDK `1.30.0`、TypeBox `1.3.7`；历史 npm audit 记录为 0 vulnerabilities。
- 隔离运行配置已实际创建 AgentProfile、Workspace、ModelRuntime 和 AgentSession，并使用阿里云百炼 / `qwen3.7-plus-2026-05-26`。
- v2 冒烟已真实派发直播专业子 Agent，但严格 inspect 参数/次数与最终报告不通过；失败证据保留。
- v3 冒烟已真实运行 Supervisor + `live-conversion-analyst`，显式链路为 `Agent ×1 → inspect ×1 → analyze_live ×1`，未调用 drilldown。
- v3 strict business smoke 和 final reporting accuracy 通过；16 项评估为 14 pass、0 fail、2 observability differences。
- v3 共记录 5 次模型请求和 46,599 reported tokens；成本仍为 `null/unknown`。
- 内容增长 v1 已真实运行 Supervisor + `content-growth-analyst`。专业子 Agent 显式业务链路为 `inspect ×1 → analyze_short_video ×1`，未调用 drilldown，业务参数与 run_id/evidence 链通过。
- 内容增长 v1 的 Supervisor 先以 `isolation=worktree` 调用 `Agent` 并失败，随后第二次调用才成功；最终回复未披露该失败与重复派发。因此 19 项评估为 13 pass、4 fail、2 differences，strict end-to-end smoke 与 final reporting accuracy 失败。
- 内容增长 v1 共记录 6 次模型请求和 65,235 reported tokens；成本为 `null/unknown`。Supervisor 在同一任务内发起了第二次 Agent 调用，但页面与 Codex 没有重提整条任务。
- 内容增长失败后的无模型根因修复已完成：authored Profile 禁止 worktree isolation、父级失败立即 blocked；兼容桥移除上游 worktree 推荐，并在子 Agent 创建前拒绝带 isolation 的调用、锁住后续派发和附加父级尝试审计。
- v2 bridge validator 使用真实 `DefaultResourceLoader` 完成 25/25 检查；第一次 worktree 调用与第二次调用均未进入上游 Agent execute，验证过程未创建 AgentSession、未启动 MCP、未调用模型。
- 修复后 AgentProfile 已通过 MiniClaw 官方 API 落地为 version 2；四段 Prompt 哈希与 authored 模板一致，平台自动补入的 `reasoning.effort=inherit` 作为额外默认字段保留。
- 内容增长 v2 使用新会话只提交一次，但百炼在模型推理前返回 HTTP 400 `Arrearage`；reported token 为 0，没有产生 Supervisor 输出、`Agent` 调用、子 Agent 或业务工具调用，且没有自动重试或任务重提。
- 内容增长 v2 的 SDK 轨迹已记录终止错误，而 UI-facing session 仍为 `running/waiting`；两种状态分别保留为生命周期差异，不能互相改写。
- 本地确定性演示后端已完成：支持内置三域样例、synthetic 表格上传、运行结果读取和 JSON 报告下载。
- 默认演示返回 3 个 AnalysisPacket、3 个 DrilldownResult、3 个 Action、12 个 WorkflowStep 和 9 个 SummaryMetric；因部分线索缺少首次跟进记录，总状态为 `partial`。
- 项目功能演示页已完成：支持三域切换、合成数据上传、证据指标、维度钻取、角色工作流、行动复验和 JSON 下载；页面由同一 FastAPI 应用通过 `/demo` 提供。
- HTTP 与页面测试已覆盖 `/health`、演示页面、静态资源、场景读取、样例运行、上传运行和报告下载；该过程没有调用 Provider 或 Agent Runtime。
- 7 个界面开发辅助 Skill 已安装到 `.agents/skills`，Codex 项目发现检查为 7/7；这些 Skill 只参与开发和验收，不进入项目运行链路。

## 当前仍未发生的动作

- 未导入或启用 project017 Plugin；当前业务工具来自 project-local Pi extension。
- 未通过内容增长严格单次派发冒烟；未运行渠道线索归因和复盘策略角色。
- 修复后 Profile 已写入隔离运行数据库，但尚未完成修复后内容增长 Agent 路由；v2 在 Provider 推理前被账户状态阻断，不能算通过或失败。
- 未运行完整一主四专、失败恢复全集或 30 条真实模型 Agent 评测。
- 未接入 LLM-as-Judge，未形成 Agent 通过率或 baseline/candidate 质量结论。
- 未使用真实电商数据或外部业务系统，未生成或声称真实经营收益。
- 未确认准确模型成本，也未形成最终端到端延迟 SLO。

## 运行观测边界

- 父级 `Agent.details.toolUses` 是 activity-end 聚合值，不是显式业务 toolCall 的严格计数。
- v3 业务调用次数以子 Agent `.output` 中两个显式 assistant `toolCall` 和对应 toolResult 为权威来源。
- 内容增长 v1 的业务子链同样以子 Agent `.output` 中两个显式 toolCall 为权威；父级主会话另有两次 `Agent` toolCall，其中第一次失败，不能被业务工具计数或最终回复遗漏。
- final reply 可能先于 persistent conversation agent 从 `running` 回收到 `idle`；平台状态和观察到的最终回复分别保留。
- project017 辅助页已加入 idle/error 终态和 20 秒只读等待，不会为观测差异自动重提任务。

## 机器可读证据

- `artifacts/miniclaw-static-config-v5.json`
- `artifacts/miniclaw-subagent-bridge-validation-v2.json`
- `artifacts/pi-extension-runtime-v2.json`
- `artifacts/pi-default-resource-loader-v2.json`
- `artifacts/npm-audit-commerce-ops-extension-v1.json`
- `artifacts/tool-layer-validation-v1.json`
- `artifacts/contract-validation-v1.json`
- `artifacts/evals/fixture-preflight-v1.json`
- `artifacts/evals/evaluation-executor-selftest-v1.json`
- `artifacts/runtime/smoke-live-v2-bridge-redacted-trace.json`
- `artifacts/runtime/smoke-live-v2-bridge-assessment.json`
- `artifacts/runtime/smoke-live-v3-contract-redacted-trace.json`
- `artifacts/runtime/smoke-live-v3-contract-assessment.json`
- `artifacts/runtime/smoke-content-v1-contract-redacted-trace.json`
- `artifacts/runtime/smoke-content-v1-contract-assessment.json`
- `artifacts/runtime/smoke-content-v2-dispatch-guard-redacted-trace.json`
- `artifacts/runtime/smoke-content-v2-dispatch-guard-assessment.json`
- `artifacts/runtime/runtime-observability-source-audit-v1.json`

这些 artifacts 分别记录静态/无模型验证、离线评测基础设施和真实模型 synthetic 冒烟。直播 v3 是严格通过的一主一子单域冒烟；内容增长 v1 只证明专业子链完成，同时保留父级路由/报告失败。两者都不是完整一主四专或 30-case 评测。

## 下一步

本地项目功能演示已经可独立启动，下一步准备“第 13 期课程”跨表合成数据，并将页面运行入口逐步接入 MiniClaw 原生一主四专链路。真实模型方向仍需先恢复百炼账户可用状态并获得新的费用与运行授权，不得复用 v2 会话、重复提交直播 v3，或覆盖内容增长 v1/v2 证据。
