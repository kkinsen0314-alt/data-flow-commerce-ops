# Data Flow 原生运行模式 v1

2026-09-20 更新：Data Flow `/operations/*` 已接通认证后的业务接口；当前操作、鉴权和无付费验收入口见 `DATA-FLOW-AUTHENTICATED-API-v1.md`。下文 `/v1/native` 保留为可信本机脚本接口，旧浏览器入口 `/native` 已跳转到 MiniClaw Host 的认证运营工作区。

## 结论

project017 已具备前后端一体的 MiniClaw 原生运行入口。Data Flow Web 复用 MiniClaw Host 的本地账户认证、AuthGuard、路由和管理页面；project017 后端继续通过 Workspace、AgentProfile、Session 和消息接口启动真实 Supervisor，不经过 `/demo`，也不把业务编排交给浏览器。

截至 2026-09-10，代码、契约、持久化幂等、无自动重试、父子尝试账本、审计权威结果、敏感字段脱敏、本机 Host 启动和正式运营后台均已完成分层验证。完整 v7 已以固定请求只 POST 一次并严格通过；历史 v4/v5/v6 失败证据保持不变。运营后台现支持逐次费用确认、单次提交、只读轮询、严格经营结果、任务记录与结果重开；失败恢复已形成 8 场景确定性生产策略和离线验证入口。任何新模型运行仍需新的范围与费用授权。

## 固定架构

```text
本机调用方
  -> project017 FastAPI /v1/native
  -> MiniClaw Host API :3017
  -> project017 Workspace + AgentProfile
  -> Supervisor Session
  -> project-local Subagent compatibility bridge
  -> 专业 Agent
  -> project-local commerce-ops Pi extension
  -> Python stdio MCP 五工具
  -> runtime/data/native-audit 脱敏父子账本
  -> GET /v1/native/runs/{workflow_run_id} 确定性对账
  -> GET /v1/native/runs/{workflow_run_id}/result 运营结果投影
  -> GET /v1/native/tasks 运营任务目录
  -> GET /v1/native/tasks/{task_reference}/result 历史结果重开
```

平台来源固定为 `project014-miniclaw-deployment/upstream/miniclaw` 的 `main@3ff1c8d6a0707f4a9f0957ff411758e5e141583a`。project017 当前正式运行来源是项目本地 Pi extension 与 compatibility bridge，不依赖 Plugin Catalog 导入。

## MiniClaw Host 接口

project017 只调用锁定平台中已核对的真实接口：

- `POST /api/auth/login` 或 `GET /api/auth/me`
- `GET /api/groups`
- `GET /api/agent-profiles`
- `GET /api/groups/{workspace_jid}/sessions`
- `POST /api/groups/{workspace_jid}/sessions`
- `GET /api/groups/{workspace_jid}/messages?agentId={session_id}`
- `POST /api/messages`

认证信息只存在于 project017 后端进程环境和服务端 HTTP Client，不写进请求响应、运行记录、审计 JSONL、文档或前端存储。

## 服务端配置

先启动隔离 MiniClaw Host。下面的 `<miniclaw-entry>` 指向已构建的 MiniClaw `dist/index.js`，不要把凭据写入命令或仓库：

```powershell
$env:WEB_PORT = '3017'
$env:TZ = 'Asia/Shanghai'
Start-Process -FilePath 'node.exe' `
  -ArgumentList @('<miniclaw-entry>') `
  -WorkingDirectory '<project-root>\runtime' `
  -WindowStyle Hidden
```

再在仅当前终端有效的环境变量中配置原生后端。不要把真实值写入仓库或聊天记录：

```powershell
$env:MINICLAW_BASE_URL = 'http://127.0.0.1:3017'
$env:MINICLAW_WORKSPACE_JID = '<project017 workspace jid>'
$env:MINICLAW_USERNAME = '<local username>'
$env:MINICLAW_PASSWORD = '<local password>'

cd <project-root>
python -m uvicorn commerce_ops.app:app --host 127.0.0.1 --port 3022
```

推荐直接使用安全启动脚本。它要求 PowerShell 7，会在本机终端隐藏输入密码、先验证登录并自动定位 project017 Workspace，再使用临时 Session Cookie 启动后端；不会把密码写入文件，也不会提交模型任务：

```powershell
cd <project-root>
pwsh -ExecutionPolicy Bypass -File scripts\start-native-runtime.ps1 `
  -MiniClawEntry '<miniclaw-entry>'
```

