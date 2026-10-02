from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import httpx

from commerce_ops.app import create_app
from commerce_ops.miniclaw_client import MiniClawClientError
from commerce_ops.native_presenter import operator_task_reference
from commerce_ops.native_runtime import NativeAuditReader, NativeRunStore, NativeRuntime
from commerce_ops.operations_auth import OperationsAuth
from test_native_presenter import make_record, valid_operator_result
from test_native_runtime import FakeMiniClawClient, WORKSPACE_JID


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://127.0.0.1:3017"


class OperationsApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary_root = PROJECT_ROOT / "runtime" / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temporary = TemporaryDirectory(dir=temporary_root)
        self.root = Path(self.temporary.name)
        self.client = FakeMiniClawClient()
        self.client.project_root = str(PROJECT_ROOT)
        self.runtime = NativeRuntime(
            project_root=PROJECT_ROOT, data_root=PROJECT_ROOT / "data" / "fixtures",
            workspace_jid=WORKSPACE_JID, client=self.client,
            store=NativeRunStore(self.root / "runs"),
            audit_reader=NativeAuditReader(self.root / "audit"),
        )
        self.auth_requests = []
        self.auth_status = 200
        self.visible = True
        self.force_password = False
        self.auth = OperationsAuth(ORIGIN, transport=httpx.MockTransport(self.host))
        self.app = create_app(native_runtime=self.runtime, operations_auth=self.auth)

    def tearDown(self):
        self.temporary.cleanup()

    def host(self, request: httpx.Request):
        self.auth_requests.append(request)
        if self.auth_status != 200:
            return httpx.Response(self.auth_status, json={"error": "private upstream detail"})
        if request.url.path == "/api/auth/me":
            return httpx.Response(200, json={"user": {
                "id": request.headers["cookie"], "must_change_password": self.force_password,
            }})
        if request.url.path == "/api/groups":
            return httpx.Response(200, json={"groups": {WORKSPACE_JID: {}} if self.visible else {}})
        raise AssertionError("Unexpected upstream route")

    async def request(self, method, path, *, headers=None, remote=False, **kwargs):
        transport = httpx.ASGITransport(
            app=self.app, client=("203.0.113.2" if remote else "127.0.0.1", 12345),
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(
                method, "/v1/operations" + path,
                headers=headers if headers is not None else {"Origin": ORIGIN, "Cookie": "test-session=owner"},
                **kwargs,
            )

    def payload(self, **updates):
        payload = {
            "idempotency_key": "browser-submit-001", "title": "内容经营检查",
            "source_id": "sample-commerce-data", "objective": "检查内容表现。",
            "requested_domains": ["content_growth"], "include_strategy": False,
            "fee_confirmation": "confirmed", "authorized_model_execution": True,
        }
        payload.update(updates)
        return payload

    async def test_missing_cookie_denied_before_host_or_model(self):
        response = await self.request("GET", "/tasks", headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.auth_requests, [])
        self.assertEqual(self.client.send_calls, 0)

    async def test_expired_disabled_and_host_failure(self):
        for upstream, expected in [(401, 401), (403, 403), (500, 503), (302, 503)]:
            with self.subTest(upstream=upstream):
                self.auth_status = upstream
                response = await self.request("GET", "/tasks")
                self.assertEqual(response.status_code, expected)
                self.assertNotIn("private upstream detail", response.text)

    async def test_workspace_access_is_required_even_with_valid_session(self):
        self.visible = False
        response = await self.request("POST", "/tasks", json=self.payload())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.send_calls, 0)

    async def test_forced_password_change_denied(self):
        self.force_password = True
        response = await self.request("GET", "/tasks")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(self.auth_requests), 1)

    async def test_untrusted_origin_and_missing_write_origin_denied(self):
        for origin in ["https://evil.example", "null", None]:
            headers = {"Cookie": "test-session=owner"}
            if origin is not None:
                headers["Origin"] = origin
            response = await self.request("POST", "/tasks", headers=headers, json=self.payload())
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.send_calls, 0)

    async def test_remote_client_denied(self):
        response = await self.request("GET", "/tasks", remote=True)
        self.assertEqual(response.status_code, 403)

    async def test_cors_preflight_does_not_call_auth_or_model(self):
        response = await self.request("OPTIONS", "/tasks", headers={
            "Origin": ORIGIN, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], ORIGIN)
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")
        self.assertEqual(self.auth_requests, [])

    async def test_browser_cannot_use_unprotected_native_or_tool_routes(self):
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for path in ["/v1/native/runs", "/v1/native/configuration", "/v1/tools"]:
                response = await client.get(path, headers={"Origin": ORIGIN})
                self.assertEqual(response.status_code, 403)

    async def test_sources_are_backend_catalog_with_real_fixture_counts(self):
        response = await self.request("GET", "/data-sources")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["catalog"]["sources"][0]["record_count"], 89)
        self.assertEqual([item["records"] for item in data["datasets"]["sample-commerce-data"]], [18, 24, 18, 17, 12])
        self.assertEqual(len(data["catalog"]["source_types"]), 7)
        self.assertNotIn("file_path", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_safe_configuration_and_empty_history_without_seed_tasks(self):
        config = await self.request("GET", "/configuration")
        self.assertEqual(config.json(), {
            "ready": True, "model_submission_requires_explicit_authorization": True,
            "automatic_model_retry": False,
        })
        response = await self.request("GET", "/tasks")
        self.assertEqual(response.json(), {"tasks": [], "has_more": False})

    async def test_explicit_cost_confirmation_and_known_source_required(self):
        for change in [{"fee_confirmation": "declined"}, {"authorized_model_execution": False},
                       {"title": "   "}, {"objective": "   "}, {"source_id": "unknown-data"},
                       {"requested_domains": ["content_growth", "content_growth"]}]:
            response = await self.request("POST", "/tasks", json=self.payload(**change))
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.send_calls, 0)

    async def test_create_is_persistent_safe_and_idempotent(self):
        first = await self.request("POST", "/tasks", json=self.payload())
        second = await self.request("POST", "/tasks", json=self.payload())
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()["title"], "内容经营检查")
        self.assertEqual(first.json()["view_state"], "processing")
        self.assertEqual(self.client.send_calls, 1)
        record = NativeRunStore(self.root / "runs").list_recent()[0]
        self.assertEqual(record.operator_metadata.objective, "检查内容表现。")
        for internal in ["workflow_run_id", "session_id", "final_response", "file_path", "created_by", "idempotency_key"]:
            self.assertNotIn(internal, first.text)
        recovered = await self.request("GET", "/submissions/browser-submit-001")
        self.assertEqual(recovered.json()["task_reference"], first.json()["task_reference"])

    async def test_idempotency_conflict_does_not_call_model_again(self):
        await self.request("POST", "/tasks", json=self.payload())
        response = await self.request("POST", "/tasks", json=self.payload(title="不同的任务名称"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.send_calls, 1)

    async def test_recovery_is_user_scoped(self):
        await self.request("POST", "/tasks", json=self.payload())
        response = await self.request("GET", "/submissions/browser-submit-001", headers={"Origin": ORIGIN, "Cookie": "test-session=another"})
        self.assertEqual(response.status_code, 404)

    async def test_uncertain_submission_never_resubmits(self):
        self.client.send_error = MiniClawClientError("TIMEOUT", "test", mutation_uncertain=True)
        first = await self.request("POST", "/tasks", json=self.payload())
        second = await self.request("POST", "/tasks", json=self.payload())
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.json()["terminal_status"], "uncertain")
        self.assertEqual(second.json()["result"]["findings"], [])
        self.assertEqual(self.client.send_calls, 1)
        replacement = await self.request("POST", "/tasks", json=self.payload(idempotency_key="browser-replacement-002"))
        self.assertEqual(replacement.status_code, 409)
        self.assertEqual(self.client.send_calls, 1)
        self.assertIn("不要创建替代任务", second.json()["result"]["summary"])

    async def test_tasks_filter_internal_and_other_workspaces_and_paginate(self):
        base = make_record(operator_result=valid_operator_result())
        for index in range(3):
            self.runtime.store.save(base.model_copy(update={
                "workflow_run_id": f"wf_visible_{index}", "operator_visible": True,
                "workspace_jid": WORKSPACE_JID,
            }))
        self.runtime.store.save(base.model_copy(update={"workflow_run_id": "wf_hidden", "workspace_jid": WORKSPACE_JID}))
        self.runtime.store.save(base.model_copy(update={"workflow_run_id": "wf_other", "operator_visible": True}))
        response = await self.request("GET", "/tasks?limit=2")
        self.assertEqual(len(response.json()["tasks"]), 2)
        self.assertTrue(response.json()["has_more"])
        last = await self.request("GET", "/tasks?limit=2&offset=2")
        self.assertEqual(len(last.json()["tasks"]), 1)
        self.assertFalse(last.json()["has_more"])
        for identifier in ["wf_other", "wf_hidden"]:
            hidden = await self.request("GET", f"/tasks/{operator_task_reference(identifier)}")
            self.assertEqual(hidden.status_code, 404)

    async def test_detail_returns_valid_result_without_mutating_settled_task(self):
        record = make_record(operator_result=valid_operator_result()).model_copy(update={
            "workspace_jid": WORKSPACE_JID, "operator_visible": True,
        })
        self.runtime.store.save(record)
        response = await self.request("GET", f"/tasks/{operator_task_reference(record.workflow_run_id)}")
        self.assertEqual(response.json()["result"]["view_state"], "ready")
        self.assertEqual(len(response.json()["result"]["findings"]), 1)
        self.assertEqual(self.client.get_messages_calls, 0)
        self.assertEqual(self.client.send_calls, 0)

    async def test_session_is_revalidated_each_request(self):
        first = await self.request("GET", "/tasks")
        self.assertEqual(first.status_code, 200)
        self.auth_status = 401
        second = await self.request("GET", "/tasks")
        self.assertEqual(second.status_code, 401)


if __name__ == "__main__":
    unittest.main()
