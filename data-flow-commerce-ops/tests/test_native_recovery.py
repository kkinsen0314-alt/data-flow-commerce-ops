from datetime import UTC, datetime
import json
from pathlib import Path
import unittest

from pydantic import ValidationError

from commerce_ops.native_models import (
    NativeDatasetReference,
    NativeLedgerSummary,
    NativeReconciliation,
    NativeRunResult,
)
from commerce_ops.native_recovery import (
    NativeRecoverySnapshot,
    build_native_recovery_plan,
    plan_native_recovery,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PROJECT_ROOT / "contracts" / "native-recovery-cases-v1.json"


class NativeRecoveryTests(unittest.TestCase):
    def test_catalog_cases_match_production_recovery_planner(self):
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(catalog["schema_version"], "1.0")
        self.assertEqual(len(catalog["cases"]), 8)
        self.assertEqual(
            len({item["case_id"] for item in catalog["cases"]}),
            len(catalog["cases"]),
        )

        for item in catalog["cases"]:
            with self.subTest(case_id=item["case_id"]):
                plan = plan_native_recovery(
                    NativeRecoverySnapshot.model_validate(item["snapshot"])
                )
                expected = item["expected"]
                self.assertEqual(plan.scenario, expected["scenario"])
                self.assertEqual(
                    plan.automatic_retry_allowed,
                    expected["automatic_retry_allowed"],
                )
                self.assertEqual(
                    plan.same_run_observation_required,
                    expected["same_run_observation_required"],
                )
                self.assertEqual(plan.new_run_policy, expected["new_run_policy"])
                self.assertTrue(
                    set(expected["required_allowed_steps"]).issubset(
                        plan.allowed_steps
                    )
                )
                self.assertTrue(
                    set(expected["required_forbidden_steps"]).issubset(
                        plan.forbidden_steps
                    )
                )

    def test_uncertain_state_forbids_replacement_run(self):
        plan = plan_native_recovery(
            NativeRecoverySnapshot(
                phase="settled",
                submission_state="uncertain",
                terminal_status="uncertain",
                operator_view_state="unavailable",
            )
        )
        self.assertFalse(plan.automatic_retry_allowed)
        self.assertTrue(plan.same_run_observation_required)
        self.assertEqual(
            plan.new_run_policy,
            "forbidden_until_original_resolved",
        )
        self.assertIn(
            "create_replacement_run_before_resolution",
            plan.forbidden_steps,
        )
        self.assertNotIn("create_new_run_after_authorization", plan.allowed_steps)

    def test_recovery_snapshot_rejects_inconsistent_lifecycle(self):
        invalid_snapshots = [
            {
                "phase": "settled",
                "submission_state": "accepted",
                "terminal_status": None,
                "operator_view_state": "processing",
            },
            {
                "phase": "running",
                "submission_state": "accepted",
                "terminal_status": "completed",
                "operator_view_state": "ready",
            },
            {
                "phase": "settled",
                "submission_state": "accepted",
                "terminal_status": "blocked",
                "operator_view_state": "ready",
            },
        ]
        for snapshot in invalid_snapshots:
            with self.subTest(snapshot=snapshot):
                with self.assertRaises(ValidationError):
                    NativeRecoverySnapshot.model_validate(snapshot)

    def test_record_adapter_uses_fail_closed_operator_projection(self):
        now = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
        record = NativeRunResult(
            workflow_run_id="wf_native_recovery_001",
            idempotency_key="native-recovery-001",
            request_fingerprint="a" * 64,
            workspace_jid="web:workspace",
            session_id="session-recovery-001",
            phase="settled",
            submission_state="accepted",
            terminal_status="completed",
            requested_domains=["content_growth"],
            datasets=[
                NativeDatasetReference(
                    dataset_id="ds_native_recovery_01",
                    dataset_type="short_video",
                    file_path="data/fixtures/short-video-sample.csv",
                )
            ],
            include_strategy=True,
            created_at=now,
            updated_at=now,
            settled_at=now,
            observed_execution_state="settled",
            final_response="没有可验证的运营结果结构。",
            ledger=NativeLedgerSummary(
                parent_agent_attempts=0,
                specialist_tool_attempts=0,
                total_attempts=0,
                completed_attempts=0,
                failed_or_blocked_attempts=0,
                unfinished_attempts=0,
            ),
            reconciliation=NativeReconciliation(
                audit_available=False,
                final_response_structured=False,
                observed_total_attempts=0,
            ),
        )

        plan = build_native_recovery_plan(record)

        self.assertEqual(plan.scenario, "operator_projection_unavailable")
        self.assertIn("correct_operator_projection_contract", plan.allowed_steps)
        self.assertIn("expose_raw_model_output", plan.forbidden_steps)


if __name__ == "__main__":
    unittest.main()
