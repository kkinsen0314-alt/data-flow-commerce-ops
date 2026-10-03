# Data Flow 界面规范 v1

落地日期：2026-10-02。适用范围：MiniClaw 原生登录、应用外壳与 `/operations/*` 运营工作区。

## 设计方向

使用 `frontend-design` 将现有界面统一为日常运营后台：一个主导航、紧凑的信息层级、统一的按钮和表格、明确的状态色。页面不承担项目汇报或验收展示，保留真实数据来源和逐次模型费用确认。

本轮不增加第三方连接、不改变业务接口、不触发真实模型分析。原生账号认证、工作区权限、智能体管理和设置继续复用 MiniClaw。

## 导航

桌面主导航宽度 224px；小于 1024px 时使用单一移动页头和右侧抽屉。删除运营页顶部编号导航及重复的移动底栏。

| 运营入口 | 路由 |
| --- | --- |
| 新建分析（主按钮） | `/operations/analysis` |
| 运营概览 | `/operations` |
| 数据看板 | `/operations/visualizations` |
| 运营对话 | `/operations/conversations` |
| 分析任务 | `/operations/tasks` |
| 数据源 | `/operations/data-sources` |

任务结果 `/operations/tasks/:reference` 只选中“分析任务”，运营概览采用精确匹配。系统区保留智能体工作台、智能体配置、能力库、自动化任务、用量统计、设置；账单按原生功能开关显示。工作台旁的展开按钮只控制原生工作区列表，不与路由跳转混用。

## 视觉基础

| 项目 | 默认浅色规范 |
| --- | --- |
| 主色 | `#0B7C70` |
| 页面底色 | `#F5F7F8` |
| 面板 | `#FFFFFF` |
| 主文字／次文字 | `#202C32`／`#52626D` |
| 边框 | `#DCE3E7` |
| 字体 | 原生 DM Sans 与系统中文回退字体 |
| 页面标题／模块标题／正文／辅助文字 | 28／18／14／12px |
| 间距 | 4、8、12、16、24、32px |
| 圆角 | 控件 6px，面板 10px，弹窗 12px |
| 控件高度 | 桌面主要控件 40px，手机主要操作 44px |

`native_app/src/design-tokens.css` 是业务页与原生组件的共享颜色来源；`--df-*` 别名引用原生背景、文字、主色和边框变量。默认采用青绿色，原生设置中已有的橙色／中性配色选择继续生效。深色模式同时覆盖导航、面板、输入框、图表、提示和弹窗，不单独建立第二套主题开关。

状态色按含义使用：绿色表示完成或可用，蓝色表示处理中，琥珀色表示数据提示或待确认，红色表示错误。仍由服务端结果状态决定文案，不为视觉效果伪造成功状态。

## 页面落地

- 登录：轻量产品标识、正式账号表单、原生认证行为和真实环境标识；不新增演示登录。
- 概览：统一指标卡、分析入口、数据概况与最近任务，采用紧凑模块代替大幅宣传区域。
- 分析与任务：统一表单、确认弹窗、列表和状态标记，保留策略选择、费用门禁、幂等提交和原任务查询。
- 结果：统一发现、指标、行动和数据说明模块，保留安全结果投影与“在对话中继续”。
- 数据源：七类接入方式按现有类别分组，压缩为信息行；接入说明使用原生对话框，支持 Escape 关闭和焦点恢复。
- 看板：图表字体、网格、提示框和状态色读取共享主题；导出时把 SVG 的计算颜色与字体写入克隆，避免 CSS 变量在离线图片中丢失。
- 对话：页面高度受应用视口约束，历史和消息各自滚动，不再把外层页面滚动到输入区。输入框保留明确的可访问名称、上下文卡片和逐条费用确认。

在 400px／320px 高的手机视口中启用紧凑布局：减少辅助说明、压缩上下文为单行、降低输入区占用；极短视口暂收起重复页标题和历史栏。验收同时检查输入区处于视口及对话面板内，避免容器裁切被宽度检查遗漏。

