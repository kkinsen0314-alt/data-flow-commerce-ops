import { useEffect, useRef, useState, type FormEvent } from "react";
import { BarChart, Bar, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BarChart3, Download, Filter, ImageDown, LoaderCircle, MessageCircle, RefreshCw, Table2, X } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import {
  chartPng, downloadBlob, visualizationService,
  type DetailKind, type VisualizationChart, type VisualizationDetails, type VisualizationFilters, type VisualizationSnapshot,
} from "../visualizationService";
import "../visualizations.css";

const detailLabels: Record<DetailKind, string> = { content: "内容明细", live: "直播参与明细", leads: "线索明细", followups: "跟进明细", orders: "订单明细" };
const number = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
const message = (error: unknown) => error instanceof Error ? error.message : "数据读取失败，请重试。";
const formatCell = (value: string | number | null) => value === null ? "—" : typeof value === "number" ? number.format(value) : value;

function Plot({ chart }: { chart: VisualizationChart }) {
  if (chart.kind === "funnel") return <svg className="df-viz-funnel" viewBox="0 0 600 260" role="img" aria-label="内容曝光、点击和关联线索数量">
    {chart.rows.map((row, index) => <g key={String(row.label)}>
      <rect x={index * 200 + 5} y="65" width="180" height="122" rx="6" fill={index === 2 ? "var(--df-green)" : "var(--df-subtle)"} />
      <text x={index * 200 + 95} y="104" textAnchor="middle" fill={index === 2 ? "var(--df-brand-on)" : "var(--df-ink-soft)"} fontSize="15">{row.label}</text>
      <text x={index * 200 + 95} y="148" textAnchor="middle" fill={index === 2 ? "var(--df-brand-on)" : "var(--df-ink)"} fontSize="28" fontWeight="600">{number.format(Number(row.value))}</text>
      {index < 2 && <text x={index * 200 + 195} y="134" textAnchor="middle" fill="var(--df-ink-soft)" fontSize="18">→</text>}
    </g>)}
  </svg>;
  const axes = <>
    <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="var(--df-line)" />
    <XAxis dataKey="label" tick={{ fontSize: 12, fill: "var(--df-ink-soft)" }} tickLine={false} axisLine={false} interval={0} height={42} tickFormatter={(value: string) => value.startsWith("2026-") ? value.slice(5) : value} />
    <YAxis tick={{ fontSize: 12, fill: "var(--df-ink-soft)" }} tickLine={false} axisLine={false} width={48} allowDecimals={false} />
    <Tooltip contentStyle={{ borderRadius: 6, border: "1px solid var(--df-line)", background: "var(--df-panel)", color: "var(--df-ink)", fontSize: 12 }} />
  </>;
  return <ResponsiveContainer width="100%" height={260} minWidth={0}>
    {chart.kind === "line" ? <LineChart data={chart.rows} margin={{ top: 18, right: 20, bottom: 8, left: 0 }}>{axes}{chart.series.map((series) => <Line key={series.key} dataKey={series.key} name={series.label} stroke={series.color} strokeWidth={3} dot={{ r: 4 }} isAnimationActive={false} />)}</LineChart>
      : <BarChart data={chart.rows} margin={{ top: 18, right: 12, bottom: 8, left: 0 }} barGap={3}>{axes}{chart.series.map((series) => <Bar key={series.key} dataKey={series.key} name={series.label} fill={series.color} radius={[3, 3, 0, 0]} maxBarSize={38} isAnimationActive={false} />)}</BarChart>}
  </ResponsiveContainer>;
}

function ChartCard({ chart, context, onDetails }: { chart: VisualizationChart; context: string[]; onDetails: (kind: DetailKind) => void }) {
  const plot = useRef<HTMLDivElement>(null);
  const [exporting, setExporting] = useState(false);
  const [notice, setNotice] = useState("");
  const exportPng = async () => {
    const svg = plot.current?.querySelector("svg");
    if (!svg) return;
    setExporting(true); setNotice("");
    try {
      downloadBlob(await chartPng(svg, chart.title, [...context, chart.description], chart.series.map((series) => series.label).join(" / ")), `data-flow-${chart.key}.png`);
      setNotice("图片已导出");
    } catch (error) { setNotice(message(error)); }
    finally { setExporting(false); }
  };
  return <article className="df-viz-card" data-chart={chart.key}>
    <header><div><h2>{chart.title}</h2><p>{chart.description}</p></div><button type="button" className="df-viz-icon" aria-label={`导出${chart.title}图片`} onClick={exportPng} disabled={exporting || !chart.rows.length}><ImageDown size={18} /></button></header>
    <div className="df-viz-plot" ref={plot}>{chart.rows.length ? <Plot chart={chart} /> : <div className="df-viz-empty">当前范围没有付款记录</div>}</div>
    {chart.kind !== "funnel" && <div className="df-viz-legend">{chart.series.map((series) => <span key={series.key}><i style={{ background: series.color }} />{series.label}</span>)}</div>}
    <footer><button type="button" onClick={() => onDetails(chart.detail)}><Table2 size={15} />查看{detailLabels[chart.detail]}</button><details><summary>指标数据表</summary><div className="df-viz-data-table"><table><thead><tr><th>分组</th>{chart.series.map((series) => <th key={series.key}>{series.label}</th>)}</tr></thead><tbody>{chart.rows.map((row) => <tr key={String(row.label)}><td>{row.label}</td>{chart.series.map((series) => <td key={series.key}>{row[series.key] === null ? "—" : number.format(Number(row[series.key]))}</td>)}</tr>)}</tbody></table></div></details></footer>
    {notice && <p role="status" className="df-viz-export-notice">{notice}</p>}
  </article>;
}

