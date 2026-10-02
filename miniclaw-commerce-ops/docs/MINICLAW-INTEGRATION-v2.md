# MiniClaw 接入与运行验证说明 v2

## 当前结论

project017 已为 MiniClaw `main@3ff1c8d6a0707f4a9f0957ff411758e5e141583a` 准备一主四专角色文件、五工具 Pi extension、Profile/Workspace 请求模板和 Plugin Catalog 静态资产，并完成 Supervisor + 单个直播专业子 Agent 的真实 synthetic 冒烟。2026-09-03 又完成后端驱动的 `/v1/native` 原生运行入口、持久化幂等、单次提交、父子审计账本和确定性终态对账。2026-09-04 的完整 v4 固定三域五表请求只 POST 一次：三个专业角色与较早策略调用完成，策略 DecisionPacket 通过 Pydantic；但直播同回合重复 analyze 与 Supervisor 同回合重复策略仍使完整流程严格失败。后续无模型根因诊断确认单工具字段已到达最终序列化 JSON，本地链路未绕过；项目侧已让审计 run ID 成为权威结果，并把驻留平台进程状态与单次回合状态分离。

当前状态：

- Provider configured in isolated runtime: `true`
- Plugin imported: `false`
- Plugin enabled: `false`
- AgentProfile created in isolated runtime: `true`
- Workspace created in isolated runtime: `true`
- ModelRuntime created in isolated runtime: `true`
- AgentSession executed: `true`
- Standalone specialist executed: `false`
- Supervisor plus one specialist executed: `true`
- Full one-main-four-specialist workflow executed: `true`
- Full one-main-four-specialist strict acceptance: `false`
- Real model called for synthetic smoke: `true`
- Real business data used: `false`
- Post-fix compatibility bridge no-model validation: `true`
- Post-fix AgentProfile applied to isolated runtime: `true`
- Post-fix AgentSession executed: `true`
- Post-fix Pi session initialized before Provider rejection: `true`
- Post-fix Provider inference accepted: `true`
- Native backend API implemented: `true`
- Native host started and health checked without model: `true`
- Native backend submitted a new model run: `true`（仅原生内容增长 v1，一次提交）

静态/无模型 harness 与真实 AgentSession 证据仍需分开。harness 直接调用 Pi ToolDefinition 或 Loader 已注册工具；v3 脱敏轨迹则记录了 Supervisor 真实派发 `live-conversion-analyst`，并由该子 Agent 显式调用 inspect 与直播分析工具。

## 平台与项目职责

| 类别 | 来源 | 当前用途 | 归属边界 |
| --- | --- | --- | --- |
| Pi Agent Runtime、AgentSession、Plugin Catalog、Subagent 生命周期 | MiniClaw 平台 | 提供运行和调度底座 | 平台整体架构，不写为本人从零研发 |
| `@tintinweb/pi-subagents@0.16.1` | MiniClaw runner | 读取 `.pi/agents` 与 `subagents.json` | 平台依赖；project017 只做角色配置与约束适配 |
| 五工具 Python/FastAPI/stdio MCP | project017 | 执行确定性数据检查、分析和钻取 | project017 已实现并通过 synthetic 工具层验证 |
| Pi extension、compatibility bridge、角色 frontmatter 与运行配置 | project017 | 将业务契约映射到 MiniClaw/Pi，并对非 Git 工作区的父级派发执行 fail-closed 门控 | 静态、无模型加载、单域 AgentSession 和完整一主四专真实轨迹已验证；完整流程严格验收尚未通过 |

## 运行结构

```text
project017 FastAPI /v1/native
  -> MiniClaw Host API
  -> MiniClaw Supervisor
  ├─ Agent → content-growth-analyst
  │    └─ role-local Pi extension → role-local stdio MCP process
  ├─ Agent → live-conversion-analyst
  │    └─ role-local Pi extension → role-local stdio MCP process
  ├─ Agent → attribution-lead-analyst
  │    └─ role-local Pi extension → role-local stdio MCP process
  └─ Agent → commerce-review-strategist
       └─ no extension, no tool

project-local runtime audit
  -> 合并父级 Agent 与子级业务工具尝试
  -> 校验最终 PROJECT017_NATIVE_RESULT_JSON
  -> completed / partial / blocked / uncertain
```

Supervisor 只负责 `workflow_run_id`、路由、结果收集、Schema 校验和汇总。三个专业角色分别在自己的 MCP 进程内先调用 `inspect_commerce_data`，再调用本域分析和可选 drilldown。这样处理是因为 DatasetManifest 注册表为 MCP 进程内状态，不能假设一个进程登记的数据会自动出现在另一个进程。

## Supervisor 工具边界

