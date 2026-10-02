import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import httpx

from commerce_ops.app import create_app
from commerce_ops.demo_orchestrator import DemoOrchestrator
from commerce_ops.service import CommerceOpsService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data" / "fixtures"


class DemoApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_directory = TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        service = CommerceOpsService(DATA_ROOT)
        orchestrator = DemoOrchestrator(
            DATA_ROOT,
            upload_root=Path(self.temp_directory.name),
        )
        self.app = create_app(service, orchestrator)

    async def request(self, method: str, path: str, **kwargs):
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    async def test_catalog_sample_lookup_and_report_download(self):
        catalog = await self.request("GET", "/v1/demo/scenarios")
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(
            catalog.json()["default_scenario_id"],
            "full_commerce_funnel",
        )

        run = await self.request(
            "POST",
            "/v1/demo/runs/sample",
            json={"include_drilldowns": True},
        )
        self.assertEqual(run.status_code, 200)
        body = run.json()
        workflow_run_id = body["workflow_run_id"]
        self.assertFalse(body["provider_called"])
        self.assertFalse(body["agent_runtime_executed"])
        self.assertEqual(len(body["analysis_packets"]), 3)

        lookup = await self.request(
            "GET",
            f"/v1/demo/runs/{workflow_run_id}",
        )
        self.assertEqual(lookup.status_code, 200)
        self.assertEqual(lookup.json()["workflow_run_id"], workflow_run_id)

        report = await self.request(
            "GET",
            f"/v1/demo/runs/{workflow_run_id}/report",
        )
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json()["workflow_run_id"], workflow_run_id)
        self.assertIn("attachment", report.headers["content-disposition"])

    async def test_demo_page_and_assets_are_served_by_the_same_app(self):
        root = await self.request("GET", "/")
        self.assertEqual(root.status_code, 307)
        self.assertEqual(root.headers["location"], "/native")

        page = await self.request("GET", "/demo")
        self.assertEqual(page.status_code, 200)
        self.assertIn("MiniClaw 电商运营数据分析多 Agent 工作台", page.text)
        self.assertNotIn("synthetic=true", page.text)
        self.assertNotIn("Provider 未调用", page.text)
        self.assertNotIn("Agent Runtime 未运行", page.text)
        self.assertNotIn("此处展示业务分工", page.text)
        self.assertNotIn("本地确定性演示", page.text)

        styles = await self.request("GET", "/demo/assets/styles.css")
        script = await self.request("GET", "/demo/assets/app.js")
        self.assertEqual(styles.status_code, 200)
        self.assertEqual(script.status_code, 200)
        self.assertIn("renderResult", script.text)
        self.assertNotIn("provider_key", script.text.lower())

    async def test_upload_endpoint_runs_uploaded_synthetic_data(self):
        sources = [
            ("video.csv", "short_video", DATA_ROOT / "short_video" / "synthetic-short-video.csv"),
            ("live.csv", "live_session", DATA_ROOT / "live" / "synthetic-live-integration.csv"),
            ("leads.csv", "channel_lead", DATA_ROOT / "leads" / "synthetic-channel-leads.csv"),
            ("followup.csv", "sales_followup", DATA_ROOT / "followup" / "synthetic-sales-followup.csv"),
            ("orders.csv", "order", DATA_ROOT / "orders" / "synthetic-orders.csv"),
        ]
        metadata = {
            "datasets": [
                {
                    "dataset_id": f"ds_api_upload_{index}",
                    "dataset_type": dataset_type,
                    "file_index": index,
                    "display_name": file_name,
                }
                for index, (file_name, dataset_type, _) in enumerate(sources)
            ],
            "requested_domains": [
                "content_growth",
                "live_conversion",
                "attribution_leads",
            ],
            "objective": "API 上传合成数据演示。",
            "include_drilldowns": False,
            "synthetic": True,
        }
        files = [
            ("files", (file_name, path.read_bytes(), "text/csv"))
            for file_name, _, path in sources
        ]

        response = await self.request(
            "POST",
            "/v1/demo/runs/upload",
            data={"metadata": json.dumps(metadata, ensure_ascii=False)},
            files=files,
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["scenario"]["scenario_id"], "uploaded_synthetic_data")
        self.assertEqual(len(body["analysis_packets"]), 3)
        self.assertEqual(body["drilldowns"], [])

    async def test_invalid_upload_metadata_and_missing_run_are_safe(self):
        invalid = await self.request(
            "POST",
            "/v1/demo/runs/upload",
            data={"metadata": "{}"},
            files=[("files", ("empty.csv", b"a,b\n1,2\n", "text/csv"))],
        )
        self.assertEqual(invalid.status_code, 422)

        missing = await self.request(
            "GET",
            "/v1/demo/runs/wf_demo_missing",
        )
        self.assertEqual(missing.status_code, 404)
        self.assertNotIn("traceback", missing.text.lower())

    async def test_invalid_uploaded_file_fails_closed(self):
        metadata = {
            "datasets": [
                {
                    "dataset_id": "ds_invalid_video",
                    "dataset_type": "short_video",
                    "file_index": 0,
                    "display_name": "错误文件",
                }
            ],
            "requested_domains": ["content_growth"],
            "objective": "验证错误文件停止。",
            "synthetic": True,
        }

        response = await self.request(
            "POST",
            "/v1/demo/runs/upload",
            data={"metadata": json.dumps(metadata, ensure_ascii=False)},
            files=[("files", ("video.txt", b"not-a-table", "text/plain"))],
        )

        self.assertEqual(response.status_code, 422)
        self.assertNotIn("traceback", response.text.lower())

    async def test_demo_response_does_not_expose_runtime_secrets(self):
        response = await self.request(
            "POST",
            "/v1/demo/runs/sample",
            json={},
        )

        lowered = response.text.lower()
        self.assertNotIn("provider_key", lowered)
        self.assertNotIn("session-secret", lowered)
        self.assertNotIn("authorization", lowered)
        self.assertNotIn("messages.db", lowered)


if __name__ == "__main__":
    unittest.main()
