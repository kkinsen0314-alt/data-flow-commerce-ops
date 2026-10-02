# 证据边界

## 证据分层

| 标签 | 含义 | 当前状态 |
| --- | --- | --- |
| `reused_from_project015` | 代码、设计或 fixture 来自只读直播项目 | 三个白名单文件已复制并记录来源哈希；不能继承 project015 的运行结论 |
| `miniclaw_native_capability` | MiniClaw 数据库、队列、认证、Catalog、Pi Runtime 或 Subagent | 平台能力，不是个人从零研发成果 |
| `project017_static_verified` | project017 配置、Schema、源码和文档经过静态验证 | 当前静态配置 v21 为 175/175 通过 |
| `project017_synthetic_tool_verified` | 确定性工具或无模型桥接使用 synthetic 数据运行 | Python、HTTP、stdio MCP、Pi extension、Loader 和 compatibility bridge 已完成分层验证 |
| `project017_native_runtime_no_model_verified` | 后端原生入口、宿主启动、幂等提交边界、运营投影、失败恢复和父子账本在不调用模型时完成验证 | Python 99/99、静态 v21 175/175、bridge v14 39/39、extension v8 23/23、Loader v4 19/19、provider request chain 14/14；本机 Host 健康检查通过 |
| `project017_native_content_business_reporting_verified` | `/v1/native` 通过真实模型完成内容增长单域，并由项目脱敏账本校验最终结构化报告 | 原生内容增长 v1 的 `Agent ×1 + inspect ×1 + analyze ×1` 全部完成，次数和 run_id 一致；后续只读复查确认平台 Session 回收到 `idle`，旧审计精确值差异使项目终态仍为 `partial` |
| `project017_native_attribution_business_reporting_verified` | `/v1/native` 通过真实模型完成渠道线索归因单域，并由项目脱敏账本和确定性重算校验结果 | 原生渠道归因 v1 的 `Agent ×1 + inspect ×1 + analyze ×1` 全部完成，父级前台参数、次数、run_id 和四项指标一致；业务按预期为 `partial`，后续只读复查确认平台回收到 `idle` |
| `project017_native_strategy_runtime_observed` | `/v1/native` 通过真实模型执行渠道诊断与零工具策略角色 | 父级 `Agent ×2`、渠道工具 `2` 次和最终合并账本通过；DecisionPacket 经 Pydantic 产生 20 个错误，策略契约失败，不能标记 verified |
| `project017_eval_infrastructure_verified` | 电商评测集、fixture、评分器、分批计划和回归比较器完成离线验证 | 30/30 fixture preflight、6 个批次精确覆盖、H09/H10/H12 复核来源门禁和评测执行器单元测试通过；B01 已采集 5/30 条真实 Agent 轨迹，完整 30-case run 仍为 0 |
| `project017_deterministic_demo_verified` | 本地演示编排实际调用确定性工具并生成结构化报告 | 三域内置样例、synthetic 上传、结果读取和报告下载已验证；固定声明未调用 Provider/Agent Runtime |
| `project017_development_tools_discovered` | 项目级 Skill 已被 Codex 发现，可用于后续界面开发与验收 | 7/7 已发现；不属于 MiniClaw 或项目运行能力 |
| `project017_single_specialist_runtime_verified` | MiniClaw Supervisor 与一个专业子 Agent 使用真实模型运行 synthetic 冒烟 | 直播 v3 严格通过；原生内容增长 v1 与原生渠道归因 v1 的业务、报告及后续生命周期通过；历史内容增长失败轨迹仍原样保留 |
| `project017_full_multi_agent_runtime_verified` | 内容、直播、归因、策略和 Supervisor 的完整一主四专轨迹 | v7 已以全新身份只提交一次并严格 18/18 通过；v4/v5/v6 历史失败证据继续保留，不能反向改写 |
| `real_business_verified` | 真实数据、真实经营指标和业务收益有测量证据 | 尚未开始 |

## 当前可以声明

