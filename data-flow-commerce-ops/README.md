# Data Flow｜电商数据运营多 Agent 工作台

面向内容运营、直播运营、渠道运营和销售转化团队的本地经营分析工作台。系统以一个经营分析主管 Agent 调度四个专业 Agent，通过确定性数据工具、结构化证据链和只读运营结果，把短视频、直播、渠道线索、销售跟进与订单数据组织成可复核的分析任务。

当前源码版本：`2026.10.03`。本次统一 Data Flow 项目命名与目录，保留原生登录、运营界面、认证分析、对话、看板和导出，详见 [版本说明](docs/RELEASE-NOTES-2026-10-03.md)。

> 当前交付是 `source preview`，不是“已评测正式版”。30 条评测 fixture 已全部就绪，真实 Agent 评测已执行 5/30；自动门禁当前 0/5 通过，H09/H10/H12 语义复核为 0/5。不得据此声明模型质量、真实经营效果或生产稳定性已经通过。

## 运营人员可以做什么

- 使用 MiniClaw 原生账号登录，在 `/operations` 查看概览和最近任务。
- 创建内容增长、直播转化或渠道归因分析任务，查看进度与历史结果。
- 使用登记过的数据源，填写分析目标并选择是否生成行动建议；当前内置数据为五份本地 CSV 测试数据。
- 每次真实模型提交前单独确认费用，提交后只读查看进度，不自动重试。
- 查看经营结论、关键发现、指标口径、判断依据、使用边界和行动计划。
- 从历史任务列表重新打开严格脱敏的运营结果。
- 与 Data Flow 自由对话，继续讨论某次分析结果或当前看板筛选范围。
- 查看五项经营指标、六组图表、筛选后的五类数据明细，并导出 PNG 与 CSV。

桌面和移动页面共用统一的导航、主题、表单、表格和确认弹窗。明细查看、看板计算、图片/CSV 导出及历史查看不调用模型；创建分析或发送 AI 消息前需要逐次确认模型费用。

运营页面不展示内部 Agent ID、工具名、workflow ID、原始模型回复或父子尝试账本。合法的结构化 JSON 结果即使缺少输出标记也可被识别；`partial` 任务会显示结论并同时标注数据限制。真正未完成或结构无效的任务显示为未生成结果。

数据源管理会区分“已连接”与“可接入”：当前 89 条测试数据来自短视频、直播场次、渠道线索、销售跟进和订单五份本地 CSV；MySQL、PostgreSQL、飞书多维表格、飞书电子表格、HTTP API 和 MCP 未配置前不会显示成已连接。

## 一主四专

| 角色 | 职责 | 工具边界 |
|---|---|---|
| 经营分析主管 | 理解目标、拆解任务、调度与汇总 | 只调度，不直接计算业务指标 |
| 内容增长分析师 | 短视频与内容效率诊断 | 内容数据检查、分析与受限钻取 |
| 直播转化分析师 | 观看、点击、下单与成交漏斗诊断 | 直播数据检查、分析与受限钻取 |
| 渠道归因分析师 | 线索、跟进、订单关联与渠道贡献 | 渠道数据检查、分析与受限钻取 |
| 复盘策略分析师 | 把已校验诊断转为行动与复验指标 | 不读取原始数据，不调用业务工具 |

## 运行架构

```text
运营浏览器 /operations
  -> MiniClaw 原生登录与 HttpOnly Cookie
  -> project FastAPI /v1/operations
  -> 账号与工作区权限校验
  -> MiniClaw Host API
  -> Supervisor AgentSession
  -> project-local Subagent bridge
  -> 专业 Agent
  -> project-local Pi extension
  -> Python stdio MCP 确定性工具
  -> 脱敏审计与严格运营结果投影
```

MiniClaw/Pi Runtime、AgentSession 和平台基础调度属于外部平台能力，本仓库提供电商业务建模、角色约束、确定性工具、原生接入、证据链、恢复策略、评测门禁与运营界面。

## 环境要求

- Python 3.10+
- Node.js 20+，以及 MiniClaw 平台和前端依赖
- PowerShell 7（使用 Windows 安全启动脚本时）
- 已构建的 MiniClaw Host `dist/index.js` 与平台前端源码
- MiniClaw 中可用的本地账号、Workspace、AgentProfile 和 Provider 配置

公开包不包含 MiniClaw 平台源码、Provider Key、账号密码、Cookie、数据库、Session、运行日志或真实业务数据。

