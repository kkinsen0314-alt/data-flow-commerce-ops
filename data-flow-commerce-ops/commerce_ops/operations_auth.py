from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, Request

from .native_api import NativeRuntimeDep, _require_loopback


class OperationsAuth:
    def __init__(
        self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    async def verify(self, cookie: str, workspace_jid: str | None) -> str:
        if not cookie:
            raise HTTPException(401, "登录已失效，请重新登录。")
        if not workspace_jid:
            raise HTTPException(503, "运营服务尚未启动，请使用原生运行启动脚本。")
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, headers={"Cookie": cookie},
                timeout=10, follow_redirects=False, transport=self.transport,
            ) as client:
                identity = await client.get("/api/auth/me")
                self._check_status(identity)
                user = identity.json().get("user")
                if not isinstance(user, dict) or not isinstance(user.get("id"), str):
                    raise ValueError("Invalid identity")
                if user.get("must_change_password"):
                    raise HTTPException(403, "请先在账户设置中修改密码。")
                groups = await client.get("/api/groups")
                self._check_status(groups)
                visible = groups.json().get("groups")
                if not isinstance(visible, dict):
                    raise ValueError("Invalid workspace list")
                if workspace_jid not in visible:
                    raise HTTPException(403, "当前账号没有此运营工作区的访问权限。")
                return user["id"]
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            raise HTTPException(503, "无法验证登录状态，请检查 MiniClaw 服务。") from exc

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        if response.status_code == 401:
            raise HTTPException(401, "登录已失效，请重新登录。")
        if response.status_code == 403:
            raise HTTPException(403, "当前账号无权访问，请检查账户状态和工作区权限。")
        if response.status_code != 200:
            raise HTTPException(503, "MiniClaw 认证服务暂时无法访问。")


async def require_operator(request: Request, runtime: NativeRuntimeDep) -> str:
    _require_loopback(request)
    auth: OperationsAuth = request.app.state.operations_auth
    origin = request.headers.get("origin")
    if origin is not None and origin != auth.base_url:
        raise HTTPException(403, "请求来源不受信任。")
    if request.method not in {"GET", "HEAD"} and origin != auth.base_url:
        raise HTTPException(403, "请从 Data Flow 页面提交任务。")
    return await auth.verify(request.headers.get("cookie", ""), runtime.workspace_jid)


OperatorDep = Annotated[str, Depends(require_operator)]
