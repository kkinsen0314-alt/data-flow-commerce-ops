from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from .native_api import NativeRuntimeDep
from .operations_auth import require_operator
from .visualization_models import DetailKind, VisualizationDetails, VisualizationDetailsQuery, VisualizationFilters, VisualizationSnapshot
from .visualizations import VisualizationDataError, VisualizationService


def get_visualization_service(runtime: NativeRuntimeDep) -> VisualizationService:
    return VisualizationService(runtime.data_root)


VisualizationDep = Annotated[VisualizationService, Depends(get_visualization_service)]
FiltersDep = Annotated[VisualizationFilters, Query()]


def create_visualization_router() -> APIRouter:
    router = APIRouter(prefix="/v1/operations/visualizations", tags=["visualizations"], dependencies=[Depends(require_operator)])

    def invoke(operation, *args):
        try:
            return operation(*args)
        except VisualizationDataError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("")
    def snapshot(filters: FiltersDep, service: VisualizationDep) -> VisualizationSnapshot:
        return invoke(service.snapshot, filters)

    @router.get("/details/{dataset}")
    def details(dataset: DetailKind, query: Annotated[VisualizationDetailsQuery, Query()], service: VisualizationDep) -> VisualizationDetails:
        filters = VisualizationFilters.model_validate(query.model_dump(exclude={"offset", "limit"}))
        return invoke(service.details, filters, dataset, query.offset, query.limit)

    @router.get("/export/{dataset}.csv")
    def export(dataset: DetailKind, filters: FiltersDep, service: VisualizationDep) -> Response:
        return Response(invoke(service.export_csv, filters, dataset), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="data-flow-{dataset}.csv"'})

    return router
