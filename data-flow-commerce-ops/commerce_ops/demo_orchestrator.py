"""Deterministic orchestration used by the local product demonstration."""

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import RLock
from typing import Callable
from uuid import uuid4

from .demo_models import (
    DemoDatasetDescriptor,
    DemoRunRequest,
    DemoRunResult,
    DemoScenario,
    DemoScenarioCatalog,
    DemoSummaryMetric,
    DemoUploadedFile,
    DemoUploadRunRequest,
    DemoWorkflowStep,
)
from .models import (
    Action,
    AnalysisPacket,
    CommerceOpsRunRequest,
    DecisionPacket,
    DeliveryPackage,
    DeliveryRequirements,
    Domain,
    TimeRange,
    TraceReference,
    VerificationMetric,
)
from .service import CommerceOpsService
from .tool_models import (
    AttributionLeadAnalysisRequest,
    DataReference,
    DrilldownCommerceMetricRequest,
    InspectCommerceDataRequest,
    LiveCommerceAnalysisRequest,
    ShortVideoAnalysisRequest,
)


MAX_DEMO_FILES = 6
MAX_DEMO_TOTAL_BYTES = 50 * 1024 * 1024


class DemoInputError(ValueError):
    pass


class DemoRunNotFound(KeyError):
    pass


SAMPLE_REFERENCES = (
    DataReference(
        dataset_id="ds_video",
        dataset_type="short_video",
        file_path="short_video/synthetic-short-video.csv",
    ),
    DataReference(
        dataset_id="ds_live",
        dataset_type="live_session",
        file_path="live/synthetic-live-integration.csv",
    ),
    DataReference(
        dataset_id="ds_lead",
        dataset_type="channel_lead",
        file_path="leads/synthetic-channel-leads.csv",
    ),
    DataReference(
        dataset_id="ds_followup",
        dataset_type="sales_followup",
        file_path="followup/synthetic-sales-followup.csv",
    ),
    DataReference(
        dataset_id="ds_order",
        dataset_type="order",
        file_path="orders/synthetic-orders.csv",
    ),
)


FULL_SCENARIO = DemoScenario(
    scenario_id="full_commerce_funnel",
    name="全链路经营分析演示",
    description=(
        "使用五份合成数据演示短视频、直播、线索跟进、订单关联与复盘动作。"
    ),
    requested_domains=[
        "content_growth",
        "live_conversion",
        "attribution_leads",
    ],
    datasets=[
        DemoDatasetDescriptor(
            dataset_id=item.dataset_id,
            dataset_type=item.dataset_type,
            display_name={
                "short_video": "短视频内容数据",
                "live_session": "直播转化数据",
                "channel_lead": "渠道线索数据",
                "sales_followup": "销售跟进数据",
                "order": "订单数据",
            }[item.dataset_type],
            source_name=Path(item.file_path).name,
        )
        for item in SAMPLE_REFERENCES
    ],
)


DOMAIN_ROLES = {
    "content_growth": "content_growth_analyst",
    "live_conversion": "live_conversion_analyst",
    "attribution_leads": "attribution_lead_analyst",
}
DOMAIN_REQUIRED_TYPES = {
    "content_growth": "short_video",
    "live_conversion": "live_session",
    "attribution_leads": "channel_lead",
}
DOMAIN_ALLOWED_TYPES = {
    "content_growth": {"short_video", "account", "channel_lead"},
    "live_conversion": {"live_session", "account", "channel_lead", "order"},
    "attribution_leads": {
        "channel_lead",
        "sales_followup",
        "order",
        "short_video",
        "live_session",
    },
}
DOMAIN_DIMENSIONS = {
    "content_growth": ["account", "content"],
    "live_conversion": ["live_session", "channel"],
    "attribution_leads": [
        "channel",
        "lead_source",
        "sales_owner",
        "order_status",
    ],
}
DOMAIN_DRILLDOWN_DIMENSION = {
    "content_growth": "content",
    "live_conversion": "live_session",
    "attribution_leads": "channel",
}