`-MiniClawEntry` 也可以由当前进程的 `MINICLAW_ENTRY` 提供；本地开发环境若存在同级 `project014-miniclaw-deployment`，脚本会尝试自动发现。Workspace 自动定位不唯一时可追加 `-WorkspaceJid '<project017 workspace jid>'`。脚本只把临时 Cookie 注入 API 子进程环境，登录用户名、密码和 Cookie 都不写入项目文件、运行记录或 artifact。

脚本启动 Host 前会运行 `scripts/build-data-flow-web.mjs`，将 Data Flow 页面与锁定 MiniClaw 前端组合构建到 `runtime/web/dist`。新安装会自动创建项目自己的生成目录；当前开发机已有的 `runtime/web` 是指向上游 `web` 的目录联接，因此构建更新同一份生成资产，不修改上游源码。启动后浏览器入口为：

- `http://127.0.0.1:3017/login`：Data Flow 原生登录页。
- `http://127.0.0.1:3017/operations`：登录后的运营工作台。
- `http://127.0.0.1:3017/operations/analysis`：新建分析与执行确认。
- `http://127.0.0.1:3017/operations/tasks`：任务记录与结果重开。
- `http://127.0.0.1:3017/operations/data-sources`：数据集详情与七类接入说明。
- `http://127.0.0.1:3022/native`：跳转到 `http://127.0.0.1:3017/operations`，不再提供独立免登录业务页面。

当前 `/operations/*` 已接入 `:3022/v1/operations` 正式业务接口，逐次验证原生登录会话与目标工作区权限。分析任务和运营对话持久化在服务端，真实提交会创建原生 Session 或发送模型消息，需逐次确认费用；页面、看板和历史查看不会触发模型。浏览器本地适配器仅为历史验证阶段，不是当前产品运行模式。

### 新安装的目录准备

MiniClaw 平台和前端依赖独立安装在本机，不包含在公开源码包内。运行安全启动脚本前，应完成原生账户与 Provider 初始化，并根据 `config/` 模板建立 Profile 和 host Workspace。模板中的 `agent_profile_id` 必须替换，`custom_cwd` 必须改为本次安装的真实源码路径；不要复用其他机器的数据库 ID 或凭据。

Host 使用 `runtime/` 作为工作目录。它需要当前目录下的 `container/agent-runner` 来执行原生会话；新安装时可将 `runtime/container` 连接到锁定平台的 `container`，也可准备独立的对应平台运行资产。Windows 目录联接只连接平台运行器，不上传至 GitHub。既有目录不得盲目覆盖。

前端构建支持 `--platform-root` 或 `MINICLAW_PLATFORM_ROOT` 显式指定平台目录，不要求放在本机开发路径。当前 `native_app/tsconfig.json` 保留默认开发目录布局；在其他布局执行独立 `tsc` 时，需要把其平台源码与类型目录映射到实际位置。生产构建按显式平台目录读取依赖和组件样式，移位构建可用下列命令验证：

```powershell
node tests/verify_data_flow_build.mjs --platform-root '<path-to-miniclaw>'
```

该命令只在项目 `tmp/` 创建隔离前端副本，验证新建生成目录和原生组件样式，再清理自己的测试副本；不会启动服务或调用模型。

如已由可信服务端流程取得 Cookie，可改用 `MINICLAW_COOKIE`，不要同时把 Cookie 暴露给浏览器。`MINICLAW_TIMEOUT_SECONDS` 默认是 30 秒。

只读检查：

```powershell
Invoke-RestMethod http://127.0.0.1:3022/v1/native/configuration
```

项目根路径 `/` 默认重定向到这个原生配置状态；冻结的 `/demo` 不再是首页。

只有 `workspace_configured=true`、`credentials_configured=true` 和 `ready=true` 才允许创建运行。响应只显示配置状态，不返回凭据。

## 创建真实运行

