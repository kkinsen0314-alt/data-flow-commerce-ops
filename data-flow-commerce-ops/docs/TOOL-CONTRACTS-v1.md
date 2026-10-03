# 电商运营五工具契约 v1

## 文档状态

- status: `deterministic_tools_and_live_specialist_synthetic_runtime_validated`
- 当前阶段：工具名称、角色、参数、返回、幂等性、副作用、重试和隐私边界已定义；Python/Pandas、FastAPI、stdio MCP、Pi ToolDefinition 和真实 `DefaultResourceLoader` harness 已在 project017 synthetic fixtures 上分层调用。
- 运行证据：v3 中 Supervisor 真实派发 `live_conversion_analyst`，该角色按 inspect→analyze 调用两个 project017 业务工具；其余角色、Plugin 和完整一主四专尚未运行。

## 通用规则

所有工具都必须：

- 接收并原样返回 `workflow_run_id`。
- 为每次调用生成唯一 `service_run_id`。
- 返回 `completed / partial / blocked / uncertain` 之一。
- 标明 `synthetic`、数据质量、调用者、耗时和可能副作用。
- 只返回聚合结果和脱敏引用，不返回原始个人明细。
- 结果不确定时禁止自动重跑；先按 run_id 和日志核对。
- 运行报告必须列出所有工具尝试和全部可用 `service_run_id`；Schema 参数校验失败同样计入总尝试次数，不能只统计成功调用。
- transport 自动重试与模型主动重新调用必须分开记录；当前 Pi 桥接声明 `automaticRetry=false`。

## 角色 allowlist

| 角色 | inspect | short video | live | attribution/leads | drilldown |
| --- | --- | --- | --- | --- | --- |
| `commerce_ops_supervisor` | 禁止 | 禁止 | 禁止 | 禁止 | 禁止 |
| `content_growth_analyst` | 允许 | 允许 | 禁止 | 禁止 | 允许 |
| `live_conversion_analyst` | 允许 | 禁止 | 允许 | 禁止 | 允许 |
| `attribution_lead_analyst` | 允许 | 禁止 | 禁止 | 允许 | 允许 |
| `commerce_review_strategist` | 禁止 | 禁止 | 禁止 | 禁止 | 禁止 |

## 1. inspect_commerce_data

### 用途

检查数据类型、字段、SHA-256、数据质量、脱敏状态、关联键、成本字段和可用维度，生成 `DatasetManifest[]`。不产生经营 finding。

### 调用者

三个专业 Agent。每个角色只能在自己的 MCP 进程内登记当前任务所需的数据集，并必须显式传入自身 `caller_role`；Supervisor 不直接调用业务工具。

### 参数

根对象采用 `additionalProperties=false`，只允许：

- `workflow_run_id`
- `caller_role`：`content_growth_analyst|live_conversion_analyst|attribution_lead_analyst`。
- `data_refs[]`：受限文件引用、声明的数据类型和 synthetic；`synthetic=true` 只能位于每个数组项内。
- `requested_domains[]`
- `max_rows_for_profile`：可选，只控制结构检查采样，不改变经营指标计算范围。

根对象禁止 `synthetic`。若模型传入顶层 `synthetic` 或其他未声明字段，Schema 参数校验失败也计为一次 inspect 尝试；专业 Agent 必须停止当前分支并返回 `blocked`，不得通过第二次 inspect 隐藏失败尝试。

### 成功返回

- `terminal_status=completed|partial`
- `dataset_manifests[]`
- `service_run_id`
- `missing_evidence[]`

### 失败返回

- `INVALID_INPUT`
- `PAYLOAD_TOO_LARGE`
- `RELATION_KEY_MISSING`
- `COST_FIELD_MISSING` 只阻塞 ROI，不一定阻塞其他分析

### 执行属性

- 幂等性：相同文件 SHA-256 与参数下应为幂等。
- 副作用：无，默认只读。
- 自动重试：当前 Pi 桥接 `automaticRetry=false`；专业 Agent 不主动第二次调用。若未来 transport 层增加“明确未进入读取逻辑”的自动重试，必须与模型工具尝试分开记录；结果不确定时仍禁止。
- 隐私：只输出字段名、聚合质量和脱敏关联键描述。

## 2. analyze_short_video_data

### 用途

分析曝光、播放、完播、互动、点击和可关联线索，支持账号、内容和发布时间维度。

### 调用者

仅 `content_growth_analyst`。

### 参数

- `workflow_run_id`
- `dataset_ids[]`：必须指向 `short_video`，可选 `account` 和具有稳定 click key 的 `channel_lead`。
- `requested_dimensions[]`：`account|content|publish_time`。
- `top_n`：1—50。
- `synthetic`

