# Data Flow 认证业务接口 v1

日期：2026-09-26。范围：认证运营接口、数据看板与运营对话；管理员连接配置、飞书与数据库真实读取保持独立。

## 当前运行方式

```text
浏览器 :3017 /operations
  → MiniClaw 原生登录与 HttpOnly 会话 Cookie
  → project017 :3022 /v1/operations
  → MiniClaw /api/auth/me + /api/groups 校验身份与工作区权限
  → 现有 NativeRuntime / NativeRunStore / 安全运营结果投影
```

前端的本地种子任务和本地生成结果实现已移除。历史浏览器 localStorage 测试记录不会迁入正式任务目录；服务端已有的 `operator_visible=true` 且属于当前工作区的任务仍可查看，内部调试运行不进入目录。旧任务没有自定义名称和源元数据时显示通用名称与“任务提交时的数据文件”，不反推不存在的历史字段。

数据源由后端目录和第 13 期校验摘要提供：短视频 18、直播 24、渠道线索 18、销售跟进 17、订单 12，共 89 条合成测试记录。它们仍是本地 CSV，不是 MySQL 或飞书中的真实经营数据。

## 操作

在项目目录运行：

```powershell
pwsh -File scripts/start-native-runtime.ps1
```

启动脚本隐藏输入密码，验证目标工作区并启动 Host/API；构建端口与 API 的 `-ApiPort` 参数一致。然后访问 `http://127.0.0.1:3017/login`。旧 `:3022/native` 自动跳转到认证工作区。

1. 登录后查看工作台和数据源。账号必须能够在 MiniClaw 访问项目目标工作区；有账号不等于拥有该工作区权限。
2. 新建分析，填写名称、目标，选择域和策略范围。
3. 明确勾选模型费用确认后提交。此时会进入真实 NativeRuntime，可能产生 Provider 费用，不再是本地演示。
4. 结果页每 5 秒只读观察执行中的任务，完成后停止轮询。列表按 20 条分页并刷新当前页；结果可直接通过参考号重开，不依赖数据源页先加载成功。
5. 如果确认响应中断，使用“查询上次提交”。sessionStorage 只保存当前账号的提交编号，不保存密码、Cookie 或分析结果。
6. 如果模型端受理状态不确定，保留原编号并联系管理员。前端不会清除这次编号，服务端在提交锁内也会阻止该账号在同一工作区用新编号创建替代任务。确认前不自动重试、不把失败伪装成成功。
7. 运营对话也逐条执行费用确认和单次发送。分析任务或数据看板进入对话时，服务端重新读取权威结果/快照并生成安全上下文，不接受浏览器自报的结论或指标正文。

## 认证与状态边界

- 每次业务请求验证浏览器会话与工作区可见性；会话失效返回 401 并退出受保护页面，权限不足返回 403。
- API 只监听本机，CORS 只允许 `MINICLAW_BASE_URL` 的精确来源；写请求必须携带该来源。请不要混用 localhost 与 127.0.0.1。
- 浏览器不再直连旧 `/v1/native` 或工具端点；它们保留给可信本机脚本，不能作为对外开放的身份边界。
- 响应设置 `Cache-Control: no-store`。浏览器不接收原始模型回复、审计账本、内部运行 ID、文件路径或服务端凭据。
- 同一提交编号与同一请求只执行一次；参数或标题变化不能复用旧编号。编号在后端按账号和工作区隔离。
- 合格的 completed/partial 结果直接显示发现与行动；真实阻断或无效内容不使用未经校验原文兜底。
- 已结束的结果直接读持久化记录，但访问仍要求 MiniClaw 在线验证身份。查看结果不触发模型，也不重写已结束记录。

## 无付费验收

后端测试：

```powershell
python -m unittest discover -s tests -p 'test_*.py'
```

浏览器验收在 3017/3022 空闲时运行，先构建前端，在单独终端启动：

```powershell
python tests/operations_browser_harness.py
```

另一终端运行：

```powershell
node tests/verify_data_flow_operations.mjs
node tests/verify_data_flow_conversations.mjs
```

测试入口先校验隔离环境标记；不允许向真实 Host 发送测试提交。它使用真实 FastAPI 运营接口、真实 NativeRuntime 提交逻辑和独立临时存储，但认证提供方、模型及完成响应均为测试替身。验证 Cookie/CORS、费用勾选、执行中、结果轮询、刷新重开、策略开关、中断恢复、权限、会话过期和移动端布局，不代表新增真实模型验收。

证据：`artifacts/data-flow-api-browser-validation.json`、`artifacts/data-flow-api-result-desktop.png`、`artifacts/data-flow-api-sources-mobile.png`。测试结束关闭临时服务；测试运行记录不能进入正式 `runtime/data/native-runs`。

`tests/verify_data_flow_auth_cdp.mjs` 是第二小节本地适配器的历史验收脚本，不作为当前认证业务接口验收入口。

## 后续

下一小节为管理员连接配置和外部读取验证，优先飞书多维表格。仍需独立配置企业应用权限、目标表及字段映射，不能把飞书消息渠道等同为已接通的业务数据。全量 30 条模型评测和公网发布是另外的交付门禁，本节未改变其状态。
