# GitHub Source Preview 说明

> version: `2026.10.02` · release type: `source preview`

本次是 Data Flow 原生运营工作台的源码版本更新，包含原生登录、统一前端、认证分析任务、运营对话、数据看板和导出。当前产品入口为 MiniClaw Host 的 `/login` 与 `/operations`；旧 `/native` 兼容跳转，冻结的 `/demo` 与 `web/` 不再作为产品主线。完整说明见 `docs/RELEASE-NOTES-2026-10-02.md`。

## 已验证范围

- 完整一主四专原生 synthetic v7 以唯一请求严格 18/18 通过。
- 第 13 期五类跨表 synthetic 数据已生成并通过 51/51 无模型检查。
- 原生失败恢复目录 8/8 通过，所有场景禁止自动模型重试。
- 30 条评测 fixture 为 30/30 可运行，六个批次精确覆盖，每批最多 6 条。
- 最新界面验收、认证分析、对话与看板回归为 34 组隔离浏览器检查，使用测试身份和模型替身，不代表新增真实模型评测。

## 尚未验证范围

- 真实 Agent 正式评测已执行 5/30；自动门禁当前 0/5 通过。
- H09/H10/H12 与五维软评分仍为 0/5 待复核。
- 尚无通过的 baseline、candidate 或 regression comparison。
- 尚无完整的人工/LLM Judge 语义评分。
- 未使用真实电商数据，未验证真实经营收益、成本或延迟 SLO。

因此，本包可以作为可审阅、可本地验证的源码预览，不能标记为“已评测正式版”。

## 安全排除

构建器使用明确白名单，并排除 Provider Key、密码、Cookie、`.env`、数据库、Session、运行日志、原始模型轨迹、`runtime/`、`artifacts/runtime/`、`.agents/skills`、`skills-lock.json`、`node_modules`、缓存和真实业务数据。React 页面与其他文本源码均进入敏感信息扫描。

包内 `PUBLIC-PREVIEW-MANIFEST.json` 记录文件 SHA-256、证据边界与禁发路径扫描结果；`FILE-MANIFEST.txt` 提供稳定排序的文件清单。压缩包旁的 `.sha256.txt` 用于下载后完整性核验。

## 运行与验证

请从根目录 [README](README.md) 开始。真实模型运行必须重新确认本次 Provider、模型、价格和最高预算；构建或验证本源码包本身不会调用模型或 Judge，也不会发布 GitHub。
