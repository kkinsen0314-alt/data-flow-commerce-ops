from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .models import StrictModel
from .visualization_models import VisualizationFilters


ConversationLifecycle = Literal[
    "provisioning",
    "ready",
    "creation_uncertain",
    "creation_failed",
]
ConversationSubmissionState = Literal[
    "reserved",
    "accepted",
    "completed",
    "uncertain",
    "rejected",
    "failed",
]
ConversationStatus = Literal["ready", "processing", "uncertain", "unavailable"]
ConversationRole = Literal["user", "assistant"]


class ConversationContextRequest(StrictModel):
    kind: Literal["analysis_task", "visualization_view"]
    task_reference: str | None = Field(
        default=None, pattern=r"^[A-F0-9]{12}$"
    )
    visualization_filters: VisualizationFilters | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "ConversationContextRequest":
        if self.kind == "analysis_task":
            if self.task_reference is None or self.visualization_filters is not None:
                raise ValueError("分析任务上下文必须且只能指定任务编号")
        elif self.task_reference is not None:
            raise ValueError("数据看板上下文不能指定任务编号")
        return self


class ConversationContextLink(StrictModel):
    kind: Literal["analysis_task", "visualization_view"]
    reference: str
    title: str
    summary: str
    return_path: str


class ConversationSubmissionRecord(StrictModel):
    submission_key: str
    request_fingerprint: str
    content_hash: str
    display_content: str | None = None
    context: ConversationContextLink | None = None
    state: ConversationSubmissionState
    attempted_at: str
    submitted_at: str | None = None
    message_id: str | None = None
    run_id: str | None = None


class ConversationRecord(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    reference: str = Field(pattern=r"^[A-F0-9]{12}$")
    creation_key: str
    creation_fingerprint: str
    workspace_jid: str
    user_id: str
    session_id: str | None = None
    title: str
    lifecycle: ConversationLifecycle
    created_at: str
    updated_at: str
    submissions: list[ConversationSubmissionRecord] = Field(default_factory=list)


class ConversationCreateRequest(StrictModel):
    title: str = Field(default="新对话", min_length=1, max_length=40)
    client_request_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$",
    )

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("会话名称不能为空")
        return normalized


class ConversationSendRequest(StrictModel):
    content: str = Field(min_length=1, max_length=6000)
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$",
    )
    fee_confirmation: Literal["confirmed"]
    authorized_model_execution: Literal[True]
    context: ConversationContextRequest | None = None

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("消息内容不能为空")
        return normalized


class ConversationMessage(StrictModel):
    message_reference: str
    role: ConversationRole
    content: str
    timestamp: str
    truncated: bool = False
    context: ConversationContextLink | None = None


class ConversationSummary(StrictModel):
    conversation_reference: str
    title: str
    status: ConversationStatus
    status_label: str
    latest_preview: str | None = None
    created_at: str
    updated_at: str
    can_send: bool


class ConversationThread(ConversationSummary):
    messages: list[ConversationMessage]
    pending_submission: bool
    query_original_submission_only: bool


class ConversationCatalog(StrictModel):
    conversations: list[ConversationSummary]
