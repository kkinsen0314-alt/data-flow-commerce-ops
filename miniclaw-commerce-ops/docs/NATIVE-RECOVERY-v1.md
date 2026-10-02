# MiniClaw 原生任务失败恢复 v1

## 目标与边界

本契约规定原生任务在运行中、阻断、结果不确定、部分完成和运营结果不可用时，运营人员与管理员可以做什么、禁止做什么。恢复判断只读取持久化运行状态和严格运营投影，不解析原始模型文本，不启动 Host，不提交任务，也不调用模型。

所有场景统一遵守以下底线：

- 禁止自动重试模型或自动新建替代任务。
- 禁止用变更后的请求复用旧幂等键。
- 禁止改写历史审计或失败证据。
- 禁止向运营页面暴露原始模型输出、内部 ID、Agent/工具账本或凭据。
- 当前项目仍是只读分析系统，恢复动作不能写入外部经营系统。

## 恢复判定矩阵

| 场景 | 识别状态 | 允许动作 | 新任务规则 |
|---|---|---|---|
| 运行中观察 | 未结算，运营视图为 `processing` | 只读查询同一任务和任务目录 | 原任务未结算前禁止替代任务 |
| 预检阻断 | `blocked + not_attempted` | 检查配置，修正输入，再由运营人员确认 | 修正和重新授权后使用新幂等键 |
| 提交结果不确定 | `submission_state=uncertain` 或终态 `uncertain` | 查询同一任务、查看脱敏审计、升级管理员 | 原任务结果确认前禁止替代任务 |
| 执行阻断 | `blocked` 且已尝试提交 | 查看脱敏审计、修正根因、人工复核 | 修正和重新授权后使用新幂等键 |
| 部分结果待复核 | `partial + needs_review` | 先阅读限制和缺失项，再决定是否补充分析 | 仅在确有需要且重新授权后创建范围明确的新任务 |
| 运营投影不可用 | 已结算但运营视图为 `unavailable` | 管理员检查脱敏审计并修正投影契约 | 不得用原始文本兜底；重跑仍需新授权和新幂等键 |
| 正常完成 | `completed + ready` | 直接使用已校验结果 | 无需恢复或重跑 |

其中“同一任务”是现有持久化记录，不是重新提交同一请求。只读刷新允许更新该记录的观测状态，但不能创建 Session、发送消息或改变幂等身份。

## 运营人员处理清单

1. 先在“当前任务”或“历史任务”中打开原任务，不要重复点击创建任务。
2. 如果页面显示处理中，继续查看当前任务；不要新建相同任务。
3. 如果页面显示状态无法确认，保留 12 位任务参考号并联系管理员；在管理员确认前不要重提。
4. 如果显示部分结果，先阅读“使用边界”和缺失项；只有补充分析确有必要时才创建新任务。
5. 如果显示结果不可用，只提交任务参考号给管理员，不复制浏览器外的内部日志或模型原文。
6. 任何新任务都必须重新确认模型费用，并由页面生成新的幂等键。

## 管理员处理清单

1. 使用持久化原生记录核对 `phase`、`submission_state`、`terminal_status` 和安全运营投影。
2. 对不确定态只观察同一记录和脱敏审计；不得通过再次 POST 来“试一试”。
3. 对预检阻断检查 Host/Workspace/Profile 就绪状态和数据输入范围；未通过预检不得提交。
4. 对执行阻断只定位明确失败点，保留原记录和原审计，不重写为通过。
5. 对投影不可用修正 `operator_result` 结构或投影校验，绝不回退展示 `final_response`。
6. 需要重跑时，先完成根因修正，再取得运营人员新的费用授权，最后使用新幂等键创建新任务。
7. 确认恢复结束后检查 3017、3022 和临时验收端口没有遗留监听进程。

## 机器契约与验证入口

- 生产恢复策略：`commerce_ops/native_recovery.py`
- 恢复场景目录：`contracts/native-recovery-cases-v1.json`
- 单元测试：`tests/test_native_recovery.py`
- 验证器：`scripts/verify-native-recovery.py`
- 验证证据：`artifacts/native-recovery-validation-v1.json`

在项目根目录运行：

```powershell
python -B scripts/verify-native-recovery.py
python -B -m unittest discover -s tests -p "test_*.py" -v
```

第一条命令应返回 `status=pass` 和 `cases=8/8`。它只读取恢复目录、调用生产恢复规划器并写入 JSON 验证证据；不会启动 MiniClaw Host/API、读取 Provider 凭据、创建 Session、发送消息、调用模型或触发自动重试。

## 恢复计划合同

`NativeRecoveryPlan` 对每个状态输出：

- `scenario`：标准恢复场景。
- `automatic_retry_allowed`：固定为 `false`。
- `same_run_observation_required`：是否必须继续观察原任务。
- `new_run_policy`：新任务是禁止、修正后允许、复核后可选，还是完全不需要。
- `allowed_steps` / `forbidden_steps`：机器可验证的允许与禁止动作。
- `resolution_gate`：退出当前恢复状态前必须满足的条件。
- `operator_message`：不含内部身份与模型原文的运营提示。

生产适配器 `build_native_recovery_plan(record)` 会先通过既有安全投影得到运营视图，再基于四个状态字段生成计划。已完成但缺少合格 `operator_result` 的记录会进入“运营投影不可用”，不会被误判为可直接使用。
