"use strict";

const DOMAIN_META = {
  content_growth: { name: "内容增长", role: "content_growth_analyst", roleName: "内容增长分析师" },
  live_conversion: { name: "直播转化", role: "live_conversion_analyst", roleName: "直播转化分析师" },
  attribution_leads: { name: "渠道线索", role: "attribution_lead_analyst", roleName: "渠道归因分析师" },
};

const ROLE_NAMES = {
  commerce_ops_supervisor: "经营分析主管",
  content_growth_analyst: "内容增长分析师",
  live_conversion_analyst: "直播转化分析师",
  attribution_lead_analyst: "渠道归因分析师",
  commerce_review_strategist: "复盘策略分析师",
};

const STAGE_NAMES = {
  route: "路由",
  inspect: "检查",
  analyze: "诊断",
  drilldown: "钻取",
  decision: "决策",
  delivery: "交付",
};

const METRIC_NAMES = {
  click_rate: "内容点击率",
  completion_rate: "内容完播率",
  linked_lead_coverage_rate: "线索关联覆盖率",
  attendance_rate: "直播到课率",
  purchase_rate: "到课购买率",
  lead_count: "去重线索数",
  first_followup_within_24h_rate: "24 小时首跟率",
  order_link_coverage_rate: "订单关联覆盖率",
  lead_to_paid_order_conversion_rate: "线索支付转化率",
  impressions: "曝光量",
  plays: "播放量",
  clicks: "点击量",
  reservation_count: "预约数",
  row_count: "记录数",
};

const REQUIRED_TYPES = {
  content_growth: "short_video",
  live_conversion: "live_session",
  attribution_leads: "channel_lead",
};

const state = {
  result: null,
  activeDomain: "content_growth",
  activeMode: "sample",
  running: false,
};

const elements = {};

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  bindEvents();
  checkService();
});

function cacheElements() {
  [
    "service-state",
    "sample-tab",
    "upload-tab",
    "sample-form",
    "upload-form",
    "run-message",
    "empty-state",
    "result-view",
    "result-status",
    "result-summary",
    "workflow-run-id",
    "copy-run-id",
    "rerun-button",
    "download-report",
    "domain-selectors",
    "domain-detail",
    "workflow-list",
    "step-count",
    "action-list",
    "action-count",
    "unresolved-list",
    "evidence-boundary-list",
  ].forEach((id) => {
    elements[id] = document.getElementById(id);
  });
}

function bindEvents() {
  elements["sample-tab"].addEventListener("click", () => setMode("sample"));
  elements["upload-tab"].addEventListener("click", () => setMode("upload"));
  elements["sample-form"].addEventListener("submit", runSample);
  elements["upload-form"].addEventListener("submit", runUpload);
  elements["copy-run-id"].addEventListener("click", copyRunId);
  elements["rerun-button"].addEventListener("click", () => {
    document.querySelector(".run-console").scrollIntoView({ behavior: "smooth" });
  });
}

async function checkService() {
  try {
    const response = await fetch("/v1/demo/scenarios", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error("演示场景读取失败");
    }
    const catalog = await response.json();
    elements["service-state"].textContent = `${catalog.scenarios.length} 个场景可用`;
    elements["service-state"].classList.add("is-ready");
  } catch (error) {
    elements["service-state"].textContent = "服务不可用";
    setMessage("无法连接本地演示服务，请确认 FastAPI 已启动。", true);
  }
}

function setMode(mode) {
  state.activeMode = mode;
  const sampleActive = mode === "sample";
  elements["sample-tab"].classList.toggle("is-active", sampleActive);
  elements["sample-tab"].setAttribute("aria-selected", String(sampleActive));
  elements["upload-tab"].classList.toggle("is-active", !sampleActive);
  elements["upload-tab"].setAttribute("aria-selected", String(!sampleActive));
  elements["sample-form"].hidden = !sampleActive;
  elements["upload-form"].hidden = sampleActive;
  setMessage(
    sampleActive
      ? "运行后将显示完整证据链，结果不会写入外部业务系统。"
      : "上传文件只在本次临时目录内处理，结束后删除。",
    false,
  );
}

