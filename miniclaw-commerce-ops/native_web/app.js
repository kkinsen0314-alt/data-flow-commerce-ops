const CONFIGURATION_ENDPOINT = "/v1/native/configuration";
const DATA_SOURCES_ENDPOINT = "/v1/native/data-sources";
const RUNS_ENDPOINT = "/v1/native/runs";
const TASKS_ENDPOINT = "/v1/native/tasks";
const RESULT_ENDPOINT_SUFFIX = "/result";
const ACTIVE_RUN_STORAGE_KEY = "miniclaw.native.active-run.v1";
const POLL_INTERVAL_MS = 4000;

const domainLabels = {
  content_growth: "内容增长",
  live_conversion: "直播转化",
  attribution_leads: "渠道与线索",
};

const phaseLabels = {
  reserved: "正在准备",
  preflight: "正在检查环境",
  session_created: "正在创建任务",
  submitted: "已提交",
  running: "分析中",
  settled: "已结束",
};

const resultStateLabels = {
  processing: "正在整理",
  ready: "分析完成",
  needs_review: "分析完成",
  unavailable: "未生成结果",
};

const sourceTypeMarks = {
  local_file: "CSV",
  mysql: "MY",
  postgresql: "PG",
  feishu_bitable: "多",
  feishu_spreadsheet: "表",
  http_api: "API",
  mcp: "MCP",
};

const priorityLabels = {
  high: "高优先级",
  medium: "中优先级",
  low: "低优先级",
};

let runtimeReady = false;
let currentDraft = null;
let activeRunContext = null;
let pollTimer = null;
let submissionInFlight = false;
let taskCatalogLoading = false;

class HttpError extends Error {
  constructor(status, detail) {
    super(detail || `请求返回 ${status}`);
    this.status = status;
  }
}

async function fetchJson(endpoint) {
  const response = await fetch(endpoint, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new HttpError(response.status, `${endpoint} returned ${response.status}`);
  }
  return response.json();
}

async function postJsonOnce(endpoint, payload) {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new HttpError(response.status, body.detail || `请求返回 ${response.status}`);
  }
  return body;
}

function setText(selector, value) {
  const element = document.querySelector(selector);
  if (element) {
    element.textContent = String(value);
  }
}

function setConnectionState(ready) {
  const chip = document.querySelector("[data-runtime-chip]");
  const dot = document.querySelector("[data-sidebar-dot]");
  chip.classList.remove("is-loading", "is-ready", "is-blocked");
  chip.classList.add(ready ? "is-ready" : "is-blocked");
  dot.classList.remove("is-ready", "is-blocked");
  dot.classList.add(ready ? "is-ready" : "is-blocked");
}

function refreshStartButton() {
  const button = document.querySelector("[data-open-confirm]");
  button.disabled = !runtimeReady || !currentDraft || currentDraft.submissionAttempted;
  if (currentDraft?.submissionAttempted) {
    button.textContent = "本次请求已提交";
  } else if (!runtimeReady) {
    button.textContent = "服务就绪后可开始";
  } else {
    button.textContent = "确认并开始";
  }
}

function renderRuntime(configuration) {
  runtimeReady = Boolean(configuration.ready);
  const state = document.querySelector("[data-ready-state]");
  const note = document.querySelector("[data-runtime-note]");

  setConnectionState(runtimeReady);
  setText("[data-runtime-label]", runtimeReady ? "分析服务已就绪" : "分析服务未启动");
  setText("[data-sidebar-state]", runtimeReady ? "服务已连接" : "服务未就绪");
  setText("[data-workspace-state]", configuration.workspace_configured ? "已连接" : "未连接");
  setText("[data-credentials-state]", configuration.credentials_configured ? "可用" : "未配置");
  setText(
    "[data-retry-state]",
    configuration.automatic_model_retry === false ? "关闭" : "需要检查",
  );

  state.classList.remove("is-loading", "is-ready", "is-blocked");
  state.classList.add(runtimeReady ? "is-ready" : "is-blocked");
  state.textContent = runtimeReady ? "可运行" : "待启动";
  note.classList.remove("is-ready", "is-blocked");
  note.classList.add(runtimeReady ? "is-ready" : "is-blocked");
  note.textContent = runtimeReady
    ? "环境已准备完成。每次正式提交都需要单独确认可能产生的模型费用。"
    : "启动本机分析服务并完成访问配置后，即可运行任务。";
  refreshStartButton();
}

