from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from .conversation_models import (
    ConversationCatalog,
    ConversationCreateRequest,
    ConversationSendRequest,
    ConversationThread,
)
from .conversation_context import resolve_conversation_context
from .conversation_service import (
    ConversationConflict,
    ConversationNotFound,
    ConversationService,
    ConversationUnavailable,
)
from .native_api import NativeRuntimeDep
from .native_runtime import NativeRuntimeUnavailable
from .operations_auth import OperatorDep, require_operator
from .visualizations import VisualizationDataError


def _conversation_service(request: Request) -> ConversationService:
    service = request.app.state.conversation_service
    if service is None:
        raise HTTPException(503, "Data Flow 对话服务尚未配置。")
    return service


ConversationServiceDep = Annotated[ConversationService, Depends(_conversation_service)]


def _handle_conversation_error(exc: RuntimeError) -> HTTPException:
    if isinstance(exc, ConversationNotFound):
        return HTTPException(404, str(exc))
    if isinstance(exc, ConversationConflict):
        return HTTPException(409, str(exc))
    return HTTPException(503, str(exc))


def create_conversation_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/operations",
        tags=["operations-conversations"],
        dependencies=[Depends(require_operator)],
    )

    @router.get("/conversations")
    async def conversations(
        user_id: OperatorDep,
        runtime: NativeRuntimeDep,
        service: ConversationServiceDep,
    ) -> ConversationCatalog:
        if not runtime.workspace_jid:
            raise HTTPException(503, "运营工作区尚未配置。")
        try:
            return await service.list_conversations(
                user_id=user_id, workspace_jid=runtime.workspace_jid
            )
        except ConversationUnavailable as exc:
            raise _handle_conversation_error(exc) from exc

    @router.post("/conversations", status_code=201)
    async def create_conversation(
        payload: ConversationCreateRequest,
        user_id: OperatorDep,
        runtime: NativeRuntimeDep,
        service: ConversationServiceDep,
    ) -> ConversationThread:
        if not runtime.workspace_jid:
            raise HTTPException(503, "运营工作区尚未配置。")
        try:
            return await service.create_conversation(
                user_id=user_id,
                workspace_jid=runtime.workspace_jid,
                title=payload.title,
                client_request_id=payload.client_request_id,
            )
        except (ConversationConflict, ConversationUnavailable) as exc:
            raise _handle_conversation_error(exc) from exc

    @router.get("/conversation-submissions/{idempotency_key}")
    async def recover_submission(
        idempotency_key: Annotated[
            str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
        ],
        user_id: OperatorDep,
        runtime: NativeRuntimeDep,
        service: ConversationServiceDep,
    ) -> ConversationThread:
        if not runtime.workspace_jid:
            raise HTTPException(503, "运营工作区尚未配置。")
        try:
            return await service.recover_submission(
                idempotency_key=idempotency_key,
                user_id=user_id,
                workspace_jid=runtime.workspace_jid,
            )
        except (ConversationNotFound, ConversationUnavailable) as exc:
            raise _handle_conversation_error(exc) from exc

    @router.get("/conversations/{conversation_reference}")
    async def conversation(
        conversation_reference: Annotated[
            str, Path(pattern=r"^[A-F0-9]{12}$")
        ],
        user_id: OperatorDep,
        runtime: NativeRuntimeDep,
        service: ConversationServiceDep,
    ) -> ConversationThread:
        if not runtime.workspace_jid:
            raise HTTPException(503, "运营工作区尚未配置。")
        try:
            return await service.get_thread(
                reference=conversation_reference,
                user_id=user_id,
                workspace_jid=runtime.workspace_jid,
            )
        except (ConversationNotFound, ConversationUnavailable) as exc:
            raise _handle_conversation_error(exc) from exc

    @router.post("/conversations/{conversation_reference}/messages", status_code=202)
    async def send_message(
        conversation_reference: Annotated[
            str, Path(pattern=r"^[A-F0-9]{12}$")
        ],
        payload: ConversationSendRequest,
        user_id: OperatorDep,
        runtime: NativeRuntimeDep,
        service: ConversationServiceDep,
    ) -> ConversationThread:
        if not runtime.workspace_jid:
            raise HTTPException(503, "运营工作区尚未配置。")
        try:
            context_prefix = None
            context_link = None
            if payload.context is not None:
                context_prefix, context_link = await resolve_conversation_context(
                    payload.context, runtime
                )
            transport_content = (
                f"{context_prefix}\n\n[用户问题]\n{payload.content}"
                if context_prefix
                else payload.content
            )
            return await service.send_message(
                reference=conversation_reference,
                user_id=user_id,
                workspace_jid=runtime.workspace_jid,
                content=payload.content,
                transport_content=transport_content,
                context=context_link,
                idempotency_key=payload.idempotency_key,
            )
        except (
            ConversationNotFound,
            ConversationConflict,
            ConversationUnavailable,
        ) as exc:
            raise _handle_conversation_error(exc) from exc
        except VisualizationDataError as exc:
            raise HTTPException(503, "无法读取要关联的数据看板。") from exc
        except NativeRuntimeUnavailable as exc:
            raise HTTPException(503, "无法读取要关联的分析任务。") from exc

    return router