### 成功返回

统一 `AnalysisPacket`，domain 固定为 `content_growth`。

### 失败与边界

- 缺曝光/点击等基础字段时 `blocked`。
- 缺稳定 click key 时可以完成内容内部分析，但内容到线索归因必须 `blocked` 或从结果中移除。
- 不读取直播、销售跟进或成本字段。

### 执行属性

- 幂等性：只读确定性计算，参数与数据相同时应幂等。
- 副作用：无。
- 自动重试：明确的读取前失败最多一次；uncertain 不重试。

## 3. analyze_live_commerce_data

### 用途

分析观看、停留、互动、商品点击、留资、下单和成交漏斗，并支持账号、场次和渠道维度。

### 调用者

仅 `live_conversion_analyst`。

### 参数

- `workflow_run_id`
- `dataset_ids[]`：必须包含 `live_session`，可选 `account` 和可关联 `channel_lead/order`。
- `requested_dimensions[]`：`account|live_session|channel`。
- `top_n`：1—50。
- `synthetic`

### 成功返回

统一 `AnalysisPacket`，domain 固定为 `live_conversion`。

### 失败与边界

- 复用直播漏斗计算思想，但不能直接继承 project015 的测试或运行结论。
- 缺某个后链路字段时允许返回 `partial`，保留已完成漏斗事实。
- 不自行评价销售人员，也不把直播相关性写成订单因果。

### 执行属性

- 幂等性：目标实现为只读幂等。
- 副作用：无。
- 自动重试：读取前明确失败最多一次；uncertain 不重试。

## 4. analyze_attribution_and_leads

### 用途

分析渠道、线索来源、分配、首次跟进、跟进次数、积压、订单覆盖和转化。

### 调用者

仅 `attribution_lead_analyst`。

### 参数

- `workflow_run_id`
- `dataset_ids[]`：`channel_lead` 为核心，可选 `sales_followup`、`order`、`short_video`、`live_session`。
- `requested_dimensions[]`：`channel|lead_source|sales_owner|order_status`。
- `link_orders`：是否请求订单关联。
- `calculate_roi`：是否请求 ROI；默认 false。
- `top_n`：1—50。
- `synthetic`

### 成功返回

统一 `AnalysisPacket`，domain 固定为 `attribution_leads`。

### 强制门槛

- `link_orders=true` 时必须有稳定脱敏关联键和覆盖率；否则返回 `RELATION_KEY_MISSING`，不能模糊匹配后继续。
- `calculate_roi=true` 时必须存在成本字段且 manifest 明确允许；否则返回 `COST_FIELD_MISSING`。
- 销售负责人维度只描述分配、跟进和转化聚合，不能据此评价个人能力。

### 执行属性

- 幂等性：目标实现为只读幂等。
- 副作用：无。
- 自动重试：读取前明确失败最多一次；任何关联结果不确定时不重试。

## 5. drilldown_commerce_metric

### 用途

对已经完成的基础分析进行受限维度钻取。不能替代基础分析，也不能扩大数据权限。

### 调用者

三个专业 Agent；调用者必须与 `base_analysis_run_id` 的 Agent role 一致。

### 参数

- `workflow_run_id`
- `base_analysis_run_id`
- `evidence_id`
- `dimension`：必须属于对应 manifest 的 `available_dimensions`。
- `filters`：白名单字段与值。
- `top_n`：1—50。
- `synthetic`

### 成功返回

- 新 `service_run_id`
- 钻取维度、聚合 rows、数据质量和 source evidence 引用
- 不能创建脱离 base evidence 的新归因结论

### 失败与边界

- base analysis 不存在、未完成或调用者不一致时 `blocked`。
- 未声明维度、越权过滤、尝试读取原始明细时 `INVALID_INPUT`。
- 不能通过 drilldown 绕过关联键或 ROI 门槛。

### 执行属性

- 幂等性：只读幂等。
- 副作用：无。
- 自动重试：读取前明确失败最多一次；uncertain 不重试。

## 当前证据边界

本文件已由阶段 3 确定性实现、阶段 4 Pi 适配和阶段 6 单专业运行冒烟承接。FastAPI ASGI、官方 MCP Client stdio、Pi extension API harness 与真实 `DefaultResourceLoader` harness 的结果见 `artifacts/tool-layer-validation-v1.json`、`artifacts/pi-extension-runtime-v1.json` 和 `artifacts/pi-default-resource-loader-v1.json`；真实 Agent 调用另见 v3 脱敏轨迹与评估。v3 只证明直播专业子 Agent 的 inspect/analyze 链路，不证明 Plugin 已启用、其他角色、一主四专、30-case 或真实经营效果。
