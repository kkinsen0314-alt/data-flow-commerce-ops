import { useAuthStore } from "@/stores/auth";
import { connectorGuides } from "./connectorGuides";
import type {
  AnalysisRequest, AvailableDataSource, ConnectorType, OperationDomainId,
  OperationsSnapshot, OperationsTask, OperatorResult, ResultState, TerminalStatus,
} from "./operationsContracts";

declare const __DATA_FLOW_API_PORT__: number;

interface ResultDto {
  schema_version: "1.0";
  result_type: "miniclaw_operator_result";
  task_reference: string;
  view_state: ResultState;
  terminal_status: TerminalStatus;
  requested_domains: OperationDomainId[];
  synthetic: true;
  updated_at: string;
  headline: string;
  summary: string;
  findings: Array<{
    domain: OperationDomainId; title: string; summary: string;
    metrics: OperatorResult["findings"][number]["metrics"];
    evidence_basis: string[]; limitations: string[];
  }>;
  actions: Array<{
    title: string; priority: "high" | "medium" | "low"; owner: string;
    due_window: string; rationale: string; verification: string; guardrails: string[];
  }>;
  notices: string[];
}

interface TaskDto {
  task_reference: string; title: string; objective: string;
  source_id: string | null; source_name: string; requested_domains: OperationDomainId[];
  terminal_status: TerminalStatus; view_state: ResultState;
  created_at: string; updated_at: string; result: ResultDto;
}

interface SourcesDto {
  catalog: {
    sources: Array<{
      source_id: string; display_name: string; description: string;
      source_type: "local_file"; source_type_label: string;
      status: AvailableDataSource["status"]; synthetic: true;
      available_domains: OperationDomainId[]; data_period: string | null;
    }>;
    source_types: Array<{
      type_id: "local_file" | Exclude<ConnectorType["id"], "csv_excel">;
      display_name: string; description: string; status: ConnectorType["availability"];
    }>;
  };
  datasets: Record<string, AvailableDataSource["datasets"]>;
}

export class OperationsApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

function apiUrl(path: string): string {
  const url = new URL(window.location.origin);
  url.port = String(__DATA_FLOW_API_PORT__);
  return new URL(`/v1/operations${path}`, url).href;
}

export async function operationsResponse(path: string, options?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      ...options, credentials: "include", cache: "no-store",
      signal: AbortSignal.timeout(options?.method === "POST" ? 90000 : 20000),
    });
  } catch {
    throw new OperationsApiError("无法连接运营服务。请检查服务状态；已发出的操作请查询原记录，不要重复提交。", 0);
  }
  if (!response.ok) {
    if (response.status === 401) {
      useAuthStore.setState({ authenticated: false, user: null });
    }
    const body: unknown = await response.json().catch(() => null);
    const detail = typeof body === "object" && body !== null && "detail" in body ? body.detail : null;
    throw new OperationsApiError(
      typeof detail === "string" ? detail : "运营请求未通过校验，请检查输入或联系管理员。",
      response.status,
    );
  }
  return response;
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  return (await operationsResponse(path, options)).json() as Promise<T>;
}

function mapTask(dto: TaskDto): OperationsTask {
  const result = dto.result;
  return {
    taskReference: dto.task_reference, title: dto.title, objective: dto.objective,
    sourceId: dto.source_id, sourceName: dto.source_name, requestedDomains: dto.requested_domains,
    status: dto.terminal_status, resultState: dto.view_state,
    createdAt: dto.created_at, updatedAt: dto.updated_at,
    result: {
      schemaVersion: result.schema_version, resultType: result.result_type,
      taskReference: result.task_reference, viewState: result.view_state,
      terminalStatus: result.terminal_status, requestedDomains: result.requested_domains,
      synthetic: result.synthetic, updatedAt: result.updated_at,
      headline: result.headline, summary: result.summary, notices: result.notices,
      findings: result.findings.map((item) => ({
        domain: item.domain, title: item.title, summary: item.summary, metrics: item.metrics,
        evidenceBasis: item.evidence_basis, limitations: item.limitations,
      })),
      actions: result.actions.map((item) => ({
        title: item.title, priority: item.priority, owner: item.owner, dueWindow: item.due_window,
        rationale: item.rationale, verification: item.verification, guardrails: item.guardrails,
      })),
    },
  };
}