function renderRuntimeError() {
  runtimeReady = false;
  const state = document.querySelector("[data-ready-state]");
  const note = document.querySelector("[data-runtime-note]");

  setConnectionState(false);
  setText("[data-runtime-label]", "分析服务不可用");
  setText("[data-sidebar-state]", "服务连接失败");
  setText("[data-workspace-state]", "无法检查");
  setText("[data-credentials-state]", "无法检查");
  setText("[data-retry-state]", "无法检查");
  state.classList.remove("is-loading", "is-ready");
  state.classList.add("is-blocked");
  state.textContent = "连接失败";
  note.classList.remove("is-ready");
  note.classList.add("is-blocked");
  note.textContent = "无法读取本机服务状态。请确认后台服务已经启动。";
  refreshStartButton();
}

function createSourceOption(source) {
  const option = document.createElement("option");
  option.value = source.source_id;
  option.textContent = `${source.display_name} · ${source.source_type_label}`;
  return option;
}

function createSourceRow(source) {
  const row = document.createElement("div");
  row.className = "data-row";
  row.setAttribute("role", "row");

  const name = document.createElement("div");
  name.className = "source-name";
  const mark = document.createElement("span");
  mark.className = "source-mark";
  mark.textContent = sourceTypeMarks[source.source_type] || "数";
  const nameCopy = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = source.display_name;
  const description = document.createElement("small");
  description.textContent = source.description;
  nameCopy.append(title, description);
  name.append(mark, nameCopy);

  const type = document.createElement("span");
  type.className = "data-detail source-type";
  type.textContent = source.source_type_label;

  const coverage = document.createElement("span");
  coverage.className = "data-detail";
  coverage.textContent = (source.dataset_labels || []).join("、");

  const amount = document.createElement("span");
  amount.className = "data-detail";
  amount.textContent = `${source.dataset_count} 个数据集 / ${source.record_count} 条`;

  const status = document.createElement("span");
  status.className = "source-status";
  status.classList.add("is-" + source.status);
  status.textContent = source.status === "ready" ? "已就绪" : "需要检查";

  row.append(name, type, coverage, amount, status);
  return row;
}

function createSourceTypeCard(sourceType) {
  const card = document.createElement("article");
  card.className = "connector-card";
  card.dataset.sourceType = sourceType.type_id;

  const heading = document.createElement("div");
  heading.className = "connector-card__heading";
  const mark = document.createElement("span");
  mark.className = "connector-mark";
  mark.textContent = sourceTypeMarks[sourceType.type_id] || "数";
  const title = document.createElement("strong");
  title.textContent = sourceType.display_name;
  const status = document.createElement("span");
  status.className = "connector-status is-" + sourceType.status;
  status.textContent = sourceType.status === "enabled" ? "已启用" : "可接入";
  heading.append(mark, title, status);

  const description = document.createElement("p");
  description.textContent = sourceType.description;
  const method = document.createElement("small");
  method.textContent = sourceType.connection_method;
  card.append(heading, description, method);
  return card;
}

function renderDataSources(catalog) {
  const select = document.querySelector("[data-source-select]");
  const sourceContainer = document.querySelector("[data-source-hint]");
  const sourceRows = document.querySelectorAll("[data-source-row]");
  const sources = catalog.sources || [];
  const sourceTypes = catalog.source_types || [];

  select.replaceChildren(...sources.map(createSourceOption));
  select.disabled = sources.length === 0;
  if (catalog.default_source_id) {
    select.value = catalog.default_source_id;
  }
  sourceContainer.textContent = sources.length
    ? "当前数据源以只读方式用于分析，不会写回原始业务系统。"
    : "没有可用数据，请先完成数据接入。";
  setText("[data-source-count]", `${sources.length} 个已连接`);
  setText("[data-connector-count]", `${sourceTypes.length} 种`);

  sourceRows.forEach((row) => row.remove());
  const sourceTable = document.querySelector(".data-source-table");
  sourceTable.append(...sources.map(createSourceRow));
  document
    .querySelector("[data-source-types]")
    .replaceChildren(...sourceTypes.map(createSourceTypeCard));
}

