from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import httpx

from commerce_ops.app import create_app
from commerce_ops.native_models import (
    NativeDatasetReference,
    NativeLedgerSummary,
    NativeReconciliation,
    NativeRunResult,
    NativeRuntimeConfiguration,
)
from commerce_ops.native_runtime import (
    NativeRunNotFound,
    NativeRuntimeUnavailable,
)
from commerce_ops.service import CommerceOpsService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data" / "fixtures"


class StubNativeRuntime:
    def __init__(self) -> None:
        self.configuration = NativeRuntimeConfiguration(
            base_url="http://127.0.0.1:3017",
            workspace_configured=True,
            credentials_configured=True,
            ready=True,
            agent_profile_name="电商运营多 Agent 工作流总控",
            project_root=str(PROJECT_ROOT),
        )
        self.start_calls = 0
        self.last_payload = None
        self.last_operator_visible = False
        self.refresh_result = None
        self.refresh_calls = 0
        self.list_results = []

    async def start(self, payload, *, operator_visible=False):
        self.start_calls += 1
        self.last_payload = payload
        self.last_operator_visible = operator_visible
        raise NativeRuntimeUnavailable("测试运行器未连接。")

    async def refresh(self, workflow_run_id: str):
        self.refresh_calls += 1
        if self.refresh_result is not None:
            return self.refresh_result
        raise NativeRunNotFound("原生运行不存在。")

    def list_operator_runs(self, limit=20):
        return self.list_results if limit is None else self.list_results[:limit]

    async def aclose(self):
        pass


class NativeApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.runtime = StubNativeRuntime()
        self.app = create_app(
            CommerceOpsService(DATA_ROOT),
            native_runtime=self.runtime,
        )

    async def request(self, method: str, path: str, **kwargs):
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    async def test_configuration_exposes_readiness_but_not_credentials(self):
        response = await self.request("GET", "/v1/native/configuration")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ready"])
        self.assertNotIn("password", response.text.lower())
        self.assertNotIn("cookie", response.text.lower())
        self.assertNotIn("session-secret", response.text.lower())

    async def test_native_entry_redirects_and_legacy_assets_are_retained(self):
        root = await self.request("GET", "/")
        self.assertEqual(root.status_code, 307)
        self.assertEqual(root.headers["location"], "/native")

        page = await self.request("GET", "/native")
        self.assertEqual(page.status_code, 307)
        self.assertEqual(page.headers["location"], "http://127.0.0.1:3017/operations")
        page = SimpleNamespace(text=(PROJECT_ROOT / "native_web" / "index.html").read_text(encoding="utf-8"))
        self.assertIn("运营分析工作台", page.text)
        self.assertIn("设置分析范围", page.text)
        self.assertIn("Data Flow", page.text)
        self.assertIn("数据源管理", page.text)
        self.assertIn("接入类型", page.text)
        self.assertIn("支持的接入方式", page.text)
        self.assertNotIn("第 13 期数据底座", page.text)
        self.assertNotIn("51 / 51", page.text)
        self.assertNotIn("commerce_ops_supervisor", page.text)
        self.assertNotIn("content_growth_analyst", page.text)
        self.assertNotIn("/v1/demo/runs", page.text)

        styles = await self.request("GET", "/native/assets/styles.css")
        script = await self.request("GET", "/native/assets/app.js")
        self.assertEqual(styles.status_code, 200)
        self.assertEqual(script.status_code, 200)
        self.assertIn("/v1/native/configuration", script.text)
        self.assertIn("/v1/native/data-sources", script.text)
        self.assertNotIn("/v1/native/period-13", script.text)
        self.assertIn("/v1/native/runs", script.text)
        self.assertIn("/v1/native/tasks", script.text)
        self.assertIn("data-task-history-list", page.text)
        self.assertIn("data-refresh-tasks", page.text)
        self.assertEqual(
            script.text.count("postJsonOnce(RUNS_ENDPOINT, payload)"),
            1,
        )
        self.assertIn('fee_confirmation: "confirmed"', script.text)
        self.assertIn("pollRun(activeRunContext.workflowRunId)", script.text)

        catalog = await self.request("GET", "/v1/native/data-sources")
        self.assertEqual(catalog.status_code, 200)
        catalog_body = catalog.json()
        self.assertEqual(catalog_body["default_source_id"], "sample-commerce-data")
        self.assertEqual(len(catalog_body["sources"]), 1)
        source = catalog_body["sources"][0]
        self.assertEqual(source["display_name"], "电商运营测试数据")
        self.assertEqual(source["source_type"], "local_file")
        self.assertEqual(source["source_type_label"], "本地文件（CSV）")
        self.assertEqual(source["dataset_labels"], [
            "短视频",
            "直播场次",
            "渠道线索",
            "销售跟进",
            "订单",
        ])
        self.assertEqual(catalog_body["sources"][0]["record_count"], 89)
        self.assertEqual(len(catalog_body["source_types"]), 7)
        self.assertIn(
            "mysql",
            {item["type_id"] for item in catalog_body["source_types"]},
        )
        self.assertIn(
            "feishu_bitable",
            {item["type_id"] for item in catalog_body["source_types"]},
        )
        self.assertNotIn(str(PROJECT_ROOT).lower(), catalog.text.lower())

        summary = await self.request("GET", "/v1/native/period-13")
        self.assertEqual(summary.status_code, 200)
        body = summary.json()
        self.assertTrue(body["synthetic"])
        self.assertEqual(body["checks_passed"], 51)
        self.assertEqual(body["checks_total"], 51)
        self.assertEqual(body["total_rows"], 89)
        self.assertEqual(len(body["datasets"]), 5)
        self.assertEqual(body["metrics"]["paid_order_count"], 9)
        self.assertNotIn(str(PROJECT_ROOT).lower(), summary.text.lower())
        self.assertNotIn("password", summary.text.lower())

    async def test_model_execution_requires_literal_authorization(self):
        response = await self.request(
            "POST",
            "/v1/native/runs",
            json={
                "idempotency_key": "native-api-0001",
                "requested_domains": ["content_growth"],
                "datasets": [
                    {
                        "dataset_type": "short_video",
                        "file_path": "short_video/synthetic-short-video.csv",
                    }
                ],
                "objective": "分析合成数据",
                "include_strategy": False,
                "authorized_model_execution": False,
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.runtime.start_calls, 0)

    async def test_operator_run_requires_fee_confirmation(self):
        response = await self.request(
            "POST",
            "/v1/native/runs",
            json={
                "idempotency_key": "native-ui-no-fee-0001",
                "source_id": "sample-commerce-data",
                "requested_domains": ["content_growth"],
                "objective": "分析内容表现",
                "include_strategy": True,
                "fee_confirmation": "not_confirmed",
                "authorized_model_execution": True,
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.runtime.start_calls, 0)

    async def test_operator_run_maps_source_to_required_server_datasets(self):
        response = await self.request(
            "POST",
            "/v1/native/runs",
            json={
                "idempotency_key": "native-ui-confirmed-0001",
                "source_id": "sample-commerce-data",
                "requested_domains": [
                    "content_growth",
                    "live_conversion",
                    "attribution_leads",
                ],
                "objective": "识别主要流失环节并生成行动建议",
                "include_strategy": True,
                "fee_confirmation": "confirmed",
                "authorized_model_execution": True,
            },
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.runtime.start_calls, 1)
        self.assertEqual(
            [item.dataset_type for item in self.runtime.last_payload.datasets],
            [
                "short_video",
                "live_session",
                "channel_lead",
                "sales_followup",
                "order",
            ],
        )
        self.assertTrue(self.runtime.last_payload.authorized_model_execution)
        self.assertTrue(self.runtime.last_operator_visible)

    async def test_unknown_operator_source_never_enters_runtime(self):
        response = await self.request(
            "POST",
            "/v1/native/runs",
            json={
                "idempotency_key": "native-ui-unknown-0001",
                "source_id": "unknown-source",
                "requested_domains": ["content_growth"],
                "objective": "分析内容表现",
                "include_strategy": False,
                "fee_confirmation": "confirmed",
                "authorized_model_execution": True,
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.runtime.start_calls, 0)

    async def test_unknown_run_returns_404(self):
        response = await self.request("GET", "/v1/native/runs/wf_native_missing")
        self.assertEqual(response.status_code, 404)

    async def test_operator_result_route_exposes_only_safe_projection(self):
        now = datetime(2026, 9, 9, 8, 0, tzinfo=UTC)
        operator_result = {
            "headline": "优先改善内容到直播的承接",
            "summary": "重点内容带来更多点击，但后续商品访问仍有提升空间。",
            "findings": [],
            "actions": [],
            "notices": ["结果来自电商运营测试数据。"],
        }
        final_payload = {
            "schema_version": "1.0",
            "result_type": "project017_native_agent_result",
            "workflow_run_id": "wf_native_result_api_001",
            "operator_result": operator_result,
        }
        record = NativeRunResult(
            workflow_run_id="wf_native_result_api_001",
            idempotency_key="native-result-api-001",
            request_fingerprint="b" * 64,
            workspace_jid="web:workspace",
            session_id="session-api-1",
            phase="settled",
            submission_state="accepted",
            terminal_status="completed",
            requested_domains=["content_growth"],
            datasets=[
                NativeDatasetReference(
                    dataset_id="ds_native_result_api_01",
                    dataset_type="short_video",
                    file_path="fixture.csv",
                )
            ],
            include_strategy=True,
            operator_visible=True,
            created_at=now,
            updated_at=now,
            observed_execution_state="settled",
            final_response=(
                "内部说明 service_run_id=srv_private_001\n"
                "PROJECT017_NATIVE_RESULT_JSON\n```json\n"
                + json.dumps(final_payload, ensure_ascii=False)
                + "\n```"
            ),
            ledger=NativeLedgerSummary(
                parent_agent_attempts=1,
                specialist_tool_attempts=2,
                total_attempts=3,
                completed_attempts=3,
                failed_or_blocked_attempts=0,
                unfinished_attempts=0,
                service_run_ids=["srv_private_001"],
                analysis_run_ids=["analysis_private_001"],
            ),
            reconciliation=NativeReconciliation(
                audit_available=True,
                final_response_structured=True,
                observed_total_attempts=3,
            ),
        )
        self.runtime.refresh_result = record
        self.runtime.list_results = [record]

        response = await self.request(
            "GET",
            "/v1/native/runs/wf_native_result_api_001/result",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["view_state"], "ready")
        self.assertEqual(response.json()["headline"], operator_result["headline"])
        for forbidden in (
            "final_response",
            "attempts",
            "service_run_id",
            "analysis_private_001",
            "commerce_ops_supervisor",
        ):
            self.assertNotIn(forbidden, response.text)

        catalog = await self.request("GET", "/v1/native/tasks")
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog.json()["returned_count"], 1)
        self.assertFalse(catalog.json()["has_more"])
        task = catalog.json()["tasks"][0]
        self.assertEqual(len(task["task_reference"]), 12)
        self.assertNotIn("wf_native_result_api_001", catalog.text)
        self.assertNotIn("service_run_id", catalog.text)

        invalid_reference = await self.request(
            "GET",
            "/v1/native/tasks/not-a-reference/result",
        )
        self.assertEqual(invalid_reference.status_code, 422)

        reopened = await self.request(
            "GET",
            f"/v1/native/tasks/{task['task_reference']}/result",
        )
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(reopened.json()["headline"], operator_result["headline"])
        self.assertNotIn("wf_native_result_api_001", reopened.text)
        self.assertEqual(self.runtime.refresh_calls, 1)

    async def test_remote_clients_are_rejected(self):
        transport = httpx.ASGITransport(
            app=self.app,
            client=("192.0.2.10", 50000),
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            response = await client.get("/v1/native/configuration")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