`POST /v1/native/runs` 会创建 MiniClaw Session 并提交一次真实模型消息。必须先获得本次费用与范围授权，然后显式传入 `authorized_model_execution=true`：

正式运营页面使用面向产品的请求结构，不把服务器文件路径交给浏览器。用户在每次提交前必须单独勾选费用确认；后端要求 `fee_confirmation=confirmed` 和 `authorized_model_execution=true`，再根据登记的 `source_id` 与业务域选择必要数据文件：

```json
{
  "idempotency_key": "native-ui-<unique-token>",
  "source_id": "sample-commerce-data",
  "requested_domains": ["content_growth", "live_conversion"],
  "objective": "识别主要流失环节并生成行动建议",
  "include_strategy": true,
  "fee_confirmation": "confirmed",
  "authorized_model_execution": true
}
```

前端只执行一次 POST。接受后保存 `workflow_run_id` 并只读轮询；页面重载只恢复 GET 查询。POST 响应因网络中断而未知时显示 `uncertain` 提示，不会自动生成新键或再次提交。

内部脚本和受控服务调用仍兼容显式 `datasets` 的底层请求：

```powershell
$body = @{
  idempotency_key = 'native-content-<yyyymmdd>-001'
  requested_domains = @('content_growth')
  datasets = @(
    @{
      dataset_type = 'short_video'
      file_path = 'short_video/synthetic-short-video.csv'
    }
  )
  objective = '核验内容增长诊断链路与父子尝试账本'
  include_strategy = $false
  authorized_model_execution = $true
} | ConvertTo-Json -Depth 6

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:3022/v1/native/runs `
  -ContentType 'application/json' `
  -Body $body
```

每个数据文件必须位于 `data/fixtures` 内；后端生成唯一 `workflow_run_id`、`dataset_id` 和 Session 名称。同一个 `idempotency_key` 与相同请求只返回原记录；同键不同请求返回 409，不会再次提交。

## 查询与终态

```powershell
Invoke-RestMethod http://127.0.0.1:3022/v1/native/runs/<workflow_run_id>
```

查询只读取 Session、消息和项目审计，不会提交消息。运行结果同时保留 `platform_status` 和 `observed_execution_state`：前者是 MiniClaw 驻留 conversation process 的状态，后者是当前提交回合的项目侧观测状态。固定平台的默认驻留超时为 30 分钟，所以 `platform_status=running` 不等于该回合尚未完成。

终态含义：

- `completed`：同 workflow 的最终结构化结果与项目审计都存在，父级派发和子级工具账本满足契约，且没有失败或未完成尝试。
- `partial`：有结果，但父级/专业工具基数错误、存在失败或阻断尝试，或仍有可用但不完整的证据。
- `blocked`：预检、平台或工具明确拒绝/失败。
- `uncertain`：创建 Session、提交消息或生命周期结果无法确认；系统不会自动重试。

最终回复必须带 `PROJECT017_NATIVE_RESULT_JSON`。后端不会只相信模型自报：它会读取 `runtime/data/native-audit/{workflow_run_id}.jsonl`，合并父级 `Agent` 与子级业务工具尝试，并生成 `authoritative_result`。权威尝试数、service run ID 和 analysis run ID 来自项目审计；模型自报值只用于 reconciliation，要求保序精确匹配且不能替换审计 ID。相同 workflow 的结构化最终结果、非空审计和零 unfinished 尝试足以把 `observed_execution_state` 结算为 `settled`，平台进程状态仍原样保留。常见凭据字段在写入响应前会再次替换为 `[REDACTED]`。

### 运营结果投影

正式页面不读取上述原生记录中的 `final_response`。任务 settled 后只调用：

```powershell
Invoke-RestMethod http://127.0.0.1:3022/v1/native/runs/<workflow_run_id>/result
```

该接口返回 `processing`、`ready`、`needs_review` 或 `unavailable` 四种视图状态，以及不可逆短任务参考号、运营标题、摘要、发现、指标、行动和提示。它不返回原始模型回复、workflow/service/analysis/dataset 等内部 ID、Agent 角色、工具名、尝试次数或审计结构。

新运行的 `PROJECT017_NATIVE_RESULT_JSON` 必须包含如下产品合同；内部对账字段仍保留在同一结构化块中，但不会进入运营结果响应：

