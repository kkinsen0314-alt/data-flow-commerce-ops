# Data Flow 运行观测口径与平台兼容规则 v1

## 1. 文档状态

- status: `native_content_business_reporting_lifecycle_validated_audit_difference`
- source_platform_commit: `3ff1c8d6a0707f4a9f0957ff411758e5e141583a`
- 适用范围：project017 的 MiniClaw 主会话、Pi Subagent foreground 运行、synthetic 冒烟证据和 `/v1/native` 项目侧对账。
- 原生内容增长 v1 在一次明确授权内调用真实模型；其后的审计字段与 reconciliation 修复没有再次调用模型，也没有修改 MiniClaw 或 pi-subagents 来源代码，synthetic 结果未写成真实经营效果。

## 2. 两类计数不能混用

`@tintinweb/pi-subagents@0.16.1` 的 `record.toolUses` 是 activity-end 聚合值，不是子 Agent 原始 `toolCall` 记录数。

固定来源中：

- `agent-manager.ts:321`、`:582`、`:672` 对每个 `activity.type === "end"` 执行 `record.toolUses++`。
- `agent-runner.ts:944-947` 和 `:1011-1012` 将真实 `tool_execution_end` 映射为 activity end。
- 同一文件的 `:682`、`:701`、`:712`、`:725`、`:735`、`:889` 还会把未知工具、extension 配置告警或 extension bind 错误映射为 activity end；这些活动不一定在子 Agent `.output` 中形成 assistant `toolCall`。

因此 project017 固定采用以下证据优先级：

1. 子 Agent `.output` 中 assistant content 的显式 `toolCall`：业务调用次数权威来源。
2. 对应 `toolResult`：参数结果、`service_run_id`、`analysis_run_id`、耗时和失败状态来源。
3. 父级 `Agent.details.toolUses`：仅作为运行时活动聚合参考；与显式 toolCall 不一致时保留差异，不用于判定 inspect/analyze 的准确次数。
4. Agent 最终自然语言摘要：用于表达审计，不能替代原始轨迹。

第三次冒烟中，父级聚合为 3，子 Agent `.output` 的显式业务 toolCall 为 2。业务链路按后者判定为 inspect ×1、analyze ×1；多出的 activity end 没有足够事件明细可精确归因，不能猜测成第三次业务调用。

## 3. conversation agent 的平台状态不是单次回合状态

MiniClaw 固定来源 `src/index.ts` 中：

- `:14019-14022` 明确说明 conversation process 会在没有新消息时继续驻留到 `idleTimeout`，期间可在 idle 与 running 间循环。
- `:14210` 在处理消息前把 conversation agent 状态设为 `running`。
- `:16975-16984` 的 process-level finally 才把持久 conversation agent 设回 `idle`；默认 `idleTimeout=1800000` 毫秒，即 30 分钟。
- 因此最终 assistant 回复与完整项目审计出现后，平台仍长时间显示 `running` 不只是 20 秒轮询竞态，也可能是正常的驻留进程状态。它不能单独证明该次提交回合仍未完成。

旧版辅助页存在两个项目侧问题：

- settled 状态集合遗漏了 `idle` 和 `error`。
- 一看到最终回复就立即停止轮询，没有给 finally 状态回收留出观察窗口。

`runtime/setup-helper/smoke.html` 的只读等待仍用于观察平台回收，但项目 API 现在采用双状态：

- 最终回复出现后继续只读轮询，不提交新任务。
- 把 `idle/completed/error/failed/interrupted/stopped` 视为平台已回收。
- 最多等待 20 秒；若仍为 running，再记录 `lifecycle_difference` 并停止。
- `platform_status` 原样表示 MiniClaw conversation process 状态。
- `observed_execution_state` 表示当前提交回合的项目侧观测状态。相同 workflow 的结构化最终结果、非空审计及零 unfinished 尝试可把它结算为 `settled`，无需等待驻留进程退出。
- 两者始终分别显示，不互相改写；回合结算也不会触发重提、删除或重置 Session。

## 4. 第三次冒烟的当前结论