MiniClaw 当前 Pi runner 把主会话 `DEFAULT_ALLOWED_TOOLS` 映射为明确的 `selectedTools`，Pi `allowedToolNames` 再过滤项目 extension 工具。project017 的 Profile 同时将 `runtime_policy.mcp` 设为 `disabled`，不把 Plugin MCP 加入 Supervisor 能力。

因此当前设计中：

- Supervisor 使用平台提供的 `Agent`、`get_subagent_result`、`steer_subagent`。
- Supervisor 不直接获得 `commerce_ops_*` 五个项目 extension 工具。
- 专业子 Agent 通过 `extensions` 显式加载 project017 extension，再由 `ext:commerce-ops-mcp/<tool>` 缩小工具范围。
- 复盘策略 Agent 使用 `tools: none`、`extensions: false`。

锁定 commit 的源码、静态配置和 v3 脱敏轨迹共同证明：直播单域冒烟中 Supervisor 只调用一次 `Agent`，没有直接调用 `commerce_ops_*`；`live_conversion_analyst` 依次调用 inspect 与直播分析。内容增长 v1 则真实记录了首次 `isolation=worktree` 失败和第二次派发，不能写成严格通过。

project017 兼容桥现已在注册 `Agent` ToolDefinition 时移除上游 worktree 推荐文案，把 `isolation` 参数说明改为必须省略，并通过 `tool_call`/`tool_result` 门控在创建子 Agent 前拒绝带 isolation 的调用。首次父级失败会锁住本会话后续新 `Agent` 派发，并附加 `project017DispatchAudit`；最终报告仍须把父级派发和子级业务工具合并为同一尝试账本。完整 v3 暴露的锁反向污染竞态已修复，历史 bridge v10 又证明 `disable_parallel_tool_use=true` 可到达 Provider 请求。完整 v4 仍出现双工具，说明远端语义不可靠。当前 bridge v11 为 Agent 声明 `executionMode=sequential`，并把重复同角色 Provider proposal 透明记录为 `coalesced`、复用首个结果；专业 extension 对重复阶段采用同一规则。安全违规和真实失败仍 fail-closed，原始 Prompt 与完整参数不进入审计。该新边界只通过无模型/合成门禁，尚未用完整真实模型流程复验。

## 角色级权限

| 角色 | 允许工具 | 进程状态要求 |
| --- | --- | --- |
| `content_growth_analyst` | inspect、短视频分析、drilldown | 在同一角色进程先 inspect |
| `live_conversion_analyst` | inspect、直播分析、drilldown | 在同一角色进程先 inspect |
| `attribution_lead_analyst` | inspect、渠道线索分析、drilldown | 在同一角色进程先 inspect |
| `commerce_review_strategist` | 无 | 只读取 Supervisor 提供的结构化诊断包 |

`.pi/subagents.json` 使用：

- `strictAgentFiles=true`
- `fallbackSubagent=none`
- `disableDefaultAgents=true`
- `maxSubagentDepth=1`
- `schedulingEnabled=false`

这些配置用于拒绝未知角色、损坏角色文件、默认全工具 Agent、嵌套委派和计划任务入口。

## 五工具 extension

入口：`.pi/extensions/commerce-ops-mcp/index.ts`

依赖：

- `@earendil-works/pi-coding-agent@0.84.2`
- `@modelcontextprotocol/sdk@1.30.0`
- `typebox@1.3.7`

extension 只注册：

1. `commerce_ops_inspect_commerce_data`
2. `commerce_ops_analyze_short_video_data`
3. `commerce_ops_analyze_live_commerce_data`
4. `commerce_ops_analyze_attribution_and_leads`
5. `commerce_ops_drilldown_commerce_metric`

每个 extension 实例维护自己的 MCP Client 与 stdio transport；`session_shutdown` 关闭 transport。所有映射强制 `synthetic=true`，结果详情记录 `automaticRetry=false`。harness 证据仍属于无模型桥接；v3 运行轨迹已另行证明其中两个业务工具由直播专业子 Agent 实际调用。

## Plugin、Profile 与 Workspace

`integrations/miniclaw-plugin-marketplace` 是未来导入 MiniClaw Catalog 的静态目录。它声明同一个 Python stdio MCP Server，但当前仍未导入、未启用，也不是本次运行的工具来源。本次运行使用 project-local Pi extension 与 Subagent compatibility bridge。

`config/agent-profile-create.template.json`：