function renderDataSourcesError() {
  const select = document.querySelector("[data-source-select]");
  const option = document.createElement("option");
  option.textContent = "数据源暂不可用";
  select.replaceChildren(option);
  select.disabled = true;
  setText("[data-source-count]", "读取失败");
  setText("[data-connector-count]", "读取失败");
  setText("[data-source-hint]", "无法读取数据源，请检查后台服务。");
  const row = document.querySelector("[data-source-row]");
  if (row) {
    row.textContent = "数据源连接失败，请检查服务状态后刷新页面。";
  }
  const sourceTypes = document.querySelector("[data-source-types]");
  sourceTypes.replaceChildren();
}

function showToast(message) {
  const toast = document.querySelector("[data-toast]");
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => {
    toast.hidden = true;
  }, 2800);
}

function invalidatePreview() {
  if (!currentDraft) {
    return;
  }
  currentDraft = null;
  document.querySelector("[data-empty-preview]").hidden = false;
  document.querySelector("[data-empty-preview] p").textContent =
    "设置已变化，请重新点击“预览任务”核对范围和目标。";
  document.querySelector("[data-task-preview]").hidden = true;
  refreshStartButton();
}

function previewTask(form) {
  const selectedDomains = [...form.querySelectorAll("input[name='domain']:checked")];
  const error = document.querySelector("[data-domain-error]");
  const objective = form.elements.objective.value.trim();

  if (selectedDomains.length === 0) {
    error.textContent = "请至少选择一个业务模块。";
    return;
  }
  error.textContent = "";
  if (!objective) {
    form.elements.objective.focus();
    return;
  }
  if (!form.elements.data_source.value) {
    showToast("请先选择可用数据源。");
    return;
  }

  const domains = selectedDomains.map((input) => input.value);
  const domainText = domains.map((domain) => domainLabels[domain]).join("、");
  const sourceText = form.elements.data_source.selectedOptions[0]?.textContent || "未选择";
  const includeStrategy = form.elements.include_strategy.checked;

  currentDraft = {
    domains,
    domainText,
    sourceId: form.elements.data_source.value,
    sourceText,
    includeStrategy,
    objective,
    idempotencyKey: null,
    submissionAttempted: false,
  };
  setText("[data-preview-domains]", domainText);
  setText("[data-preview-source]", sourceText);
  setText("[data-preview-strategy]", includeStrategy ? "包含" : "不包含");
  setText("[data-preview-objective]", objective);
  document.querySelector("[data-empty-preview]").hidden = true;
  document.querySelector("[data-task-preview]").hidden = false;
  refreshStartButton();
  showToast(runtimeReady ? "任务设置已生成，请确认后开始。" : "任务设置已生成，服务就绪后可开始。");
}

function openConfirmation() {
  if (!currentDraft || !runtimeReady || currentDraft.submissionAttempted) {
    return;
  }
  setText("[data-confirm-domains]", currentDraft.domainText);
  setText("[data-confirm-source]", currentDraft.sourceText);
  setText("[data-confirm-strategy]", currentDraft.includeStrategy ? "包含" : "不包含");
  const feeConfirmation = document.querySelector("[data-fee-confirm]");
  feeConfirmation.checked = false;
  const submitButton = document.querySelector("[data-submit-run]");
  submitButton.disabled = true;
  submitButton.textContent = "确认费用并开始分析";
  setText("[data-submit-error]", "");
  document.querySelector("[data-run-dialog]").showModal();
}

function createIdempotencyKey() {
  const randomPart = globalThis.crypto?.randomUUID
    ? globalThis.crypto.randomUUID().replaceAll("-", "")
    : String(Date.now()) + Math.random().toString(16).slice(2);
  return "native-ui-" + Date.now() + "-" + randomPart;
}

function saveActiveRun() {
  if (!activeRunContext?.workflowRunId && !activeRunContext?.submissionAttempted) {
    return;
  }
  try {
    localStorage.setItem(ACTIVE_RUN_STORAGE_KEY, JSON.stringify(activeRunContext));
  } catch {
    return;
  }
}

function clearSavedRun() {
  try {
    localStorage.removeItem(ACTIVE_RUN_STORAGE_KEY);
  } catch {
    return;
  }
}

function loadSavedRun() {
  try {
    const value = JSON.parse(localStorage.getItem(ACTIVE_RUN_STORAGE_KEY));
    if (value?.workflowRunId || value?.submissionAttempted) {
      activeRunContext = value;
      return true;
    }
  } catch {
    clearSavedRun();
  }
  return false;
}

