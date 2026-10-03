export const EXPECTED_TOOLS = [
  "commerce_ops_inspect_commerce_data",
  "commerce_ops_analyze_short_video_data",
  "commerce_ops_analyze_live_commerce_data",
  "commerce_ops_analyze_attribution_and_leads",
  "commerce_ops_drilldown_commerce_metric",
];

const CONTENT_REFS = [
  {
    dataset_id: "ds_video_pi",
    dataset_type: "short_video",
    file_path: "short_video/synthetic-short-video.csv",
    synthetic: true,
  },
  {
    dataset_id: "ds_lead_content_pi",
    dataset_type: "channel_lead",
    file_path: "leads/synthetic-channel-leads.csv",
    synthetic: true,
  },
];

const LIVE_REFS = [
  {
    dataset_id: "ds_live_pi",
    dataset_type: "live_session",
    file_path: "live/synthetic-live-integration.csv",
    synthetic: true,
  },
];

const ATTRIBUTION_REFS = [
  {
    dataset_id: "ds_lead_pi",
    dataset_type: "channel_lead",
    file_path: "leads/synthetic-channel-leads.csv",
    synthetic: true,
  },
  {
    dataset_id: "ds_followup_pi",
    dataset_type: "sales_followup",
    file_path: "followup/synthetic-sales-followup.csv",
    synthetic: true,
  },
  {
    dataset_id: "ds_order_pi",
    dataset_type: "order",
    file_path: "orders/synthetic-orders.csv",
    synthetic: true,
  },
];

function payloadFromResult(result) {
  if (result?.details?.structuredContent) {
    return result.details.structuredContent;
  }
  for (const item of result?.content ?? []) {
    if (item?.type !== "text") continue;
    try {
      return JSON.parse(item.text);
    } catch {
    }
  }
  throw new Error("Pi tool result 中没有可解析的结构化 JSON");
}

function addCheck(checks, checkId, condition, detail) {
  checks.push({
    check_id: checkId,
    status: condition ? "pass" : "fail",
    detail,
  });
  if (!condition) throw new Error(`${checkId}: ${detail}`);
}

