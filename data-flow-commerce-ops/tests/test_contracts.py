import copy
import json
import unittest

from commerce_ops.contracts import (
    ContractValidationError,
    DEFAULT_SAMPLE,
    DEFAULT_SCHEMA,
    validate_contract_bundle,
    validate_contract_data,
)


class ContractValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(DEFAULT_SCHEMA.read_text(encoding="utf-8"))
        cls.sample = json.loads(DEFAULT_SAMPLE.read_text(encoding="utf-8"))

    def validate_mutation(self, mutation):
        sample = copy.deepcopy(self.sample)
        mutation(sample)
        return validate_contract_data(self.schema, sample)

    def test_current_contract_bundle_passes(self):
        result = validate_contract_bundle()

        self.assertEqual(
            self.schema["title"], "Data Flow Commerce Operations Workflow Contract v1"
        )
        self.assertEqual(result["json_schema"], "pass")
        self.assertEqual(result["pydantic_models"], "pass")
        self.assertEqual(result["reference_chain"], "pass")
        self.assertEqual(result["sensitive_token_scan"], "pass")
        self.assertEqual(result["dataset_count"], 5)
        self.assertEqual(result["analysis_packet_count"], 3)

    def test_unknown_dataset_reference_is_rejected(self):
        def mutate(sample):
            sample["analysis_packets"][0]["dataset_ids"] = ["ds_missing"]

        with self.assertRaisesRegex(
            ContractValidationError, "不存在的 dataset"
        ):
            self.validate_mutation(mutate)

    def test_missing_evidence_reference_is_rejected(self):
        def mutate(sample):
            sample["analysis_packets"][0]["findings"][0][
                "evidence_ids"
            ] = ["ev_missing"]

        with self.assertRaisesRegex(
            ContractValidationError, "不存在的 evidence"
        ):
            self.validate_mutation(mutate)

    def test_strategy_cannot_reference_missing_analysis(self):
        def mutate(sample):
            sample["decision_packet"]["source_analysis_ids"] = [
                "analysis_missing"
            ]

        with self.assertRaisesRegex(
            ContractValidationError, "不存在的 analysis"
        ):
            self.validate_mutation(mutate)

    def test_strategy_cannot_reference_missing_finding(self):
        def mutate(sample):
            sample["decision_packet"]["actions"][0]["finding_ids"] = [
                "finding_missing"
            ]

        with self.assertRaisesRegex(
            ContractValidationError, "不存在的 finding"
        ):
            self.validate_mutation(mutate)

    def test_strategy_cannot_reference_missing_action_evidence(self):
        def mutate(sample):
            sample["decision_packet"]["actions"][0]["evidence_ids"] = [
                "ev_missing"
            ]

        with self.assertRaisesRegex(
            ContractValidationError, "不存在的 evidence"
        ):
            self.validate_mutation(mutate)

    def test_strategy_verification_cannot_reference_missing_dataset(self):
        def mutate(sample):
            sample["decision_packet"]["actions"][0][
                "verification_metric"
            ]["dataset_ids"] = ["ds_missing"]

        with self.assertRaisesRegex(
            ContractValidationError, "不存在的 dataset"
        ):
            self.validate_mutation(mutate)

    def test_strategy_cannot_use_blocked_analysis(self):
        def mutate(sample):
            packet = sample["analysis_packets"][2]
            packet["terminal_status"] = "blocked"
            packet["evidence"] = []
            packet["findings"] = []

        with self.assertRaisesRegex(
            ContractValidationError, "不能进入策略阶段"
        ):
            self.validate_mutation(mutate)

    def test_attribution_is_rejected_without_stable_key(self):
        def mutate(sample):
            for manifest in sample["dataset_manifests"]:
                for key in manifest["relationship_keys"]:
                    key["stable"] = False

        with self.assertRaisesRegex(
            ContractValidationError, "稳定关联键"
        ):
            self.validate_mutation(mutate)

    def test_role_tool_allowlist_is_enforced(self):
        def mutate(sample):
            sample["analysis_packets"][0]["service_calls"][0][
                "tool_name"
            ] = "analyze_live_commerce_data"

        with self.assertRaisesRegex(
            ContractValidationError, "不允许调用"
        ):
            self.validate_mutation(mutate)

    def test_roi_is_rejected_without_cost_field(self):
        def mutate(sample):
            metric = sample["decision_packet"]["actions"][0][
                "verification_metric"
            ]
            metric["name"] = "ROI"
            metric["requires_cost_data"] = True

        with self.assertRaisesRegex(ContractValidationError, "ROI"):
            self.validate_mutation(mutate)

    def test_sensitive_secret_marker_is_rejected(self):
        def mutate(sample):
            sample["normalized_request"]["constraints"].append(
                "Authorization: Bearer example"
            )

        with self.assertRaisesRegex(
            ContractValidationError, "敏感令牌"
        ):
            self.validate_mutation(mutate)

    def test_schema_rejects_unknown_property(self):
        def mutate(sample):
            sample["normalized_request"]["unexpected"] = True

        with self.assertRaisesRegex(
            ContractValidationError, "JSON Schema"
        ):
            self.validate_mutation(mutate)


if __name__ == "__main__":
    unittest.main()
