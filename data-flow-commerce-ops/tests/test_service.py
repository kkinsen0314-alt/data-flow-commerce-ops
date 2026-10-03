from pathlib import Path
import unittest

from commerce_ops.service import CommerceOpsService
from commerce_ops.tool_models import (
    AttributionLeadAnalysisRequest,
    DataReference,
    DrilldownCommerceMetricRequest,
    InspectCommerceDataRequest,
    LiveCommerceAnalysisRequest,
    ShortVideoAnalysisRequest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data" / "fixtures"


def all_references() -> list[DataReference]:
    return [
        DataReference(
            dataset_id="ds_video",
            dataset_type="short_video",
            file_path="short_video/synthetic-short-video.csv",
        ),
        DataReference(
            dataset_id="ds_live",
            dataset_type="live_session",
            file_path="live/synthetic-live-integration.csv",
        ),
        DataReference(
            dataset_id="ds_lead",
            dataset_type="channel_lead",
            file_path="leads/synthetic-channel-leads.csv",
        ),
        DataReference(
            dataset_id="ds_followup",
            dataset_type="sales_followup",
            file_path="followup/synthetic-sales-followup.csv",
        ),
        DataReference(
            dataset_id="ds_order",
            dataset_type="order",
            file_path="orders/synthetic-orders.csv",
        ),
    ]


class CommerceOpsServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = CommerceOpsService(DATA_ROOT)
        self.workflow_run_id = "wf_service_test"

    def inspect_all(self):
        return self.service.inspect_commerce_data(
            InspectCommerceDataRequest(
                workflow_run_id=self.workflow_run_id,
                caller_role="content_growth_analyst",
                data_refs=all_references(),
                requested_domains=[
                    "content_growth",
                    "live_conversion",
                    "attribution_leads",
                ],
            )
        )

    def test_inspection_registers_five_pass_manifests(self):
        result = self.inspect_all()

        self.assertEqual(result.terminal_status, "completed")
        self.assertEqual(len(result.dataset_manifests), 5)
        self.assertEqual(
            {item.data_quality.status for item in result.dataset_manifests},
            {"pass"},
        )
        self.assertTrue(result.synthetic)
        self.assertEqual(result.caller_role, "content_growth_analyst")

    def test_short_video_analysis_and_content_drilldown(self):
        self.inspect_all()
        result = self.service.analyze_short_video_data(
            ShortVideoAnalysisRequest(
                workflow_run_id=self.workflow_run_id,
                dataset_ids=["ds_video", "ds_lead"],
                requested_dimensions=["account", "content"],
            )
        )

        self.assertEqual(result.terminal_status, "completed")
        packet = result.analysis_packet
        self.assertIsNotNone(packet)
        self.assertEqual(packet.agent_role, "content_growth_analyst")
        self.assertEqual(packet.domain, "content_growth")
        self.assertEqual(len(packet.evidence), 3)
        self.assertFalse(packet.service_calls[0].automatic_retry)
        self.assertEqual(packet.service_calls[0].side_effect_state, "none")

        drilldown = self.service.drilldown_commerce_metric(
            DrilldownCommerceMetricRequest(
                workflow_run_id=self.workflow_run_id,
                caller_role="content_growth_analyst",
                base_analysis_run_id=packet.analysis_run_id,
                evidence_id=packet.evidence[0].evidence_id,
                dimension="content",
                top_n=3,
            )
        )
        self.assertEqual(drilldown.terminal_status, "completed")
        self.assertEqual(len(drilldown.rows), 3)
        self.assertTrue(
            all("click_rate" in item.metrics for item in drilldown.rows)
        )

    def test_live_analysis_uses_legacy_fixture_as_live_domain_only(self):
        self.inspect_all()
        result = self.service.analyze_live_commerce_data(
            LiveCommerceAnalysisRequest(
                workflow_run_id=self.workflow_run_id,
                dataset_ids=["ds_live"],
                requested_dimensions=["live_session", "channel"],
            )
        )

        self.assertEqual(result.terminal_status, "completed")
        packet = result.analysis_packet
        self.assertEqual(packet.domain, "live_conversion")
        self.assertEqual(
            {item.metric_name for item in packet.evidence},
            {"attendance_rate", "purchase_rate"},
        )
        self.assertTrue(all(item.synthetic for item in packet.evidence))

    def test_attribution_is_partial_when_a_lead_lacks_followup(self):
        self.inspect_all()
        result = self.service.analyze_attribution_and_leads(
            AttributionLeadAnalysisRequest(
                workflow_run_id=self.workflow_run_id,
                dataset_ids=["ds_lead", "ds_followup", "ds_order"],
                requested_dimensions=["channel", "sales_owner", "order_status"],
                link_orders=True,
            )
        )

        self.assertEqual(result.terminal_status, "partial")
        packet = result.analysis_packet
        self.assertIn(
            "部分线索缺少首次跟进记录",
            packet.missing_evidence,
        )
        self.assertEqual(len(packet.evidence), 4)
        self.assertIn("关联不等于因果", packet.findings[0].limitations)

    def test_order_linking_without_order_dataset_is_blocked(self):
        self.inspect_all()
        result = self.service.analyze_attribution_and_leads(
            AttributionLeadAnalysisRequest(
                workflow_run_id=self.workflow_run_id,
                dataset_ids=["ds_lead", "ds_followup"],
                link_orders=True,
            )
        )

        self.assertEqual(result.terminal_status, "blocked")
        self.assertEqual(result.workflow_error.code, "RELATION_KEY_MISSING")
        self.assertFalse(result.workflow_error.retryable)

    def test_roi_without_cost_field_is_blocked(self):
        self.inspect_all()
        result = self.service.analyze_attribution_and_leads(
            AttributionLeadAnalysisRequest(
                workflow_run_id=self.workflow_run_id,
                dataset_ids=["ds_lead", "ds_followup", "ds_order"],
                link_orders=True,
                calculate_roi=True,
            )
        )

        self.assertEqual(result.terminal_status, "blocked")
        self.assertEqual(result.workflow_error.code, "COST_FIELD_MISSING")
        self.assertFalse(result.workflow_error.outcome_uncertain)

    def test_analysis_before_inspection_is_blocked_without_retry(self):
        result = self.service.analyze_short_video_data(
            ShortVideoAnalysisRequest(
                workflow_run_id=self.workflow_run_id,
                dataset_ids=["ds_video"],
            )
        )

        self.assertEqual(result.terminal_status, "blocked")
        self.assertEqual(result.workflow_error.code, "ANALYSIS_UNAVAILABLE")
        self.assertFalse(result.workflow_error.retryable)

    def test_path_outside_data_root_is_blocked(self):
        result = self.service.inspect_commerce_data(
            InspectCommerceDataRequest(
                workflow_run_id=self.workflow_run_id,
                caller_role="content_growth_analyst",
                data_refs=[
                    DataReference(
                        dataset_id="ds_outside",
                        dataset_type="short_video",
                        file_path="../README.md",
                    )
                ],
                requested_domains=["content_growth"],
            )
        )

        self.assertEqual(result.terminal_status, "blocked")
        self.assertEqual(result.workflow_error.code, "INVALID_INPUT")
        self.assertIn("数据根目录", result.workflow_error.safe_message)

    def test_drilldown_role_mismatch_fails_closed(self):
        self.inspect_all()
        result = self.service.analyze_short_video_data(
            ShortVideoAnalysisRequest(
                workflow_run_id=self.workflow_run_id,
                dataset_ids=["ds_video"],
            )
        )
        packet = result.analysis_packet

        drilldown = self.service.drilldown_commerce_metric(
            DrilldownCommerceMetricRequest(
                workflow_run_id=self.workflow_run_id,
                caller_role="live_conversion_analyst",
                base_analysis_run_id=packet.analysis_run_id,
                evidence_id=packet.evidence[0].evidence_id,
                dimension="content",
            )
        )

        self.assertEqual(drilldown.terminal_status, "blocked")
        self.assertEqual(drilldown.workflow_error.code, "INVALID_INPUT")

    def test_non_synthetic_reference_is_blocked(self):
        result = self.service.inspect_commerce_data(
            InspectCommerceDataRequest(
                workflow_run_id=self.workflow_run_id,
                caller_role="content_growth_analyst",
                data_refs=[
                    DataReference(
                        dataset_id="ds_real",
                        dataset_type="short_video",
                        file_path="short_video/synthetic-short-video.csv",
                        synthetic=False,
                    )
                ],
                requested_domains=["content_growth"],
            )
        )

        self.assertEqual(result.terminal_status, "blocked")
        self.assertIn("synthetic=true", result.workflow_error.safe_message)


if __name__ == "__main__":
    unittest.main()
