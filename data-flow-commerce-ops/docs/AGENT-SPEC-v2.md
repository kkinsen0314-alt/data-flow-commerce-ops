# Data Flow 电商运营数据分析多 Agent 工作台 Agent Spec v2

## 1. 文档状态

- spec_version: `2.0`
- status: `native_strategy_v1_lifecycle_settled_decision_packet_contract_failed_prompt_repaired`
- workflow_schema: `contracts/commerce-ops-workflow-v1.schema.json`
- synthetic_example: `contracts/synthetic-commerce-workflow-example.json`
- 当前证据：一主四专职责、五工具边界、Pydantic/JSON Schema、跨包引用、Python/FastAPI/stdio MCP、Pi extension、真实 `DefaultResourceLoader` synthetic harness、30-case 评测基础设施、Supervisor + 单个直播专业子 Agent 的严格 synthetic 冒烟，以及历史内容增长 v1—v4 的父级派发、单回合单工具和最终报告契约审计均已在 project017 分层验证。原生内容增长 v1、渠道归因 v1 和策略 v1 又分别通过 `/v1/native` 证明单次有效提交与父子合并账本；三者后续只读复查都回收到 `idle/settled`。策略 v1 同时保留 DecisionPacket 严格契约失败证据。
- 当前不代表：历史内容增长父级调用的每个参数都有精确审计、Plugin 已导入/启用、策略 DecisionPacket 已通过严格契约、完整一主四专已运行、30 条真实模型评测已执行，也不代表真实电商数据或经营效果已经验证。

## 2. 定位与业务目标

项目面向电商运营负责人、内容运营、直播运营、渠道运营和销售转化团队，统一处理以下链路：

`短视频曝光 → 互动点击 → 直播承接 → 线索进入 → 销售跟进 → 订单转化 → 经营复盘`

系统目标不是替代运营人员做最终经营判断，而是把数据范围、确定性指标、诊断证据、行动建议和复验指标组织成可追溯的交付包。证据不足时优先输出 `partial`、`blocked` 或 `uncertain`，不为完整性补造结论。

## 3. 一主四专角色

| 角色 | 职责 | 允许工具 | 明确边界 |
| --- | --- | --- | --- |
| `commerce_ops_supervisor` | 规范目标、生成 `workflow_run_id`、选择专业 Agent、校验数据包并汇总交付 | `tools=[]`，只使用 Pi Subagent 调度工具 | 不直接读取原始数据或计算经营指标；不绕过诊断门槛 |
| `content_growth_analyst` | 检查本任务数据并分析曝光、播放、完播、互动、点击和可关联线索 | `inspect_commerce_data`、`analyze_short_video_data`、`drilldown_commerce_metric` | 不分析直播或销售跟进；无稳定 click key 时不做内容到线索归因 |
| `live_conversion_analyst` | 检查本任务数据并分析观看、停留、互动、点击、留资、下单和成交漏斗 | `inspect_commerce_data`、`analyze_live_commerce_data`、`drilldown_commerce_metric` | 不直接评价销售人员；不使用旧直播测试冒充新电商链路验证 |
| `attribution_lead_analyst` | 检查本任务数据并分析渠道、线索来源、分配、跟进、负责人和订单转化 | `inspect_commerce_data`、`analyze_attribution_and_leads`、`drilldown_commerce_metric` | 只有稳定关联键时才做归因；不因线索数量评价个人能力；无成本字段不算 ROI |
| `commerce_review_strategist` | 读取通过门槛的 `AnalysisPacket`，生成行动、责任岗位、时限、复验指标和护栏 | `tools=[]` | 不读取原始数据；不调用计算工具；不脱离 evidence 生成原因或收益结论 |

角色 allowlist 是项目行为契约。Pi Subagent frontmatter 使用 `ext:<extension>/<tool>` 形成工具范围；直播 v3 已验证专业角色在真实 AgentSession 中只显式调用 inspect 与直播分析，Supervisor 未直接调用业务工具。历史内容增长 v4 已验证父级只派发一次、isolation 省略、专业角色分两个 assistant 回合完成一次 inspect 和一次固定参数短视频分析，但最终回复遗漏父级 Agent 尝试；原生内容增长 v1 已由 `/v1/native` 的项目侧审计证明相同业务链和完整父子账本准确。原生渠道归因 v1 已验证三份跨表 synthetic 数据、稳定关联键、业务 partial、ROI/因果边界、精确前台参数和完整父子账本。策略角色 v1 已真实运行、保持零工具并完成后续 lifecycle 回收，但 DecisionPacket 严格契约失败；修复后的 Prompt 仍需新的模型验收。