移动导航复用 MiniClaw 原生 `Sheet`，确认及接入弹窗复用原生 `Dialog`。保留焦点约束、Escape、关闭后焦点恢复及忙碌状态保护，不另写全局键盘监听。

## 实现位置与构建边界

- `native_app/src/design-tokens.css`、`styles.css`：基础规范与业务布局。
- `native_app/src/navigationItems.ts`、`components/DataFlowNavigation.tsx`：统一导航。
- `native_app/src/components/WorkspaceDialog.tsx`：运营对话框适配。
- `native_app/src/pages/`：登录、运营主页面、看板、对话。
- `native_app/src/visualizationService.ts`：图片导出的主题解析。
- `scripts/build-data-flow-web.mjs`：原生前端构建 overlay，保留原生应用与工作区逻辑。

project014 上游源码保持只读。现有 `runtime/web` 是指向 project014 上游 `web` 的目录联接，因此 `runtime/web/dist` 与上游 `web/dist` 是同一份生成资产；构建会更新这些运行资产，但不修改上游源码。不要把此目录联接描述为独立复制的前端目录。前端 staging 仍在 project017 的 `runtime/tmp` 内完成，再按原有流程替换运行资产。

## 验证与证据

2026-10-02 本轮验证结果：

| 验证 | 结果 |
| --- | --- |
| Python 全量回归 | 138/138 通过 |
| TypeScript 严格检查 | 通过 |
| 原生生产构建 | 4905 modules，成功；保留上游既有大 chunk 提示 |
| 界面专项浏览器检查 | 7/7 组通过 |
| 分析与认证浏览器回归 | 9/9 组通过 |
| 对话与联动浏览器回归 | 10/10 组通过 |
| 看板与导出浏览器回归 | 8/8 组通过 |

四套浏览器共 34 组检查，分析／对话为 4／3 次模拟提交，真实模型调用均为 0。首次看板套件在隔离 fixture HTTP 请求处遇到 `ECONNRESET` 中断，独立读请求检查未复现；重新启动隔离服务后，同一套件完整 8/8 通过，没有加入自动网络重试或改写业务请求。收尾确认命名浏览器会话为空，3017／3022／3023 无监听，上游工作树 clean。

在项目根目录执行：

```powershell
python -B -m unittest discover -s tests -p 'test_*.py'
node D:\Workspace\project014-miniclaw-deployment\upstream\miniclaw\web\node_modules\typescript\bin\tsc -p native_app/tsconfig.json
node scripts/build-data-flow-web.mjs
```

浏览器验收只针对 `tests/operations_browser_harness.py` 提供的隔离身份、临时存储和模型响应替身，连接的业务接口及 CSV 计算是正式实现。不得将测试替身结果当作真实 Provider 端到端评测。各业务套件应分别重启 harness，避免提交计数、登录失效和历史记录互相影响；同一 harness 不并行运行多个浏览器套件。

```powershell
python -B tests/operations_browser_harness.py
node tests/verify_data_flow_design.mjs
```

在分别重启 harness 后运行 `verify_data_flow_operations.mjs`、`verify_data_flow_conversations.mjs`、`verify_data_flow_visualizations.mjs`。运行完关闭命名浏览器及隔离测试 Host/API。

证据位置：

- `artifacts/design-system/verification.json`：导航、结果选中状态、原有页面、弹窗键盘行为、原生主题、手机与短视口检查。
- `artifacts/design-system/*.png`：1440px 登录与核心页面、1280px 对话与深色看板、768px／390px 导航及页面、400px／320px 高对话。
- `artifacts/data-flow-api-browser-validation.json`：分析与认证回归。
- `artifacts/data-flow-conversations-browser-validation.json`：对话与关联上下文回归。
- `artifacts/data-flow-visualizations-browser-validation.json`：看板、筛选、明细及 PNG／CSV 真实下载回归。

现有 MySQL／飞书目录只表示接入方式和准备要求，只有当前本地文件数据源标记可用。第 13 期合成数据说明随页面、看板和导出继续保留；没有把外部数据源改成已连接。
