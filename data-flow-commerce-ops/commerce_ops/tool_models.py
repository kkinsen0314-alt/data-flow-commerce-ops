"""Validated request and response models for deterministic commerce tools."""

from typing import Any, Literal

from pydantic import Field, model_validator

from .models import (
    AgentRole,
    AnalystRole,
    AnalysisPacket,
    DatasetManifest,
    DatasetType,
    Dimension,
    Domain,
    StrictModel,
    TerminalStatus,
    ToolName,
    WorkflowError,
)


class DataReference(StrictModel):
    dataset_id: str = Field(pattern=r"^ds_[A-Za-z0-9_-]+$")
    dataset_type: DatasetType
    file_path: str = Field(min_length=1)
    synthetic: bool = True


class InspectCommerceDataRequest(StrictModel):
    workflow_run_id: str = Field(pattern=r"^wf_[A-Za-z0-9_-]+$")
    caller_role: AnalystRole
    data_refs: list[DataReference] = Field(min_length=1)
    requested_domains: list[Domain] = Field(min_length=1)
    max_rows_for_profile: int = Field(default=1000, ge=1, le=100_000)


class AnalysisRequestBase(StrictModel):
    workflow_run_id: str = Field(pattern=r"^wf_[A-Za-z0-9_-]+$")
    dataset_ids: list[str] = Field(min_length=1)
    requested_dimensions: list[Dimension] = Field(default_factory=list)
    top_n: int = Field(default=10, ge=1, le=50)
    synthetic: bool = True


class ShortVideoAnalysisRequest(AnalysisRequestBase):
    caller_role: Literal["content_growth_analyst"] = "content_growth_analyst"


class LiveCommerceAnalysisRequest(AnalysisRequestBase):
    caller_role: Literal["live_conversion_analyst"] = "live_conversion_analyst"


class AttributionLeadAnalysisRequest(AnalysisRequestBase):
    caller_role: Literal["attribution_lead_analyst"] = (
        "attribution_lead_analyst"
    )
    link_orders: bool = True
    calculate_roi: bool = False


class DrilldownCommerceMetricRequest(StrictModel):
    workflow_run_id: str = Field(pattern=r"^wf_[A-Za-z0-9_-]+$")
    caller_role: Literal[
        "content_growth_analyst",
        "live_conversion_analyst",
        "attribution_lead_analyst",
    ]
    base_analysis_run_id: str = Field(pattern=r"^analysis_[A-Za-z0-9_-]+$")
    evidence_id: str = Field(pattern=r"^ev_[A-Za-z0-9_-]+$")
    dimension: Dimension
    filters: dict[str, str] = Field(default_factory=dict)
    top_n: int = Field(default=10, ge=1, le=50)
    synthetic: bool = True


class InspectionResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    workflow_run_id: str = Field(pattern=r"^wf_[A-Za-z0-9_-]+$")
    service_run_id: str = Field(pattern=r"^srv_[A-Za-z0-9_-]+$")
    tool_name: Literal["inspect_commerce_data"] = "inspect_commerce_data"
    caller_role: AnalystRole
    terminal_status: TerminalStatus
    synthetic: bool
    dataset_manifests: list[DatasetManifest] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    workflow_error: WorkflowError | None = None
    duration_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_result(self) -> "InspectionResult":
        if self.terminal_status in {"completed", "partial"}:
            if not self.dataset_manifests or self.workflow_error is not None:
                raise ValueError("完成的数据检查必须且只能包含 manifests")
        else:
            if self.workflow_error is None:
                raise ValueError("blocked/uncertain 数据检查必须包含 workflow_error")
        return self


class AnalysisToolResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    workflow_run_id: str = Field(pattern=r"^wf_[A-Za-z0-9_-]+$")
    service_run_id: str = Field(pattern=r"^srv_[A-Za-z0-9_-]+$")
    tool_name: Literal[
        "analyze_short_video_data",
        "analyze_live_commerce_data",
        "analyze_attribution_and_leads",
    ]
    caller_role: Literal[
        "content_growth_analyst",
        "live_conversion_analyst",
        "attribution_lead_analyst",
    ]
    terminal_status: TerminalStatus
    synthetic: bool
    analysis_packet: AnalysisPacket | None = None
    workflow_error: WorkflowError | None = None
    duration_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_result(self) -> "AnalysisToolResult":
        if (self.analysis_packet is None) == (self.workflow_error is None):
            raise ValueError("分析结果必须且只能包含 packet 或 workflow_error")
        if self.analysis_packet is not None:
            if self.analysis_packet.workflow_run_id != self.workflow_run_id:
                raise ValueError("analysis_packet.workflow_run_id 不一致")
            if self.analysis_packet.terminal_status != self.terminal_status:
                raise ValueError("analysis_packet.terminal_status 不一致")
        return self


class DrilldownRow(StrictModel):
    dimension_value: str
    metrics: dict[str, int | float | str | bool | None]


class DrilldownResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    workflow_run_id: str = Field(pattern=r"^wf_[A-Za-z0-9_-]+$")
    service_run_id: str = Field(pattern=r"^srv_[A-Za-z0-9_-]+$")
    tool_name: Literal["drilldown_commerce_metric"] = (
        "drilldown_commerce_metric"
    )
    caller_role: AgentRole
    terminal_status: TerminalStatus
    synthetic: bool
    base_analysis_run_id: str
    source_evidence_id: str
    dimension: Dimension
    rows: list[DrilldownRow] = Field(default_factory=list)
    data_quality_status: Literal["pass", "partial"] | None = None
    limitations: list[str] = Field(default_factory=list)
    workflow_error: WorkflowError | None = None
    duration_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_result(self) -> "DrilldownResult":
        if self.terminal_status in {"completed", "partial"}:
            if not self.rows or self.workflow_error is not None:
                raise ValueError("完成的钻取必须且只能包含 rows")
        elif self.workflow_error is None:
            raise ValueError("blocked/uncertain 钻取必须包含 workflow_error")
        return self


class HealthResult(StrictModel):
    status: Literal["ok"] = "ok"
    service: Literal["commerce_ops"] = "commerce_ops"
    mode: Literal["deterministic_synthetic"] = "deterministic_synthetic"
    provider_configured: Literal[False] = False
    agent_runtime_executed: Literal[False] = False
    data_root: str


class ToolDescriptor(StrictModel):
    name: ToolName
    allowed_callers: list[AgentRole]
    read_only: Literal[True] = True
    idempotent: Literal[True] = True


class ToolCatalog(StrictModel):
    service: Literal["commerce_ops"] = "commerce_ops"
    tools: list[ToolDescriptor]
    provider_configured: Literal[False] = False
    agent_runtime_executed: Literal[False] = False


TOOL_ALLOWED_CALLERS: dict[ToolName, set[AgentRole]] = {
    "inspect_commerce_data": {
        "content_growth_analyst",
        "live_conversion_analyst",
        "attribution_lead_analyst",
    },
    "analyze_short_video_data": {"content_growth_analyst"},
    "analyze_live_commerce_data": {"live_conversion_analyst"},
    "analyze_attribution_and_leads": {"attribution_lead_analyst"},
    "drilldown_commerce_metric": {
        "content_growth_analyst",
        "live_conversion_analyst",
        "attribution_lead_analyst",
    },
}


def tool_catalog() -> ToolCatalog:
    return ToolCatalog(
        tools=[
            ToolDescriptor(
                name=name,
                allowed_callers=sorted(callers),
            )
            for name, callers in TOOL_ALLOWED_CALLERS.items()
        ]
    )
