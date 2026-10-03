# 确定性工具层与 synthetic 验证 v1

## 当前结论

project017 已实现并实际调用五个只读确定性工具：

- `inspect_commerce_data`
- `analyze_short_video_data`
- `analyze_live_commerce_data`
- `analyze_attribution_and_leads`
- `drilldown_commerce_metric`

这证明 Python/Pandas 业务层、FastAPI 路由和 stdio MCP 链路可以在本项目 synthetic fixtures 上运行，不证明 MiniClaw AgentSession、一主四专、真实模型或真实业务数据已经运行。

## 实现结构

| 文件 | 作用 |
| --- | --- |
| `commerce_ops/datasets.py` | 限定数据根目录、字段别名归一、Pandas 读取、数据质量和 DatasetManifest |
| `commerce_ops/service.py` | 五工具确定性实现、角色边界、run_id、证据、失败语义和受限钻取 |
| `commerce_ops/tool_models.py` | HTTP/MCP 请求响应模型、五工具调用者 allowlist 和证据边界字段 |
| `commerce_ops/app.py` | FastAPI `/health`、工具目录和五个同步业务路由 |
| `commerce_ops/mcp_server.py` | 只暴露五工具的官方 stdio MCP Server |
| `commerce_ops/tool_validation.py` | 可复跑的 synthetic 工具层验证 |

FastAPI 使用同步路径函数承载 Pandas 文件读取与聚合，避免把阻塞计算直接放进 async 事件循环。服务状态只保留当前进程内已检查的数据集和 base analysis 引用，不写 MiniClaw 数据库。

## synthetic fixtures

| 数据域 | 文件 | 状态 |
| --- | --- | --- |
| 短视频 | `data/fixtures/short_video/synthetic-short-video.csv` | 新建 |
| 直播 | `data/fixtures/live/synthetic-live-integration.csv` | 阶段 1 从 project015 原样复制，本阶段只读取 |
| 渠道线索 | `data/fixtures/leads/synthetic-channel-leads.csv` | 新建 |
| 销售跟进 | `data/fixtures/followup/synthetic-sales-followup.csv` | 新建 |
| 订单 | `data/fixtures/orders/synthetic-orders.csv` | 新建 |

所有工具默认拒绝 `synthetic=false`。文件路径必须位于配置的数据根目录内，输出只保留聚合指标和脱敏引用。

## 已执行验证

```powershell
python -B -m commerce_ops.tool_validation
python -B -m unittest discover -s tests -p "test_*.py" -v
```

结果：

- 五个 DatasetManifest 的数据质量均为 `pass`。
- 短视频和直播分析为 `completed`。
- 渠道线索分析保留一条缺失跟进记录，按设计返回 `partial`。
- 内容维度钻取为 `completed`。
- 缺订单关联键请求返回 `RELATION_KEY_MISSING`。
- 无成本字段请求 ROI 返回 `COST_FIELD_MISSING`。
- 服务调用均记录 `automatic_retry=false`、`side_effect_state=none`。
- 28 项 Python 测试通过，覆盖服务层、阶段 2 契约、HTTP ASGI 和官方 MCP Client stdio 链路。

机器可读结果见 `artifacts/tool-layer-validation-v1.json`。

## 尚未验证

- Pi extension ToolDefinition 与真实 `DefaultResourceLoader`。
- MiniClaw Profile、Workspace、Plugin Catalog 或 capability policy。
- Provider、模型、AgentSession、一主四专路由和 Agent 轨迹。
- 真实字段映射、真实敏感数据权限、经营收益、成本和延迟。

因此本阶段可以写“完成确定性工具与 HTTP/MCP synthetic 链路”，不能写“完成 MiniClaw 多 Agent 运行”或“提升真实经营指标”。
