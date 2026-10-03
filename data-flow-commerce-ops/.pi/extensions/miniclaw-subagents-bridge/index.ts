// Compatibility bridge for MiniClaw commit 3ff1c8d6a0707f4a9f0957ff411758e5e141583a
// and @tintinweb/pi-subagents 0.16.1. Remove it when MiniClaw resolves the
// package's pi.extensions entry, otherwise the tools could be registered twice.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";

import subagentsExtension from "file:///D:/Workspace/project014-miniclaw-deployment/upstream/miniclaw/container/agent-runner/node_modules/@tintinweb/pi-subagents/dist/index.js";

const PROJECT017_AGENT_DISPATCH_POLICY =
  "project017_agent_dispatch_deterministic_admission_v2";
const PROJECT017_POLICY_TEXT =
  'Project017 is not a Git repository. Omit the Agent isolation argument entirely; isolation="worktree" is forbidden. Every Agent call must explicitly set run_in_background=false. The runtime admits unique subagent_type calls in provider order and executes them sequentially. A repeated provider proposal for an already completed subagent_type is audited and coalesced onto the first result without creating another parent Agent attempt. Any Agent argument-validation or real dispatch failure counts as a parent Agent attempt, blocks the current branch, and forbids another Agent call in this session. Final reporting must merge admitted parent Agent attempts with specialist business-tool attempts; coalesced provider proposals are reported separately and are not failures.';
const PROJECT_ROOT =
  process.env.COMMERCE_OPS_PROJECT_ROOT?.trim() ||
  "D:\\Workspace\\project017-data-flow-commerce-ops";
const AUDIT_ROOT = path.join(PROJECT_ROOT, "runtime", "data", "native-audit");
const WORKFLOW_RUN_ID_PATTERN = /\bwf_[A-Za-z0-9_-]+\b/;

type DispatchAttempt = {
  attemptNumber: number;
  toolCallId: string;
  workflowRunId: string | null;
  subagentType: string | null;
  isolationProvided: boolean;
  runInBackgroundProvided: boolean;
  runInBackgroundValue: boolean | null;
  startedAt: string;
  startedRecorded: boolean;
  finishedRecorded: boolean;
  status: "started" | "completed" | "failed" | "blocked";
  reason: string | null;
  strategyReferenceValidation: "pass" | "failed" | null;
  strategyReferenceErrorCodes: string[];
};

type DispatchProposal = {
  proposalNumber: number;
  toolCallId: string;
  workflowRunId: string | null;
  subagentType: string | null;
  isolationProvided: boolean;
  runInBackgroundProvided: boolean;
  runInBackgroundValue: boolean | null;
  receivedAt: string;
  disposition: "pending" | "admitted" | "coalesced" | "rejected";
  canonicalToolCallId: string | null;
  reason: string | null;
  receivedRecorded: boolean;
  dispositionRecorded: boolean;
};

type ToolDefinition = {
  name: string;
  description: string;
  promptGuidelines?: string[];
  execute: (...args: any[]) => Promise<any>;
  [key: string]: any;
};

type ExtensionApi = {
  registerTool: (tool: ToolDefinition) => void;
  on: (event: string, handler: (...args: any[]) => any) => void;
  [key: string]: any;
};

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

function sessionIdFromContext(ctx: any): string | null {
  try {
    return ctx?.sessionManager?.getSessionId?.() ?? null;
  } catch {
    return null;
  }
}

export function workflowRunIdFromParams(
  params: Record<string, unknown>,
): string | null {
  try {
    const serialized = JSON.stringify(params);
    const datasetMatch = serialized.match(
      /\bds_native_([A-Za-z0-9_-]+)_\d{2}\b/,
    );
    if (datasetMatch) return `wf_native_${datasetMatch[1]}`;
    return serialized.match(WORKFLOW_RUN_ID_PATTERN)?.[0] ?? null;
  } catch {
    return null;
  }
}