function pendingStorageKey(): string {
  const user = useAuthStore.getState().user;
  if (!user) throw new OperationsApiError("请重新登录后提交分析。", 401);
  return `data-flow.pending-submission.${user.id}`;
}

export const operationsApiService = {
  async getTasks(offset = 0): Promise<{ tasks: OperationsTask[]; hasMore: boolean }> {
    const catalog = await request<{ tasks: TaskDto[]; has_more: boolean }>(`/tasks?offset=${offset}&limit=20`);
    return { tasks: catalog.tasks.map(mapTask), hasMore: catalog.has_more };
  },

  async getSnapshot(): Promise<OperationsSnapshot> {
    const [sources, tasks, configuration] = await Promise.all([
      request<SourcesDto>("/data-sources"), this.getTasks(), request<{ ready: boolean }>("/configuration"),
    ]);
    return {
      ...tasks, ready: configuration.ready,
      sources: sources.catalog.sources.map((source) => ({
        id: source.source_id, name: source.display_name, type: source.source_type,
        typeLabel: source.source_type_label, status: source.status,
        statusLabel: { ready: "可用", degraded: "需检查数据", unavailable: "无法读取" }[source.status],
        synthetic: source.synthetic, periodLabel: source.data_period ?? "当前周期",
        datasets: sources.datasets[source.source_id] ?? [],
        supportedDomains: source.available_domains, description: source.description,
      })),
      connectorTypes: sources.catalog.source_types.map((type) => {
        const id = type.type_id === "local_file" ? "csv_excel" : type.type_id;
        const guide = connectorGuides.find((item) => item.id === id);
        if (!guide) throw new Error("接入类型格式不受支持。");
        return { ...guide, name: type.display_name, description: type.description,
          availability: type.status, availabilityLabel: type.status === "enabled" ? "可直接使用" : "管理员接入" };
      }),
    };
  },

  async getTask(reference: string): Promise<OperationsTask> {
    return mapTask(await request<TaskDto>(`/tasks/${encodeURIComponent(reference)}`));
  },

  hasPendingSubmission(): boolean {
    return Boolean(window.sessionStorage.getItem(pendingStorageKey()));
  },

  async recoverSubmission(): Promise<OperationsTask> {
    const storageKey = pendingStorageKey();
    const key = window.sessionStorage.getItem(storageKey);
    if (!key) throw new OperationsApiError("当前没有待确认的提交记录。", 404);
    const task = mapTask(await request<TaskDto>(`/submissions/${encodeURIComponent(key)}`));
    if (task.status !== "uncertain") window.sessionStorage.removeItem(storageKey);
    return task;
  },

  async createAnalysis(analysis: AnalysisRequest): Promise<OperationsTask> {
    const storageKey = pendingStorageKey();
    const key = window.sessionStorage.getItem(storageKey) ?? window.crypto.randomUUID();
    window.sessionStorage.setItem(storageKey, key);
    try {
      const dto = await request<TaskDto>("/tasks", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: analysis.title, objective: analysis.objective, source_id: analysis.sourceId,
          requested_domains: analysis.requestedDomains, include_strategy: analysis.includeStrategy,
          fee_confirmation: "confirmed", authorized_model_execution: true, idempotency_key: key,
        }),
      });
      if (dto.terminal_status !== "uncertain") window.sessionStorage.removeItem(storageKey);
      return mapTask(dto);
    } catch (error) {
      if (error instanceof OperationsApiError && [401, 403, 422].includes(error.status)) {
        window.sessionStorage.removeItem(storageKey);
      }
      throw error;
    }
  },
};