function runPresentation(run) {
  if (run.terminal_status === "completed") {
    return {
      label: "分析已完成",
      className: "is-completed",
      guidance: "分析结果已生成，可进入任务记录继续查看。",
    };
  }
  if (run.terminal_status === "partial") {
    return {
      label: "分析完成",
      className: "is-partial",
      guidance: "分析结果已生成，结果页会同时说明数据范围和缺失项。",
    };
  }
  if (run.terminal_status === "blocked") {
    return {
      label: "未能完成",
      className: "is-blocked",
      guidance: "任务没有自动重试。请检查运行环境后创建一项新任务。",
    };
  }
  if (run.terminal_status === "uncertain") {
    return {
      label: "状态待确认",
      className: "is-uncertain",
      guidance: "提交结果暂时无法确认，请勿重复提交，并联系管理员核对。",
    };
  }
  return {
    label: phaseLabels[run.phase] || "处理中",
    className: "is-running",
    guidance: "页面会自动刷新任务状态；重新打开页面后也会继续查询。",
  };
}

function renderActiveRun(run) {
  const empty = document.querySelector("[data-activity-empty]");
  const list = document.querySelector("[data-activity-list]");
  const presentation = runPresentation(run);
  const settled = run.phase === "settled";
  const objective = activeRunContext?.objective || "运营分析任务";
  const domains = activeRunContext?.domainText || "已选业务范围";

  empty.hidden = true;
  list.hidden = false;
  list.replaceChildren();

  const item = document.createElement("article");
  item.className = "activity-item";
  const heading = document.createElement("div");
  heading.className = "activity-item__heading";
  const title = document.createElement("strong");
  title.textContent = domains;
  const status = document.createElement("span");
  status.className = "activity-status " + presentation.className;
  status.textContent = presentation.label;
  heading.append(title, status);

  const objectiveText = document.createElement("p");
  objectiveText.className = "activity-item__objective";
  objectiveText.textContent = objective;
  const progress = document.createElement("div");
  progress.className = "activity-progress" + (settled ? " is-settled" : "");
  progress.setAttribute("aria-label", settled ? "任务已结束" : "任务正在运行");
  progress.append(document.createElement("span"));

  const meta = document.createElement("div");
  meta.className = "activity-item__meta";
  const taskId = document.createElement("span");
  taskId.textContent = settled ? "本次分析" : "当前任务";
  const phase = document.createElement("span");
  phase.textContent = phaseLabels[run.phase] || "状态更新中";
  meta.append(taskId, phase);

  const guidance = document.createElement("p");
  guidance.className = "activity-guidance";
  guidance.textContent = presentation.guidance;
  item.append(heading, objectiveText, progress, meta, guidance);
  list.append(item);
}

function renderUncertainSubmission() {
  renderActiveRun({
    workflow_run_id: null,
    phase: "settled",
    terminal_status: "uncertain",
  });
}

function taskPresentation(task) {
  const state = task.view_state || "unavailable";
  return {
    label:
      state === "ready" && task.terminal_status === "partial"
        ? "分析完成 · 含数据提示"
        : resultStateLabels[state] || "状态更新",
    className: "is-" + state,
  };
}

function createTaskHistoryItem(task) {
  const button = document.createElement("button");
  button.className = "task-history-item";
  button.type = "button";
  button.dataset.taskReference = task.task_reference;
  button.setAttribute("aria-label", `查看任务 ${task.task_reference} 的结果`);

  const main = document.createElement("span");
  main.className = "task-history-item__main";
  const eyebrow = document.createElement("span");
  eyebrow.className = "task-history-item__eyebrow";
  eyebrow.textContent = (task.requested_domains || [])
    .map((domain) => domainLabels[domain] || domain)
    .join(" · ");
  const title = document.createElement("strong");
  title.textContent = task.headline;
  const summary = document.createElement("span");
  summary.className = "task-history-item__summary";
  summary.textContent = task.summary;
  main.append(eyebrow, title, summary);

  const aside = document.createElement("span");
  aside.className = "task-history-item__aside";
  const presentation = taskPresentation(task);
  const status = document.createElement("span");
  status.className = "task-history-status " + presentation.className;
  status.textContent = presentation.label;
  const reference = document.createElement("span");
  reference.className = "task-history-reference";
  reference.textContent = task.task_reference;
  const time = document.createElement("span");
  time.className = "task-history-time";
  time.textContent = formatResultTime(task.created_at);
  const action = document.createElement("span");
  action.className = "task-history-action";
  action.textContent = "查看结果 →";
  aside.append(status, reference, time, action);
  button.append(main, aside);
  button.addEventListener("click", () => loadTaskResult(task.task_reference));
  return button;
}

