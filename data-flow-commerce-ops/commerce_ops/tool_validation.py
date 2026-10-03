"""Reproducible synthetic validation for the deterministic tool layer."""

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from .service import CommerceOpsService
from .tool_models import (
    AttributionLeadAnalysisRequest,
    DataReference,
    DrilldownCommerceMetricRequest,
    InspectCommerceDataRequest,
    LiveCommerceAnalysisRequest,
    ShortVideoAnalysisRequest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data" / "fixtures"


def fixture_references() -> list[DataReference]:
    return [
        DataReference(
            dataset_id="ds_video_validation",
            dataset_type="short_video",
            file_path="short_video/synthetic-short-video.csv",
        ),
        DataReference(
            dataset_id="ds_live_validation",
            dataset_type="live_session",
            file_path="live/synthetic-live-integration.csv",
        ),
        DataReference(
            dataset_id="ds_lead_validation",
            dataset_type="channel_lead",
            file_path="leads/synthetic-channel-leads.csv",
        ),
        DataReference(
            dataset_id="ds_followup_validation",
            dataset_type="sales_followup",
            file_path="followup/synthetic-sales-followup.csv",
        ),
        DataReference(
            dataset_id="ds_order_validation",
            dataset_type="order",
            file_path="orders/synthetic-orders.csv",
        ),
    ]


def validate_tool_layer() -> dict[str, Any]:
    service = CommerceOpsService(DATA_ROOT)
    workflow_run_id = "wf_tool_validation_v1"
    inspection = service.inspect_commerce_data(
        InspectCommerceDataRequest(
            workflow_run_id=workflow_run_id,
            caller_role="content_growth_analyst",
            data_refs=fixture_references(),
            requested_domains=[
                "content_growth",
                "live_conversion",
                "attribution_leads",
            ],
        )
    )
    video = service.analyze_short_video_data(
        ShortVideoAnalysisRequest(
            workflow_run_id=workflow_run_id,
            dataset_ids=["ds_video_validation", "ds_lead_validation"],
            requested_dimensions=["account", "content"],
        )
    )
    live = service.analyze_live_commerce_data(
        LiveCommerceAnalysisRequest(
            workflow_run_id=workflow_run_id,
            dataset_ids=["ds_live_validation"],
            requested_dimensions=["live_session", "channel"],
        )
    )
    attribution = service.analyze_attribution_and_leads(
        AttributionLeadAnalysisRequest(
            workflow_run_id=workflow_run_id,
            dataset_ids=[
                "ds_lead_validation",
                "ds_followup_validation",
                "ds_order_validation",
            ],
            requested_dimensions=["channel", "sales_owner", "order_status"],
        )
    )
    video_packet = video.analysis_packet
    if video_packet is None:
        raise RuntimeError("短视频合成验证没有生成 AnalysisPacket")
    drilldown = service.drilldown_commerce_metric(
        DrilldownCommerceMetricRequest(
            workflow_run_id=workflow_run_id,
            caller_role="content_growth_analyst",
            base_analysis_run_id=video_packet.analysis_run_id,
            evidence_id=video_packet.evidence[0].evidence_id,
            dimension="content",
            top_n=3,
        )
    )
    no_relation = service.analyze_attribution_and_leads(
        AttributionLeadAnalysisRequest(
            workflow_run_id=workflow_run_id,
            dataset_ids=["ds_lead_validation", "ds_followup_validation"],
            link_orders=True,
        )
    )
    no_cost = service.analyze_attribution_and_leads(
        AttributionLeadAnalysisRequest(
            workflow_run_id=workflow_run_id,
            dataset_ids=[
                "ds_lead_validation",
                "ds_followup_validation",
                "ds_order_validation",
            ],
            link_orders=True,
            calculate_roi=True,
        )
    )

    checks = {
        "five_manifests_pass": (
            inspection.terminal_status == "completed"
            and len(inspection.dataset_manifests) == 5
            and all(
                item.data_quality.status == "pass"
                for item in inspection.dataset_manifests
            )
        ),
        "short_video_completed": video.terminal_status == "completed",
        "live_completed": live.terminal_status == "completed",
        "attribution_partial_preserves_missing_evidence": (
            attribution.terminal_status == "partial"
            and attribution.analysis_packet is not None
            and bool(attribution.analysis_packet.missing_evidence)
        ),
        "drilldown_completed": (
            drilldown.terminal_status == "completed" and len(drilldown.rows) == 3
        ),
        "missing_relation_key_blocked": (
            no_relation.workflow_error is not None
            and no_relation.workflow_error.code == "RELATION_KEY_MISSING"
        ),
        "missing_cost_roi_blocked": (
            no_cost.workflow_error is not None
            and no_cost.workflow_error.code == "COST_FIELD_MISSING"
        ),
        "no_automatic_retry": all(
            not call.automatic_retry
            for result in (video, live, attribution)
            if result.analysis_packet is not None
            for call in result.analysis_packet.service_calls
        ),
        "read_only_side_effect_state": all(
            call.side_effect_state == "none"
            for result in (video, live, attribution)
            if result.analysis_packet is not None
            for call in result.analysis_packet.service_calls
        ),
        "synthetic_evidence_only": all(
            evidence.synthetic
            for result in (video, live, attribution)
            if result.analysis_packet is not None
            for evidence in result.analysis_packet.evidence
        ),
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError(f"工具层验证失败：{', '.join(failed)}")

    return {
        "schema_version": "1.0",
        "record_type": "commerce_ops_tool_layer_validation",
        "status": "pass",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "checks": checks,
        "counts": {
            "fixture_count": len(fixture_references()),
            "manifest_count": len(inspection.dataset_manifests),
            "analysis_packet_count": sum(
                result.analysis_packet is not None
                for result in (video, live, attribution)
            ),
            "evidence_count": sum(
                len(result.analysis_packet.evidence)
                for result in (video, live, attribution)
                if result.analysis_packet is not None
            ),
            "finding_count": sum(
                len(result.analysis_packet.findings)
                for result in (video, live, attribution)
                if result.analysis_packet is not None
            ),
            "drilldown_row_count": len(drilldown.rows),
        },
        "terminal_statuses": {
            "inspection": inspection.terminal_status,
            "short_video": video.terminal_status,
            "live": live.terminal_status,
            "attribution": attribution.terminal_status,
            "drilldown": drilldown.terminal_status,
            "missing_relation_key": no_relation.terminal_status,
            "missing_cost_roi": no_cost.terminal_status,
        },
        "evidence_boundary": {
            "synthetic_data_only": True,
            "deterministic_tools_executed": True,
            "http_chain_covered_by_tests": True,
            "stdio_mcp_chain_covered_by_tests": True,
            "provider_configured": False,
            "plugin_enabled": False,
            "agent_session_created": False,
            "model_called": False,
            "multi_agent_executed": False,
            "real_business_data_used": False,
            "business_outcome_claimed": False,
        },
    }


def main() -> None:
    print(json.dumps(validate_tool_layer(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
