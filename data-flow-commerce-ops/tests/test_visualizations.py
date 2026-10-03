import csv
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import test_operations_api as fixture
from commerce_ops.visualizations import VisualizationService
from commerce_ops.visualization_models import VisualizationFilters


class VisualizationTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.OperationsApiTests.setUp
    host = fixture.OperationsApiTests.host
    request = fixture.OperationsApiTests.request

    def tearDown(self):
        self.assertEqual(self.client.send_calls, 0)
        self.assertEqual(self.client.create_calls, 0)
        self.temporary.cleanup()

    async def snapshot(self, **params):
        response = await self.request("GET", "/visualizations", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response.json()

    async def test_baseline_money_denominators_and_cross_session_deduplication(self):
        data = await self.snapshot()
        metrics = {item["key"]: item["value"] for item in data["metrics"]}
        self.assertEqual(metrics, {"gmv": 10591, "paid_orders": 9, "leads": 18, "paid_conversion": 50, "followup_24h": 72.2222})
        charts = {item["key"]: item for item in data["charts"]}
        self.assertEqual([row["value"] for row in charts["content"]["rows"]], [312600, 13840, 18])
        self.assertEqual([row["attended"] for row in charts["live"]["rows"]], [8, 12])
        self.assertEqual([row["ordered"] for row in charts["live"]["rows"]], [2, 7])
        self.assertEqual(sum(row["gmv"] for row in charts["sales"]["rows"]), 10591)
        self.assertEqual([row["value"] for row in charts["followups"]["rows"]], [11, 2, 4, 1, 0])
        self.assertTrue(data["synthetic"])
        self.assertNotIn(str(fixture.PROJECT_ROOT), str(data))

    async def test_cohort_date_inclusive_and_later_payment_preserved(self):
        data = await self.snapshot(date_from="2026-08-31", date_to="2026-08-31")
        self.assertEqual(data["selected_leads"], 3)
        self.assertEqual(data["metrics"][0]["value"], 899)
        self.assertEqual(data["charts"][0]["rows"], [{"label": "2026-09-01", "gmv": 899}])

    async def test_channel_content_session_intersection_and_joined_orders(self):
        data = await self.snapshot(channel="直播承接")
        self.assertEqual(data["selected_leads"], 6)
        self.assertEqual(data["metrics"][0]["value"], 5795)
        data = await self.snapshot(content="p13_cnt_008", session="1302")
        self.assertEqual(data["selected_leads"], 1)
        self.assertEqual(data["metrics"][0]["value"], 999)
        self.assertEqual(data["charts"][3]["rows"][0]["registered"], 1)
        empty = await self.snapshot(content="p13_cnt_001", session="1302")
        self.assertEqual(empty["selected_leads"], 0)

    async def test_empty_denominator_is_null_and_reset_is_read_only(self):
        data = await self.snapshot(date_from="2030-01-01")
        self.assertEqual([metric["value"] for metric in data["metrics"]], [0, 0, 0, None, None])
        self.assertEqual((await self.snapshot())["selected_leads"], 18)

    async def test_paginated_details_and_filtered_csv_have_same_rows(self):
        first = await self.request("GET", "/visualizations/details/live?limit=20&offset=0")
        second = await self.request("GET", "/visualizations/details/live?limit=20&offset=20")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["total"], 24)
        self.assertEqual(len(first.json()["rows"]), 20)
        self.assertEqual(len(second.json()["rows"]), 4)
        detail = await self.request("GET", "/visualizations/details/orders", params={"channel": "直播承接"})
        export = await self.request("GET", "/visualizations/export/orders.csv", params={"channel": "直播承接"})
        self.assertEqual(export.status_code, 200, export.text)
        self.assertTrue(export.content.startswith(b"\xef\xbb\xbf"))
        self.assertIn("attachment", export.headers["content-disposition"])
        rows = list(csv.DictReader(StringIO(export.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), detail.json()["total"])
        self.assertEqual(sum(float(row["有效付款金额（元）"]) for row in rows), 5795)
        follow = await self.request("GET", "/visualizations/details/followups", params={"content": "p13_cnt_017"})
        self.assertEqual(follow.json()["rows"][0]["bucket"], "无首跟进记录")

    async def test_all_surfaces_require_session_workspace_and_trusted_origin(self):
        for route in ["/visualizations", "/visualizations/details/leads", "/visualizations/export/leads.csv"]:
            self.assertEqual((await self.request("GET", route, headers={})).status_code, 401)
            self.visible = False
            self.assertEqual((await self.request("GET", route)).status_code, 403)
            self.visible = True
            self.assertEqual((await self.request("GET", route, headers={"Origin": "https://outside.test", "Cookie": "test=1"})).status_code, 403)

    async def test_invalid_filters_source_and_pagination_are_rejected(self):
        for query in ["date_from=2026-09-03&date_to=2026-09-01", "date_from=bad", "channel=unknown", "source_id=../../secret", "content=unknown", "unexpected=1"]:
            response = await self.request("GET", f"/visualizations?{query}")
            self.assertEqual(response.status_code, 422, response.text)
        for route in ["/visualizations/details/unknown", "/visualizations/details/leads?offset=-1", "/visualizations/details/leads?limit=101"]:
            self.assertEqual((await self.request("GET", route)).status_code, 422)

    async def test_missing_source_returns_sanitized_error(self):
        with TemporaryDirectory(dir=self.root) as folder:
            self.runtime.data_root = Path(folder)
            response = await self.request("GET", "/visualizations")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(folder, response.text)

    def test_csv_text_cannot_execute_spreadsheet_formula(self):
        service = VisualizationService(fixture.PROJECT_ROOT / "data" / "fixtures")
        original = service.details
        def altered(*args, **kwargs):
            detail = original(*args, **kwargs)
            detail.rows[0]["channel"] = "=1+1"
            return detail
        service.details = altered
        rows = list(csv.DictReader(StringIO(service.export_csv(VisualizationFilters(), "leads").decode("utf-8-sig"))))
        self.assertEqual(rows[0]["线索渠道"], "'=1+1")


if __name__ == "__main__":
    unittest.main()
