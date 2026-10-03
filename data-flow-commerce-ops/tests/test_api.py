from pathlib import Path
import unittest

import httpx

from commerce_ops.app import create_app
from commerce_ops.service import CommerceOpsService
from test_service import all_references


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data" / "fixtures"


class CommerceOpsApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = create_app(CommerceOpsService(DATA_ROOT))

    async def request(self, method: str, path: str, **kwargs):
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    async def inspect_all(self, workflow_run_id: str):
        return await self.request(
            "POST",
            "/v1/inspect",
            json={
                "workflow_run_id": workflow_run_id,
                "caller_role": "content_growth_analyst",
                "data_refs": [
                    item.model_dump(mode="json") for item in all_references()
                ],
                "requested_domains": [
                    "content_growth",
                    "live_conversion",
                    "attribution_leads",
                ],
            },
        )

    async def test_health_and_catalog_keep_runtime_boundary_explicit(self):
        health = await self.request("GET", "/health")
        catalog = await self.request("GET", "/v1/tools")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["mode"], "deterministic_synthetic")
        self.assertFalse(health.json()["provider_configured"])
        self.assertFalse(health.json()["agent_runtime_executed"])
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(len(catalog.json()["tools"]), 5)
        self.assertTrue(
            all(item["read_only"] for item in catalog.json()["tools"])
        )

    async def test_api_and_legacy_page_present_data_flow_brand(self):
        schema = await self.request("GET", "/openapi.json")
        page = await self.request("GET", "/demo")
        favicon = await self.request("GET", "/demo/assets/favicon.svg")

        self.assertEqual(schema.status_code, 200)
        self.assertEqual(schema.json()["info"]["title"], "Data Flow 电商运营确定性工具层")
        self.assertEqual(page.status_code, 200)
        self.assertIn("<title>Data Flow 电商运营数据分析多 Agent 工作台｜功能演示</title>", page.text)
        self.assertIn('class="brand-mark" aria-hidden="true">DF</span>', page.text)
        self.assertIn("DATA FLOW COMMERCE OPS · FUNCTIONAL DEMO", page.text)
        self.assertEqual(favicon.status_code, 200)
        self.assertIn(">DF</text>", favicon.text)

    async def test_http_inspect_analyze_and_drilldown_chain(self):
        workflow_run_id = "wf_api_chain"
        inspection = await self.inspect_all(workflow_run_id)
        self.assertEqual(inspection.status_code, 200)
        self.assertEqual(inspection.json()["terminal_status"], "completed")

        analysis = await self.request(
            "POST",
            "/v1/analyze/short-video",
            json={
                "workflow_run_id": workflow_run_id,
                "dataset_ids": ["ds_video", "ds_lead"],
                "requested_dimensions": ["account", "content"],
                "top_n": 5,
                "synthetic": True,
            },
        )
        self.assertEqual(analysis.status_code, 200)
        body = analysis.json()
        self.assertEqual(body["terminal_status"], "completed")
        packet = body["analysis_packet"]

        drilldown = await self.request(
            "POST",
            "/v1/drilldown",
            json={
                "workflow_run_id": workflow_run_id,
                "caller_role": "content_growth_analyst",
                "base_analysis_run_id": packet["analysis_run_id"],
                "evidence_id": packet["evidence"][0]["evidence_id"],
                "dimension": "content",
                "top_n": 3,
                "synthetic": True,
            },
        )
        self.assertEqual(drilldown.status_code, 200)
        self.assertEqual(drilldown.json()["terminal_status"], "completed")
        self.assertEqual(len(drilldown.json()["rows"]), 3)

    async def test_http_roi_request_is_structurally_blocked(self):
        workflow_run_id = "wf_api_roi"
        await self.inspect_all(workflow_run_id)
        response = await self.request(
            "POST",
            "/v1/analyze/attribution-leads",
            json={
                "workflow_run_id": workflow_run_id,
                "dataset_ids": ["ds_lead", "ds_followup", "ds_order"],
                "calculate_roi": True,
                "link_orders": True,
                "synthetic": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["terminal_status"], "blocked")
        self.assertEqual(
            response.json()["workflow_error"]["code"],
            "COST_FIELD_MISSING",
        )

    async def test_http_caller_role_is_fail_closed_by_request_model(self):
        response = await self.request(
            "POST",
            "/v1/analyze/short-video",
            json={
                "workflow_run_id": "wf_api_role",
                "caller_role": "commerce_ops_supervisor",
                "dataset_ids": ["ds_video"],
                "synthetic": True,
            },
        )

        self.assertEqual(response.status_code, 422)

    async def test_http_response_does_not_expose_local_secrets(self):
        response = await self.inspect_all("wf_api_secret_scan")

        self.assertNotIn("authorization", response.text.lower())
        self.assertNotIn("provider_key", response.text.lower())
        self.assertNotIn("session-secret", response.text.lower())


if __name__ == "__main__":
    unittest.main()
