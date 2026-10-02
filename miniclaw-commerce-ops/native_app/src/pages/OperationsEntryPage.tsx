import { lazy, Suspense, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuthStore } from "@/stores/auth";
import {
  ArrowLeft, ArrowRight, BarChart3, CheckCircle2, ChevronRight,
  Clock3, Database, FileSpreadsheet, Layers3, ListChecks, LoaderCircle, PlayCircle,
  MessageCircle, Plug, RefreshCw, ShieldCheck, Sparkles, Target, X,
} from "lucide-react";
import {
  operationDomains,
  type AnalysisRequest, type AvailableDataSource, type ConnectorType,
  type OperationDomainId, type OperationsSnapshot, type OperationsTask, type Priority,
} from "../operationsContracts";
import { operationsApiService } from "../operationsApiService";
import { WorkspaceDialog } from "../components/WorkspaceDialog";

const VisualizationsPage = lazy(() => import("./VisualizationsPage"));
const ConversationsPage = lazy(() => import("./ConversationsPage"));

type LoadState =
  | { status: "loading" }
  | { status: "ready"; snapshot: OperationsSnapshot }
  | { status: "error"; message: string };

const priorityLabels: Record<Priority, string> = { high: "高优先级", medium: "中优先级", low: "低优先级" };

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "运营服务请求失败，请稍后重试。";
}

function TaskStatus({ task }: { task: OperationsTask }) {
  const label = task.resultState === "processing" ? "分析进行中"
    : task.status === "uncertain" ? "提交待确认"
    : task.resultState === "unavailable" ? "执行异常"
    : task.status === "partial" ? "部分分析完成" : "分析完成";
  const tone = task.resultState === "processing" ? "is-processing"
    : task.status === "uncertain" ? ""
    : task.resultState === "unavailable" ? "is-error"
    : task.status === "partial" ? "" : "is-ready";
  return <span className={`df-status-pill ${tone}`}>
    {task.resultState === "processing" ? <LoaderCircle className="df-spin" size={14} /> : <ListChecks size={14} />}{label}
  </span>;
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(value));
}

function domainLabel(domainId: OperationDomainId): string {
  return operationDomains.find((domain) => domain.id === domainId)?.label ?? domainId;
}

function totalRecords(source: AvailableDataSource): number {
  return source.datasets.reduce((sum, dataset) => sum + dataset.records, 0);
}

function EmptyMessage({ children }: { children: string }) {
  return <div className="df-empty-message"><ListChecks size={22} /><p>{children}</p></div>;
}

function WorkspaceHeader({ eyebrow, title, description, action }: {
  eyebrow: string; title: string; description: string; action?: ReactNode;
}) {
  return (
    <header className="df-workspace-header">
      <div><p className="df-eyebrow">{eyebrow}</p><h1>{title}</h1><p className="df-page-description">{description}</p></div>
      {action}
    </header>
  );
}

