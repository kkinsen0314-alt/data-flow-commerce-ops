import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

const SCRIPT_ROOT = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(SCRIPT_ROOT, "..");
const PLATFORM_ROOT =
  "D:/Workspace/project014-miniclaw-deployment/upstream/miniclaw";
const PLATFORM_COMMIT = "3ff1c8d6a0707f4a9f0957ff411758e5e141583a";
const SUBAGENTS_VERSION = "0.16.1";
const PI_HOST_VERSION = "0.84.2";
const BRIDGE_ENTRY = path.join(
  PROJECT_ROOT,
  ".pi",
  "extensions",
  "miniclaw-subagents-bridge",
  "index.ts",
);
const BUSINESS_ENTRY = path.join(
  PROJECT_ROOT,
  ".pi",
  "extensions",
  "commerce-ops-mcp",
  "index.ts",
);
const PI_HOST_ENTRY = path.join(
  PROJECT_ROOT,
  ".pi",
  "extensions",
  "commerce-ops-mcp",
  "node_modules",
  "@earendil-works",
  "pi-coding-agent",
  "dist",
  "index.js",
);
const PI_AGENT_LOOP_SOURCE = path.join(
  PROJECT_ROOT,
  ".pi",
  "extensions",
  "commerce-ops-mcp",
  "node_modules",
  "@earendil-works",
  "pi-coding-agent",
  "node_modules",
  "@earendil-works",
  "pi-agent-core",
  "dist",
  "agent-loop.js",
);
const PI_RUNTIME_SOURCE = path.join(
  PLATFORM_ROOT,
  "container",
  "agent-runner",
  "src",
  "runtime",
  "pi",
  "pi-runtime.ts",
);
const PI_INDEX_SOURCE = path.join(
  PLATFORM_ROOT,
  "container",
  "agent-runner",
  "src",
  "pi-index.ts",
);
const SUBAGENTS_ROOT = path.join(
  PLATFORM_ROOT,
  "container",
  "agent-runner",
  "node_modules",
  "@tintinweb",
  "pi-subagents",
);
const SUBAGENTS_PACKAGE = path.join(SUBAGENTS_ROOT, "package.json");
const SUBAGENTS_ENTRY = path.join(SUBAGENTS_ROOT, "dist", "index.js");
const CUSTOM_AGENTS_ENTRY = path.join(
  SUBAGENTS_ROOT,
  "dist",
  "custom-agents.js",
);
const DISPATCH_TOOLS = [
  "Agent",
  "get_subagent_result",
  "steer_subagent",
];
const BUSINESS_TOOLS = [
  "commerce_ops_analyze_attribution_and_leads",
  "commerce_ops_analyze_live_commerce_data",
  "commerce_ops_analyze_short_video_data",
  "commerce_ops_drilldown_commerce_metric",
  "commerce_ops_inspect_commerce_data",
];
const EXPECTED_PROJECT_AGENTS = [
  "attribution-lead-analyst",
  "commerce-review-strategist",
  "content-growth-analyst",
  "live-conversion-analyst",
];

function parseArgs(argv) {
  const outputIndex = argv.indexOf("--output");
  if (outputIndex === -1) {
    return {
      output: path.join(
        PROJECT_ROOT,
        "artifacts",
        "miniclaw-subagent-bridge-validation-v12.json",
      ),
    };
  }
  const output = argv[outputIndex + 1];
  if (!output) throw new Error("--output 后必须提供文件路径");
  return { output: path.resolve(process.cwd(), output) };
}

function check(checks, checkId, condition, detail) {
  checks.push({
    check_id: checkId,
    status: condition ? "pass" : "fail",
    detail,
  });
  if (!condition) throw new Error(`${checkId}: ${detail}`);
}

function runGit(args) {
  return execFileSync("git", ["-C", PLATFORM_ROOT, ...args], {
    encoding: "utf8",
    windowsHide: true,
  }).trim();
}

function extractDefaultAllowedTools(source) {
  const block = source.match(/const DEFAULT_ALLOWED_TOOLS = \[([\s\S]*?)\];/);
  if (!block) throw new Error("无法从 pi-index.ts 解析 DEFAULT_ALLOWED_TOOLS");
  return [...block[1].matchAll(/'([^']+)'/g)].map((match) => match[1]);
}

function simulateMiniClawSelectedTools(allowedTools, customTools = []) {
  const aliases = {
    Bash: "bash",
    Read: "read",
    Write: "write",
    Edit: "edit",
    Glob: "find",
    Grep: "grep",
    Task: "Agent",
    TaskOutput: "get_subagent_result",
    TaskStop: "steer_subagent",
  };
  const builtins = new Set([
    "read",
    "bash",
    "edit",
    "write",
    "find",
    "grep",
    "ls",
  ]);
  const dispatch = new Set(DISPATCH_TOOLS);
  const customNames = new Set(customTools.map((tool) => tool.name));
  const expanded = allowedTools.flatMap((name) =>
    name === "mcp__miniclaw__*"
      ? [...customNames]
      : [aliases[name] ?? name],
  );
  return [...new Set(expanded)].filter(
    (name) =>
      builtins.has(name) || customNames.has(name) || dispatch.has(name),
  );
}

