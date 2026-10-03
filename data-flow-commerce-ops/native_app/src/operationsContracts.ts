export const operationDomains = [
  {
    id: "content_growth",
    label: "内容增长",
    description: "定位内容到点击链路中的高效主题与待优化环节。",
  },
  {
    id: "live_conversion",
    label: "直播转化",
    description: "观察直播场次、线索承接与成交之间的转化表现。",
  },
  {
    id: "attribution_leads",
    label: "归因与线索",
    description: "核对渠道归因、跟进覆盖与订单回收质量。",
  },
] as const;

export type OperationDomainId = (typeof operationDomains)[number]["id"];

export type Priority = "high" | "medium" | "low";
export type ResultState = "processing" | "ready" | "needs_review" | "unavailable";
export type TerminalStatus = "completed" | "partial" | "blocked" | "uncertain" | null;

export interface OperatorMetric {
  label: string;
  value: string;
  context?: string;
}

export interface OperatorFinding {
  domain: OperationDomainId;
  title: string;
  summary: string;
  metrics: OperatorMetric[];
  evidenceBasis: string[];
  limitations: string[];
}

export interface OperatorAction {
  title: string;
  priority: Priority;
  owner: string;
  dueWindow: string;
  rationale: string;
  verification: string;
  guardrails: string[];
}

export interface OperatorResult {
  schemaVersion: "1.0";
  resultType: "miniclaw_operator_result";
  taskReference: string;
  viewState: ResultState;
  terminalStatus: TerminalStatus;
  requestedDomains: OperationDomainId[];
  synthetic: true;
  updatedAt: string;
  headline: string;
  summary: string;
  findings: OperatorFinding[];
  actions: OperatorAction[];
  notices: string[];
}

export interface OperationsTask {
  taskReference: string;
  title: string;
  objective: string;
  requestedDomains: OperationDomainId[];
  sourceId: string | null;
  sourceName: string;
  status: TerminalStatus;
  resultState: ResultState;
  createdAt: string;
  updatedAt: string;
  result: OperatorResult;
}

export interface DataSourceDataset {
  name: string;
  records: number;
}

export interface AvailableDataSource {
  id: string;
  name: string;
  type: "local_file";
  typeLabel: string;
  status: "ready" | "degraded" | "unavailable";
  statusLabel: string;
  synthetic: true;
  periodLabel: string;
  datasets: DataSourceDataset[];
  supportedDomains: OperationDomainId[];
  description: string;
}

export type ConnectorTypeId =
  | "csv_excel"
  | "mysql"
  | "postgresql"
  | "feishu_bitable"
  | "feishu_spreadsheet"
  | "http_api"
  | "mcp";

export interface ConnectorType {
  id: ConnectorTypeId;
  name: string;
  category: string;
  description: string;
  accessMode: "只读";
  availability: "enabled" | "configurable";
  availabilityLabel: string;
  authentication: string;
  requiredFields: string[];
  setupSteps: string[];
}

export interface AnalysisRequest {
  title: string;
  objective: string;
  sourceId: string;
  requestedDomains: OperationDomainId[];
  includeStrategy: boolean;
}

export interface OperationsSnapshot {
  sources: AvailableDataSource[];
  connectorTypes: ConnectorType[];
  tasks: OperationsTask[];
  hasMore: boolean;
  ready: boolean;
}

export interface DataFlowOperationsService {
  getSnapshot(): Promise<OperationsSnapshot>;
  createAnalysis(request: AnalysisRequest): Promise<OperationsTask>;
}

export type ConversationStatus = "ready" | "processing" | "uncertain" | "unavailable";
export type ConversationRole = "user" | "assistant";

export interface ConversationContextLink {
  kind: "analysis_task" | "visualization_view";
  reference: string;
  title: string;
  summary: string;
  returnPath: string;
}

export type ConversationContextRequest =
  | { kind: "analysis_task"; task_reference: string }
  | {
      kind: "visualization_view";
      visualization_filters: {
        source_id?: string;
        date_from?: string;
        date_to?: string;
        channel?: string;
        content?: string;
        session?: string;
      };
    };

export interface ConversationSummary {
  conversationReference: string;
  title: string;
  status: ConversationStatus;
  statusLabel: string;
  latestPreview: string | null;
  createdAt: string;
  updatedAt: string;
  canSend: boolean;
}

export interface ConversationMessage {
  messageReference: string;
  role: ConversationRole;
  content: string;
  timestamp: string;
  truncated: boolean;
  context: ConversationContextLink | null;
}

export interface ConversationThread extends ConversationSummary {
  messages: ConversationMessage[];
  pendingSubmission: boolean;
  queryOriginalSubmissionOnly: boolean;
}
