import asyncio
import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import Field, field_validator

from .models import StrictModel
from .native_api import (
    NativeRuntimeDep, _load_period_13_summary, _materialize_operator_request,
    load_data_source_catalog,
)
from .native_models import (
    NativeDataSourceCatalog, NativeOperatorMetadata, NativeOperatorResultView,
    NativeOperatorRunRequest, NativeOperatorTaskSummary, NativeRunResult,
)
from .native_presenter import build_operator_result_view, build_operator_task_summary
from .native_runtime import NativeInputError, NativeRunConflict, NativeRuntimeUnavailable
from .operations_auth import OperatorDep, require_operator


class OperationsRunRequest(NativeOperatorRunRequest):
    title: str = Field(min_length=1, max_length=60)

    @field_validator("title", "objective")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("任务名称和目标不能为空")
        return value.strip()


class OperationsTask(NativeOperatorTaskSummary):
    title: str
    objective: str
    source_id: str | None
    source_name: str
    result: NativeOperatorResultView


class OperationsTasks(StrictModel):
    tasks: list[OperationsTask]
    has_more: bool


class SourceDataset(StrictModel):
    name: str
    records: int


class OperationsSources(StrictModel):
    catalog: NativeDataSourceCatalog
    datasets: dict[str, list[SourceDataset]]


class OperationsConfiguration(StrictModel):
    ready: bool
    model_submission_requires_explicit_authorization: bool = True
    automatic_model_retry: bool = False


def submission_key(user_id: str, workspace_jid: str | None, key: str) -> str:
    digest = hashlib.sha256(f"{workspace_jid}\0{user_id}\0{key}".encode()).hexdigest()
    return f"operations-{digest}"


def present_task(record: NativeRunResult) -> OperationsTask:
    summary = build_operator_task_summary(record)
    metadata = record.operator_metadata
    result = build_operator_result_view(record)
    if record.terminal_status == "uncertain":
        result = result.model_copy(update={
            "headline": "提交状态待确认",
            "summary": "本次提交的执行状态尚未确认。请保留任务编号并联系管理员核查原任务，确认前不要创建替代任务。",
        })
    return OperationsTask(
        **summary.model_dump(),
        title=metadata.title if metadata else "运营分析",
        objective=metadata.objective if metadata else summary.summary,
        source_id=metadata.source_id if metadata else None,
        source_name="电商运营测试数据" if metadata else "任务提交时的数据文件",
        result=result,
    )


def create_operations_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/operations", tags=["operations"],
        dependencies=[Depends(require_operator)],
    )

    @router.get("/configuration")
    def configuration(runtime: NativeRuntimeDep) -> OperationsConfiguration:
        return OperationsConfiguration(ready=runtime.configuration.ready)

    @router.get("/data-sources")
    def sources() -> OperationsSources:
        catalog = load_data_source_catalog()
        period = _load_period_13_summary()
        return OperationsSources(
            catalog=catalog,
            datasets={catalog.default_source_id: [
                SourceDataset(name=item.label, records=item.row_count)
                for item in period.datasets
            ]},
        )

    @router.get("/tasks")
    async def tasks(
        runtime: NativeRuntimeDep,
        offset: Annotated[int, Query(ge=0, le=10000)] = 0,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
    ) -> OperationsTasks:
        try:
            records = [record for record in runtime.list_operator_runs(limit=None)
                       if record.workspace_jid == runtime.workspace_jid]
            selected = records[offset:offset + limit]
            semaphore = asyncio.Semaphore(3)

            async def refresh(record: NativeRunResult) -> NativeRunResult:
                if record.phase == "settled":
                    return record
                async with semaphore:
                    return await runtime.refresh(record.workflow_run_id)

            refreshed = await asyncio.gather(*(refresh(record) for record in selected))
            return OperationsTasks(
                tasks=[present_task(record) for record in refreshed],
                has_more=len(records) > offset + limit,
            )
        except NativeRuntimeUnavailable as exc:
            raise HTTPException(503, "任务记录读取失败，请联系管理员。") from exc

    @router.get("/tasks/{task_reference}")
    async def task(
        task_reference: Annotated[str, Path(pattern=r"^[A-F0-9]{12}$")],
        runtime: NativeRuntimeDep,
    ) -> OperationsTask:
        try:
            matches = [record for record in runtime.list_operator_runs(limit=None)
                       if record.workspace_jid == runtime.workspace_jid
                       and build_operator_task_summary(record).task_reference == task_reference]
            if not matches:
                raise HTTPException(404, "没有找到对应的分析任务。")
            if len(matches) != 1:
                raise HTTPException(503, "任务编号冲突，请联系管理员。")
            record = matches[0]
            if record.phase != "settled":
                record = await runtime.refresh(record.workflow_run_id)
            return present_task(record)
        except NativeRuntimeUnavailable as exc:
            raise HTTPException(503, "任务记录读取失败，请联系管理员。") from exc

    @router.get("/submissions/{key}")
    def submission(
        key: Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")],
        user_id: OperatorDep, runtime: NativeRuntimeDep,
    ) -> OperationsTask:
        try:
            record = runtime.store.find_by_idempotency_key(submission_key(user_id, runtime.workspace_jid, key))
            if record is None or not record.operator_visible or record.workspace_jid != runtime.workspace_jid:
                raise HTTPException(404, "尚未查到提交记录，请稍后再次查询；不会自动重新提交。")
            return present_task(record)
        except NativeRuntimeUnavailable as exc:
            raise HTTPException(503, "任务记录读取失败，请联系管理员。") from exc

    @router.post("/tasks", status_code=202)
    async def create_task(
        payload: OperationsRunRequest, user_id: OperatorDep, runtime: NativeRuntimeDep,
    ) -> OperationsTask:
        try:
            catalog = load_data_source_catalog()
            source = next((item for item in catalog.sources if item.source_id == payload.source_id), None)
            if source is None or source.status != "ready":
                raise NativeInputError("所选数据源不存在或未通过校验。")
            request = _materialize_operator_request(payload).model_copy(
                update={"idempotency_key": submission_key(user_id, runtime.workspace_jid, payload.idempotency_key)}
            )
            record = await runtime.start(
                request, operator_visible=True,
                operator_metadata=NativeOperatorMetadata(
                    title=payload.title, objective=payload.objective,
                    source_id=payload.source_id, created_by=user_id,
                ),
            )
            return present_task(record)
        except NativeInputError as exc:
            raise HTTPException(422, str(exc)) from exc
        except NativeRunConflict as exc:
            raise HTTPException(409, "已有任务需要核查，请先查询原任务；不能使用变更后的参数或新编号重复提交。") from exc
        except NativeRuntimeUnavailable as exc:
            raise HTTPException(503, "运营运行服务暂不可用，请查询提交记录后检查服务。") from exc

    return router
