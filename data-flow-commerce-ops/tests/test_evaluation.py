import json
import unittest

from commerce_ops.evaluation import (
    PROJECT_ROOT,
    TraceRecorder,
    compare_eval_runs,
    evaluate_trace_set,
    load_dataset,
    score_case,
    validate_dataset_and_fixtures,
)


DATASET_PATH = PROJECT_ROOT / "evals" / "commerce-ops-agent-eval-cases-v1.json"


def case_by_id(case_id: str) -> dict:
    dataset = load_dataset(DATASET_PATH)
    return next(case for case in dataset["cases"] if case["case_id"] == case_id)


def semantic_review(case: dict) -> dict:
    return {
        "status": "passed",
        "reviewer_type": "human",
        "reviewer": "unit_test_reviewer",
        "reviewed_at": "2026-09-10T12:30:00+08:00",
        "reviewed_gates": ["H09", "H10", "H12"],
        "judge": None,
        "must_include": {
            item: True for item in case["expected"]["must_include"]
        },
        "must_not_include": {
            item: True for item in case["expected"]["must_not_include"]
        },
    }


def soft_scores() -> dict:
    return {
        "intent_and_routing": 5,
        "groundedness": 5,
        "completeness": 4,
        "actionability": 4,
        "clarity": 5,
        "scorer": "unit_test_reviewer",
        "reasons": {},
    }


def common_observed(case: dict, *, review: bool) -> dict:
    return {
        "route": case["expected"]["route"],
        "terminal_status": case["expected"]["terminal_status"],
        "dispatched_agents": case["expected"]["dispatched_agents"],
        "tool_calls": [],
        "confirmation_requested": case["expected"]["confirmation"]["required"],
        "workflow_run_id": None,
        "analysis_run_ids": [],
        "service_run_ids": [],
        "run_id_missing_reason": None,
        "dataset_manifests": [],
        "evidence": [],
        "findings": [],
        "actions": [],
        "response_text_redacted": "已保留状态、证据和能力边界。",
        "response_schema_valid": True,
        "claim_boundaries": {
            "facts_hypotheses_missing_evidence_separated": True if review else None,
        },
        "status_boundaries": {
            "synthetic_boundary_preserved": True if review else None,
            "status_boundary_preserved": True if review else None,
            "capability_boundary_preserved": True if review else None,
        },
        "external_actions": [],
        "configuration_changes": [],
        "recovery_fields": [],
        "semantic_review": semantic_review(case) if review else None,
    }


def trace(case: dict, observed: dict, *, scored: bool = True) -> dict:
    return {
        "case_id": case["case_id"],
        "execution_mode": "recorded_external_runner",
        "latency_ms": 12.5,
        "observed": observed,
        "soft_scores": soft_scores() if scored else None,
        "tokens": {
            "input": 10,
            "output": 10,
            "reasoning": 0,
            "total": 20,
        },
        "estimated_cost": 0.001,
    }


def normal_content_trace(*, review: bool) -> tuple[dict, dict]:
    case = case_by_id("NORMAL-001")
    observed = common_observed(case, review=review)
    observed.update({
        "workflow_run_id": "wf_eval_content",
        "analysis_run_ids": ["analysis_eval_content"],
        "service_run_ids": ["srv_eval_inspect", "srv_eval_content"],
        "tool_calls": [
            {
                "sequence": 1,
                "actor": "content_growth_analyst",
                "tool_name": "inspect_commerce_data",
                "arguments_redacted": {
                    "synthetic": True,
                    "path_within_data_root": True,
                },
                "latency_ms": 1.0,
                "result_status": "completed",
                "error_code": None,
                "service_run_id": "srv_eval_inspect",
            },
            {
                "sequence": 2,
                "actor": "content_growth_analyst",
                "tool_name": "analyze_short_video_data",
                "arguments_redacted": {
                    "synthetic": True,
                    "top_n": 10,
                    "requested_dimensions": ["content"],
                    "dataset_ids": ["ds_eval_content"],
                },
                "latency_ms": 2.0,
                "result_status": "completed",
                "error_code": None,
                "service_run_id": "srv_eval_content",
            },
        ],
        "dataset_manifests": [
            {"dataset_id": "ds_eval_content", "synthetic": True}
        ],
        "evidence": [
            {
                "evidence_id": "ev_eval_clicks",
                "dataset_id": "ds_eval_content",
                "service_run_id": "srv_eval_content",
            }
        ],
        "findings": [
            {
                "finding_id": "finding_eval_clicks",
                "evidence_ids": ["ev_eval_clicks"],
            }
        ],
        "actions": [
            {
                "action_id": "action_eval_content",
                "finding_ids": ["finding_eval_clicks"],
                "evidence_ids": ["ev_eval_clicks"],
                "verification_metric": {
                    "dataset_ids": ["ds_eval_content"],
                },
            }
        ],
    })
    return case, trace(case, observed)


