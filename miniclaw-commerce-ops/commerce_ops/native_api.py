"""FastAPI router for MiniClaw native runtime operations."""

import json
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path as ApiPath,
    Query,
    Request,
    status,
)

from .native_models import (
    NativeDataSourceCatalog,
    NativeDataSourceSummary,
    NativeDataSourceTypeOption,
    NativeDatasetInput,
    NativeOperatorRunRequest,
    NativeOperatorResultView,
    NativeOperatorTaskCatalog,
    NativePeriod13Dataset,
    NativePeriod13Metrics,
    NativePeriod13Summary,
    NativeRunRequest,
    NativeRunResult,
    NativeRuntimeConfiguration,
)
from .native_presenter import (
    build_operator_result_view,
    build_operator_task_summary,
    operator_task_reference,
)
from .native_runtime import (
    NativeInputError,
    NativeRunConflict,
    NativeRunNotFound,
    NativeRuntime,
    NativeRuntimeUnavailable,
)


def _get_native_runtime(request: Request) -> NativeRuntime:
    return request.app.state.native_runtime


def _require_loopback(request: Request) -> None:
    host = request.client.host if request.client else None
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="原生运行接口仅允许本机调用。",
        )


NativeRuntimeDep = Annotated[NativeRuntime, Depends(_get_native_runtime)]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PERIOD_13_ARTIFACT = (
    PROJECT_ROOT / "artifacts" / "period-13-data-validation-v1.json"
)
PERIOD_13_DATASETS = (
    ("short_video", "短视频", "period-13/short-video-period-13.csv"),
    ("live_session", "直播场次", "period-13/live-session-period-13.csv"),
    ("channel_lead", "渠道线索", "period-13/channel-leads-period-13.csv"),
    ("sales_followup", "销售跟进", "period-13/sales-followup-period-13.csv"),
    ("order", "订单", "period-13/orders-period-13.csv"),
)
OPERATOR_DATA_SOURCES = {
    "sample-commerce-data": {
        dataset_type: file_path
        for dataset_type, _, file_path in PERIOD_13_DATASETS
    }
}
DOMAIN_DATASET_TYPES = {
    "content_growth": ("short_video",),
    "live_conversion": ("live_session",),
    "attribution_leads": ("channel_lead", "sales_followup", "order"),
}


def _materialize_operator_request(
    payload: NativeOperatorRunRequest,
) -> NativeRunRequest:
    source = OPERATOR_DATA_SOURCES.get(payload.source_id)
    if source is None:
        raise NativeInputError("所选数据源不存在或当前不可用。")
    selected_types = {
        dataset_type
        for domain in payload.requested_domains
        for dataset_type in DOMAIN_DATASET_TYPES[domain]
    }
    return NativeRunRequest(
        idempotency_key=payload.idempotency_key,
        requested_domains=payload.requested_domains,
        datasets=[
            NativeDatasetInput(
                dataset_type=dataset_type,
                file_path=file_path,
            )
            for dataset_type, _, file_path in PERIOD_13_DATASETS
            if dataset_type in selected_types
        ],
        objective=payload.objective,
        include_strategy=payload.include_strategy,
        authorized_model_execution=True,
    )


def _load_period_13_summary() -> NativePeriod13Summary:
    payload = json.loads(PERIOD_13_ARTIFACT.read_text(encoding="utf-8"))
    if payload.get("synthetic") is not True:
        raise ValueError("第 13 期数据未保留 synthetic 边界。")
    manifests = payload["production_manifests"]
    datasets = [
        NativePeriod13Dataset(
            dataset_type=dataset_type,
            label=label,
            file_path=file_path,
            row_count=manifests[dataset_type]["row_count"],
            quality_status=manifests[dataset_type]["quality_status"],
        )
        for dataset_type, label, file_path in PERIOD_13_DATASETS
    ]
    metrics = payload["business_metrics"]
    return NativePeriod13Summary(
        label=payload["period"]["label"],
        start=payload["period"]["start"],
        end=payload["period"]["end"],
        status=payload["status"],
        checks_total=payload["checks_total"],
        checks_passed=payload["checks_passed"],
        total_rows=sum(item.row_count for item in datasets),
        datasets=datasets,
        metrics=NativePeriod13Metrics(
            paid_order_count=metrics["paid_order_count"],
            paid_gmv=metrics["paid_gmv"],
            order_lead_coverage=metrics["order_lead_coverage"],
            paid_lead_conversion=metrics["paid_lead_conversion"],
            followup_within_24h=metrics["followup_within_24h"]["ratio"],
            intentional_missing_followup_count=len(
                metrics["intentional_missing_followup_lead_ids"]
            ),
        ),
    )