async function runSample(event) {
  event.preventDefault();
  const form = new FormData(elements["sample-form"]);
  const requestedDomains = form.getAll("domain");
  if (!requestedDomains.length) {
    setMessage("请至少选择一个分析域。", true);
    return;
  }
  const payload = {
    scenario_id: "full_commerce_funnel",
    requested_domains: requestedDomains,
    objective: String(form.get("objective") || "").trim(),
    top_n: Number(form.get("top_n")),
    include_drilldowns: document.getElementById("include-drilldowns").checked,
  };
  await submitRun("/v1/demo/runs/sample", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  });
}

async function runUpload(event) {
  event.preventDefault();
  const requestedDomains = Array.from(
    elements["upload-form"].querySelectorAll('input[name="upload-domain"]:checked'),
  ).map((input) => input.value);
  if (!requestedDomains.length) {
    setMessage("请至少选择一个分析域。", true);
    return;
  }

  const selectedFiles = Array.from(
    elements["upload-form"].querySelectorAll('input[type="file"]'),
  )
    .filter((input) => input.files && input.files.length)
    .map((input) => ({
      file: input.files[0],
      datasetType: input.dataset.datasetType,
      displayName: input.dataset.displayName,
    }));

  if (!selectedFiles.length) {
    setMessage("请先选择至少一份合成表格。", true);
    return;
  }

  const availableTypes = new Set(selectedFiles.map((item) => item.datasetType));
  const missingTypes = requestedDomains
    .map((domain) => REQUIRED_TYPES[domain])
    .filter((datasetType) => !availableTypes.has(datasetType));
  if (missingTypes.length) {
    setMessage(`所选分析域缺少必需文件：${missingTypes.join("、")}。`, true);
    return;
  }

  const token = Date.now().toString(36);
  const metadata = {
    datasets: selectedFiles.map((item, index) => ({
      dataset_id: `ds_upload_${item.datasetType}_${token}`,
      dataset_type: item.datasetType,
      file_index: index,
      display_name: item.displayName,
    })),
    requested_domains: requestedDomains,
    objective: document.getElementById("upload-objective").value.trim(),
    top_n: 5,
    include_drilldowns: true,
    synthetic: true,
  };
  const body = new FormData();
  body.append("metadata", JSON.stringify(metadata));
  selectedFiles.forEach((item) => body.append("files", item.file));
  await submitRun("/v1/demo/runs/upload", {
    method: "POST",
    headers: { Accept: "application/json" },
    body,
  });
}

async function submitRun(url, options) {
  if (state.running) {
    return;
  }
  setRunning(true);
  try {
    const response = await fetch(url, options);
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    const result = await response.json();
    renderResult(result);
    setMessage(
      `运行完成：${result.workflow_steps.length} 个步骤，${result.analysis_packets.length} 个诊断包。`,
      false,
    );
    elements["result-view"].scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    setMessage(error instanceof Error ? error.message : "演示运行失败。", true);
  } finally {
    setRunning(false);
  }
}

async function readError(response) {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") {
      return body.detail;
    }
    if (Array.isArray(body.detail)) {
      return body.detail.map((item) => item.msg || "输入不符合要求").join("；");
    }
  } catch (error) {
    return `请求失败（HTTP ${response.status}）`;
  }
  return `请求失败（HTTP ${response.status}）`;
}

function setRunning(running) {
  state.running = running;
  document.querySelectorAll(".primary-action").forEach((button) => {
    button.disabled = running;
  });
  setMessage(running ? "正在执行字段检查、三域诊断和证据汇总…" : "", false);
}

function setMessage(message, isError) {
  if (!message) {
    return;
  }
  elements["run-message"].textContent = message;
  elements["run-message"].classList.toggle("is-error", isError);
  elements["run-message"].setAttribute("role", isError ? "alert" : "status");
}

