"""Deterministic recovery policy for MiniClaw native run records."""

from typing import Literal

from pydantic import Field, model_validator

from .models import StrictModel, TerminalStatus
from .native_models import (
    NativeRunPhase,
    NativeRunResult,
    OperatorViewState,
    SubmissionState,
)
from .native_presenter import build_operator_result_view


NativeRecoveryScenario = Literal[
    "active_run_observation",
    "preflight_blocked",
    "submission_outcome_uncertain",
    "execution_blocked",
    "partial_operator_review",
    "operator_projection_unavailable",
    "completed_no_recovery",
]
NativeNewRunPolicy = Literal[
    "forbidden_until_original_resolved",
    "allowed_after_correction_and_new_authorization",
    "optional_after_operator_review_and_new_authorization",
    "not_needed",
]
NativeRecoveryStep = Literal[
    "read_same_run",
    "read_task_catalog",
    "inspect_runtime_configuration",
    "inspect_redacted_audit",
    "correct_configuration_or_input",
    "correct_operator_projection_contract",
    "operator_review",
    "escalate_to_administrator",
    "create_new_run_after_authorization",
    "no_action_required",
]
NativeForbiddenRecoveryStep = Literal[
    "automatic_retry",
    "reuse_idempotency_key_for_changed_payload",
    "create_replacement_run_before_resolution",
    "expose_raw_model_output",
    "rewrite_historical_evidence",
    "write_external_business_system",
]


class NativeRecoverySnapshot(StrictModel):
    """Minimal state needed to select a recovery path without model output."""

    phase: NativeRunPhase
    submission_state: SubmissionState
    terminal_status: TerminalStatus | None = None
    operator_view_state: OperatorViewState

    @model_validator(mode="after")
    def validate_state_combination(self) -> "NativeRecoverySnapshot":
        if self.phase == "settled" and self.terminal_status is None:
            raise ValueError("settled 恢复快照必须包含 terminal_status")
        if self.phase != "settled" and self.terminal_status is not None:
            raise ValueError("未结算恢复快照不能提前声明 terminal_status")
        if self.terminal_status is None and self.operator_view_state != "processing":
            raise ValueError("未结算任务的运营视图必须为 processing")
        allowed_views = {
            "completed": {"ready", "unavailable"},
            "partial": {"needs_review", "unavailable"},
            "blocked": {"unavailable"},
            "uncertain": {"unavailable"},
        }
        if (
            self.terminal_status is not None
            and self.operator_view_state
            not in allowed_views[self.terminal_status]
        ):
            raise ValueError("terminal_status 与 operator_view_state 不一致")
        return self


