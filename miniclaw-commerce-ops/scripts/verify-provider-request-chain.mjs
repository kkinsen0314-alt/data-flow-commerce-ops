import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

import {
  DefaultResourceLoader,
  SettingsManager,
} from "../.pi/extensions/commerce-ops-mcp/node_modules/@earendil-works/pi-coding-agent/dist/index.js";

const PROJECT_ROOT = path.resolve(import.meta.dirname, "..");
const TEMP_PARENT = path.join(PROJECT_ROOT, "tmp");
const BRIDGE_ENTRY = path.join(
  PROJECT_ROOT,
  ".pi",
  "extensions",
  "miniclaw-subagents-bridge",
  "index.ts",
);
const COMMERCE_ENTRY = path.join(
  PROJECT_ROOT,
  ".pi",
  "extensions",
  "commerce-ops-mcp",
  "index.ts",
);
const PI_AI_ROOT = path.join(
  PROJECT_ROOT,
  ".pi",
  "extensions",
  "commerce-ops-mcp",
  "node_modules",
  "@earendil-works",
  "pi-coding-agent",
  "node_modules",
  "@earendil-works",
  "pi-ai",
);
const ANTHROPIC_MESSAGES_ENTRY = path.join(
  PI_AI_ROOT,
  "dist",
  "api",
  "anthropic-messages.js",
);

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

