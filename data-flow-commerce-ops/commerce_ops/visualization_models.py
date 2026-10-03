from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from .models import StrictModel


DetailKind = Literal["content", "live", "leads", "followups", "orders"]
CellValue = str | int | float | None


class VisualizationFilters(StrictModel):
    source_id: str = Field(default="sample-commerce-data", max_length=80)
    date_from: date | None = None
    date_to: date | None = None
    channel: str | None = Field(default=None, max_length=80)
    content: str | None = Field(default=None, max_length=80)
    session: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("开始日期不能晚于结束日期。")
        return self


class VisualizationOption(StrictModel):
    value: str
    label: str


class VisualizationDetailsQuery(VisualizationFilters):
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=50, ge=1, le=100)


class VisualizationMetric(StrictModel):
    key: str
    label: str
    value: float | None
    format: Literal["number", "currency", "percent"]
    definition: str


class VisualizationSeries(StrictModel):
    key: str
    label: str
    color: str


class VisualizationChart(StrictModel):
    key: str
    title: str
    description: str
    kind: Literal["bar", "line", "funnel"]
    detail: DetailKind
    series: list[VisualizationSeries]
    rows: list[dict[str, CellValue]]


class VisualizationSnapshot(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    source_id: str
    source_name: str
    source_type: str
    synthetic: bool
    data_updated_at: str
    observed_through: str
    date_min: date
    date_max: date
    filters: VisualizationFilters
    options: dict[str, list[VisualizationOption]]
    metrics: list[VisualizationMetric]
    charts: list[VisualizationChart]
    notices: list[str]
    selected_leads: int


class DetailColumn(StrictModel):
    key: str
    label: str


class VisualizationDetails(StrictModel):
    dataset: DetailKind
    columns: list[DetailColumn]
    rows: list[dict[str, CellValue]]
    total: int
    offset: int
    limit: int