- 使用四段 Prompt Schema v2。
- authored 模板继续保留 `model_config_id=null`，不把本机运行数据库 ID 写入可复制配置。
- `runtime_policy.skills` 与 `runtime_policy.mcp` 均 disabled。
- 保留 MiniClaw preset，只追加 project017 的 Supervisor 契约。
- 明确 project017 非 Git，`Agent` 必须省略 isolation；父级派发失败立即 `blocked` 且不得第二次派发；最终尝试账本同时覆盖父级与子级。
- authored 模板保持 `model_config_id=null`；安全启动脚本会在启动原生 API 前通过官方 API 幂等同步唯一同名 Profile、保留原模型绑定并回读核对。当前隔离运行数据库为 version 3，四段 Prompt 哈希和 authored 模板一致。Profile 落库只能证明运行配置已生效，不能替代修复后 Agent 工具轨迹。

`config/workspace-create.template.json`：

- `execution_mode=host`
- `interaction_mode=assistant`
- `custom_cwd=D:\Workspace\project017-miniclaw-commerce-ops`
- authored 模板中的 Profile ID 保留占位符；隔离运行时已另行创建实际 Profile 与 Workspace，敏感或数据库 ID 不进入文档。

## 本地无模型验证命令

```powershell
cd D:\Workspace\project017-miniclaw-commerce-ops
python -B scripts\verify-miniclaw-static-config.py --output artifacts\miniclaw-static-config-v17.json
node scripts\verify-miniclaw-subagent-bridge.mjs --output artifacts\miniclaw-subagent-bridge-validation-v10.json
node --experimental-strip-types scripts\verify-provider-request-chain.mjs --output artifacts\provider-request-chain-validation-v1.json
python -B -m commerce_ops.tool_validation
python -B -m unittest discover -s tests -p "test_*.py" -v
cd .pi\extensions\commerce-ops-mcp
node validate-runtime.mjs --output ..\..\..\artifacts\pi-extension-runtime-v3.json
node validate-pi-resource-loader.mjs --output ..\..\..\artifacts\pi-default-resource-loader-v2.json
npm.cmd audit --json
```

## 结果解释

静态与无模型结果：

- 静态配置：`167/167` 通过，当前证据为 v18；新增检查覆盖 proposal/attempt 分层和确定性准入边界。
- Subagent bridge：`36/36` 通过，当前证据为 v11；父级工具声明顺序执行，同角色重复提议合并到 1 次准入尝试，安全拒绝仍 fail-closed。
- Provider request chain：`14/14` 通过；真实 Pi Loader 与 Anthropic serializer 的最终请求 JSON 保留单工具字段，假 `fetch` 保证零联网、零模型调用。
- Python：`65/65` 通过；已验证驻留进程仍为 `running` 时可结算当前回合、审计 ID 不被模型自报值替换，且不会新建 Session 或重发消息。
- extension API harness：`22/22` 通过，当前证据为 v5；重复分析 proposal 复用首个 service run，不再次调用 MCP。
- Pi `DefaultResourceLoader` harness：`19/19` 通过，当前证据为 v4。
- Subagent compatibility bridge：`26/26` 通过；包括 worktree 前置拒绝、第二次派发锁止、`tool_result isError` 和脱敏父级审计。
- Python 完整回归：`59/59` 通过；包括原生 MiniClaw Client/API、持久化幂等、无重试、父子账本对账和最终回复敏感字段脱敏。
- 本机 Host：3017 端口健康检查通过，未认证访问正确返回 401；该项没有创建 Session 或提交消息。
- Node 依赖：Pi `0.84.2`、MCP SDK `1.30.0`、TypeBox `1.3.7`。
- `npm audit --json`：执行时 0 vulnerabilities。
- 两个 harness 均完成 7 次 synthetic 工具调用，`automatic_retry_attempted=false`，并触发 shutdown 关闭 transport。

- 静态配置通过：证明文件、Prompt、角色 allowlist、Plugin 声明、版本和文档边界一致。
- extension harness 通过：证明 Node 原生 TypeScript 加载、五个 ToolDefinition 注册及 synthetic stdio MCP 调用可用。
- DefaultResourceLoader 通过：证明同版本 Pi Loader 能发现 extension、注册五工具并完成无模型 synthetic 调用。
- npm audit 通过：只证明当前 project017 extension 锁文件依赖图在执行时没有 npm 已知漏洞报告。

真实 synthetic 冒烟结果：

