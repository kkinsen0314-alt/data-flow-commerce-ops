import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  EXPECTED_TOOLS,
  runSyntheticToolSequence,
} from "./validation-shared.mjs";

const EXTENSION_ROOT = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(EXTENSION_ROOT, "..", "..", "..");
const PLATFORM_COMMIT = "3ff1c8d6a0707f4a9f0957ff411758e5e141583a";

function parseArgs(argv) {
  const outputIndex = argv.indexOf("--output");
  if (outputIndex === -1) return { output: undefined };
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

async function applyProviderRequestHandlers(handlers, payload) {
  let current = payload;
  for (const handler of handlers) {
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
  const registeredTools = new Map();
  const eventHandlers = new Map();
  let shutdownInvoked = false;

  process.env.COMMERCE_OPS_PROJECT_ROOT = PROJECT_ROOT;
  const packageJson = JSON.parse(
    await fs.readFile(path.join(EXTENSION_ROOT, "package.json"), "utf8"),
  );
  const packageLock = JSON.parse(
    await fs.readFile(path.join(EXTENSION_ROOT, "package-lock.json"), "utf8"),
  );
  check(
    checks,
    "dependency:pi-host-lock",
    packageJson.dependencies?.["@earendil-works/pi-coding-agent"] ===
      "0.84.2" &&
      packageLock.packages?.[
        "node_modules/@earendil-works/pi-coding-agent"
      ]?.version === "0.84.2",
    "Pi host is installed and locked to MiniClaw version 0.84.2",
  );
  check(
    checks,
    "dependency:sdk-lock",
    packageJson.dependencies?.["@modelcontextprotocol/sdk"] === "1.30.0" &&
      packageLock.packages?.["node_modules/@modelcontextprotocol/sdk"]
        ?.version === "1.30.0",
    "MCP SDK is installed and locked to 1.30.0",
  );
  check(
    checks,
    "dependency:typebox-lock",
    packageJson.dependencies?.typebox === "1.3.7" &&
      packageLock.packages?.["node_modules/typebox"]?.version === "1.3.7",
    "typebox is installed and locked to 1.3.7",
  );

  const imported = await import(
    `${pathToFileURL(path.join(EXTENSION_ROOT, "index.ts")).href}?v=${Date.now()}`
  );
  check(
    checks,
    "extension:default-export",
    typeof imported.default === "function",
    "index.ts exports an extension initializer",
  );
  imported.default({
    registerTool(tool) {
      if (registeredTools.has(tool.name)) {
        throw new Error(`重复注册 Pi tool：${tool.name}`);
      }
      registeredTools.set(tool.name, tool);
    },
    on(eventName, handler) {
      const handlers = eventHandlers.get(eventName) ?? [];
      handlers.push(handler);
      eventHandlers.set(eventName, handlers);
    },
  });

  const registeredNames = [...registeredTools.keys()].sort();
  check(
    checks,
    "extension:exactly-five-tools",
    registeredNames.join(",") === [...EXPECTED_TOOLS].sort().join(","),
    "extension registers exactly the five expected commerce_ops tools",
  );
  check(
    checks,
    "extension:shutdown-handler",
    (eventHandlers.get("session_shutdown")?.length ?? 0) === 1,
    "extension registers one session_shutdown handler",
  );
  const providerRequestHandlers =
    eventHandlers.get("before_provider_request") ?? [];
  check(
    checks,
    "extension:single-tool-provider-handler",
    providerRequestHandlers.length === 1,
    "extension registers one before_provider_request handler",
  );
  const existingChoicePayload = await applyProviderRequestHandlers(
    providerRequestHandlers,
    {
      model: "validation-model",
      tools: [{ name: "tool-a" }, { name: "tool-b" }],
      tool_choice: {
        type: "any",
        disable_parallel_tool_use: false,
        vendor_field: "preserved",
      },
    },
  );
  check(
    checks,
    "extension:single-tool-provider-rewrite",
    existingChoicePayload.tool_choice?.type === "any" &&
      existingChoicePayload.tool_choice?.vendor_field === "preserved" &&
      existingChoicePayload.tool_choice?.disable_parallel_tool_use === true,
    "provider rewrite disables parallel tool use while preserving the existing tool choice",
  );
  const defaultChoicePayload = await applyProviderRequestHandlers(
    providerRequestHandlers,
    {
      model: "validation-model",
      tools: [{ name: "tool-a" }],
    },
  );
  check(
    checks,
    "extension:single-tool-provider-default-auto",
    defaultChoicePayload.tool_choice?.type === "auto" &&
      defaultChoicePayload.tool_choice?.disable_parallel_tool_use === true,
    "provider rewrite creates an auto tool choice with at-most-one-call semantics",
  );
  const noToolsPayload = { model: "validation-model", messages: [] };
  const untouchedPayload = await applyProviderRequestHandlers(
    providerRequestHandlers,
    noToolsPayload,
  );
  check(
    checks,
    "extension:no-tool-payload-untouched",
    untouchedPayload === noToolsPayload,
    "provider rewrite leaves requests without tools untouched",
  );

  let sequence;
  try {
    sequence = await runSyntheticToolSequence(
      registeredTools,
      "extension_api_validation_harness",
      "pi_extension_validation",
    );
    checks.push(...sequence.checks);
    const referenceAuditEvents = (
      await fs.readFile(
        path.join(
          PROJECT_ROOT,
          "runtime",
          "data",
          "native-audit",
          "wf_pi_extension_validation_content.jsonl",
        ),
        "utf8",
      )
    )
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line));
    const referenceAuditEvent = referenceAuditEvents.findLast(
      (event) =>
        event.event_type === "attempt_finished" &&
        event.tool_name === "commerce_ops_analyze_short_video_data" &&
        event.status === "completed",
    );
    check(
      checks,
      "audit:analysis-reference-catalog",
      Array.isArray(referenceAuditEvent?.dataset_ids) &&
        referenceAuditEvent.dataset_ids.length > 0 &&
        Array.isArray(referenceAuditEvent?.evidence_ids) &&
        referenceAuditEvent.evidence_ids.length > 0 &&
        Array.isArray(referenceAuditEvent?.finding_ids) &&
        referenceAuditEvent.finding_ids.length > 0 &&
        referenceAuditEvent.finding_ids.every(
          (findingId) =>
            Array.isArray(
              referenceAuditEvent.finding_evidence_links?.[findingId],
            ) &&
            referenceAuditEvent.finding_evidence_links[findingId].length > 0,
        ),
      "completed analysis audit events expose only the ID catalog and finding-to-evidence edges required for deterministic strategy validation",
    );
  } finally {
    for (const handler of eventHandlers.get("session_shutdown") ?? []) {
      await handler({ reason: "validation_complete" });
    }
    shutdownInvoked = true;
  }
  check(
    checks,
    "extension:shutdown-invoked",
    shutdownInvoked,
    "session_shutdown closes the role-local stdio transport",
  );

  const report = {
    schema_version: "1.0",
    validation_kind: "project017_pi_extension_synthetic_runtime",
    status: checks.every((item) => item.status === "pass") ? "pass" : "fail",
    generated_at: new Date().toISOString(),
    project_root: PROJECT_ROOT,
    source_platform_commit: PLATFORM_COMMIT,
    runtime: {
      node_version: process.version,
      module_load_mechanism: "node_native_typescript_type_stripping",
      extension_api_harness: true,
      miniclaw_default_resource_loader_executed: false,
      python_stdio_mcp_spawned: true,
    },
    registered_tools: registeredNames,
    tool_calls: sequence.toolCalls,
    guard_calls: sequence.guardCalls,
    session_shutdown: {
      handler_registered: true,
      invoked: shutdownInvoked,
      status: "pass",
    },
    provider_request_policy: {
      protocol: "anthropic-messages",
      tool_choice_type: defaultChoicePayload.tool_choice.type,
      disable_parallel_tool_use:
        defaultChoicePayload.tool_choice.disable_parallel_tool_use,
      existing_tool_choice_preserved: true,
      no_tool_payload_untouched: untouchedPayload === noToolsPayload,
      model_or_provider_started: false,
    },
    checks_total: checks.length,
    checks_passed: checks.filter((item) => item.status === "pass").length,
    checks_failed: checks.filter((item) => item.status === "fail").length,
    checks,
    evidence_boundary: {
      synthetic_data_only: true,
      extension_module_loaded: true,
      pi_tool_definitions_registered: true,
      mcp_tools_called_by_validation_harness: true,
      stdio_transport_closed: shutdownInvoked,
      provider_configured: false,
      plugin_imported: false,
      plugin_enabled: false,
      agent_profile_created: false,
      workspace_created: false,
      model_runtime_created: false,
      agent_session_created: false,
      provider_request_payload_rewrite_validated: true,
      single_agent_executed: false,
      multi_agent_executed: false,
      real_model_called: false,
      real_business_data_used: false,
      real_business_outcome_claimed: false,
    },
  };
  const serialized = `${JSON.stringify(report, null, 2)}\n`;
  if (args.output) {
    await fs.mkdir(path.dirname(args.output), { recursive: true });
    await fs.writeFile(args.output, serialized, "utf8");
  }
  process.stdout.write(serialized);
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exitCode = 1;
});