export function withAuthoritativeWorkflowPrompt(
  params: Record<string, unknown>,
): Record<string, unknown> {
  const workflowRunId = workflowRunIdFromParams(params);
  if (
    !workflowRunId ||
    typeof params.prompt !== "string" ||
    params.prompt.includes(`PROJECT017_AUTHORITATIVE_WORKFLOW_RUN_ID=${workflowRunId}`)
  ) {
    return params;
  }
  return {
    ...params,
    prompt:
      `PROJECT017_AUTHORITATIVE_WORKFLOW_RUN_ID=${workflowRunId}\n` +
      "Every tool call and every returned packet must use this exact workflow_run_id literal; do not shorten, rename, or regenerate it.\n" +
      params.prompt,
  };
}

type StrategyReferenceCatalog = {
  analysisRunIds: Set<string>;
  datasetIds: Set<string>;
  evidenceIds: Set<string>;
  findingEvidenceLinks: Map<string, Set<string>>;
};

type StrategyReferenceValidation = {
  status: "pass" | "failed";
  errorCodes: string[];
  catalogCounts: {
    analysisRunIds: number;
    datasetIds: number;
    evidenceIds: number;
    findingIds: number;
  };
  actionCount: number;
};

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function strategyReferenceCatalog(
  workflowRunId: string,
): StrategyReferenceCatalog {
  const catalog: StrategyReferenceCatalog = {
    analysisRunIds: new Set(),
    datasetIds: new Set(),
    evidenceIds: new Set(),
    findingEvidenceLinks: new Map(),
  };
  try {
    const auditPath = path.join(AUDIT_ROOT, `${workflowRunId}.jsonl`);
    const lines = fs.readFileSync(auditPath, "utf8").split(/\r?\n/);
    for (const line of lines) {
      if (!line) continue;
      let event: unknown;
      try {
        event = JSON.parse(line);
      } catch {
        continue;
      }
      if (
        !isRecord(event) ||
        event.workflow_run_id !== workflowRunId ||
        event.layer !== "specialist_tool" ||
        event.event_type !== "attempt_finished" ||
        event.status !== "completed" ||
        typeof event.analysis_run_id !== "string"
      ) {
        continue;
      }
      catalog.analysisRunIds.add(event.analysis_run_id);
      for (const datasetId of strings(event.dataset_ids)) {
        catalog.datasetIds.add(datasetId);
      }
      for (const evidenceId of strings(event.evidence_ids)) {
        catalog.evidenceIds.add(evidenceId);
      }
      if (isRecord(event.finding_evidence_links)) {
        for (const [findingId, evidenceIds] of Object.entries(
          event.finding_evidence_links,
        )) {
          catalog.findingEvidenceLinks.set(
            findingId,
            new Set(strings(evidenceIds)),
          );
        }
      }
    }
  } catch {
  }
  return catalog;
}

function jsonObjectsFromText(text: string): Record<string, unknown>[] {
  const objects: Record<string, unknown>[] = [];
  for (let start = 0; start < text.length; start += 1) {
    if (text[start] !== "{") continue;
    let depth = 0;
    let inString = false;
    let escaped = false;
    for (let index = start; index < text.length; index += 1) {
      const character = text[index];
      if (inString) {
        if (escaped) escaped = false;
        else if (character === "\\") escaped = true;
        else if (character === '"') inString = false;
        continue;
      }
      if (character === '"') inString = true;
      else if (character === "{") depth += 1;
      else if (character === "}") {
        depth -= 1;
        if (depth !== 0) continue;
        try {
          const parsed = JSON.parse(text.slice(start, index + 1));
          if (isRecord(parsed)) objects.push(parsed);
        } catch {
        }
        start = index;
        break;
      }
    }
  }
  return objects;
}

function decisionPacketFromResult(result: any): Record<string, unknown> | null {
  const text = (Array.isArray(result?.content) ? result.content : [])
    .filter((item: unknown) => isRecord(item) && item.type === "text")
    .map((item: Record<string, unknown>) => String(item.text ?? ""))
    .join("\n");
  return (
    jsonObjectsFromText(text).find(
      (item) => item.message_type === "decision_packet",
    ) ?? null
  );
}

