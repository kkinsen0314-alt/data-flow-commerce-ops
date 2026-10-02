from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import httpx

from commerce_ops.app import create_app
from commerce_ops.conversation_store import ConversationStore
from commerce_ops.miniclaw_client import MiniClawClientError
from commerce_ops.native_models import NativeOperatorMetadata
from commerce_ops.native_presenter import operator_task_reference
from commerce_ops.native_runtime import NativeAuditReader, NativeRunStore, NativeRuntime
from commerce_ops.operations_auth import OperationsAuth
from test_native_presenter import make_record, valid_operator_result
from test_native_runtime import FakeMiniClawClient, WORKSPACE_JID


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://127.0.0.1:3017"


class ConversationMiniClawClient(FakeMiniClawClient):
    def __init__(self) -> None:
        super().__init__()
        self.sessions: list[dict] = []
        self.messages_by_session: dict[str, list[dict]] = {}
        self.create_error: MiniClawClientError | None = None
        self.next_session = 1

    async def get_sessions(self, workspace_jid: str):
        self.get_sessions_calls += 1
        return {"sessions": self.sessions}

    async def create_session(self, workspace_jid: str, *, name: str, description: str):
        self.create_calls += 1
        if self.create_error:
            raise self.create_error
        session_id = f"session-{self.next_session}"
        self.next_session += 1
        session = {
            "id": session_id,
            "name": name,
            "status": "idle",
            "created_at": "2026-09-26T08:00:00Z",
        }
        self.sessions.append(session)
        self.messages_by_session[session_id] = []
        return {"session": session}

    async def get_messages(self, workspace_jid: str, session_id: str, *, limit=200):
        self.get_messages_calls += 1
        return {"messages": list(self.messages_by_session.get(session_id, []))}

    async def send_message_once(self, workspace_jid: str, session_id: str, content: str):
        self.send_calls += 1
        self.last_prompt = content
        if self.send_error:
            raise self.send_error
        timestamp = "2026-09-26T08:01:00Z"
        message_id = f"user-message-{self.send_calls}"
        self.messages_by_session[session_id].append({
            "id": message_id,
            "chat_jid": f"{workspace_jid}#agent:{session_id}",
            "sender": "owner-cookie",
            "sender_name": "Owner",
            "content": content,
            "timestamp": timestamp,
            "is_from_me": False,
            "source_kind": None,
        })
        return {
            "success": True,
            "messageId": message_id,
            "timestamp": timestamp,
            "disposition": "started",
            "runId": f"run-{self.send_calls}",
        }


class ConversationApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary_root = PROJECT_ROOT / "runtime" / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temporary = TemporaryDirectory(dir=temporary_root)
        self.root = Path(self.temporary.name)
        self.client = ConversationMiniClawClient()
        self.client.project_root = str(PROJECT_ROOT)
        self.runtime = NativeRuntime(
            project_root=PROJECT_ROOT,
            data_root=PROJECT_ROOT / "data" / "fixtures",
            workspace_jid=WORKSPACE_JID,
            client=self.client,
            store=NativeRunStore(self.root / "runs"),
            audit_reader=NativeAuditReader(self.root / "audit"),
        )
        self.auth = OperationsAuth(ORIGIN, transport=httpx.MockTransport(self.host))
        self.app = create_app(
            native_runtime=self.runtime,
            operations_auth=self.auth,
            conversation_store=ConversationStore(self.root / "conversations"),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def host(self, request: httpx.Request):
        if request.url.path == "/api/auth/me":
            cookie = request.headers.get("cookie", "")
            return httpx.Response(200, json={"user": {
                "id": "other-user" if "other" in cookie else "owner-cookie",
                "must_change_password": False,
            }})
        if request.url.path == "/api/groups":
            return httpx.Response(200, json={"groups": {WORKSPACE_JID: {}}})
        raise AssertionError("Unexpected auth route")

    async def request(self, method: str, path: str, *, cookie="owner", **kwargs):
        transport = httpx.ASGITransport(app=self.app, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.request(
                method,
                "/v1/operations" + path,
                headers={"Origin": ORIGIN, "Cookie": cookie},
                **kwargs,
            )

    async def create_conversation(self, key="create-conversation-001"):
        return await self.request("POST", "/conversations", json={
            "title": "经营复盘",
            "client_request_id": key,
        })

    async def test_create_list_and_browser_projection_are_persistent(self):
        first = await self.create_conversation()
        second = await self.create_conversation()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(self.client.create_calls, 1)
        self.assertEqual(first.json()["status"], "ready")
        self.assertTrue(first.json()["can_send"])
        reference = first.json()["conversation_reference"]
        catalog = await self.request("GET", "/conversations")
        self.assertEqual(catalog.json()["conversations"][0]["conversation_reference"], reference)
        for internal in ["session_id", "workspace_jid", "user_id", "creation_key", "run_id"]:
            self.assertNotIn(internal, catalog.text)

    async def test_creation_key_conflict_and_user_scope(self):
        created = await self.create_conversation()
        conflict = await self.request("POST", "/conversations", json={
            "title": "另一个名称", "client_request_id": "create-conversation-001",
        })
        self.assertEqual(conflict.status_code, 409)
        reference = created.json()["conversation_reference"]
        hidden = await self.request("GET", f"/conversations/{reference}", cookie="other")
        self.assertEqual(hidden.status_code, 404)
        other_catalog = await self.request("GET", "/conversations", cookie="other")
        self.assertEqual(other_catalog.json(), {"conversations": []})

    async def test_send_requires_cost_consent_and_calls_model_once(self):
        created = await self.create_conversation()
        reference = created.json()["conversation_reference"]
        base = {
            "content": "请总结本期转化问题。",
            "idempotency_key": "message-submit-001",
        }
        for extra in [
            {},
            {"fee_confirmation": "declined", "authorized_model_execution": True},
            {"fee_confirmation": "confirmed", "authorized_model_execution": False},
        ]:
            response = await self.request(
                "POST", f"/conversations/{reference}/messages", json={**base, **extra}
            )
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.send_calls, 0)

        payload = {
            **base,
            "fee_confirmation": "confirmed",
            "authorized_model_execution": True,
        }
        first = await self.request(
            "POST", f"/conversations/{reference}/messages", json=payload
        )
        second = await self.request(
            "POST", f"/conversations/{reference}/messages", json=payload
        )
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(self.client.send_calls, 1)
        self.assertEqual(first.json()["status"], "processing")
        self.assertFalse(first.json()["can_send"])
        self.assertEqual(first.json()["messages"][0]["role"], "user")

    async def test_completed_reply_is_sanitized_and_allows_next_turn(self):
        created = await self.create_conversation()
        reference = created.json()["conversation_reference"]
        await self.request("POST", f"/conversations/{reference}/messages", json={
            "content": "请总结本期转化问题。",
            "idempotency_key": "message-submit-001",
            "fee_confirmation": "confirmed",
            "authorized_model_execution": True,
        })
        self.client.messages_by_session["session-1"].extend([
            {
                "id": "internal-tool",
                "sender": "__system__",
                "sender_name": "system",
                "content": "secret tool trace",
                "timestamp": "2026-09-26T08:01:30Z",
                "is_from_me": True,
                "source_kind": None,
            },
            {
                "id": "assistant-1",
                "sender": "miniclaw-agent",
                "sender_name": "Data Flow",
                "content": "本期需要优先改善线索到支付的承接效率。",
                "timestamp": "2026-09-26T08:02:00Z",
                "is_from_me": True,
                "source_kind": "sdk_final",
                "session_id": "private-provider-session",
                "token_usage": "private-token-usage",
            },
        ])
        thread = await self.request("GET", f"/conversations/{reference}")
        self.assertEqual(thread.status_code, 200)
        self.assertEqual(thread.json()["status"], "ready")
        self.assertTrue(thread.json()["can_send"])
        self.assertEqual([item["role"] for item in thread.json()["messages"]], ["user", "assistant"])
        self.assertNotIn("secret tool trace", thread.text)
        self.assertNotIn("private-provider-session", thread.text)
        self.assertNotIn("private-token-usage", thread.text)

    async def test_pending_turn_blocks_a_second_model_call(self):
        created = await self.create_conversation()
        reference = created.json()["conversation_reference"]
        first_payload = {
            "content": "第一条消息。",
            "idempotency_key": "message-submit-001",
            "fee_confirmation": "confirmed",
            "authorized_model_execution": True,
        }
        await self.request("POST", f"/conversations/{reference}/messages", json=first_payload)
        blocked = await self.request("POST", f"/conversations/{reference}/messages", json={
            **first_payload,
            "content": "第二条消息。",
            "idempotency_key": "message-submit-002",
        })
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(self.client.send_calls, 1)

    async def test_failed_platform_turn_becomes_unavailable_instead_of_polling_forever(self):
        created = await self.create_conversation()
        reference = created.json()["conversation_reference"]
        await self.request("POST", f"/conversations/{reference}/messages", json={
            "content": "检查本次分析。",
            "idempotency_key": "message-platform-failed",
            "fee_confirmation": "confirmed",
            "authorized_model_execution": True,
        })
        self.client.sessions[0]["status"] = "failed"
        thread = await self.request("GET", f"/conversations/{reference}")
        self.assertEqual(thread.status_code, 200)
        self.assertEqual(thread.json()["status"], "unavailable")
        self.assertFalse(thread.json()["can_send"])
        self.assertEqual(self.client.send_calls, 1)

    async def test_uncertain_send_is_never_retried_and_can_be_reconciled(self):
        created = await self.create_conversation()
        reference = created.json()["conversation_reference"]
        self.client.send_error = MiniClawClientError(
            "TIMEOUT", "private", mutation_uncertain=True
        )
        payload = {
            "content": "核对渠道线索。",
            "idempotency_key": "message-submit-uncertain",
            "fee_confirmation": "confirmed",
            "authorized_model_execution": True,
        }
        first = await self.request(
            "POST", f"/conversations/{reference}/messages", json=payload
        )
        second = await self.request(
            "POST", f"/conversations/{reference}/messages", json=payload
        )
        self.assertEqual(first.json()["status"], "uncertain")
        self.assertTrue(first.json()["query_original_submission_only"])
        self.assertEqual(second.status_code, 202)
        self.assertEqual(self.client.send_calls, 1)

        self.client.send_error = None
        self.client.messages_by_session["session-1"].extend([
            {
                "id": "accepted-after-timeout",
                "sender": "owner-cookie",
                "sender_name": "Owner",
                "content": "核对渠道线索。",
                "timestamp": "2099-09-26T08:01:00Z",
                "is_from_me": False,
                "source_kind": None,
            },
            {
                "id": "reply-after-timeout",
                "sender": "miniclaw-agent",
                "sender_name": "Data Flow",
                "content": "渠道线索已核对。",
                "timestamp": "2099-09-26T08:02:00Z",
                "is_from_me": True,
                "source_kind": "sdk_final",
            },
        ])
        recovered = await self.request(
            "GET", "/conversation-submissions/message-submit-uncertain"
        )
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json()["status"], "ready")
        self.assertEqual(self.client.send_calls, 1)

    async def test_uncertain_session_creation_is_visible_but_not_sendable(self):
        self.client.create_error = MiniClawClientError(
            "TIMEOUT", "private", mutation_uncertain=True
        )
        response = await self.create_conversation("create-uncertain-001")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "uncertain")
        self.assertFalse(response.json()["can_send"])
        self.assertEqual(self.client.create_calls, 1)

    async def test_analysis_task_context_is_resolved_server_side_and_safely_projected(self):
        record = make_record(operator_result=valid_operator_result()).model_copy(update={
            "workspace_jid": WORKSPACE_JID,
            "operator_visible": True,
            "operator_metadata": NativeOperatorMetadata(
                title="内容经营检查",
                objective="检查内容到成交的承接表现。",
                source_id="sample-commerce-data",
                created_by="owner-cookie",
            ),
        })
        self.runtime.store.save(record)
        task_reference = operator_task_reference(record.workflow_run_id)
        created = await self.create_conversation()
        reference = created.json()["conversation_reference"]
        response = await self.request(
            "POST",
            f"/conversations/{reference}/messages",
            json={
                "content": "基于这个结果，下一步优先做什么？",
                "idempotency_key": "message-with-task-context",
                "fee_confirmation": "confirmed",
                "authorized_model_execution": True,
                "context": {
                    "kind": "analysis_task",
                    "task_reference": task_reference,
                },
            },
        )
        self.assertEqual(response.status_code, 202)
        message = response.json()["messages"][0]
        self.assertEqual(message["content"], "基于这个结果，下一步优先做什么？")
        self.assertEqual(message["context"]["kind"], "analysis_task")
        self.assertEqual(message["context"]["reference"], task_reference)
        self.assertIn("内容点击后的承接仍有提升空间", self.client.last_prompt)
        self.assertIn("[用户问题]", self.client.last_prompt)
        self.assertNotIn("fixture.csv", self.client.last_prompt)
        self.assertNotIn("wf_native_result_001", response.text)
        self.assertNotIn("session-1", response.text)

    async def test_visualization_context_uses_validated_snapshot_not_client_text(self):
        created = await self.create_conversation()
        reference = created.json()["conversation_reference"]
        response = await self.request(
            "POST",
            f"/conversations/{reference}/messages",
            json={
                "content": "解释当前看板里最需要关注的指标。",
                "idempotency_key": "message-with-visual-context",
                "fee_confirmation": "confirmed",
                "authorized_model_execution": True,
                "context": {
                    "kind": "visualization_view",
                    "visualization_filters": {"source_id": "sample-commerce-data"},
                },
            },
        )
        self.assertEqual(response.status_code, 202)
        context = response.json()["messages"][0]["context"]
        self.assertEqual(context["title"], "当前数据看板")
        self.assertEqual(context["return_path"], "/operations/visualizations?source_id=sample-commerce-data")
        self.assertIn('"selected_leads":18', self.client.last_prompt)
        self.assertIn('"metrics"', self.client.last_prompt)
        self.assertNotIn(str(PROJECT_ROOT), self.client.last_prompt)
        self.assertNotIn("Data Flow 已核验关联上下文", response.text)

    async def test_unknown_task_context_never_calls_model(self):
        created = await self.create_conversation()
        reference = created.json()["conversation_reference"]
        response = await self.request(
            "POST",
            f"/conversations/{reference}/messages",
            json={
                "content": "继续分析。",
                "idempotency_key": "message-unknown-task-context",
                "fee_confirmation": "confirmed",
                "authorized_model_execution": True,
                "context": {
                    "kind": "analysis_task",
                    "task_reference": "ABCDEF123456",
                },
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.send_calls, 0)


if __name__ == "__main__":
    unittest.main()