function Overview({ snapshot }: { snapshot: OperationsSnapshot }) {
  const source = snapshot.sources[0];
  const latestTask = snapshot.tasks[0];
  const stats = [
    { label: "可用数据源", value: String(snapshot.sources.filter((item) => item.status === "ready").length), detail: "已通过读取校验", icon: Database },
    { label: "最近分析任务", value: String(snapshot.tasks.length), detail: "最近 20 项任务记录", icon: ListChecks },
    { label: "本期数据记录", value: source ? String(totalRecords(source)) : "0", detail: source?.periodLabel ?? "当前周期", icon: Layers3 },
    { label: "建议行动", value: String(latestTask?.result.actions.length ?? 0), detail: "来自最近一次分析", icon: Target },
  ];
  return (
    <>
      <WorkspaceHeader eyebrow="运营中心" title="运营概览" description="查看数据状态、最近分析与需要跟进的行动。" action={
        <Link className="df-primary-button" to="/operations/analysis"><Sparkles size={17} />新建分析</Link>
      } />
      <section className="df-stat-grid" aria-label="工作台概览">
        {stats.map(({ label, value, detail, icon: Icon }) => (
          <article className="df-stat-card" key={label}><div className="df-stat-icon"><Icon size={19} /></div><p>{label}</p><strong>{value}</strong><span>{detail}</span></article>
        ))}
      </section>
      <section className="df-overview-grid">
        <article className="df-feature-card df-feature-card-main">
          <div className="df-card-heading"><div><p className="df-eyebrow">运营分析</p><h2>发起一次经营复盘</h2></div><div className="df-feature-mark"><BarChart3 size={23} /></div></div>
          <p>选择数据源和分析范围，系统会把关键发现整理成指标、证据与可执行行动。</p>
          <div className="df-domain-pills">{operationDomains.map((domain) => <span key={domain.id}>{domain.label}</span>)}</div>
          <Link className="df-primary-button" to="/operations/analysis">配置本次分析 <ArrowRight size={16} /></Link>
        </article>
        <article className="df-feature-card">
          <div className="df-card-heading"><div><p className="df-eyebrow">当前数据</p><h2>{source?.name ?? "数据源"}</h2></div>{source && <span className={`df-status-pill ${source.status === "ready" ? "is-ready" : ""}`}><CheckCircle2 size={14} />{source.statusLabel}</span>}</div>
          {source ? <>
            <dl className="df-compact-list"><div><dt>数据周期</dt><dd>{source.periodLabel}</dd></div><div><dt>数据规模</dt><dd>{source.datasets.length} 类 · {totalRecords(source)} 条</dd></div><div><dt>接入类型</dt><dd>{source.typeLabel}</dd></div></dl>
            <Link className="df-text-link" to="/operations/data-sources">查看数据明细 <ChevronRight size={15} /></Link>
          </> : <EmptyMessage>当前没有可用数据源</EmptyMessage>}
        </article>
      </section>
      <section className="df-section-block">
        <div className="df-section-heading"><div><p className="df-eyebrow">最近活动</p><h2>分析任务</h2></div><Link className="df-text-link" to="/operations/tasks">查看全部 <ChevronRight size={15} /></Link></div>
        <TaskTable tasks={snapshot.tasks.slice(0, 3)} />
      </section>
    </>
  );
}