- strict business smoke: `pass`
- final reporting accuracy: `pass`
- parent toolUses 与显式 toolCall：`known_non_equivalent_aggregation_semantics`
- 用户当时观察到的 running-after-final：`race_observed_before_helper_fix`
- 是否已证明该 session 后续回收到 idle：`not_captured`

这次运行不需要付费重跑。以后若需要验证生命周期，只使用修复后的只读等待逻辑，或建立不具备提交能力的状态查看页。

## 5. 父级派发尝试必须独立记账

内容增长 v1 的主会话显式轨迹包含两次 `Agent`：第一次由模型添加 `isolation=worktree`，在非 Git 的 project017 中派发失败；第二次才成功创建 `content-growth-analyst`。子 Agent 的 inspect→短视频分析成功不能覆盖第一次父级失败，也不能支持最终回复中的“零失败、无重试”。

无模型根因修复包含两层：

1. authored Supervisor Prompt 明确必须省略 isolation，任一父级参数校验或派发失败立即使当前分支 `blocked`，同一会话不得再次调用 `Agent`。
2. project-local compatibility bridge 在注册 `Agent` ToolDefinition 时移除上游 worktree 推荐，把 isolation 字段说明改为禁止使用，并在 `tool_call` 前置门控中拒绝该参数。首次失败后锁住后续派发，`tool_result` 标记 `isError=true`，同时附加 `project017DispatchAudit`。

`artifacts/miniclaw-subagent-bridge-validation-v4.json` 由真实 `DefaultResourceLoader` 生成，`26/26` 通过；验证中第一次 worktree 调用和第二次无 isolation 调用均在上游 execute 前被阻断，没有创建 AgentSession、没有调用模型，并验证父级审计源码不记录原始 Prompt、会记录参数存在性与安全的精确布尔值。修复后 Profile 随后已写入隔离运行数据库；内容增长 v2 的首个 Provider 请求在推理前被 `Arrearage` 拒绝。内容增长 v3/v4 与原生内容增长 v1 的后续真实轨迹已证明父级只派发一次并省略 isolation；原生 v1 还通过最终报告账本校验。

最终运行评估必须分别采集：

- 父级主会话中的 `Agent` toolCall/toolResult、参数、失败与次数。
- 子 Agent `.output` 中的业务 toolCall/toolResult、service/analysis run_id 与顺序。
- Supervisor 最终声明是否与上述两层显式尝试一致。

## 6. 内容增长 v3/v4 的单回合工具与最终账本口径

内容增长 v3 中，Supervisor 只派发一次并省略 isolation，但专业 Agent 在同一 assistant 回合批量发出两个不同参数版本的 `commerce_ops_analyze_short_video_data`。该次最终报告准确披露重复 analyze，因此派发门控与披露通过，严格业务次数和单回合单工具契约失败。

角色配置随后增加以下约束：

- 每个 assistant 回合最多一个业务工具调用；
- 必须等待工具结果再决定下一次调用；
- analyze 使用唯一固定参数集；
- 禁止参数变体比较调用。

内容增长 v4 的原始轨迹显示：

- 父级 `Agent ×1`，路由 `content-growth-analyst`，isolation 省略；
- 专业 Agent 在两个不同 assistant 回合依次执行 inspect ×1、analyze ×1；
- analyze 使用固定参数，drilldown ×0；
- 两个 service_run_id、analysis_run_id 和 evidence→finding 引用闭合；
- 业务工具 `automaticRetry=false`；
- 5 次模型请求，49,752 reported tokens，成本仍为 `null/unknown`。

v4 的专业业务子链与单回合单工具约束通过，但 Supervisor 最终回复只列两次子级业务工具并写“总尝试次数 2”。项目 Prompt 明确要求合并父级 Agent 与子级业务工具，所以正确的全部显式尝试是 `Agent ×1 + inspect ×1 + analyze ×1 = 3`。因此 v4 的 strict end-to-end 与 final reporting accuracy 判为失败，不能用成功业务子链覆盖。

v4 Agent 的序列化参数没有显式 `run_in_background=false`；`.pi/agents/content-growth-analyst.md` 固定该值为 false，且父级等待子 Agent 完成后才继续，因此实际行为是 foreground。正式 assessment 将“有效前台执行”记为通过，同时把“字面参数未记录”保留为 difference。

