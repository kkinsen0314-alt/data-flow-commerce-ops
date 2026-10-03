import asyncio
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

from commerce_ops.app import create_app
from commerce_ops.conversation_store import ConversationStore
from commerce_ops.miniclaw_client import MiniClawClientError
from commerce_ops.native_models import NativeOperatorMetadata
from commerce_ops.native_presenter import operator_task_reference
from commerce_ops.native_runtime import NativeAuditReader, NativeRunStore, NativeRuntime
from test_native_presenter import make_record, valid_operator_result
from test_native_runtime import FakeMiniClawClient, WORKSPACE_JID


class BrowserMiniClawClient(FakeMiniClawClient):
    def __init__(self) -> None:
        super().__init__()
        self.sessions = []
        self.messages_by_session = {}

    async def get_sessions(self, workspace_jid: str):
        self.get_sessions_calls += 1
        return {"sessions": self.sessions}

    async def create_session(self, workspace_jid: str, *, name: str, description: str):
        self.create_calls += 1
        session_id = f"session-{self.create_calls}"
        session = {
            "id": session_id,
            "name": name,
            "status": "idle" if description.startswith("Data Flow") else self.platform_status,
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
        if self.send_error:
            raise self.send_error
        self.last_prompt = content
        message_id = f"browser-user-message-{self.send_calls}"
        timestamp = f"2026-09-26T08:{self.send_calls:02d}:00Z"
        self.messages_by_session.setdefault(session_id, []).append({
            "id": message_id,
            "chat_jid": f"{workspace_jid}#agent:{session_id}",
            "sender": "browser-fixture-operator",
            "sender_name": "联调验收员",
            "content": content,
            "timestamp": timestamp,
            "is_from_me": False,
            "source_kind": None,
        })
        for session in self.sessions:
            if session["id"] == session_id:
                session["status"] = "running"
        return {
            "success": True,
            "messageId": message_id,
            "timestamp": timestamp,
            "disposition": "started",
            "runId": f"browser-run-{self.send_calls}",
        }


async def main():
    temporary_root = PROJECT_ROOT / "runtime" / "tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=temporary_root, prefix="operations-browser-") as folder:
        root = Path(folder)
        model = BrowserMiniClawClient()
        model.project_root = str(PROJECT_ROOT)
        runtime = NativeRuntime(
            project_root=PROJECT_ROOT, data_root=PROJECT_ROOT / "data" / "fixtures",
            workspace_jid=WORKSPACE_JID, client=model,
            store=NativeRunStore(root / "runs"), audit_reader=NativeAuditReader(root / "audit"),
        )
        host = FastAPI()
        sessions = set()
        blocked = False
        lose_next_response = False
        user = {
            "id": "browser-fixture-operator", "username": "qa_operator", "display_name": "联调验收员",
            "role": "admin", "status": "active", "permissions": [], "must_change_password": False,
            "avatar_emoji": None, "avatar_color": None, "avatar_url": None, "ai_name": None,
            "ai_avatar_emoji": None, "ai_avatar_color": None, "ai_avatar_url": None,
            "default_require_mention": False,
        }
        identity = {"user": user, "setupStatus": {"needsSetup": False, "claudeConfigured": True,
                    "feishuConfigured": False, "providerSetupSkipped": True},
                    "appearance": {"appName": "Data Flow", "aiName": "Data Flow", "aiAvatarMode": "brand"}}

        @host.get("/__fixture/status")
        def fixture_status():
            return {"fixture": "project017-operations-browser-only", "real_model_calls": 0,
                    "simulated_submissions": model.send_calls}

        @host.post("/__fixture/complete")
        def complete():
            records = runtime.list_operator_runs(limit=None)
            for record in records:
                content = valid_operator_result()
                content["notices"] = ["浏览器联调专用测试响应，不是实际经营结论。"]
                content["findings"][0]["domain"] = record.requested_domains[0]
                if not record.include_strategy:
                    content["actions"] = []
                response = make_record(operator_result=content).final_response
                runtime.store.save(record.model_copy(update={
                    "phase": "settled", "terminal_status": "completed", "platform_status": "completed",
                    "observed_execution_state": "settled", "final_response": response,
                }))
            return {"completed": len(records)}

        @host.post("/__fixture/seed-task")
        def seed_task():
            content = valid_operator_result()
            content["notices"] = ["浏览器联调专用测试响应，不是实际经营结论。"]
            record = make_record(operator_result=content).model_copy(update={
                "workspace_jid": WORKSPACE_JID,
                "operator_visible": True,
                "operator_metadata": NativeOperatorMetadata(
                    title="第 13 期内容承接复盘",
                    objective="核对内容点击到商品访问的承接表现。",
                    source_id="sample-commerce-data",
                    created_by=user["id"],
                ),
            })
            runtime.store.save(record)
            return {"task_reference": operator_task_reference(record.workflow_run_id)}

        @host.post("/__fixture/block")
        def block():
            nonlocal blocked
            blocked = True
            return {"blocked": True}

        @host.post("/__fixture/unblock")
        def unblock():
            nonlocal blocked
            blocked = False
            return {"blocked": False}

        @host.post("/__fixture/expire")
        def expire():
            sessions.clear()
            return {"expired": True}

        @host.post("/__fixture/lose-response")
        def lose_response():
            nonlocal lose_next_response
            lose_next_response = True
            return {"armed": True}

        @host.post("/__fixture/uncertain")
        def uncertain():
            model.send_error = MiniClawClientError("TEST_TIMEOUT", "Fixture timeout", mutation_uncertain=True)
            return {"armed": True}

        @host.post("/__fixture/reset-send")
        def reset_send():
            model.send_error = None
            return {"armed": False}

        @host.post("/__fixture/complete-conversation")
        def complete_conversation():
            if not model.sessions:
                raise HTTPException(404, "No fixture conversation")
            session = model.sessions[-1]
            session["status"] = "idle"
            messages = model.messages_by_session.setdefault(session["id"], [])
            messages.append({
                "id": f"browser-assistant-{len(messages) + 1}",
                "chat_jid": f"{WORKSPACE_JID}#agent:{session['id']}",
                "sender": "miniclaw-agent",
                "sender_name": "Data Flow",
                "content": "第 13 期应优先提升线索承接与支付转化，并按渠道持续跟踪完成率。",
                "timestamp": f"2026-09-26T08:{model.send_calls:02d}:30Z",
                "is_from_me": True,
                "source_kind": "sdk_final",
            })
            return {"completed": True, "session": session["id"]}

        @host.get("/api/auth/status")
        def auth_status():
            return {"initialized": True}

        @host.post("/api/auth/login")
        async def login(request: Request):
            body = await request.json()
            if body != {"username": "qa_operator", "password": "browser-check-only"}:
                raise HTTPException(401, "Invalid fixture credentials")
            sessions.add("browser-fixture-session")
            response = JSONResponse({"success": True, **identity})
            response.set_cookie("miniclaw_session", "browser-fixture-session", httponly=True, samesite="lax")
            return response

        @host.post("/api/auth/logout")
        def logout():
            sessions.clear()
            response = JSONResponse({"success": True})
            response.delete_cookie("miniclaw_session")
            return response

        @host.get("/api/auth/me")
        def me(request: Request):
            if request.cookies.get("miniclaw_session") not in sessions:
                raise HTTPException(401)
            return identity

        @host.get("/api/groups")
        def groups(request: Request):
            me(request)
            return {"groups": {} if blocked else {WORKSPACE_JID: {"name": "联调隔离工作区", "folder": "fixture"}}}

        @host.get("/api/billing/status")
        def billing():
            return {"enabled": False}

        @host.get("/api/{path:path}")
        def native_reads():
            return {}

        @host.get("/{path:path}")
        def static(path: str):
            dist = (PROJECT_ROOT / "runtime" / "web" / "dist").resolve()
            file = (dist / path).resolve()
            if not file.is_relative_to(dist):
                raise HTTPException(404)
            return FileResponse(file if file.is_file() else dist / "index.html")

        app = create_app(
            native_runtime=runtime,
            conversation_store=ConversationStore(root / "conversations"),
        )

        @app.middleware("http")
        async def simulate_lost_response(request: Request, call_next):
            nonlocal lose_next_response
            response = await call_next(request)
            if lose_next_response and request.method == "POST" and (
                request.url.path == "/v1/operations/tasks"
                or request.url.path.endswith("/messages")
            ):
                lose_next_response = False
                return JSONResponse({"detail": "联调模拟：任务已受理，但确认响应中断。"}, status_code=503,
                                    headers={"Access-Control-Allow-Origin": "http://127.0.0.1:3017",
                                             "Access-Control-Allow-Credentials": "true"})
            return response
        servers = [uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=port, log_level="error"))
                   for application, port in [(host, 3017), (app, 3022)]]
        await asyncio.gather(*(server.serve() for server in servers))


if __name__ == "__main__":
    asyncio.run(main())