export async function runSyntheticToolSequence(
  registeredTools,
  caller,
  callIdPrefix,
) {
  const checks = [];
  const toolCalls = [];
  const guardCalls = [];

  addCheck(
    checks,
    "tools:sequential-execution-mode",
    [...registeredTools.values()].every(
      (tool) => tool.executionMode === "sequential",
    ),
    "all commerce tools force Pi to execute provider-emitted calls in source order",
  );

  async function invoke(toolName, params) {
    const tool = registeredTools.get(toolName);
    if (!tool) throw new Error(`缺少 Pi tool：${toolName}`);
    const startedAt = performance.now();
    const result = await tool.execute(
      `${callIdPrefix}_${toolName}_${toolCalls.length + 1}`,
      params,
      new AbortController().signal,
      undefined,
      undefined,
    );
    const durationMs = Number((performance.now() - startedAt).toFixed(3));
    const payload = payloadFromResult(result);
    toolCalls.push({
      tool_name: toolName,
      caller,
      invocation_count: 1,
      automatic_retry_attempted: false,
      duration_ms: durationMs,
      terminal_status: payload.terminal_status,
      workflow_run_id: payload.workflow_run_id,
      service_run_id: payload.service_run_id,
    });
    return payload;
  }

  const contentWorkflow = `wf_${callIdPrefix}_content`;
  const contentInspection = await invoke(
    "commerce_ops_inspect_commerce_data",
    {
      workflow_run_id: contentWorkflow,
      caller_role: "content_growth_analyst",
      data_refs: CONTENT_REFS,
      requested_domains: ["content_growth"],
    },
  );
  addCheck(
    checks,
    "call:content-inspect",
    contentInspection.terminal_status === "completed" &&
      contentInspection.caller_role === "content_growth_analyst" &&
      contentInspection.dataset_manifests?.length === 2,
    "content specialist registers two synthetic datasets in its own workflow",
  );
  const contentAnalysis = await invoke(
    "commerce_ops_analyze_short_video_data",
    {
      workflow_run_id: contentWorkflow,
      dataset_ids: ["ds_video_pi", "ds_lead_content_pi"],
      requested_dimensions: ["content"],
      top_n: 3,
      synthetic: true,
    },
  );
  addCheck(
    checks,
    "call:content-analysis",
    contentAnalysis.terminal_status === "completed" &&
      contentAnalysis.analysis_packet?.agent_role ===
        "content_growth_analyst",
    "short-video analysis completes with the content role",
  );
  const contentPacket = contentAnalysis.analysis_packet;
  const drilldown = await invoke(
    "commerce_ops_drilldown_commerce_metric",
    {
      workflow_run_id: contentWorkflow,
      caller_role: "content_growth_analyst",
      base_analysis_run_id: contentPacket.analysis_run_id,
      evidence_id: contentPacket.evidence[0].evidence_id,
      dimension: "content",
      top_n: 3,
      synthetic: true,
    },
  );
  addCheck(
    checks,
    "call:content-drilldown",
    drilldown.terminal_status === "completed" &&
      drilldown.caller_role === "content_growth_analyst" &&
      drilldown.rows?.length === 3,
    "content drilldown is role-matched and remains synthetic",
  );
  const duplicateContentResult = await registeredTools
    .get("commerce_ops_analyze_short_video_data")
    .execute(
      `${callIdPrefix}_duplicate_content_analysis_guard`,
      {
        workflow_run_id: contentWorkflow,
        dataset_ids: ["ds_video_pi"],
        requested_dimensions: ["content"],
        top_n: 3,
        synthetic: true,
      },
      new AbortController().signal,
      undefined,
      undefined,
    );
  const duplicateContentPayload = payloadFromResult(duplicateContentResult);
  guardCalls.push({
    guard: "duplicate_analysis_provider_proposal",
    is_error: duplicateContentResult.isError === true,
    terminal_status: duplicateContentPayload.terminal_status,
    disposition:
      duplicateContentResult.details?.project017ProviderProposal?.disposition,
    canonical_tool_call_id:
      duplicateContentResult.details?.project017ProviderProposal
        ?.canonicalToolCallId,
  });
  addCheck(
    checks,
    "admission:duplicate-analysis-coalesced",
    duplicateContentResult.isError !== true &&
      duplicateContentPayload.terminal_status ===
        contentAnalysis.terminal_status &&
      duplicateContentPayload.service_run_id ===
        contentAnalysis.service_run_id &&
      duplicateContentResult.details?.project017ProviderProposal
        ?.disposition === "coalesced" &&
      duplicateContentResult.details?.project017ProviderProposal
        ?.canonicalToolCallId ===
        `${callIdPrefix}_commerce_ops_analyze_short_video_data_2`,
    "a repeated analysis proposal reuses the first result without another MCP execution or a workflow failure",
  );

  const liveWorkflow = `wf_${callIdPrefix}_live`;
  const liveInspection = await invoke(
    "commerce_ops_inspect_commerce_data",
    {
      workflow_run_id: liveWorkflow,
      caller_role: "live_conversion_analyst",
      data_refs: LIVE_REFS,
      requested_domains: ["live_conversion"],
    },
  );
  addCheck(
    checks,
    "call:live-inspect",
    liveInspection.terminal_status === "completed" &&
      liveInspection.caller_role === "live_conversion_analyst" &&
      liveInspection.dataset_manifests?.length === 1,
    "live specialist registers its synthetic dataset",
  );
  const liveAnalysis = await invoke(
    "commerce_ops_analyze_live_commerce_data",
    {
      workflow_run_id: liveWorkflow,
      dataset_ids: ["ds_live_pi"],
      requested_dimensions: ["live_session", "channel"],
      top_n: 3,
      synthetic: true,
    },
  );
  addCheck(
    checks,
    "call:live-analysis",
    liveAnalysis.terminal_status === "completed" &&
      liveAnalysis.analysis_packet?.agent_role ===
        "live_conversion_analyst",
    "live analysis completes with the live-conversion role",
  );

  const attributionWorkflow = `wf_${callIdPrefix}_attribution`;
  const attributionInspection = await invoke(
    "commerce_ops_inspect_commerce_data",
    {
      workflow_run_id: attributionWorkflow,
      caller_role: "attribution_lead_analyst",
      data_refs: ATTRIBUTION_REFS,
      requested_domains: ["attribution_leads"],
    },
  );
  addCheck(
    checks,
    "call:attribution-inspect",
    attributionInspection.terminal_status === "completed" &&
      attributionInspection.caller_role === "attribution_lead_analyst" &&
      attributionInspection.dataset_manifests?.length === 3,
    "attribution specialist registers lead, follow-up, and order datasets",
  );
  const attributionAnalysis = await invoke(
    "commerce_ops_analyze_attribution_and_leads",
    {
      workflow_run_id: attributionWorkflow,
      dataset_ids: ["ds_lead_pi", "ds_followup_pi", "ds_order_pi"],
      requested_dimensions: ["channel", "sales_owner", "order_status"],
      link_orders: true,
      calculate_roi: false,
      top_n: 3,
      synthetic: true,
    },
  );
  addCheck(
    checks,
    "call:attribution-analysis",
    attributionAnalysis.terminal_status === "partial" &&
      attributionAnalysis.analysis_packet?.agent_role ===
        "attribution_lead_analyst" &&
      attributionAnalysis.analysis_packet?.missing_evidence?.length > 0,
    "attribution analysis preserves partial status and missing evidence",
  );

  const incompleteAttributionWorkflow =
    `wf_${callIdPrefix}_attribution_missing_refs`;
  const incompleteAttributionResult = await registeredTools
    .get("commerce_ops_inspect_commerce_data")
    .execute(
      `${callIdPrefix}_attribution_missing_refs_guard`,
      {
        workflow_run_id: incompleteAttributionWorkflow,
        caller_role: "attribution_lead_analyst",
        data_refs: [ATTRIBUTION_REFS[0]],
        requested_domains: ["attribution_leads"],
      },
      new AbortController().signal,
      undefined,
      undefined,
    );
  const incompleteAttributionPayload = payloadFromResult(
    incompleteAttributionResult,
  );
  guardCalls.push({
    guard: "attribution_required_datasets",
    is_error: incompleteAttributionResult.isError === true,
    terminal_status: incompleteAttributionPayload.terminal_status,
    reason_code: incompleteAttributionPayload.reason_code,
  });
  addCheck(
    checks,
    "guard:attribution-required-datasets",
    incompleteAttributionResult.isError === true &&
      incompleteAttributionPayload.terminal_status === "blocked" &&
      incompleteAttributionPayload.reason_code ===
        "required_inspect_dataset_types_missing:sales_followup,order" &&
      incompleteAttributionPayload.service_run_id === null,
    "attribution inspect is blocked before MCP execution unless lead, follow-up, and order datasets are all present",
  );

  const counts = new Map();
  for (const entry of toolCalls) {
    counts.set(entry.tool_name, (counts.get(entry.tool_name) ?? 0) + 1);
  }
  addCheck(
    checks,
    "calls:expected-counts",
    toolCalls.length === 7 &&
      counts.get("commerce_ops_inspect_commerce_data") === 3 &&
      EXPECTED_TOOLS.every((name) => counts.has(name)),
    "three role-local inspections plus one call for each remaining Pi tool",
  );

  return { checks, toolCalls, guardCalls };
}