```json
{
  "operator_result": {
    "headline": "一句话经营结论",
    "summary": "面向运营人员的结果摘要",
    "findings": [
      {
        "domain": "content_growth",
        "title": "结论标题",
        "summary": "结论说明",
        "metrics": [{"label": "指标名", "value": "值", "context": "口径或范围"}],
        "evidence_basis": ["支撑该结论的事实描述"],
        "limitations": ["适用限制"]
      }
    ],
    "actions": [
      {
        "title": "行动内容",
        "priority": "high",
        "owner": "运营岗位名称",
        "due_window": "执行时限",
        "rationale": "行动依据",
        "verification": "复验方式与指标",
        "guardrails": ["执行边界"]
      }
    ],
    "notices": ["数据或解释边界"]
  }
}
```

`operator_result` 只能从通过生产 Schema 的 AnalysisPacket 与 DecisionPacket 整理。发现域必须属于本次请求；未请求策略时 actions 必须为空；`blocked`/`uncertain`、旧运行缺少该结构、字段不合格或出现内部引用/敏感标签时均 fail-closed 为 `unavailable`，不会用原始文本兜底。

### 运营任务记录

正式页面通过以下只读接口加载历史任务：

```powershell
Invoke-RestMethod http://127.0.0.1:3022/v1/native/tasks
Invoke-RestMethod http://127.0.0.1:3022/v1/native/tasks/<task_reference>/result
```

只有通过正式运营请求结构创建的运行会保存 `operator_visible=true`；底层 `NativeRunRequest`、内部脚本和历史开发运行默认不可见。任务目录只返回业务范围、策略范围、创建/更新时间、视图状态、运营标题与摘要，以及由 workflow ID 单向哈希得到的 12 位大写任务参考号，不返回原始 ID 或内部账本。

历史结果接口只在 operator-visible 记录中查找参考号。格式错误返回 422，不存在返回 404，参考号碰撞返回 503；这些情况都不会回退到原始运行记录或模型文本。任务目录和结果重开均为 GET，不会创建 Session、提交消息、重试任务或触发模型。

## 安全与失败语义

- `/v1/native` 仅允许 loopback 调用。
- HTTP Client 没有自动重试；每次变更请求最多发送一次。
- 发送前先持久化请求指纹和提交状态，进程重启后仍能阻止重复提交。
- 连接中断或 5xx 导致副作用无法确认时标为 `uncertain`，禁止自动重投。
- 审计只保存角色、工具、次数、状态和 run_id，不保存原始 Prompt、工具参数或凭据。
- 当前只接受 `synthetic=true` 的项目 fixture；不写 CRM、订单或任何外部业务系统。

### 确定性恢复契约

`commerce_ops/native_recovery.py` 会把持久化运行状态和安全运营投影归一为 `NativeRecoveryPlan`。计划固定 `automatic_retry_allowed=false`，并明确是否必须观察原任务、新任务策略、允许步骤、禁止步骤和退出当前状态的门槛。

运行中或 `uncertain` 状态必须继续只读观察同一任务；原任务结果确认前禁止创建替代任务。明确阻断、部分结果或运营投影不可用也不会自动重跑：只有在根因修正或人工复核后，由运营人员重新确认模型费用并使用新幂等键，才允许创建新任务。已完成但投影不合格的结果不会回退展示 `final_response`。

完整恢复矩阵、运营/管理员清单和离线命令见 `docs/NATIVE-RECOVERY-v1.md`。恢复目录 `contracts/native-recovery-cases-v1.json` 当前 8/8 通过，证据为 `artifacts/native-recovery-validation-v1.json`；该验证不启动 Host/API、创建 Session、提交消息或调用模型。

本节新增 4 项恢复单测后，Python 完整回归为 83/83；恢复模块、验证器和测试文件 AST 语法检查为 3/3。

## 2026-09-03 验收结果