function renderTaskCatalog(catalog) {
  const state = document.querySelector("[data-task-history-state]");
  const list = document.querySelector("[data-task-history-list]");
  const tasks = catalog.tasks || [];
  const countLabel = catalog.has_more
    ? `最近 ${catalog.returned_count} 项`
    : `${catalog.returned_count} 项`;
  setText("[data-task-count]", countLabel);
  list.replaceChildren(...tasks.map(createTaskHistoryItem));
  list.hidden = tasks.length === 0;
  state.hidden = tasks.length > 0;
  state.classList.remove("is-error");
  state.textContent = "还没有任务记录。完成首次分析后，可从这里重新打开结果。";
}

function renderTaskCatalogError() {
  const state = document.querySelector("[data-task-history-state]");
  const list = document.querySelector("[data-task-history-list]");
  setText("[data-task-count]", "读取失败");
  list.hidden = true;
  state.hidden = false;
  state.classList.add("is-error");
  state.textContent = "暂时无法读取任务记录。当前任务不会因此重复提交。";
}

async function loadTaskCatalog() {
  if (taskCatalogLoading) {
    return;
  }
  taskCatalogLoading = true;
  const button = document.querySelector("[data-refresh-tasks]");
  button.disabled = true;
  try {
    renderTaskCatalog(await fetchJson(TASKS_ENDPOINT));
  } catch {
    renderTaskCatalogError();
  } finally {
    taskCatalogLoading = false;
    button.disabled = false;
  }
}

function stopPolling() {
  window.clearTimeout(pollTimer);
  pollTimer = null;
}

function createTextList(items) {
  const list = document.createElement("ul");
  (items || []).forEach((item) => {
    const row = document.createElement("li");
    row.textContent = item;
    list.append(row);
  });
  return list;
}

function createResultDetail(title, items) {
  const detail = document.createElement("div");
  detail.className = "result-detail";
  const heading = document.createElement("strong");
  heading.textContent = title;
  detail.append(heading, createTextList(items));
  return detail;
}

function createFindingCard(finding) {
  const card = document.createElement("article");
  card.className = "finding-card";

  const domain = document.createElement("span");
  domain.className = "finding-domain";
  domain.textContent = domainLabels[finding.domain] || "经营分析";
  const title = document.createElement("h3");
  title.textContent = finding.title;
  const summary = document.createElement("p");
  summary.className = "finding-summary";
  summary.textContent = finding.summary;
  card.append(domain, title, summary);

  if (finding.metrics?.length) {
    const metrics = document.createElement("div");
    metrics.className = "finding-metrics";
    finding.metrics.forEach((metric) => {
      const item = document.createElement("div");
      item.className = "metric-item";
      const value = document.createElement("strong");
      value.textContent = metric.value;
      const label = document.createElement("span");
      label.textContent = metric.label;
      item.append(value, label);
      if (metric.context) {
        const context = document.createElement("small");
        context.textContent = metric.context;
        item.append(context);
      }
      metrics.append(item);
    });
    card.append(metrics);
  }

  if (finding.evidence_basis?.length) {
    card.append(createResultDetail("为什么这么判断", finding.evidence_basis));
  }
  if (finding.limitations?.length) {
    card.append(createResultDetail("使用边界", finding.limitations));
  }
  return card;
}

function createActionCard(action) {
  const card = document.createElement("article");
  card.className = "action-card";

  const main = document.createElement("div");
  const heading = document.createElement("div");
  heading.className = "action-card__heading";
  const title = document.createElement("h3");
  title.textContent = action.title;
  const priority = document.createElement("span");
  priority.className = "priority-badge is-" + action.priority;
  priority.textContent = priorityLabels[action.priority] || "建议";
  heading.append(title, priority);
  const rationale = document.createElement("p");
  rationale.className = "action-rationale";
  rationale.textContent = action.rationale;
  const meta = document.createElement("div");
  meta.className = "action-meta";
  const owner = document.createElement("span");
  owner.textContent = "负责人：" + action.owner;
  const due = document.createElement("span");
  due.textContent = "时限：" + action.due_window;
  meta.append(owner, due);
  main.append(heading, rationale, meta);

  const verification = document.createElement("div");
  verification.className = "action-verification";
  const verificationTitle = document.createElement("strong");
  verificationTitle.textContent = "如何复验";
  const verificationText = document.createElement("p");
  verificationText.textContent = action.verification;
  verification.append(verificationTitle, verificationText);
  if (action.guardrails?.length) {
    const guardrails = createTextList(action.guardrails);
    guardrails.className = "action-guardrails";
    verification.append(guardrails);
  }
  card.append(main, verification);
  return card;
}

