"""Public models for the deterministic commerce operations demo API."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .models import (
    Action,
    AgentRole,
    AnalysisPacket,
    CommerceOpsRunRequest,
    DatasetManifest,
    DatasetType,
    DecisionPacket,
    DeliveryPackage,
    Domain,
    Evidence,
    StrictModel,
    TerminalStatus,
)
from .tool_models import DrilldownResult


class DemoDatasetDescriptor(StrictModel):
    dataset_id: str = Field(pattern=r"^ds_[A-Za-z0-9_-]+$")
    dataset_type: DatasetType
    display_name: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    synthetic: Literal[True] = True


class DemoScenario(StrictModel):
    scenario_id: str = Field(pattern=r"^[a-z][a-z0-9_-]+$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    requested_domains: list[Domain] = Field(min_length=1)
    datasets: list[DemoDatasetDescriptor] = Field(min_length=1)
    mode: Literal["deterministic_demo"] = "deterministic_demo"
    provider_required: Literal[False] = False
    agent_runtime_executed: Literal[False] = False


class DemoScenarioCatalog(StrictModel):
    scenarios: list[DemoScenario] = Field(min_length=1)
    default_scenario_id: str = Field(min_length=1)


class DemoRunRequest(StrictModel):
    scenario_id: Literal["full_commerce_funnel"] = "full_commerce_funnel"
    requested_domains: list[Domain] = Field(
        default_factory=lambda: [
            "content_growth",
            "live_conversion",
            "attribution_leads",
        ],
        min_length=1,
    )
    objective: str = Field(
        default="使用合成数据演示内容、直播、线索与订单的可追溯经营分析。",
        min_length=1,
        max_length=500,
    )
    top_n: int = Field(default=5, ge=1, le=20)
    include_drilldowns: bool = True

    @model_validator(mode="after")
    def validate_domains(self) -> "DemoRunRequest":
        if len(self.requested_domains) != len(set(self.requested_domains)):
            raise ValueError("requested_domains 不能重复")
        return self


class DemoUploadDatasetSpec(StrictModel):
    dataset_id: str = Field(pattern=r"^ds_[A-Za-z0-9_-]+$")
    dataset_type: DatasetType
    file_index: int = Field(ge=0, le=5)
    display_name: str = Field(min_length=1, max_length=100)


class DemoUploadRunRequest(StrictModel):
    datasets: list[DemoUploadDatasetSpec] = Field(min_length=1, max_length=6)
    requested_domains: list[Domain] = Field(min_length=1)
    objective: str = Field(min_length=1, max_length=500)
    top_n: int = Field(default=5, ge=1, le=20)
    include_drilldowns: bool = True
    synthetic: Literal[True] = True

    @model_validator(mode="after")
    def validate_upload_mapping(self) -> "DemoUploadRunRequest":
        dataset_ids = [item.dataset_id for item in self.datasets]
        file_indexes = [item.file_index for item in self.datasets]
        if len(dataset_ids) != len(set(dataset_ids)):
            raise ValueError("dataset_id 不能重复")
        if len(file_indexes) != len(set(file_indexes)):
            raise ValueError("file_index 不能重复")
        if len(self.requested_domains) != len(set(self.requested_domains)):
            raise ValueError("requested_domains 不能重复")
        return self


class DemoUploadedFile(StrictModel):
    file_name: str = Field(min_length=1)
    content: bytes = Field(min_length=1, exclude=True)


class DemoWorkflowStep(StrictModel):
    step_id: str = Field(pattern=r"^step_[A-Za-z0-9_-]+$")
    actor_role: AgentRole
    stage: Literal[
        "route",
        "inspect",
        "analyze",
        "drilldown",
        "decision",
        "delivery",
    ]
    execution_kind: Literal["deterministic_service"] = "deterministic_service"
    terminal_status: TerminalStatus
    label: str = Field(min_length=1)
    dataset_ids: list[str] = Field(default_factory=list)
    service_run_id: str | None = None
    analysis_run_id: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    detail: str = Field(min_length=1)


class DemoSummaryMetric(StrictModel):
    domain: Domain
    metric_name: str = Field(min_length=1)
    metric_value: str | int | float | bool | None
    unit: str = Field(min_length=1)
    evidence_id: str = Field(pattern=r"^ev_[A-Za-z0-9_-]+$")
    synthetic: Literal[True] = True


class DemoRunResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    result_type: Literal["commerce_ops_deterministic_demo"] = (
        "commerce_ops_deterministic_demo"
    )
    mode: Literal["deterministic_demo"] = "deterministic_demo"
    workflow_run_id: str = Field(pattern=r"^wf_[A-Za-z0-9_-]+$")
    started_at: datetime
    completed_at: datetime
    terminal_status: TerminalStatus
    synthetic: Literal[True] = True
    provider_called: Literal[False] = False
    agent_runtime_executed: Literal[False] = False
    scenario: DemoScenario
    normalized_request: CommerceOpsRunRequest
    dataset_manifests: list[DatasetManifest] = Field(min_length=1)
    analysis_packets: list[AnalysisPacket] = Field(default_factory=list)
    drilldowns: list[DrilldownResult] = Field(default_factory=list)
    decision_packet: DecisionPacket | None = None
    delivery_package: DeliveryPackage
    workflow_steps: list[DemoWorkflowStep] = Field(min_length=1)
    summary_metrics: list[DemoSummaryMetric] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
    evidence_boundaries: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_reference_chain(self) -> "DemoRunResult":
        if self.normalized_request.workflow_run_id != self.workflow_run_id:
            raise ValueError("normalized_request.workflow_run_id 不一致")
        manifest_ids = [item.dataset_id for item in self.dataset_manifests]
        if len(manifest_ids) != len(set(manifest_ids)):
            raise ValueError("dataset_manifests.dataset_id 不能重复")
        if not set(self.normalized_request.dataset_refs).issubset(manifest_ids):
            raise ValueError("normalized_request 引用了不存在的数据集")

        analysis_ids = [item.analysis_run_id for item in self.analysis_packets]
        if len(analysis_ids) != len(set(analysis_ids)):
            raise ValueError("analysis_run_id 不能重复")
        evidence: dict[str, Evidence] = {}
        findings: dict[str, object] = {}
        for packet in self.analysis_packets:
            if packet.workflow_run_id != self.workflow_run_id:
                raise ValueError("analysis_packet.workflow_run_id 不一致")
            if not set(packet.dataset_ids).issubset(manifest_ids):
                raise ValueError("analysis_packet 引用了不存在的数据集")
            for item in packet.evidence:
                if item.evidence_id in evidence:
                    raise ValueError("evidence_id 不能重复")
                evidence[item.evidence_id] = item
            for item in packet.findings:
                if item.finding_id in findings:
                    raise ValueError("finding_id 不能重复")
                findings[item.finding_id] = item

        action_ids: set[str] = set()
        if self.decision_packet is not None:
            if not set(self.decision_packet.source_analysis_ids).issubset(
                analysis_ids
            ):
                raise ValueError("decision_packet 引用了不存在的 analysis")
            for action in self.decision_packet.actions:
                self._validate_action(action, evidence, findings)
                action_ids.add(action.action_id)

        delivery = self.delivery_package
        if delivery.workflow_run_id != self.workflow_run_id:
            raise ValueError("delivery_package.workflow_run_id 不一致")
        if not set(delivery.analysis_refs).issubset(analysis_ids):
            raise ValueError("delivery_package 引用了不存在的 analysis")
        if not set(delivery.action_refs).issubset(action_ids):
            raise ValueError("delivery_package 引用了不存在的 action")
        return self

    @staticmethod
    def _validate_action(
        action: Action,
        evidence: dict[str, Evidence],
        findings: dict[str, object],
    ) -> None:
        if not set(action.evidence_ids).issubset(evidence):
            raise ValueError("action 引用了不存在的 evidence")
        if not set(action.finding_ids).issubset(findings):
            raise ValueError("action 引用了不存在的 finding")


class DemoRunList(StrictModel):
    runs: list[DemoRunResult]