function AnalysisWorkspace({ snapshot, onCreated }: { snapshot: OperationsSnapshot; onCreated: (task: OperationsTask) => void }) {
  const navigate = useNavigate();
  const [title, setTitle] = useState("电商经营分析");
  const [objective, setObjective] = useState("梳理内容、直播、线索到订单的关键表现，并给出下一周期行动建议。");
  const [sourceId, setSourceId] = useState(snapshot.sources[0]?.id ?? "");
  const [domains, setDomains] = useState<OperationDomainId[]>(operationDomains.map((domain) => domain.id));
  const [includeStrategy, setIncludeStrategy] = useState(true);
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [feeConfirmed, setFeeConfirmed] = useState(false);
  const [hasPending, setHasPending] = useState(() => operationsApiService.hasPendingSubmission());
  const source = snapshot.sources.find((item) => item.id === sourceId);
  const canSubmit = snapshot.ready && !submitting && title.trim().length > 0 && objective.trim().length > 0
    && source?.status === "ready" && domains.length > 0 && domains.every((domain) => source.supportedDomains.includes(domain));

  const toggleDomain = (domain: OperationDomainId) => {
    setDomains((current) => current.includes(domain) ? current.filter((item) => item !== domain) : [...current, domain]);
  };
  const submitForm = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); if (canSubmit) { setFeeConfirmed(false); setShowConfirmation(true); } };
  const createTask = async () => {
    if (submitting || !feeConfirmed || !canSubmit) return;
    setSubmitting(true); setError("");
    const request: AnalysisRequest = { title, objective, sourceId, requestedDomains: domains, includeStrategy };
    try {
      const task = await operationsApiService.createAnalysis(request);
      onCreated(task);
      navigate(`/operations/tasks/${task.taskReference}`);
    } catch (error) {
      setError(errorMessage(error)); setSubmitting(false); setShowConfirmation(false);
      if (useAuthStore.getState().authenticated) setHasPending(operationsApiService.hasPendingSubmission());
    }
  };
  const recoverTask = async () => {
    setSubmitting(true); setError("");
    try {
      const task = await operationsApiService.recoverSubmission();
      onCreated(task); navigate(`/operations/tasks/${task.taskReference}`);
    } catch (error) { setError(errorMessage(error)); }
    finally { setSubmitting(false); }
  };

  return (
    <>
      <WorkspaceHeader eyebrow="分析配置" title="新建运营分析" description="明确业务目标和分析范围，生成可追踪的发现与行动清单。" />
      <form className="df-analysis-layout" onSubmit={submitForm}>
        <div className="df-form-stack">
          <section className="df-form-card">
            <div className="df-step-heading"><span>01</span><div><h2>任务信息</h2><p>为本次分析设置清晰的业务目标。</p></div></div>
            <label className="df-field"><span>任务名称</span><input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={60} /></label>
            <label className="df-field"><span>分析目标</span><textarea value={objective} onChange={(event) => setObjective(event.target.value)} rows={4} maxLength={300} /><small>{objective.length} / 300</small></label>
          </section>
          <section className="df-form-card">
            <div className="df-step-heading"><span>02</span><div><h2>数据范围</h2><p>选择已通过读取校验的数据源。</p></div></div>
            <label className="df-field"><span>数据源</span><select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>{snapshot.sources.map((item) => <option value={item.id} key={item.id} disabled={item.status !== "ready"}>{item.name} · {item.periodLabel}</option>)}</select></label>
            {source && <div className="df-source-inline"><FileSpreadsheet size={18} /><div><strong>{source.datasets.length} 类 · {totalRecords(source)} 条记录</strong><span>{source.typeLabel} · 合成测试数据</span></div><CheckCircle2 size={18} /></div>}
          </section>
          <section className="df-form-card">
            <div className="df-step-heading"><span>03</span><div><h2>分析范围</h2><p>至少选择一个运营领域。</p></div></div>
            <div className="df-domain-select-grid">
              {operationDomains.map((domain) => {
                const selected = domains.includes(domain.id);
                return <button type="button" className={selected ? "is-selected" : ""} onClick={() => toggleDomain(domain.id)} aria-pressed={selected} key={domain.id}>
                  <span className="df-check-box">{selected && <CheckCircle2 size={17} />}</span><strong>{domain.label}</strong><small>{domain.description}</small>
                </button>;
              })}
            </div>
            <label className="df-toggle-row"><span><strong>生成行动建议</strong><small>在分析结果中包含负责人、完成时间和验证方式。</small></span><input type="checkbox" checked={includeStrategy} onChange={(event) => setIncludeStrategy(event.target.checked)} /></label>
          </section>
        </div>
        <aside className="df-analysis-summary">
          <p className="df-eyebrow">提交前核对</p><h2>任务摘要</h2>
          <dl><div><dt>数据源</dt><dd>{source?.name ?? "—"}</dd></div><div><dt>数据周期</dt><dd>{source?.periodLabel ?? "—"}</dd></div><div><dt>分析领域</dt><dd>{domains.length} 个</dd></div><div><dt>行动建议</dt><dd>{includeStrategy ? "包含" : "不包含"}</dd></div></dl>
          <div className="df-summary-domains">{domains.map((domain) => <span key={domain}>{domainLabel(domain)}</span>)}</div>
          <div className="df-test-note"><ShieldCheck size={17} /><p>当前使用合成测试数据。提交后将调用 MiniClaw 已配置的模型，可能产生费用；系统不会自动重试模型调用。</p></div>
          {!snapshot.ready && <p className="df-form-error">请先启动完整的原生运行服务。</p>}
          {hasPending && <div role="status"><p>上次提交尚待确认。请先查询任务；再次确认提交会复用同一提交编号。</p><button className="df-secondary-button" type="button" onClick={recoverTask} disabled={submitting}>查询上次提交</button></div>}
          {error && <p className="df-form-error" role="alert">{error}</p>}
          <button className="df-primary-button df-full-button" type="submit" disabled={!canSubmit}><PlayCircle size={17} />生成分析结果</button>
        </aside>
      </form>
      <WorkspaceDialog open={showConfirmation} onClose={() => setShowConfirmation(false)} busy={submitting} titleId="confirm-title" className="df-confirm-dialog">
          <button className="df-icon-button df-dialog-close" type="button" aria-label="关闭" onClick={() => setShowConfirmation(false)} disabled={submitting}><X size={19} /></button>
          <div className="df-dialog-mark"><Sparkles size={25} /></div><p className="df-eyebrow">执行确认</p><h2 id="confirm-title">生成本次运营分析</h2>
          <p>系统将使用“{source?.name}”整理 {domains.length} 个分析领域，并生成结构化结果。</p>
          <div className="df-dialog-facts"><span><Database size={15} />{source?.periodLabel}</span><span><BarChart3 size={15} />{domains.map(domainLabel).join("、")}</span></div>
          <label className="df-dialog-note"><input type="checkbox" checked={feeConfirmed} onChange={(event) => setFeeConfirmed(event.target.checked)} disabled={submitting} /> 我确认调用已配置的模型，并知晓本次分析可能产生费用。</label>
          <div className="df-dialog-actions"><button className="df-secondary-button" type="button" onClick={() => setShowConfirmation(false)} disabled={submitting}>返回修改</button><button className="df-primary-button" type="button" onClick={createTask} disabled={submitting || !feeConfirmed}>{submitting ? <LoaderCircle className="df-spin" size={17} /> : <PlayCircle size={17} />}{submitting ? "正在提交" : "确认生成"}</button></div>
      </WorkspaceDialog>
    </>
  );
}