function renderResult(result) {
  state.result = result;
  state.activeDomain = result.analysis_packets[0]?.domain || "content_growth";
  elements["empty-state"].hidden = true;
  elements["result-view"].hidden = false;

  elements["result-status"].textContent = statusName(result.terminal_status);
  elements["result-status"].classList.toggle("is-completed", result.terminal_status === "completed");
  elements["result-summary"].textContent = result.delivery_package.executive_summary;
  elements["workflow-run-id"].textContent = result.workflow_run_id;
  elements["download-report"].href =
    `/v1/demo/runs/${encodeURIComponent(result.workflow_run_id)}/report`;

  renderDomainSelectors(result);
  renderDomainDetail(result, state.activeDomain);
  renderWorkflow(result.workflow_steps);
  renderActions(result.decision_packet?.actions || []);
  renderBoundaries(result.unresolved_items, result.evidence_boundaries);
}

function renderDomainSelectors(result) {
  elements["domain-selectors"].innerHTML = result.analysis_packets
    .map((packet) => {
      const meta = DOMAIN_META[packet.domain];
      const metrics = result.summary_metrics
        .filter((metric) => metric.domain === packet.domain)
        .slice(0, 2);
      return `
        <button
          class="domain-selector"
          type="button"
          data-domain="${escapeHtml(packet.domain)}"
          aria-pressed="${packet.domain === state.activeDomain}"
        >
          <header>
            <h3>${escapeHtml(meta.name)}</h3>
            <span class="domain-status">${escapeHtml(statusName(packet.terminal_status))}</span>
          </header>
          <span class="metric-cluster">
            ${metrics.map((metric) => `
              <span class="metric-brief">
                <small>${escapeHtml(metricName(metric.metric_name))}</small>
                <strong>${escapeHtml(formatMetric(metric.metric_value, metric.unit))}</strong>
              </span>
            `).join("")}
          </span>
        </button>
      `;
    })
    .join("");

  elements["domain-selectors"].querySelectorAll(".domain-selector").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeDomain = button.dataset.domain;
      elements["domain-selectors"].querySelectorAll(".domain-selector").forEach((item) => {
        item.setAttribute("aria-pressed", String(item === button));
      });
      renderDomainDetail(result, state.activeDomain);
    });
  });
}

function renderDomainDetail(result, domain) {
  const packet = result.analysis_packets.find((item) => item.domain === domain);
  if (!packet) {
    elements["domain-detail"].innerHTML = "<p>当前分析域没有结果。</p>";
    return;
  }
  const meta = DOMAIN_META[domain];
  const finding = packet.findings[0];
  const drilldown = result.drilldowns.find((item) => item.caller_role === meta.role);

  elements["domain-detail"].innerHTML = `
    <div class="domain-detail-grid">
      <div class="evidence-column">
        <div class="finding-block ${finding?.severity === "attention" ? "is-attention" : ""}">
          <span>${escapeHtml(meta.roleName)} · ${escapeHtml(finding?.severity || "unknown")}</span>
          <p>${escapeHtml(finding?.statement || "当前没有可交付的经营判断。")}</p>
        </div>
        <h3>证据条目</h3>
        <div class="evidence-stack">
          ${packet.evidence.map((evidence) => `
            <article class="evidence-item">
              <header>
                <h4>${escapeHtml(metricName(evidence.metric_name))}</h4>
                <span class="evidence-value">${escapeHtml(formatMetric(evidence.metric_value, evidence.unit))}</span>
              </header>
              <p>${escapeHtml(evidence.statement)}</p>
              <code>${escapeHtml(evidence.evidence_id)}</code>
            </article>
          `).join("")}
        </div>
      </div>
      <div class="drilldown-chart">
        <h3>${drilldown ? `${escapeHtml(dimensionName(drilldown.dimension))} Top ${drilldown.rows.length}` : "未启用维度钻取"}</h3>
        ${renderBars(drilldown)}
        <p class="chart-note">
          图形只展示本次确定性计算结果；没有成本字段时不计算 ROI，不把相关性写成因果关系。
        </p>
      </div>
    </div>
  `;
}

