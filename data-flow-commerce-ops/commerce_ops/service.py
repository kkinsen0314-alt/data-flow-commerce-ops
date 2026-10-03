"""Deterministic read-only implementations of the five commerce tools."""

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Any, Iterable
from uuid import uuid4

import pandas as pd

from .datasets import DatasetAccessError, DatasetStore, StoredDataset, dimension_column
from .models import (
    AnalysisPacket,
    Evidence,
    Finding,
    ServiceCall,
    WorkflowError,
)
from .tool_models import (
    AnalysisToolResult,
    AttributionLeadAnalysisRequest,
    DrilldownCommerceMetricRequest,
    DrilldownResult,
    DrilldownRow,
    HealthResult,
    InspectCommerceDataRequest,
    InspectionResult,
    LiveCommerceAnalysisRequest,
    ShortVideoAnalysisRequest,
    ToolCatalog,
    tool_catalog,
)


@dataclass(frozen=True)
class AnalysisContext:
    packet: AnalysisPacket
    dataset_ids: tuple[str, ...]


class CommerceOpsService:
    def __init__(
        self,
        data_root: Path,
        *,
        allow_non_synthetic: bool = False,
    ) -> None:
        self.store = DatasetStore(
            data_root,
            allow_non_synthetic=allow_non_synthetic,
        )
        self._analyses: dict[str, AnalysisContext] = {}
        self._lock = RLock()

    def health(self) -> HealthResult:
        return HealthResult(data_root=str(self.store.data_root))

    def describe_tools(self) -> ToolCatalog:
        return tool_catalog()

    def inspect_commerce_data(
        self,
        request: InspectCommerceDataRequest,
    ) -> InspectionResult:
        started = perf_counter()
        service_run_id = _run_id("srv_inspect")
        manifests = []
        missing: list[str] = []
        seen_ids: set[str] = set()
        first_error: DatasetAccessError | None = None

        for reference in request.data_refs:
            if reference.dataset_id in seen_ids:
                error = DatasetAccessError(
                    "INVALID_INPUT",
                    f"dataset_id 重复：{reference.dataset_id}。",
                )
                first_error = first_error or error
                missing.append(error.safe_message)
                continue
            seen_ids.add(reference.dataset_id)
            try:
                stored = self.store.load(request.workflow_run_id, reference)
            except DatasetAccessError as exc:
                first_error = first_error or exc
                missing.append(exc.safe_message)
                continue
            manifests.append(stored.manifest)
            if stored.manifest.data_quality.status == "blocked":
                missing.append(
                    f"{reference.dataset_id} 缺少必需字段："
                    + ", ".join(
                        stored.manifest.data_quality.missing_required_fields
                    )
                )

        duration = _duration_ms(started)
        synthetic = all(item.synthetic for item in request.data_refs)
        if not manifests:
            error = first_error or DatasetAccessError(
                "ANALYSIS_UNAVAILABLE", "没有可注册的数据集。"
            )
            return InspectionResult(
                workflow_run_id=request.workflow_run_id,
                service_run_id=service_run_id,
                caller_role=request.caller_role,
                terminal_status="blocked",
                synthetic=synthetic,
                missing_evidence=missing or [error.safe_message],
                workflow_error=_workflow_error(
                    request.workflow_run_id,
                    stage="inspection",
                    code=error.code,
                    safe_message=error.safe_message,
                ),
                duration_ms=duration,
            )

        status = "completed"
        if missing or any(
            item.data_quality.status != "pass" for item in manifests
        ):
            status = "partial"
        return InspectionResult(
            workflow_run_id=request.workflow_run_id,
            service_run_id=service_run_id,
            caller_role=request.caller_role,
            terminal_status=status,
            synthetic=synthetic,
            dataset_manifests=manifests,
            missing_evidence=missing,
            duration_ms=duration,
        )

    def analyze_short_video_data(
        self,
        request: ShortVideoAnalysisRequest,
    ) -> AnalysisToolResult:
        started = perf_counter()
        service_run_id = _run_id("srv_video")
        tool_name = "analyze_short_video_data"
        allowed_dimensions = {"account", "content", "publish_time"}
        invalid = set(request.requested_dimensions) - allowed_dimensions
        if invalid:
            return self._analysis_error(
                request,
                service_run_id,
                tool_name,
                started,
                "INVALID_INPUT",
                f"短视频分析不允许维度：{', '.join(sorted(invalid))}。",
            )
        try:
            datasets = self._datasets_for_analysis(
                request.workflow_run_id,
                request.dataset_ids,
                required_type="short_video",
                allowed_types={"short_video", "account", "channel_lead"},
                synthetic=request.synthetic,
            )
        except DatasetAccessError as exc:
            return self._analysis_error(
                request,
                service_run_id,
                tool_name,
                started,
                exc.code,
                exc.safe_message,
            )

        video = _concat(datasets, "short_video")
        totals = {
            field: float(video[field].fillna(0).sum())
            for field in (
                "impressions",
                "plays",
                "completions",
                "interactions",
                "clicks",
            )
        }
        metrics = {
            "play_rate": _rate(totals["plays"], totals["impressions"]),
            "completion_rate": _rate(
                totals["completions"], totals["plays"]
            ),
            "interaction_rate": _rate(
                totals["interactions"], totals["plays"]
            ),
            "click_rate": _rate(totals["clicks"], totals["plays"]),
        }
        run_token = uuid4().hex[:12]
        evidence = [
            _evidence(
                f"ev_video_click_{run_token}",
                _first_dataset_id(datasets, "short_video"),
                service_run_id,
                "click_rate",
                metrics["click_rate"],
                "ratio",
                "sum(clicks) / sum(plays)",
                "合成短视频样例的点击率已按统一口径计算。",
                _quality(datasets),
            ),
            _evidence(
                f"ev_video_completion_{run_token}",
                _first_dataset_id(datasets, "short_video"),
                service_run_id,
                "completion_rate",
                metrics["completion_rate"],
                "ratio",
                "sum(completions) / sum(plays)",
                "合成短视频样例的完播率已按统一口径计算。",
                _quality(datasets),
            ),
        ]
        missing = _missing_dimensions(datasets, request.requested_dimensions)

        lead_datasets = [
            item for item in datasets if item.reference.dataset_type == "channel_lead"
        ]
        if lead_datasets:
            lead_frame = _concat(datasets, "channel_lead")
            if "click_id_hash" in video and "click_id_hash" in lead_frame:
                linked = lead_frame["click_id_hash"].isin(
                    set(video["click_id_hash"].dropna())
                ).sum()
                evidence.append(
                    _evidence(
                        f"ev_video_linked_leads_{run_token}",
                        lead_datasets[0].reference.dataset_id,
                        service_run_id,
                        "linked_lead_coverage_rate",
                        _rate(linked, len(lead_frame)),
                        "ratio",
                        "linked lead click keys / all lead rows",
                        "只在稳定脱敏 click_id_hash 覆盖范围内计算关联线索率。",
                        _quality(datasets),
                    )
                )
            else:
                missing.append("缺少稳定 click_id_hash，未计算内容到线索关联")

        severity = (
            "attention"
            if metrics["click_rate"] < 0.05
            or metrics["completion_rate"] < 0.30
            else "normal"
        )
        findings = [
            Finding(
                finding_id=f"finding_video_funnel_{run_token}",
                category="content",
                severity=severity,
                statement=(
                    "合成短视频样例已形成曝光、播放、完播、互动和点击漏斗；"
                    "阈值只用于确定性回归，不代表真实账号表现。"
                ),
                evidence_ids=[item.evidence_id for item in evidence[:2]],
                confidence=0.95,
                limitations=["synthetic=true", *missing],
            )
        ]
        return self._analysis_success(
            request=request,
            datasets=datasets,
            service_run_id=service_run_id,
            tool_name=tool_name,
            domain="content_growth",
            analysis_prefix="analysis_video",
            evidence=evidence,
            findings=findings,
            missing=missing,
            started=started,
        )

    def analyze_live_commerce_data(
        self,
        request: LiveCommerceAnalysisRequest,
    ) -> AnalysisToolResult:
        started = perf_counter()
        service_run_id = _run_id("srv_live")
        tool_name = "analyze_live_commerce_data"
        allowed_dimensions = {"account", "live_session", "channel"}
        invalid = set(request.requested_dimensions) - allowed_dimensions
        if invalid:
            return self._analysis_error(
                request,
                service_run_id,
                tool_name,
                started,
                "INVALID_INPUT",
                f"直播分析不允许维度：{', '.join(sorted(invalid))}。",
            )
        try:
            datasets = self._datasets_for_analysis(
                request.workflow_run_id,
                request.dataset_ids,
                required_type="live_session",
                allowed_types={"live_session", "account", "channel_lead", "order"},
                synthetic=request.synthetic,
            )
        except DatasetAccessError as exc:
            return self._analysis_error(
                request,
                service_run_id,
                tool_name,
                started,
                exc.code,
                exc.safe_message,
            )

        live = _concat(datasets, "live_session")
        row_count = len(live)
        attended = int(live["attended"].fillna(False).sum())
        completed = int(live["completed_view"].fillna(False).sum())
        clicked = int(live["product_clicked"].fillna(False).sum())
        paid = int(live["payment_initiated"].fillna(False).sum())
        ordered = int(live["ordered"].fillna(False).sum())
        metrics = {
            "attendance_rate": _rate(attended, row_count),
            "completion_rate": _rate(completed, attended),
            "product_click_rate": _rate(clicked, attended),
            "payment_rate": _rate(paid, clicked),
            "purchase_rate": _rate(ordered, attended),
        }
        run_token = uuid4().hex[:12]
        dataset_id = _first_dataset_id(datasets, "live_session")
        evidence = [
            _evidence(
                f"ev_live_attendance_{run_token}",
                dataset_id,
                service_run_id,
                "attendance_rate",
                metrics["attendance_rate"],
                "ratio",
                "attended rows / reservation rows",
                "合成直播样例的到课率已按预约记录口径计算。",
                _quality(datasets),
            ),
            _evidence(
                f"ev_live_purchase_{run_token}",
                dataset_id,
                service_run_id,
                "purchase_rate",
                metrics["purchase_rate"],
                "ratio",
                "ordered rows / attended rows",
                "合成直播样例的购买率已按到课记录口径计算。",
                _quality(datasets),
            ),
        ]
        missing = _missing_dimensions(datasets, request.requested_dimensions)
        severity = (
            "attention"
            if metrics["attendance_rate"] < 0.60
            or metrics["purchase_rate"] < 0.10
            else "normal"
        )
        findings = [
            Finding(
                finding_id=f"finding_live_funnel_{run_token}",
                category="live_funnel",
                severity=severity,
                statement=(
                    "合成直播样例已形成预约、到课、完课、商品访问、支付和购买漏斗；"
                    "不据此推断真实直播经营结果。"
                ),
                evidence_ids=[item.evidence_id for item in evidence],
                confidence=0.95,
                limitations=["synthetic=true", *missing],
            )
        ]
        return self._analysis_success(
            request=request,
            datasets=datasets,
            service_run_id=service_run_id,
            tool_name=tool_name,
            domain="live_conversion",
            analysis_prefix="analysis_live",
            evidence=evidence,
            findings=findings,
            missing=missing,
            started=started,
        )

    def analyze_attribution_and_leads(
        self,
        request: AttributionLeadAnalysisRequest,
    ) -> AnalysisToolResult:
        started = perf_counter()
        service_run_id = _run_id("srv_attribution")
        tool_name = "analyze_attribution_and_leads"
        allowed_dimensions = {
            "channel",
            "lead_source",
            "sales_owner",
            "order_status",
        }
        invalid = set(request.requested_dimensions) - allowed_dimensions
        if invalid:
            return self._analysis_error(
                request,
                service_run_id,
                tool_name,
                started,
                "INVALID_INPUT",
                f"归因与线索分析不允许维度：{', '.join(sorted(invalid))}。",
            )
        try:
            datasets = self._datasets_for_analysis(
                request.workflow_run_id,
                request.dataset_ids,
                required_type="channel_lead",
                allowed_types={
                    "channel_lead",
                    "sales_followup",
                    "order",
                    "short_video",
                    "live_session",
                },
                synthetic=request.synthetic,
            )
        except DatasetAccessError as exc:
            return self._analysis_error(
                request,
                service_run_id,
                tool_name,
                started,
                exc.code,
                exc.safe_message,
            )

        if request.link_orders:
            order_sets = [
                item for item in datasets if item.reference.dataset_type == "order"
            ]
            if not order_sets or not _has_stable_lead_key(datasets):
                return self._analysis_error(
                    request,
                    service_run_id,
                    tool_name,
                    started,
                    "RELATION_KEY_MISSING",
                    "订单关联需要 channel_lead 与 order 的稳定脱敏 lead_id_hash。",
                )
        if request.calculate_roi and not _roi_allowed(datasets):
            return self._analysis_error(
                request,
                service_run_id,
                tool_name,
                started,
                "COST_FIELD_MISSING",
                "未检测到成本字段且 ROI 未放行，禁止计算 ROI。",
            )

        leads = _concat(datasets, "channel_lead").drop_duplicates(
            subset=["lead_id_hash"]
        )
        lead_count = len(leads)
        run_token = uuid4().hex[:12]
        evidence = [
            _evidence(
                f"ev_lead_count_{run_token}",
                _first_dataset_id(datasets, "channel_lead"),
                service_run_id,
                "lead_count",
                lead_count,
                "rows",
                "count(distinct lead_id_hash)",
                "合成线索样例的脱敏线索数已按 lead_id_hash 去重。",
                _quality(datasets),
            )
        ]
        missing = _missing_dimensions(datasets, request.requested_dimensions)

        followups = [
            item
            for item in datasets
            if item.reference.dataset_type == "sales_followup"
        ]
        if followups:
            followup = _concat(datasets, "sales_followup").sort_values(
                "first_followup_at"
            ).drop_duplicates(subset=["lead_id_hash"])
            merged = leads[["lead_id_hash"]].merge(
                followup,
                on="lead_id_hash",
                how="left",
            )
            has_followup = merged["first_followup_at"].notna()
            hours = (
                merged["first_followup_at"] - merged["assigned_at"]
            ).dt.total_seconds() / 3600
            evidence.append(
                _evidence(
                    f"ev_followup_24h_{run_token}",
                    followups[0].reference.dataset_id,
                    service_run_id,
                    "first_followup_within_24h_rate",
                    _rate(int(((hours >= 0) & (hours <= 24)).sum()), lead_count),
                    "ratio",
                    "first_followup within 24h / all distinct leads",
                    "合成样例只描述首次跟进及时性，不评价个人能力。",
                    _quality(datasets),
                )
            )
            if int(has_followup.sum()) < lead_count:
                missing.append("部分线索缺少首次跟进记录")
        else:
            missing.append("未提供 sales_followup，无法计算首次跟进及时性")

        orders = [item for item in datasets if item.reference.dataset_type == "order"]
        if request.link_orders and orders:
            order = _concat(datasets, "order")
            paid_order = order[
                order["order_status"].astype(str).str.lower().isin(
                    {"paid", "completed", "已支付", "已完成"}
                )
            ]
            paid_leads = set(paid_order["lead_id_hash"].dropna())
            linked_leads = set(order["lead_id_hash"].dropna())
            evidence.extend(
                [
                    _evidence(
                        f"ev_order_link_{run_token}",
                        orders[0].reference.dataset_id,
                        service_run_id,
                        "order_link_coverage_rate",
                        _rate(len(linked_leads.intersection(set(leads["lead_id_hash"]))), lead_count),
                        "ratio",
                        "distinct linked lead ids / all distinct leads",
                        "仅在稳定脱敏 lead_id_hash 覆盖范围内计算订单关联。",
                        _quality(datasets),
                    ),
                    _evidence(
                        f"ev_paid_conversion_{run_token}",
                        orders[0].reference.dataset_id,
                        service_run_id,
                        "lead_to_paid_order_conversion_rate",
                        _rate(len(paid_leads.intersection(set(leads["lead_id_hash"]))), lead_count),
                        "ratio",
                        "distinct paid lead ids / all distinct leads",
                        "合成样例的支付转化率只用于确定性链路验证。",
                        _quality(datasets),
                    ),
                ]
            )

        findings = [
            Finding(
                finding_id=f"finding_attribution_{run_token}",
                category="attribution" if request.link_orders else "lead",
                severity="attention" if missing else "normal",
                statement=(
                    "合成样例已按渠道、线索、跟进和订单的稳定脱敏键形成覆盖范围内关联；"
                    "结果不证明因果关系，也不用于评价个人能力。"
                ),
                evidence_ids=[item.evidence_id for item in evidence],
                confidence=0.90,
                limitations=["synthetic=true", "关联不等于因果", *missing],
            )
        ]
        return self._analysis_success(
            request=request,
            datasets=datasets,
            service_run_id=service_run_id,
            tool_name=tool_name,
            domain="attribution_leads",
            analysis_prefix="analysis_attribution",
            evidence=evidence,
            findings=findings,
            missing=missing,
            started=started,
        )

    def drilldown_commerce_metric(
        self,
        request: DrilldownCommerceMetricRequest,
    ) -> DrilldownResult:
        started = perf_counter()
        service_run_id = _run_id("srv_drilldown")
        with self._lock:
            context = self._analyses.get(request.base_analysis_run_id)
        if context is None:
            return self._drilldown_error(
                request,
                service_run_id,
                started,
                "ANALYSIS_UNAVAILABLE",
                "base_analysis_run_id 不存在或不在当前进程中。",
            )
        packet = context.packet
        if packet.workflow_run_id != request.workflow_run_id:
            return self._drilldown_error(
                request,
                service_run_id,
                started,
                "INVALID_INPUT",
                "base analysis 与 workflow_run_id 不一致。",
            )
        if packet.agent_role != request.caller_role:
            return self._drilldown_error(
                request,
                service_run_id,
                started,
                "INVALID_INPUT",
                "drilldown 调用者必须与 base analysis 的 Agent role 一致。",
            )
        if packet.terminal_status not in {"completed", "partial"}:
            return self._drilldown_error(
                request,
                service_run_id,
                started,
                "DIAGNOSIS_INCOMPLETE",
                "base analysis 未完成，禁止钻取。",
            )
        if request.evidence_id not in {item.evidence_id for item in packet.evidence}:
            return self._drilldown_error(
                request,
                service_run_id,
                started,
                "INVALID_INPUT",
                "evidence_id 不属于 base analysis。",
            )

        datasets = self.store.get_many(
            request.workflow_run_id,
            list(context.dataset_ids),
        )
        candidate = next(
            (
                item
                for item in datasets
                if dimension_column(item.reference.dataset_type, request.dimension)
                in item.frame.columns
            ),
            None,
        )
        if candidate is None:
            return self._drilldown_error(
                request,
                service_run_id,
                started,
                "INVALID_INPUT",
                f"dimension={request.dimension} 未在 manifest 中声明。",
            )
        dimension_field = dimension_column(
            candidate.reference.dataset_type, request.dimension
        )
        assert dimension_field is not None
        allowed_filter_fields = {
            column
            for item in datasets
            for dimension in item.manifest.available_dimensions
            if (column := dimension_column(item.reference.dataset_type, dimension))
        }
        invalid_filters = set(request.filters) - allowed_filter_fields
        if invalid_filters:
            return self._drilldown_error(
                request,
                service_run_id,
                started,
                "INVALID_INPUT",
                f"filters 包含未授权字段：{', '.join(sorted(invalid_filters))}。",
            )
        frame = candidate.frame.copy()
        for field, value in request.filters.items():
            if field in frame:
                frame = frame[frame[field].astype(str) == value]
        rows = _drilldown_rows(
            packet.domain,
            frame,
            dimension_field,
            request.top_n,
        )
        if not rows:
            return self._drilldown_error(
                request,
                service_run_id,
                started,
                "DIAGNOSIS_INCOMPLETE",
                "筛选后没有可聚合的数据。",
            )
        quality = candidate.manifest.data_quality.status
        limitations = ["synthetic=true", "钻取不扩大关联或 ROI 权限"]
        return DrilldownResult(
            workflow_run_id=request.workflow_run_id,
            service_run_id=service_run_id,
            caller_role=request.caller_role,
            terminal_status="partial" if quality == "partial" else "completed",
            synthetic=request.synthetic,
            base_analysis_run_id=request.base_analysis_run_id,
            source_evidence_id=request.evidence_id,
            dimension=request.dimension,
            rows=rows,
            data_quality_status="partial" if quality == "partial" else "pass",
            limitations=limitations,
            duration_ms=_duration_ms(started),
        )

    def _datasets_for_analysis(
        self,
        workflow_run_id: str,
        dataset_ids: list[str],
        *,
        required_type: str,
        allowed_types: set[str],
        synthetic: bool,
    ) -> list[StoredDataset]:
        if len(dataset_ids) != len(set(dataset_ids)):
            raise DatasetAccessError("INVALID_INPUT", "dataset_ids 不能重复。")
        datasets = self.store.get_many(workflow_run_id, dataset_ids)
        actual_types = {item.reference.dataset_type for item in datasets}
        if required_type not in actual_types:
            raise DatasetAccessError(
                "ANALYSIS_UNAVAILABLE",
                f"分析必须包含 dataset_type={required_type}。",
            )
        unexpected = actual_types - allowed_types
        if unexpected:
            raise DatasetAccessError(
                "INVALID_INPUT",
                f"工具不能读取数据类型：{', '.join(sorted(unexpected))}。",
            )
        if any(item.manifest.data_quality.status == "blocked" for item in datasets):
            raise DatasetAccessError(
                "ANALYSIS_UNAVAILABLE",
                "存在 data_quality=blocked 的数据集，分析已停止。",
            )
        if not synthetic or any(not item.reference.synthetic for item in datasets):
            raise DatasetAccessError(
                "INVALID_INPUT",
                "当前阶段只允许 synthetic=true。",
            )
        return datasets

    def _analysis_success(
        self,
        *,
        request: Any,
        datasets: list[StoredDataset],
        service_run_id: str,
        tool_name: str,
        domain: str,
        analysis_prefix: str,
        evidence: list[Evidence],
        findings: list[Finding],
        missing: list[str],
        started: float,
    ) -> AnalysisToolResult:
        duration = _duration_ms(started)
        analysis_run_id = _run_id(analysis_prefix)
        terminal_status = "partial" if missing or _quality(datasets) == "partial" else "completed"
        packet = AnalysisPacket(
            workflow_run_id=request.workflow_run_id,
            analysis_run_id=analysis_run_id,
            agent_role=request.caller_role,
            domain=domain,
            terminal_status=terminal_status,
            dataset_ids=request.dataset_ids,
            service_calls=[
                ServiceCall(
                    tool_name=tool_name,
                    caller_role=request.caller_role,
                    attempt=1,
                    service_run_id=service_run_id,
                    outcome="success",
                    duration_ms=duration,
                    side_effect_state="none",
                    automatic_retry=False,
                )
            ],
            evidence=evidence,
            findings=findings,
            missing_evidence=missing,
            assumptions=[],
        )
        with self._lock:
            self._analyses[analysis_run_id] = AnalysisContext(
                packet=packet,
                dataset_ids=tuple(request.dataset_ids),
            )
        return AnalysisToolResult(
            workflow_run_id=request.workflow_run_id,
            service_run_id=service_run_id,
            tool_name=tool_name,
            caller_role=request.caller_role,
            terminal_status=terminal_status,
            synthetic=request.synthetic,
            analysis_packet=packet,
            duration_ms=duration,
        )

    def _analysis_error(
        self,
        request: Any,
        service_run_id: str,
        tool_name: str,
        started: float,
        code: str,
        safe_message: str,
    ) -> AnalysisToolResult:
        return AnalysisToolResult(
            workflow_run_id=request.workflow_run_id,
            service_run_id=service_run_id,
            tool_name=tool_name,
            caller_role=request.caller_role,
            terminal_status="blocked",
            synthetic=request.synthetic,
            workflow_error=_workflow_error(
                request.workflow_run_id,
                stage="analysis",
                code=code,
                safe_message=safe_message,
            ),
            duration_ms=_duration_ms(started),
        )

    def _drilldown_error(
        self,
        request: DrilldownCommerceMetricRequest,
        service_run_id: str,
        started: float,
        code: str,
        safe_message: str,
    ) -> DrilldownResult:
        return DrilldownResult(
            workflow_run_id=request.workflow_run_id,
            service_run_id=service_run_id,
            caller_role=request.caller_role,
            terminal_status="blocked",
            synthetic=request.synthetic,
            base_analysis_run_id=request.base_analysis_run_id,
            source_evidence_id=request.evidence_id,
            dimension=request.dimension,
            workflow_error=_workflow_error(
                request.workflow_run_id,
                stage="analysis",
                code=code,
                safe_message=safe_message,
            ),
            duration_ms=_duration_ms(started),
        )