- Python 回归：`59/59`。
- MiniClaw 静态配置：`129/129`，见 `artifacts/miniclaw-static-config-v8.json`。
- Subagent bridge：`26/26`，见 `artifacts/miniclaw-subagent-bridge-validation-v4.json`。
- Pi extension runtime：`15/15`，见 `artifacts/pi-extension-runtime-v3.json`。
- 本机 Host：`/api/auth/status` 返回 HTTP 200 和 `initialized=true`；未认证 `/api/auth/me` 返回 401；载入 2 个 host execution Workspace。
- 本机原生 API：3022 端口实际启动，OpenAPI 版本为 `0.4.0`，三条 `/v1/native` 路由存在；未传 `authorized_model_execution=true` 的请求返回 422。
- 宿主健康验收阶段未创建 Session、未调用 `/api/messages`、未触发 Provider 或模型。

随后在用户单独授权下完成原生内容增长 v1：

- 使用全新 idempotency/workflow/session/dataset 身份，创建一次 Session、向 `/api/messages` 只提交一次任务，没有自动重试。
- 请求只包含 `content_growth`，`include_strategy=false`；父级 `Agent ×1` 和子级 `inspect ×1 → analyze_short_video ×1` 共 3 次尝试全部完成。
- 最终 `PROJECT017_NATIVE_RESULT_JSON` 报告的总次数、两个 service_run_id 和一个 analysis_run_id 与项目脱敏审计一致；strict business smoke 与 final reporting accuracy 通过。
- MiniClaw Session 在最终回复和完整审计出现后曾超过宽限时间为 `running`，后续只读复查确认 `platform_status=idle`、`phase=settled`；没有重提、删除或重置 Session。
- 正式 assessment 为 23 项中 20 pass、0 fail、1 difference、2 not_evaluated。业务、报告与平台生命周期通过，唯一 difference 是旧审计缺少精确布尔值；模型请求数、token 或准确成本仍保持 `null/unknown`。
- 运行时的 v1 父级审计证明 `run_in_background` 参数存在，但未保存精确布尔值。运行结束后 bridge 已新增 `run_in_background_value`，对账也会完整收集生命周期 warning；该无模型修复没有用于反向改写或重跑历史运行。

随后在新的明确授权下完成原生渠道归因 v1：

- 使用三份 synthetic 渠道线索、销售跟进和订单数据，只创建一次 Session、只提交一次消息，没有自动重试。
- 父级 `Agent ×1` 精确记录 `isolation_argument_present=false`、`run_in_background_argument_present=true` 和 `run_in_background_value=false`；子级严格执行 `inspect ×1 → analyze_attribution_and_leads ×1`，未调用 drilldown。
- 三份 manifest 均为 pass；分析按设计返回可用 `partial`，因为 12 条线索中 1 条缺少跟进。四项报告值与确定性重算一致：线索 12、24 小时首次跟进率 75%、订单关联覆盖率 66.6667%、线索到已支付订单转化率 50%。
- 无成本字段时未计算 ROI；最终报告保留 synthetic、关联不等于因果和不评价个人能力边界。
- 最终结构化结果中的父子 3 次尝试、两个 service_run_id 和一个 analysis_run_id 与项目审计一致。后续只读 GET 确认 `platform_status=idle`、`phase=settled`；正式 assessment 为 30 项中 28 pass、0 fail、0 difference、2 not_evaluated，业务、报告与平台生命周期通过。

宿主健康证据见 `artifacts/native-host-health-v1.json`；原生真实运行证据见 `artifacts/runtime/native-content-v1-*` 与 `artifacts/runtime/native-attribution-v1-*`。运行日志位于被 Git 忽略的 `runtime/logs`，不进入公开交付包。

策略 v1 已在新授权下运行一次“渠道诊断 + 策略”原生工作流：渠道业务链、两次父级前台派发、策略零工具和 4 次合并账本通过；实际 DecisionPacket 经 Pydantic 验证产生 20 个错误，严格契约失败。Prompt 已无模型收紧但未重跑。后续只读 GET 已确认 `platform_status=idle`、`phase=settled`、0 warning、0 unresolved，4 次账本未变化；未创建 Session、未提交消息、未调用模型。正式 assessment 更新为 40 项中 33 pass、5 fail、1 difference、1 not_evaluated。修复后策略验收、完整一主四专、失败恢复与 30-case 评测仍需要各自的新费用与运行授权。

## 2026-09-04 完整 v4 结果与后续无模型诊断