- 已实现独立的电商运营统一契约、五个只读确定性工具、FastAPI 与 stdio MCP 入口。
- 已建立一主四专角色配置，Supervisor 只负责调度与校验；三个专业角色各自先 inspect，再调用本域分析和受限钻取；策略角色不加载工具。
- 已建立角色级 `ext:commerce-ops-mcp/<tool>` 白名单、未知角色拒绝、默认 Agent 禁用、嵌套禁用和计划调度禁用。
- 已实现五工具 Pi extension，并通过 Node 24 原生 TypeScript、extension harness 与同版本 Pi Loader 验证。
- 当前验证基线为 Python `99/99`、静态配置 v21 `175/175`、extension harness v8 `23/23`、Pi `DefaultResourceLoader` v4 `19/19`、compatibility bridge v14 `39/39` 和 provider request chain `14/14`。
- 确定性准入边界已在无模型/合成 harness 中证明：Pi 按 Provider 原顺序执行工具，重复角色或阶段 proposal 被透明记录为 `coalesced` 并复用首次结果，只形成 1 次 Agent/MCP 执行；其后的完整一主四专 v7 已用独立真实轨迹取得 18/18 严格通过。
- 已实现 `/v1/native` 服务端原生入口：验证 Workspace/Profile 后生成唯一运行身份，持久化幂等状态，创建 Session 并最多提交一次消息；查询路径只读，传输副作用不确定时停止且不自动重试。
- 已实现父级 `Agent` 与子级业务工具的项目侧脱敏审计及确定性合并对账；审计生成权威尝试数和 run ID，模型自报值只用于 reconciliation，不能替换审计结果。
- 已在 3017 端口实际启动 project017 隔离 MiniClaw Host，健康接口返回 initialized，未认证接口正确拒绝；该次验收未创建 Session、未调用 Provider 或模型。
- 已编写 30 条电商评测用例和 7 个专用 fixture，并通过 30/30 fixture preflight。B01 的 NORMAL-001—005 已形成 5/30 条独立真实 Agent 脱敏轨迹；3 条 `completed`、2 条 `partial`，五条均因 H05 参数范围偏差未通过自动门禁，NORMAL-003 与 NORMAL-005 另触发 H01。
- B01 共记录 578,300 Token；按执行时公开常规输入/输出价且不主张缓存折扣的保守估算为 ¥1.645288，未出现余额不足。该值是项目侧估算，不等于供应商最终账单。H09、H10、H12 与五维软评分仍为 0/5 待人工或另行授权 Judge，B02—B06 未授权、未运行。
- 已在 project017 隔离运行配置中实际使用阿里云百炼与 `qwen3.7-plus-2026-05-26`，创建并运行 MiniClaw AgentSession。
- 已真实运行 Supervisor + `live-conversion-analyst` 的 synthetic 冒烟。v3 中显式业务调用为 `Agent ×1、inspect ×1、analyze_live ×1、drilldown ×0`，Supervisor 未直接调用业务工具。
- v3 strict business smoke 与最终报告准确性均通过；两个 service_run_id、analysis_run_id 和 evidence→finding 引用均可由脱敏轨迹核验。
- v2 的 inspect 参数/次数报告失败和 v3 的两项观测差异均保留，没有删改失败证据或猜测聚合计数来源。
- v3 共记录 5 次模型请求和 46,599 reported tokens；估算成本仍为 `null/unknown`。
- 已真实运行 Supervisor + `content-growth-analyst`。子 Agent 仅执行 `inspect ×1 → analyze_short_video ×1`，未钻取，业务参数、service/analysis run_id 和 evidence→finding 完整。
- 内容增长 v1 的首次 `Agent` 因错误的 worktree isolation 失败，Supervisor 随后发起第二次 `Agent`；最终回复遗漏父级失败并错误声明零失败、无重试、全部约束满足。该次只能声明“内容增长专业子链完成”，不能声明严格冒烟通过。
- 内容增长 v1 评估为 13 pass、4 fail、2 difference；6 次模型请求、65,235 reported tokens，成本为 `null/unknown`。
- 已针对该失败实现 project017 父级派发门控：Agent 描述不再推荐 worktree，带 isolation 的调用在子 Agent 创建前返回 blocked/isError，首次失败后锁住后续派发，并通过 `project017DispatchAudit` 保留父级尝试。真实 `DefaultResourceLoader` 无模型验证为 25/25，未创建 AgentSession。
- 最新派发门控 AgentProfile 已由安全启动脚本通过官方 API 幂等写入隔离运行数据库并核对为 version 3；四段 Prompt 哈希匹配，原 Provider 绑定保留，平台额外默认字段未被误写为 authored 能力。同步过程未创建 Session 或调用模型。
- bridge v7 无模型验证为 30/30：`run_in_background=true` 和同 `subagent_type` 第二次派发都在上游 Agent execute 前被拒绝并记录 started/finished 审计。Agent schema 不使用会在桥接审计前截断违规值的 `const false`；真正的强制约束位于 tool_call/execute 运行时门控。
- 内容增长 v2 只提交一次，但首个百炼请求在模型推理前被 `Arrearage` 拒绝；没有 Agent/业务工具调用，0 reported token 不能独立证明最终账单为零。该次只能证明 Profile 已落地和单次提交保护生效，不能证明派发门控通过或失败。
- 内容增长 v3 已真实运行单次父级派发并正确省略 isolation，但专业 Agent 在同一 assistant 回合发出两个短视频 analyze 参数变体；业务结果可用，严格次数与单回合单工具契约失败，最终报告准确披露偏差。
- 内容增长 v4 已真实运行父级 `Agent ×1`，专业 Agent 分两个 assistant 回合执行 `inspect ×1 → analyze_short_video ×1`，未钻取；固定参数、两个 service_run_id、analysis_run_id、synthetic 标记和 evidence→finding 均完整，业务工具无自动重试。
- v4 的 Agent 序列化参数没有显式 `run_in_background=false`，但角色配置和阻塞式完成记录证明实际前台执行；该项作为参数记录差异保留，不改写为后台运行。
- v4 最终回复只统计两次子级业务工具，没有把父级 `Agent ×1` 合并进尝试账本，并把全部显式尝试 3 次写成 2 次。因此 v4 只能声明专业业务子链和单回合单工具契约通过，不能声明 strict end-to-end 或 final reporting accuracy 通过。
- v4 正式 assessment 为 23 项中 19 pass、1 fail、2 difference、1 not_evaluated；5 次模型请求、49,752 reported tokens，成本仍为 `null/unknown`。
- 已在一次明确授权内通过 `/v1/native` 只提交一次原生内容增长 synthetic 运行。父级 `Agent ×1` 与子级 `inspect ×1 → analyze_short_video ×1` 全部完成；最终结构化报告中的 3 次总尝试、两个 service_run_id 和一个 analysis_run_id 与项目审计一致。
- 原生内容增长 v1 的 strict business smoke、final reporting accuracy 与平台生命周期通过；正式 assessment 为 23 项中 20 pass、0 fail、1 difference、2 not_evaluated。Session 曾超过宽限时间为 `running`，后续只读复查确认回收到 `idle`；project017 终态仅因旧审计精确值差异保留 `partial`。
- 原生 v1 的模型请求数、token 与成本未由项目审计采集，保持 `null/unknown`；登录凭据、临时 Cookie、原始 Prompt 和原始工具参数未写入交付 artifact。
- 原生 v1 结束后新增 `run_in_background_value` 精确审计并修正 lifecycle warning 的 reconciliation 汇总顺序；该修复只经过无模型验证，没有反向改写或重跑历史运行。
- 已在新的明确授权内通过 `/v1/native` 只提交一次原生渠道归因 synthetic 运行。父级 `Agent ×1` 与子级 `inspect ×1 → analyze_attribution_and_leads ×1` 全部完成，未调用 drilldown、策略或其他专业角色；最终结构化报告与项目审计均为 3 次总尝试，并准确列出两个 service_run_id 和一个 analysis_run_id。
- 原生渠道归因 v1 的 deterministic 重算与最终报告一致：线索数 12、24 小时首次跟进率 75%、订单关联覆盖率 66.6667%、线索到已支付订单转化率 50%。报告正确保留一条缺失跟进导致的业务 `partial`、无成本不算 ROI、关联不等于因果、不评价个人能力和 synthetic 边界。
- 渠道归因 v1 正式 assessment 为 30 项中 28 pass、0 fail、0 difference、2 not_evaluated；strict business smoke、final reporting accuracy 与平台生命周期通过。后续只读 GET 确认 `idle/settled`，没有创建 Session、提交消息或重提任务。
- 策略 v1 在一次新授权下只提交一个有效 workflow；渠道业务链、`Agent ×2`、零工具策略边界、4 次合并账本、最终报告准确性和后续 `idle/settled` 生命周期通过。实际 DecisionPacket 有 20 个 Pydantic 错误，正式 assessment 为 40 项中 33 pass、5 fail、1 difference、1 not_evaluated，策略严格契约失败。
- 运行后已无模型收紧策略角色 Prompt，并通过 129/129 静态检查与契约单测；这只证明修复后的配置与确定性契约一致，不等于修复后模型输出已经通过。
- 完整一主四专 v3 只提交一次并准确对账 12 次父子尝试、6 个 service run ID 和 3 个 analysis run ID；三个专业角色均真实运行，归因三表准入通过。直播的重复分析被 extension 在 MCP 前阻断，Supervisor 又同回合重复派发策略，因此严格失败，未重提任务。
- v3 后 bridge v9 已用锁生效序号修复“后发重复调用反向污染较早在途调用”的竞态，并增加不同角色并发调用阻断；无模型验证 31/31 通过，不等同于修复后完整模型流程已通过。
- 完整一主四专 v4 使用预检固定请求只 POST 一次。三个专业角色与较早的策略调用完成，后发重复策略被单独阻断，真实证明 bridge 截止序号不会反向污染较早调用；策略 DecisionPacket 通过生产 Pydantic，0 error。
- v4 仍有直播同回合双 analyze 和 Supervisor 同回合双策略；两个后发尝试均被 fail-closed 门禁阻断。最终 `5/7/12` 尝试数和 3 个 analysis run ID 对账，但模型自报 service run ID 集合不一致。35 项评估为 28 pass、5 fail、1 difference、1 not_evaluated，完整流程严格失败且未重提。
- 新的 14/14 无模型 request-chain 验证证明 `disable_parallel_tool_use=true` 保留到真实 Pi Anthropic serializer 的最终 JSON，并排除本地 hook/serializer 绕过；v4 实际双工具响应只支持“provider 行为契约不一致”，不能继续断言阿里云兼容网关或模型后端中的具体忽略层。
- 固定 MiniClaw 源码证明 conversation agent 默认驻留 30 分钟。项目侧现在分别返回原始 `platform_status` 与提交回合 `observed_execution_state`；相同 workflow 的结构化最终结果和零 unfinished 审计可结算回合，不会把平台 `running` 改写成 `idle`。
- 已实现本地确定性演示编排与 FastAPI 演示接口；内置样例实际生成三域 AnalysisPacket、DrilldownResult、规则化 Action、VerificationMetric 和 DeliveryPackage。
- 演示接口明确返回 `provider_called=false` 和 `agent_runtime_executed=false`；其角色时间线证明业务分工和数据流可以组装，不证明本轮运行了 MiniClaw AgentSession。
- 已在 project017 本机安装 7 个项目级界面开发 Skill，并通过 Codex 项目发现检查；该结论只证明开发工具可被发现。