async function applyProviderHandlers(handlers, payload) {
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

function mockAnthropicSse() {
  return [
    "event: message_start",
    `data: ${JSON.stringify({
      type: "message_start",
      message: {
        id: "msg_project017_no_model_validation",
        type: "message",
        role: "assistant",
        model: "project017-no-model-validation",
        content: [],
        stop_reason: null,
        stop_sequence: null,
        usage: { input_tokens: 1, output_tokens: 0 },
      },
    })}`,
    "",
    "event: message_delta",
    `data: ${JSON.stringify({
      type: "message_delta",
      delta: { stop_reason: "end_turn", stop_sequence: null },
      usage: { output_tokens: 1 },
    })}`,
    "",
    "event: message_stop",
    `data: ${JSON.stringify({ type: "message_stop" })}`,
    "",
    "",
  ].join("\n");
}

async function requestBody(input, init) {
  if (typeof init?.body === "string") return init.body;
  if (input instanceof Request) return input.clone().text();
  return "";
}

async function serializeThroughAnthropic(anthropicStream, handlers, label) {
  let fetchCalls = 0;
  let capturedUrl = null;
  let capturedBody = null;
  let payloadAfterHook = null;
  const fakeFetch = async (input, init) => {
    fetchCalls += 1;
    capturedUrl = String(input instanceof Request ? input.url : input);
    capturedBody = JSON.parse(await requestBody(input, init));
    return new Response(mockAnthropicSse(), {
      status: 200,
      headers: { "content-type": "text/event-stream" },
    });
  };
  const model = {
    id: "project017-no-model-validation",
    name: "project017 no-model validation",
    api: "anthropic-messages",
    provider: "project017-mock-provider",
    baseUrl: "https://provider.invalid/apps/anthropic",
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 128_000,
    maxTokens: 1_024,
  };
  const context = {
    messages: [
      {
        role: "user",
        content: `serialize ${label}`,
        timestamp: 0,
      },
    ],
    tools: [
      {
        name: "project017_validation_tool_a",
        description: "No-op validation tool A",
        parameters: { type: "object", properties: {}, additionalProperties: false },
      },
      {
        name: "project017_validation_tool_b",
        description: "No-op validation tool B",
        parameters: { type: "object", properties: {}, additionalProperties: false },
      },
    ],
  };
  const stream = anthropicStream(model, context, {
    apiKey: "project017-dummy-key-no-network",
    fetch: fakeFetch,
    onPayload: async (payload) => {
      payloadAfterHook = await applyProviderHandlers(handlers, payload);
      return payloadAfterHook;
    },
  });
  const eventTypes = [];
  for await (const event of stream) eventTypes.push(event.type);
  return {
    label,
    fetch_calls: fetchCalls,
    captured_url: capturedUrl,
    payload_after_hook: {
      tool_count: payloadAfterHook?.tools?.length ?? 0,
      tool_choice: payloadAfterHook?.tool_choice ?? null,
      stream_present: Object.hasOwn(payloadAfterHook ?? {}, "stream"),
    },
    serialized_request: {
      tool_count: capturedBody?.tools?.length ?? 0,
      tool_choice: capturedBody?.tool_choice ?? null,
      stream: capturedBody?.stream ?? null,
      top_level_parallel_tool_calls_present: Object.hasOwn(
        capturedBody ?? {},
        "parallel_tool_calls",
      ),
    },
    response_event_types: eventTypes,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const checks = [];
  let tempRoot;
  process.env.COMMERCE_OPS_PROJECT_ROOT = PROJECT_ROOT;
  try {
    await fs.mkdir(TEMP_PARENT, { recursive: true });
    tempRoot = await fs.mkdtemp(path.join(TEMP_PARENT, "provider-chain-"));
    const resolvedTemp = path.resolve(tempRoot);
    if (!resolvedTemp.startsWith(`${path.resolve(TEMP_PARENT)}${path.sep}`)) {
      throw new Error("临时目录越出 project017/tmp，拒绝继续");
    }
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
      additionalExtensionPaths: [BRIDGE_ENTRY, COMMERCE_ENTRY],
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
      "Pi DefaultResourceLoader loads both project017 extensions without errors",
    );
    const bridge = loaded.extensions.find((extension) =>
      extension.tools.has("Agent"),
    );
    const commerce = loaded.extensions.find((extension) =>
      extension.tools.has("commerce_ops_inspect_commerce_data"),
    );
    check(
      checks,
      "loader:bridge-found",
      Boolean(bridge),
      "Pi loader exposes the bridged Agent tool",
    );
    check(
      checks,
      "loader:commerce-extension-found",
      Boolean(commerce),
      "Pi loader exposes the commerce_ops tool extension",
    );
    const bridgeHandlers = bridge.handlers.get("before_provider_request") ?? [];
    const commerceHandlers =
      commerce.handlers.get("before_provider_request") ?? [];
    check(
      checks,
      "loader:bridge-provider-handler",
      bridgeHandlers.length === 1,
      "Supervisor bridge registers exactly one provider request handler",
    );
    check(
      checks,
      "loader:commerce-provider-handler",
      commerceHandlers.length === 1,
      "Specialist extension registers exactly one provider request handler",
    );

    const imported = await import(
      `${pathToFileURL(ANTHROPIC_MESSAGES_ENTRY).href}?v=${Date.now()}`
    );
    check(
      checks,
      "serializer:anthropic-stream-loaded",
      typeof imported.stream === "function",
      "Pi 0.84.2 Anthropic Messages serializer is loaded directly",
    );
    const supervisor = await serializeThroughAnthropic(
      imported.stream,
      bridgeHandlers,
      "supervisor",
    );
    const specialist = await serializeThroughAnthropic(
      imported.stream,
      commerceHandlers,
      "specialist",
    );
    for (const observation of [supervisor, specialist]) {
      check(
        checks,
        `serializer:${observation.label}:single-fetch`,
        observation.fetch_calls === 1,
        `${observation.label} serialization invokes only the injected fetch once`,
      );
      check(
        checks,
        `serializer:${observation.label}:mock-endpoint-only`,
        new URL(observation.captured_url).hostname === "provider.invalid",
        `${observation.label} request is intercepted at the non-routable mock endpoint`,
      );
      check(
        checks,
        `serializer:${observation.label}:hook-output`,
        observation.payload_after_hook.tool_choice?.type === "auto" &&
          observation.payload_after_hook.tool_choice
            ?.disable_parallel_tool_use === true,
        `${observation.label} hook returns Anthropic single-tool choice semantics`,
      );
      check(
        checks,
        `serializer:${observation.label}:wire-body`,
        observation.serialized_request.tool_choice?.type === "auto" &&
          observation.serialized_request.tool_choice
            ?.disable_parallel_tool_use === true &&
          observation.serialized_request.stream === true,
        `${observation.label} serialized HTTP JSON body retains disable_parallel_tool_use=true`,
      );
    }

    const report = {
      schema_version: "1.0",
      validation_kind: "project017_provider_request_chain_no_model",
      status: checks.every((item) => item.status === "pass")
        ? "pass"
        : "fail",
      generated_at: new Date().toISOString(),
      project_root: PROJECT_ROOT,
      runtime: {
        node_version: process.version,
        pi_host_version: "0.84.2",
        pi_ai_version: "0.84.2",
        protocol: "anthropic-messages",
        loader: "DefaultResourceLoader",
        serializer: "pi-ai anthropic-messages stream",
        http_transport: "injected in-process fake fetch",
      },
      observations: { supervisor, specialist },
      diagnosis: {
        local_hook_loaded: true,
        local_hook_return_used: true,
        serialized_http_body_retains_single_tool_field: true,
        local_request_chain_bypass_observed: false,
        provider_semantics_executed: false,
        proven_boundary:
          "The field reaches the serialized Anthropic HTTP JSON body. This harness does not call or emulate the Alibaba endpoint's behavioral semantics.",
      },
      checks_total: checks.length,
      checks_passed: checks.filter((item) => item.status === "pass").length,
      checks_failed: checks.filter((item) => item.status === "fail").length,
      checks,
      evidence_boundary: {
        project014_modified: false,
        project015_modified: false,
        provider_configuration_read: false,
        provider_credential_read: false,
        real_network_request_sent: false,
        model_runtime_created: false,
        agent_session_created: false,
        mcp_transport_started: false,
        real_model_called: false,
        paid_usage_incurred: false,
      },
    };
    const serialized = `${JSON.stringify(report, null, 2)}\n`;
    if (args.output) {
      await fs.mkdir(path.dirname(args.output), { recursive: true });
      await fs.writeFile(args.output, serialized, "utf8");
    }
    process.stdout.write(serialized);
  } finally {
    if (tempRoot) await fs.rm(tempRoot, { recursive: true, force: true });
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exitCode = 1;
});
