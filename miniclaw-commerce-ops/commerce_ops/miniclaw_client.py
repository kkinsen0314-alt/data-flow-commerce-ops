"""Small, typed HTTP client for the MiniClaw host API used by project017."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx


class MiniClawClientError(RuntimeError):
    """A sanitized MiniClaw transport or contract failure."""

    def __init__(self, code: str, message: str, *, mutation_uncertain: bool = False):
        super().__init__(message)
        self.code = code
        self.mutation_uncertain = mutation_uncertain


@dataclass(frozen=True)
class MiniClawClientSettings:
    base_url: str = "http://127.0.0.1:3017"
    workspace_jid: str | None = None
    username: str | None = None
    password: str | None = None
    cookie_header: str | None = None
    timeout_seconds: float = 30.0

    @classmethod
    def from_environment(cls) -> "MiniClawClientSettings":
        username = os.getenv("MINICLAW_USERNAME")
        password = os.getenv("MINICLAW_PASSWORD")
        cookie_header = os.getenv("MINICLAW_COOKIE")
        return cls(
            base_url=os.getenv("MINICLAW_BASE_URL", "http://127.0.0.1:3017"),
            workspace_jid=os.getenv("MINICLAW_WORKSPACE_JID") or None,
            username=username or None,
            password=password or None,
            cookie_header=cookie_header or None,
            timeout_seconds=float(os.getenv("MINICLAW_TIMEOUT_SECONDS", "30")),
        )

    @property
    def credentials_configured(self) -> bool:
        return bool(self.cookie_header or (self.username and self.password))


class MiniClawClient:
    """One authenticated MiniClaw client with no automatic HTTP retries."""

    def __init__(
        self,
        settings: MiniClawClientSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        headers = {"Accept": "application/json"}
        if settings.cookie_header:
            headers["Cookie"] = settings.cookie_header
        self._headers = headers
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._authenticated = False
        self._auth_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def authenticate(self) -> None:
        if self._authenticated:
            return
        async with self._auth_lock:
            if self._authenticated:
                return
            if self.settings.cookie_header:
                await self._request_once("GET", "/api/auth/me")
            elif self.settings.username and self.settings.password:
                await self._request_once(
                    "POST",
                    "/api/auth/login",
                    json={
                        "username": self.settings.username,
                        "password": self.settings.password,
                    },
                )
            else:
                raise MiniClawClientError(
                    "MINICLAW_CREDENTIALS_MISSING",
                    "MiniClaw 服务端凭据未配置。",
                )
            self._authenticated = True

    async def get_groups(self) -> dict[str, Any]:
        return await self._request("GET", "/api/groups")

    async def get_agent_profiles(self) -> dict[str, Any]:
        return await self._request("GET", "/api/agent-profiles")

    async def get_sessions(self, workspace_jid: str) -> dict[str, Any]:
        jid = quote(workspace_jid, safe="")
        return await self._request("GET", f"/api/groups/{jid}/sessions")

    async def get_messages(
        self,
        workspace_jid: str,
        session_id: str,
        *,
        limit: int = 200,
    ) -> dict[str, Any]:
        jid = quote(workspace_jid, safe="")
        agent_id = quote(session_id, safe="")
        return await self._request(
            "GET",
            f"/api/groups/{jid}/messages?agentId={agent_id}&limit={limit}",
        )

    async def create_session(
        self,
        workspace_jid: str,
        *,
        name: str,
        description: str,
    ) -> dict[str, Any]:
        jid = quote(workspace_jid, safe="")
        return await self._request(
            "POST",
            f"/api/groups/{jid}/sessions",
            mutation=True,
            json={"name": name, "description": description},
        )

    async def send_message_once(
        self,
        workspace_jid: str,
        session_id: str,
        content: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/messages",
            mutation=True,
            json={
                "chatJid": workspace_jid,
                "agentId": session_id,
                "content": content,
                "followUpBehavior": "queue",
            },
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        mutation: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        await self.authenticate()
        return await self._request_once(method, path, mutation=mutation, **kwargs)

    async def _request_once(
        self,
        method: str,
        path: str,
        *,
        mutation: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            response = await self._http_client().request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise MiniClawClientError(
                "MINICLAW_TRANSPORT_ERROR",
                "MiniClaw Host 请求未得到可确认响应。",
                mutation_uncertain=mutation,
            ) from exc
        if response.is_error:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            upstream_code = payload.get("code") if isinstance(payload, dict) else None
            code = str(upstream_code or f"MINICLAW_HTTP_{response.status_code}")
            raise MiniClawClientError(
                code,
                f"MiniClaw Host 返回 HTTP {response.status_code}。",
                mutation_uncertain=mutation and response.status_code >= 500,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MiniClawClientError(
                "MINICLAW_INVALID_JSON",
                "MiniClaw Host 返回了非 JSON 响应。",
                mutation_uncertain=mutation,
            ) from exc
        if not isinstance(payload, dict):
            raise MiniClawClientError(
                "MINICLAW_INVALID_PAYLOAD",
                "MiniClaw Host 返回结构不符合契约。",
                mutation_uncertain=mutation,
            )
        return payload

    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.base_url.rstrip("/"),
                headers=self._headers,
                timeout=self.settings.timeout_seconds,
                transport=self._transport,
            )
        return self._client
