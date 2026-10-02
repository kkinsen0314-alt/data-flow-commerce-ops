from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from commerce_ops.evaluation import load_dataset


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "verify-evaluation-delivery-readiness.py"
PLAN_PATH = PROJECT_ROOT / "evals" / "real-run-plan-v1.json"


def load_readiness_module():
    spec = importlib.util.spec_from_file_location(
        "verify_evaluation_delivery_readiness",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载评测交付就绪验证器")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


readiness = load_readiness_module()


class EvaluationDeliveryReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (PROJECT_ROOT / "tmp").mkdir(parents=True, exist_ok=True)

    def test_run_plan_covers_all_cases_once_in_small_batches(self):
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        dataset = load_dataset()

        result = readiness._validate_plan(plan, dataset)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["case_count"], 30)
        self.assertEqual(result["batch_count"], 6)
        self.assertLessEqual(result["maximum_cases_per_batch"], 6)
        self.assertTrue(result["paid_execution_is_not_authorized_by_plan"])

    def test_run_plan_rejects_duplicate_case_identity(self):
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        dataset = load_dataset()
        invalid = deepcopy(plan)
        invalid["batches"][1]["case_ids"][0] = invalid["batches"][0][
            "case_ids"
        ][0]

        with self.assertRaises(readiness.ReadinessVerificationError):
            readiness._validate_plan(invalid, dataset)

    def test_current_readiness_is_truthfully_blocked_without_complete_run(self):
        report = readiness.build_report()

        self.assertEqual(report["verification_status"], "pass")
        self.assertEqual(report["fixture_preflight"]["runnable_case_count"], 30)
        self.assertEqual(
            report["real_evaluation_evidence"]["complete_30_case_run_count"],
            0,
        )
        self.assertLess(
            report["real_evaluation_evidence"][
                "maximum_completed_cases_in_one_run"
            ],
            30,
        )
        self.assertEqual(report["quality_release"]["status"], "blocked")
        self.assertEqual(
            report["paid_execution_gate"]["status"],
            "explicit_future_authorization_required",
        )
        self.assertFalse(
            report["paid_execution_gate"]["authorization_granted_by_this_plan"]
        )
        self.assertFalse(report["model_called"])
        self.assertFalse(report["judge_called"])

    def test_pre_b01_github_preview_is_truthfully_stale(self):
        required = [
            "README.md",
            "commerce_ops/native_eval_runner.py",
            "scripts/run-native-eval-batch.py",
            "tests/test_native_eval_runner.py",
        ]
        plan = {"github_delivery": {
            "required_current_paths": required,
            "forbidden_public_paths": ["runtime", "node_modules"],
            "preview_without_real_eval_allowed": True,
        }}
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "tmp") as folder:
            source_root = Path(folder)
            release_root = source_root / "release" / "preview"
            release_root.mkdir(parents=True)
            for relative in required:
                target = source_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("synthetic test fixture\n", encoding="utf-8")
            (release_root / "README.md").write_text("old preview\n", encoding="utf-8")
            with patch.object(readiness, "PROJECT_ROOT", source_root), patch.object(
                readiness, "RELEASE_ROOT", release_root
            ):
                github = readiness._github_delivery_status(plan)

        self.assertTrue(github["source_required_paths_present"])
        self.assertEqual(github["github_preview_status"], "stale_rebuild_required")
        self.assertEqual(
            github["release_missing_current_paths"],
            [
                "commerce_ops/native_eval_runner.py",
                "scripts/run-native-eval-batch.py",
                "tests/test_native_eval_runner.py",
            ],
        )
        self.assertTrue(github["preview_without_real_eval_allowed"])

    def test_partial_run_is_not_a_complete_or_passed_baseline(self):
        evidence = readiness._evaluation_evidence_status({
            "runs": [{
                "path": "synthetic-partial-run.json",
                "value": {
                    "run_identity": {"baseline_or_candidate": "baseline"},
                    "aggregate": {"counts": {"completed": 5}},
                    "case_results": [],
                    "release_decision": {"status": "blocked"},
                },
            }],
            "comparisons": [],
            "case_traces": [],
        })

        self.assertEqual(evidence["recorded_eval_run_count"], 1)
        self.assertEqual(evidence["maximum_completed_cases_in_one_run"], 5)
        self.assertEqual(evidence["complete_30_case_run_count"], 0)
        self.assertEqual(evidence["passed_baseline_count"], 0)
        self.assertEqual(evidence["passed_candidate_count"], 0)

    def test_current_source_preview_is_ready_without_quality_release(self):
        package_root = readiness.RELEASE_ROOT
        manifest = json.loads(
            (package_root / "PUBLIC-PREVIEW-MANIFEST.json").read_text(encoding="utf-8")
        )
        public_paths = [entry["path"] for entry in manifest["files"]]
        public_paths.extend(["FILE-MANIFEST.txt", "PUBLIC-PREVIEW-MANIFEST.json"])
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "tmp") as folder:
            snapshot = Path(folder)
            for relative in public_paths:
                target = snapshot / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(package_root / relative, target)
            with patch.object(readiness, "RELEASE_ROOT", snapshot):
                report = readiness.build_report()
        github = report["github_delivery"]

        self.assertTrue(github["source_required_paths_present"])
        self.assertEqual(github["release_missing_current_paths"], [])
        self.assertEqual(github["github_preview_status"], "current_file_set_present")
        self.assertEqual(github["status"], "ready")
        self.assertEqual(github["evaluated_release_status"], "blocked")


if __name__ == "__main__":
    unittest.main()