父级 `Agent.details.toolUses=3` 继续只作为 activity 聚合参考；v4 子 Agent 显式业务 toolCall 仍是 2，不能把聚合值解释成第三次业务调用。该差异不需要付费重跑，后续应在最终报告生成前用 `project017DispatchAudit` 与子级显式 toolCall 做确定性对账。

## 7. 原生入口的确定性对账

`/v1/native` 不再只依赖 Supervisor 自然语言汇总：

1. compatibility bridge 把每次父级 `Agent` 的 started/finished、角色、次数、状态和 reason code 写入 `runtime/data/native-audit/{workflow_run_id}.jsonl`。
2. commerce-ops Pi extension 把每次子级业务工具的 started/finished、角色、次数、状态、service_run_id 和 analysis_run_id 写入同一脱敏账本。
3. 查询运行状态时，FastAPI 合并两层尝试；项目审计直接生成 `authoritative_result` 的尝试数、service run ID 和 analysis run ID。
4. 最终 `PROJECT017_NATIVE_RESULT_JSON` 自报的次数与 run ID 只进入 reconciliation。ID 要求保序精确匹配；不一致会明确告警，但不能替换项目审计生成的权威 ID。
5. 账本缺失、父级角色或专业工具基数错误、失败/阻断或未完成尝试存在时，即使模型自报 `completed` 也降级为 `partial`。仅模型自报 ID 错误不再污染正确的项目审计结果。
6. 查询只读取 Session、消息与审计；网络或生命周期不确定时保留 `uncertain`，不会为获取更好结果重提消息。

审计不记录原始 Prompt、原始工具参数、Cookie、Authorization、密码或 Provider Key；最终回复在 API 持久化和返回前还会对常见凭据字段做二次替换。当前机制已通过 65 项 Python 回归，并已在原生内容增长 v1 中完成一次真实模型提交与账本对账。

## 8. 原生内容增长 v1 的观测结论

2026-09-03 在一次明确授权内，`/v1/native` 使用唯一 workflow/session/dataset 身份只提交一次内容增长 synthetic 任务：

- 父级 `Agent ×1` 完成，目标为 `content-growth-analyst`，`isolation` 省略；
- 子级依次完成 `inspect ×1 → analyze_short_video ×1`，两次 service_run_id 和一次 analysis_run_id 均进入脱敏账本；
- 最终 `PROJECT017_NATIVE_RESULT_JSON` 报告父级 1 次、子级 2 次、总计 3 次，与项目审计一致，strict business smoke 与 final reporting accuracy 通过；
- MiniClaw Session 在最终回复和完整审计出现后曾超过宽限时间显示 `running`，后续只读复查确认回收到 `idle`；没有自动重提、删除或重置 Session；
- 原生审计未采集模型请求数、token 或准确成本，均保持 `null/unknown`。

运行发生时的 v1 审计记录了 `run_in_background` 参数存在，但未保存精确布尔值。运行后 bridge 新增 `run_in_background_value`，NativeAuditReader 同步读取；对账逻辑调整为先汇总全部告警、再构建 reconciliation，并在新观测到来时移除已经不再成立的派生 warning，避免 `running` 阶段的 lifecycle warning 在后续 `idle` 后残留。修复后的 v4 bridge harness 与 Python 回归均通过，但不能用新字段反向填充历史运行，也没有为此重跑模型。因此原生 v1 assessment 为 20 pass、0 fail、1 difference、2 not_evaluated，唯一 difference 是历史精确值缺失。

机器可读证据：`artifacts/runtime/native-content-v1-redacted-trace.json` 与 `artifacts/runtime/native-content-v1-assessment.json`。

## 9. 证据边界

