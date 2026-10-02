"""Validate the deterministic native recovery catalog without model calls."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any

from pydantic import ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from commerce_ops.native_recovery import (  # noqa: E402
    NativeRecoverySnapshot,
    plan_native_recovery,
)


CATALOG_PATH = PROJECT_ROOT / "contracts" / "native-recovery-cases-v1.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "native-recovery-validation-v1.json"


class RecoveryVerificationError(ValueError):
    pass


def _load_catalog() -> dict[str, Any]:
    value = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RecoveryVerificationError("恢复用例目录必须是 JSON 对象")
    if value.get("schema_version") != "1.0":
        raise RecoveryVerificationError("恢复用例目录 schema_version 必须为 1.0")
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RecoveryVerificationError("恢复用例目录必须包含非空 cases 数组")
    return value


def _validate_output_path(path: Path) -> Path:
    resolved = path.resolve()
    if resolved != PROJECT_ROOT and PROJECT_ROOT not in resolved.parents:
        raise RecoveryVerificationError("输出路径必须位于 project017 内")
    return resolved


def verify_catalog() -> dict[str, Any]:
    catalog = _load_catalog()
    case_results: list[dict[str, Any]] = []
    case_ids: set[str] = set()

    for raw_case in catalog["cases"]:
        if not isinstance(raw_case, dict):
            raise RecoveryVerificationError("每条恢复用例必须是对象")
        case_id = raw_case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise RecoveryVerificationError("每条恢复用例必须包含 case_id")
        if case_id in case_ids:
            raise RecoveryVerificationError(f"重复 case_id: {case_id}")
        case_ids.add(case_id)

        snapshot = NativeRecoverySnapshot.model_validate(raw_case.get("snapshot"))
        plan = plan_native_recovery(snapshot)
        expected = raw_case.get("expected")
        if not isinstance(expected, dict):
            raise RecoveryVerificationError(f"{case_id} 缺少 expected 对象")

        checks = {
            "scenario": plan.scenario == expected.get("scenario"),
            "automatic_retry_allowed": (
                plan.automatic_retry_allowed
                == expected.get("automatic_retry_allowed")
            ),
            "same_run_observation_required": (
                plan.same_run_observation_required
                == expected.get("same_run_observation_required")
            ),
            "new_run_policy": plan.new_run_policy == expected.get("new_run_policy"),
            "required_allowed_steps": set(
                expected.get("required_allowed_steps", [])
            ).issubset(plan.allowed_steps),
            "required_forbidden_steps": set(
                expected.get("required_forbidden_steps", [])
            ).issubset(plan.forbidden_steps),
        }
        case_results.append(
            {
                "case_id": case_id,
                "name": raw_case.get("name"),
                "status": "pass" if all(checks.values()) else "fail",
                "checks": checks,
                "actual_plan": plan.model_dump(),
            }
        )

    passed = sum(item["status"] == "pass" for item in case_results)
    return {
        "schema_version": "1.0",
        "record_type": "miniclaw_native_recovery_validation",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_catalog": str(CATALOG_PATH.relative_to(PROJECT_ROOT)).replace(
            "\\", "/"
        ),
        "execution_mode": "deterministic_no_model",
        "model_called": False,
        "automatic_retry_attempted": False,
        "case_count": len(case_results),
        "passed_count": passed,
        "failed_count": len(case_results) - passed,
        "status": "pass" if passed == len(case_results) else "fail",
        "cases": case_results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "校验原生任务恢复契约并输出确定性证据；命令不启动 Host/API、"
            "不创建任务，也不调用模型。"
        )
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        output = _validate_output_path(args.output)
        report = verify_catalog()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "cases": f"{report['passed_count']}/{report['case_count']}",
                    "output": str(output.relative_to(PROJECT_ROOT)).replace(
                        "\\", "/"
                    ),
                    "model_called": False,
                },
                ensure_ascii=False,
            )
        )
        return 0 if report["status"] == "pass" else 1
    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
        RecoveryVerificationError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
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