Provider proposal 与执行尝试现在是两层状态：父级 `Agent` 和专业业务工具声明 `executionMode=sequential`，Pi 按同一 assistant 响应中的原始顺序逐个执行；首个合法角色/阶段 proposal 进入 admitted 并创建 attempt，已完成同角色/阶段的重复 proposal 进入 coalesced 并复用首个结果，不创建第二次 Agent 或 MCP service run。参数违规和真实失败仍进入 rejected 加 blocked/failed attempt。Supervisor 的最终尝试账本只统计 admitted/rejected 后形成的实际尝试，proposal 汇总由原生 API 单列公开。

## 4. Agent Loop

1. Supervisor 将用户目标规范为 `CommerceOpsRunRequest`，生成唯一 `workflow_run_id`。
2. Supervisor 只为 `requested_domains` 中的必要领域创建专业任务；互不依赖的内容、直播和渠道诊断可以并行。project017 不是 Git 仓库，调用 `Agent` 必须完全省略 `isolation`；任一父级参数校验或派发失败都计入尝试并使当前分支立即 `blocked`，同一会话不得第二次调用 `Agent` 掩盖失败。
3. 每个专业 Agent 在自己的 MCP 进程内只允许一次 `inspect_commerce_data` 尝试，只登记本任务需要的数据集，并检查字段、质量、稳定关联键、成本字段和可用维度。inspect 根对象只允许 `workflow_run_id`、`caller_role`、`data_refs`、`requested_domains` 和可选 `max_rows_for_profile`；`synthetic=true` 只能位于各 `data_refs[]` 项内，禁止作为根字段。Schema 参数校验失败也计为一次工具尝试，当前分支必须返回 `blocked`，不得主动第二次调用 inspect。
4. 专业 Agent 只有在 manifest 通过门槛后才能调用本域分析与受限钻取工具，输出 `AnalysisPacket`，并保留 `analysis_run_id`、`service_run_id`、evidence、finding、missing_evidence 和 terminal_status。
5. Supervisor 校验：Schema、角色/领域、工具调用者、全部工具尝试及顺序、run_id、dataset 引用、evidence→finding 关系、synthetic 和数据质量边界。最终尝试账本必须合并父级 `Agent` 派发与子级业务工具；失败尝试必须计入总次数，全部可用 `service_run_id` 均需保留；成功调用数不能冒充总尝试数。
6. 只有 `completed` 或 `partial` 的诊断包可以进入策略阶段；`blocked` 或 `uncertain` 不能作为策略输入。
7. `commerce_review_strategist` 仅根据通过门槛的诊断包生成 `DecisionPacket`，每条 action 必须引用 finding 和 evidence，并携带 `verification_metric` 与 guardrail。
8. Supervisor 校验 action→finding→evidence 引用，生成 `DeliveryPackage`；未解决问题原样进入 `unresolved_items`。

## 5. 路由与门槛

### 数据检查门槛

- 数据集必须声明类型、字段、SHA-256、synthetic、数据质量和脱敏状态。
- `contains_sensitive_data=true` 时必须同时满足 `redaction_applied=true`。
- 数据质量为 `blocked` 时，不得调用对应分析工具。
- 用户没有请求的业务域不得自动扩展分析范围。

### 归因门槛

- 跨短视频、直播、线索和订单的归因必须存在 `stable=true` 且覆盖率大于 0 的脱敏关联键。
- 未关联记录必须单列为 missing evidence，不能强行进入归因分母。
- 关联键覆盖率只能说明可关联范围，不能证明因果关系。

### ROI 门槛

- 至少一个数据集必须存在 `semantic_role=cost` 的成本字段。
- 数据检查必须把 `roi_calculation` 标记为 `allowed`。
- 任一条件缺失时，ROI evidence 和需要成本数据的 verification metric 都必须被确定性校验拒绝。

### 策略门槛