function TaskTable({ tasks }: { tasks: OperationsTask[] }) {
  if (tasks.length === 0) return <EmptyMessage>当前没有分析任务</EmptyMessage>;
  return <div className="df-table-wrap"><table className="df-task-table">
    <thead><tr><th>任务</th><th>分析范围</th><th>创建时间</th><th>结果状态</th><th aria-label="操作" /></tr></thead>
    <tbody>{tasks.map((task) => <tr key={task.taskReference}>
      <td><strong>{task.title}</strong><span>#{task.taskReference}</span></td>
      <td><div className="df-table-domains">{task.requestedDomains.map((domain) => <span key={domain}>{domainLabel(domain)}</span>)}</div></td>
      <td>{formatDateTime(task.createdAt)}</td><td><TaskStatus task={task} /></td>
      <td><Link className="df-row-link" to={`/operations/tasks/${task.taskReference}`} aria-label={`查看 ${task.title}`}><ChevronRight size={18} /></Link></td>
    </tr>)}</tbody>
  </table></div>;
}

function TasksWorkspace({ tasks, hasMore }: { tasks: OperationsTask[]; hasMore: boolean }) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [pageData, setPageData] = useState({ tasks, hasMore });
  const [pageError, setPageError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      setLoading(true);
      try {
        const data = await operationsApiService.getTasks(page * 20);
        if (active) { setPageData(data); setPageError(""); }
      } catch (error) { if (active) setPageError(errorMessage(error)); }
      finally { if (active) { setLoading(false); timer = setTimeout(load, 5000); } }
    };
    void load();
    return () => { active = false; clearTimeout(timer); };
  }, [page]);
  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return normalized ? pageData.tasks.filter((task) => `${task.title} ${task.taskReference} ${task.objective}`.toLowerCase().includes(normalized)) : pageData.tasks;
  }, [query, pageData.tasks]);
  return <>
    <WorkspaceHeader eyebrow="任务中心" title="分析任务" description="查看任务范围、分析状态和已经整理完成的运营结论。" action={<Link className="df-primary-button" to="/operations/analysis"><PlayCircle size={17} />新建分析</Link>} />
    <section className="df-section-block"><div className="df-task-toolbar"><div><strong>{filtered.length}</strong><span>项分析任务 · 第 {page + 1} 页</span></div><label className="df-search-field"><span>搜索本页</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="任务名称或编号" /></label></div>{pageError && <p role="alert" className="df-form-error">{pageError} 当前保留上次读取的记录。</p>}<TaskTable tasks={filtered} /><div className="df-dialog-actions"><button type="button" className="df-secondary-button" disabled={page === 0 || loading} onClick={() => setPage((value) => value - 1)}>上一页</button><button type="button" className="df-secondary-button" disabled={!pageData.hasMore || loading} onClick={() => setPage((value) => value + 1)}>下一页</button></div></section>
  </>;
}