export function validateStrategyReferences(
  workflowRunId: string,
  result: any,
): StrategyReferenceValidation {
  const catalog = strategyReferenceCatalog(workflowRunId);
  const packet = decisionPacketFromResult(result);
  const errors = new Set<string>();
  const catalogCounts = {
    analysisRunIds: catalog.analysisRunIds.size,
    datasetIds: catalog.datasetIds.size,
    evidenceIds: catalog.evidenceIds.size,
    findingIds: catalog.findingEvidenceLinks.size,
  };
  if (
    catalog.analysisRunIds.size === 0 ||
    catalog.datasetIds.size === 0 ||
    catalog.evidenceIds.size === 0 ||
    catalog.findingEvidenceLinks.size === 0
  ) {
    errors.add("strategy_reference_catalog_missing");
  }
  if (!packet) {
    errors.add("strategy_decision_packet_missing_or_invalid");
    return {
      status: "failed",
      errorCodes: [...errors],
      catalogCounts,
      actionCount: 0,
    };
  }
  if (packet.workflow_run_id !== workflowRunId) {
    errors.add("strategy_workflow_run_id_mismatch");
  }
  const sourceAnalysisIds = strings(packet.source_analysis_ids);
  const uniqueSourceAnalysisIds = new Set(sourceAnalysisIds);
  if (
    sourceAnalysisIds.length !== catalog.analysisRunIds.size ||
    uniqueSourceAnalysisIds.size !== sourceAnalysisIds.length ||
    sourceAnalysisIds.some((item) => !catalog.analysisRunIds.has(item))
  ) {
    errors.add("strategy_source_analysis_ids_mismatch");
  }
  const actions = Array.isArray(packet.actions)
    ? packet.actions.filter(isRecord)
    : [];
  if (!Array.isArray(packet.actions) || actions.length !== packet.actions.length) {
    errors.add("strategy_actions_invalid");
  }
  for (const action of actions) {
    const findingIds = strings(action.finding_ids);
    const evidenceIds = strings(action.evidence_ids);
    if (
      findingIds.length === 0 ||
      findingIds.some((item) => !catalog.findingEvidenceLinks.has(item))
    ) {
      errors.add("strategy_finding_id_not_in_catalog");
    }
    if (
      evidenceIds.length === 0 ||
      evidenceIds.some((item) => !catalog.evidenceIds.has(item))
    ) {
      errors.add("strategy_evidence_id_not_in_catalog");
    }
    const linkedEvidenceIds = new Set(
      findingIds.flatMap((findingId) => [
        ...(catalog.findingEvidenceLinks.get(findingId) ?? new Set()),
      ]),
    );
    if (evidenceIds.some((item) => !linkedEvidenceIds.has(item))) {
      errors.add("strategy_evidence_not_linked_to_finding");
    }
    const verificationMetric = isRecord(action.verification_metric)
      ? action.verification_metric
      : null;
    const datasetIds = strings(verificationMetric?.dataset_ids);
    if (
      datasetIds.length === 0 ||
      datasetIds.some((item) => !catalog.datasetIds.has(item))
    ) {
      errors.add("strategy_dataset_id_not_in_catalog");
    }
  }
  return {
    status: errors.size === 0 ? "pass" : "failed",
    errorCodes: [...errors],
    catalogCounts,
    actionCount: actions.length,
  };
}

