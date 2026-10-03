from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from commerce_ops.demo_models import (
    DemoRunRequest,
    DemoUploadedFile,
    DemoUploadDatasetSpec,
    DemoUploadRunRequest,
)
from commerce_ops.demo_orchestrator import (
    DemoInputError,
    DemoOrchestrator,
    DemoRunNotFound,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data" / "fixtures"


class DemoOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.orchestrator = DemoOrchestrator(
            DATA_ROOT,
            upload_root=Path(self.temp_directory.name),
        )

    def test_scenario_catalog_keeps_runtime_boundary_explicit(self):
        catalog = self.orchestrator.scenarios()

        self.assertEqual(catalog.default_scenario_id, "full_commerce_funnel")
        self.assertEqual(len(catalog.scenarios), 1)
        scenario = catalog.scenarios[0]
        self.assertFalse(scenario.provider_required)
        self.assertFalse(scenario.agent_runtime_executed)
        self.assertTrue(all(item.synthetic for item in scenario.datasets))

    def test_full_sample_run_builds_three_domain_evidence_chain(self):
        result = self.orchestrator.run_sample(DemoRunRequest())

        self.assertEqual(result.terminal_status, "partial")
        self.assertTrue(result.synthetic)
        self.assertFalse(result.provider_called)
        self.assertFalse(result.agent_runtime_executed)
        self.assertEqual(len(result.analysis_packets), 3)
        self.assertEqual(len(result.drilldowns), 3)
        self.assertEqual(len(result.decision_packet.actions), 3)
        self.assertEqual(len(result.dataset_manifests), 5)
        self.assertEqual(
            {item.domain for item in result.analysis_packets},
            {"content_growth", "live_conversion", "attribution_leads"},
        )
        self.assertTrue(
            all(item.execution_kind == "deterministic_service" for item in result.workflow_steps)
        )
        self.assertTrue(result.delivery_package.requires_human_confirmation)
        self.assertIn(
            "部分线索缺少首次跟进记录",
            result.unresolved_items,
        )

    def test_single_domain_run_only_routes_selected_specialist(self):
        result = self.orchestrator.run_sample(
            DemoRunRequest(
                requested_domains=["live_conversion"],
                include_drilldowns=False,
            )
        )

        self.assertEqual(len(result.analysis_packets), 1)
        self.assertEqual(result.analysis_packets[0].domain, "live_conversion")
        self.assertEqual(result.drilldowns, [])
        roles = {item.actor_role for item in result.workflow_steps}
        self.assertNotIn("content_growth_analyst", roles)
        self.assertNotIn("attribution_lead_analyst", roles)
        self.assertIn("commerce_review_strategist", roles)

    def test_saved_result_can_be_retrieved_without_shared_mutation(self):
        result = self.orchestrator.run_sample(DemoRunRequest())
        retrieved = self.orchestrator.get_run(result.workflow_run_id)

        retrieved.unresolved_items.append("local mutation")
        second = self.orchestrator.get_run(result.workflow_run_id)
        self.assertNotIn("local mutation", second.unresolved_items)

        with self.assertRaises(DemoRunNotFound):
            self.orchestrator.get_run("wf_demo_missing")

    def test_uploaded_synthetic_files_use_the_same_workflow(self):
        paths = [
            ("short-video.csv", DATA_ROOT / "short_video" / "synthetic-short-video.csv"),
            ("live.csv", DATA_ROOT / "live" / "synthetic-live-integration.csv"),
            ("leads.csv", DATA_ROOT / "leads" / "synthetic-channel-leads.csv"),
            ("followup.csv", DATA_ROOT / "followup" / "synthetic-sales-followup.csv"),
            ("orders.csv", DATA_ROOT / "orders" / "synthetic-orders.csv"),
        ]
        dataset_types = [
            "short_video",
            "live_session",
            "channel_lead",
            "sales_followup",
            "order",
        ]
        request = DemoUploadRunRequest(
            datasets=[
                DemoUploadDatasetSpec(
                    dataset_id=f"ds_upload_{index}",
                    dataset_type=dataset_type,
                    file_index=index,
                    display_name=file_name,
                )
                for index, ((file_name, _), dataset_type) in enumerate(
                    zip(paths, dataset_types)
                )
            ],
            requested_domains=[
                "content_growth",
                "live_conversion",
                "attribution_leads",
            ],
            objective="验证上传的合成数据。",
        )
        files = [
            DemoUploadedFile(file_name=file_name, content=path.read_bytes())
            for file_name, path in paths
        ]

        result = self.orchestrator.run_upload(request, files)

        self.assertEqual(len(result.analysis_packets), 3)
        self.assertEqual(len(result.dataset_manifests), 5)
        self.assertEqual(result.scenario.scenario_id, "uploaded_synthetic_data")
        self.assertFalse(any(Path(self.temp_directory.name).iterdir()))

    def test_upload_missing_required_domain_type_is_rejected(self):
        request = DemoUploadRunRequest(
            datasets=[
                DemoUploadDatasetSpec(
                    dataset_id="ds_only_leads",
                    dataset_type="channel_lead",
                    file_index=0,
                    display_name="线索数据",
                )
            ],
            requested_domains=["content_growth"],
            objective="缺少短视频数据的错误示例。",
        )
        files = [
            DemoUploadedFile(
                file_name="leads.csv",
                content=(
                    DATA_ROOT / "leads" / "synthetic-channel-leads.csv"
                ).read_bytes(),
            )
        ]

        with self.assertRaisesRegex(DemoInputError, "short_video"):
            self.orchestrator.run_upload(request, files)


if __name__ == "__main__":
    unittest.main()
