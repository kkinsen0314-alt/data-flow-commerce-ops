"""Official stdio MCP surface for the five deterministic commerce tools."""

import os
from pathlib import Path
from threading import RLock
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .models import Dimension, Domain
from .service import CommerceOpsService
from .tool_models import (
    AttributionLeadAnalysisRequest,
    DataReference,
    DrilldownCommerceMetricRequest,
    InspectCommerceDataRequest,
    LiveCommerceAnalysisRequest,
    ShortVideoAnalysisRequest,
)


WorkflowRunId = Annotated[str, Field(pattern=r"^wf_[A-Za-z0-9_-]+$")]
DatasetId = Annotated[str, Field(pattern=r"^ds_[A-Za-z0-9_-]+$")]
AnalysisRunId = Annotated[str, Field(pattern=r"^analysis_[A-Za-z0-9_-]+$")]
EvidenceId = Annotated[str, Field(pattern=r"^ev_[A-Za-z0-9_-]+$")]
TopN = Annotated[int, Field(ge=1, le=50)]
DrilldownCallerRole = Literal[
    "content_growth_analyst",
    "live_conversion_analyst",
    "attribution_lead_analyst",
]
InspectCallerRole = DrilldownCallerRole

READ_ONLY_HINTS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

mcp = FastMCP(
    name="commerce_ops",
    instructions=(
        "提供电商数据检查、短视频、直播、归因线索和受限钻取五个确定性工具。"
        "当前只允许 synthetic=true；不配置 Provider，不运行 Agent。"
    ),
    log_level="ERROR",
)

_SERVICES: dict[str, CommerceOpsService] = {}
_SERVICE_LOCK = RLock()


def _service() -> CommerceOpsService:
    default_root = Path(__file__).resolve().parents[1] / "data" / "fixtures"
    data_root = Path(
        os.getenv("COMMERCE_OPS_DATA_ROOT", str(default_root))
    ).expanduser().resolve()
    key = str(data_root)
    with _SERVICE_LOCK:
        if key not in _SERVICES:
            _SERVICES[key] = CommerceOpsService(data_root)
        return _SERVICES[key]


@mcp.tool(
    name="inspect_commerce_data",
    title="电商数据结构与质量检查",
    description=(
        "读取受限数据根目录中的 synthetic 文件，生成 DatasetManifest；"
        "不输出经营结论。"
    ),
    annotations=READ_ONLY_HINTS,
    structured_output=True,
)
def inspect_commerce_data(
    workflow_run_id: WorkflowRunId,
    caller_role: InspectCallerRole,
    data_refs: list[DataReference],
    requested_domains: list[Domain],
    max_rows_for_profile: int = 1000,
) -> dict[str, Any]:
    result = _service().inspect_commerce_data(
        InspectCommerceDataRequest(
            workflow_run_id=workflow_run_id,
            caller_role=caller_role,
            data_refs=data_refs,
            requested_domains=requested_domains,
            max_rows_for_profile=max_rows_for_profile,
        )
    )
    return result.model_dump(mode="json")


@mcp.tool(
    name="analyze_short_video_data",
    title="短视频内容增长确定性分析",
    description="计算曝光、播放、完播、互动、点击及稳定 click key 覆盖。",
    annotations=READ_ONLY_HINTS,
    structured_output=True,
)
def analyze_short_video_data(
    workflow_run_id: WorkflowRunId,
    dataset_ids: list[DatasetId],
    requested_dimensions: list[Dimension] | None = None,
    top_n: TopN = 10,
    synthetic: bool = True,
) -> dict[str, Any]:
    result = _service().analyze_short_video_data(
        ShortVideoAnalysisRequest(
            workflow_run_id=workflow_run_id,
            dataset_ids=dataset_ids,
            requested_dimensions=requested_dimensions or [],
            top_n=top_n,
            synthetic=synthetic,
        )
    )
    return result.model_dump(mode="json")


@mcp.tool(
    name="analyze_live_commerce_data",
    title="直播转化漏斗确定性分析",
    description="计算预约、到课、完课、商品访问、支付和购买漏斗。",
    annotations=READ_ONLY_HINTS,
    structured_output=True,
)
def analyze_live_commerce_data(
    workflow_run_id: WorkflowRunId,
    dataset_ids: list[DatasetId],
    requested_dimensions: list[Dimension] | None = None,
    top_n: TopN = 10,
    synthetic: bool = True,
) -> dict[str, Any]:
    result = _service().analyze_live_commerce_data(
        LiveCommerceAnalysisRequest(
            workflow_run_id=workflow_run_id,
            dataset_ids=dataset_ids,
            requested_dimensions=requested_dimensions or [],
            top_n=top_n,
            synthetic=synthetic,
        )
    )
    return result.model_dump(mode="json")


@mcp.tool(
    name="analyze_attribution_and_leads",
    title="渠道归因与线索转化确定性分析",
    description=(
        "只在稳定脱敏 lead key 覆盖范围内关联订单；"
        "无成本字段时拒绝 ROI。"
    ),
    annotations=READ_ONLY_HINTS,
    structured_output=True,
)
def analyze_attribution_and_leads(
    workflow_run_id: WorkflowRunId,
    dataset_ids: list[DatasetId],
    requested_dimensions: list[Dimension] | None = None,
    link_orders: bool = True,
    calculate_roi: bool = False,
    top_n: TopN = 10,
    synthetic: bool = True,
) -> dict[str, Any]:
    result = _service().analyze_attribution_and_leads(
        AttributionLeadAnalysisRequest(
            workflow_run_id=workflow_run_id,
            dataset_ids=dataset_ids,
            requested_dimensions=requested_dimensions or [],
            link_orders=link_orders,
            calculate_roi=calculate_roi,
            top_n=top_n,
            synthetic=synthetic,
        )
    )
    return result.model_dump(mode="json")


@mcp.tool(
    name="drilldown_commerce_metric",
    title="电商指标受限维度钻取",
    description=(
        "只对已完成 base analysis 的 evidence 做 manifest 允许维度聚合；"
        "不能扩大数据权限。"
    ),
    annotations=READ_ONLY_HINTS,
    structured_output=True,
)
def drilldown_commerce_metric(
    workflow_run_id: WorkflowRunId,
    caller_role: DrilldownCallerRole,
    base_analysis_run_id: AnalysisRunId,
    evidence_id: EvidenceId,
    dimension: Dimension,
    filters: dict[str, str] | None = None,
    top_n: TopN = 10,
    synthetic: bool = True,
) -> dict[str, Any]:
    result = _service().drilldown_commerce_metric(
        DrilldownCommerceMetricRequest(
            workflow_run_id=workflow_run_id,
            caller_role=caller_role,
            base_analysis_run_id=base_analysis_run_id,
            evidence_id=evidence_id,
            dimension=dimension,
            filters=filters or {},
            top_n=top_n,
            synthetic=synthetic,
        )
    )
    return result.model_dump(mode="json")


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
