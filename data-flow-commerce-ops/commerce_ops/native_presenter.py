"""Safe operator-facing projection for native MiniClaw results."""

import hashlib
import json
import re

from pydantic import ValidationError

from .native_models import (
    NativeOperatorResultContent,
    NativeOperatorResultView,
    NativeOperatorTaskSummary,
    NativeRunResult,
)
from .native_result_parser import extract_native_result


_INTERNAL_REFERENCE = re.compile(
    r"\b(?:wf|srv|analysis|decision|finding|ev|ds)_[A-Za-z0-9_-]+\b"
    r"|\bcommerce_ops_[A-Za-z0-9_]+\b"
    r"|\b(?:commerce_ops_supervisor|content_growth_analyst|"
    r"live_conversion_analyst|attribution_lead_analyst|"
    r"commerce_review_strategist)\b",
    re.IGNORECASE,
)
_SENSITIVE_LABEL = re.compile(
    r"\b(?:password|passwd|secret|cookie|authorization|bearer|"
    r"api[_ -]?key|access[_ -]?token|refresh[_ -]?token)\b",
    re.IGNORECASE,
)


def operator_task_reference(workflow_run_id: str) -> str:
    digest = hashlib.sha256(workflow_run_id.encode("utf-8")).hexdigest()
    return digest[:12].upper()


def _extract_operator_content(
    final_response: str | None,
) -> NativeOperatorResultContent | None:
    payload = extract_native_result(final_response)
    if payload is None:
        return None
    operator_payload = payload.get("operator_result")
    if not isinstance(operator_payload, dict):
        return None
    serialized = json.dumps(operator_payload, ensure_ascii=False)
    if _INTERNAL_REFERENCE.search(serialized) or _SENSITIVE_LABEL.search(serialized):
        return None
    try:
        return NativeOperatorResultContent.model_validate(operator_payload)
    except ValidationError:
        return None


def build_operator_result_view(record: NativeRunResult) -> NativeOperatorResultView:
    """Project a runtime record without exposing raw model or audit fields."""
    common = {
        "task_reference": operator_task_reference(record.workflow_run_id),
        "terminal_status": record.terminal_status,
        "requested_domains": record.requested_domains,
        "updated_at": record.updated_at,
    }
    if record.phase != "settled" or record.terminal_status is None:
        return NativeOperatorResultView(
            **common,
            view_state="processing",
            headline="分析正在进行",
            summary="系统正在整理经营结论与可执行建议，请稍候查看。",
        )
    if record.terminal_status in {"blocked", "uncertain"}:
        return NativeOperatorResultView(
            **common,
            view_state="unavailable",
            headline="本次分析未生成结果",
            summary="任务执行没有完成，请检查运行环境后重新创建分析任务。",
        )
    content = _extract_operator_content(record.final_response)
    content_out_of_scope = content is not None and (
        any(
            finding.domain not in record.requested_domains
            for finding in content.findings
        )
        or (not record.include_strategy and bool(content.actions))
    )
    if content is None or content_out_of_scope:
        return NativeOperatorResultView(
            **common,
            view_state="unavailable",
            headline="未生成可展示的分析结果",
            summary="任务已结束，但没有形成完整的经营结果。请重新运行或联系管理员查看任务诊断。",
        )
    return NativeOperatorResultView(
        **common,
        view_state="ready",
        **content.model_dump(),
    )


def build_operator_task_summary(
    record: NativeRunResult,
) -> NativeOperatorTaskSummary:
    view = build_operator_result_view(record)
    return NativeOperatorTaskSummary(
        task_reference=view.task_reference,
        view_state=view.view_state,
        terminal_status=view.terminal_status,
        requested_domains=view.requested_domains,
        include_strategy=record.include_strategy,
        created_at=record.created_at,
        updated_at=view.updated_at,
        headline=view.headline,
        summary=view.summary,
    )