function extensionWithExactTools(extensions, expectedTools) {
  const expected = [...expectedTools].sort().join(",");
  return extensions.filter((extension) => {
    const actual = [...extension.tools.keys()].sort().join(",");
    return actual === expected;
  });
}

async function applyProviderRequestHandlers(extension, payload) {
  let current = payload;
  for (const handler of extension.handlers.get("before_provider_request") ?? []) {
    const replacement = await handler({
      type: "before_provider_request",
      payload: current,
    });
    if (replacement !== undefined) current = replacement;
  }
  return current;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const checks = [];
  let tempRoot;
  const guardWorkflowRunId = "wf_bridge_event_enrichment_validation";
  const guardAuditPath = path.join(
    PROJECT_ROOT,
    "runtime",
    "data",
    "native-audit",
    `${guardWorkflowRunId}.jsonl`,
  );
  const backgroundGuardWorkflowRunId =
    "wf_bridge_background_guard_validation";
  const backgroundGuardAuditPath = path.join(
    PROJECT_ROOT,
    "runtime",
    "data",
    "native-audit",
    `${backgroundGuardWorkflowRunId}.jsonl`,
  );
  const duplicateGuardWorkflowRunId =
    "wf_bridge_duplicate_role_validation";
  const duplicateGuardAuditPath = path.join(
    PROJECT_ROOT,
    "runtime",
    "data",
    "native-audit",
    `${duplicateGuardWorkflowRunId}.jsonl`,
  );
  const strategyGuardWorkflowRunId =
    "wf_bridge_strategy_reference_validation";
  const strategyGuardAuditPath = path.join(
    PROJECT_ROOT,
    "runtime",
    "data",
    "native-audit",
    `${strategyGuardWorkflowRunId}.jsonl`,
  );

  check(
    checks,
    "source:platform-commit",
    runGit(["rev-parse", "HEAD"]) === PLATFORM_COMMIT,
    `project014 is pinned to ${PLATFORM_COMMIT}`,
  );
  check(
    checks,
    "source:platform-git-clean",
    runGit(["status", "--porcelain"]) === "",
    "project014 Git worktree is clean",
  );

  const packageJson = JSON.parse(
    await fs.readFile(SUBAGENTS_PACKAGE, "utf8"),
  );
  check(
    checks,
    "source:subagents-version",
    packageJson.name === "@tintinweb/pi-subagents" &&
      packageJson.version === SUBAGENTS_VERSION,
    `pi-subagents package is ${SUBAGENTS_VERSION}`,
  );
  check(
    checks,
    "source:subagents-pi-entry",
    packageJson.main === undefined &&
      packageJson.exports === undefined &&
      packageJson.pi?.extensions?.join(",") === "./src/index.ts",
    "pi-subagents exposes a Pi metadata entry but no ordinary package entry",
  );
  check(
    checks,
    "source:compiled-entry-exists",
    await fs
      .access(SUBAGENTS_ENTRY)
      .then(() => true)
      .catch(() => false),
    "the fixed baseline contains dist/index.js",
  );

  const runtimeRequire = createRequire(pathToFileURL(PI_RUNTIME_SOURCE));
  let packageResolution;
  let packageResolutionError;
  try {
    packageResolution = runtimeRequire.resolve("@tintinweb/pi-subagents");
  } catch (error) {
    packageResolutionError = error;
  }
  check(
    checks,
    "baseline:ordinary-package-resolution-fails",
    packageResolution === undefined &&
      packageResolutionError?.code === "MODULE_NOT_FOUND",
    "MiniClaw's current require.resolve path cannot resolve the package entry",
  );

  const bridgeSource = await fs.readFile(BRIDGE_ENTRY, "utf8");
  check(
    checks,
    "bridge:fixed-compiled-entry",
    bridgeSource.includes(pathToFileURL(SUBAGENTS_ENTRY).href) &&
      bridgeSource.includes(PLATFORM_COMMIT) &&
      bridgeSource.includes(SUBAGENTS_VERSION),
    "project017 bridge is pinned to the fixed MiniClaw and pi-subagents baseline",
  );
  check(
    checks,
    "bridge:no-third-party-source-copy",
    bridgeSource.length < 45000 &&
      bridgeSource.includes("new Proxy(pi") &&
      bridgeSource.includes('property === "registerTool"') &&
      !bridgeSource.includes("createAgentSession") &&
      !bridgeSource.includes("manager.spawn") &&
      !bridgeSource.includes("spawnAndWait"),
    "bridge wraps the installed compiled entry with a project-local policy and does not copy spawn/session implementation",
  );
  check(
    checks,
    "bridge:redacted-native-audit-source",
    [
      "native-audit",
      'event_type: eventType',
      'layer: "parent_dispatch"',
      'tool_name: "Agent"',
      "run_in_background_value",
      "automatic_retry: false",
      "provider_proposal_received",
      "provider_proposal_disposition",
    ].every((token) => bridgeSource.includes(token)),
    "bridge writes a redacted parent Agent attempt ledger for native reconciliation",
  );
  check(
    checks,
    "bridge:fail-closed-policy-source",
    [
      "PROJECT017_AGENT_DISPATCH_POLICY",
      "project017_agent_dispatch_deterministic_admission_v2",
      'hasOwnProperty.call(params, "isolation")',
      "isolation_argument_forbidden_in_non_git_project",
      "duplicate_subagent_provider_proposal_coalesced",
      "project017DispatchAudit",
      'pi.on("tool_call"',
      'pi.on("tool_result"',
      "isError: true",
    ].every((token) => bridgeSource.includes(token)),
    "bridge source contains safety rejection, duplicate-proposal coalescing, audit payload, and runtime error marking",
  );
  check(
    checks,
    "bridge:deterministic-admission-boundary",
    [
      'executionMode: "sequential"',
      "completedRoleResults",
      'disposition: "coalesced"',
      "canonicalToolCallId",
      "providerProposalCount",
    ].every((token) => bridgeSource.includes(token)),
    "Pi serializes Agent calls and the bridge coalesces repeated provider proposals onto one canonical execution",
  );
  check(
    checks,
    "bridge:strategy-cross-packet-validation-source",
    [
      "strategyReferenceCatalog",
      "validateStrategyReferences",
      "strategy_cross_packet_reference_validation_failed",
      "project017StrategyReferenceValidation",
    ].every((token) => bridgeSource.includes(token)),
    "strategy DecisionPacket references are checked against specialist audit catalogs before a parent attempt can complete",
  );
  check(
    checks,
    "bridge:single-tool-provider-policy-source",
    [
      'pi.on("before_provider_request"',
      "enforceSingleToolTurn",
      "disable_parallel_tool_use: true",
      'type: "auto"',
    ].every((token) => bridgeSource.includes(token)),
    "bridge source injects Anthropic at-most-one tool call semantics before each provider request",
  );

  await fs.mkdir(path.dirname(strategyGuardAuditPath), { recursive: true });
  await fs.writeFile(
    strategyGuardAuditPath,
    `${JSON.stringify({
      schema_version: "1.0",
      event_type: "attempt_finished",
      attempt_id: "child:strategy-catalog-analysis",
      workflow_run_id: strategyGuardWorkflowRunId,
      layer: "specialist_tool",
      actor: "content_growth_analyst",
      tool_name: "commerce_ops_analyze_short_video_data",
      tool_call_id: "strategy-catalog-analysis",
      attempt_number: 2,
      status: "completed",
      service_run_id: "srv_strategy_catalog",
      analysis_run_id: "analysis_strategy_catalog",
      dataset_ids: ["ds_strategy_catalog"],
      evidence_ids: ["ev_strategy_catalog"],
      finding_ids: ["finding_strategy_catalog"],
      finding_evidence_links: {
        finding_strategy_catalog: ["ev_strategy_catalog"],
      },
      observed_at: "2026-09-06T00:00:00Z",
      automatic_retry: false,
    })}\n`,
    "utf8",
  );
  const { validateStrategyReferences } = await import(
    `${pathToFileURL(BRIDGE_ENTRY).href}?strategy-reference=${Date.now()}`
  );
  const decisionResult = (findingId, evidenceId, datasetId) => ({
    content: [
      {
        type: "text",
        text: JSON.stringify({
          schema_version: "1.0",
          message_type: "decision_packet",
          workflow_run_id: strategyGuardWorkflowRunId,
          decision_run_id: "decision_strategy_catalog",
          agent_role: "commerce_review_strategist",
          source_analysis_ids: ["analysis_strategy_catalog"],
          terminal_status: "completed",
          actions: [
            {
              finding_ids: [findingId],
              evidence_ids: [evidenceId],
              verification_metric: { dataset_ids: [datasetId] },
            },
          ],
          blocked_reasons: [],
        }),
      },
    ],
  });
  const validStrategyReferences = validateStrategyReferences(
    strategyGuardWorkflowRunId,
    decisionResult(
      "finding_strategy_catalog",
      "ev_strategy_catalog",
      "ds_strategy_catalog",
    ),
  );
  const invalidStrategyReferences = validateStrategyReferences(
    strategyGuardWorkflowRunId,
    decisionResult(
      "finding_invented",
      "ev_invented",
      "ds_invented",
    ),
  );
  check(
    checks,
    "guard:strategy-valid-references-pass",
    validStrategyReferences.status === "pass" &&
      validStrategyReferences.errorCodes.length === 0 &&
      validStrategyReferences.actionCount === 1,
    "a DecisionPacket using only audited analysis, finding, evidence, and dataset IDs passes",
  );
  check(
    checks,
    "guard:strategy-invented-references-fail",
    invalidStrategyReferences.status === "failed" &&
      [
        "strategy_finding_id_not_in_catalog",
        "strategy_evidence_id_not_in_catalog",
        "strategy_dataset_id_not_in_catalog",
      ].every((code) => invalidStrategyReferences.errorCodes.includes(code)),
    "invented strategy references are rejected deterministically without a model or Agent session",
  );

  const piHostPackage = JSON.parse(
    await fs.readFile(
      path.join(
        PROJECT_ROOT,
        ".pi",
        "extensions",
        "commerce-ops-mcp",
        "node_modules",
        "@earendil-works",
        "pi-coding-agent",
        "package.json",
      ),
      "utf8",
    ),
  );
  check(
    checks,
    "dependency:pi-host-version",
    piHostPackage.version === PI_HOST_VERSION,
    `validation loader uses Pi host ${PI_HOST_VERSION}`,
  );
  const agentLoopSource = await fs.readFile(PI_AGENT_LOOP_SOURCE, "utf8");
  check(
    checks,
    "dependency:pi-sequential-execution-contract",
    [
      "hasSequentialToolCall",
      'executionMode === "sequential"',
      "executeToolCallsSequential",
    ].every((token) => agentLoopSource.includes(token)),
    "Pi agent-core routes a tool batch through sequential execution when any registered tool declares sequential mode",
  );

  const [{ DefaultResourceLoader, SettingsManager }, { loadCustomAgents }] =
    await Promise.all([
      import(pathToFileURL(PI_HOST_ENTRY).href),
      import(pathToFileURL(CUSTOM_AGENTS_ENTRY).href),
    ]);

  const originalCwd = process.cwd();
  try {
    process.chdir(PROJECT_ROOT);
    await fs.mkdir(path.join(PROJECT_ROOT, "runtime", "tmp"), {
      recursive: true,
    });
    tempRoot = await fs.mkdtemp(
      path.join(PROJECT_ROOT, "runtime", "tmp", "subagent-bridge-loader-"),
    );
    const agentDir = path.join(tempRoot, "agent");
    await fs.mkdir(agentDir, { recursive: true });
    const settingsManager = SettingsManager.create(PROJECT_ROOT, agentDir, {
      projectTrusted: true,
    });
    const resourceLoader = new DefaultResourceLoader({
      cwd: PROJECT_ROOT,
      agentDir,
      settingsManager,
      systemPrompt: "",
      noSkills: true,
      noPromptTemplates: true,
      noThemes: true,
      noContextFiles: true,
    });
    await resourceLoader.reload({ resolveProjectTrust: async () => true });
    const loaded = resourceLoader.getExtensions();
    check(
      checks,
      "loader:no-errors",
      loaded.errors.length === 0,
      "DefaultResourceLoader reports no extension load errors",
    );

    const dispatchExtensions = extensionWithExactTools(
      loaded.extensions,
      DISPATCH_TOOLS,
    );
    const businessExtensions = extensionWithExactTools(
      loaded.extensions,
      BUSINESS_TOOLS,
    );
    check(
      checks,
      "loader:single-dispatch-extension",
      dispatchExtensions.length === 1,
      "one project extension registers exactly the three dispatch tools",
    );
    check(
      checks,
      "loader:dispatch-extension-is-bridge",
      path.resolve(dispatchExtensions[0].path) === path.resolve(BRIDGE_ENTRY),
      "the dispatch tools are attributed to the project017 bridge entry",
    );
    const agentRegistration = dispatchExtensions[0].tools.get("Agent");
    const agentTool = agentRegistration?.definition;
    check(
      checks,
      "loader:agent-policy-injected",
      agentTool?.description.includes(
        "Project017 is not a Git repository",
      ) &&
      agentTool?.description.includes(
        "Omit the Agent isolation argument entirely",
      ) &&
        agentTool?.executionMode === "sequential" &&
        agentTool?.promptGuidelines?.some((line) =>
          line.includes(
            "Final reporting must merge admitted parent Agent attempts",
          ),
        ),
      "loaded Agent definition carries the project017 dispatch and parent-child attempt-ledger policy",
    );
    check(
      checks,
      "loader:worktree-recommendation-removed",
      !agentTool?.description.includes('isolation: "worktree" runs') &&
        !agentTool?.description.includes(
          'Use isolation: "worktree" to run',
        ) &&
        agentTool?.parameters?.properties?.isolation?.description?.includes(
          "Forbidden in project017",
        ),
      "loaded Agent prose no longer recommends worktree and its schema field says to omit isolation",
    );
    check(
      checks,
      "loader:background-policy-remains-auditable",
      agentTool?.parameters?.properties?.run_in_background?.type ===
        "boolean" &&
        agentTool?.parameters?.properties?.run_in_background?.const ===
          undefined &&
        agentTool?.parameters?.properties?.run_in_background?.description?.includes(
          "Required to be false in project017",
        ),
      "the Agent schema tells the model to use foreground execution while runtime hooks retain visibility of invalid true values",
    );

    const guardContext = {
      cwd: PROJECT_ROOT,
      sessionManager: {
        getSessionId: () => "project017-no-model-guard-validation",
      },
    };
    await fs.rm(guardAuditPath, { force: true });
    for (const handler of dispatchExtensions[0].handlers.get("tool_call") ?? []) {
      await handler(
        {
          type: "tool_call",
          toolName: "Agent",
          toolCallId: "project017-guard-call-1",
          input: {},
        },
        guardContext,
      );
    }
    const firstGuardResult = await agentTool.execute(
      "project017-guard-call-1",
      {
        prompt: `No-model guard validation for ${guardWorkflowRunId}; this must not start an agent.`,
        description: "validate isolation guard",
        subagent_type: "content-growth-analyst",
        isolation: "worktree",
        run_in_background: false,
      },
      undefined,
      undefined,
      guardContext,
    );
    const firstAudit = firstGuardResult.details?.project017DispatchAudit;
    check(
      checks,
      "guard:worktree-blocked-before-spawn",
      firstGuardResult.isError === true &&
        firstGuardResult.details?.status === "blocked" &&
        firstAudit?.dispatchLocked === true &&
        firstAudit?.parentAgentAttemptCount === 1 &&
        firstAudit?.attempts?.[0]?.workflowRunId === guardWorkflowRunId &&
        firstAudit?.attempts?.[0]?.subagentType ===
          "content-growth-analyst" &&
        firstAudit?.attempts?.[0]?.isolationProvided === true &&
        firstAudit?.attempts?.[0]?.runInBackgroundProvided === true &&
        firstAudit?.attempts?.[0]?.runInBackgroundValue === false &&
        firstAudit?.attempts?.[0]?.startedRecorded === true &&
        firstAudit?.attempts?.[0]?.reason ===
          "isolation_argument_forbidden_in_non_git_project",
      "an incomplete tool_call event is enriched from execute parameters before isolation=worktree is blocked",
    );
    const guardAuditEvents = (await fs.readFile(guardAuditPath, "utf8"))
      .trim()
      .split(/\r?\n/)
      .map((line) => JSON.parse(line));
    check(
      checks,
      "guard:enriched-attempt-persisted",
      guardAuditEvents.length === 4 &&
        guardAuditEvents[0]?.event_type === "provider_proposal_received" &&
        guardAuditEvents[1]?.event_type === "provider_proposal_disposition" &&
        guardAuditEvents[1]?.disposition === "rejected" &&
        guardAuditEvents[2]?.event_type === "attempt_started" &&
        guardAuditEvents[3]?.event_type === "attempt_finished" &&
        guardAuditEvents.every(
          (event) =>
            event.workflow_run_id === guardWorkflowRunId &&
            event.subagent_type === "content-growth-analyst" &&
            event.isolation_argument_present === true &&
            event.run_in_background_argument_present === true &&
            event.run_in_background_value === false,
        ),
      "the rejected provider proposal and its blocked safety attempt are persisted separately under the workflow ledger",
    );

    const secondGuardResult = await agentTool.execute(
      "project017-guard-call-2",
      {
        prompt: "No-model guard validation; this must remain locked.",
        description: "validate session lock",
        subagent_type: "content-growth-analyst",
      },
      undefined,
      undefined,
      guardContext,
    );
    const secondAudit = secondGuardResult.details?.project017DispatchAudit;
    check(
      checks,
      "guard:second-dispatch-remains-locked",
      secondGuardResult.isError === true &&
        secondGuardResult.details?.status === "blocked" &&
        secondAudit?.dispatchLocked === true &&
        secondAudit?.parentAgentAttemptCount === 2 &&
        secondAudit?.attempts?.[1]?.reason ===
          "previous_agent_dispatch_blocked",
      "a second Agent call in the same extension session is blocked without delegating to upstream execution",
    );

    let toolResultGuard;
    for (const handler of dispatchExtensions[0].handlers.get("tool_result") ?? []) {
      const candidate = await handler(
        {
          type: "tool_result",
          toolName: "Agent",
          toolCallId: "project017-guard-call-1",
          input: { isolation: "worktree" },
          content: firstGuardResult.content,
          details: firstGuardResult.details,
          isError: false,
        },
        guardContext,
      );
      if (
        candidate?.isError === true &&
        candidate?.details?.project017DispatchAudit
      ) {
        toolResultGuard = candidate;
      }
    }
    check(
      checks,
      "guard:runtime-tool-result-marked-error",
      toolResultGuard?.isError === true &&
        toolResultGuard?.details?.project017DispatchAudit?.dispatchLocked ===
          true,
      "tool_result hook marks a blocked Agent result as an error and preserves the audit payload",
    );

    const sessionStartHandlers =
      dispatchExtensions[0].handlers.get("session_start") ?? [];
    const toolCallHandlers =
      dispatchExtensions[0].handlers.get("tool_call") ?? [];
    const toolResultHandlers =
      dispatchExtensions[0].handlers.get("tool_result") ?? [];
    const resetGuardSession = async (sessionId) => {
      const context = {
        cwd: PROJECT_ROOT,
        sessionManager: { getSessionId: () => sessionId },
      };
      for (const handler of sessionStartHandlers) {
        await handler({ type: "session_start" }, context);
      }
      return context;
    };
    const invokeToolCall = async (event, context) => {
      let blocked;
      for (const handler of toolCallHandlers) {
        const candidate = await handler(event, context);
        if (candidate?.block === true) blocked = candidate;
      }
      return blocked;
    };

    await fs.rm(backgroundGuardAuditPath, { force: true });
    const backgroundGuardContext = await resetGuardSession(
      "project017-no-model-background-guard",
    );
    const backgroundGuardResult = await invokeToolCall(
      {
        type: "tool_call",
        toolName: "Agent",
        toolCallId: "project017-background-guard-call-1",
        input: {
          prompt: `No-model validation for ${backgroundGuardWorkflowRunId}.`,
          description: "validate foreground-only dispatch",
          subagent_type: "live-ops-analyst",
          run_in_background: true,
        },
      },
      backgroundGuardContext,
    );
    const backgroundGuardEvents = (
      await fs.readFile(backgroundGuardAuditPath, "utf8")
    )
      .trim()
      .split(/\r?\n/)
      .map((line) => JSON.parse(line));
    check(
      checks,
      "guard:background-true-blocked-before-spawn",
      backgroundGuardResult?.block === true &&
        backgroundGuardResult.reason.includes(
          "run_in_background_false_required",
        ) &&
        backgroundGuardEvents.length === 4 &&
        backgroundGuardEvents[0]?.event_type ===
          "provider_proposal_received" &&
        backgroundGuardEvents[1]?.event_type ===
          "provider_proposal_disposition" &&
        backgroundGuardEvents[1]?.disposition === "rejected" &&
        backgroundGuardEvents[2]?.event_type === "attempt_started" &&
        backgroundGuardEvents[3]?.event_type === "attempt_finished" &&
        backgroundGuardEvents[3]?.status === "blocked" &&
        backgroundGuardEvents[3]?.reason_code ===
          "run_in_background_false_required" &&
        backgroundGuardEvents.every(
          (event) =>
            event.workflow_run_id === backgroundGuardWorkflowRunId &&
            event.subagent_type === "live-ops-analyst" &&
            event.run_in_background_argument_present === true &&
            event.run_in_background_value === true,
        ),
      "run_in_background=true is rejected and fully audited by the bridge before upstream Agent execution",
    );

    await fs.rm(duplicateGuardAuditPath, { force: true });
    const duplicateGuardContext = await resetGuardSession(
      "project017-no-model-duplicate-role-guard",
    );
    const firstDuplicateHookResult = await invokeToolCall(
      {
        type: "tool_call",
        toolName: "Agent",
        toolCallId: "project017-duplicate-guard-call-1",
        input: {
          prompt: `First no-model validation attempt for ${duplicateGuardWorkflowRunId}.`,
          description: "validate first unique role",
          subagent_type: "attribution-leads-analyst",
          run_in_background: false,
        },
      },
      duplicateGuardContext,
    );
    let firstDuplicateToolResult;
    for (const handler of toolResultHandlers) {
      const candidate = await handler(
        {
          type: "tool_result",
          toolName: "Agent",
          toolCallId: "project017-duplicate-guard-call-1",
          content: [{ type: "text", text: "simulated no-model completion" }],
          details: { status: "completed" },
          isError: false,
        },
        duplicateGuardContext,
      );
      if (candidate?.details?.project017DispatchAudit) {
        firstDuplicateToolResult = candidate;
      }
    }
    const secondDuplicateHookResult = await invokeToolCall(
      {
        type: "tool_call",
        toolName: "Agent",
        toolCallId: "project017-duplicate-guard-call-2",
        input: {
          prompt: `Second no-model validation proposal for ${duplicateGuardWorkflowRunId}.`,
          description: "validate duplicate role coalescing",
          subagent_type: "attribution-leads-analyst",
          run_in_background: false,
        },
      },
      duplicateGuardContext,
    );
    const secondDuplicateResult = await agentTool.execute(
      "project017-duplicate-guard-call-2",
      {
        prompt: `Second no-model validation proposal for ${duplicateGuardWorkflowRunId}.`,
        description: "validate duplicate role coalescing",
        subagent_type: "attribution-leads-analyst",
        run_in_background: false,
      },
      undefined,
      undefined,
      duplicateGuardContext,
    );
    const duplicateGuardEvents = (
      await fs.readFile(duplicateGuardAuditPath, "utf8")
    )
      .trim()
      .split(/\r?\n/)
      .map((line) => JSON.parse(line));
    check(
      checks,
      "admission:duplicate-role-coalesced-before-spawn",
      firstDuplicateHookResult === undefined &&
        secondDuplicateHookResult === undefined &&
        firstDuplicateToolResult?.isError !== true &&
        secondDuplicateResult?.isError !== true &&
        secondDuplicateResult?.details?.project017ProviderProposal
          ?.disposition === "coalesced" &&
        secondDuplicateResult?.details?.project017ProviderProposal
          ?.canonicalToolCallId === "project017-duplicate-guard-call-1" &&
        firstDuplicateToolResult?.details?.project017DispatchAudit
          ?.parentAgentAttemptCount === 1 &&
        secondDuplicateResult?.details?.project017DispatchAudit
          ?.parentAgentAttemptCount === 1 &&
        secondDuplicateResult?.details?.project017DispatchAudit
          ?.providerProposalCount === 2 &&
        secondDuplicateResult?.details?.project017DispatchAudit
          ?.coalescedProviderProposalCount === 1 &&
        duplicateGuardEvents.length === 6 &&
        duplicateGuardEvents.filter(
          (event) => event.event_type === "attempt_started",
        ).length === 1 &&
        duplicateGuardEvents.filter(
          (event) => event.event_type === "attempt_finished",
        ).length === 1 &&
        duplicateGuardEvents.some(
          (event) =>
            event.tool_call_id === "project017-duplicate-guard-call-2" &&
            event.event_type === "provider_proposal_disposition" &&
            event.disposition === "coalesced" &&
            event.canonical_tool_call_id ===
              "project017-duplicate-guard-call-1" &&
            event.reason_code ===
              "duplicate_subagent_provider_proposal_coalesced",
        ) &&
        duplicateGuardEvents.some(
          (event) =>
            event.tool_call_id === "project017-duplicate-guard-call-1" &&
            event.event_type === "attempt_finished" &&
            event.status === "completed" &&
            event.reason_code === null,
        ) &&
        duplicateGuardEvents.every(
          (event) =>
            event.workflow_run_id === duplicateGuardWorkflowRunId &&
            event.subagent_type === "attribution-leads-analyst" &&
            event.run_in_background_argument_present === true &&
            event.run_in_background_value === false,
        ),
      "a repeated same-role provider proposal is audited and reuses the canonical result without reaching upstream Agent execution",
    );
    check(
      checks,
      "loader:single-business-extension",
      businessExtensions.length === 1,
      "one project extension still registers exactly the five commerce tools",
    );
    check(
      checks,
      "loader:business-extension-unchanged",
      path.resolve(businessExtensions[0].path) === path.resolve(BUSINESS_ENTRY),
      "the five business tools remain owned by commerce-ops-mcp",
    );
    const dispatchProviderHandlers =
      dispatchExtensions[0].handlers.get("before_provider_request") ?? [];
    const businessProviderHandlers =
      businessExtensions[0].handlers.get("before_provider_request") ?? [];
    check(
      checks,
      "loader:single-tool-provider-handlers",
      dispatchProviderHandlers.length === 1 &&
        businessProviderHandlers.length === 1,
      "Supervisor and professional specialist extensions each register one provider request guard",
    );
    const providerPayloadFixture = {
      model: "validation-model",
      tools: [{ name: "tool-a" }, { name: "tool-b" }],
      tool_choice: {
        type: "any",
        disable_parallel_tool_use: false,
        vendor_field: "preserved",
      },
    };
    const dispatchProviderPayload = await applyProviderRequestHandlers(
      dispatchExtensions[0],
      providerPayloadFixture,
    );
    const businessProviderPayload = await applyProviderRequestHandlers(
      businessExtensions[0],
      providerPayloadFixture,
    );
    check(
      checks,
      "loader:dispatch-single-tool-provider-rewrite",
      dispatchProviderPayload.tool_choice?.type === "any" &&
        dispatchProviderPayload.tool_choice?.vendor_field === "preserved" &&
        dispatchProviderPayload.tool_choice?.disable_parallel_tool_use === true,
      "Supervisor provider payload is constrained to at most one Agent tool call per assistant response",
    );
    check(
      checks,
      "loader:business-single-tool-provider-rewrite",
      businessProviderPayload.tool_choice?.type === "any" &&
        businessProviderPayload.tool_choice?.vendor_field === "preserved" &&
        businessProviderPayload.tool_choice?.disable_parallel_tool_use === true,
      "professional specialist provider payload is constrained to at most one business tool call per assistant response",
    );

    const projectAgents = loadCustomAgents(PROJECT_ROOT, true);
    const projectAgentNames = [...projectAgents.entries()]
      .filter(([, agent]) => agent.source === "project")
      .map(([name]) => name)
      .sort();
    check(
      checks,
      "agents:strict-project-parse",
      projectAgentNames.join(",") === EXPECTED_PROJECT_AGENTS.join(","),
      "strict parser loads exactly the four project017 specialist agent files",
    );
    const professionalAgents = EXPECTED_PROJECT_AGENTS.filter(
      (name) => name !== "commerce-review-strategist",
    ).map((name) => projectAgents.get(name));
    check(
      checks,
      "agents:professional-extension-scope",
      professionalAgents.every(
        (agent) =>
          agent?.extensions?.length === 1 &&
          path.resolve(agent.extensions[0]) === path.resolve(BUSINESS_ENTRY) &&
          agent.extSelectors?.length === 3 &&
          (agent.builtinToolNames ?? []).every(
            (tool) => tool === "none" || !["bash", "read", "write", "edit"].includes(tool),
          ),
      ),
      "three professional agents retain explicit business extension allowlists and no usable built-in tools",
    );
    const reviewAgent = projectAgents.get("commerce-review-strategist");
    check(
      checks,
      "agents:review-tool-free",
      reviewAgent?.extensions === false &&
        (reviewAgent?.builtinToolNames ?? []).length === 0,
      "review strategist remains extension-free and tool-free",
    );

    const piIndexSource = await fs.readFile(PI_INDEX_SOURCE, "utf8");
    const defaultAllowedTools = extractDefaultAllowedTools(piIndexSource);
    const selectedMainTools = simulateMiniClawSelectedTools(
      defaultAllowedTools,
      [],
    );
    check(
      checks,
      "main-session:dispatch-tools-selected",
      DISPATCH_TOOLS.every((tool) => selectedMainTools.includes(tool)),
      "MiniClaw main-session selection includes all three dispatch tools",
    );
    check(
      checks,
      "main-session:no-business-tools-selected",
      BUSINESS_TOOLS.every((tool) => !selectedMainTools.includes(tool)),
      "MiniClaw main-session selection excludes all five commerce tools",
    );

    const report = {
      schema_version: "3.0",
      validation_kind:
        "project017_miniclaw_subagent_bridge_fail_closed_no_model",
      status: checks.every((item) => item.status === "pass")
        ? "pass"
        : "fail",
      generated_at: new Date().toISOString(),
      project_root: PROJECT_ROOT,
      source_platform: {
        root: PLATFORM_ROOT,
        commit: PLATFORM_COMMIT,
        git_clean: true,
        pi_subagents_version: SUBAGENTS_VERSION,
        ordinary_package_resolution: "MODULE_NOT_FOUND",
        bridged_compiled_entry: SUBAGENTS_ENTRY,
      },
      runtime: {
        scope_note:
          "These fields describe actions performed by this no-model validator, not the total runtime history of project017.",
        node_version: process.version,
        pi_host_version: PI_HOST_VERSION,
        loader: "DefaultResourceLoader",
        project_trust_resolved: true,
        model_runtime_created_by_this_validator: false,
        agent_session_created_by_this_validator: false,
        model_called_by_this_validator: false,
        provider_read_by_this_validator: false,
        sqlite_read_or_written_by_this_validator: false,
        mcp_transport_started_by_this_validator: false,
      },
      loader_result: {
        loaded_extension_count: loaded.extensions.length,
        load_error_count: loaded.errors.length,
        dispatch_extension_path: dispatchExtensions[0].path,
        business_extension_path: businessExtensions[0].path,
        dispatch_tools: [...DISPATCH_TOOLS].sort(),
        business_tools: [...BUSINESS_TOOLS].sort(),
      },
      main_session_policy_simulation: {
        source: "project014 pi-index.ts DEFAULT_ALLOWED_TOOLS plus pi-runtime.ts alias and filter semantics",
        default_allowed_tools: defaultAllowedTools,
        selected_tool_names: selectedMainTools,
        dispatch_tools_selected: true,
        business_tools_selected: false,
      },
      provider_request_policy: {
        protocol: "anthropic-messages",
        supervisor_handler_count: dispatchProviderHandlers.length,
        specialist_handler_count: businessProviderHandlers.length,
        supervisor_disable_parallel_tool_use:
          dispatchProviderPayload.tool_choice.disable_parallel_tool_use,
        specialist_disable_parallel_tool_use:
          businessProviderPayload.tool_choice.disable_parallel_tool_use,
        existing_tool_choice_preserved: true,
        model_or_provider_started: false,
      },
      guard_validation: {
        policy_id: firstAudit.policyId,
        tool_call_input_was_incomplete: true,
        isolation_attempt_result: {
          status: firstGuardResult.details.status,
          is_error: firstGuardResult.isError,
          audit: firstAudit,
        },
        second_attempt_result: {
          status: secondGuardResult.details.status,
          is_error: secondGuardResult.isError,
          audit: secondAudit,
        },
        runtime_tool_result_hook_sets_error: toolResultGuard.isError,
        background_true_attempt_result: {
          blocked: backgroundGuardResult.block,
          reason_contains: "run_in_background_false_required",
          audit_event_count: backgroundGuardEvents.length,
        },
        duplicate_role_proposal_result: {
          first_hook_allowed: firstDuplicateHookResult === undefined,
          second_hook_allowed: secondDuplicateHookResult === undefined,
          second_result_disposition:
            secondDuplicateResult.details.project017ProviderProposal
              .disposition,
          canonical_tool_call_id:
            secondDuplicateResult.details.project017ProviderProposal
              .canonicalToolCallId,
          admitted_attempt_count:
            secondDuplicateResult.details.project017DispatchAudit
              .parentAgentAttemptCount,
          provider_proposal_count:
            secondDuplicateResult.details.project017DispatchAudit
              .providerProposalCount,
          audit_event_count: duplicateGuardEvents.length,
        },
        upstream_agent_execute_reached: false,
      },
      strict_project_agents: projectAgentNames,
      checks_total: checks.length,
      checks_passed: checks.filter((item) => item.status === "pass").length,
      checks_failed: checks.filter((item) => item.status === "fail").length,
      checks,
      evidence_boundary: {
        compatibility_bridge_loaded_by_this_validator: true,
        dispatch_tool_definitions_registered_by_this_validator: true,
        business_tool_definitions_registered_by_this_validator: true,
        main_session_tool_policy_simulated_from_fixed_source: true,
        specialist_agent_files_strictly_parsed_by_this_validator: true,
        isolation_guard_executed_without_agent_session: true,
        second_dispatch_lock_executed_without_agent_session: true,
        background_guard_executed_without_agent_session: true,
        duplicate_role_coalescing_executed_without_agent_session: true,
        deterministic_agent_execution_mode_validated_without_agent_session: true,
        provider_request_payload_rewrite_validated_without_agent_session: true,
        model_runtime_created_by_this_validator: false,
        agent_session_created_by_this_validator: false,
        subagent_spawned_by_this_validator: false,
        business_tool_called_by_this_validator: false,
        real_model_called_by_this_validator: false,
        real_business_data_used_by_this_validator: false,
        post_fix_multi_agent_execution_verified: false,
      },
      removal_condition:
        "Remove this bridge after MiniClaw resolves @tintinweb/pi-subagents through its pi.extensions metadata or another ordinary package entry; revalidate first to avoid duplicate registration.",
    };
    const serialized = `${JSON.stringify(report, null, 2)}\n`;
    await fs.mkdir(path.dirname(args.output), { recursive: true });
    await fs.writeFile(args.output, serialized, "utf8");
    process.stdout.write(serialized);
  } finally {
    process.chdir(originalCwd);
    await fs.rm(guardAuditPath, { force: true });
    await fs.rm(backgroundGuardAuditPath, { force: true });
    await fs.rm(duplicateGuardAuditPath, { force: true });
    await fs.rm(strategyGuardAuditPath, { force: true });
    if (tempRoot) {
      await fs.rm(tempRoot, { recursive: true, force: true });
    }
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exitCode = 1;
});
