import { operationsResponse, request } from "./operationsApiService";

export type DetailKind = "content" | "live" | "leads" | "followups" | "orders";
export type ChartRow = Record<string, string | number | null>;
export interface VisualizationFilters {
  source_id?: string; date_from?: string; date_to?: string; channel?: string; content?: string; session?: string;
}
export interface VisualizationChart {
  key: string; title: string; description: string; kind: "bar" | "line" | "funnel";
  detail: DetailKind; series: Array<{ key: string; label: string; color: string }>; rows: ChartRow[];
}
export interface VisualizationSnapshot {
  source_id: string; source_name: string; source_type: string; synthetic: boolean;
  data_updated_at: string; observed_through: string; date_min: string; date_max: string;
  filters: VisualizationFilters;
  options: Record<"channel" | "content" | "session", Array<{ value: string; label: string }>>;
  metrics: Array<{ key: string; label: string; value: number | null; format: "number" | "currency" | "percent"; definition: string }>;
  charts: VisualizationChart[]; notices: string[]; selected_leads: number;
}
export interface VisualizationDetails {
  dataset: DetailKind; columns: Array<{ key: string; label: string }>;
  rows: ChartRow[]; total: number; offset: number; limit: number;
}

function query(filters: VisualizationFilters): string {
  return new URLSearchParams(Object.entries(filters).filter(([, value]) => Boolean(value))).toString();
}

export const visualizationService = {
  snapshot: (filters: VisualizationFilters) => request<VisualizationSnapshot>(`/visualizations?${query(filters)}`),
  details: (filters: VisualizationFilters, kind: DetailKind, offset: number) =>
    request<VisualizationDetails>(`/visualizations/details/${kind}?${query(filters)}&offset=${offset}&limit=20`),
  csv: async (filters: VisualizationFilters, kind: DetailKind) =>
    (await operationsResponse(`/visualizations/export/${kind}.csv?${query(filters)}`)).blob(),
};

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = filename;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function chartPng(svg: SVGSVGElement, title: string, context: string[], legend: string): Promise<Blob> {
  const width = Math.max(620, svg.clientWidth);
  const height = svg.clientHeight || 260;
  const copy = svg.cloneNode(true) as SVGSVGElement;
  const sourceElements = [svg, ...svg.querySelectorAll<SVGElement>("*")];
  const targetElements = [copy, ...copy.querySelectorAll<SVGElement>("*")];
  sourceElements.forEach((element, index) => {
    const computed = getComputedStyle(element);
    const target = targetElements[index];
    target.style.fill = computed.fill;
    target.style.stroke = computed.stroke;
    target.style.fontFamily = computed.fontFamily;
  });
  const theme = getComputedStyle(svg);
  copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  copy.setAttribute("width", String(width)); copy.setAttribute("height", String(height));
  if (!copy.hasAttribute("viewBox")) copy.setAttribute("viewBox", `0 0 ${svg.clientWidth} ${height}`);
  const canvas = document.createElement("canvas");
  const lines = context.flatMap((line) => line.match(/.{1,44}/gu) ?? []);
  canvas.width = (width + 48) * 2; canvas.height = (height + 130 + lines.length * 20) * 2;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("浏览器无法生成图片，请使用 CSV 导出。");
  ctx.scale(2, 2); ctx.fillStyle = theme.getPropertyValue("--card").trim(); ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = theme.getPropertyValue("--foreground").trim(); ctx.font = `600 22px ${theme.fontFamily}`; ctx.fillText(`Data Flow · ${title}`, 24, 36);
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const img = new Image(); img.src = url; await img.decode();
    ctx.drawImage(img, 24, 58, width, height);
  } finally { URL.revokeObjectURL(url); }
  ctx.font = `12px ${theme.fontFamily}`; ctx.fillStyle = theme.getPropertyValue("--muted-foreground").trim();
  ctx.fillText(legend, 24, height + 82);
  lines.forEach((line, index) => ctx.fillText(line, 24, height + 110 + index * 20));
  return new Promise((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("图片导出失败，请重试。")), "image/png"));
}
