from datetime import UTC, datetime
import json
import unittest

from commerce_ops.native_models import (
    NativeDatasetReference,
    NativeLedgerSummary,
    NativeReconciliation,
    NativeRunResult,
)
from commerce_ops.native_presenter import build_operator_result_view


def make_record(
    *,
    phase="settled",
    terminal_status="completed",
    operator_result=None,
    include_strategy=True,
    include_marker=True,
):
    now = datetime(2026, 9, 9, 8, 0, tzinfo=UTC)
    final_response = None
    if operator_result is not None:
        payload = {
            "schema_version": "1.0",
            "result_type": "project017_native_agent_result",
            "operator_result": operator_result,
        }
        marker = "PROJECT017_NATIVE_RESULT_JSON\n" if include_marker else ""
        final_response = (
            "分析已完成。\n"
            + marker
            + "```json\n"
            + json.dumps(payload, ensure_ascii=False)
            + "\n```"
        )
    return NativeRunResult(
        workflow_run_id="wf_native_result_001",
        idempotency_key="native-result-001",
        request_fingerprint="a" * 64,
        workspace_jid="web:workspace",
        session_id="session-1",
        phase=phase,
        submission_state="accepted",
        terminal_status=terminal_status,
        requested_domains=["content_growth"],
        datasets=[
            NativeDatasetReference(
                dataset_id="ds_native_result_01",
                dataset_type="short_video",
                file_path="fixture.csv",
            )
        ],
        include_strategy=include_strategy,
        created_at=now,
        updated_at=now,
        observed_execution_state=("settled" if phase == "settled" else "pending"),
        final_response=final_response,
        ledger=NativeLedgerSummary(
            parent_agent_attempts=0,
            specialist_tool_attempts=0,
            total_attempts=0,
            completed_attempts=0,
            failed_or_blocked_attempts=0,
            unfinished_attempts=0,
        ),
        reconciliation=NativeReconciliation(
            audit_available=True,
            final_response_structured=operator_result is not None,
            observed_total_attempts=0,
        ),
    )


def valid_operator_result():
    return {
        "headline": "内容点击后的承接仍有提升空间",
        "summary": "高互动内容已形成稳定流量，但进入直播间后的商品访问需要优先优化。",
        "findings": [
            {
                "domain": "content_growth",
                "title": "高互动内容贡献主要点击",
                "summary": "重点内容组合带来的点击更集中，可继续验证相同选题。",
                "metrics": [
                    {
                        "label": "点击贡献",
                        "value": "62%",
                        "context": "当前所选数据范围",
                    }
                ],
                "evidence_basis": ["内容点击分布与互动表现方向一致。"],
                "limitations": ["仅适用于当前所选数据。"],
            }
        ],
        "actions": [
            {
                "title": "复用高互动选题并优化直播承接",
                "priority": "high",
                "owner": "内容运营",
                "due_window": "下个运营周期",
                "rationale": "点击集中但后续访问仍有流失。",
                "verification": "复验点击到商品访问的转化变化。",
                "guardrails": ["先小范围验证，不直接扩大投放。"],
            }
        ],
        "notices": ["结果来自电商运营测试数据。"],
    }


class NativePresenterTests(unittest.TestCase):
    def test_completed_result_returns_strict_operator_view(self):
        view = build_operator_result_view(
            make_record(operator_result=valid_operator_result())
        )

        self.assertEqual(view.view_state, "ready")
        self.assertEqual(view.headline, "内容点击后的承接仍有提升空间")
        self.assertEqual(len(view.findings), 1)
        self.assertEqual(len(view.actions), 1)
        self.assertNotIn("wf_native_result_001", view.model_dump_json())

    def test_partial_result_remains_visible_with_data_notice(self):
        view = build_operator_result_view(
            make_record(
                terminal_status="partial",
                operator_result=valid_operator_result(),
            )
        )

        self.assertEqual(view.view_state, "ready")
        self.assertEqual(len(view.findings), 1)

    def test_valid_typed_json_fence_is_accepted_without_marker(self):
        view = build_operator_result_view(
            make_record(
                terminal_status="partial",
                operator_result=valid_operator_result(),
                include_marker=False,
            )
        )

        self.assertEqual(view.view_state, "ready")
        self.assertEqual(view.headline, "内容点击后的承接仍有提升空间")

    def test_internal_reference_causes_fail_closed_result(self):
        content = valid_operator_result()
        content["summary"] = "请查看 analysis_internal_001 获取详细结论。"
        view = build_operator_result_view(make_record(operator_result=content))

        self.assertEqual(view.view_state, "unavailable")
        self.assertEqual(view.findings, [])
        self.assertNotIn("analysis_internal_001", view.model_dump_json())

    def test_out_of_scope_domain_causes_fail_closed_result(self):
        content = valid_operator_result()
        content["findings"][0]["domain"] = "live_conversion"
        view = build_operator_result_view(make_record(operator_result=content))

        self.assertEqual(view.view_state, "unavailable")
        self.assertEqual(view.findings, [])

    def test_actions_are_rejected_without_strategy_scope(self):
        view = build_operator_result_view(
            make_record(
                operator_result=valid_operator_result(),
                include_strategy=False,
            )
        )

        self.assertEqual(view.view_state, "unavailable")
        self.assertEqual(view.actions, [])

    def test_processing_and_blocked_states_never_expose_raw_output(self):
        processing = build_operator_result_view(
            make_record(phase="running", terminal_status=None)
        )
        blocked = build_operator_result_view(
            make_record(
                terminal_status="blocked",
                operator_result=valid_operator_result(),
            )
        )

        self.assertEqual(processing.view_state, "processing")
        self.assertEqual(blocked.view_state, "unavailable")
        self.assertEqual(blocked.actions, [])


if __name__ == "__main__":
    unittest.main()