def load_data_source_catalog() -> NativeDataSourceCatalog:
    try:
        period_summary = _load_period_13_summary()
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="运营数据源当前不可用。",
        ) from exc
    source = NativeDataSourceSummary(
        source_id="sample-commerce-data",
        display_name="电商运营测试数据",
        description="短视频、直播场次、渠道线索、销售跟进和订单数据。",
        source_type="local_file",
        source_type_label="本地文件（CSV）",
        status="ready" if period_summary.status == "pass" else "degraded",
        synthetic=True,
        dataset_count=len(period_summary.datasets),
        record_count=period_summary.total_rows,
        available_domains=[
            "content_growth",
            "live_conversion",
            "attribution_leads",
        ],
        dataset_types=[item.dataset_type for item in period_summary.datasets],
        dataset_labels=[item.label for item in period_summary.datasets],
        data_period=f"{period_summary.start} 至 {period_summary.end}",
    )
    return NativeDataSourceCatalog(
        default_source_id=source.source_id,
        sources=[source],
        source_types=[
            NativeDataSourceTypeOption(
                type_id="local_file",
                display_name="CSV / Excel",
                category="file",
                status="enabled",
                description="上传或读取受控目录中的表格文件。",
                connection_method="本地只读文件",
                requires_authorization=False,
                read_only_supported=True,
            ),
            NativeDataSourceTypeOption(
                type_id="mysql",
                display_name="MySQL",
                category="database",
                status="configurable",
                description="使用只读账号连接指定数据库、表或视图。",
                connection_method="数据库只读连接器",
                requires_authorization=True,
                read_only_supported=True,
            ),
            NativeDataSourceTypeOption(
                type_id="postgresql",
                display_name="PostgreSQL",
                category="database",
                status="configurable",
                description="使用只读账号连接指定数据库、表或视图。",
                connection_method="数据库只读连接器",
                requires_authorization=True,
                read_only_supported=True,
            ),
            NativeDataSourceTypeOption(
                type_id="feishu_bitable",
                display_name="飞书多维表格",
                category="application",
                status="configurable",
                description="通过飞书开放平台读取已授权的数据表记录。",
                connection_method="MiniClaw MCP / 飞书 OpenAPI",
                requires_authorization=True,
                read_only_supported=True,
            ),
            NativeDataSourceTypeOption(
                type_id="feishu_spreadsheet",
                display_name="飞书电子表格",
                category="application",
                status="configurable",
                description="读取已授权电子表格中的指定工作表和范围。",
                connection_method="MiniClaw MCP / 飞书 OpenAPI",
                requires_authorization=True,
                read_only_supported=True,
            ),
            NativeDataSourceTypeOption(
                type_id="http_api",
                display_name="HTTP API",
                category="api",
                status="configurable",
                description="接入电商平台、CRM、ERP 等标准业务接口。",
                connection_method="受控 HTTPS 接口",
                requires_authorization=True,
                read_only_supported=True,
            ),
            NativeDataSourceTypeOption(
                type_id="mcp",
                display_name="MCP 连接器",
                category="connector",
                status="configurable",
                description="复用 MiniClaw 原生 MCP 能力接入外部数据工具。",
                connection_method="MiniClaw MCP",
                requires_authorization=True,
                read_only_supported=True,
            ),
        ],
    )


def create_native_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/native",
        tags=["miniclaw_native"],
        dependencies=[Depends(_require_loopback)],
    )

    @router.get("/configuration")
    def get_native_configuration(
        runtime: NativeRuntimeDep,
    ) -> NativeRuntimeConfiguration:
        return runtime.configuration

    @router.get("/period-13")
    def get_period_13_summary() -> NativePeriod13Summary:
        try:
            return _load_period_13_summary()
        except (
            KeyError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="第 13 期 synthetic 数据验证摘要当前不可用。",
            ) from exc

    @router.get("/data-sources")
    def get_data_sources() -> NativeDataSourceCatalog:
        return load_data_source_catalog()

    @router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
    async def start_native_run(
        payload: NativeRunRequest | NativeOperatorRunRequest,
        runtime: NativeRuntimeDep,
    ) -> NativeRunResult:
        try:
            runtime_payload = (
                _materialize_operator_request(payload)
                if isinstance(payload, NativeOperatorRunRequest)
                else payload
            )
            return await runtime.start(
                runtime_payload,
                operator_visible=isinstance(payload, NativeOperatorRunRequest),
            )
        except NativeInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except NativeRunConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except NativeRuntimeUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/runs/{workflow_run_id}")
    async def get_native_run(
        workflow_run_id: str,
        runtime: NativeRuntimeDep,
    ) -> NativeRunResult:
        try:
            return await runtime.refresh(workflow_run_id)
        except NativeRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except NativeRuntimeUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/runs/{workflow_run_id}/result")
    async def get_native_operator_result(
        workflow_run_id: str,
        runtime: NativeRuntimeDep,
    ) -> NativeOperatorResultView:
        try:
            record = await runtime.refresh(workflow_run_id)
            return build_operator_result_view(record)
        except NativeRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except NativeRuntimeUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/tasks")
    def list_native_operator_tasks(
        runtime: NativeRuntimeDep,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
    ) -> NativeOperatorTaskCatalog:
        try:
            records = runtime.list_operator_runs(limit=limit + 1)
        except NativeRuntimeUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return NativeOperatorTaskCatalog(
            returned_count=min(len(records), limit),
            has_more=len(records) > limit,
            tasks=[
                build_operator_task_summary(record)
                for record in records[:limit]
            ],
        )

    @router.get("/tasks/{task_reference}/result")
    async def get_native_operator_task_result(
        task_reference: Annotated[
            str,
            ApiPath(pattern=r"^[A-F0-9]{12}$"),
        ],
        runtime: NativeRuntimeDep,
    ) -> NativeOperatorResultView:
        try:
            matches = [
                record
                for record in runtime.list_operator_runs(limit=None)
                if operator_task_reference(record.workflow_run_id)
                == task_reference
            ]
            if not matches:
                raise NativeRunNotFound("任务记录不存在。")
            if len(matches) > 1:
                raise NativeRuntimeUnavailable("任务参考号冲突，结果暂不可用。")
            record = matches[0]
            if record.phase != "settled":
                record = await runtime.refresh(record.workflow_run_id)
            return build_operator_result_view(record)
        except NativeRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except NativeRuntimeUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return router