## 当前不能声明

- 已导入或启用 project017 Plugin。当前业务工具来自 project-local Pi extension，不能把 Plugin Catalog 静态资产写成运行来源。
- 已取得所有运行契约字段均有精确审计的内容增长无差异结论。原生 v1 的业务、报告和平台回收通过，但旧父级审计缺少 `run_in_background` 精确值。
- v7 严格通过等同于 30 条正式评测、baseline/candidate 回归结论或持续生产稳定性证明。
- v3 冒烟等同于 30 条正式评测，或已经得到 Agent 通过率和 baseline/candidate 质量结论。
- 父级 `toolUses=3` 等于三次业务工具调用；业务调用次数以子 Agent `.output` 中两个显式 assistant `toolCall` 为权威来源。
- `platform_status=running` 可以被改写为 `idle`，或可单独证明提交回合未完成；平台驻留进程状态与项目侧提交回合状态必须分别保留。
- 运行时价格映射为 0 证明免费；B01 只有按公开价格和 reported tokens 计算的保守估算，不能替代供应商最终账单，历史运行成本仍有未采集项。
- 已使用真实电商数据，或提升 GMV、ROI、转化率、运营效率、成本或用户规模。
- project015 的静态检查、评测、Loader 或隔离启动结果属于 project017。
- MiniClaw/Pi Runtime、Pi Subagent、AgentSession、宿主界面和调度底座由本人从零研发。
- 本地确定性演示中的 Supervisor/专业角色/策略角色时间线等同于真实一主四专模型运行。
- 这些项目级 Skill 已进入 MiniClaw 运行时、被 Agent 调用，或可写成本人研发的业务能力；公开 GitHub 包也不会包含 `.agents/skills`。