function appendAuditEvent(
  attempt: DispatchAttempt,
  eventType: "attempt_started" | "attempt_finished",
  sessionId: string | null,
  reasonCode: string | null = null,
): boolean {
  if (!attempt.workflowRunId) return false;
  const event = {
    schema_version: "1.0",
    event_id: crypto.randomUUID(),
    event_type: eventType,
    attempt_id: `parent:${attempt.toolCallId}`,
    workflow_run_id: attempt.workflowRunId,
    session_id: sessionId,
    layer: "parent_dispatch",
    actor: "commerce_ops_supervisor",
    tool_name: "Agent",
    tool_call_id: attempt.toolCallId,
    attempt_number: attempt.attemptNumber,
    status: attempt.status,
    subagent_type: attempt.subagentType,
    isolation_argument_present: attempt.isolationProvided,
    run_in_background_argument_present: attempt.runInBackgroundProvided,
    run_in_background_value: attempt.runInBackgroundValue,
    strategy_reference_validation: attempt.strategyReferenceValidation,
    strategy_reference_error_codes: attempt.strategyReferenceErrorCodes,
    reason_code: reasonCode,
    observed_at: new Date().toISOString(),
    automatic_retry: false,
  };
  try {
    fs.mkdirSync(AUDIT_ROOT, { recursive: true });
    fs.appendFileSync(
      path.join(AUDIT_ROOT, `${attempt.workflowRunId}.jsonl`),
      `${JSON.stringify(event)}\n`,
      "utf8",
    );
    return true;
  } catch {
    return false;
  }
}

function appendProposalAuditEvent(
  proposal: DispatchProposal,
  eventType: "provider_proposal_received" | "provider_proposal_disposition",
  sessionId: string | null,
): boolean {
  if (!proposal.workflowRunId) return false;
  const event = {
    schema_version: "2.0",
    event_id: crypto.randomUUID(),
    event_type: eventType,
    proposal_id: `parent-proposal:${proposal.toolCallId}`,
    workflow_run_id: proposal.workflowRunId,
    session_id: sessionId,
    layer: "parent_dispatch",
    actor: "commerce_ops_supervisor",
    tool_name: "Agent",
    tool_call_id: proposal.toolCallId,
    proposal_number: proposal.proposalNumber,
    disposition: proposal.disposition,
    canonical_tool_call_id: proposal.canonicalToolCallId,
    subagent_type: proposal.subagentType,
    isolation_argument_present: proposal.isolationProvided,
    run_in_background_argument_present: proposal.runInBackgroundProvided,
    run_in_background_value: proposal.runInBackgroundValue,
    reason_code: proposal.reason,
    observed_at: new Date().toISOString(),
  };
  try {
    fs.mkdirSync(AUDIT_ROOT, { recursive: true });
    fs.appendFileSync(
      path.join(AUDIT_ROOT, `${proposal.workflowRunId}.jsonl`),
      `${JSON.stringify(event)}\n`,
      "utf8",
    );
    return true;
  } catch {
    return false;
  }
}