function ResultWorkspace({ task }: { task: OperationsTask }) {
  const result = task.result;
  return <>
    <Link className="df-back-link" to="/operations/tasks"><ArrowLeft size={16} />返回任务列表</Link>
    <section className="df-result-hero"><div><div className="df-result-meta"><TaskStatus task={task} /><span>#{task.taskReference}</span><span>{formatDateTime(result.updatedAt)}</span></div><h1>{result.headline}</h1><p>{result.summary}</p></div><div className="df-result-score"><span>行动建议</span><strong>{result.actions.length}</strong><small>{result.viewState === "processing" ? "等待分析完成" : "项可执行任务"}</small></div></section>
    <div className="df-result-layout"><main className="df-result-main">
      <section className="df-result-section"><div className="df-section-heading"><div><p className="df-eyebrow">核心发现</p><h2>数据说明了什么</h2></div><span>{result.findings.length} 项</span></div>
        <div className="df-finding-list">{result.findings.map((finding, index) => <article className="df-finding-card" key={`${finding.domain}-${index}`}><div className="df-finding-number">0{index + 1}</div><div className="df-finding-content"><span className="df-domain-label">{domainLabel(finding.domain)}</span><h3>{finding.title}</h3><p>{finding.summary}</p><div className="df-metric-grid">{finding.metrics.map((metric) => <div key={metric.label}><span>{metric.label}</span><strong>{metric.value}</strong>{metric.context && <small>{metric.context}</small>}</div>)}</div><details className="df-evidence-details"><summary>查看证据与适用范围</summary><div><strong>证据依据</strong><ul>{finding.evidenceBasis.map((item) => <li key={item}>{item}</li>)}</ul></div><div><strong>适用范围</strong><ul>{finding.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div></details></div></article>)}</div>
      </section>
      <section className="df-result-section"><div className="df-section-heading"><div><p className="df-eyebrow">行动清单</p><h2>下一步怎么做</h2></div><span>{result.actions.length} 项</span></div>
        {result.actions.length > 0 ? <div className="df-action-list">{result.actions.map((action, index) => <article className="df-action-card" key={`${action.title}-${index}`}><div className={`df-priority-mark is-${action.priority}`}>{priorityLabels[action.priority]}</div><h3>{action.title}</h3><p>{action.rationale}</p><dl><div><dt>负责人</dt><dd>{action.owner}</dd></div><div><dt>完成时间</dt><dd>{action.dueWindow}</dd></div><div><dt>验收方式</dt><dd>{action.verification}</dd></div></dl><div className="df-guardrails"><ShieldCheck size={16} /><div><strong>执行边界</strong>{action.guardrails.map((item) => <span key={item}>{item}</span>)}</div></div></article>)}</div> : <EmptyMessage>{result.viewState === "processing" ? "任务正在运行，完成后自动更新行动建议。" : result.viewState === "unavailable" ? "请联系管理员检查本次任务，不会自动再次调用模型。" : "本次分析仅整理数据发现"}</EmptyMessage>}
      </section>
    </main><aside className="df-result-sidebar"><section><p className="df-eyebrow">任务信息</p><dl className="df-compact-list"><div><dt>任务名称</dt><dd>{task.title}</dd></div><div><dt>数据源</dt><dd>{task.sourceName}</dd></div><div><dt>分析范围</dt><dd>{task.requestedDomains.map(domainLabel).join("、")}</dd></div></dl></section><section><p className="df-eyebrow">结果说明</p><ul className="df-notice-list">{result.notices.map((notice) => <li key={notice}>{notice}</li>)}</ul></section><Link className="df-primary-button df-full-button" to={`/operations/conversations?context=task&task_reference=${task.taskReference}`}><MessageCircle size={16} />在对话中继续</Link><Link className="df-secondary-button df-full-button" to="/operations/analysis"><RefreshCw size={16} />发起新的分析</Link></aside></div>
  </>;
}

function ConnectorDialog({ connector, onClose }: { connector: ConnectorType; onClose: () => void }) {
  return <WorkspaceDialog open onClose={onClose} className="df-connector-dialog" titleId="connector-title">
    <button className="df-icon-button df-dialog-close" type="button" aria-label="关闭" onClick={onClose}><X size={19} /></button>
    <div className="df-connector-dialog-head"><div className="df-dialog-mark"><Plug size={24} /></div><div><p className="df-eyebrow">{connector.category} · {connector.accessMode}</p><h2 id="connector-title">{connector.name} 接入要求</h2></div></div><p className="df-connector-lead">{connector.description}</p>
    <div className="df-connector-info"><span>认证方式</span><strong>{connector.authentication}</strong></div><div className="df-requirement-grid"><section><h3>准备信息</h3><ol>{connector.requiredFields.map((item) => <li key={item}>{item}</li>)}</ol></section><section><h3>接入流程</h3><ol>{connector.setupSteps.map((item) => <li key={item}>{item}</li>)}</ol></section></div>
    <div className="df-dialog-footer"><p><ShieldCheck size={16} />数据连接统一采用只读权限，并由管理员完成授权与验证。</p><button className="df-primary-button" type="button" onClick={onClose}>我已了解</button></div>
  </WorkspaceDialog>;
}

function SourcesWorkspace({ snapshot }: { snapshot: OperationsSnapshot }) {
  const [selectedConnector, setSelectedConnector] = useState<ConnectorType | null>(null);
  const connectorGroups = [...new Set(snapshot.connectorTypes.map((connector) => connector.category))];
  return <>
    <WorkspaceHeader eyebrow="数据管理" title="数据源" description="查看当前可分析的数据，并了解数据库、协作应用与标准接口的接入方式。" />
    <section className="df-section-block"><div className="df-section-heading"><div><p className="df-eyebrow">可用数据</p><h2>已接入数据源</h2></div><span>{snapshot.sources.length} 个</span></div>
      <div className="df-source-card-grid">{snapshot.sources.map((source) => <article className="df-source-card" key={source.id}><div className="df-source-card-head"><div className="df-source-icon"><FileSpreadsheet size={23} /></div><div><h3>{source.name}</h3><p>{source.description}</p></div><span className={`df-status-pill ${source.status === "ready" ? "is-ready" : ""}`}><CheckCircle2 size={14} />{source.statusLabel}</span></div><div className="df-source-facts"><span>{source.periodLabel}</span><span>{source.datasets.length} 类数据</span><span>{totalRecords(source)} 条记录</span><span>合成测试数据</span></div><div className="df-dataset-grid">{source.datasets.map((dataset) => <div key={dataset.name}><span>{dataset.name}</span><strong>{dataset.records}</strong><small>条</small></div>)}</div><div className="df-source-footer"><span><Clock3 size={15} />数据校验摘要已载入</span><span><ShieldCheck size={15} />只读</span></div></article>)}</div>
    </section>
    <section className="df-section-block"><div className="df-section-heading"><div><p className="df-eyebrow">接入类型</p><h2>支持的数据连接</h2></div><span>{snapshot.connectorTypes.length} 种</span></div>
      {connectorGroups.map((category) => <div className="df-connector-group" key={category}><h3>{category}</h3><div className="df-connector-grid">{snapshot.connectorTypes.filter((connector) => connector.category === category).map((connector) => <article className="df-connector-card" key={connector.id}><div className="df-connector-icon">{connector.category === "数据库" ? <Database size={20} /> : connector.category === "文件" ? <FileSpreadsheet size={20} /> : <Plug size={20} />}</div><div><h3>{connector.name}</h3><p>{connector.description}</p></div><div className="df-connector-card-foot"><span className={connector.availability === "enabled" ? "is-enabled" : ""}>{connector.availabilityLabel}</span><button type="button" aria-label={`查看 ${connector.name} 接入要求`} onClick={() => setSelectedConnector(connector)}>接入要求 <ChevronRight size={15} /></button></div></article>)}</div></div>)}
    </section>
    {selectedConnector && <ConnectorDialog connector={selectedConnector} onClose={() => setSelectedConnector(null)} />}
  </>;
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="df-page-state"><Database size={30} /><h2>工作区加载失败</h2><p>{message}</p><button className="df-primary-button" onClick={onRetry} type="button"><RefreshCw size={16} />重新加载</button></div>;
}

function TaskDetail({ reference }: { reference: string }) {
  const [task, setTask] = useState<OperationsTask | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const next = await operationsApiService.getTask(reference);
        if (!active) return;
        setTask(next); setError("");
        if (next.resultState === "processing") timer = setTimeout(load, 5000);
      } catch (error) { if (active) setError(errorMessage(error)); }
    };
    void load();
    return () => { active = false; clearTimeout(timer); };
  }, [reference, reload]);
  if (error) return <ErrorState message={error} onRetry={() => { setError(""); setReload((value) => value + 1); }} />;
  if (!task) return <div className="df-page-state"><LoaderCircle className="df-spin" size={30} /><p>正在读取任务结果</p></div>;
  return <ResultWorkspace task={task} />;
}