def default_service() -> CommerceOpsService:
    project_root = Path(__file__).resolve().parents[1]
    return CommerceOpsService(project_root / "data" / "fixtures")


def _workflow_error(
    workflow_run_id: str,
    *,
    stage: str,
    code: str,
    safe_message: str,
) -> WorkflowError:
    human_actions = {
        "INVALID_INPUT": "按错误提示修正文件或参数后重新提交。",
        "PAYLOAD_TOO_LARGE": "拆分或压缩数据文件后重新提交。",
        "RELATION_KEY_MISSING": "补充稳定脱敏关联键或关闭跨域关联请求。",
        "COST_FIELD_MISSING": "补充已确认口径的成本字段，或关闭 ROI 请求。",
        "ANALYSIS_UNAVAILABLE": "先完成数据检查并补齐必需字段。",
        "ANALYSIS_OUTCOME_UNCERTAIN": "先按 run_id 核对，再由人工决定是否重跑。",
        "DIAGNOSIS_INCOMPLETE": "补齐缺失证据后重新执行对应分支。",
        "DECISION_BLOCKED": "人工复核诊断门槛后再进入策略阶段。",
        "DELIVERY_UNCERTAIN": "核对投递状态后再决定是否重试。",
    }
    return WorkflowError(
        workflow_run_id=workflow_run_id,
        stage=stage,
        code=code,
        retryable=False,
        outcome_uncertain=False,
        human_action=human_actions[code],
        safe_message=safe_message,
    )