function formatResultTime(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "刚刚更新";
  }
  return parsed.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderOperatorResult(result) {
  const panel = document.querySelector("[data-results-panel]");
  const status = document.querySelector("[data-result-status]");
  const findings = result.findings || [];
  const actions = result.actions || [];
  const notices = result.notices || [];

  panel.hidden = false;
  status.className = "result-status is-" + result.view_state;
  status.textContent =
    result.view_state === "ready" && result.terminal_status === "partial"
      ? "分析完成 · 含数据提示"
      : resultStateLabels[result.view_state] || "结果更新";
  setText(
    "[data-result-reference]",
    `任务 ${result.task_reference} · ${formatResultTime(result.updated_at)}`,
  );
  setText("[data-result-headline]", result.headline);
  setText("[data-result-summary]", result.summary);

  const noticesContainer = document.querySelector("[data-result-notices]");
  noticesContainer.hidden = notices.length === 0;
  noticesContainer.replaceChildren(createTextList(notices));

  const findingsSection = document.querySelector("[data-findings-section]");
  findingsSection.hidden = findings.length === 0;
  setText("[data-finding-count]", `${findings.length} 项`);
  document
    .querySelector("[data-result-findings]")
    .replaceChildren(...findings.map(createFindingCard));

  const actionsSection = document.querySelector("[data-actions-section]");
  actionsSection.hidden = actions.length === 0;
  setText("[data-action-count]", `${actions.length} 项`);
  document
    .querySelector("[data-result-actions]")
    .replaceChildren(...actions.map(createActionCard));

  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function hideOperatorResult() {
  document.querySelector("[data-results-panel]").hidden = true;
}

function renderResultReadError(taskReference) {
  renderOperatorResult({
    view_state: "unavailable",
    task_reference: taskReference,
    updated_at: new Date().toISOString(),
    headline: "结果读取失败",
    summary: "任务记录仍然保留，但结果页当前连接失败。请稍后刷新记录再试。",
    findings: [],
    actions: [],
    notices: ["请勿为了读取历史结果而重复创建同一任务。"],
  });
}

async function loadOperatorResult(workflowRunId) {
  try {
    const endpoint =
      RUNS_ENDPOINT + "/" + encodeURIComponent(workflowRunId) + RESULT_ENDPOINT_SUFFIX;
    renderOperatorResult(await fetchJson(endpoint));
  } catch {
    renderResultReadError("当前任务");
  }
}

async function loadTaskResult(taskReference) {
  try {
    const endpoint =
      TASKS_ENDPOINT + "/" + encodeURIComponent(taskReference) + RESULT_ENDPOINT_SUFFIX;
    renderOperatorResult(await fetchJson(endpoint));
  } catch {
    renderResultReadError(taskReference);
  }
}

async function pollRun(workflowRunId) {
  stopPolling();
  try {
    const run = await fetchJson(RUNS_ENDPOINT + "/" + encodeURIComponent(workflowRunId));
    renderActiveRun(run);
    if (run.phase === "settled") {
      await loadOperatorResult(workflowRunId);
      await loadTaskCatalog();
      clearSavedRun();
      return;
    }
  } catch (error) {
    if (error instanceof HttpError && error.status === 404) {
      clearSavedRun();
      showToast("未找到上次任务记录。");
      return;
    }
  }
  pollTimer = window.setTimeout(() => pollRun(workflowRunId), POLL_INTERVAL_MS);
}

async function submitCurrentDraft() {
  if (!currentDraft || currentDraft.submissionAttempted || submissionInFlight) {
    return;
  }
  const feeConfirmation = document.querySelector("[data-fee-confirm]");
  if (!feeConfirmation.checked) {
    setText("[data-submit-error]", "请先确认本次模型调用费用。");
    return;
  }
  if (!runtimeReady) {
    setText("[data-submit-error]", "分析服务当前未就绪，请先检查运行环境。");
    return;
  }

  submissionInFlight = true;
  hideOperatorResult();
  currentDraft.idempotencyKey = currentDraft.idempotencyKey || createIdempotencyKey();
  currentDraft.submissionAttempted = true;
  refreshStartButton();
  const submitButton = document.querySelector("[data-submit-run]");
  submitButton.disabled = true;
  submitButton.textContent = "正在提交…";
  setText("[data-submit-error]", "");

  const payload = {
    idempotency_key: currentDraft.idempotencyKey,
    source_id: currentDraft.sourceId,
    requested_domains: currentDraft.domains,
    objective: currentDraft.objective,
    include_strategy: currentDraft.includeStrategy,
    fee_confirmation: "confirmed",
    authorized_model_execution: true,
  };
  activeRunContext = {
    workflowRunId: null,
    idempotencyKey: currentDraft.idempotencyKey,
    submissionAttempted: true,
    objective: currentDraft.objective,
    domainText: currentDraft.domainText,
    sourceText: currentDraft.sourceText,
  };
  saveActiveRun();

  try {
    const run = await postJsonOnce(RUNS_ENDPOINT, payload);
    activeRunContext.workflowRunId = run.workflow_run_id;
    saveActiveRun();
    renderActiveRun(run);
    loadTaskCatalog();
    document.querySelector("[data-run-dialog]").close();
    showToast("任务已提交，正在读取运行状态。");
    if (run.phase !== "settled") {
      pollTimer = window.setTimeout(
        () => pollRun(run.workflow_run_id),
        POLL_INTERVAL_MS,
      );
    } else {
      await loadOperatorResult(run.workflow_run_id);
      await loadTaskCatalog();
      clearSavedRun();
    }
  } catch (error) {
    if (error instanceof HttpError) {
      clearSavedRun();
      setText("[data-submit-error]", "任务未开始：" + error.message);
      submitButton.textContent = "本次请求未执行";
    } else {
      document.querySelector("[data-run-dialog]").close();
      renderUncertainSubmission();
      showToast("提交状态无法确认，请勿重复提交。");
    }
  } finally {
    submissionInFlight = false;
  }
}

function bindInteractions() {
  const objective = document.querySelector("[data-objective]");
  const form = document.querySelector("[data-analysis-form]");
  const dialog = document.querySelector("[data-run-dialog]");
  const feeConfirmation = document.querySelector("[data-fee-confirm]");

  form.addEventListener("input", () => {
    setText("[data-objective-count]", objective.value.length);
    invalidatePreview();
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    previewTask(form);
  });

  document.querySelector("[data-open-confirm]").addEventListener("click", openConfirmation);
  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => dialog.close());
  });
  feeConfirmation.addEventListener("change", () => {
    document.querySelector("[data-submit-run]").disabled = !feeConfirmation.checked;
    setText("[data-submit-error]", "");
  });
  document.querySelector("[data-submit-run]").addEventListener("click", submitCurrentDraft);
  document.querySelector("[data-refresh-tasks]").addEventListener("click", loadTaskCatalog);

  document.querySelectorAll("[data-create-task]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelector("#new-analysis").scrollIntoView({ behavior: "smooth" });
      window.setTimeout(() => objective.focus(), 350);
    });
  });
}

async function initializeWorkspace() {
  bindInteractions();
  const [runtimeResult, sourceResult, taskResult] = await Promise.allSettled([
    fetchJson(CONFIGURATION_ENDPOINT),
    fetchJson(DATA_SOURCES_ENDPOINT),
    fetchJson(TASKS_ENDPOINT),
  ]);

  if (runtimeResult.status === "fulfilled") {
    renderRuntime(runtimeResult.value);
  } else {
    renderRuntimeError();
  }

  if (sourceResult.status === "fulfilled") {
    renderDataSources(sourceResult.value);
  } else {
    renderDataSourcesError();
  }

  if (taskResult.status === "fulfilled") {
    renderTaskCatalog(taskResult.value);
  } else {
    renderTaskCatalogError();
  }

  if (loadSavedRun()) {
    if (activeRunContext.workflowRunId) {
      renderActiveRun({
        workflow_run_id: activeRunContext.workflowRunId,
        phase: "running",
        terminal_status: null,
      });
      pollRun(activeRunContext.workflowRunId);
    } else {
      renderUncertainSubmission();
    }
  }
}

initializeWorkspace();