class NativeRecoveryPlan(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    result_type: Literal["miniclaw_native_recovery_plan"] = (
        "miniclaw_native_recovery_plan"
    )
    source: Literal["native_runtime_state_only"] = "native_runtime_state_only"
    scenario: NativeRecoveryScenario
    automatic_retry_allowed: Literal[False] = False
    same_run_observation_required: bool
    new_run_policy: NativeNewRunPolicy
    allowed_steps: list[NativeRecoveryStep] = Field(min_length=1)
    forbidden_steps: list[NativeForbiddenRecoveryStep] = Field(min_length=1)
    resolution_gate: str = Field(min_length=1, max_length=500)
    operator_message: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_unique_steps(self) -> "NativeRecoveryPlan":
        if len(self.allowed_steps) != len(set(self.allowed_steps)):
            raise ValueError("allowed_steps 不能重复")
        if len(self.forbidden_steps) != len(set(self.forbidden_steps)):
            raise ValueError("forbidden_steps 不能重复")
        return self


_BASE_FORBIDDEN_STEPS: list[NativeForbiddenRecoveryStep] = [
    "automatic_retry",
    "reuse_idempotency_key_for_changed_payload",
    "expose_raw_model_output",
    "rewrite_historical_evidence",
    "write_external_business_system",
]


def _plan(
    *,
    scenario: NativeRecoveryScenario,
    same_run_observation_required: bool,
    new_run_policy: NativeNewRunPolicy,
    allowed_steps: list[NativeRecoveryStep],
    resolution_gate: str,
    operator_message: str,
    forbid_replacement: bool = False,
) -> NativeRecoveryPlan:
    forbidden_steps = list(_BASE_FORBIDDEN_STEPS)
    if forbid_replacement:
        forbidden_steps.append("create_replacement_run_before_resolution")
    return NativeRecoveryPlan(
        scenario=scenario,
        same_run_observation_required=same_run_observation_required,
        new_run_policy=new_run_policy,
        allowed_steps=allowed_steps,
        forbidden_steps=forbidden_steps,
        resolution_gate=resolution_gate,
        operator_message=operator_message,
    )


def plan_native_recovery(
    snapshot: NativeRecoverySnapshot,
) -> NativeRecoveryPlan:
    """Return the only permitted recovery path for a normalized run state."""
    if (
        snapshot.submission_state == "uncertain"
        or snapshot.terminal_status == "uncertain"
    ):
        return _plan(
            scenario="submission_outcome_uncertain",
            same_run_observation_required=True,
            new_run_policy="forbidden_until_original_resolved",
            allowed_steps=[
                "read_same_run",
                "read_task_catalog",
                "inspect_redacted_audit",
                "escalate_to_administrator",
            ],
            resolution_gate=(
                "先通过同一任务记录和脱敏审计确认原提交是否生效；在原任务结果"
                "仍不确定时，不得创建替代任务。"
            ),
            operator_message=(
                "本次提交状态暂时无法确认。系统不会自动重试，请保留当前任务并"
                "联系管理员核对。"
            ),
            forbid_replacement=True,
        )

    if snapshot.phase != "settled":
        return _plan(
            scenario="active_run_observation",
            same_run_observation_required=True,
            new_run_policy="forbidden_until_original_resolved",
            allowed_steps=["read_same_run", "read_task_catalog"],
            resolution_gate=(
                "继续只读观察同一任务，直到任务结算或被明确判定为阻断/不确定。"
            ),
            operator_message="分析仍在处理中，请继续查看当前任务，不要重复提交。",
            forbid_replacement=True,
        )

    if (
        snapshot.terminal_status == "blocked"
        and snapshot.submission_state == "not_attempted"
    ):
        return _plan(
            scenario="preflight_blocked",
            same_run_observation_required=False,
            new_run_policy="allowed_after_correction_and_new_authorization",
            allowed_steps=[
                "inspect_runtime_configuration",
                "correct_configuration_or_input",
                "create_new_run_after_authorization",
            ],
            resolution_gate=(
                "修正配置或输入，通过预检，并由操作者重新确认模型费用；新任务必须"
                "使用新的幂等键。"
            ),
            operator_message="任务尚未提交，请修正配置或输入后重新确认并创建新任务。",
        )

    if snapshot.terminal_status == "blocked":
        return _plan(
            scenario="execution_blocked",
            same_run_observation_required=False,
            new_run_policy="allowed_after_correction_and_new_authorization",
            allowed_steps=[
                "inspect_redacted_audit",
                "correct_configuration_or_input",
                "operator_review",
                "create_new_run_after_authorization",
            ],
            resolution_gate=(
                "管理员根据脱敏审计确认阻断根因并完成修正；操作者重新确认模型费用后，"
                "方可使用新的幂等键创建新任务。"
            ),
            operator_message="任务已阻断且没有可交付结果，请由管理员核对后再决定是否新建任务。",
        )

    if (
        snapshot.terminal_status == "partial"
        and snapshot.operator_view_state == "needs_review"
    ):
        return _plan(
            scenario="partial_operator_review",
            same_run_observation_required=False,
            new_run_policy="optional_after_operator_review_and_new_authorization",
            allowed_steps=[
                "operator_review",
                "inspect_redacted_audit",
                "create_new_run_after_authorization",
            ],
            resolution_gate=(
                "先由运营人员阅读结果中的限制和未解决事项；只有需要补充分析时，"
                "重新确认模型费用并使用新的幂等键创建范围明确的新任务。"
            ),
            operator_message="本次结果可供复核，请先确认限制与缺失项，再决定是否补充分析。",
        )

    if snapshot.operator_view_state == "unavailable":
        return _plan(
            scenario="operator_projection_unavailable",
            same_run_observation_required=False,
            new_run_policy="allowed_after_correction_and_new_authorization",
            allowed_steps=[
                "inspect_redacted_audit",
                "correct_operator_projection_contract",
                "operator_review",
                "create_new_run_after_authorization",
            ],
            resolution_gate=(
                "管理员先定位并修正运营结果投影契约；禁止直接展示原始模型输出。"
                "如需重新分析，必须重新授权并使用新的幂等键。"
            ),
            operator_message="任务已结束，但结果未通过运营展示校验，请联系管理员处理。",
        )

    return _plan(
        scenario="completed_no_recovery",
        same_run_observation_required=False,
        new_run_policy="not_needed",
        allowed_steps=["no_action_required"],
        resolution_gate="结果已完成并通过运营展示校验，无需恢复或重跑。",
        operator_message="任务已完成，可直接查看经营结论和行动建议。",
    )


def build_native_recovery_plan(record: NativeRunResult) -> NativeRecoveryPlan:
    """Build a recovery plan from a persisted native run without raw output."""
    operator_view = build_operator_result_view(record)
    return plan_native_recovery(
        NativeRecoverySnapshot(
            phase=record.phase,
            submission_state=record.submission_state,
            terminal_status=record.terminal_status,
            operator_view_state=operator_view.view_state,
        )
    )