- Provider/模型：阿里云百炼 / `qwen3.7-plus-2026-05-26`。
- v2：真实派发和业务工具链已发生，但严格 inspect 参数/次数与最终报告准确性不通过；失败证据保留。
- v3：Supervisor + `live-conversion-analyst` 严格业务冒烟通过；显式调用为 `Agent ×1、inspect ×1、analyze ×1、drilldown ×0`。
- 内容增长 v1：专业子链 `inspect ×1、analyze_short_video ×1` 通过，但父级 `Agent ×2`、首次 worktree 失败和错误最终声明使严格端到端冒烟失败。
- 内容增长 v2：修复后 Profile 已生效，任务只提交一次；百炼返回 HTTP 400 `Arrearage`，没有完成模型推理，也没有 Agent 或业务工具调用，因此严格契约为 `not_evaluated`。
- v3 评估：16 项中 14 项通过、0 项失败、2 项观测差异；差异涉及父级 activity-end 聚合计数和 final reply/平台状态时序。
- v3 记录 5 次模型请求、46,599 reported tokens，估算成本为 `null/unknown`。
- 原生内容增长 v1：`/v1/native` 使用全新 workflow/session/dataset 身份且只提交一次，父级 `Agent ×1`、子级 `inspect ×1 → analyze_short_video ×1` 全部完成，最终结构化报告的 3 次总尝试和全部 run_id 与项目审计一致。
- 原生内容增长 v1 的 23 项评估为 20 pass、0 fail、1 difference、2 not_evaluated；业务链、final reporting accuracy 与平台生命周期通过。MiniClaw Session 曾在最终回复后超过宽限时间报告 `running`，后续只读复查确认回收到 `idle`；项目终态仅因旧审计精确值差异为 `partial`，没有重提、删除或重置会话。
- 原生审计没有采集本轮模型请求数、token 或价格映射，这些值保持 `null/unknown`。凭据仅用于本机交互登录和后端进程内临时认证，不进入文档、artifact 或日志。
- 完整一主四专 v3：唯一 workflow 只提交一次；三个专业父级均各一次且前台串行，内容和归因各为 `inspect ×1 → analyze ×1`，直播的第二次 analyze 被 extension 在 MCP 前阻断，归因唯一 inspect 已完整登记三类跨表数据。Supervisor 同回合发出两个策略调用，两次均未完成；最终 12 次合并账本及全部 6 个 service run ID、3 个 analysis run ID 对账准确，整体严格失败并保留证据。
- v3 之后的 bridge v10 竞态与 provider 单工具请求门禁为无模型 35/35 通过，没有覆盖或重跑该失败 workflow。
- v3 的持久化平台快照随后通过唯一一次真实 GET 从 `running` 更新为 `idle`，生命周期告警被移除，12 次账本和业务 `partial` 结论不变；该检查未创建 Session、提交消息或调用模型，证据为 `artifacts/runtime/native-full-v3-lifecycle-refresh-v1.json`。
- 完整一主四专 v4：预检请求只 POST 一次，父级 5、专业工具 7、合计 12；10 completed、2 blocked。三个专业父级仍各一次前台串行，直播的第二个 analyze 被阻断；Supervisor 的较早策略调用完成，后发重复策略被阻断，证明 bridge 截止序号没有反向污染较早在途调用。
- v4 策略输出通过 `DecisionPacket.model_validate()`，0 个 Pydantic 错误；最终尝试数和 3 个 analysis run ID 与审计一致，但 service run ID 报告观察 6 个却输出 7 个，遗漏 1 个观察值并加入 2 个未观察值。正式 assessment 为 35 项中 28 pass、5 fail、1 difference、1 not_evaluated。
- v4 真实 Provider 请求未因 `disable_parallel_tool_use` 字段报兼容错误，但 Supervisor 与直播专业 Agent 仍各出现一个同回合双工具响应。无模型请求链已排除本地 hook/serializer 绕过，根因类别为 provider 行为契约不一致；精确远端组件仍不可见。
- v4 最终回复后多次只读 GET 仍为 `running`。固定 MiniClaw 源码确认 conversation process 默认驻留 30 分钟，因此该值作为平台进程状态原样保留；项目侧提交回合可由相同 workflow 的结构化最终结果和零 unfinished 审计结算。v4 的重复调用失败不受此重分类影响。

以上结果仍不能推出 Plugin 已启用、完整一主四专已严格通过、30 条评测通过、真实电商数据已接入，或 GMV、ROI、转化率、效率和成本收益成立。

## 后续运行顺序

原生入口、三个专业单域、策略修复和完整一主四专 v1-v4 真实运行均已发生，但完整流程严格验收仍未通过。v4 已完成固定请求的唯一提交、只读观察和严格留证，不得复用其 workflow 或 idempotency key。本轮已完成无模型诊断、审计权威输出、生命周期分层和不依赖 Provider 单工具承诺的确定性准入边界。下一步先安全启动并同步新版 authored Profile，再使用新的唯一身份做一次受控真实模型复验。严格通过后生成“第 13 期课程”五类跨表 synthetic 数据，再完成失败恢复与必要评测，最后整理 GitHub 交付包。`/demo` 与 `web/` 保持冻结；Plugin 导入/启用继续作为独立选择。

原生服务端配置、请求示例和失败语义见 `docs/MINICLAW-NATIVE-RUNTIME-v1.md`。