function DetailPanel({ kind, filters, onClose }: { kind: DetailKind; filters: VisualizationFilters; onClose: () => void }) {
  const [data, setData] = useState<VisualizationDetails | null>(null);
  const [offset, setOffset] = useState(0);
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportStatus, setExportStatus] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); heading.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, []);
  useEffect(() => {
    let active = true; setLoading(true); setError("");
    visualizationService.details(filters, kind, offset).then((next) => { if (active) setData(next); }).catch((error: unknown) => { if (active) setError(message(error)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [filters, kind, offset, reload]);
  const exportCsv = async () => {
    setExporting(true); setExportStatus("");
    try { downloadBlob(await visualizationService.csv(filters, kind), `data-flow-${kind}.csv`); setExportStatus("已导出当前筛选范围内的全部明细"); }
    catch (error) { setExportStatus(message(error)); }
    finally { setExporting(false); }
  };
  return <section className="df-viz-details" aria-label={detailLabels[kind]}>
    <header><div><p className="df-eyebrow">数据明细</p><h2 tabIndex={-1} ref={heading}>{detailLabels[kind]}</h2><p>编号已脱敏 · 导出包含当前筛选范围内的全部记录</p></div><div className="df-viz-actions"><button type="button" className="df-secondary-button" onClick={exportCsv} disabled={exporting || loading || Boolean(error)}><Download size={16} />导出 CSV</button><button type="button" className="df-viz-icon" aria-label="关闭明细" onClick={onClose}><X size={18} /></button></div></header>
    {loading ? <p role="status">正在读取明细…</p> : error ? <div role="alert"><p>{error}</p><button className="df-secondary-button" type="button" onClick={() => setReload((value) => value + 1)}>重新读取明细</button></div> : data && <>
      <div className="df-viz-table-scroll"><table><thead><tr>{data.columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>{data.rows.map((row, index) => <tr key={`${row.reference}-${index}`}>{data.columns.map((column) => <td key={column.key}>{formatCell(row[column.key])}</td>)}</tr>)}</tbody></table>{data.total === 0 && <p className="df-viz-empty">当前筛选范围没有记录</p>}</div>
      <footer><span>共 {data.total} 条 · 第 {Math.floor(offset / 20) + 1} 页</span><div className="df-viz-actions"><button type="button" className="df-secondary-button" disabled={offset === 0} onClick={() => setOffset((value) => Math.max(0, value - 20))}>上一页</button><button type="button" className="df-secondary-button" disabled={offset + 20 >= data.total} onClick={() => setOffset((value) => value + 20)}>下一页</button></div></footer>
    </>}
    {exportStatus && <p role="status">{exportStatus}</p>}
  </section>;
}

export default function VisualizationsPage() {
  const [searchParams] = useSearchParams();
  const initialFilters = () => Object.fromEntries(
    ["source_id", "date_from", "date_to", "channel", "content", "session"]
      .map((key) => [key, searchParams.get(key)] as const)
      .filter((entry): entry is readonly [string, string] => Boolean(entry[1])),
  ) as VisualizationFilters;
  const [draft, setDraft] = useState<VisualizationFilters>(initialFilters);
  const [filters, setFilters] = useState<VisualizationFilters>(initialFilters);
  const [data, setData] = useState<VisualizationSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [detail, setDetail] = useState<DetailKind | null>(null);
  useEffect(() => {
    let active = true; setLoading(true); setError(""); setDetail(null);
    visualizationService.snapshot(filters).then((next) => { if (active) setData(next); }).catch((error: unknown) => { if (active) setError(message(error)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [filters, reload]);
  const change = (key: keyof VisualizationFilters, value: string) => setDraft((current) => ({ ...current, [key]: value || undefined }));
  const apply = (event: FormEvent) => { event.preventDefault(); setFilters({ ...draft }); };
  const period = data ? `${data.filters.date_from || data.date_min} 至 ${data.filters.date_to || data.date_max}` : "";
  const context = data ? [
    `${data.source_name} · ${data.source_type}${data.synthetic ? " · 合成测试数据" : ""}`,
    `线索创建日期：${period}；后续数据截至 ${data.observed_through.replace("T", " ")}`,
    `渠道：${data.filters.channel || "全部"}；内容：${data.filters.content || "全部"}；场次：${data.filters.session || "全部"}`,
  ] : [];
  const conversationPath = data ? `/operations/conversations?${new URLSearchParams({
    context: "visualization",
    source_id: data.source_id,
    ...Object.fromEntries(Object.entries(data.filters).filter(([, value]) => Boolean(value))),
  }).toString()}` : "/operations/conversations";
  return <div className="df-visualizations">
    <header className="df-workspace-header"><div><p className="df-eyebrow">经营洞察</p><h1>数据看板</h1><p className="df-page-description">从内容触达到付款转化，查看经营表现与每一个指标背后的记录。</p></div><div className="df-viz-actions"><Link className="df-primary-button" to={conversationPath}><MessageCircle size={16} />带到运营对话</Link><button type="button" className="df-secondary-button" disabled={loading} onClick={() => setReload((value) => value + 1)}><RefreshCw size={16} />刷新数据</button></div></header>
    <form className="df-viz-filters" onSubmit={apply}>
      <div className="df-viz-filter-heading"><Filter size={16} /><strong>分析范围</strong><span>按线索创建日期筛选</span></div>
      <div className="df-viz-filter-fields">
        <label><span>开始日期</span><input type="date" value={draft.date_from || ""} onChange={(event) => change("date_from", event.target.value)} /></label>
        <label><span>结束日期</span><input type="date" value={draft.date_to || ""} min={draft.date_from} onChange={(event) => change("date_to", event.target.value)} /></label>
        {([ ["channel", "渠道"], ["content", "内容"], ["session", "直播场次"] ] as const).map(([key, label]) => <label key={key}><span>{label}</span><select value={draft[key] || ""} onChange={(event) => change(key, event.target.value)}><option value="">全部{label}</option>{data?.options[key].map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>)}
        <div className="df-viz-actions"><button type="submit" className="df-primary-button" disabled={loading}>应用筛选</button><button type="button" className="df-secondary-button" onClick={() => { setDraft({}); setFilters({}); }} disabled={loading}>重置</button></div>
      </div>
    </form>
    {loading ? <div className="df-page-state" role="status"><LoaderCircle className="df-spin" size={28} /><p>正在计算经营指标</p></div> : error ? <div className="df-page-state" role="alert"><BarChart3 size={28} /><h2>看板读取失败</h2><p>{error}</p><button type="button" className="df-primary-button" onClick={() => setReload((value) => value + 1)}>重新读取</button></div> : data && <>
      <div className="df-viz-provenance"><div><strong>{data.source_name}</strong><span>{data.source_type}</span>{data.synthetic && <span className="df-viz-data-badge">合成测试数据</span>}</div><p>线索创建日期 {period} · 后续数据截至 {data.observed_through.replace("T", " ")}</p></div>
      <section className="df-viz-kpis" aria-label="经营核心指标">{data.metrics.map((metric, index) => <article key={metric.key} data-metric={metric.key}><span>{metric.label}</span><strong>{metric.value === null ? "—" : `${metric.format === "currency" ? "¥" : ""}${number.format(metric.value)}${metric.format === "percent" ? "%" : ""}`}</strong><button type="button" onClick={() => setDetail(index < 2 ? "orders" : index === 4 ? "followups" : "leads")}>查看记录 →</button><details><summary>指标口径</summary><p>{metric.definition}</p></details></article>)}</section>
      <p className="df-viz-cohort" role="status">当前范围：{data.selected_leads} 条线索 · {data.filters.channel || "全部渠道"} · {data.filters.content ? data.options.content.find((option) => option.value === data.filters.content)?.label : "全部内容"} · {data.filters.session ? `场次 ${data.filters.session}` : "全部场次"}</p>
      {data.selected_leads === 0 ? <section className="df-viz-no-data"><BarChart3 size={32} /><h2>当前筛选范围没有线索</h2><p>调整日期或清除筛选，查看其他数据。无分母的转化率显示为“—”。</p></section> : <section className="df-viz-grid" aria-label="经营图表">{data.charts.map((chart) => <ChartCard key={chart.key} chart={chart} context={context} onDetails={setDetail} />)}</section>}
      {detail && <DetailPanel key={detail} kind={detail} filters={data.filters} onClose={() => setDetail(null)} />}
      <details className="df-viz-definitions"><summary>数据来源与统计说明</summary><p>源文件最近更新：{new Date(data.data_updated_at).toLocaleString("zh-CN", { hour12: false })}</p>{data.notices.map((notice) => <p key={notice}>{notice}</p>)}</details>
    </>}
  </div>;
}