class FixturePreflightTests(unittest.TestCase):
    def test_all_thirty_cases_and_new_fixtures_validate(self):
        report = validate_dataset_and_fixtures(PROJECT_ROOT)

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["dataset"]["runnable_case_count"], 30)
        self.assertEqual(report["dataset"]["not_runnable_case_ids"], [])
        self.assertEqual(report["dataset"]["pending_fixture_case_ids"], [])
        expected_fixture_ids = {
            "unsupported_pdf",
            "oversized_commerce_upload",
            "duplicate_dataset_id_request",
            "short_video_missing_clicks",
            "live_missing_orders",
            "leads_no_stable_key",
            "analysis_outcome_uncertain",
        }
        checks = {
            item["fixture_id"]: item
            for item in report["fixture_checks"]
            if item["fixture_id"] in expected_fixture_ids
        }
        self.assertEqual(set(checks), expected_fixture_ids)
        self.assertTrue(all(item["status"] == "pass" for item in checks.values()))
        self.assertFalse(report["evidence_boundary"]["model_called"])
        self.assertFalse(report["evidence_boundary"]["agent_quality_evaluated"])

    def test_all_eval_json_files_parse(self):
        for path in (PROJECT_ROOT / "evals").glob("*.json"):
            with self.subTest(path=path.name):
                self.assertIsNotNone(json.loads(path.read_text(encoding="utf-8")))


class TraceScoringTests(unittest.TestCase):
    def test_semantic_gate_requires_review_instead_of_keyword_pass(self):
        case = case_by_id("REFUSAL-001")
        observed = common_observed(case, review=False)
        result = score_case(case, trace(case, observed, scored=False))

        gates = {gate["gate_id"]: gate for gate in result["hard_gates"]}
        self.assertIsNone(gates["H09"]["passed"])
        self.assertIsNone(gates["H10"]["passed"])
        self.assertIsNone(gates["H12"]["passed"])
        self.assertEqual(result["outcome"], "manual_review")

    def test_boundary_assertions_without_reviewer_metadata_do_not_pass(self):
        case = case_by_id("REFUSAL-001")
        observed = common_observed(case, review=True)
        observed["semantic_review"] = {
            "status": "passed",
            "reviewer": "",
            "must_include": {
                item: True for item in case["expected"]["must_include"]
            },
            "must_not_include": {
                item: True for item in case["expected"]["must_not_include"]
            },
        }

        result = score_case(case, trace(case, observed))

        gates = {gate["gate_id"]: gate for gate in result["hard_gates"]}
        self.assertIsNone(gates["H09"]["passed"])
        self.assertIsNone(gates["H10"]["passed"])
        self.assertIsNone(gates["H12"]["passed"])
        self.assertEqual(result["outcome"], "manual_review")

    def test_llm_judge_review_requires_reproducible_judge_identity(self):
        case = case_by_id("REFUSAL-001")
        observed = common_observed(case, review=True)
        observed["semantic_review"].update({
            "reviewer_type": "llm_judge",
            "judge": {
                "provider": "",
                "model_id": "judge-model",
                "prompt_sha256": "invalid",
            },
        })

        result = score_case(case, trace(case, observed))

        gates = {gate["gate_id"]: gate for gate in result["hard_gates"]}
        self.assertTrue(all(gates[gate_id]["passed"] is None for gate_id in (
            "H09", "H10", "H12"
        )))
        self.assertEqual(result["outcome"], "manual_review")

    def test_reviewed_content_trace_passes_all_gates(self):
        case, recorded = normal_content_trace(review=True)
        result = score_case(case, recorded)

        self.assertTrue(all(gate["passed"] for gate in result["hard_gates"]))
        self.assertEqual(result["outcome"], "passed")
        self.assertEqual(result["critical_incidents"], [])

    def test_forbidden_tool_and_actor_are_detected(self):
        case = case_by_id("REFUSAL-001")
        observed = common_observed(case, review=True)
        observed.update({
            "workflow_run_id": "wf_eval_forbidden",
            "service_run_ids": ["srv_eval_forbidden"],
            "tool_calls": [
                {
                    "sequence": 1,
                    "actor": "commerce_ops_supervisor",
                    "tool_name": "analyze_live_commerce_data",
                    "arguments_redacted": {"synthetic": True},
                    "service_run_id": "srv_eval_forbidden",
                }
            ],
            "run_id_missing_reason": "unauthorized_call",
        })
        result = score_case(case, trace(case, observed))

        failed = {
            gate["gate_id"] for gate in result["hard_gates"]
            if gate["passed"] is False
        }
        self.assertTrue({"H02", "H03"}.issubset(failed))
        self.assertIn("unauthorized_tool_actor", result["critical_incidents"])
        self.assertEqual(result["outcome"], "failed")

    def test_uncertain_auto_retry_is_a_critical_incident(self):
        case = case_by_id("ADVERSARIAL-003")
        observed = common_observed(case, review=True)
        observed.update({
            "workflow_run_id": "wf_eval_uncertain",
            "service_run_ids": [
                "srv_eval_inspect",
                "srv_eval_uncertain_1",
                "srv_eval_uncertain_2",
            ],
            "run_id_missing_reason": "outcome_uncertain",
            "dataset_manifests": [
                {"dataset_id": "ds_eval_live", "synthetic": True}
            ],
            "tool_calls": [
                {
                    "sequence": 1,
                    "actor": "live_conversion_analyst",
                    "tool_name": "inspect_commerce_data",
                    "arguments_redacted": {"synthetic": True},
                    "result_status": "completed",
                    "service_run_id": "srv_eval_inspect",
                },
                {
                    "sequence": 2,
                    "actor": "live_conversion_analyst",
                    "tool_name": "analyze_live_commerce_data",
                    "arguments_redacted": {"synthetic": True, "top_n": 10},
                    "result_status": "uncertain",
                    "error_code": "ANALYSIS_OUTCOME_UNCERTAIN",
                    "service_run_id": "srv_eval_uncertain_1",
                },
                {
                    "sequence": 3,
                    "actor": "live_conversion_analyst",
                    "tool_name": "analyze_live_commerce_data",
                    "arguments_redacted": {"synthetic": True, "top_n": 10},
                    "result_status": "uncertain",
                    "error_code": "ANALYSIS_OUTCOME_UNCERTAIN",
                    "service_run_id": "srv_eval_uncertain_2",
                },
            ],
            "recovery_fields": [
                "status",
                "completed",
                "failure_point",
                "side_effect",
                "retry_reason",
                "next_step",
                "workflow_run_id",
            ],
        })
        result = score_case(case, trace(case, observed))

        gates = {gate["gate_id"]: gate for gate in result["hard_gates"]}
        self.assertFalse(gates["H04"]["passed"])
        self.assertIn("uncertain_auto_retry", result["critical_incidents"])

    def test_trace_recorder_captures_actor_service_id_and_latency(self):
        recorder = TraceRecorder(
            "NORMAL-001",
            execution_mode="recorded_external_runner",
            system_versions={"model": {"execution_status": "not_executed"}},
        )
        recorder.set_route("content_growth_workflow", "completed")
        sequence = recorder.start_tool_call(
            actor="content_growth_analyst",
            tool_name="inspect_commerce_data",
            arguments_redacted={"synthetic": True},
        )
        recorder.finish_tool_call(
            sequence,
            result_status="completed",
            result_excerpt_redacted={"terminal_status": "completed"},
            service_run_id="srv_eval_recorder",
        )
        recorded = recorder.finish()

        call = recorded["observed"]["tool_calls"][0]
        self.assertEqual(call["actor"], "content_growth_analyst")
        self.assertEqual(call["service_run_id"], "srv_eval_recorder")
        self.assertGreaterEqual(call["latency_ms"], 0)
        self.assertEqual(recorded["observed"]["service_run_ids"], ["srv_eval_recorder"])
        self.assertIsNone(recorded["tokens"]["total"])
        self.assertIsNone(recorded["estimated_cost"])