完整 v4 使用 `runtime/native-full-v4-request.json` 只 POST 一次，创建一个新 workflow 与 Session，提交后没有重提：

- 三个专业角色各一次前台串行派发，全部省略 isolation 并显式记录 `run_in_background=false`；内容和归因严格各为 `inspect ×1 → analyze ×1`，归因唯一 inspect 登记三类跨表数据，零 drilldown。
- 直播角色在一个 assistant 回合发出两个 analyze；一个完成，后一个在 MCP 前以 `duplicate_analysis_attempt_forbidden` 阻断。
- Supervisor 在一个 assistant 回合发出两个策略 Agent；较早调用完成，后发调用以 `duplicate_subagent_dispatch_forbidden` 阻断。该真实轨迹证明 bridge 截止序号修复没有反向污染较早调用。
- 策略 Agent 零工具，输出通过 `DecisionPacket.model_validate()`，0 error；因上游已有 blocked 尝试，合法输出为 `terminal_status=blocked`、3 个 source analysis、0 action、5 个 blocked reason。
- 项目审计为父级 5、专业工具 7、合计 12；10 completed、2 blocked、0 unfinished。最终报告的次数和 3 个 analysis run ID 对账，但 service run ID 集合失败：观察 6 个、报告 7 个，遗漏 1 个并加入 2 个未观察 ID。
- `disable_parallel_tool_use` 没有引发兼容 HTTP 错误，但真实响应仍出现双工具，因此不能声明该 provider 约束已经有效执行。
- 后续 14/14 无模型请求链验证使用真实 Pi Loader、Anthropic serializer 和假 `fetch`，确认 Supervisor 与专业 Agent 的最终 JSON 都保留该字段；本地 hook/serializer 绕过已排除，精确远端层仍不可见。
- 固定 MiniClaw 源码确认 conversation process 默认驻留 30 分钟。最终回复后的 `platform_status=running` 是平台进程状态；v4 提交回合已由最终结果与零 unfinished 审计结算，但重复派发和重复分析失败不变。
- 新返回结构由项目审计生成权威 6 个 service run ID 和 3 个 analysis run ID；历史模型报告的 7 个 service run ID 继续作为不匹配证据保留，不能覆盖审计值。

正式 assessment 为 35 项中 28 pass、5 fail、1 difference、1 not_evaluated，完整流程 strict fail。历史证据不回写；根因与本地修复证据见 `artifacts/runtime/native-full-v4-root-cause-diagnosis-v1.json`、`artifacts/provider-request-chain-validation-v1.json` 和 `artifacts/miniclaw-static-config-v17.json`。该 workflow 与 idempotency key 不得复用。

## 2026-09-05 确定性准入边界

项目不再把 `disable_parallel_tool_use=true` 当作唯一正确性前提。父级 `Agent` 与五个专业业务工具现在都声明 Pi `executionMode=sequential`；固定版本 Pi agent-core 会在任一工具要求顺序执行时，把该 assistant 消息中的整个工具批次交给 `executeToolCallsSequential`，保持 Provider 输出顺序。

bridge 与专业 extension 还增加了第二层准入：每个 Provider tool proposal 先写 `provider_proposal_received`，再记录 `admitted`、`coalesced` 或 `rejected`。已完成同角色 Agent 或同阶段业务工具的重复提议会 `coalesced` 到首个 canonical tool call，返回首个结果且不创建第二次 Agent/MCP 执行；参数违规、越权、前序失败和真实 transport/业务失败仍按 blocked/failed 尝试处理。两类记录都不保存原始 Prompt 或完整工具参数。

`NativeRunResult` 现在单独返回 `provider_proposals` 与 `proposal_summary`。父子执行尝试仍由 `attempts`、`ledger` 和 `authoritative_result` 表示；coalesced proposal 不增加尝试数，不制造新的 service/analysis run ID，也不把可用业务结果降级为失败。无模型验证为 bridge v11 `36/36`、extension v5 `22/22`、Loader v4 `19/19`、静态 v18 `167/167`。本节没有启动 MiniClaw、同步实时 Profile、创建 Session、提交消息或调用模型；历史 v4 strict fail 不变。
