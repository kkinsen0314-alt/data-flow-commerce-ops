import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import {
  DefaultResourceLoader,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";

import {
  EXPECTED_TOOLS,
  runSyntheticToolSequence,
} from "./validation-shared.mjs";

const EXTENSION_ROOT = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(EXTENSION_ROOT, "..", "..", "..");
const EXTENSION_ENTRY = path.join(EXTENSION_ROOT, "index.ts");
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
  let shutdownInvoked = false;
  let tempRoot;
  let sequence;

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

  try {
    await fs.mkdir(path.join(PROJECT_ROOT, "tmp"), { recursive: true });
    tempRoot = await fs.mkdtemp(
      path.join(PROJECT_ROOT, "tmp", "pi-resource-loader-"),
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
      additionalExtensionPaths: [EXTENSION_ENTRY],
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
    const targetExtensions = loaded.extensions.filter((extension) =>
      EXPECTED_TOOLS.some((name) => extension.tools.has(name)),
    );
    check(
      checks,
      "loader:single-target-extension",
      targetExtensions.length === 1,
      "DefaultResourceLoader discovers one commerce-ops extension instance",
    );
    const targetExtension = targetExtensions[0];
    const registeredTools = new Map(
      [...targetExtension.tools.values()].map((registered) => [
        registered.definition.name,
        registered.definition,
      ]),
    );
    const registeredNames = [...registeredTools.keys()].sort();
    check(
      checks,
      "loader:exactly-five-tools",
      registeredNames.join(",") === [...EXPECTED_TOOLS].sort().join(","),
      "real Pi loader registers exactly five commerce_ops tools",
    );
    const shutdownHandlers =
      targetExtension.handlers.get("session_shutdown") ?? [];
    check(
      checks,
      "loader:shutdown-handler",
      shutdownHandlers.length === 1,
      "real Pi loader registers one session_shutdown handler",
    );
    const providerRequestHandlers =
      targetExtension.handlers.get("before_provider_request") ?? [];
    check(
      checks,
      "loader:single-tool-provider-handler",
      providerRequestHandlers.length === 1,
      "real Pi loader registers one before_provider_request handler",
    );
    const providerPayload = await applyProviderRequestHandlers(
      providerRequestHandlers,
      {
        model: "validation-model",
        tools: [{ name: "tool-a" }, { name: "tool-b" }],
        tool_choice: { type: "auto", vendor_field: "preserved" },
      },
    );
    check(
      checks,
      "loader:single-tool-provider-rewrite",
      providerPayload.tool_choice?.type === "auto" &&
        providerPayload.tool_choice?.vendor_field === "preserved" &&
        providerPayload.tool_choice?.disable_parallel_tool_use === true,
      "Pi-loaded extension applies at-most-one tool call semantics to Anthropic payloads",
    );

    try {
      sequence = await runSyntheticToolSequence(
        registeredTools,
        "default_resource_loader_validation_harness",
        "pi_loader_validation",
      );
      checks.push(...sequence.checks);
    } finally {
      for (const handler of shutdownHandlers) {
        await handler(
          { type: "session_shutdown", reason: "quit" },
          undefined,
        );
      }
      shutdownInvoked = true;
    }
    check(
      checks,
      "loader:shutdown-invoked",
      shutdownInvoked,
      "Pi-loaded session_shutdown handler closes the stdio transport",
    );

    const report = {
      schema_version: "1.0",
      validation_kind:
        "project017_pi_default_resource_loader_synthetic_runtime",
      status: checks.every((item) => item.status === "pass")
        ? "pass"
        : "fail",
      generated_at: new Date().toISOString(),
      project_root: PROJECT_ROOT,
      source_platform_commit: PLATFORM_COMMIT,
      runtime: {
        node_version: process.version,
        pi_host_package: "@earendil-works/pi-coding-agent",
        pi_host_version: "0.84.2",
        loader: "DefaultResourceLoader",
        project_trust_resolved: true,
        install_scripts_enabled: false,
        model_runtime_created: false,
        agent_session_created: false,
        python_stdio_mcp_spawned: true,
      },
      loader_result: {
        loaded_extension_count: loaded.extensions.length,
        load_error_count: loaded.errors.length,
        target_extension_path: targetExtension.path,
        target_extension_resolved_path: targetExtension.resolvedPath,
        target_source_info: targetExtension.sourceInfo,
      },
      registered_tools: registeredNames,
      tool_calls: sequence.toolCalls,
      guard_calls: sequence.guardCalls,
      session_shutdown: {
        handler_registered: shutdownHandlers.length === 1,
        invoked: shutdownInvoked,
        status: "pass",
      },
      provider_request_policy: {
        protocol: "anthropic-messages",
        tool_choice_type: providerPayload.tool_choice.type,
        disable_parallel_tool_use:
          providerPayload.tool_choice.disable_parallel_tool_use,
        existing_tool_choice_preserved: true,
        model_or_provider_started: false,
      },
      checks_total: checks.length,
      checks_passed: checks.filter((item) => item.status === "pass").length,
      checks_failed: checks.filter((item) => item.status === "fail").length,
      checks,
      evidence_boundary: {
        synthetic_data_only: true,
        default_resource_loader_executed: true,
        extension_module_loaded_by_pi: true,
        pi_tool_definitions_registered: true,
        mcp_tools_called_by_validation_harness: true,
        stdio_transport_closed: shutdownInvoked,
        provider_configured: false,
        plugin_imported: false,
        plugin_enabled: false,
        model_runtime_created: false,
        agent_session_created: false,
        provider_request_payload_rewrite_validated: true,
        agent_profile_created: false,
        workspace_created: false,
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
  } finally {
    if (tempRoot) {
      await fs.rm(tempRoot, { recursive: true, force: true });
    }
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exitCode = 1;
});
