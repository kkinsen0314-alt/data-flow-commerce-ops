import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import {
  getDefaultEnvironment,
  StdioClientTransport,
} from "@modelcontextprotocol/sdk/client/stdio.js";
import { Type } from "typebox";

const PROJECT_ROOT =
  process.env.COMMERCE_OPS_PROJECT_ROOT?.trim() ||
  "D:\\Workspace\\project017-data-flow-commerce-ops";
const DATA_ROOT = path.join(PROJECT_ROOT, "data", "fixtures");
const AUDIT_ROOT = path.join(PROJECT_ROOT, "runtime", "data", "native-audit");
const CALL_TIMEOUT_MS = 45_000;
const WORKFLOW_RUN_ID_PATTERN = /^wf_[A-Za-z0-9_-]+$/;
const EXPECTED_MCP_TOOLS = new Set([
  "inspect_commerce_data",
  "analyze_short_video_data",
  "analyze_live_commerce_data",
  "analyze_attribution_and_leads",
  "drilldown_commerce_metric",
]);
const REQUIRED_INSPECT_DATASET_TYPES: Record<string, string[]> = {
  content_growth_analyst: ["short_video"],
  live_conversion_analyst: ["live_session"],
  attribution_lead_analyst: [
    "channel_lead",
    "sales_followup",
    "order",
  ],
};

type ToolPhase = "inspect" | "analysis" | "drilldown";
type CompletedPhaseResult = {
  toolCallId: string;
  result: any;
};
type WorkflowToolState = {
  actor: string;
  blocked: boolean;
  inspectAttempted: boolean;
  inspectCompleted: boolean;
  analysisAttempted: boolean;
  analysisCompleted: boolean;
  drilldownAttempted: boolean;
  registeredDatasetIds: Set<string>;
  completedPhaseResults: Map<ToolPhase, CompletedPhaseResult>;
};

const ANALYST_ROLE = Type.Union([
  Type.Literal("content_growth_analyst"),
  Type.Literal("live_conversion_analyst"),
  Type.Literal("attribution_lead_analyst"),
]);
const DOMAIN = Type.Union([
  Type.Literal("content_growth"),
  Type.Literal("live_conversion"),
  Type.Literal("attribution_leads"),
]);
const DATASET_TYPE = Type.Union([
  Type.Literal("short_video"),
  Type.Literal("live_session"),
  Type.Literal("account"),
  Type.Literal("channel_lead"),
  Type.Literal("sales_followup"),
  Type.Literal("order"),
]);
const DIMENSION = Type.Union([
  Type.Literal("account"),
  Type.Literal("content"),
  Type.Literal("publish_time"),
  Type.Literal("live_session"),
  Type.Literal("channel"),
  Type.Literal("lead_source"),
  Type.Literal("sales_owner"),
  Type.Literal("order_status"),
]);
const WORKFLOW_RUN_ID = Type.String({ pattern: "^wf_[A-Za-z0-9_-]+$" });
const DATASET_ID = Type.String({ pattern: "^ds_[A-Za-z0-9_-]+$" });
const TOP_N = Type.Integer({ minimum: 1, maximum: 50 });

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function enforceSingleToolTurn(payload: unknown): unknown {
  if (!isRecord(payload) || !Array.isArray(payload.tools) || payload.tools.length === 0) {
    return payload;
  }
  const existingToolChoice = isRecord(payload.tool_choice)
    ? payload.tool_choice
    : { type: "auto" };
  return {
    ...payload,
    tool_choice: {
      ...existingToolChoice,
      type:
        typeof existingToolChoice.type === "string"
          ? existingToolChoice.type
          : "auto",
      disable_parallel_tool_use: true,
    },
  };
}

function actorForTool(
  name: string,
  args: Record<string, unknown>,
): string {
  if (typeof args.caller_role === "string") return args.caller_role;
  if (name === "analyze_short_video_data") return "content_growth_analyst";
  if (name === "analyze_live_commerce_data") return "live_conversion_analyst";
  if (name === "analyze_attribution_and_leads") {
    return "attribution_lead_analyst";
  }
  return "specialist_unknown";
}