## 归因边界

### 本人完成

后续简历只能把 project017 中实际完成并重新验证的内容写为本人工作，例如：

- 电商业务问题拆解、一主四专职责和五工具范围。
- Workflow/Pydantic/JSON Schema、run_id 和 evidence→finding→action→verification_metric 证据链。
- Python/Pandas 确定性工具、FastAPI/stdio MCP 接入和 synthetic fixtures。
- Pi extension ToolDefinition 映射、compatibility bridge 接入、非 Git 工作区的 isolation fail-closed 门控、父子尝试账本、角色级工具范围、失败语义和静态/无模型验证资产。
- 在 MiniClaw/Pi Runtime 上完成业务配置与 synthetic 一主一子冒烟，采集并审计脱敏轨迹。

### 平台整体架构

MiniClaw 的数据库、队列、认证、Plugin Catalog、Pi Agent Runtime、Pi Subagent、AgentSession、宿主界面和基础调度工具属于平台能力。项目只能描述为“基于 MiniClaw/Pi Runtime 进行业务接入、角色约束和运行验证”，不能写成个人从零研发平台底座。

### 尚待确认

历史内容增长 v4 与完整 v4/v5/v6 的失败证据继续保留；原生内容增长、渠道归因和完整一主四专 v7 已分别取得边界内的真实 synthetic 运行证据。30 条真实模型评测现完成 B01 的 5/30 条轨迹采集，但 0/5 通过自动门禁、语义复核 0/5，尚不能形成 baseline 质量结论。Plugin 导入/启用、其余 25 条 baseline、完整 candidate、LLM-as-Judge、真实业务阈值、准确成本/延迟 SLO 和经营收益仍须后续确认。Provider 与模型曾用于受控 synthetic 运行，但不能据此写成持续可用。