- 只接受 `completed` 或 `partial` AnalysisPacket。
- action 必须引用实际存在的 finding 与 evidence。
- verification metric 必须指向现有 dataset，并说明方向、基线、目标、复验时间和方法。
- 策略 Agent 不得把 limitation、assumption 或 missing_evidence 改写成事实。
- DecisionPacket 必须精确遵守 Pydantic/JSON Schema 的固定字面值、ID 模式、字段类型、非空引用和 `additionalProperties=false`；未通过 `DecisionPacket.model_validate()` 不得进入交付阶段。

## 6. 上下文策略

- Supervisor 保留请求、manifest、路由状态和结构化包，不把所有原始行复制进主上下文。
- 专业 Agent 只获得所需 manifest、业务目标、允许维度和自身领域数据引用。
- 策略 Agent 只获得通过校验的 AnalysisPacket，不获得原始文件路径或个人明细。
- DeliveryPackage 只引用聚合 evidence、finding、action、trace 和未解决事项。
- 阶段 5 的轨迹模板和执行器已要求记录 Prompt、模型、工具说明、上下文策略和代码版本；直播 v3、历史内容增长 v1—v4、原生内容增长 v1 与原生渠道归因 v1 已有独立脱敏运行记录，但尚未形成 30-case baseline/candidate 版本记录。原生运行未采集模型请求数、token 或准确成本，这些值保持 `null/unknown`。

## 7. terminal_status

| 状态 | 含义 | 行为 |
| --- | --- | --- |
| `completed` | 当前请求范围内的必需证据和诊断可用 | 可进入下一阶段 |
| `partial` | 保留了可验证事实，但存在缺失维度、未关联记录或其他限制 | 可以受限进入策略阶段，限制必须进入交付包 |
| `blocked` | 缺少必需数据、字段、权限或关联条件 | 停止该分支，不生成经营 finding |
| `uncertain` | 调用可能已经执行但结果无法确认 | 禁止自动重跑，先按 run_id 核对 |

## 8. 不能回答或执行

- 无 evidence 的经营原因、责任归因、趋势预测或收益承诺。
- 缺稳定关联键时的跨域归因，缺成本字段时的 ROI。
- 把 synthetic 数值写成真实账号、渠道、直播或订单表现。
- 输出手机号、原始订单号、身份信息、Provider Key 或本机敏感路径。
- 修改 CRM、订单、线索、工单、权限、Provider、Plugin、Workspace 或业务规则。
- 根据线索数量、成交数量等单一指标评价销售个人能力。
- 把 MiniClaw 平台数据库、队列、认证、Catalog 或 Runtime 描述为个人从零研发成果。

## 9. 失败回复要求

失败或降级回复必须包含：

- `terminal_status`
- 所有父级 `Agent` 与子级业务工具尝试、实际顺序、总尝试次数和失败原因；Schema 校验失败也算一次尝试
- 已完成事实
- 缺失证据或失败点
- 可能的副作用
- 是否自动重试及原因
- transport 自动重试与模型主动重新调用的区分
- 用户或管理员下一步
- `workflow_run_id`、全部可用 `service_run_id` 与 `analysis_run_id`；未生成的 run_id 标为不可用

结果不确定时必须说明“为什么没有重试”，不得只返回“失败了”。

## 10. 质量门槛

硬门槛：

1. JSON Schema 与 Pydantic 模型合法。
2. workflow/analysis/service/evidence/finding/action 引用可追溯。
3. 角色、领域、工具调用者和 allowlist 一致。
4. finding 至少引用一条 evidence，action 引用 finding 与 evidence。
5. 事实、限制、假设和 missing evidence 分开。
6. 归因与 ROI 门槛被确定性执行。
7. synthetic、数据质量、敏感字段和失败状态保真。
8. 没有越权工具、盲目重试、凭据泄露或经营效果冒领。

当前完成契约、行为 Spec、无模型确定性工具层、Pi extension 注册、同版本 Pi Loader synthetic harness、30-case 离线评测基础设施，以及分层真实模型 synthetic 冒烟。原生内容增长与渠道归因的业务和合并账本通过。策略 v1 已真实执行并遵守两次父级前台派发与零工具边界，后续生命周期也回收到 `idle/settled`；但完整 DecisionPacket 有 20 个 Pydantic 错误，严格契约失败。角色 Prompt 已无模型修复并通过静态与契约检查，尚未模型复验。当前仍未覆盖完整一主四专、失败恢复或正式 30-case。H01—H12 中 H09、H10、H12 语义项仍须由人工或 Judge 记录；fixture preflight 和执行器测试不形成 Agent 通过率。