function renderBars(drilldown) {
  if (!drilldown || !drilldown.rows.length) {
    return '<p class="chart-note">本次请求未返回钻取数据。</p>';
  }
  const metricKey = selectChartMetric(drilldown.rows);
  const values = drilldown.rows.map((row) => Number(row.metrics[metricKey]) || 0);
  const maxValue = Math.max(...values, 1);
  return `
    <div class="bar-list">
      ${drilldown.rows.map((row, index) => {
        const value = values[index];
        const width = Math.max((value / maxValue) * 100, 3);
        return `
          <div class="bar-row">
            <span class="bar-label" title="${escapeHtml(row.dimension_value)}">${escapeHtml(row.dimension_value)}</span>
            <span class="bar-track" aria-hidden="true">
              <span class="bar-fill" style="width: ${width.toFixed(2)}%"></span>
            </span>
            <span class="bar-value">${escapeHtml(formatMetric(value, metricKey.includes("rate") ? "ratio" : "rows"))}</span>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function selectChartMetric(rows) {
  const preferred = ["click_rate", "attendance_rate", "purchase_rate", "row_count", "reservation_count"];
  const available = Object.keys(rows[0]?.metrics || {});
  return (
    preferred.find((key) => available.includes(key)) ||
    available.find((key) => typeof rows[0].metrics[key] === "number") ||
    available[0]
  );
}

function renderWorkflow(steps) {
  elements["step-count"].textContent = `${steps.length} steps`;
  elements["workflow-list"].innerHTML = steps
    .map((step, index) => `
      <li class="workflow-step ${step.terminal_status === "partial" ? "is-partial" : ""}">
        <span class="step-dot">${String(index + 1).padStart(2, "0")}</span>
        <span class="step-content">
          <strong>${escapeHtml(step.label)}</strong>
          <small>${escapeHtml(ROLE_NAMES[step.actor_role] || step.actor_role)} · ${escapeHtml(STAGE_NAMES[step.stage] || step.stage)}</small>
        </span>
        <span class="step-duration">${step.duration_ms == null ? "—" : `${Number(step.duration_ms).toFixed(1)} ms`}</span>
      </li>
    `)
    .join("");
}

function renderActions(actions) {
  elements["action-count"].textContent = `${actions.length} actions`;
  elements["action-list"].innerHTML = actions.length
    ? actions.map((action) => `
      <article class="action-card">
        <header>
          <span class="action-owner">${escapeHtml(action.owner_role)}</span>
          <span class="priority-badge">${escapeHtml(action.priority.toUpperCase())}</span>
        </header>
        <p>${escapeHtml(action.action)}</p>
        <div class="verify-line">
          <strong>复验：</strong>
          ${escapeHtml(metricName(action.verification_metric.name))}
          · 基线 ${escapeHtml(formatMetric(action.verification_metric.baseline, action.verification_metric.unit))}
          · ${escapeHtml(action.verification_metric.check_after)}
        </div>
      </article>
    `).join("")
    : '<p class="chart-note">当前没有可交付动作。</p>';
}

function renderBoundaries(unresolvedItems, evidenceBoundaries) {
  elements["unresolved-list"].innerHTML = unresolvedItems.length
    ? unresolvedItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")
    : "<li>本次没有新增待补证据。</li>";
  elements["evidence-boundary-list"].innerHTML = evidenceBoundaries
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
}

async function copyRunId() {
  const value = state.result?.workflow_run_id;
  if (!value) {
    return;
  }
  try {
    await navigator.clipboard.writeText(value);
    elements["copy-run-id"].textContent = "已复制";
    window.setTimeout(() => {
      elements["copy-run-id"].textContent = "复制 run_id";
    }, 1600);
  } catch (error) {
    setMessage("浏览器未允许复制，请手动选择 run_id。", true);
  }
}

function metricName(name) {
  return METRIC_NAMES[name] || name;
}

function dimensionName(dimension) {
  return {
    content: "内容维度",
    live_session: "直播场次",
    channel: "渠道维度",
  }[dimension] || dimension;
}

function statusName(status) {
  return {
    completed: "已完成",
    partial: "部分完成",
    blocked: "已阻断",
    uncertain: "结果不确定",
  }[status] || status;
}

function formatMetric(value, unit) {
  if (value == null) {
    return "—";
  }
  if (unit === "ratio") {
    return `${(Number(value) * 100).toFixed(1)}%`;
  }
  if (unit === "rows") {
    return Number(value).toLocaleString("zh-CN");
  }
  return String(value);
}

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
      })[character],
  );
}