export function OperationsEntryPage() {
  const location = useLocation();
  const userId = useAuthStore((state) => state.user?.id);
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const path = location.pathname.replace(/\/$/, "");
  const taskReference = path.match(/^\/operations\/tasks\/([A-F0-9]{12})$/)?.[1];
  useEffect(() => {
    if (taskReference || path === "/operations/visualizations" || path === "/operations/conversations") return;
    let active = true;
    setLoadState({ status: "loading" });
    operationsApiService.getSnapshot().then((snapshot) => active && setLoadState({ status: "ready", snapshot })).catch((error: unknown) => active && setLoadState({ status: "error", message: errorMessage(error) }));
    return () => { active = false; };
  }, [reloadKey, userId, path, taskReference]);
  const current = path === "/operations/visualizations" ? "visualizations" : path === "/operations/conversations" ? "conversations" : path.includes("/data-sources") ? "sources" : path.includes("/analysis") ? "analysis" : path.includes("/tasks") ? "tasks" : "overview";
  const addTask = (task: OperationsTask) => setLoadState((state) => state.status === "ready" ? { ...state, snapshot: { ...state.snapshot, tasks: [task, ...state.snapshot.tasks.filter((item) => item.taskReference !== task.taskReference)] } } : state);
  let content: ReactNode;
  if (taskReference) content = <TaskDetail key={`${userId}-${taskReference}`} reference={taskReference} />;
  else if (current === "visualizations") content = <Suspense fallback={<div className="df-page-state">正在加载数据看板</div>}><VisualizationsPage key={userId} /></Suspense>;
  else if (current === "conversations") content = <Suspense fallback={<div className="df-page-state">正在加载运营对话</div>}><ConversationsPage key={userId} /></Suspense>;
  else if (loadState.status === "loading") content = <div className="df-page-state"><LoaderCircle className="df-spin" size={30} /><p>正在加载运营工作区</p></div>;
  else if (loadState.status === "error") content = <ErrorState message={loadState.message} onRetry={() => { setLoadState({ status: "loading" }); setReloadKey((value) => value + 1); }} />;
  else if (current === "analysis") content = <AnalysisWorkspace snapshot={loadState.snapshot} onCreated={addTask} />;
  else if (current === "sources") content = <SourcesWorkspace snapshot={loadState.snapshot} />;
  else if (current === "tasks") {
    content = <TasksWorkspace tasks={loadState.snapshot.tasks} hasMore={loadState.snapshot.hasMore} />;
  } else content = <Overview snapshot={loadState.snapshot} />;
  return <div className={`df-operations-shell${current === "conversations" ? " is-conversations" : ""}`}><div className="df-operations-page">{content}</div></div>;
}

export default OperationsEntryPage;
