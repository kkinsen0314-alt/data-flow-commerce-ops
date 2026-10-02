import json
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from commerce_ops.native_eval_runner import (
    PricingSnapshot,
    build_batch_requests,
    build_case_trace,
    classify_balance_error,
    collect_usage,
    estimate_cost_cny,
    RuntimeCapture,
)


class NativeEvalPlanningTests(unittest.TestCase):
    def test_b01_builds_five_isolated_requests_with_required_domains(self):
        planned = build_batch_requests("B01", run_stamp="TEST")

        self.assertEqual(len(planned), 5)
        self.assertEqual(
            [case["case_id"] for case, _ in planned],
            [f"NORMAL-{index:03d}" for index in range(1, 6)],
        )
        self.assertEqual(len({item[1]["idempotency_key"] for item in planned}), 5)
        self.assertEqual(
            planned[-1][1]["requested_domains"],
            ["content_growth", "live_conversion", "attribution_leads"],
        )
        self.assertEqual(len(planned[-1][1]["datasets"]), 5)
        self.assertTrue(all(item[1]["authorized_model_execution"] for item in planned))

    def test_cost_uses_conservative_regular_input_and_output_prices(self):
        usage = {"input": 100_000, "output": 10_000}

        value = estimate_cost_cny(usage, PricingSnapshot())

        self.assertEqual(value, Decimal("0.280000"))

    def test_balance_errors_are_distinct_from_generic_runtime_errors(self):
        self.assertTrue(classify_balance_error({"message": "Arrearage"}))
        self.assertTrue(classify_balance_error({"detail": "账户余额不足"}))
        self.assertFalse(classify_balance_error({"message": "rate limited"}))

    def test_usage_counts_cache_buckets_as_conservative_input(self):
        usage = collect_usage(
            [
                {
                    "usage": {
                        "input": 5,
                        "cacheRead": 20,
                        "cacheWrite": 30,
                        "output": 7,
                        "totalTokens": 62,
                    }
                }
            ]
        )

        self.assertEqual(usage["input"], 55)
        self.assertEqual(usage["output"], 7)
        self.assertEqual(usage["total"], 62)

    def test_usage_fallback_total_is_per_message_not_cumulative(self):
        usage = collect_usage(
            [
                {"usage": {"input": 10, "output": 5}},
                {"usage": {"input": 20, "output": 7}},
            ]
        )

        self.assertEqual(usage["input"], 30)
        self.assertEqual(usage["output"], 12)
        self.assertEqual(usage["total"], 42)


class NativeEvalTraceTests(unittest.TestCase):
    def test_trace_uses_authoritative_attempts_and_keeps_semantic_review_open(self):
        case = build_batch_requests("B01", run_stamp="TEST")[0][0]
        record = {
            "workflow_run_id": "wf_eval_native_001",
            "requested_domains": ["content_growth"],
            "terminal_status": "completed",
            "created_at": "2026-09-12T00:00:00Z",
            "submitted_at": "2026-09-12T00:00:01Z",
            "updated_at": "2026-09-12T00:00:04Z",
            "settled_at": "2026-09-12T00:00:04Z",
            "attempts": [
                {
                    "layer": "parent_dispatch",
                    "subagent_type": "content-growth-analyst",
                    "started_at": "2026-09-12T00:00:01Z",
                },
                {
                    "layer": "parent_dispatch",
                    "subagent_type": "commerce-review-strategist",
                    "started_at": "2026-09-12T00:00:03Z",
                },
                {
                    "layer": "specialist_tool",
                    "actor": "content_growth_analyst",
                    "tool_name": "commerce_ops_inspect_commerce_data",
                    "tool_call_id": "tool_1",
                    "status": "completed",
                    "started_at": "2026-09-12T00:00:01Z",
                    "completed_at": "2026-09-12T00:00:02Z",
                    "service_run_id": "srv_eval_001",
                    "reason_code": None,
                },
            ],
            "ledger": {
                "analysis_run_ids": ["analysis_eval_001"],
                "service_run_ids": ["srv_eval_001"],
            },
            "reconciliation": {"final_response_structured": True},
            "final_response": "synthetic=true",
        }
        capture = RuntimeCapture(
            tool_arguments={"tool_1": {"synthetic": True}},
            dataset_manifests=[{"dataset_id": "ds_eval_001", "synthetic": True}],
            evidence=[],
            findings=[],
            actions=[],
            response_messages=[
                {"usage": {"input": 10, "output": 5, "totalTokens": 15}}
            ],
            capture_warnings=[],
        )

        trace = build_case_trace(case, record, capture)

        self.assertEqual(trace["observed"]["route"], "content_growth_workflow")
        self.assertEqual(
            trace["observed"]["dispatched_agents"],
            ["content_growth_analyst", "commerce_review_strategist"],
        )
        self.assertEqual(trace["observed"]["tool_calls"][0]["tool_name"], "inspect_commerce_data")
        self.assertEqual(trace["observed"]["semantic_review"]["status"], "not_reviewed")
        self.assertIsNone(trace["soft_scores"])


if __name__ == "__main__":
    unittest.main()