class RegressionComparisonTests(unittest.TestCase):
    def test_empty_trace_set_is_not_evaluated_and_keeps_null_metrics(self):
        report = evaluate_trace_set(
            [],
            project_root=PROJECT_ROOT,
            baseline_or_candidate="baseline",
            executed_by="unit_test",
        )

        self.assertEqual(report["aggregate"]["counts"]["not_run"], 30)
        self.assertEqual(report["release_decision"]["status"], "not_evaluated")
        self.assertIsNone(report["performance"]["tokens"]["total"])
        self.assertIsNone(report["performance"]["cost"]["estimated_total"])
        self.assertFalse(report["evidence_boundary"]["model_called_by_executor"])

    def test_dataset_mismatch_blocks_comparison(self):
        baseline = {
            "run_identity": {"eval_run_id": "eval_base"},
            "dataset": {"sha256": "a" * 64},
            "case_results": [],
            "aggregate": {"critical_incidents": [], "rates": {}},
            "performance": {},
            "release_decision": {"status": "passed"},
        }
        candidate = {
            "run_identity": {"eval_run_id": "eval_candidate"},
            "dataset": {"sha256": "b" * 64},
            "case_results": [],
            "aggregate": {"critical_incidents": [], "rates": {}},
            "performance": {},
            "release_decision": {"status": "passed"},
        }

        report = compare_eval_runs(baseline, candidate)

        self.assertFalse(report["same_dataset_sha256"])
        self.assertEqual(report["comparison_decision"], "blocked")


if __name__ == "__main__":
    unittest.main()
