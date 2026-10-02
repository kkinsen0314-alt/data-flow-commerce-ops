import unittest

import httpx

from commerce_ops.miniclaw_client import (
    MiniClawClient,
    MiniClawClientError,
    MiniClawClientSettings,
)


class MiniClawClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticates_once_and_uses_exact_native_routes(self):
        requests: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append((request.method, request.url.path))
            if request.url.path == "/api/auth/login":
                return httpx.Response(
                    200,
                    json={"success": True},
                    headers={"set-cookie": "miniclaw_session=test; Path=/"},
                )
            self.assertIn("miniclaw_session=test", request.headers.get("cookie", ""))
            if request.url.path == "/api/groups":
                return httpx.Response(200, json={"groups": {}})
            if request.url.path.endswith("/sessions"):
                if request.method == "POST":
                    return httpx.Response(200, json={"session": {"id": "session-1"}})
                return httpx.Response(200, json={"sessions": []})
            if request.url.path == "/api/messages":
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "messageId": "message-1",
                        "disposition": "started",
                        "runId": "run-1",
                    },
                )
            raise AssertionError(f"unexpected route: {request.url}")

        client = MiniClawClient(
            MiniClawClientSettings(
                workspace_jid="web:workspace",
                username="admin",
                password="secret-value",
            ),
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.get_groups()
            await client.get_sessions("web:workspace")
            await client.create_session(
                "web:workspace", name="native", description="test"
            )
            await client.send_message_once("web:workspace", "session-1", "prompt")
        finally:
            await client.aclose()

        self.assertEqual(requests.count(("POST", "/api/auth/login")), 1)
        self.assertEqual(requests.count(("POST", "/api/messages")), 1)
        self.assertIn(("POST", "/api/groups/web:workspace/sessions"), requests)

    async def test_mutating_transport_failure_is_uncertain_and_not_retried(self):
        message_attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal message_attempts
            if request.url.path == "/api/auth/me":
                return httpx.Response(200, json={"user": {"id": "admin"}})
            if request.url.path == "/api/messages":
                message_attempts += 1
                raise httpx.ReadTimeout("unknown delivery", request=request)
            raise AssertionError(f"unexpected route: {request.url}")

        client = MiniClawClient(
            MiniClawClientSettings(
                workspace_jid="web:workspace",
                cookie_header="miniclaw_session=server-only-secret",
            ),
            transport=httpx.MockTransport(handler),
        )
        try:
            with self.assertRaises(MiniClawClientError) as raised:
                await client.send_message_once("web:workspace", "session-1", "prompt")
        finally:
            await client.aclose()

        self.assertTrue(raised.exception.mutation_uncertain)
        self.assertEqual(message_attempts, 1)
        self.assertNotIn("server-only-secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