## 验证结果如何解释

| 结果 | 可以证明 | 不能证明 |
| --- | --- | --- |
| 99 项 Python 测试 | 契约、服务、HTTP、stdio MCP、冻结演示、原生 Client/API、运营结果与任务记录、持久化幂等、失败恢复、synthetic 上传、真实批次运行器、离线评测门禁和公开包构建符合当前测试 | Agent 或模型质量 |
| 175 项静态检查 | Prompt、父级派发门控、provider 请求链证据、脱敏原生审计源码、配置、角色权限、版本和文档一致 | 本轮完成了模型推理或重跑了 Agent |
| 23 项 extension harness | extension 可加载、注册五工具、执行身份归一化并调用 MCP | Supervisor 本轮实际调用 |
| 19 项 Loader harness | 同版本 Pi Loader 可发现、加载并按角色隔离 extension | 真实子 Agent 路由与生命周期 |
| 39 项 compatibility bridge 检查 | 平台 Subagent 调度工具可经 project-local bridge 注册，执行角色、幂等、workflow 身份、重复提议和失败锁止门禁 | 本轮完成了真实一主四专模型运行；真实结论须看独立 v7 轨迹 |
| 原生 Host 健康证据 | project017 隔离宿主可启动、载入 host Workspace，认证边界正常 | 已通过新入口创建 Session、提交消息或运行模型 |
| v3 脱敏轨迹与 16 项评估 | Supervisor 已实际派发一个直播专业子 Agent，严格 synthetic 业务链路通过并保留两项观测差异 | 其他角色、完整多 Agent、30-case 或真实经营效果 |
| 内容增长 v1 脱敏轨迹与 19 项评估 | 内容增长专业子 Agent 的 inspect→analyze 子链完成；父级两次 Agent 尝试、失败披露错误和两项观测差异有证据 | 内容增长严格端到端冒烟通过、其他角色、完整多 Agent 或真实经营效果 |
| 内容增长 v3 脱敏轨迹与 12 项评估 | 单次派发、isolation 省略和最终偏差披露通过；重复 analyze 与同回合批量工具调用有证据 | 内容增长严格端到端冒烟通过、其他角色或完整多 Agent |
| 内容增长 v4 脱敏轨迹与 23 项评估 | 单次派发、分回合 inspect→analyze、固定参数、run_id/evidence 链和 synthetic 边界通过；最终合并尝试账本遗漏有证据 | strict end-to-end、完整一主四专、30-case 或真实经营效果 |
| 原生内容增长 v1 脱敏轨迹与 23 项评估 | `/v1/native` 单次提交、父子 3 次尝试、最终报告账本、synthetic 边界和后续 idle 回收通过；running-after-final 的早期观测仍保留 | 历史父级调用的精确 `run_in_background` 审计值、其他角色、完整一主四专、30-case 或真实经营效果 |
| 原生渠道归因 v1 脱敏轨迹与 30 项评估 | `/v1/native` 单次提交、父子 3 次尝试、精确 `run_in_background=false`、渠道跨表指标、ROI/因果/个人评价边界、最终账本和后续 idle 回收通过 | 策略角色真实运行、完整一主四专、30-case、准确模型成本或真实经营效果 |
| 完整一主四专 v3 脱敏轨迹与 assessment | 三个专业角色各一次前台派发、归因三表准入、阻断重复业务调用、12 次合并账本和全部 run_id 准确对账 | 完整流程严格通过、策略成功完成、30-case 或真实经营效果 |
| 完整一主四专 v4 脱敏轨迹与 35 项 assessment | 固定请求只提交一次；三个专业角色和较早策略完成；竞态截止与 DecisionPacket 契约通过；重复调用阻断、尝试数和分析 run ID 有证据 | 单工具字段已实际生效、service run ID 报告准确、平台已回收、完整流程严格通过、30-case 或真实经营效果 |
| bridge v11 的 36 项无模型验证 | Pi 顺序执行、重复同角色 proposal 合并到 1 次准入尝试、安全违规仍 fail-closed | 修复后完整一主四专真实模型流程已经通过 |
| provider request chain 的 14 项无模型验证 | 两类 project017 hook 均被真实 Loader 加载，改写结果保留到 Pi Anthropic serializer 的最终 JSON | 阿里云兼容网关或模型后端实际执行了单工具语义 |
| npm audit 0 | 当前锁文件依赖图在执行时无 npm 已知漏洞报告 | 永久无漏洞或整个平台依赖已审计 |
| 30/30 fixture preflight | 评测集、契约引用和 fixture 可供外部运行器使用 | 30 条 Agent 用例已经执行或通过 |
| B01 的 5 条真实脱敏轨迹与部分 baseline | NORMAL-001—005 已使用独立 Session/workflow/幂等键执行并留下可评分证据；自动门禁发现 H01/H05 偏差 | 五条质量通过、H09/H10/H12 通过、完整 30-case baseline、candidate 或发布准入 |
| 7/7 项目 Skill 发现 | Codex 可在 project017 中定位这些界面开发辅助 Skill | 界面已经实现、MiniClaw 已加载这些 Skill，或 Agent 运行质量已提升 |

## 数据与安全边界

- Python 负责确定性清洗、计算、阈值和判断；LLM 不凭空计算经营指标。
- 无稳定关联键时输出 `missing_evidence` 或 `blocked`，不做伪归因。
- 无成本字段时不计算 ROI。
- synthetic 数据必须保留 `synthetic=true` 或等价来源标签。
- 默认只读，不写 CRM、订单、线索、工单或外部消息系统。
- 不保存或输出不必要的手机号、订单号、用户身份、Provider Key 或 Session Secret。
- 副作用不确定时停止自动重试，通过 run_id 与日志核对。
- 后续真实模型重跑必须再次得到明确授权，不因本次文档同步自动发生。
- 公开 GitHub 包排除 `.agents/skills`、本地运行数据、密钥、数据库和日志；第三方 Skill 不作为项目源代码再分发。
