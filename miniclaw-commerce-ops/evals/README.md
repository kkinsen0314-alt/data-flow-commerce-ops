# 电商运营 Agent 评测资产

## 当前状态

- 数据集：`authored_partially_executed`
- 评测执行器：`deterministic_executor_implemented`
- fixture：仅用于输入与失败语义预检
- Provider / AgentSession / 真实模型：`B01_executed_5_of_30`
- Plugin：`not_imported_or_enabled`
- LLM-as-Judge：`not_configured`
- 真实评测轨迹：`5/30`
- 真实运行计划：`B01_completed_B02_to_B06_not_authorized`
- 质量发布：`blocked_without_real_baseline_candidate`

本目录建立 30 条电商运营多 Agent 评测用例、H01—H12 评分规则、单条轨迹模板和 baseline/candidate 回归模板。预检、评分和比较命令都不会创建 MiniClaw AgentSession，也不会调用模型。

## 用例分布

| 类别 | 数量 | 重点 |
| --- | ---: | --- |
| normal | 10 | 三个专业域、双域、一主四专、受限钻取 |
| boundary | 6 | 上限、重复 ID、超限、格式、范围和维度边界 |
| data_missing | 6 | 缺指标、缺订单、缺关联键、缺成本、缺跟进、缺映射 |
| adversarial | 4 | 越权、synthetic 冒充、uncertain 重试、人员归责 |
| refusal | 4 | 凭据、平台配置、外部写入和个人明细 |

## 离线命令

```powershell
python -B scripts\run-commerce-ops-evals.py preflight
python -B scripts\run-commerce-ops-evals.py score --traces <脱敏轨迹.json> --output <评测结果.json> --run-label baseline --executed-by <执行人>
python -B scripts\run-commerce-ops-evals.py compare --baseline <baseline.json> --candidate <candidate.json> --output <回归报告.json>
python -B scripts\verify-evaluation-delivery-readiness.py
```

- `preflight`：只检查评测集、契约引用和 fixture；不能说明 Agent 通过。
- `score`：只评分外部运行器提供的脱敏轨迹；缺轨迹的用例记为 `not_run`。
- `compare`：只比较已有的两轮评测记录；数据集或 fixture 指纹不同会阻塞比较。
- `verify-evaluation-delivery-readiness`：核对 6 批次计划、真实评测证据与 GitHub 预览缺口；不运行模型或发布 GitHub。

真实批次使用独立入口，缺少最后一个显式开关时只预览计划，不调用模型：

```powershell
python -B scripts\run-native-eval-batch.py --batch B01 --max-budget-cny 10 --authorized-by <授权标识>
```

只有获得该命名批次的 Provider、模型、价格与最高预算授权后，才能追加 `--execute-authorized-model-batch`。运行器每条用例使用独立 Session、只 POST 一次并串行只读轮询；余额不足、提交不确定、`blocked` 或 `uncertain` 会立即停批，不自动续跑或重试。

## 轨迹要求

每条轨迹至少记录 route、terminal_status、dispatched_agents、工具调用顺序、actor、脱敏参数、结果状态、错误码、工具耗时、workflow/analysis/service run_id、DatasetManifest、evidence、finding、action、Prompt/模型/工具说明/上下文策略版本、token、估算成本和端到端延迟。

没有采集到的 token、成本或延迟必须使用 `null`，并在 `unavailable_metric_reasons` 说明原因；不能用 `0` 代替未知值。

H09、H10 和 H12 的语义结论必须由人工或 Judge 写入同一份结构化复核记录。记录必须包含复核类型、复核标识、带时区时间和覆盖门槛；LLM Judge 还必须记录 Provider、模型 ID 和 Judge Prompt SHA-256。执行器只验证这份复核记录是否完整，不用关键词命中或无来源布尔值冒充最终语义通过。

30 条真实运行按 `real-run-plan-v1.json` 拆成 6 个批次、每批最多 6 条。计划本身不授权模型调用；每个命名批次都要单独确认 Provider/模型、当日价格来源、最高预算和授权时间，批次之间不自动续跑。

## 证据边界

- fixture preflight 通过，只证明评测输入可用。
- 执行器单元测试通过，只证明评分与回归逻辑可运行。
- synthetic 工具数据不能写成真实经营结果。
- 只有实际 AgentSession 轨迹才能形成 Agent 评测结论。
- MiniClaw 平台能力、project014 和 project015 的历史证据不能直接算作 project017 的 Agent 运行证据。
- 完整一主四专 v7 是专项运行验收，不是这 30 条数据集的 baseline/candidate。
- 2026-09-12 B01 已形成 5 条真实脱敏轨迹和一个部分 baseline；自动门禁 0/5 通过，H09/H10/H12 仍为 0/5 待复核，不能标记“已评测正式版”。2026-09-11 source preview 是 B01 前 0/30 快照，发布前必须重建。
