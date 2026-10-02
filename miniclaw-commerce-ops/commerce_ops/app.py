"""FastAPI surface for deterministic tools and MiniClaw native runs."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .datasets import MAX_INPUT_BYTES
from .conversation_api import create_conversation_router
from .conversation_service import ConversationService
from .conversation_store import ConversationStore
from .demo_models import (
    DemoRunRequest,
    DemoRunResult,
    DemoScenarioCatalog,
    DemoUploadedFile,
    DemoUploadRunRequest,
)
from .demo_orchestrator import (
    MAX_DEMO_FILES,
    MAX_DEMO_TOTAL_BYTES,
    DemoInputError,
    DemoOrchestrator,
    DemoRunNotFound,
)
from .native_api import create_native_router
from .native_runtime import NativeRuntime, default_native_runtime
from .operations_auth import OperationsAuth
from .operations_api import create_operations_router
from .visualization_api import create_visualization_router
from .service import CommerceOpsService, default_service
from .tool_models import (
    AnalysisToolResult,
    AttributionLeadAnalysisRequest,
    DrilldownCommerceMetricRequest,
    DrilldownResult,
    HealthResult,
    InspectCommerceDataRequest,
    InspectionResult,
    LiveCommerceAnalysisRequest,
    ShortVideoAnalysisRequest,
    ToolCatalog,
)


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
NATIVE_WEB_ROOT = Path(__file__).resolve().parents[1] / "native_web"


def _get_service(request: Request) -> CommerceOpsService:
    return request.app.state.commerce_ops_service


ServiceDep = Annotated[CommerceOpsService, Depends(_get_service)]


def _get_demo_orchestrator(request: Request) -> DemoOrchestrator:
    return request.app.state.demo_orchestrator


DemoOrchestratorDep = Annotated[
    DemoOrchestrator,
    Depends(_get_demo_orchestrator),
]


def create_app(
    service: CommerceOpsService | None = None,
    demo_orchestrator: DemoOrchestrator | None = None,
    native_runtime: NativeRuntime | None = None,
    operations_auth: OperationsAuth | None = None,
    conversation_store: ConversationStore | None = None,
    conversation_service: ConversationService | None = None,
) -> FastAPI:
    commerce_service = service or default_service()
    miniclaw_runtime = native_runtime or default_native_runtime()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await miniclaw_runtime.aclose()

    application = FastAPI(
        title="MiniClaw 电商运营确定性工具层",
        version="0.4.0",
        description=(
            "提供五个只读经营分析工具，以及服务端驱动的 MiniClaw "
            "原生 Agent 运行接口。"
        ),
        lifespan=lifespan,
    )
    application.state.commerce_ops_service = commerce_service
    application.state.native_runtime = miniclaw_runtime
    application.state.operations_auth = operations_auth or OperationsAuth(
        miniclaw_runtime.configuration.base_url
    )
    runtime_client = getattr(miniclaw_runtime, "client", None)
    application.state.conversation_service = conversation_service
    if application.state.conversation_service is None and runtime_client is not None:
        application.state.conversation_service = ConversationService(
            runtime_client,
            conversation_store
            or ConversationStore(
                miniclaw_runtime.project_root / "runtime" / "data" / "conversations"
            ),
        )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[application.state.operations_auth.base_url],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @application.middleware("http")
    async def protect_browser_surface(request: Request, call_next):
        is_browser = "origin" in request.headers or "sec-fetch-site" in request.headers
        if is_browser and request.url.path.startswith("/v1/") and not request.url.path.startswith("/v1/operations/"):
            return JSONResponse({"detail": "浏览器请使用已认证的运营接口。"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/v1/operations/"):
            response.headers["Cache-Control"] = "no-store"
        return response
    application.state.demo_orchestrator = demo_orchestrator or DemoOrchestrator(
        commerce_service.store.data_root
    )

    application.mount(
        "/demo/assets",
        StaticFiles(directory=WEB_ROOT),
        name="demo-assets",
    )
    application.mount(
        "/native/assets",
        StaticFiles(directory=NATIVE_WEB_ROOT),
        name="native-assets",
    )

    @application.get("/", include_in_schema=False)
    def redirect_to_native_console() -> RedirectResponse:
        return RedirectResponse(url="/native", status_code=307)

    @application.get("/native", include_in_schema=False)
    def native_page() -> RedirectResponse:
        return RedirectResponse(
            url=f"{application.state.operations_auth.base_url}/operations", status_code=307
        )

    @application.get("/demo", include_in_schema=False)
    def demo_page() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html")

    router = APIRouter(prefix="/v1", tags=["commerce_ops"])
    demo_router = APIRouter(prefix="/v1/demo", tags=["demo"])

    @application.get("/health")
    def health_check(service_dep: ServiceDep) -> HealthResult:
        return service_dep.health()

    @router.get("/tools")
    def describe_tools(service_dep: ServiceDep) -> ToolCatalog:
        return service_dep.describe_tools()

    @router.post("/inspect")
    def inspect_commerce_data(
        request: InspectCommerceDataRequest,
        service_dep: ServiceDep,
    ) -> InspectionResult:
        return service_dep.inspect_commerce_data(request)

    @router.post("/analyze/short-video")
    def analyze_short_video_data(
        request: ShortVideoAnalysisRequest,
        service_dep: ServiceDep,
    ) -> AnalysisToolResult:
        return service_dep.analyze_short_video_data(request)

    @router.post("/analyze/live")
    def analyze_live_commerce_data(
        request: LiveCommerceAnalysisRequest,
        service_dep: ServiceDep,
    ) -> AnalysisToolResult:
        return service_dep.analyze_live_commerce_data(request)

    @router.post("/analyze/attribution-leads")
    def analyze_attribution_and_leads(
        request: AttributionLeadAnalysisRequest,
        service_dep: ServiceDep,
    ) -> AnalysisToolResult:
        return service_dep.analyze_attribution_and_leads(request)

    @router.post("/drilldown")
    def drilldown_commerce_metric(
        request: DrilldownCommerceMetricRequest,
        service_dep: ServiceDep,
    ) -> DrilldownResult:
        return service_dep.drilldown_commerce_metric(request)

    @demo_router.get("/scenarios")
    def list_demo_scenarios(
        orchestrator: DemoOrchestratorDep,
    ) -> DemoScenarioCatalog:
        return orchestrator.scenarios()

    @demo_router.post("/runs/sample")
    def run_sample_demo(
        request: DemoRunRequest,
        orchestrator: DemoOrchestratorDep,
    ) -> DemoRunResult:
        try:
            return orchestrator.run_sample(request)
        except DemoInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @demo_router.post("/runs/upload")
    async def run_uploaded_demo(
        metadata: Annotated[str, Form()],
        files: Annotated[list[UploadFile], File()],
        orchestrator: DemoOrchestratorDep,
    ) -> DemoRunResult:
        try:
            request = DemoUploadRunRequest.model_validate_json(metadata)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=exc.errors(include_input=False),
            ) from exc
        if len(files) > MAX_DEMO_FILES:
            raise HTTPException(
                status_code=413,
                detail=f"上传文件不能超过 {MAX_DEMO_FILES} 个。",
            )
        uploaded_files = []
        total_bytes = 0
        for uploaded in files:
            content = await uploaded.read(MAX_INPUT_BYTES + 1)
            await uploaded.close()
            if len(content) > MAX_INPUT_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"{uploaded.filename or 'upload'} 超过 25 MB。",
                )
            total_bytes += len(content)
            if total_bytes > MAX_DEMO_TOTAL_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="上传文件总大小不能超过 50 MB。",
                )
            uploaded_files.append(
                DemoUploadedFile(
                    file_name=uploaded.filename or "upload.csv",
                    content=content,
                )
            )
        try:
            return orchestrator.run_upload(request, uploaded_files)
        except DemoInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @demo_router.get("/runs/{workflow_run_id}")
    def get_demo_run(
        workflow_run_id: str,
        orchestrator: DemoOrchestratorDep,
    ) -> DemoRunResult:
        try:
            return orchestrator.get_run(workflow_run_id)
        except DemoRunNotFound as exc:
            raise HTTPException(status_code=404, detail="演示运行不存在。") from exc

    @demo_router.get("/runs/{workflow_run_id}/report")
    def download_demo_report(
        workflow_run_id: str,
        orchestrator: DemoOrchestratorDep,
    ) -> Response:
        try:
            result = orchestrator.get_run(workflow_run_id)
        except DemoRunNotFound as exc:
            raise HTTPException(status_code=404, detail="演示运行不存在。") from exc
        return Response(
            content=result.model_dump_json(indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{workflow_run_id}.json"'
                )
            },
        )

    application.include_router(router)
    application.include_router(demo_router)
    application.include_router(create_native_router())
    application.include_router(create_operations_router())
    application.include_router(create_conversation_router())
    application.include_router(create_visualization_router())
    return application


app = create_app()
