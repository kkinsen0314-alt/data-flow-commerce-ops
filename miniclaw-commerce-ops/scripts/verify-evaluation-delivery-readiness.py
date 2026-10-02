"""Build a no-model readiness report for evaluation and GitHub delivery."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from commerce_ops.evaluation import (  # noqa: E402
    load_dataset,
    validate_dataset_and_fixtures,
)


PLAN_PATH = PROJECT_ROOT / "evals" / "real-run-plan-v1.json"
PREFLIGHT_PATH = PROJECT_ROOT / "artifacts" / "evals" / "fixture-preflight-v1.json"
SELFTEST_PATH = (
    PROJECT_ROOT / "artifacts" / "evals" / "evaluation-executor-selftest-v1.json"
)
ARTIFACT_DIR = PROJECT_ROOT / "artifacts" / "evals"
RELEASE_ROOT = (
    PROJECT_ROOT
    if (PROJECT_ROOT / "PUBLIC-PREVIEW-MANIFEST.json").is_file()
    else PROJECT_ROOT / "release" / "miniclaw-commerce-ops"
)
DEFAULT_OUTPUT = ARTIFACT_DIR / "evaluation-delivery-readiness-v1.json"


class ReadinessVerificationError(ValueError):
    pass


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")


def _validate_output_path(path: Path) -> Path:
    resolved = path.resolve()
    if resolved != PROJECT_ROOT and PROJECT_ROOT not in resolved.parents:
        raise ReadinessVerificationError("输出路径必须位于 project017 内")
    return resolved


def _validate_plan(plan: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
    if plan.get("schema_version") != "1.0":
        raise ReadinessVerificationError("运行计划 schema_version 必须为 1.0")
    if plan.get("record_type") != "commerce_ops_real_eval_run_plan":
        raise ReadinessVerificationError("运行计划 record_type 不正确")
    batches = plan.get("batches")
    if not isinstance(batches, list) or not batches:
        raise ReadinessVerificationError("运行计划必须包含非空 batches")
    if plan.get("batch_count") != len(batches):
        raise ReadinessVerificationError("batch_count 与实际 batches 不一致")
    dataset_cases = {
        item["case_id"]: item["category"] for item in dataset["cases"]
    }
    planned_ids: list[str] = []
    batch_ids: list[str] = []
    for batch in batches:
        batch_id = batch.get("batch_id")
        case_ids = batch.get("case_ids")
        if not isinstance(batch_id, str) or not batch_id:
            raise ReadinessVerificationError("每个批次必须包含 batch_id")
        if not isinstance(case_ids, list) or not 1 <= len(case_ids) <= 6:
            raise ReadinessVerificationError(f"{batch_id} 必须包含 1—6 条用例")
        if any(dataset_cases.get(case_id) != batch.get("category") for case_id in case_ids):
            raise ReadinessVerificationError(f"{batch_id} 的 category 与用例不一致")
        batch_ids.append(batch_id)
        planned_ids.extend(case_ids)
    if len(batch_ids) != len(set(batch_ids)):
        raise ReadinessVerificationError("batch_id 不能重复")
    if len(planned_ids) != len(set(planned_ids)):
        raise ReadinessVerificationError("运行计划中的 case_id 不能重复")
    if set(planned_ids) != set(dataset_cases):
        missing = sorted(set(dataset_cases).difference(planned_ids))
        unknown = sorted(set(planned_ids).difference(dataset_cases))
        raise ReadinessVerificationError(
            f"运行计划未精确覆盖评测集: missing={missing}, unknown={unknown}"
        )
    policy = plan.get("execution_policy") or {}
    required_policy = {
        "explicit_fee_authorization_required_per_batch": True,
        "automatic_batch_continuation": False,
        "automatic_model_retry": False,
        "one_session_per_case": True,
        "max_inflight_cases": 1,
        "new_workflow_and_idempotency_identity_per_case": True,
        "synthetic_data_only": True,
        "external_business_writes_allowed": False,
    }
    mismatches = {
        key: {"expected": expected, "actual": policy.get(key)}
        for key, expected in required_policy.items()
        if policy.get(key) != expected
    }
    if mismatches:
        raise ReadinessVerificationError(f"运行安全策略不匹配: {mismatches}")
    semantic = plan.get("semantic_review_contract") or {}
    if set(semantic.get("required_gates") or []) != {"H09", "H10", "H12"}:
        raise ReadinessVerificationError("语义复核门槛必须精确覆盖 H09/H10/H12")
    github = plan.get("github_delivery") or {}
    for field in ("required_current_paths", "forbidden_public_paths"):
        values = github.get(field)
        if not isinstance(values, list) or not values:
            raise ReadinessVerificationError(f"github_delivery.{field} 必须为非空数组")
        if len(values) != len(set(values)):
            raise ReadinessVerificationError(f"github_delivery.{field} 不能重复")
    return {
        "status": "pass",
        "batch_count": len(batches),
        "case_count": len(planned_ids),
        "maximum_cases_per_batch": max(len(item["case_ids"]) for item in batches),
        "case_ids_unique": True,
        "all_dataset_cases_covered": True,
        "paid_execution_is_not_authorized_by_plan": plan.get("status")
        == "planned_not_authorized",
    }


def _scan_evaluation_artifacts() -> dict[str, list[dict[str, Any]]]:
    collected: dict[str, list[dict[str, Any]]] = {
        "runs": [],
        "comparisons": [],
        "case_traces": [],
    }
    if not ARTIFACT_DIR.is_dir():
        return collected
    for path in sorted(ARTIFACT_DIR.rglob("*.json")):
        if path == DEFAULT_OUTPUT:
            continue
        try:
            value = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict) or value.get("template_status") == "template_not_executed":
            continue
        entry = {"path": _relative(path), "value": value}
        record_type = value.get("record_type")
        if record_type == "commerce_ops_agent_eval_run":
            collected["runs"].append(entry)
        elif record_type == "commerce_ops_eval_regression_report":
            collected["comparisons"].append(entry)
        elif record_type == "commerce_ops_case_trace":
            collected["case_traces"].append(entry)
    return collected


def _semantic_reviewed_count(run: dict[str, Any]) -> int:
    count = 0
    for result in run.get("case_results", []):
        gates = {
            item.get("gate_id"): item
            for item in result.get("hard_gates", [])
            if isinstance(item, dict)
        }
        if all(
            gates.get(gate_id, {}).get("passed") is True
            and gates.get(gate_id, {}).get("automation_status")
            == "semantic_review_record_validated"
            for gate_id in ("H09", "H10", "H12")
        ):
            count += 1
    return count


def _evaluation_evidence_status(
    artifacts: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    runs = [entry["value"] for entry in artifacts["runs"]]
    run_summaries = []
    for entry in artifacts["runs"]:
        value = entry["value"]
        counts = value.get("aggregate", {}).get("counts", {})
        run_summaries.append(
            {
                "path": entry["path"],
                "eval_run_id": value.get("run_identity", {}).get("eval_run_id"),
                "baseline_or_candidate": value.get("run_identity", {}).get(
                    "baseline_or_candidate"
                ),
                "completed_case_count": counts.get("completed", 0),
                "semantic_reviewed_case_count": _semantic_reviewed_count(value),
                "release_decision": value.get("release_decision", {}).get("status"),
            }
        )
    complete_runs = [
        value
        for value in runs
        if value.get("aggregate", {}).get("counts", {}).get("completed") == 30
    ]
    passed_baselines = [
        value
        for value in complete_runs
        if value.get("run_identity", {}).get("baseline_or_candidate") == "baseline"
        and value.get("release_decision", {}).get("status") == "passed"
    ]
    passed_candidates = [
        value
        for value in complete_runs
        if value.get("run_identity", {}).get("baseline_or_candidate") == "candidate"
        and value.get("release_decision", {}).get("status") == "passed"
    ]
    passed_comparisons = [
        entry
        for entry in artifacts["comparisons"]
        if entry["value"].get("comparison_decision") == "passed"
    ]
    maximum_completed = max(
        (
            summary["completed_case_count"]
            for summary in run_summaries
            if isinstance(summary["completed_case_count"], int)
        ),
        default=0,
    )
    maximum_reviewed = max(
        (summary["semantic_reviewed_case_count"] for summary in run_summaries),
        default=0,
    )
    return {
        "recorded_eval_run_count": len(runs),
        "standalone_case_trace_count": len(artifacts["case_traces"]),
        "complete_30_case_run_count": len(complete_runs),
        "maximum_completed_cases_in_one_run": maximum_completed,
        "maximum_h09_h10_h12_reviewed_cases_in_one_run": maximum_reviewed,
        "passed_baseline_count": len(passed_baselines),
        "passed_candidate_count": len(passed_candidates),
        "passed_regression_comparison_count": len(passed_comparisons),
        "run_summaries": run_summaries,
    }


def _path_matches_forbidden(relative: str, forbidden: list[str]) -> bool:
    normalized = relative.replace("\\", "/").strip("/")
    parts = normalized.split("/")
    for rule in forbidden:
        clean = rule.strip("/")
        if normalized == clean or normalized.startswith(f"{clean}/"):
            return True
        if clean in {"node_modules", "__pycache__"} and clean in parts:
            return True
    return normalized.endswith(".key") or Path(normalized).name == ".env"


def _github_delivery_status(plan: dict[str, Any]) -> dict[str, Any]:
    github = plan.get("github_delivery") or {}
    required = github.get("required_current_paths") or []
    forbidden = github.get("forbidden_public_paths") or []
    source_missing = [
        relative for relative in required if not (PROJECT_ROOT / relative).is_file()
    ]
    release_missing = [
        relative for relative in required if not (RELEASE_ROOT / relative).is_file()
    ]
    release_files = (
        [path for path in RELEASE_ROOT.rglob("*") if path.is_file()]
        if RELEASE_ROOT.is_dir()
        else []
    )
    forbidden_release_files = [
        str(path.relative_to(RELEASE_ROOT)).replace("\\", "/")
        for path in release_files
        if _path_matches_forbidden(
            str(path.relative_to(RELEASE_ROOT)).replace("\\", "/"),
            forbidden,
        )
    ]
    preview_status = (
        "missing"
        if not RELEASE_ROOT.is_dir()
        else "stale_rebuild_required"
        if release_missing or forbidden_release_files
        else "current_file_set_present"
    )
    return {
        "source_required_paths_present": not source_missing,
        "source_missing_paths": source_missing,
        "existing_release_root": _relative(RELEASE_ROOT),
        "existing_release_file_count": len(release_files),
        "release_missing_current_paths": release_missing,
        "forbidden_release_files": forbidden_release_files,
        "github_preview_status": preview_status,
        "preview_without_real_eval_allowed": github.get(
            "preview_without_real_eval_allowed"
        ),
        "required_preview_disclosure": github.get("preview_required_disclosure"),
    }


def build_report() -> dict[str, Any]:
    plan = _load_json(PLAN_PATH)
    if not isinstance(plan, dict):
        raise ReadinessVerificationError("运行计划必须是 JSON 对象")
    dataset = load_dataset()
    plan_validation = _validate_plan(plan, dataset)
    live_preflight = validate_dataset_and_fixtures(PROJECT_ROOT)
    persisted_preflight = _load_json(PREFLIGHT_PATH)
    selftest = _load_json(SELFTEST_PATH)
    preflight_current = (
        persisted_preflight.get("status") == "pass"
        and persisted_preflight.get("dataset") == live_preflight.get("dataset")
        and persisted_preflight.get("executor_versions")
        == live_preflight.get("executor_versions")
    )
    artifacts = _scan_evaluation_artifacts()
    evidence = _evaluation_evidence_status(artifacts)
    github = _github_delivery_status(plan)

    quality_blockers: list[str] = []
    if evidence["complete_30_case_run_count"] == 0:
        quality_blockers.append("没有单轮覆盖 30 条用例的真实 Agent 评测记录。")
    if evidence["maximum_h09_h10_h12_reviewed_cases_in_one_run"] < 30:
        quality_blockers.append("没有 30 条 H09/H10/H12 可追溯人工或 Judge 复核。")
    if evidence["passed_baseline_count"] == 0:
        quality_blockers.append("没有 release_decision=passed 的 baseline。")
    if evidence["passed_candidate_count"] == 0:
        quality_blockers.append("没有 release_decision=passed 的 candidate。")
    if evidence["passed_regression_comparison_count"] == 0:
        quality_blockers.append("没有 comparison_decision=passed 的回归比较。")

    github_blockers: list[str] = []
    if github["source_missing_paths"]:
        github_blockers.append("当前源码缺少公开预览要求文件。")
    if github["github_preview_status"] != "current_file_set_present":
        github_blockers.append("现有 release 文件集不是当前源码预览。")
    if github["forbidden_release_files"]:
        github_blockers.append("现有 release 包含禁止公开的路径。")

    return {
        "schema_version": "1.0",
        "record_type": "commerce_ops_evaluation_delivery_readiness",
        "generated_at": datetime.now(UTC).isoformat(),
        "verification_status": "pass",
        "execution_mode": "deterministic_no_model_no_github_publish",
        "model_called": False,
        "judge_called": False,
        "github_published": False,
        "plan": {
            "path": _relative(PLAN_PATH),
            **plan_validation,
        },
        "fixture_preflight": {
            "live_status": live_preflight.get("status"),
            "runnable_case_count": live_preflight.get("dataset", {}).get(
                "runnable_case_count"
            ),
            "persisted_artifact_current": preflight_current,
            "persisted_artifact": _relative(PREFLIGHT_PATH),
        },
        "evaluation_executor": {
            "selftest_status": selftest.get("status"),
            "semantic_review_metadata_required": True,
            "semantic_gates": ["H09", "H10", "H12"],
            "unreviewed_boundary_booleans_can_pass": False,
        },
        "real_evaluation_evidence": evidence,
        "quality_release": {
            "status": "blocked" if quality_blockers else "ready",
            "blockers": quality_blockers,
        },
        "paid_execution_gate": {
            "status": "explicit_future_authorization_required",
            "authorization_granted_by_this_plan": False,
            "authorization_scope": plan.get("cost_gate", {}).get(
                "authorization_scope"
            ),
            "requirements": plan.get("cost_gate"),
        },
        "github_delivery": {
            **github,
            "status": "blocked" if github_blockers else "ready",
            "blockers": github_blockers,
            "evaluated_release_status": (
                "blocked" if quality_blockers else "eligible_after_package_rebuild"
            ),
        },
        "next_safe_action": (
            "如要运行真实评测，先单独确认一个命名批次、Provider/模型快照和最高预算。"
            if github["github_preview_status"] == "current_file_set_present"
            else "重建不含敏感资产的当前 GitHub source preview；如要运行真实评测，"
            "先单独确认一个命名批次、Provider/模型快照和最高预算。"
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "验证 30 条评测运行计划、当前证据和 GitHub 交付缺口；"
            "命令不创建 AgentSession、不调用模型或 Judge，也不发布 GitHub。"
        )
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        output = _validate_output_path(args.output)
        report = build_report()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "verification_status": report["verification_status"],
                    "fixture_cases": report["fixture_preflight"][
                        "runnable_case_count"
                    ],
                    "real_eval_runs": report["real_evaluation_evidence"][
                        "recorded_eval_run_count"
                    ],
                    "quality_release": report["quality_release"]["status"],
                    "github_preview": report["github_delivery"][
                        "github_preview_status"
                    ],
                    "output": _relative(output),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (
        OSError,
        json.JSONDecodeError,
        ReadinessVerificationError,
    ) as exc:
        print(
            json.dumps(
                {
                    "verification_status": "error",
                    "error_type": type(exc).__name__,
                    "safe_message": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