export function workflowRunIdFromDatasetIdentity(
  args: Record<string, unknown>,
): string | null {
  const ids: string[] = [];
  if (Array.isArray(args.dataset_ids)) {
    ids.push(...args.dataset_ids.filter((item): item is string => typeof item === "string"));
  }
  if (Array.isArray(args.data_refs)) {
    for (const ref of args.data_refs) {
      if (isRecord(ref) && typeof ref.dataset_id === "string") ids.push(ref.dataset_id);
    }
  }
  const tokens = new Set(
    ids
      .map((id) => id.match(/^ds_native_([A-Za-z0-9_-]+)_\d{2}$/)?.[1] ?? null)
      .filter((item): item is string => item !== null),
  );
  return tokens.size === 1 ? `wf_native_${[...tokens][0]}` : null;
}

export function withAuthoritativeWorkflowIdentity(
  args: Record<string, unknown>,
): Record<string, unknown> {
  const workflowRunId = workflowRunIdFromDatasetIdentity(args);
  return workflowRunId ? { ...args, workflow_run_id: workflowRunId } : args;
}

function appendAuditEvent(event: Record<string, unknown>) {
  const workflowRunId = event.workflow_run_id;
  if (
    typeof workflowRunId !== "string" ||
    !WORKFLOW_RUN_ID_PATTERN.test(workflowRunId)
  ) {
    return;
  }
  try {
    fs.mkdirSync(AUDIT_ROOT, { recursive: true });
    fs.appendFileSync(
      path.join(AUDIT_ROOT, `${workflowRunId}.jsonl`),
      `${JSON.stringify(event)}\n`,
      "utf8",
    );
  } catch {
  }
}

function appendProposalAuditEvent(event: Record<string, unknown>) {
  appendAuditEvent({
    schema_version: "2.0",
    event_id: crypto.randomUUID(),
    observed_at: new Date().toISOString(),
    ...event,
  });
}

function withCoalescedProposalResult(
  completed: CompletedPhaseResult,
  proposalToolCallId: string,
): any {
  const previousDetails = isRecord(completed.result?.details)
    ? completed.result.details
    : {};
  return {
    ...completed.result,
    content: [
      ...(Array.isArray(completed.result?.content)
        ? completed.result.content
        : []),
      {
        type: "text" as const,
        text:
          "PROJECT017_PROVIDER_PROPOSAL_COALESCED: no additional business-tool execution was created; the canonical result above is authoritative.",
      },
    ],
    details: {
      ...previousDetails,
      project017ProviderProposal: {
        disposition: "coalesced",
        canonicalToolCallId: completed.toolCallId,
        proposalToolCallId,
      },
    },
    isError: false,
  };
}

function resultRunIds(payload: unknown): {
  serviceRunId: string | null;
  analysisRunId: string | null;
} {
  if (!isRecord(payload)) {
    return { serviceRunId: null, analysisRunId: null };
  }
  const packet = isRecord(payload.analysis_packet)
    ? payload.analysis_packet
    : payload;
  return {
    serviceRunId:
      typeof payload.service_run_id === "string"
        ? payload.service_run_id
        : typeof packet.service_run_id === "string"
          ? packet.service_run_id
          : null,
    analysisRunId:
      typeof payload.analysis_run_id === "string"
        ? payload.analysis_run_id
        : typeof packet.analysis_run_id === "string"
          ? packet.analysis_run_id
          : null,
  };
}

function resultReferenceMetadata(payload: unknown): Record<string, unknown> {
  if (!isRecord(payload)) return {};
  const manifests = Array.isArray(payload.dataset_manifests)
    ? payload.dataset_manifests.filter(isRecord)
    : [];
  const packet = isRecord(payload.analysis_packet)
    ? payload.analysis_packet
    : null;
  const datasetIds = new Set<string>();
  for (const manifest of manifests) {
    if (typeof manifest.dataset_id === "string") {
      datasetIds.add(manifest.dataset_id);
    }
  }
  if (packet && Array.isArray(packet.dataset_ids)) {
    for (const datasetId of packet.dataset_ids) {
      if (typeof datasetId === "string") datasetIds.add(datasetId);
    }
  }
  if (!packet) {
    return datasetIds.size > 0 ? { dataset_ids: [...datasetIds] } : {};
  }
  const evidenceIds = new Set<string>();
  if (Array.isArray(packet.evidence)) {
    for (const evidence of packet.evidence) {
      if (isRecord(evidence) && typeof evidence.evidence_id === "string") {
        evidenceIds.add(evidence.evidence_id);
      }
    }
  }
  const findingIds: string[] = [];
  const findingEvidenceLinks: Record<string, string[]> = {};
  if (Array.isArray(packet.findings)) {
    for (const finding of packet.findings) {
      if (!isRecord(finding) || typeof finding.finding_id !== "string") {
        continue;
      }
      const linkedEvidenceIds = Array.isArray(finding.evidence_ids)
        ? finding.evidence_ids.filter(
            (evidenceId): evidenceId is string =>
              typeof evidenceId === "string" && evidenceIds.has(evidenceId),
          )
        : [];
      findingIds.push(finding.finding_id);
      findingEvidenceLinks[finding.finding_id] = linkedEvidenceIds;
    }
  }
  return {
    dataset_ids: [...datasetIds],
    evidence_ids: [...evidenceIds],
    finding_ids: findingIds,
    finding_evidence_links: findingEvidenceLinks,
  };
}

