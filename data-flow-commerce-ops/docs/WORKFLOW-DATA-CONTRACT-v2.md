# 电商运营 Workflow 数据契约 v2

## 文档状态

- status: `project017_contract_implemented_tested_and_live_specialist_runtime_exercised`
- schema: `contracts/commerce-ops-workflow-v1.schema.json`
- sample: `contracts/synthetic-commerce-workflow-example.json`
- models: `commerce_ops/models.py`
- validator: `commerce_ops/contracts.py`
- 当前验证：JSON Schema、Pydantic 模型、跨包引用、敏感标记、归因门槛和 ROI 门槛已建立；确定性工具已在 synthetic fixtures 上实际生成对应消息包，v3 还由直播专业子 Agent 真实生成 DatasetManifest、AnalysisPacket 和 evidence→finding 链。

## 核心消息包

### CommerceOpsRunRequest

包含目标、数据集引用、请求领域、请求维度、时间范围、交付要求、约束和 synthetic 状态。每个闭环只能有一个 `workflow_run_id`。

### DatasetManifest

由 `inspect_commerce_data` 产生，记录：

- 数据集类型、来源名、SHA-256 和 synthetic。
- 字段类型、语义角色和可空性。
- 可用分析维度。
- 稳定关联键、覆盖率、目标数据类型和脱敏状态。
- 行数、重复行、缺失必需字段和质量状态。
- 是否允许跨域归因与 ROI 计算及其原因。

Manifest 只描述数据能否分析，不输出经营结论。

### AnalysisPacket

三个专业 Agent 的统一输出。包含 agent role、domain、terminal status、dataset 引用、工具调用、evidence、finding、missing evidence 和 assumptions。

约束：

- Agent 角色必须与 domain 匹配。
- 工具调用者和工具名必须符合角色 allowlist。
- evidence 必须关联成功的 `service_run_id`。
- finding 必须引用当前 packet 中存在的 evidence。
- `blocked/uncertain` 不能输出经营 finding。

### DecisionPacket

只允许 `commerce_review_strategist` 生成。每条 action 包含 finding/evidence 引用、责任岗位、时限、理由、复验指标、护栏和置信度。

`blocked/uncertain` AnalysisPacket 不能进入 `source_analysis_ids`。

### DeliveryPackage

由 Supervisor 汇总，包含 analysis/decision/finding/action/trace 引用、摘要、未解决事项和人工确认标志。`partial`、`blocked` 或 `uncertain` 必须保留未解决事项或人工确认。

## canonical 数据域

| dataset_type | 关键字段示例 | 主要用途 | 边界 |
| --- | --- | --- | --- |
| `short_video` | `content_id_hash`、`account_id_hash`、`published_at`、`impressions`、`plays`、`completions`、`interactions`、`clicks`、可选 `click_id_hash` | 内容曝光、播放、完播、互动和点击诊断 | 没有 click key 时不连接线索 |
| `live_session` | `live_session_id_hash`、`account_id_hash`、`started_at`、`viewers`、`watch_seconds`、`interactions`、`product_clicks`、`leads`、`orders` | 直播观看至成交漏斗 | 不把旧直播结果直接继承为新项目证据 |
| `account` | `account_id_hash`、`platform`、`account_group`、`active_from` | 账号口径和跨内容/直播聚合 | 账号标识必须脱敏 |
| `channel_lead` | `lead_id_hash`、`click_id_hash`、`channel`、`lead_source`、`created_at`、`sales_owner_id_hash`、`lead_stage` | 渠道、来源、分配和线索结构 | 不根据线索量评价个人能力 |
| `sales_followup` | `lead_id_hash`、`sales_owner_id_hash`、`assigned_at`、`first_followup_at`、`followup_count`、`followup_status` | 跟进及时性和积压分析 | 缺跟进记录要进入 missing evidence |
| `order` | `order_id_hash`、可选 `lead_id_hash`、`ordered_at`、`paid_at`、`paid_amount`、`order_status`、可选成本字段 | 订单转化与覆盖范围内归因 | 无 lead key 不归因，无成本字段不算 ROI |

canonical 字段是项目契约，不等于已经接入真实业务表。真实字段映射、口径和权限必须单独确认。

## 语义角色

字段通过 `semantic_role` 区分：

- `metric`：确定性指标计算输入。
- `dimension`：受限钻取维度。
- `relationship_key`：跨表或同实体连接键。
- `timestamp`：时间范围和时效计算。
- `cost`：ROI 或成本类计算的必需输入。
- `identifier`：仅用于数据集内部唯一性，不自动具备跨域关联资格。

## run_id 与证据链

```text
workflow_run_id
  → analysis_run_id
    → service_run_id
      → evidence_id
        → finding_id
          → action_id
            → verification_metric
```

- `workflow_run_id`：一次完整业务请求。
- `analysis_run_id`：一个专业 Agent 的一次诊断。
- `service_run_id`：一个确定性工具调用。
- evidence 只能引用成功的 service call。
- finding 只能引用当前 analysis packet 的 evidence。
- action 可以引用多个 analysis packet 的 finding/evidence，但必须在 bundle 中实际存在。
- DeliveryPackage 只保存引用，不复制原始明细。

## 归因规则

跨域 attribution 同时要求：

1. 存在 `stable=true` 的关联键。
2. `coverage_ratio > 0`。
3. 关联键对敏感实体已脱敏。
4. 至少一个相关 manifest 的 `cross_domain_attribution=allowed`。
5. 未覆盖记录单独报告，不进入可归因分母。

满足这些条件只允许做覆盖范围内的关联分析，不自动证明因果关系。

## ROI 规则

ROI evidence 或 `requires_cost_data=true` 的复验指标同时要求：

1. 至少一个 manifest 存在 `semantic_role=cost` 字段。
2. 至少一个 manifest 的 `roi_calculation=allowed`。

任一条件缺失，Pydantic 跨包校验直接拒绝，不由 LLM 自由决定。

## terminal_status

- `completed`：所需证据与 finding 可用。
- `partial`：存在可交付事实，也存在限制或 missing evidence。
- `blocked`：缺必需数据、字段、权限或稳定关联条件。
- `uncertain`：调用结果可能已产生但无法确认；禁止自动重跑。

## 数据安全

- 原始手机号、身份证号、订单号、线索号、Key、Token 和 Authorization 不进入合成契约样例或交付包。
- 敏感实体的稳定关联键必须使用脱敏值。
- `contains_sensitive_data=true` 必须同时声明 `redaction_applied=true`。
- 默认只读，不向 CRM、订单、线索或工单系统写入。
- synthetic 始终显式保留，不转换成真实经营结果。

## 当前验证边界

阶段 2 的测试证明 Schema、模型和引用规则在 synthetic bundle 上一致；阶段 3 证明五工具、FastAPI 和 stdio MCP 可以在 project017 synthetic fixtures 上运行；v3 脱敏轨迹进一步证明 Supervisor 已真实派发直播专业子 Agent，并按 inspect→analyze 生成可追溯链路。v3 不证明其他角色、策略包、DeliveryPackage、完整一主四专、30-case 或真实经营效果。