def _run_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def _duration_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


def _concat(datasets: Iterable[StoredDataset], dataset_type: str) -> pd.DataFrame:
    frames = [
        item.frame
        for item in datasets
        if item.reference.dataset_type == dataset_type
    ]
    return pd.concat(frames, ignore_index=True)


def _first_dataset_id(datasets: list[StoredDataset], dataset_type: str) -> str:
    return next(
        item.reference.dataset_id
        for item in datasets
        if item.reference.dataset_type == dataset_type
    )


def _rate(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def _quality(datasets: list[StoredDataset]) -> str:
    return (
        "partial"
        if any(item.manifest.data_quality.status == "partial" for item in datasets)
        else "pass"
    )


def _evidence(
    evidence_id: str,
    dataset_id: str,
    service_run_id: str,
    metric_name: str,
    metric_value: int | float,
    unit: str,
    calculation: str,
    statement: str,
    quality: str,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        dataset_id=dataset_id,
        service_run_id=service_run_id,
        metric_name=metric_name,
        metric_value=metric_value,
        unit=unit,
        scope={"source": "synthetic"},
        calculation=calculation,
        statement=statement,
        synthetic=True,
        data_quality_status=quality,
    )


def _missing_dimensions(
    datasets: list[StoredDataset],
    requested_dimensions: list[str],
) -> list[str]:
    available = {
        dimension
        for item in datasets
        for dimension in item.manifest.available_dimensions
    }
    return [
        f"请求维度 {dimension} 在当前 manifest 中不可用"
        for dimension in requested_dimensions
        if dimension not in available
    ]


def _has_stable_lead_key(datasets: list[StoredDataset]) -> bool:
    relevant = {
        item.reference.dataset_type: any(
            key.field == "lead_id_hash"
            and key.stable
            and key.hashed
            and key.coverage_ratio > 0
            for key in item.manifest.relationship_keys
        )
        for item in datasets
        if item.reference.dataset_type in {"channel_lead", "order"}
    }
    return relevant.get("channel_lead", False) and relevant.get("order", False)


def _roi_allowed(datasets: list[StoredDataset]) -> bool:
    return any(
        field.semantic_role == "cost"
        for item in datasets
        for field in item.manifest.fields
    ) and any(
        item.manifest.analysis_readiness.roi_calculation == "allowed"
        for item in datasets
    )


def _drilldown_rows(
    domain: str,
    frame: pd.DataFrame,
    dimension_field: str,
    top_n: int,
) -> list[DrilldownRow]:
    if frame.empty or dimension_field not in frame:
        return []
    grouped = frame.groupby(dimension_field, dropna=False)
    rows: list[DrilldownRow] = []
    for value, group in grouped:
        if domain == "content_growth":
            plays = float(group["plays"].fillna(0).sum())
            metrics = {
                "impressions": int(group["impressions"].fillna(0).sum()),
                "plays": int(plays),
                "clicks": int(group["clicks"].fillna(0).sum()),
                "click_rate": _rate(group["clicks"].fillna(0).sum(), plays),
            }
        elif domain == "live_conversion":
            attended = int(group["attended"].fillna(False).sum())
            metrics = {
                "reservation_count": len(group),
                "attendance_rate": _rate(attended, len(group)),
                "purchase_rate": _rate(
                    int(group["ordered"].fillna(False).sum()), attended
                ),
            }
        else:
            metrics = {"row_count": len(group)}
        rows.append(
            DrilldownRow(
                dimension_value="<missing>" if pd.isna(value) else str(value),
                metrics=metrics,
            )
        )
    rows.sort(
        key=lambda item: float(
            item.metrics.get("impressions", item.metrics.get("row_count", item.metrics.get("reservation_count", 0)))
        ),
        reverse=True,
    )
    return rows[:top_n]