class DemoOrchestrator:
    def __init__(
        self,
        data_root: Path,
        *,
        upload_root: Path | None = None,
        max_saved_runs: int = 20,
    ) -> None:
        self.data_root = data_root.resolve()
        project_root = Path(__file__).resolve().parents[1]
        self.upload_root = (
            upload_root or project_root / "runtime" / "demo-uploads"
        ).resolve()
        self.max_saved_runs = max_saved_runs
        self._runs: OrderedDict[str, DemoRunResult] = OrderedDict()
        self._lock = RLock()

    def scenarios(self) -> DemoScenarioCatalog:
        return DemoScenarioCatalog(
            scenarios=[FULL_SCENARIO],
            default_scenario_id=FULL_SCENARIO.scenario_id,
        )

    def run_sample(self, request: DemoRunRequest) -> DemoRunResult:
        selected_ids = {
            item.dataset_id
            for domain in request.requested_domains
            for item in self._references_for_domain(SAMPLE_REFERENCES, domain)
        }
        references = [
            item for item in SAMPLE_REFERENCES if item.dataset_id in selected_ids
        ]
        scenario = FULL_SCENARIO.model_copy(
            update={
                "requested_domains": request.requested_domains,
                "datasets": [
                    item
                    for item in FULL_SCENARIO.datasets
                    if item.dataset_id in selected_ids
                ],
            }
        )
        return self._run(
            CommerceOpsService(self.data_root),
            scenario=scenario,
            references=references,
            requested_domains=request.requested_domains,
            objective=request.objective,
            top_n=request.top_n,
            include_drilldowns=request.include_drilldowns,
        )

    def run_upload(
        self,
        request: DemoUploadRunRequest,
        files: list[DemoUploadedFile],
    ) -> DemoRunResult:
        self._validate_upload_request(request, files)
        self.upload_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(
            prefix="commerce-demo-",
            dir=self.upload_root,
        ) as temp_directory:
            temp_root = Path(temp_directory)
            references: list[DataReference] = []
            descriptors: list[DemoDatasetDescriptor] = []
            for spec in request.datasets:
                uploaded = files[spec.file_index]
                safe_name = self._safe_file_name(
                    spec.file_index,
                    uploaded.file_name,
                )
                (temp_root / safe_name).write_bytes(uploaded.content)
                references.append(
                    DataReference(
                        dataset_id=spec.dataset_id,
                        dataset_type=spec.dataset_type,
                        file_path=safe_name,
                    )
                )
                descriptors.append(
                    DemoDatasetDescriptor(
                        dataset_id=spec.dataset_id,
                        dataset_type=spec.dataset_type,
                        display_name=spec.display_name,
                        source_name=Path(uploaded.file_name).name,
                    )
                )
            scenario = DemoScenario(
                scenario_id="uploaded_synthetic_data",
                name="上传数据演示",
                description=(
                    "使用用户提供且声明为 synthetic=true 的表格执行本地确定性分析。"
                ),
                requested_domains=request.requested_domains,
                datasets=descriptors,
            )
            return self._run(
                CommerceOpsService(temp_root),
                scenario=scenario,
                references=references,
                requested_domains=request.requested_domains,
                objective=request.objective,
                top_n=request.top_n,
                include_drilldowns=request.include_drilldowns,
            )

    def get_run(self, workflow_run_id: str) -> DemoRunResult:
        with self._lock:
            result = self._runs.get(workflow_run_id)
        if result is None:
            raise DemoRunNotFound(workflow_run_id)
        return result.model_copy(deep=True)

    def _run(
        self,
        service: CommerceOpsService,
        *,
        scenario: DemoScenario,
        references: list[DataReference],
        requested_domains: list[Domain],
        objective: str,
        top_n: int,
        include_drilldowns: bool,
    ) -> DemoRunResult:
        self._validate_required_types(references, requested_domains)
        started_at = datetime.now(timezone.utc)
        run_token = uuid4().hex[:16]
        workflow_run_id = f"wf_demo_{run_token}"
        steps: list[DemoWorkflowStep] = [
            DemoWorkflowStep(
                step_id=f"step_route_{run_token}",
                actor_role="commerce_ops_supervisor",
                stage="route",
                terminal_status="completed",
                label="拆解经营分析任务",
                dataset_ids=[item.dataset_id for item in references],
                detail=(
                    "本地编排器按数据类型将任务路由到三个专业角色；"
                    "此步骤不运行 MiniClaw AgentSession。"
                ),
            )
        ]
        manifests = {}
        packets: list[AnalysisPacket] = []
        drilldowns = []
        unresolved: list[str] = []

        for domain in requested_domains:
            role = DOMAIN_ROLES[domain]
            domain_references = self._references_for_domain(references, domain)
            inspection = service.inspect_commerce_data(
                InspectCommerceDataRequest(
                    workflow_run_id=workflow_run_id,
                    caller_role=role,
                    data_refs=domain_references,
                    requested_domains=[domain],
                )
            )
            for manifest in inspection.dataset_manifests:
                manifests[manifest.dataset_id] = manifest
            steps.append(
                DemoWorkflowStep(
                    step_id=f"step_inspect_{domain}_{run_token}",
                    actor_role=role,
                    stage="inspect",
                    terminal_status=inspection.terminal_status,
                    label=f"{self._domain_name(domain)}数据检查",
                    dataset_ids=[item.dataset_id for item in domain_references],
                    service_run_id=inspection.service_run_id,
                    duration_ms=inspection.duration_ms,
                    detail=(
                        "执行字段、数据质量、关联键与分析放行条件检查。"
                    ),
                )
            )
            if inspection.terminal_status == "blocked":
                unresolved.extend(inspection.missing_evidence)
                continue

            analysis = self._analyze(
                service,
                domain,
                workflow_run_id,
                [item.dataset_id for item in domain_references],
                top_n,
            )
            steps.append(
                DemoWorkflowStep(
                    step_id=f"step_analyze_{domain}_{run_token}",
                    actor_role=role,
                    stage="analyze",
                    terminal_status=analysis.terminal_status,
                    label=f"{self._domain_name(domain)}经营诊断",
                    dataset_ids=[item.dataset_id for item in domain_references],
                    service_run_id=analysis.service_run_id,
                    analysis_run_id=(
                        analysis.analysis_packet.analysis_run_id
                        if analysis.analysis_packet is not None
                        else None
                    ),
                    duration_ms=analysis.duration_ms,
                    detail=(
                        "调用确定性指标服务生成 evidence 与 finding；"
                        "没有模型推理或自动重试。"
                    ),
                )
            )
            if analysis.analysis_packet is None:
                if analysis.workflow_error is not None:
                    unresolved.append(analysis.workflow_error.safe_message)
                continue
            packet = analysis.analysis_packet
            packets.append(packet)
            unresolved.extend(packet.missing_evidence)

            if include_drilldowns and packet.evidence:
                drilldown = service.drilldown_commerce_metric(
                    DrilldownCommerceMetricRequest(
                        workflow_run_id=workflow_run_id,
                        caller_role=role,
                        base_analysis_run_id=packet.analysis_run_id,
                        evidence_id=packet.evidence[0].evidence_id,
                        dimension=DOMAIN_DRILLDOWN_DIMENSION[domain],
                        top_n=top_n,
                    )
                )
                drilldowns.append(drilldown)
                steps.append(
                    DemoWorkflowStep(
                        step_id=f"step_drilldown_{domain}_{run_token}",
                        actor_role=role,
                        stage="drilldown",
                        terminal_status=drilldown.terminal_status,
                        label=f"{self._domain_name(domain)}维度钻取",
                        dataset_ids=packet.dataset_ids,
                        service_run_id=drilldown.service_run_id,
                        analysis_run_id=packet.analysis_run_id,
                        duration_ms=drilldown.duration_ms,
                        detail=(
                            f"按 {DOMAIN_DRILLDOWN_DIMENSION[domain]} 维度展示 Top {top_n}。"
                        ),
                    )
                )
                if drilldown.workflow_error is not None:
                    unresolved.append(drilldown.workflow_error.safe_message)

        missing_manifests = [
            item.dataset_id
            for item in references
            if item.dataset_id not in manifests
        ]
        if missing_manifests:
            raise DemoInputError(
                "以下数据集未通过文件或字段检查："
                + "、".join(missing_manifests)
            )
        if not packets:
            raise DemoInputError(
                "所有请求域均未通过数据检查或分析门槛，无法生成演示报告。"
            )

        decision = self._build_decision(workflow_run_id, packets, run_token)
        unresolved.extend(decision.blocked_reasons)
        unresolved = list(dict.fromkeys(item for item in unresolved if item))
        steps.append(
            DemoWorkflowStep(
                step_id=f"step_decision_{run_token}",
                actor_role="commerce_review_strategist",
                stage="decision",
                terminal_status=decision.terminal_status,
                label="形成复盘行动与复验指标",
                dataset_ids=[item.dataset_id for item in references],
                detail=(
                    "使用确定性规则模板把 finding 转换为 action 与 verification_metric；"
                    "不代表策略 Agent 已进行模型推理。"
                ),
            )
        )
        delivery = self._build_delivery(
            workflow_run_id,
            packets,
            decision,
            unresolved,
            run_token,
        )
        steps.append(
            DemoWorkflowStep(
                step_id=f"step_delivery_{run_token}",
                actor_role="commerce_ops_supervisor",
                stage="delivery",
                terminal_status=delivery.terminal_status,
                label="汇总可追溯经营报告",
                dataset_ids=[item.dataset_id for item in references],
                detail=(
                    "保留 run_id、分析引用、证据引用、未解决事项和人工确认边界。"
                ),
            )
        )
        normalized_request = self._normalized_request(
            workflow_run_id,
            objective,
            references,
            requested_domains,
            top_n,
            started_at,
        )
        completed_at = datetime.now(timezone.utc)
        result = DemoRunResult(
            workflow_run_id=workflow_run_id,
            started_at=started_at,
            completed_at=completed_at,
            terminal_status=delivery.terminal_status,
            scenario=scenario,
            normalized_request=normalized_request,
            dataset_manifests=list(manifests.values()),
            analysis_packets=packets,
            drilldowns=drilldowns,
            decision_packet=decision,
            delivery_package=delivery,
            workflow_steps=steps,
            summary_metrics=[
                DemoSummaryMetric(
                    domain=packet.domain,
                    metric_name=evidence.metric_name,
                    metric_value=evidence.metric_value,
                    unit=evidence.unit,
                    evidence_id=evidence.evidence_id,
                )
                for packet in packets
                for evidence in packet.evidence
            ],
            unresolved_items=unresolved,
            evidence_boundaries=[
                "本次结果来自本地确定性服务，provider_called=false。",
                "角色时间线是功能演示编排，不是新的 MiniClaw AgentSession 轨迹。",
                "所有输入均为 synthetic=true，不代表真实经营结果。",
                "策略动作由规则模板生成，必须由业务人员确认后使用。",
            ],
        )
        self._save_run(result)
        return result.model_copy(deep=True)

    @staticmethod
    def _analyze(
        service: CommerceOpsService,
        domain: Domain,
        workflow_run_id: str,
        dataset_ids: list[str],
        top_n: int,
    ):
        if domain == "content_growth":
            return service.analyze_short_video_data(
                ShortVideoAnalysisRequest(
                    workflow_run_id=workflow_run_id,
                    dataset_ids=dataset_ids,
                    requested_dimensions=DOMAIN_DIMENSIONS[domain],
                    top_n=top_n,
                )
            )
        if domain == "live_conversion":
            return service.analyze_live_commerce_data(
                LiveCommerceAnalysisRequest(
                    workflow_run_id=workflow_run_id,
                    dataset_ids=dataset_ids,
                    requested_dimensions=DOMAIN_DIMENSIONS[domain],
                    top_n=top_n,
                )
            )
        return service.analyze_attribution_and_leads(
            AttributionLeadAnalysisRequest(
                workflow_run_id=workflow_run_id,
                dataset_ids=dataset_ids,
                requested_dimensions=DOMAIN_DIMENSIONS[domain],
                top_n=top_n,
                link_orders=any(
                    service.store.get(workflow_run_id, item).reference.dataset_type
                    == "order"
                    for item in dataset_ids
                ),
                calculate_roi=False,
            )
        )

    @staticmethod
    def _build_decision(
        workflow_run_id: str,
        packets: list[AnalysisPacket],
        run_token: str,
    ) -> DecisionPacket:
        actions = [
            DemoOrchestrator._action_for_packet(packet, run_token)
            for packet in packets
            if packet.findings and packet.evidence
        ]
        blocked_reasons = list(
            dict.fromkeys(
                item
                for packet in packets
                for item in packet.missing_evidence
            )
        )
        terminal_status = (
            "partial"
            if blocked_reasons
            or any(packet.terminal_status == "partial" for packet in packets)
            else "completed"
        )
        return DecisionPacket(
            workflow_run_id=workflow_run_id,
            decision_run_id=f"decision_demo_{run_token}",
            source_analysis_ids=[item.analysis_run_id for item in packets],
            terminal_status=terminal_status,
            actions=actions,
            blocked_reasons=blocked_reasons,
        )

    @staticmethod
    def _action_for_packet(packet: AnalysisPacket, run_token: str) -> Action:
        finding = packet.findings[0]
        evidence_by_id = {item.evidence_id: item for item in packet.evidence}
        evidence = evidence_by_id[finding.evidence_ids[0]]
        templates = {
            "content_growth": {
                "action": (
                    "复核高曝光内容的封面、标题与承接入口，并在下一批同口径内容中做对照。"
                ),
                "owner": "内容运营",
                "due": "下一批内容发布前",
                "guardrails": [
                    "不得承诺未经对照验证的提升幅度。",
                    "不得将合成阈值解释为真实账号行业标准。",
                ],
            },
            "live_conversion": {
                "action": (
                    "按场次复核到课、商品访问与购买漏斗，再确定需要调整的直播节点。"
                ),
                "owner": "直播运营",
                "due": "下一场直播方案确认前",
                "guardrails": [
                    "没有可比场次时只记录，不下趋势结论。",
                    "不得把漏斗现象直接归因于单一执行动作。",
                ],
            },
            "attribution_leads": {
                "action": (
                    "补齐未覆盖的线索跟进证据并核对稳定关联键，再复算线索至订单转化。"
                ),
                "owner": "渠道与销售运营",
                "due": "本次复盘后两个工作日内",
                "guardrails": [
                    "不得根据线索数量直接评价个人能力。",
                    "没有成本字段时不得计算 ROI。",
                ],
            },
        }
        template = templates[packet.domain]
        return Action(
            action_id=f"action_{packet.domain}_{run_token}",
            priority=(
                "high"
                if finding.severity in {"attention", "critical"}
                else "medium"
            ),
            finding_ids=[finding.finding_id],
            evidence_ids=list(finding.evidence_ids),
            action=template["action"],
            owner_role=template["owner"],
            due_window=template["due"],
            rationale=(
                "动作只引用已生成的 finding 与 evidence，不把待验证原因写成事实。"
            ),
            verification_metric=VerificationMetric(
                name=evidence.metric_name,
                direction=(
                    "increase"
                    if finding.severity in {"attention", "critical"}
                    else "observe"
                ),
                baseline=evidence.metric_value,
                target=None,
                unit=evidence.unit,
                check_after=template["due"],
                verification_method=(
                    "使用相同数据口径重新计算，并将新结果与本次 synthetic 基线分开记录。"
                ),
                dataset_ids=list(
                    dict.fromkeys(
                        evidence_by_id[item].dataset_id
                        for item in finding.evidence_ids
                    )
                ),
                requires_cost_data=False,
            ),
            guardrails=template["guardrails"],
            confidence=min(finding.confidence, 0.85),
        )

    @staticmethod
    def _build_delivery(
        workflow_run_id: str,
        packets: list[AnalysisPacket],
        decision: DecisionPacket,
        unresolved: list[str],
        run_token: str,
    ) -> DeliveryPackage:
        status = (
            "partial"
            if unresolved or decision.terminal_status == "partial"
            else "completed"
        )
        domain_names = "、".join(
            DemoOrchestrator._domain_name(item.domain) for item in packets
        )
        return DeliveryPackage(
            workflow_run_id=workflow_run_id,
            terminal_status=status,
            analysis_refs=[item.analysis_run_id for item in packets],
            decision_ref=decision.decision_run_id,
            headline=f"合成演示已完成{domain_names}诊断与行动复验设计",
            executive_summary=(
                "本报告由本地确定性服务生成，用于展示角色分工、工具调用和证据引用；"
                "不代表本次运行了真实模型或获得真实经营收益。"
            ),
            finding_refs=[
                finding.finding_id
                for packet in packets
                for finding in packet.findings
            ],
            action_refs=[item.action_id for item in decision.actions],
            unresolved_items=unresolved,
            trace_refs=[
                TraceReference(
                    trace_id=f"trace_supervisor_{run_token}",
                    actor_role="commerce_ops_supervisor",
                    run_id=workflow_run_id,
                ),
                *[
                    TraceReference(
                        trace_id=f"trace_{packet.domain}_{run_token}",
                        actor_role=packet.agent_role,
                        run_id=packet.analysis_run_id,
                        parent_run_id=workflow_run_id,
                    )
                    for packet in packets
                ],
                TraceReference(
                    trace_id=f"trace_strategy_{run_token}",
                    actor_role="commerce_review_strategist",
                    run_id=decision.decision_run_id,
                    parent_run_id=workflow_run_id,
                ),
            ],
            requires_human_confirmation=True,
        )

    @staticmethod
    def _normalized_request(
        workflow_run_id: str,
        objective: str,
        references: list[DataReference],
        requested_domains: list[Domain],
        top_n: int,
        requested_at: datetime,
    ) -> CommerceOpsRunRequest:
        return CommerceOpsRunRequest(
            workflow_run_id=workflow_run_id,
            requested_at=requested_at,
            objective=objective,
            dataset_refs=[item.dataset_id for item in references],
            requested_domains=requested_domains,
            requested_dimensions=list(
                dict.fromkeys(
                    dimension
                    for domain in requested_domains
                    for dimension in DOMAIN_DIMENSIONS[domain]
                )
            ),
            time_range=TimeRange(
                start=requested_at - timedelta(days=7),
                end=requested_at,
            ),
            delivery=DeliveryRequirements(
                language="zh-CN",
                format="web_report",
                top_n=top_n,
                include_actions=True,
            ),
            constraints=[
                "所有输入必须为 synthetic=true。",
                "没有稳定关联键时不得进行跨域归因。",
                "没有成本字段时不得计算 ROI。",
                "本地确定性演示不得表述为真实 AgentSession。",
            ],
            synthetic=True,
        )

    @staticmethod
    def _references_for_domain(
        references: tuple[DataReference, ...] | list[DataReference],
        domain: Domain,
    ) -> list[DataReference]:
        return [
            item
            for item in references
            if item.dataset_type in DOMAIN_ALLOWED_TYPES[domain]
        ]

    @staticmethod
    def _validate_required_types(
        references: list[DataReference],
        requested_domains: list[Domain],
    ) -> None:
        actual_types = {item.dataset_type for item in references}
        missing = [
            DOMAIN_REQUIRED_TYPES[domain]
            for domain in requested_domains
            if DOMAIN_REQUIRED_TYPES[domain] not in actual_types
        ]
        if missing:
            raise DemoInputError(
                "请求域缺少必需数据类型：" + "、".join(dict.fromkeys(missing))
            )

    @staticmethod
    def _validate_upload_request(
        request: DemoUploadRunRequest,
        files: list[DemoUploadedFile],
    ) -> None:
        if len(files) > MAX_DEMO_FILES:
            raise DemoInputError(f"上传文件不能超过 {MAX_DEMO_FILES} 个。")
        if sum(len(item.content) for item in files) > MAX_DEMO_TOTAL_BYTES:
            raise DemoInputError("上传文件总大小不能超过 50 MB。")
        indexes = {item.file_index for item in request.datasets}
        if indexes != set(range(len(files))):
            raise DemoInputError(
                "datasets.file_index 必须与上传文件按 0 开始连续一一对应。"
            )
        allowed_types = {
            dataset_type
            for domain in request.requested_domains
            for dataset_type in DOMAIN_ALLOWED_TYPES[domain]
        }
        unused_types = [
            item.dataset_type
            for item in request.datasets
            if item.dataset_type not in allowed_types
        ]
        if unused_types:
            raise DemoInputError(
                "上传数据类型不属于所选分析域："
                + "、".join(dict.fromkeys(unused_types))
            )

    @staticmethod
    def _safe_file_name(index: int, file_name: str) -> str:
        base_name = Path(file_name).name
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", base_name).strip("._")
        if not normalized:
            normalized = f"dataset_{index}.csv"
        return f"{index:02d}_{normalized}"

    @staticmethod
    def _domain_name(domain: Domain) -> str:
        return {
            "content_growth": "内容增长",
            "live_conversion": "直播转化",
            "attribution_leads": "渠道线索归因",
        }[domain]

    def _save_run(self, result: DemoRunResult) -> None:
        with self._lock:
            self._runs[result.workflow_run_id] = result.model_copy(deep=True)
            self._runs.move_to_end(result.workflow_run_id)
            while len(self._runs) > self.max_saved_runs:
                self._runs.popitem(last=False)
