"""Bounded native MiniClaw evaluation runner and redacted trace capture."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from .evaluation import build_system_versions, load_dataset, write_json


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_URL = "http://127.0.0.1:3022"
PROVIDER = "Alibaba Cloud Model Studio"
MODEL_ID = "qwen3.7-plus-2026-05-26"
PRICING_REGION = "China (Beijing)"
PRICING_SOURCE = "https://help.aliyun.com/zh/model-studio/model-pricing"
PRICING_CHECKED_AT = "2026-09-12T00:00:00+08:00"
INPUT_CNY_PER_MILLION = Decimal("2")
OUTPUT_CNY_PER_MILLION = Decimal("8")
DEFAULT_CASE_RESERVE_CNY = Decimal("2")

ROLE_TO_DOMAIN = {
    "content_growth_analyst": "content_growth",
    "live_conversion_analyst": "live_conversion",
    "attribution_lead_analyst": "attribution_leads",
}
ROLE_SLUG_TO_ID = {
    "content-growth-analyst": "content_growth_analyst",
    "live-conversion-analyst": "live_conversion_analyst",
    "attribution-lead-analyst": "attribution_lead_analyst",
    "commerce-review-strategist": "commerce_review_strategist",
}
DOMAIN_DATASETS = {
    "content_growth": [
        {"dataset_type": "short_video", "file_path": "short_video/synthetic-short-video.csv"},
    ],
    "live_conversion": [
        {"dataset_type": "live_session", "file_path": "live/synthetic-live-integration.csv"},
    ],
    "attribution_leads": [
        {"dataset_type": "channel_lead", "file_path": "leads/synthetic-channel-leads.csv"},
        {"dataset_type": "sales_followup", "file_path": "followup/synthetic-sales-followup.csv"},
        {"dataset_type": "order", "file_path": "orders/synthetic-orders.csv"},
    ],
}
BALANCE_PATTERNS = (
    "arrearage",
    "insufficient balance",
    "account balance",
    "余额不足",
    "欠费",
    "账户余额",
)


class NativeEvalRunnerError(RuntimeError):
    """The native evaluation runner could not safely continue."""


@dataclass(frozen=True)
class PricingSnapshot:
    input_cny_per_million: Decimal = INPUT_CNY_PER_MILLION
    output_cny_per_million: Decimal = OUTPUT_CNY_PER_MILLION
    region: str = PRICING_REGION
    source: str = PRICING_SOURCE
    checked_at: str = PRICING_CHECKED_AT


@dataclass
class RuntimeCapture:
    tool_arguments: dict[str, dict[str, Any]]
    dataset_manifests: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    response_messages: list[dict[str, Any]]
    capture_warnings: list[str]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def case_domains(case: dict[str, Any]) -> list[str]:
    domains = [
        ROLE_TO_DOMAIN[role]
        for role in case["expected"]["dispatched_agents"]
        if role in ROLE_TO_DOMAIN
    ]
    if not domains:
        raise NativeEvalRunnerError(f"{case['case_id']} 没有可执行专业域。")
    return domains


def build_case_request(case: dict[str, Any], run_stamp: str) -> dict[str, Any]:
    domains = case_domains(case)
    datasets = [
        deepcopy(dataset)
        for domain in domains
        for dataset in DOMAIN_DATASETS[domain]
    ]
    return {
        "idempotency_key": f"eval-{run_stamp}-{case['case_id']}",
        "requested_domains": domains,
        "datasets": datasets,
        "objective": case["user_input"],
        "include_strategy": "commerce_review_strategist"
        in case["expected"]["dispatched_agents"],
        "authorized_model_execution": True,
    }


def build_batch_requests(
    batch_id: str,
    *,
    project_root: Path = PROJECT_ROOT,
    run_stamp: str,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    plan = json.loads(
        (project_root / "evals/real-run-plan-v1.json").read_text(encoding="utf-8")
    )
    dataset = load_dataset(project_root / plan["dataset"])
    batch = next(
        (item for item in plan["batches"] if item["batch_id"] == batch_id), None
    )
    if batch is None:
        raise NativeEvalRunnerError(f"未知评测批次: {batch_id}")
    case_by_id = {item["case_id"]: item for item in dataset["cases"]}
    return [
        (case_by_id[case_id], build_case_request(case_by_id[case_id], run_stamp))
        for case_id in batch["case_ids"]
    ]


def estimate_cost_cny(
    usage: dict[str, int | None], pricing: PricingSnapshot = PricingSnapshot()
) -> Decimal | None:
    input_tokens = usage.get("input")
    output_tokens = usage.get("output")
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None
    cost = (
        Decimal(input_tokens) * pricing.input_cny_per_million
        + Decimal(output_tokens) * pricing.output_cny_per_million
    ) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def classify_balance_error(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False, default=str).casefold()
    return any(pattern in text for pattern in BALANCE_PATTERNS)


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 45,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail: Any = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        category = (
            "provider_balance_insufficient"
            if classify_balance_error(detail)
            else "native_api_http_error"
        )
        raise NativeEvalRunnerError(
            json.dumps(
                {"category": category, "status_code": exc.code, "detail": detail},
                ensure_ascii=False,
            )
        ) from exc
    except (TimeoutError, URLError) as exc:
        raise NativeEvalRunnerError(
            json.dumps(
                {
                    "category": "submission_or_poll_transport_uncertain",
                    "safe_message": str(exc),
                },
                ensure_ascii=False,
            )
        ) from exc
    if not isinstance(value, dict):
        raise NativeEvalRunnerError("原生 API 响应不是 JSON 对象。")
    return value


def poll_run(
    api_url: str,
    workflow_run_id: str,
    *,
    poll_seconds: float = 3,
    timeout_seconds: float = 1800,
    requester: Callable[..., dict[str, Any]] = request_json,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        record = requester(
            "GET", f"{api_url}/v1/native/runs/{workflow_run_id}", timeout=45
        )
        if record.get("observed_execution_state") in {"settled", "unresolved"}:
            return record
        if record.get("phase") == "settled":
            return record
        if time.monotonic() >= deadline:
            raise NativeEvalRunnerError(
                json.dumps(
                    {
                        "category": "poll_timeout_same_run_preserved",
                        "workflow_run_id": workflow_run_id,
                    },
                    ensure_ascii=False,
                )
            )
        time.sleep(poll_seconds)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            values.append(item)
    return values


def _messages(path: Path) -> list[dict[str, Any]]:
    return [
        item["message"]
        for item in _jsonl(path)
        if isinstance(item.get("message"), dict)
    ]


def _find_parent_session(project_root: Path, session_id: str) -> Path:
    matches = list(
        (project_root / "runtime/data/sessions").glob(
            f"*/agents/{session_id}/.claude/sessions/*.jsonl"
        )
    )
    if len(matches) != 1:
        raise NativeEvalRunnerError(
            f"Session {session_id} 的父级轨迹数量不是 1: {len(matches)}"
        )
    return matches[0]


def _task_outputs(parent_path: Path, project_root: Path) -> list[Path]:
    parent_records = _jsonl(parent_path)
    if not parent_records:
        return []
    header = parent_records[0]
    session_identity = header.get("id")
    if not isinstance(session_identity, str) or not session_identity:
        return []
    workspace_name = f"Workspace-{project_root.name}"
    candidates = list(
        Path(tempfile.gettempdir()).glob(
            f"pi-subagents-*/{workspace_name}/{session_identity}/tasks"
        )
    )
    if len(candidates) != 1:
        return []
    return sorted(candidates[0].glob("*.output"))


def _tool_name(value: Any) -> str:
    name = str(value or "")
    return name.removeprefix("commerce_ops_")


def _redact_arguments(arguments: Any, project_root: Path) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        return {}
    value = deepcopy(arguments)
    data_refs = value.get("data_refs")
    if isinstance(data_refs, list):
        value["synthetic"] = bool(data_refs) and all(
            isinstance(item, dict) and item.get("synthetic") is True
            for item in data_refs
        )
        value["dataset_ids"] = [
            item.get("dataset_id") for item in data_refs if isinstance(item, dict)
        ]
        value["path_within_data_root"] = all(
            isinstance(item, dict)
            and isinstance(item.get("file_path"), str)
            and Path(item["file_path"]).resolve().is_relative_to(
                (project_root / "data/fixtures").resolve()
            )
            for item in data_refs
        )
        value.pop("data_refs", None)
    value.pop("workflow_run_id", None)
    value.pop("caller_role", None)
    for key in list(value):
        if "path" in key.casefold() and key != "path_within_data_root":
            value[key] = "[REDACTED_PATH]"
    return value


def _unique_dicts(values: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[Any] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        identity = value.get(key)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(value)
    return result


def _json_objects(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    values: list[dict[str, Any]] = []
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except ValueError:
            continue
        if isinstance(value, dict):
            values.append(value)
    return values


def _capture_messages(
    messages: list[dict[str, Any]],
    *,
    project_root: Path,
    tool_arguments: dict[str, dict[str, Any]],
    manifests: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> None:
    for message in messages:
        if message.get("role") == "assistant":
            for block in message.get("content", []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "toolCall" and block.get("id"):
                    tool_arguments[str(block["id"])] = _redact_arguments(
                        block.get("arguments"), project_root
                    )
                if block.get("type") == "text":
                    for value in _json_objects(str(block.get("text", ""))):
                        if value.get("message_type") == "decision_packet":
                            actions.extend(
                                item
                                for item in value.get("actions", [])
                                if isinstance(item, dict)
                            )
        if message.get("role") != "toolResult":
            continue
        data = message.get("details", {}).get("structuredContent")
        if not isinstance(data, dict):
            continue
        manifests.extend(
            item for item in data.get("dataset_manifests", []) if isinstance(item, dict)
        )
        packet = data.get("analysis_packet")
        if isinstance(packet, dict):
            evidence.extend(
                item for item in packet.get("evidence", []) if isinstance(item, dict)
            )
            findings.extend(
                item for item in packet.get("findings", []) if isinstance(item, dict)
            )


def capture_runtime(
    record: dict[str, Any], *, project_root: Path = PROJECT_ROOT
) -> RuntimeCapture:
    session_id = record.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return RuntimeCapture({}, [], [], [], [], [], ["session_id_missing"])
    parent_path = _find_parent_session(project_root, session_id)
    parent_messages = _messages(parent_path)
    child_paths = _task_outputs(parent_path, project_root)
    warnings: list[str] = []
    if not child_paths:
        warnings.append("child_task_outputs_missing")
    tool_arguments: dict[str, dict[str, Any]] = {}
    manifests: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    response_messages = list(parent_messages)
    for child_path in child_paths:
        child_messages = _messages(child_path)
        response_messages.extend(child_messages)
        _capture_messages(
            child_messages,
            project_root=project_root,
            tool_arguments=tool_arguments,
            manifests=manifests,
            evidence=evidence,
            findings=findings,
            actions=actions,
        )
    return RuntimeCapture(
        tool_arguments=tool_arguments,
        dataset_manifests=_unique_dicts(manifests, "dataset_id"),
        evidence=_unique_dicts(evidence, "evidence_id"),
        findings=_unique_dicts(findings, "finding_id"),
        actions=_unique_dicts(actions, "action_id"),
        response_messages=response_messages,
        capture_warnings=warnings,
    )


def collect_usage(messages: list[dict[str, Any]]) -> dict[str, int | None]:
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    response_count = 0
    for message in messages:
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        response_count += 1
        input_tokens += sum(
            int(usage.get(key) or 0) for key in ("input", "cacheRead", "cacheWrite")
        )
        message_output = int(usage.get("output") or 0)
        message_input = sum(
            int(usage.get(key) or 0) for key in ("input", "cacheRead", "cacheWrite")
        )
        output_tokens += message_output
        total_tokens += int(usage.get("totalTokens") or message_input + message_output)
    if response_count == 0:
        return {
            "input": None,
            "output": None,
            "reasoning": None,
            "total": None,
            "response_count": 0,
        }
    return {
        "input": input_tokens,
        "output": output_tokens,
        "reasoning": None,
        "total": total_tokens,
        "response_count": response_count,
    }


def _iso_duration_ms(start: Any, finish: Any) -> float | None:
    if not isinstance(start, str) or not isinstance(finish, str):
        return None
    try:
        start_value = datetime.fromisoformat(start.replace("Z", "+00:00"))
        finish_value = datetime.fromisoformat(finish.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((finish_value - start_value).total_seconds() * 1000, 3)


def _route_for_domains(domains: list[str]) -> str:
    if len(domains) == 3:
        return "full_commerce_workflow"
    if len(domains) > 1:
        return "multi_domain_workflow"
    return {
        "content_growth": "content_growth_workflow",
        "live_conversion": "live_conversion_workflow",
        "attribution_leads": "attribution_leads_workflow",
    }[domains[0]]


def _redact_text(text: Any, project_root: Path) -> str | None:
    if not isinstance(text, str):
        return None
    value = text.replace(str(project_root), "[PROJECT_ROOT]")
    value = re.sub(
        r"(?i)(api[_-]?key|authorization|password|provider[_-]?key)\s*[:=]\s*[^\s,}\]]+",
        r"\1=[REDACTED]",
        value,
    )
    return value


def build_case_trace(
    case: dict[str, Any],
    record: dict[str, Any],
    capture: RuntimeCapture,
    *,
    project_root: Path = PROJECT_ROOT,
    pricing: PricingSnapshot = PricingSnapshot(),
) -> dict[str, Any]:
    attempts = [
        item
        for item in record.get("attempts", [])
        if item.get("layer") == "specialist_tool"
    ]
    attempts.sort(key=lambda item: item.get("started_at") or "")
    tool_calls = []
    for sequence, attempt in enumerate(attempts, start=1):
        tool_calls.append(
            {
                "sequence": sequence,
                "actor": attempt.get("actor"),
                "tool_name": _tool_name(attempt.get("tool_name")),
                "arguments_redacted": capture.tool_arguments.get(
                    str(attempt.get("tool_call_id")), {}
                ),
                "started_at": attempt.get("started_at"),
                "finished_at": attempt.get("completed_at"),
                "latency_ms": _iso_duration_ms(
                    attempt.get("started_at"), attempt.get("completed_at")
                ),
                "result_status": attempt.get("status"),
                "result_excerpt_redacted": {
                    "status": attempt.get("status"),
                    "reason_code": attempt.get("reason_code"),
                },
                "error_code": attempt.get("reason_code"),
                "service_run_id": attempt.get("service_run_id"),
            }
        )
    parent_roles = [
        ROLE_SLUG_TO_ID.get(str(item.get("subagent_type")), item.get("subagent_type"))
        for item in record.get("attempts", [])
        if item.get("layer") == "parent_dispatch"
    ]
    dispatched_agents = list(dict.fromkeys(role for role in parent_roles if role))
    usage = collect_usage(capture.response_messages)
    estimated = estimate_cost_cny(usage, pricing)
    started_at = record.get("submitted_at") or record.get("created_at")
    finished_at = record.get("settled_at") or record.get("updated_at")
    terminal = record.get("terminal_status") or "uncertain"
    warnings = list(capture.capture_warnings)
    if usage["total"] is None:
        warnings.append("Provider response usage was not captured; tokens and cost are null.")
    warnings.append(
        "Cost is conservatively estimated at regular input/output list price; cache discounts are not claimed."
    )
    return {
        "schema_version": "1.0",
        "record_type": "commerce_ops_case_trace",
        "case_id": case["case_id"],
        "execution_mode": "miniclaw_native_recorded_runner",
        "started_at": started_at,
        "finished_at": finished_at,
        "latency_ms": _iso_duration_ms(started_at, finished_at),
        "system_versions": {
            **build_system_versions(project_root),
            "model": {
                "provider": PROVIDER,
                "model_id": MODEL_ID,
                "snapshot": MODEL_ID,
                "execution_status": "executed",
                "pricing_region": pricing.region,
            },
        },
        "observed": {
            "route": _route_for_domains(list(record.get("requested_domains", []))),
            "terminal_status": terminal,
            "dispatched_agents": dispatched_agents,
            "tool_calls": tool_calls,
            "confirmation_requested": False,
            "workflow_run_id": record.get("workflow_run_id"),
            "analysis_run_ids": list(record.get("ledger", {}).get("analysis_run_ids", [])),
            "service_run_ids": list(record.get("ledger", {}).get("service_run_ids", [])),
            "run_id_missing_reason": (
                None if terminal in {"completed", "partial"} else terminal
            ),
            "dataset_manifests": capture.dataset_manifests,
            "evidence": capture.evidence,
            "findings": capture.findings,
            "actions": capture.actions,
            "response_text_redacted": _redact_text(
                record.get("final_response"), project_root
            ),
            "response_schema_valid": bool(
                record.get("reconciliation", {}).get("final_response_structured")
            ),
            "claim_boundaries": {
                "facts_hypotheses_missing_evidence_separated": None
            },
            "status_boundaries": {
                "synthetic_boundary_preserved": None,
                "status_boundary_preserved": None,
                "capability_boundary_preserved": None,
            },
            "external_actions": [],
            "configuration_changes": [],
            "recovery_fields": [],
            "semantic_review": {
                "status": "not_reviewed",
                "reviewer_type": None,
                "reviewer": None,
                "reviewed_at": None,
                "reviewed_gates": [],
                "judge": None,
                "must_include": {},
                "must_not_include": {},
                "notes": "LLM Judge was not authorized for this batch.",
            },
        },
        "soft_scores": None,
        "tokens": {
            "input": usage["input"],
            "output": usage["output"],
            "reasoning": usage["reasoning"],
            "total": usage["total"],
        },
        "estimated_cost": float(estimated) if estimated is not None else None,
        "cost_estimation": {
            "currency": "CNY",
            "pricing_source": pricing.source,
            "pricing_checked_at": pricing.checked_at,
            "input_cny_per_million": str(pricing.input_cny_per_million),
            "output_cny_per_million": str(pricing.output_cny_per_million),
            "cache_discount_claimed": False,
        },
        "unavailable_metric_reasons": warnings,
    }


def authorization_record(
    batch_id: str,
    *,
    max_budget_cny: Decimal,
    authorized_by: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "record_type": "private_real_eval_batch_authorization",
        "authorization_id": f"auth_{uuid4().hex}",
        "batch_id": batch_id,
        "provider": PROVIDER,
        "model_id": MODEL_ID,
        "model_snapshot": MODEL_ID,
        "provider_endpoint_region": PRICING_REGION,
        "pricing": {
            "source": PRICING_SOURCE,
            "checked_at": PRICING_CHECKED_AT,
            "input_cny_per_million": str(INPUT_CNY_PER_MILLION),
            "output_cny_per_million": str(OUTPUT_CNY_PER_MILLION),
        },
        "maximum_batch_budget": str(max_budget_cny),
        "currency": "CNY",
        "authorized_by": authorized_by,
        "authorized_at": utc_now(),
        "authorization_scope": "one_named_batch_only",
        "automatic_batch_continuation": False,
        "automatic_model_retry": False,
        "llm_judge_authorized": False,
    }


def run_batch(
    batch_id: str,
    *,
    max_budget_cny: Decimal,
    authorized_by: str,
    api_url: str = DEFAULT_API_URL,
    project_root: Path = PROJECT_ROOT,
    case_reserve_cny: Decimal = DEFAULT_CASE_RESERVE_CNY,
) -> dict[str, Any]:
    if max_budget_cny <= 0:
        raise NativeEvalRunnerError("最高批次预算必须大于 0。")
    if case_reserve_cny <= 0:
        raise NativeEvalRunnerError("单用例预算预留必须大于 0。")
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    requests = build_batch_requests(
        batch_id, project_root=project_root, run_stamp=run_stamp
    )
    if Decimal(len(requests)) * case_reserve_cny > max_budget_cny:
        raise NativeEvalRunnerError("逐条预算预留总额超过已授权批次预算。")

    private_root = project_root / "runtime/data/evals/private" / f"{batch_id.lower()}-{run_stamp}"
    public_root = project_root / "artifacts/evals" / f"{batch_id.lower()}-{run_stamp}"
    private_root.mkdir(parents=True, exist_ok=False)
    public_root.mkdir(parents=True, exist_ok=False)
    authorization = authorization_record(
        batch_id, max_budget_cny=max_budget_cny, authorized_by=authorized_by
    )
    write_json(private_root / "authorization.json", authorization)
    batch_record: dict[str, Any] = {
        "schema_version": "1.0",
        "record_type": "commerce_ops_real_eval_batch_run",
        "batch_id": batch_id,
        "status": "running",
        "started_at": utc_now(),
        "finished_at": None,
        "provider": PROVIDER,
        "model_id": MODEL_ID,
        "pricing_region": PRICING_REGION,
        "maximum_batch_budget": str(max_budget_cny),
        "case_reserve_cny": str(case_reserve_cny),
        "estimated_cost_cny": "0",
        "authorization_sha256": sha256_file(private_root / "authorization.json"),
        "llm_judge_used": False,
        "cases": [],
        "stop_reason": None,
        "evidence_boundary": {
            "synthetic_data_only": True,
            "external_business_writes_allowed": False,
            "automatic_model_retry": False,
            "one_session_per_case": True,
            "max_inflight_cases": 1,
        },
    }
    batch_path = public_root / "batch-run.json"
    traces_path = public_root / "traces.json"
    traces: list[dict[str, Any]] = []
    write_json(batch_path, batch_record)
    write_json(traces_path, {"traces": traces})

    estimated_total = Decimal("0")
    try:
        configuration = request_json("GET", f"{api_url}/v1/native/configuration")
        if configuration.get("ready") is not True:
            raise NativeEvalRunnerError("原生 API 未处于 ready 状态。")
        for case, payload in requests:
            if estimated_total + case_reserve_cny > max_budget_cny:
                batch_record["status"] = "stopped_budget_reservation"
                batch_record["stop_reason"] = "remaining_budget_below_case_reserve"
                break
            case_state: dict[str, Any] = {
                "case_id": case["case_id"],
                "status": "submitting_once",
                "workflow_run_id": None,
                "estimated_cost_cny": None,
            }
            batch_record["cases"].append(case_state)
            write_json(batch_path, batch_record)
            try:
                accepted = request_json(
                    "POST", f"{api_url}/v1/native/runs", payload
                )
            except NativeEvalRunnerError as exc:
                case_state["status"] = "submission_failed_or_uncertain"
                case_state["safe_error"] = str(exc)
                batch_record["status"] = (
                    "stopped_provider_balance_insufficient"
                    if classify_balance_error(str(exc))
                    else "stopped_submission_failure_or_uncertain"
                )
                batch_record["stop_reason"] = case_state["status"]
                write_json(batch_path, batch_record)
                break
            workflow_run_id = accepted.get("workflow_run_id")
            if not isinstance(workflow_run_id, str) or not workflow_run_id:
                case_state["status"] = "submission_response_uncertain"
                batch_record["status"] = "stopped_submission_failure_or_uncertain"
                batch_record["stop_reason"] = "workflow_run_id_missing_no_resubmit"
                write_json(batch_path, batch_record)
                break
            case_state["workflow_run_id"] = workflow_run_id
            case_state["status"] = "polling_same_run"
            write_json(batch_path, batch_record)
            record = poll_run(api_url, workflow_run_id)
            if classify_balance_error(record):
                case_state["status"] = "provider_balance_insufficient"
                batch_record["status"] = "stopped_provider_balance_insufficient"
                batch_record["stop_reason"] = "provider_balance_insufficient"
                write_json(batch_path, batch_record)
                break
            capture = capture_runtime(record, project_root=project_root)
            trace = build_case_trace(
                case, record, capture, project_root=project_root
            )
            trace_path = public_root / f"{case['case_id'].lower()}.json"
            write_json(trace_path, trace)
            traces.append(trace)
            write_json(traces_path, {"traces": traces})
            estimated = trace.get("estimated_cost")
            if isinstance(estimated, (int, float)):
                estimated_total += Decimal(str(estimated))
            case_state["estimated_cost_cny"] = (
                str(estimated) if estimated is not None else None
            )
            case_state["terminal_status"] = record.get("terminal_status")
            case_state["status"] = "captured"
            batch_record["estimated_cost_cny"] = str(estimated_total)
            write_json(batch_path, batch_record)
            if estimated_total > max_budget_cny:
                batch_record["status"] = "stopped_budget_exceeded_after_case"
                batch_record["stop_reason"] = "estimated_cost_exceeded_authorized_budget"
                break
            if record.get("terminal_status") in {"uncertain", "blocked"}:
                batch_record["status"] = "stopped_terminal_boundary"
                batch_record["stop_reason"] = str(record.get("terminal_status"))
                break
        else:
            batch_record["status"] = "completed_traces_captured"
    except NativeEvalRunnerError as exc:
        if batch_record["status"] == "running":
            batch_record["status"] = (
                "stopped_provider_balance_insufficient"
                if classify_balance_error(str(exc))
                else "stopped_runner_error"
            )
            batch_record["stop_reason"] = str(exc)
    finally:
        batch_record["finished_at"] = utc_now()
        batch_record["estimated_cost_cny"] = str(estimated_total)
        write_json(batch_path, batch_record)
        write_json(traces_path, {"traces": traces})
    return {
        "status": batch_record["status"],
        "batch_id": batch_id,
        "captured_case_count": len(traces),
        "estimated_cost_cny": str(estimated_total),
        "stop_reason": batch_record["stop_reason"],
        "public_root": str(public_root),
        "batch_record": str(batch_path),
        "traces": str(traces_path),
    }