function resultTerminalStatus(payload: unknown): string | null {
  if (!isRecord(payload)) return null;
  const packet = isRecord(payload.analysis_packet)
    ? payload.analysis_packet
    : payload;
  return typeof packet.terminal_status === "string"
    ? packet.terminal_status
    : typeof payload.terminal_status === "string"
      ? payload.terminal_status
      : null;
}

function toolPhase(name: string): ToolPhase {
  if (name === "inspect_commerce_data") return "inspect";
  if (name === "drilldown_commerce_metric") return "drilldown";
  return "analysis";
}

export default function commerceOpsMcpExtension(pi: ExtensionAPI) {
  let activeClient: Client | undefined;
  let activeTransport: StdioClientTransport | undefined;
  let connectionPromise: Promise<Client> | undefined;
  let attemptSequence = 0;
  let proposalSequence = 0;
  const workflowToolStates = new Map<string, WorkflowToolState>();

  pi.on("before_provider_request", (event) =>
    enforceSingleToolTurn(event.payload),
  );

  function prepareToolAttempt(
    name: string,
    args: Record<string, unknown>,
  ): {
    state: WorkflowToolState;
    phase: ToolPhase;
    reason: string | null;
    completedResult: CompletedPhaseResult | null;
  } {
    const workflowRunId = String(args.workflow_run_id || "");
    const actor = actorForTool(name, args);
    const phase = toolPhase(name);
    let state = workflowToolStates.get(workflowRunId);
    if (!state) {
      state = {
        actor,
        blocked: false,
        inspectAttempted: false,
        inspectCompleted: false,
        analysisAttempted: false,
        analysisCompleted: false,
        drilldownAttempted: false,
        registeredDatasetIds: new Set<string>(),
        completedPhaseResults: new Map<ToolPhase, CompletedPhaseResult>(),
      };
      workflowToolStates.set(workflowRunId, state);
    }

    let reason: string | null = null;
    let completedResult: CompletedPhaseResult | null = null;
    if (state.blocked) {
      reason = "previous_specialist_tool_blocked";
    } else if (state.actor !== actor) {
      reason = "workflow_specialist_role_mismatch";
    } else if (phase === "inspect") {
      if (state.inspectAttempted) {
        completedResult = state.completedPhaseResults.get(phase) ?? null;
        if (!completedResult) reason = "concurrent_inspect_proposal_forbidden";
      } else {
        state.inspectAttempted = true;
        const refs = Array.isArray(args.data_refs) ? args.data_refs : [];
        const datasetTypes = new Set(
          refs
            .filter(isRecord)
            .map((item) => String(item.dataset_type || "")),
        );
        state.registeredDatasetIds = new Set(
          refs
            .filter(isRecord)
            .map((item) => String(item.dataset_id || ""))
            .filter(Boolean),
        );
        const missingTypes = (REQUIRED_INSPECT_DATASET_TYPES[actor] ?? []).filter(
          (datasetType) => !datasetTypes.has(datasetType),
        );
        if (missingTypes.length > 0) {
          reason = `required_inspect_dataset_types_missing:${missingTypes.join(",")}`;
        }
      }
    } else if (phase === "analysis") {
      if (!state.inspectCompleted) {
        reason = "inspect_must_complete_before_analysis";
      } else if (state.analysisAttempted) {
        completedResult = state.completedPhaseResults.get(phase) ?? null;
        if (!completedResult) reason = "concurrent_analysis_proposal_forbidden";
      } else {
        state.analysisAttempted = true;
        const datasetIds = Array.isArray(args.dataset_ids)
          ? args.dataset_ids.map(String)
          : [];
        if (
          datasetIds.length === 0 ||
          datasetIds.some((datasetId) => !state.registeredDatasetIds.has(datasetId))
        ) {
          reason = "analysis_dataset_not_registered_by_inspect";
        }
      }
    } else if (state.drilldownAttempted) {
      completedResult = state.completedPhaseResults.get(phase) ?? null;
      if (!completedResult) reason = "concurrent_drilldown_proposal_forbidden";
    } else if (!state.analysisCompleted) {
      state.drilldownAttempted = true;
      reason = "analysis_must_complete_before_drilldown";
    } else {
      state.drilldownAttempted = true;
    }

    if (reason) state.blocked = true;
    return { state, phase, reason, completedResult };
  }

  async function createClient(signal?: AbortSignal): Promise<Client> {
    const transport = new StdioClientTransport({
      command: process.env.COMMERCE_OPS_PYTHON?.trim() || "python",
      args: ["-B", "-m", "commerce_ops.mcp_server"],
      cwd: PROJECT_ROOT,
      env: {
        ...getDefaultEnvironment(),
        COMMERCE_OPS_DATA_ROOT: DATA_ROOT,
      },
      stderr: "pipe",
    });
    const client = new Client({
      name: "project017-commerce-ops-pi-extension",
      version: "0.1.0",
    });
    try {
      await client.connect(transport, {
        signal,
        timeout: CALL_TIMEOUT_MS,
        maxTotalTimeout: CALL_TIMEOUT_MS,
      });
      const listed = await client.listTools(undefined, {
        signal,
        timeout: CALL_TIMEOUT_MS,
        maxTotalTimeout: CALL_TIMEOUT_MS,
      });
      const discovered = new Set(listed.tools.map((tool) => tool.name));
      const missing = [...EXPECTED_MCP_TOOLS].filter(
        (name) => !discovered.has(name),
      );
      if (missing.length > 0) {
        throw new Error(`commerce_ops MCP 缺少工具：${missing.join(", ")}`);
      }
      transport.onerror = () => {
        if (activeTransport === transport) {
          activeTransport = undefined;
          activeClient = undefined;
        }
      };
      transport.onclose = () => {
        if (activeTransport === transport) {
          activeTransport = undefined;
          activeClient = undefined;
        }
      };
      activeTransport = transport;
      activeClient = client;
      return client;
    } catch (error) {
      await transport.close().catch(() => undefined);
      throw error;
    }
  }

  async function getClient(signal?: AbortSignal): Promise<Client> {
    if (activeClient) return activeClient;
    if (!connectionPromise) {
      connectionPromise = createClient(signal).finally(() => {
        connectionPromise = undefined;
      });
    }
    return connectionPromise;
  }

  async function callMcpTool(
    piToolName: string,
    name: string,
    args: Record<string, unknown>,
    toolCallId: string,
    signal?: AbortSignal,
  ): Promise<any> {
    if (!EXPECTED_MCP_TOOLS.has(name)) {
      throw new Error(`未授权的 commerce_ops MCP 工具：${name}`);
    }
    args = withAuthoritativeWorkflowIdentity(args);
    const workflowRunId = String(args.workflow_run_id || "");
    const prepared = prepareToolAttempt(name, args);
    const proposalNumber = ++proposalSequence;
    const proposalId = `child-proposal:${toolCallId}`;
    const proposalAudit = {
      proposal_id: proposalId,
      workflow_run_id: workflowRunId,
      layer: "specialist_tool",
      actor: actorForTool(name, args),
      tool_name: piToolName,
      tool_call_id: toolCallId,
      proposal_number: proposalNumber,
    };
    appendProposalAuditEvent({
      ...proposalAudit,
      event_type: "provider_proposal_received",
      disposition: "pending",
      canonical_tool_call_id: null,
      reason_code: null,
    });
    if (prepared.completedResult) {
      appendProposalAuditEvent({
        ...proposalAudit,
        event_type: "provider_proposal_disposition",
        disposition: "coalesced",
        canonical_tool_call_id: prepared.completedResult.toolCallId,
        reason_code: "duplicate_phase_provider_proposal_coalesced",
      });
      return withCoalescedProposalResult(
        prepared.completedResult,
        toolCallId,
      );
    }
    const attemptNumber = ++attemptSequence;
    const attemptId = `child:${toolCallId}`;
    const commonAudit = {
      schema_version: "1.0",
      attempt_id: attemptId,
      workflow_run_id: workflowRunId,
      layer: "specialist_tool",
      actor: actorForTool(name, args),
      tool_name: piToolName,
      tool_call_id: toolCallId,
      attempt_number: attemptNumber,
      automatic_retry: false,
    };
    if (prepared.reason) {
      appendProposalAuditEvent({
        ...proposalAudit,
        event_type: "provider_proposal_disposition",
        disposition: "rejected",
        canonical_tool_call_id: null,
        reason_code: prepared.reason,
      });
      appendAuditEvent({
        ...commonAudit,
        event_id: crypto.randomUUID(),
        event_type: "attempt_started",
        status: "started",
        observed_at: new Date().toISOString(),
      });
      appendAuditEvent({
        ...commonAudit,
        event_id: crypto.randomUUID(),
        event_type: "attempt_finished",
        status: "blocked",
        reason_code: prepared.reason,
        observed_at: new Date().toISOString(),
      });
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({
              schema_version: "1.0",
              workflow_run_id: workflowRunId,
              terminal_status: "blocked",
              reason_code: prepared.reason,
              service_run_id: null,
              automatic_retry: false,
            }),
          },
        ],
        details: {
          mcpToolName: name,
          guardBlocked: true,
          reasonCode: prepared.reason,
          syntheticOnly: true,
          automaticRetry: false,
        },
        isError: true,
      };
    }
    appendProposalAuditEvent({
      ...proposalAudit,
      event_type: "provider_proposal_disposition",
      disposition: "admitted",
      canonical_tool_call_id: toolCallId,
      reason_code: null,
    });
    appendAuditEvent({
      ...commonAudit,
      event_id: crypto.randomUUID(),
      event_type: "attempt_started",
      status: "started",
      observed_at: new Date().toISOString(),
    });
    let result: any;
    let finished = false;
    try {
      const client = await getClient(signal);
      result = await client.callTool(
        { name, arguments: args },
        undefined,
        {
          signal,
          timeout: CALL_TIMEOUT_MS,
          maxTotalTimeout: CALL_TIMEOUT_MS,
        },
      );
      if (result.isError) {
        prepared.state.blocked = true;
        appendAuditEvent({
          ...commonAudit,
          event_id: crypto.randomUUID(),
          event_type: "attempt_finished",
          status: "failed",
          reason_code: "mcp_tool_error",
          observed_at: new Date().toISOString(),
        });
        finished = true;
        const safeText = result.content
          .filter((item) => item.type === "text")
          .map((item) => item.text)
          .join("\n");
        throw new Error(safeText || `${name} 调用失败`);
      }
      const runIds = resultRunIds(
        result.structuredContent ??
          ("toolResult" in result ? result.toolResult : undefined),
      );
      const structuredPayload =
        result.structuredContent ??
        ("toolResult" in result ? result.toolResult : undefined);
      const terminalStatus = resultTerminalStatus(structuredPayload);
      const businessBlocked = terminalStatus === "blocked";
      const businessFailed = terminalStatus === "uncertain";
      const referenceMetadata = resultReferenceMetadata(structuredPayload);
      appendAuditEvent({
        ...commonAudit,
        event_id: crypto.randomUUID(),
        event_type: "attempt_finished",
        status: businessBlocked
          ? "blocked"
          : businessFailed
            ? "failed"
            : "completed",
        service_run_id: runIds.serviceRunId,
        analysis_run_id: runIds.analysisRunId,
        ...referenceMetadata,
        reason_code: businessBlocked
          ? "mcp_business_terminal_blocked"
          : businessFailed
            ? "mcp_business_terminal_uncertain"
            : null,
        observed_at: new Date().toISOString(),
      });
      if (businessBlocked || businessFailed) {
        prepared.state.blocked = true;
      } else if (prepared.phase === "inspect") {
        prepared.state.inspectCompleted = true;
      } else if (prepared.phase === "analysis") {
        prepared.state.analysisCompleted = true;
      }
      finished = true;
    } catch (error) {
      prepared.state.blocked = true;
      if (!finished) {
        appendAuditEvent({
          ...commonAudit,
          event_id: crypto.randomUUID(),
          event_type: "attempt_finished",
          status: "failed",
          reason_code: "mcp_transport_or_contract_error",
          observed_at: new Date().toISOString(),
        });
      }
      throw error;
    }
    const structuredPayload =
      result.structuredContent ??
      ("toolResult" in result ? result.toolResult : undefined);
    const terminalStatus = resultTerminalStatus(structuredPayload);
    const businessError = ["blocked", "uncertain"].includes(
      String(terminalStatus),
    );
    let finalResult: any;
    if ("toolResult" in result) {
      finalResult = {
        content: [
          { type: "text" as const, text: JSON.stringify(result.toolResult) },
        ],
        details: {
          mcpToolName: name,
          legacyResult: true,
          project017ProviderProposal: {
            disposition: "admitted",
            canonicalToolCallId: toolCallId,
            proposalToolCallId: toolCallId,
          },
        },
        ...(businessError ? { isError: true } : {}),
      };
    } else {
      const textBlocks = result.content
        .filter((item) => item.type === "text")
        .map((item) => ({ type: "text" as const, text: item.text }));
      const fallback = result.structuredContent
        ? [
            {
              type: "text" as const,
              text: JSON.stringify(result.structuredContent),
            },
          ]
        : [{ type: "text" as const, text: "{}" }];
      finalResult = {
        content: textBlocks.length > 0 ? textBlocks : fallback,
        details: {
          mcpToolName: name,
          structuredContent: result.structuredContent ?? null,
          syntheticOnly: true,
          automaticRetry: false,
          project017ProviderProposal: {
            disposition: "admitted",
            canonicalToolCallId: toolCallId,
            proposalToolCallId: toolCallId,
          },
        },
        ...(businessError ? { isError: true } : {}),
      };
    }
    if (!businessError) {
      prepared.state.completedPhaseResults.set(prepared.phase, {
        toolCallId,
        result: finalResult,
      });
    }
    return finalResult;
  }

  pi.registerTool({
    name: "commerce_ops_inspect_commerce_data",
    executionMode: "sequential",
    label: "电商数据准入检查",
    description:
      "登记当前专业任务所需的 synthetic 数据集并返回 DatasetManifest，不输出经营结论。根对象仅允许 workflow_run_id、caller_role、data_refs、requested_domains 和可选 max_rows_for_profile；根对象不得传 synthetic，synthetic=true 只能放在每个 data_refs[] 项内。Schema 参数校验失败也计为一次工具尝试，禁止用第二次调用隐藏失败尝试。",
    parameters: Type.Object(
      {
        workflow_run_id: WORKFLOW_RUN_ID,
        caller_role: ANALYST_ROLE,
        data_refs: Type.Array(
          Type.Object(
            {
              dataset_id: DATASET_ID,
              dataset_type: DATASET_TYPE,
              file_path: Type.String({ minLength: 1 }),
              synthetic: Type.Optional(Type.Literal(true)),
            },
            { additionalProperties: false },
          ),
          { minItems: 1, uniqueItems: true },
        ),
        requested_domains: Type.Array(DOMAIN, {
          minItems: 1,
          uniqueItems: true,
        }),
        max_rows_for_profile: Type.Optional(
          Type.Integer({ minimum: 1, maximum: 100_000 }),
        ),
      },
      { additionalProperties: false },
    ),
    async execute(toolCallId, params, signal) {
      return callMcpTool(
        "commerce_ops_inspect_commerce_data",
        "inspect_commerce_data",
        {
          ...params,
          data_refs: params.data_refs.map((item) => ({
            ...item,
            synthetic: true,
          })),
        },
        toolCallId,
        signal,
      );
    },
  });

  pi.registerTool({
    name: "commerce_ops_analyze_short_video_data",
    executionMode: "sequential",
    label: "短视频内容增长分析",
    description:
      "基于已在同一 MCP 进程登记的数据集计算短视频漏斗；每个 workflow_run_id 只发起一次，不得并行或使用不同参数重复调用；结果不确定时不自动重试。",
    parameters: Type.Object(
      {
        workflow_run_id: WORKFLOW_RUN_ID,
        dataset_ids: Type.Array(DATASET_ID, { minItems: 1, uniqueItems: true }),
        requested_dimensions: Type.Optional(
          Type.Array(
            Type.Union([
              Type.Literal("account"),
              Type.Literal("content"),
              Type.Literal("publish_time"),
            ]),
            { uniqueItems: true, maxItems: 3 },
          ),
        ),
        top_n: Type.Optional(TOP_N),
        synthetic: Type.Optional(Type.Literal(true)),
      },
      { additionalProperties: false },
    ),
    async execute(toolCallId, params, signal) {
      return callMcpTool(
        "commerce_ops_analyze_short_video_data",
        "analyze_short_video_data",
        { ...params, synthetic: true },
        toolCallId,
        signal,
      );
    },
  });

  pi.registerTool({
    name: "commerce_ops_analyze_live_commerce_data",
    executionMode: "sequential",
    label: "直播转化漏斗分析",
    description:
      "基于已在同一 MCP 进程登记的数据集计算直播承接漏斗；结果不确定时不自动重试。",
    parameters: Type.Object(
      {
        workflow_run_id: WORKFLOW_RUN_ID,
        dataset_ids: Type.Array(DATASET_ID, { minItems: 1, uniqueItems: true }),
        requested_dimensions: Type.Optional(
          Type.Array(
            Type.Union([
              Type.Literal("account"),
              Type.Literal("live_session"),
              Type.Literal("channel"),
            ]),
            { uniqueItems: true, maxItems: 3 },
          ),
        ),
        top_n: Type.Optional(TOP_N),
        synthetic: Type.Optional(Type.Literal(true)),
      },
      { additionalProperties: false },
    ),
    async execute(toolCallId, params, signal) {
      return callMcpTool(
        "commerce_ops_analyze_live_commerce_data",
        "analyze_live_commerce_data",
        { ...params, synthetic: true },
        toolCallId,
        signal,
      );
    },
  });

  pi.registerTool({
    name: "commerce_ops_analyze_attribution_and_leads",
    executionMode: "sequential",
    label: "渠道归因与线索分析",
    description:
      "只在稳定脱敏关联键覆盖范围内分析渠道、线索和订单；无成本字段时拒绝 ROI。",
    parameters: Type.Object(
      {
        workflow_run_id: WORKFLOW_RUN_ID,
        dataset_ids: Type.Array(DATASET_ID, { minItems: 1, uniqueItems: true }),
        requested_dimensions: Type.Optional(
          Type.Array(
            Type.Union([
              Type.Literal("channel"),
              Type.Literal("lead_source"),
              Type.Literal("sales_owner"),
              Type.Literal("order_status"),
            ]),
            { uniqueItems: true, maxItems: 4 },
          ),
        ),
        link_orders: Type.Optional(Type.Boolean()),
        calculate_roi: Type.Optional(Type.Boolean()),
        top_n: Type.Optional(TOP_N),
        synthetic: Type.Optional(Type.Literal(true)),
      },
      { additionalProperties: false },
    ),
    async execute(toolCallId, params, signal) {
      return callMcpTool(
        "commerce_ops_analyze_attribution_and_leads",
        "analyze_attribution_and_leads",
        { ...params, synthetic: true },
        toolCallId,
        signal,
      );
    },
  });

  pi.registerTool({
    name: "commerce_ops_drilldown_commerce_metric",
    executionMode: "sequential",
    label: "电商指标受限钻取",
    description:
      "只对已完成基础分析的 evidence 做 manifest 允许维度聚合，不能扩大权限。",
    parameters: Type.Object(
      {
        workflow_run_id: WORKFLOW_RUN_ID,
        caller_role: ANALYST_ROLE,
        base_analysis_run_id: Type.String({
          pattern: "^analysis_[A-Za-z0-9_-]+$",
        }),
        evidence_id: Type.String({ pattern: "^ev_[A-Za-z0-9_-]+$" }),
        dimension: DIMENSION,
        filters: Type.Optional(
          Type.Record(Type.String(), Type.String(), {
            maxProperties: 10,
          }),
        ),
        top_n: Type.Optional(TOP_N),
        synthetic: Type.Optional(Type.Literal(true)),
      },
      { additionalProperties: false },
    ),
    async execute(toolCallId, params, signal) {
      return callMcpTool(
        "commerce_ops_drilldown_commerce_metric",
        "drilldown_commerce_metric",
        { ...params, synthetic: true },
        toolCallId,
        signal,
      );
    },
  });

  pi.on("session_shutdown", async () => {
    const transport = activeTransport;
    activeTransport = undefined;
    activeClient = undefined;
    connectionPromise = undefined;
    workflowToolStates.clear();
    if (transport) await transport.close().catch(() => undefined);
  });
}