- 本文确认的是固定源码的计数与状态语义，以及 project017 辅助页的观测修复。
- 本文没有证明完整一主四专工作流、30 条真实模型评测、真实业务数据或真实经营收益。
- MiniClaw、Pi Agent Runtime 和 pi-subagents 的平台实现不能包装为本人从零研发成果。
- project017 可表述为：基于原始轨迹建立业务 toolCall 权威口径，识别 activity 聚合差异，并修复冒烟页对 conversation agent `idle` 回收状态的误判。
- project017 还可表述为：针对非 Git 工作区补充父级 Agent 的 isolation fail-closed 门控和父子尝试账本。带 isolation 的拒绝与锁止路径只完成无模型验证；v3/v4 真实轨迹证明的是正确省略 isolation 后的单次派发，不得混为同一层证据。
- project017 可进一步表述为：历史内容增长 v4 已验证单次派发与分回合 inspect→analyze 业务子链但最终合并尝试账本失败；原生内容增长 v1 已通过业务、报告对账和后续 `idle` 回收，项目 partial 仅来自旧审计精确值缺失。不得把单域证据包装成完整一主四专。

## 10. 完整 v4 的 provider 单工具行为与账本结论

完整 v4 使用预检后的固定三域五表请求只 POST 一次。真实轨迹同时证明两项改进：bridge 锁截止序号没有反向污染更早的在途策略调用，且策略输出通过生产 `DecisionPacket` Pydantic 契约。它也暴露三项仍需修复的差异：

- 直播专业 Agent 的一个 assistant 响应仍包含两个 analyze tool call；后一个被 extension 以 `duplicate_analysis_attempt_forbidden` 阻断。
- Supervisor 的一个 assistant 响应仍包含两个策略 Agent tool call；后一个被 bridge 以 `duplicate_subagent_dispatch_forbidden` 阻断，较早调用正常完成。
- 最终报告的尝试数与 analysis run ID 对账，但 service run ID 集合不一致：项目审计观察 6 个，报告给出 7 个，遗漏一个已观察值并加入两个未观察值。

新的无模型请求链 harness 使用真实 Pi 0.84.2 `DefaultResourceLoader` 与 Anthropic Messages serializer，并用进程内假 `fetch` 截获最终 JSON。Supervisor 与专业 Agent 两条链均证明 `tool_choice.disable_parallel_tool_use=true` 保留到序列化 HTTP body，14/14 通过；没有真实联网或模型调用。因此可以排除 extension 未加载、hook 返回值被丢弃和本地 serializer 删除字段这三类根因。结合 v4 双工具响应，根因类别是 provider 行为契约不一致；但 project017 仍不能观察或断言究竟是阿里云兼容网关还是模型后端未执行该语义。

最终回复和全部 12 次尝试已落盘，多次只读 GET 仍得到 `platform_status=running`。源码诊断确认这是驻留 conversation process 的平台状态；项目侧可把该次提交标为 `observed_execution_state=settled`，同时原样保留平台值。v4 仍因重复分析、重复策略派发等审计失败保持 `partial`，不会因生命周期重分类被改写为成功。运行证据为 `artifacts/runtime/native-full-v4-redacted-trace.json` 与 `artifacts/runtime/native-full-v4-assessment.json`；根因边界见 `artifacts/runtime/native-full-v4-root-cause-diagnosis-v1.json`。

## 11. Provider proposal 与执行尝试分层

v4 证明 Provider 可能无视单工具语义，因此新边界把“模型提出了几个工具调用”和“系统实际执行了几次”拆开。Pi `executionMode=sequential` 决定调用顺序；项目准入状态机决定是否产生副作用。首个合法角色/阶段提议进入 `admitted` 并形成 attempt，已完成角色/阶段的后续提议进入 `coalesced` 并复用 canonical result，违规提议进入 `rejected`，真实失败仍在 attempt ledger 中保持 blocked/failed。

公开结果同时包含 `provider_proposals`、`proposal_summary` 与既有 `attempts`/`ledger`。这既不会隐藏 Provider 重复行为，也不会让重复提议制造第二个 Agent、第二个 MCP service run 或错误的基数失败。bridge v11 的无模型 harness 观察到同角色 2 个 proposal、1 个 admitted attempt、1 个 coalesced；extension v5 对重复短视频分析返回首个 service run，MCP 仍只执行一次。该证据不等于修复后完整一主四专已经真实运行。
