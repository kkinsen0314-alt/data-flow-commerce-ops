"""Execute one explicitly authorized native evaluation batch."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from commerce_ops.native_eval_runner import (  # noqa: E402
    DEFAULT_API_URL,
    NativeEvalRunnerError,
    build_batch_requests,
    run_batch,
)


def decimal_value(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("必须是有效金额。") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "对一个已单独授权的命名批次执行原生 MiniClaw 评测。"
            "每条用例单独 Session、串行执行、不自动模型重试。"
        )
    )
    parser.add_argument("--batch", required=True)
    parser.add_argument("--max-budget-cny", type=decimal_value, required=True)
    parser.add_argument("--authorized-by", required=True)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument(
        "--execute-authorized-model-batch",
        action="store_true",
        help="必须显式传入；缺少时只输出计划且不调用模型。",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if not args.execute_authorized_model_batch:
            plan = build_batch_requests(
                args.batch,
                project_root=PROJECT_ROOT,
                run_stamp="PREVIEW",
            )
            print(
                json.dumps(
                    {
                        "status": "planned_not_executed",
                        "batch_id": args.batch,
                        "case_ids": [case["case_id"] for case, _ in plan],
                        "model_called": False,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        result = run_batch(
            args.batch,
            max_budget_cny=args.max_budget_cny,
            authorized_by=args.authorized_by,
            api_url=args.api_url.rstrip("/"),
            project_root=PROJECT_ROOT,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "completed_traces_captured" else 2
    except (NativeEvalRunnerError, OSError, ValueError) as exc:
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
