"""Validated workflow models for the commerce operations contract."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Domain = Literal["content_growth", "live_conversion", "attribution_leads"]
DatasetType = Literal[
    "short_video",
    "live_session",
    "account",
    "channel_lead",
    "sales_followup",
    "order",
]
Dimension = Literal[
    "account",
    "content",
    "publish_time",
    "live_session",
    "channel",
    "lead_source",
    "sales_owner",
    "order_status",
]
TerminalStatus = Literal["completed", "partial", "blocked", "uncertain"]
AnalystRole = Literal[
    "content_growth_analyst",
    "live_conversion_analyst",
    "attribution_lead_analyst",
]
AgentRole = Literal[
    "commerce_ops_supervisor",
    "content_growth_analyst",
    "live_conversion_analyst",
    "attribution_lead_analyst",
    "commerce_review_strategist",
]
ToolName = Literal[
    "inspect_commerce_data",
    "analyze_short_video_data",
    "analyze_live_commerce_data",
    "analyze_attribution_and_leads",
    "drilldown_commerce_metric",
]
MetricValue = str | int | float | bool | None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} 不能重复")


class TimeRange(StrictModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_order(self) -> "TimeRange":
        if self.end <= self.start:
            raise ValueError("time_range.end 必须晚于 start")
        return self


class DeliveryRequirements(StrictModel):
    language: Literal["zh-CN"] = "zh-CN"
    format: Literal["structured_json", "web_report"] = "structured_json"
    top_n: int = Field(default=10, ge=1, le=50)
    include_actions: bool = True


class CommerceOpsRunRequest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    message_type: Literal["commerce_ops_run_request"] = (
        "commerce_ops_run_request"
    )
    workflow_run_id: str = Field(pattern=r"^wf_[A-Za-z0-9_-]+$")
    requested_at: datetime
    objective: str = Field(min_length=1)
    dataset_refs: list[str] = Field(min_length=1)
    requested_domains: list[Domain] = Field(min_length=1)
    requested_dimensions: list[Dimension] = Field(default_factory=list)
    time_range: TimeRange
    delivery: DeliveryRequirements
    constraints: list[str] = Field(default_factory=list)
    synthetic: bool

    @model_validator(mode="after")
    def validate_unique_requests(self) -> "CommerceOpsRunRequest":
        _require_unique(self.dataset_refs, "dataset_refs")
        _require_unique(self.requested_domains, "requested_domains")
        _require_unique(self.requested_dimensions, "requested_dimensions")
        return self


class FieldDefinition(StrictModel):
    name: str = Field(min_length=1)
    data_type: Literal["string", "integer", "number", "boolean", "datetime"]
    nullable: bool
    semantic_role: Literal[
        "metric",
        "dimension",
        "relationship_key",
        "timestamp",
        "cost",
        "identifier",
    ]
    description: str = Field(min_length=1)


class RelationshipKey(StrictModel):
    field: str = Field(min_length=1)
    entity_type: Literal[
        "account",
        "content",
        "click",
        "live_session",
        "lead",
        "sales_owner",
        "order",
    ]
    stable: bool
    coverage_ratio: float = Field(ge=0, le=1)
    target_dataset_types: list[DatasetType] = Field(default_factory=list)
    hashed: bool
    note: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_hash_for_sensitive_entities(self) -> "RelationshipKey":
        if self.stable and self.entity_type in {
            "account",
            "lead",
            "sales_owner",
            "order",
        } and not self.hashed:
            raise ValueError(
                "稳定的账号、线索、销售负责人或订单关联键必须脱敏"
            )
        return self


class DatasetQuality(StrictModel):
    status: Literal["pass", "partial", "blocked"]
    row_count: int = Field(ge=0)
    duplicate_rows: int = Field(ge=0)
    missing_required_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AnalysisReadiness(StrictModel):
    cross_domain_attribution: Literal["allowed", "blocked"]
    roi_calculation: Literal["allowed", "blocked"]
    reasons: list[str] = Field(default_factory=list)


class DatasetManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    message_type: Literal["dataset_manifest"] = "dataset_manifest"
    workflow_run_id: str = Field(pattern=r"^wf_[A-Za-z0-9_-]+$")
    dataset_id: str = Field(pattern=r"^ds_[A-Za-z0-9_-]+$")
    dataset_type: DatasetType
    source_name: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")
    synthetic: bool
    fields: list[FieldDefinition] = Field(min_length=1)
    available_dimensions: list[Dimension] = Field(default_factory=list)
    relationship_keys: list[RelationshipKey] = Field(default_factory=list)
    data_quality: DatasetQuality
    analysis_readiness: AnalysisReadiness
    contains_sensitive_data: bool
    redaction_applied: bool

    @model_validator(mode="after")
    def validate_manifest(self) -> "DatasetManifest":
        _require_unique([item.name for item in self.fields], "fields.name")
        _require_unique(self.available_dimensions, "available_dimensions")
        if self.contains_sensitive_data and not self.redaction_applied:
            raise ValueError("包含敏感数据的 manifest 必须声明已脱敏")
        if self.data_quality.status == "blocked" and not (
            self.data_quality.missing_required_fields
            or self.data_quality.warnings
        ):
            raise ValueError("blocked 数据质量必须说明缺失字段或警告")
        return self


class ServiceCall(StrictModel):
    tool_name: ToolName
    caller_role: AgentRole
    attempt: int = Field(ge=1)
    service_run_id: str = Field(pattern=r"^srv_[A-Za-z0-9_-]+$")
    outcome: Literal["success", "failure", "uncertain"]
    duration_ms: float | None = Field(default=None, ge=0)
    side_effect_state: Literal["none", "possible", "confirmed"] = "none"
    automatic_retry: bool = False


class Evidence(StrictModel):
    evidence_id: str = Field(pattern=r"^ev_[A-Za-z0-9_-]+$")
    dataset_id: str = Field(pattern=r"^ds_[A-Za-z0-9_-]+$")
    service_run_id: str = Field(pattern=r"^srv_[A-Za-z0-9_-]+$")
    metric_name: str = Field(min_length=1)
    metric_value: MetricValue
    unit: str = Field(min_length=1)
    scope: dict[str, str] = Field(default_factory=dict)
    calculation: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    synthetic: bool
    data_quality_status: Literal["pass", "partial"]


class Finding(StrictModel):
    finding_id: str = Field(pattern=r"^finding_[A-Za-z0-9_-]+$")
    category: Literal[
        "data_quality",
        "content",
        "live_funnel",
        "channel",
        "lead",
        "sales_followup",
        "order_conversion",
        "attribution",
    ]
    severity: Literal["normal", "attention", "critical", "unknown"]
    statement: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)


class AnalysisPacket(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    message_type: Literal["analysis_packet"] = "analysis_packet"
    workflow_run_id: str = Field(pattern=r"^wf_[A-Za-z0-9_-]+$")
    analysis_run_id: str = Field(pattern=r"^analysis_[A-Za-z0-9_-]+$")
    agent_role: AnalystRole
    domain: Domain
    terminal_status: TerminalStatus
    dataset_ids: list[str] = Field(min_length=1)
    service_calls: list[ServiceCall] = Field(min_length=1)
    evidence: list[Evidence] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_packet(self) -> "AnalysisPacket":
        role_domains = {
            "content_growth_analyst": "content_growth",
            "live_conversion_analyst": "live_conversion",
            "attribution_lead_analyst": "attribution_leads",
        }
        allowed_tools = {
            "content_growth_analyst": {
                "analyze_short_video_data",
                "drilldown_commerce_metric",
            },
            "live_conversion_analyst": {
                "analyze_live_commerce_data",
                "drilldown_commerce_metric",
            },
            "attribution_lead_analyst": {
                "analyze_attribution_and_leads",
                "drilldown_commerce_metric",
            },
        }
        if role_domains[self.agent_role] != self.domain:
            raise ValueError("agent_role 与 domain 不匹配")
        _require_unique(self.dataset_ids, "analysis.dataset_ids")
        _require_unique(
            [item.service_run_id for item in self.service_calls],
            "service_run_id",
        )
        _require_unique(
            [item.evidence_id for item in self.evidence], "evidence_id"
        )
        _require_unique(
            [item.finding_id for item in self.findings], "finding_id"
        )
        for call in self.service_calls:
            if call.caller_role != self.agent_role:
                raise ValueError("service_call.caller_role 与分析 Agent 不一致")
            if call.tool_name not in allowed_tools[self.agent_role]:
                raise ValueError(
                    f"{self.agent_role} 不允许调用 {call.tool_name}"
                )
            if call.outcome == "uncertain" and call.automatic_retry:
                raise ValueError("结果不确定时禁止自动重试")

        successful_calls = {
            item.service_run_id
            for item in self.service_calls
            if item.outcome == "success"
        }
        evidence_ids = {item.evidence_id for item in self.evidence}
        for item in self.evidence:
            if item.service_run_id not in successful_calls:
                raise ValueError(
                    f"{item.evidence_id} 没有对应的成功 service_call"
                )
        for item in self.findings:
            if not set(item.evidence_ids).issubset(evidence_ids):
                raise ValueError(
                    f"{item.finding_id} 引用了不存在的 evidence"
                )

        if self.terminal_status == "completed" and not (
            self.evidence and self.findings
        ):
            raise ValueError("completed 分析必须包含 evidence 和 findings")
        if self.terminal_status == "partial" and not (
            self.evidence or self.missing_evidence
        ):
            raise ValueError("partial 分析必须保留事实或缺失证据")
        if self.terminal_status in {"blocked", "uncertain"}:
            if not self.missing_evidence:
                raise ValueError("blocked/uncertain 分析必须说明 missing_evidence")
            if self.findings:
                raise ValueError("blocked/uncertain 分析不能输出经营 finding")
        return self


class VerificationMetric(StrictModel):
    name: str = Field(min_length=1)
    direction: Literal["increase", "decrease", "maintain", "observe"]
    baseline: MetricValue
    target: MetricValue
    unit: str = Field(min_length=1)
    check_after: str = Field(min_length=1)
    verification_method: str = Field(min_length=1)
    dataset_ids: list[str] = Field(min_length=1)
    requires_cost_data: bool = False


class Action(StrictModel):
    action_id: str = Field(pattern=r"^action_[A-Za-z0-9_-]+$")
    priority: Literal["high", "medium", "low"]
    finding_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    action: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    due_window: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    verification_metric: VerificationMetric
    guardrails: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class DecisionPacket(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    message_type: Literal["decision_packet"] = "decision_packet"
    workflow_run_id: str = Field(pattern=r"^wf_[A-Za-z0-9_-]+$")
    decision_run_id: str = Field(pattern=r"^decision_[A-Za-z0-9_-]+$")
    agent_role: Literal["commerce_review_strategist"] = (
        "commerce_review_strategist"
    )
    source_analysis_ids: list[str] = Field(min_length=1)
    terminal_status: TerminalStatus
    actions: list[Action] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_decision_status(self) -> "DecisionPacket":
        _require_unique(self.source_analysis_ids, "source_analysis_ids")
        _require_unique(
            [item.action_id for item in self.actions], "action_id"
        )
        if self.terminal_status in {"completed", "partial"} and not self.actions:
            raise ValueError("completed/partial 决策必须包含 actions")
        if self.terminal_status in {"blocked", "uncertain"}:
            if self.actions:
                raise ValueError("blocked/uncertain 决策不能输出 action")
            if not self.blocked_reasons:
                raise ValueError("blocked/uncertain 决策必须说明原因")
        return self


class TraceReference(StrictModel):
    trace_id: str = Field(pattern=r"^trace_[A-Za-z0-9_-]+$")
    actor_role: AgentRole
    run_id: str = Field(min_length=1)
    parent_run_id: str | None = None


class DeliveryPackage(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    message_type: Literal["delivery_package"] = "delivery_package"
    workflow_run_id: str = Field(pattern=r"^wf_[A-Za-z0-9_-]+$")
    supervisor_role: Literal["commerce_ops_supervisor"] = (
        "commerce_ops_supervisor"
    )
    terminal_status: TerminalStatus
    analysis_refs: list[str] = Field(min_length=1)
    decision_ref: str | None = None
    headline: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    finding_refs: list[str] = Field(default_factory=list)
    action_refs: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
    trace_refs: list[TraceReference] = Field(default_factory=list)
    requires_human_confirmation: bool

    @model_validator(mode="after")
    def validate_delivery_status(self) -> "DeliveryPackage":
        _require_unique(self.analysis_refs, "delivery.analysis_refs")
        _require_unique(self.finding_refs, "delivery.finding_refs")
        _require_unique(self.action_refs, "delivery.action_refs")
        if self.decision_ref is None and self.action_refs:
            raise ValueError("没有 decision_ref 时不能交付 action_refs")
        if self.terminal_status == "completed" and self.decision_ref is None:
            raise ValueError("completed 交付必须引用 decision_packet")
        if self.terminal_status in {"partial", "blocked", "uncertain"} and not (
            self.unresolved_items or self.requires_human_confirmation
        ):
            raise ValueError("非 completed 交付必须保留未解决事项或人工确认")
        return self


class WorkflowError(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    message_type: Literal["workflow_error"] = "workflow_error"
    workflow_run_id: str = Field(pattern=r"^wf_[A-Za-z0-9_-]+$")
    stage: Literal[
        "intake", "inspection", "analysis", "decision", "delivery"
    ]
    code: Literal[
        "INVALID_INPUT",
        "PAYLOAD_TOO_LARGE",
        "RELATION_KEY_MISSING",
        "COST_FIELD_MISSING",
        "ANALYSIS_UNAVAILABLE",
        "ANALYSIS_OUTCOME_UNCERTAIN",
        "DIAGNOSIS_INCOMPLETE",
        "DECISION_BLOCKED",
        "DELIVERY_UNCERTAIN",
    ]
    retryable: bool
    outcome_uncertain: bool
    human_action: str = Field(min_length=1)
    safe_message: str = Field(min_length=1)


class CommerceWorkflowBundle(StrictModel):
    bundle_type: Literal["commerce_ops_contract_test_bundle"] = (
        "commerce_ops_contract_test_bundle"
    )
    synthetic: Literal[True] = True
    normalized_request: CommerceOpsRunRequest
    dataset_manifests: list[DatasetManifest] = Field(min_length=1)
    analysis_packets: list[AnalysisPacket] = Field(min_length=1)
    decision_packet: DecisionPacket | None
    delivery_package: DeliveryPackage
    error_example: WorkflowError

    @model_validator(mode="after")
    def validate_reference_chain(self) -> "CommerceWorkflowBundle":
        workflow_id = self.normalized_request.workflow_run_id
        if not self.normalized_request.synthetic:
            raise ValueError("契约测试 bundle 只能使用 synthetic request")

        dataset_by_id = {item.dataset_id: item for item in self.dataset_manifests}
        if len(dataset_by_id) != len(self.dataset_manifests):
            raise ValueError("dataset_id 不能重复")
        if not set(self.normalized_request.dataset_refs).issubset(dataset_by_id):
            raise ValueError("request 引用了不存在的 dataset")

        for manifest in self.dataset_manifests:
            if manifest.workflow_run_id != workflow_id:
                raise ValueError("dataset_manifest.workflow_run_id 不一致")
            if not manifest.synthetic:
                raise ValueError("合成契约样例不能混入真实数据 manifest")

        analysis_by_id = {
            item.analysis_run_id: item for item in self.analysis_packets
        }
        if len(analysis_by_id) != len(self.analysis_packets):
            raise ValueError("analysis_run_id 不能重复")

        evidence_by_id: dict[str, Evidence] = {}
        finding_by_id: dict[str, Finding] = {}
        for packet in self.analysis_packets:
            if packet.workflow_run_id != workflow_id:
                raise ValueError("analysis_packet.workflow_run_id 不一致")
            if not set(packet.dataset_ids).issubset(dataset_by_id):
                raise ValueError(
                    f"{packet.analysis_run_id} 引用了不存在的 dataset"
                )
            for evidence in packet.evidence:
                if evidence.evidence_id in evidence_by_id:
                    raise ValueError("跨 analysis_packet 的 evidence_id 不能重复")
                if evidence.dataset_id not in packet.dataset_ids:
                    raise ValueError(
                        f"{evidence.evidence_id} 的 dataset 不在 analysis_packet 中"
                    )
                if not evidence.synthetic:
                    raise ValueError("合成契约样例的 evidence 必须为 synthetic")
                evidence_by_id[evidence.evidence_id] = evidence
            for finding in packet.findings:
                if finding.finding_id in finding_by_id:
                    raise ValueError("跨 analysis_packet 的 finding_id 不能重复")
                finding_by_id[finding.finding_id] = finding

            if packet.domain == "attribution_leads" and any(
                item.category == "attribution" for item in packet.findings
            ):
                manifests = [dataset_by_id[item] for item in packet.dataset_ids]
                stable_keys = [
                    key
                    for manifest in manifests
                    for key in manifest.relationship_keys
                    if key.stable and key.coverage_ratio > 0
                ]
                if not stable_keys or not any(
                    manifest.analysis_readiness.cross_domain_attribution
                    == "allowed"
                    for manifest in manifests
                ):
                    raise ValueError("没有稳定关联键时禁止输出跨域 attribution")

        decision = self.decision_packet
        action_by_id: dict[str, Action] = {}
        if decision is not None:
            if decision.workflow_run_id != workflow_id:
                raise ValueError("decision_packet.workflow_run_id 不一致")
            if not set(decision.source_analysis_ids).issubset(analysis_by_id):
                raise ValueError("decision_packet 引用了不存在的 analysis")
            for analysis_id in decision.source_analysis_ids:
                if analysis_by_id[analysis_id].terminal_status not in {
                    "completed",
                    "partial",
                }:
                    raise ValueError("blocked/uncertain 分析不能进入策略阶段")
            for action in decision.actions:
                if not set(action.finding_ids).issubset(finding_by_id):
                    raise ValueError(
                        f"{action.action_id} 引用了不存在的 finding"
                    )
                if not set(action.evidence_ids).issubset(evidence_by_id):
                    raise ValueError(
                        f"{action.action_id} 引用了不存在的 evidence"
                    )
                if not set(action.verification_metric.dataset_ids).issubset(
                    dataset_by_id
                ):
                    raise ValueError(
                        f"{action.action_id} 的复验指标引用了不存在的 dataset"
                    )
                if action.action_id in action_by_id:
                    raise ValueError("action_id 不能重复")
                action_by_id[action.action_id] = action

        roi_requested = any(
            "roi" in evidence.metric_name.lower()
            for evidence in evidence_by_id.values()
        ) or any(
            "roi" in action.verification_metric.name.lower()
            or action.verification_metric.requires_cost_data
            for action in action_by_id.values()
        )
        if roi_requested:
            has_cost_field = any(
                field.semantic_role == "cost"
                for manifest in self.dataset_manifests
                for field in manifest.fields
            )
            roi_allowed = any(
                manifest.analysis_readiness.roi_calculation == "allowed"
                for manifest in self.dataset_manifests
            )
            if not (has_cost_field and roi_allowed):
                raise ValueError("无成本字段或 ROI 未放行时禁止输出 ROI")

        delivery = self.delivery_package
        if delivery.workflow_run_id != workflow_id:
            raise ValueError("delivery_package.workflow_run_id 不一致")
        if not set(delivery.analysis_refs).issubset(analysis_by_id):
            raise ValueError("delivery_package 引用了不存在的 analysis")
        if delivery.decision_ref is not None:
            if decision is None or delivery.decision_ref != decision.decision_run_id:
                raise ValueError("delivery_package.decision_ref 不一致")
        if not set(delivery.finding_refs).issubset(finding_by_id):
            raise ValueError("delivery_package 引用了不存在的 finding")
        if not set(delivery.action_refs).issubset(action_by_id):
            raise ValueError("delivery_package 引用了不存在的 action")
        if self.error_example.workflow_run_id != workflow_id:
            raise ValueError("error_example.workflow_run_id 不一致")
        return self
