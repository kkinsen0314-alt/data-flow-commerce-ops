"""Public models for the MiniClaw native runtime integration."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .models import DatasetType, Domain, StrictModel, TerminalStatus


NativeRunPhase = Literal[
    "reserved",
    "preflight",
    "session_created",
    "submitted",
    "running",
    "settled",
]
NativeExecutionState = Literal["pending", "settled", "unresolved"]
SubmissionState = Literal[
    "not_attempted",
    "attempted",
    "accepted",
    "uncertain",
]
AttemptLayer = Literal["parent_dispatch", "specialist_tool"]
AttemptStatus = Literal["started", "completed", "failed", "blocked"]
ProposalDisposition = Literal["pending", "admitted", "coalesced", "rejected"]
StrategyReferenceValidationStatus = Literal["pass", "failed"]
OperatorViewState = Literal[
    "processing",
    "ready",
    "needs_review",
    "unavailable",
]
NativeDataSourceType = Literal[
    "local_file",
    "mysql",
    "postgresql",
    "feishu_bitable",
    "feishu_spreadsheet",
    "http_api",
    "mcp",
]
NativeDataSourceTypeStatus = Literal["enabled", "configurable"]
NativeDataSourceCategory = Literal[
    "file",
    "database",
    "application",
    "api",
    "connector",
]


class NativeDatasetInput(StrictModel):
    dataset_type: DatasetType
    file_path: str = Field(min_length=1, max_length=4096)


class NativeDatasetReference(StrictModel):
    dataset_id: str = Field(pattern=r"^ds_[A-Za-z0-9_-]+$")
    dataset_type: DatasetType
    file_path: str = Field(min_length=1, max_length=4096)
    synthetic: Literal[True] = True


class NativeRunRequest(StrictModel):
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$",
    )
    requested_domains: list[Domain] = Field(min_length=1, max_length=3)
    datasets: list[NativeDatasetInput] = Field(min_length=1, max_length=6)
    objective: str = Field(min_length=1, max_length=1000)
    include_strategy: bool = True
    authorized_model_execution: Literal[True]

    @model_validator(mode="after")
    def validate_unique_values(self) -> "NativeRunRequest":
        if len(self.requested_domains) != len(set(self.requested_domains)):
            raise ValueError("requested_domains 不能重复")
        normalized_paths = [item.file_path.casefold() for item in self.datasets]
        if len(normalized_paths) != len(set(normalized_paths)):
            raise ValueError("datasets.file_path 不能重复")
        return self


class NativeOperatorRunRequest(StrictModel):
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$",
    )
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    requested_domains: list[Domain] = Field(min_length=1, max_length=3)
    objective: str = Field(min_length=1, max_length=1000)
    include_strategy: bool = True
    fee_confirmation: Literal["confirmed"]
    authorized_model_execution: Literal[True]

    @model_validator(mode="after")
    def validate_unique_domains(self) -> "NativeOperatorRunRequest":
        if len(self.requested_domains) != len(set(self.requested_domains)):
            raise ValueError("requested_domains 不能重复")
        return self


class NativeAttempt(StrictModel):
    attempt_id: str = Field(min_length=1)
    layer: AttemptLayer
    actor: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)
    attempt_number: int = Field(ge=1)
    subagent_type: str | None = None
    status: AttemptStatus
    started_at: datetime
    completed_at: datetime | None = None
    service_run_id: str | None = None
    analysis_run_id: str | None = None
    reason_code: str | None = None
    isolation_argument_present: bool | None = None
    run_in_background_argument_present: bool | None = None
    run_in_background_value: bool | None = None
    strategy_reference_validation: StrategyReferenceValidationStatus | None = None
    strategy_reference_error_codes: list[str] = Field(default_factory=list)


class NativeLedgerSummary(StrictModel):
    parent_agent_attempts: int = Field(ge=0)
    specialist_tool_attempts: int = Field(ge=0)
    total_attempts: int = Field(ge=0)
    completed_attempts: int = Field(ge=0)
    failed_or_blocked_attempts: int = Field(ge=0)
    unfinished_attempts: int = Field(ge=0)
    service_run_ids: list[str] = Field(default_factory=list)
    analysis_run_ids: list[str] = Field(default_factory=list)


class NativeProviderProposal(StrictModel):
    proposal_id: str = Field(min_length=1)
    layer: AttemptLayer
    actor: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)
    proposal_number: int = Field(ge=1)
    disposition: ProposalDisposition
    received_at: datetime
    disposition_at: datetime | None = None
    canonical_tool_call_id: str | None = None
    subagent_type: str | None = None
    reason_code: str | None = None


class NativeProposalSummary(StrictModel):
    total_proposals: int = Field(ge=0)
    admitted_proposals: int = Field(ge=0)
    coalesced_proposals: int = Field(ge=0)
    rejected_proposals: int = Field(ge=0)
    pending_proposals: int = Field(ge=0)


class NativeReconciliation(StrictModel):
    source: Literal["project017_redacted_runtime_audit"] = (
        "project017_redacted_runtime_audit"
    )
    audit_available: bool
    final_response_structured: bool
    reported_total_attempts: int | None = Field(default=None, ge=0)
    observed_total_attempts: int = Field(ge=0)
    merged_ledger_accurate: bool | None = None
    reported_service_run_ids: list[str] | None = None
    reported_analysis_run_ids: list[str] | None = None
    service_run_ids_match: bool | None = None
    analysis_run_ids_match: bool | None = None
    strategy_cross_packet_references_valid: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class NativeAuthoritativeResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    result_type: Literal["project017_native_audit_result"] = (
        "project017_native_audit_result"
    )
    source: Literal["project017_redacted_runtime_audit"] = (
        "project017_redacted_runtime_audit"
    )
    workflow_run_id: str = Field(pattern=r"^wf_[A-Za-z0-9_-]+$")
    terminal_status: TerminalStatus
    parent_agent_attempts: int = Field(ge=0)
    specialist_tool_attempts: int = Field(ge=0)
    total_attempts: int = Field(ge=0)
    completed_attempts: int = Field(ge=0)
    failed_or_blocked_attempts: int = Field(ge=0)
    unfinished_attempts: int = Field(ge=0)
    service_run_ids: list[str] = Field(default_factory=list)
    analysis_run_ids: list[str] = Field(default_factory=list)


class NativeOperatorMetadata(StrictModel):
    title: str = Field(min_length=1, max_length=60)
    objective: str = Field(min_length=1, max_length=1000)
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    created_by: str = Field(min_length=1, max_length=512)


class NativeRunResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    result_type: Literal["miniclaw_native_run"] = "miniclaw_native_run"
    mode: Literal["miniclaw_native"] = "miniclaw_native"
    workflow_run_id: str = Field(pattern=r"^wf_[A-Za-z0-9_-]+$")
    idempotency_key: str = Field(min_length=8, max_length=128)
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    workspace_jid: str = Field(min_length=1, max_length=512)
    session_id: str | None = None
    platform_run_id: str | None = None
    phase: NativeRunPhase
    submission_state: SubmissionState
    terminal_status: TerminalStatus | None = None
    requested_domains: list[Domain] = Field(min_length=1)
    datasets: list[NativeDatasetReference] = Field(min_length=1)
    include_strategy: bool
    synthetic: Literal[True] = True
    operator_visible: bool = False
    operator_metadata: NativeOperatorMetadata | None = None
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None = None
    settled_at: datetime | None = None
    platform_status: str | None = None
    observed_execution_state: NativeExecutionState = "pending"
    final_response: str | None = None
    attempts: list[NativeAttempt] = Field(default_factory=list)
    ledger: NativeLedgerSummary
    provider_proposals: list[NativeProviderProposal] = Field(default_factory=list)
    proposal_summary: NativeProposalSummary = Field(
        default_factory=lambda: NativeProposalSummary(
            total_proposals=0,
            admitted_proposals=0,
            coalesced_proposals=0,
            rejected_proposals=0,
            pending_proposals=0,
        )
    )
    reconciliation: NativeReconciliation
    authoritative_result: NativeAuthoritativeResult | None = None
    unresolved_items: list[str] = Field(default_factory=list)


class NativeOperatorMetric(StrictModel):
    label: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=120)
    context: str | None = Field(default=None, max_length=240)


class NativeOperatorFinding(StrictModel):
    domain: Domain
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=600)
    metrics: list[NativeOperatorMetric] = Field(default_factory=list, max_length=8)
    evidence_basis: list[str] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=8)


class NativeOperatorAction(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    priority: Literal["high", "medium", "low"]
    owner: str = Field(min_length=1, max_length=80)
    due_window: str = Field(min_length=1, max_length=80)
    rationale: str = Field(min_length=1, max_length=400)
    verification: str = Field(min_length=1, max_length=400)
    guardrails: list[str] = Field(default_factory=list, max_length=8)


class NativeOperatorResultContent(StrictModel):
    headline: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=800)
    findings: list[NativeOperatorFinding] = Field(default_factory=list, max_length=12)
    actions: list[NativeOperatorAction] = Field(default_factory=list, max_length=12)
    notices: list[str] = Field(default_factory=list, max_length=12)


class NativeOperatorResultView(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    result_type: Literal["miniclaw_operator_result"] = "miniclaw_operator_result"
    task_reference: str = Field(
        min_length=12,
        max_length=12,
        pattern=r"^[A-F0-9]{12}$",
    )
    view_state: OperatorViewState
    terminal_status: TerminalStatus | None = None
    requested_domains: list[Domain]
    synthetic: Literal[True] = True
    updated_at: datetime
    headline: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=800)
    findings: list[NativeOperatorFinding] = Field(default_factory=list)
    actions: list[NativeOperatorAction] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)


class NativeOperatorTaskSummary(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    result_type: Literal["miniclaw_operator_task"] = "miniclaw_operator_task"
    task_reference: str = Field(
        min_length=12,
        max_length=12,
        pattern=r"^[A-F0-9]{12}$",
    )
    view_state: OperatorViewState
    terminal_status: TerminalStatus | None = None
    requested_domains: list[Domain]
    include_strategy: bool
    created_at: datetime
    updated_at: datetime
    headline: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=800)


class NativeOperatorTaskCatalog(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    result_type: Literal["miniclaw_operator_task_catalog"] = (
        "miniclaw_operator_task_catalog"
    )
    returned_count: int = Field(ge=0, le=50)
    has_more: bool
    tasks: list[NativeOperatorTaskSummary] = Field(max_length=50)


class NativeRuntimeConfiguration(StrictModel):
    mode: Literal["miniclaw_native"] = "miniclaw_native"
    base_url: str
    workspace_configured: bool
    credentials_configured: bool
    ready: bool
    agent_profile_name: str
    project_root: str
    model_submission_requires_explicit_authorization: Literal[True] = True
    automatic_model_retry: Literal[False] = False


class NativePeriod13Dataset(StrictModel):
    dataset_type: DatasetType
    label: str
    file_path: str
    row_count: int = Field(ge=0)
    quality_status: Literal["pass", "partial", "blocked"]


class NativePeriod13Metrics(StrictModel):
    paid_order_count: int = Field(ge=0)
    paid_gmv: str
    order_lead_coverage: float = Field(ge=0, le=1)
    paid_lead_conversion: float = Field(ge=0, le=1)
    followup_within_24h: float = Field(ge=0, le=1)
    intentional_missing_followup_count: int = Field(ge=0)


class NativePeriod13Summary(StrictModel):
    mode: Literal["synthetic_fixture"] = "synthetic_fixture"
    label: str
    start: str
    end: str
    status: Literal["pass", "partial", "blocked"]
    synthetic: Literal[True] = True
    checks_total: int = Field(ge=0)
    checks_passed: int = Field(ge=0)
    total_rows: int = Field(ge=0)
    datasets: list[NativePeriod13Dataset]
    metrics: NativePeriod13Metrics
    source_artifact: Literal["artifacts/period-13-data-validation-v1.json"] = (
        "artifacts/period-13-data-validation-v1.json"
    )


class NativeDataSourceSummary(StrictModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source_type: NativeDataSourceType
    source_type_label: str = Field(min_length=1)
    status: Literal["ready", "degraded", "unavailable"]
    synthetic: bool
    access_mode: Literal["read_only"] = "read_only"
    dataset_count: int = Field(ge=0)
    record_count: int = Field(ge=0)
    available_domains: list[Domain]
    dataset_types: list[DatasetType]
    dataset_labels: list[str] = Field(default_factory=list)
    data_period: str | None = None


class NativeDataSourceTypeOption(StrictModel):
    type_id: NativeDataSourceType
    display_name: str = Field(min_length=1)
    category: NativeDataSourceCategory
    status: NativeDataSourceTypeStatus
    description: str = Field(min_length=1)
    connection_method: str = Field(min_length=1)
    requires_authorization: bool
    read_only_supported: bool


class NativeDataSourceCatalog(StrictModel):
    default_source_id: str
    sources: list[NativeDataSourceSummary]
    source_types: list[NativeDataSourceTypeOption]