export default function project017SubagentsBridge(pi: ExtensionApi) {
  let dispatchLocked = false;
  let dispatchLockAttemptNumber: number | null = null;
  let currentSessionId: string | null = null;
  const attempts: DispatchAttempt[] = [];
  const pendingAttempts = new Map<string, DispatchAttempt>();
  const proposals: DispatchProposal[] = [];
  const pendingProposals = new Map<string, DispatchProposal>();
  const completedRoleResults = new Map<
    string,
    { toolCallId: string; result: any }
  >();

  const resetSessionAudit = (sessionId: string | null) => {
    dispatchLocked = false;
    dispatchLockAttemptNumber = null;
    currentSessionId = sessionId;
    attempts.length = 0;
    pendingAttempts.clear();
    proposals.length = 0;
    pendingProposals.clear();
    completedRoleResults.clear();
  };

  const snapshot = () => ({
    policyId: PROJECT017_AGENT_DISPATCH_POLICY,
    sessionId: currentSessionId,
    dispatchLocked,
    dispatchLockAttemptNumber,
    parentAgentAttemptCount: attempts.length,
    attempts: attempts.map((attempt) => ({ ...attempt })),
    providerProposalCount: proposals.length,
    coalescedProviderProposalCount: proposals.filter(
      (proposal) => proposal.disposition === "coalesced",
    ).length,
    rejectedProviderProposalCount: proposals.filter(
      (proposal) => proposal.disposition === "rejected",
    ).length,
    proposals: proposals.map((proposal) => ({ ...proposal })),
    finalAttemptLedgerRequired:
      "merge_parent_agent_attempts_with_specialist_business_tool_attempts",
  });

  const createProposal = (
    toolCallId: string,
    params: Record<string, unknown>,
  ): DispatchProposal => {
    const proposal: DispatchProposal = {
      proposalNumber: proposals.length + 1,
      toolCallId,
      workflowRunId: workflowRunIdFromParams(params),
      subagentType:
        typeof params.subagent_type === "string" ? params.subagent_type : null,
      isolationProvided: Object.prototype.hasOwnProperty.call(
        params,
        "isolation",
      ),
      runInBackgroundProvided: Object.prototype.hasOwnProperty.call(
        params,
        "run_in_background",
      ),
      runInBackgroundValue:
        typeof params.run_in_background === "boolean"
          ? params.run_in_background
          : null,
      receivedAt: new Date().toISOString(),
      disposition: "pending",
      canonicalToolCallId: null,
      reason: null,
      receivedRecorded: false,
      dispositionRecorded: false,
    };
    proposals.push(proposal);
    pendingProposals.set(toolCallId, proposal);
    proposal.receivedRecorded = appendProposalAuditEvent(
      proposal,
      "provider_proposal_received",
      currentSessionId,
    );
    return proposal;
  };

  const enrichProposalFromParams = (
    proposal: DispatchProposal,
    params: Record<string, unknown>,
  ) => {
    proposal.workflowRunId ??= workflowRunIdFromParams(params);
    if (typeof params.subagent_type === "string") {
      proposal.subagentType = params.subagent_type;
    }
    proposal.isolationProvided = Object.prototype.hasOwnProperty.call(
      params,
      "isolation",
    );
    proposal.runInBackgroundProvided = Object.prototype.hasOwnProperty.call(
      params,
      "run_in_background",
    );
    proposal.runInBackgroundValue =
      typeof params.run_in_background === "boolean"
        ? params.run_in_background
        : null;
    if (!proposal.receivedRecorded) {
      proposal.receivedRecorded = appendProposalAuditEvent(
        proposal,
        "provider_proposal_received",
        currentSessionId,
      );
    }
  };

  const finishProposal = (
    proposal: DispatchProposal,
    disposition: "admitted" | "coalesced" | "rejected",
    reason: string | null,
    canonicalToolCallId: string | null = null,
  ) => {
    proposal.disposition = disposition;
    proposal.reason = reason;
    proposal.canonicalToolCallId = canonicalToolCallId;
    if (proposal.dispositionRecorded) return;
    proposal.dispositionRecorded = true;
    appendProposalAuditEvent(
      proposal,
      "provider_proposal_disposition",
      currentSessionId,
    );
  };

  const createAttempt = (
    toolCallId: string,
    params: Record<string, unknown>,
  ): DispatchAttempt => {
    const attempt: DispatchAttempt = {
      attemptNumber: attempts.length + 1,
      toolCallId,
      workflowRunId: workflowRunIdFromParams(params),
      subagentType:
        typeof params.subagent_type === "string" ? params.subagent_type : null,
      isolationProvided: Object.prototype.hasOwnProperty.call(
        params,
        "isolation",
      ),
      runInBackgroundProvided: Object.prototype.hasOwnProperty.call(
        params,
        "run_in_background",
      ),
      runInBackgroundValue:
        typeof params.run_in_background === "boolean"
          ? params.run_in_background
          : null,
      startedAt: new Date().toISOString(),
      startedRecorded: false,
      finishedRecorded: false,
      status: "started",
      reason: null,
      strategyReferenceValidation: null,
      strategyReferenceErrorCodes: [],
    };
    attempts.push(attempt);
    pendingAttempts.set(toolCallId, attempt);
    attempt.startedRecorded = appendAuditEvent(
      attempt,
      "attempt_started",
      currentSessionId,
    );
    return attempt;
  };

  const enrichAttemptFromParams = (
    attempt: DispatchAttempt,
    params: Record<string, unknown>,
  ) => {
    attempt.workflowRunId ??= workflowRunIdFromParams(params);
    if (typeof params.subagent_type === "string") {
      attempt.subagentType = params.subagent_type;
    }
    attempt.isolationProvided = Object.prototype.hasOwnProperty.call(
      params,
      "isolation",
    );
    attempt.runInBackgroundProvided = Object.prototype.hasOwnProperty.call(
      params,
      "run_in_background",
    );
    attempt.runInBackgroundValue =
      typeof params.run_in_background === "boolean"
        ? params.run_in_background
        : null;
    if (!attempt.startedRecorded) {
      attempt.startedRecorded = appendAuditEvent(
        attempt,
        "attempt_started",
        currentSessionId,
      );
    }
  };

  const finishAttempt = (
    attempt: DispatchAttempt,
    status: "completed" | "failed" | "blocked",
    reason: string | null,
    reasonCode: string | null,
  ) => {
    if (!attempt.startedRecorded) {
      attempt.startedRecorded = appendAuditEvent(
        attempt,
        "attempt_started",
        currentSessionId,
      );
    }
    attempt.status = status;
    attempt.reason = reason;
    if (attempt.finishedRecorded) return;
    attempt.finishedRecorded = true;
    appendAuditEvent(attempt, "attempt_finished", currentSessionId, reasonCode);
  };

  const blockedReason = (reason: string) =>
    `PROJECT017_AGENT_DISPATCH_BLOCKED: ${reason}\n${JSON.stringify(snapshot())}`;

  const blockedResult = (reason: string) => ({
    content: [{ type: "text", text: blockedReason(reason) }],
    details: {
      status: "blocked",
      error: reason,
      project017DispatchAudit: snapshot(),
    },
    isError: true,
  });

  const lockDispatch = (attempt: DispatchAttempt) => {
    dispatchLocked = true;
    dispatchLockAttemptNumber =
      dispatchLockAttemptNumber === null
        ? attempt.attemptNumber
        : Math.min(dispatchLockAttemptNumber, attempt.attemptNumber);
  };

  const rejectProposalAsAttempt = (
    proposal: DispatchProposal,
    params: Record<string, unknown>,
    reason: string,
  ) => {
    finishProposal(proposal, "rejected", reason);
    const attempt = createAttempt(proposal.toolCallId, params);
    lockDispatch(attempt);
    finishAttempt(attempt, "blocked", reason, reason);
    return {
      block: true,
      reason: blockedReason(reason),
    };
  };

  pi.on("before_provider_request", (event: any) =>
    enforceSingleToolTurn(event?.payload),
  );

  pi.on("session_start", (_event: unknown, ctx: any) => {
    resetSessionAudit(sessionIdFromContext(ctx));
  });

  pi.on("tool_call", (event: any, ctx: any) => {
    if (event?.toolName !== "Agent") return undefined;
    currentSessionId ??= sessionIdFromContext(ctx);
    const params = isRecord(event.input) ? event.input : {};
    const proposal = createProposal(event.toolCallId, params);
    if (dispatchLocked) {
      return rejectProposalAsAttempt(
        proposal,
        params,
        "previous_agent_dispatch_blocked",
      );
    }
    if (Object.prototype.hasOwnProperty.call(params, "isolation")) {
      return rejectProposalAsAttempt(
        proposal,
        params,
        "isolation_argument_forbidden_in_non_git_project",
      );
    }
    if (
      proposal.runInBackgroundProvided &&
      proposal.runInBackgroundValue !== false
    ) {
      return rejectProposalAsAttempt(
        proposal,
        params,
        "run_in_background_false_required",
      );
    }
    const completed = proposal.subagentType
      ? completedRoleResults.get(proposal.subagentType)
      : undefined;
    if (completed) {
      finishProposal(
        proposal,
        "coalesced",
        "duplicate_subagent_provider_proposal_coalesced",
        completed.toolCallId,
      );
      return undefined;
    }
    if (
      proposal.subagentType &&
      proposal.runInBackgroundProvided &&
      proposal.runInBackgroundValue === false
    ) {
      finishProposal(proposal, "admitted", null, event.toolCallId);
      createAttempt(event.toolCallId, params);
    }
    return undefined;
  });

  pi.on("tool_result", (event: any) => {
    if (event?.toolName !== "Agent") return undefined;
    const attempt = pendingAttempts.get(event.toolCallId);
    if (attempt?.status === "started") {
      finishAttempt(
        attempt,
        event?.isError ? "failed" : "completed",
        event?.isError ? "agent_tool_result_error" : null,
        event?.isError ? "agent_tool_result_error" : null,
      );
    }
    if (
      attempt?.status === "completed" &&
      attempt.subagentType &&
      !completedRoleResults.has(attempt.subagentType)
    ) {
      completedRoleResults.set(attempt.subagentType, {
        toolCallId: attempt.toolCallId,
        result: {
          content: Array.isArray(event.content) ? event.content : [],
          details: isRecord(event.details) ? event.details : {},
          isError: false,
        },
      });
    }
    const audit = snapshot();
    const previousDetails = isRecord(event.details) ? event.details : {};
    pendingAttempts.delete(event.toolCallId);
    pendingProposals.delete(event.toolCallId);
    if (attempt?.status === "blocked" || attempt?.status === "failed") {
      return {
        details: { ...previousDetails, project017DispatchAudit: audit },
        isError: true,
      };
    }
    return { details: { ...previousDetails, project017DispatchAudit: audit } };
  });

  const bridgeApi = new Proxy(pi, {
    get(target, property, receiver) {
      if (property === "registerTool") {
        return (tool: ToolDefinition) => {
          if (tool.name !== "Agent") {
            target.registerTool(tool);
            return;
          }
          const upstreamExecute = tool.execute.bind(tool);
          const upstreamDescriptionWithoutIsolation = tool.description
            .split(/\r?\n/)
            .filter((line) => !/\bisolation\b|worktree/i.test(line))
            .join("\n");
          const parameterObject = isRecord(tool.parameters)
            ? tool.parameters
            : {};
          const parameterProperties = isRecord(parameterObject.properties)
            ? parameterObject.properties
            : {};
          const isolationParameter = isRecord(parameterProperties.isolation)
            ? parameterProperties.isolation
            : {};
          const backgroundParameter = isRecord(
            parameterProperties.run_in_background,
          )
            ? parameterProperties.run_in_background
            : {};
          const wrappedTool: ToolDefinition = {
            ...tool,
            executionMode: "sequential",
            description: `${upstreamDescriptionWithoutIsolation}\n\nProject017 dispatch policy:\n${PROJECT017_POLICY_TEXT}`,
            promptGuidelines: [
              ...(tool.promptGuidelines ?? []),
              PROJECT017_POLICY_TEXT,
            ],
            parameters: {
              ...parameterObject,
              properties: {
                ...parameterProperties,
                isolation: {
                  ...isolationParameter,
                  description:
                    "Forbidden in project017 because it is not a Git repository. Omit this argument entirely.",
                },
                run_in_background: {
                  ...backgroundParameter,
                  type: "boolean",
                  description:
                    "Required to be false in project017. Background Agent dispatch is forbidden.",
                },
              },
            },
            execute: async (...args: any[]) => {
              const [toolCallId, rawParams, , , ctx] = args;
              currentSessionId ??= sessionIdFromContext(ctx);
              const params = withAuthoritativeWorkflowPrompt(
                isRecord(rawParams) ? rawParams : {},
              );
              args[1] = params;
              const proposal =
                pendingProposals.get(toolCallId) ??
                createProposal(toolCallId, params);
              enrichProposalFromParams(proposal, params);
              const completed = proposal.subagentType
                ? completedRoleResults.get(proposal.subagentType)
                : undefined;
              if (completed) {
                finishProposal(
                  proposal,
                  "coalesced",
                  "duplicate_subagent_provider_proposal_coalesced",
                  completed.toolCallId,
                );
                const cachedDetails = isRecord(completed.result?.details)
                  ? completed.result.details
                  : {};
                return {
                  ...completed.result,
                  content: [
                    ...(Array.isArray(completed.result?.content)
                      ? completed.result.content
                      : []),
                    {
                      type: "text",
                      text:
                        "PROJECT017_PROVIDER_PROPOSAL_COALESCED: no additional Agent execution was created; the canonical result above is authoritative.",
                    },
                  ],
                  details: {
                    ...cachedDetails,
                    project017ProviderProposal: {
                      disposition: "coalesced",
                      canonicalToolCallId: completed.toolCallId,
                      proposalToolCallId: toolCallId,
                    },
                    project017DispatchAudit: snapshot(),
                  },
                  isError: false,
                };
              }
              let attempt = pendingAttempts.get(toolCallId);
              const rejectDuringExecution = (reason: string) => {
                finishProposal(proposal, "rejected", reason);
                attempt ??= createAttempt(toolCallId, params);
                enrichAttemptFromParams(attempt, params);
                lockDispatch(attempt);
                finishAttempt(attempt, "blocked", reason, reason);
                return blockedResult(reason);
              };
              if (dispatchLocked) {
                return rejectDuringExecution("previous_agent_dispatch_blocked");
              }
              if (Object.prototype.hasOwnProperty.call(params, "isolation")) {
                return rejectDuringExecution(
                  "isolation_argument_forbidden_in_non_git_project",
                );
              }
              if (
                !proposal.runInBackgroundProvided ||
                proposal.runInBackgroundValue !== false
              ) {
                return rejectDuringExecution("run_in_background_false_required");
              }
              finishProposal(proposal, "admitted", null, toolCallId);
              attempt ??= createAttempt(toolCallId, params);
              enrichAttemptFromParams(attempt, params);
              try {
                const result = await upstreamExecute(...args);
                const upstreamDetails = isRecord(result?.details)
                  ? result.details
                  : {};
                const upstreamStatus = upstreamDetails.status;
                const failed = ["error", "aborted", "stopped"].includes(
                  String(upstreamStatus),
                );
                const strategyValidation =
                  !failed &&
                  proposal.subagentType === "commerce-review-strategist" &&
                  attempt.workflowRunId
                    ? validateStrategyReferences(attempt.workflowRunId, result)
                    : null;
                if (strategyValidation) {
                  attempt.strategyReferenceValidation =
                    strategyValidation.status;
                  attempt.strategyReferenceErrorCodes =
                    strategyValidation.errorCodes;
                }
                const strategyFailed =
                  strategyValidation?.status === "failed";
                finishAttempt(
                  attempt,
                  failed || strategyFailed ? "failed" : "completed",
                  failed
                    ? `upstream_agent_status_${String(upstreamStatus)}`
                    : strategyFailed
                      ? "strategy_cross_packet_reference_validation_failed"
                      : null,
                  failed
                    ? "upstream_agent_failed"
                    : strategyFailed
                      ? "strategy_cross_packet_reference_validation_failed"
                      : null,
                );
                if (failed || strategyFailed) lockDispatch(attempt);
                const finalResult = {
                  ...result,
                  details: {
                    ...upstreamDetails,
                    project017ProviderProposal: {
                      disposition: "admitted",
                      canonicalToolCallId: toolCallId,
                      proposalToolCallId: toolCallId,
                    },
                    project017DispatchAudit: snapshot(),
                    ...(strategyValidation
                      ? {
                          project017StrategyReferenceValidation:
                            strategyValidation,
                        }
                      : {}),
                  },
                  ...(failed || strategyFailed ? { isError: true } : {}),
                };
                if (!failed && !strategyFailed && proposal.subagentType) {
                  completedRoleResults.set(proposal.subagentType, {
                    toolCallId,
                    result: finalResult,
                  });
                }
                return finalResult;
              } catch (error) {
                lockDispatch(attempt);
                const reason =
                  error instanceof Error ? error.message : String(error);
                finishAttempt(
                  attempt,
                  "failed",
                  reason,
                  "upstream_agent_exception",
                );
                throw new Error(
                  `PROJECT017_AGENT_DISPATCH_FAILED: ${attempt.reason}\n${JSON.stringify(snapshot())}`,
                );
              }
            },
          };
          target.registerTool(wrappedTool);
        };
      }
      const value = Reflect.get(target, property, receiver);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });

  return subagentsExtension(bridgeApi as never);
}