原生 overlay 对应的 MiniClaw 源码版本为 [`helsome/miniclaw@3ff1c8d`](https://github.com/helsome/miniclaw/tree/3ff1c8d6a0707f4a9f0957ff411758e5e141583a)。平台升级需重新验证原生认证、路由和构建锚点，不能直接替换为任意新版。平台采用 MIT 许可证；本仓库不重新打包该平台。

## 安装

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS/Linux 可使用对应的虚拟环境激活命令。项目内 `.pi/extensions/commerce-ops-mcp` 的 Node 依赖可用 `npm ci` 安装。

## 打开正式运营后台

本仓库保留既有目录布局：根目录是项目介绍，实际源码在 `data-flow-commerce-ops/` 内。克隆后先进入源码目录，再安装依赖和运行脚本。初始化要求与外部平台目录布局见 [原生运行说明](docs/MINICLAW-NATIVE-RUNTIME-v1.md)。

首次运行须先完成 MiniClaw 的本地账户、Provider、AgentProfile 和 Workspace 配置；Workspace 使用 `host` 执行模式，`custom_cwd` 指向当前源码目录。配置模板位于 `config/`，模板不携带可直接复用的真实凭据。安全启动脚本校验已有配置，不会自动创建用户、工作区或付费任务。

Windows 上使用安全启动脚本：

```powershell
pwsh -File scripts\start-native-runtime.ps1 `
  -MiniClawEntry '<path-to-miniclaw-dist\index.js>'
```

脚本构建 Data Flow 原生前端，在终端中隐藏输入本地密码，只把临时 Cookie 注入后端子进程，不会把密码或 Cookie 写入仓库，也不会自行创建 Session 或提交模型任务。

打开 `http://127.0.0.1:3017/login`，登录后进入 `http://127.0.0.1:3017/operations`。请统一使用 `127.0.0.1`，不要与 `localhost` 混用。业务 API 在 `127.0.0.1:3022`，原 `http://127.0.0.1:3022/native` 入口只做兼容跳转；单独启动 FastAPI 不提供免登录运营页面。

| 页面 | 路由 |
| --- | --- |
| 运营概览 | `/operations` |
| 新建分析 | `/operations/analysis` |
| 分析任务和结果 | `/operations/tasks` |
| 数据源 | `/operations/data-sources` |
| 数据看板 | `/operations/visualizations` |
| 运营对话 | `/operations/conversations` |

原生认证、工作区、智能体管理及设置保留在同一个应用内。认证业务接口、对话和看板说明分别见 [认证接口](docs/DATA-FLOW-AUTHENTICATED-API-v1.md)、[运营对话](docs/DATA-FLOW-CONVERSATIONS-v1.md) 和 [数据看板](docs/DATA-FLOW-VISUALIZATIONS-v1.md)。

## 本地无模型验证

```powershell
python -B scripts\run-commerce-ops-evals.py preflight
python -B scripts\verify-native-recovery.py
python -B scripts\verify-evaluation-delivery-readiness.py
python -B -m unittest discover -s tests -p "test_*.py" -v
node --check native_web\app.js
```

这些命令验证 fixture、契约、API、恢复策略和交付门禁，不创建 AgentSession、不调用模型或 Judge，也不证明 Agent 质量。

前端生产构建可显式指定锁定平台的位置：

```powershell
node scripts/build-data-flow-web.mjs --platform-root '<path-to-miniclaw>'
node tests/verify_data_flow_build.mjs --platform-root '<path-to-miniclaw>'
```

浏览器验收必须在正式服务停止、3017/3022 空闲时使用 `tests/operations_browser_harness.py` 的隔离身份和模型替身。各套件分别重启 harness，不能把测试脚本指向正在使用的真实项目。界面规范和验收入口见 [设计系统](docs/DATA-FLOW-DESIGN-SYSTEM-v1.md)。

## 评测与费用边界

- 30 条固定用例拆为 6 个命名批次，每批最多 6 条。
- 每个批次必须单独确认 Provider、模型、当前价格来源、最高预算和授权范围。
- 不自动续批，不自动模型重试，传输结果不确定时只观察原任务。
- H09/H10/H12 必须有可追溯人工或 Judge 复核；LLM Judge 还须记录 Provider、模型 ID 和提示词哈希。
- 只有完整 baseline、candidate 与 regression comparison 均通过后，才能称为 evaluated release。

详见 [评测与 GitHub 交付门禁](docs/EVALUATION-DELIVERY-GATE-v1.md)。

## 数据与安全边界

- 仓库内业务数据全部为 `synthetic` 合成样例。
- 不要把真实姓名、手机号、地址、账号、Cookie、API Key 或订单隐私提交到仓库。
- 无稳定关联键时停止归因；无成本字段时不计算 ROI。
- 系统只生成分析建议，不写入 CRM、投放平台、订单系统或其他外部业务系统。
- 运行中、提交结果不确定或证据不足时禁止创建替代任务；恢复规则见 [原生失败恢复](docs/NATIVE-RECOVERY-v1.md)。

## 目录

```text
.pi/             一主四专角色和 project-local extension
commerce_ops/    FastAPI、数据工具、原生运行与运营结果投影
config/          不含凭据的 Workspace/Profile 模板
contracts/       Workflow 与恢复契约
data/fixtures/   合成业务数据
docs/            架构、运行、评测与证据边界
evals/           30 条用例、fixture、Rubric 和记录模板
native_web/      历史兼容界面
native_app/      原生 React / TypeScript 运营界面与共享设计规范
scripts/         启动与无模型验证入口
tests/           自动化回归
```

`native_app/` 是当前产品主线；`native_web/`、`web/` 与 `/demo` 仅作为历史兼容和故障隔离资产保留。业务根路径经兼容入口跳转到原生认证工作区，后续产品开发不以 Demo 为主线。
