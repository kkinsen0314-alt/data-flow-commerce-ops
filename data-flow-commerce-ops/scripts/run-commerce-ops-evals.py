"""CLI for fixture preflight, recorded-trace scoring, and regression comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from commerce_ops.evaluation import (  # noqa: E402
    EvaluationInfrastructureError,
    compare_eval_runs,
    evaluate_trace_set,
    validate_dataset_and_fixtures,
    write_json,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_traces(path: Path) -> list[dict[str, Any]]:
    value = _load_json(path)
    if isinstance(value, list):
        traces = value
    elif isinstance(value, dict) and isinstance(value.get("traces"), list):
        traces = value["traces"]
    else:
        raise EvaluationInfrastructureError(
            "trace 输入必须是数组或包含 traces 数组的对象。"
        )
    if not all(isinstance(item, dict) for item in traces):
        raise EvaluationInfrastructureError("每条 trace 必须是对象。")
    return traces


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "验证 30 条电商评测用例与 fixture、评分已记录的 Agent 轨迹，或比较 "
            "baseline/candidate。命令本身不调用模型。"
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "evals" / "fixture-preflight-v1.json",
    )

    score = subparsers.add_parser("score")
    score.add_argument("--traces", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    score.add_argument(
        "--run-label",
        choices=["baseline", "candidate"],
        required=True,
    )
    score.add_argument("--executed-by", required=True)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "preflight":
            report = validate_dataset_and_fixtures(PROJECT_ROOT)
        elif args.command == "score":
            report = evaluate_trace_set(
                _load_traces(args.traces),
                project_root=PROJECT_ROOT,
                baseline_or_candidate=args.run_label,
                executed_by=args.executed_by,
            )
        else:
            report = compare_eval_runs(
                _load_json(args.baseline),
                _load_json(args.candidate),
            )
        write_json(args.output, report)
        print(json.dumps({
            "status": report.get("status"),
            "record_type": report.get("record_type"),
            "output": str(args.output),
        }, ensure_ascii=False))
        return 0
    except (EvaluationInfrastructureError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "status": "error",
            "error_type": type(exc).__name__,
            "safe_message": str(exc),
        }, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
