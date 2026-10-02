import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const debugBase = process.env.DATA_FLOW_CDP_URL || "http://127.0.0.1:9333";
const appBase = process.env.DATA_FLOW_APP_URL || "http://127.0.0.1:3017";
const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const artifactsRoot = path.join(projectRoot, "artifacts");

const sleep = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

async function waitForValue(readValue, timeoutMilliseconds = 12000) {
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    const value = await readValue();
    if (value) return value;
    await sleep(100);
  }
  throw new Error("Timed out while waiting for the Data Flow native page.");
}

const target = await fetch(
  `${debugBase}/json/new?${encodeURIComponent(`${appBase}/operations`)}`,
  { method: "PUT" },
).then((response) => response.json());
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

let commandId = 0;
let mockAuthenticated = false;
const mockRequests = [];
const pending = new Map();
const mockUser = {
  id: "data-flow-browser-check",
  username: "qa_operator",
  display_name: "验收运营员",
  role: "admin",
  status: "active",
  permissions: [
    "manage_system_config",
    "manage_group_env",
    "manage_users",
    "manage_invites",
    "view_audit_log",
    "manage_billing",
  ],
  must_change_password: false,
  disable_reason: null,
  notes: null,
  created_at: "2026-09-13T00:00:00.000Z",
  last_login_at: "2026-09-13T00:00:00.000Z",
  last_active_at: "2026-09-13T00:00:00.000Z",
  deleted_at: null,
  avatar_emoji: null,
  avatar_color: null,
  avatar_url: null,
  ai_name: null,
  ai_avatar_emoji: null,
  ai_avatar_color: null,
  ai_avatar_url: null,
  default_require_mention: false,
};
const setupStatus = {
  needsSetup: false,
  claudeConfigured: true,
  feishuConfigured: false,
  providerSetupSkipped: true,
};
const appearance = {
  appName: "Data Flow",
  aiName: "Data Flow",
  aiAvatarEmoji: "📊",
  aiAvatarColor: "#0f766e",
  aiAvatarUrl: null,
  aiAvatarMode: "brand",
};

function send(method, params = {}) {
  commandId += 1;
  const id = commandId;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
  });
}

function jsonResponse(requestId, statusCode, payload) {
  return send("Fetch.fulfillRequest", {
    requestId,
    responseCode: statusCode,
    responseHeaders: [
      { name: "content-type", value: "application/json; charset=utf-8" },
      { name: "cache-control", value: "no-store" },
    ],
    body: Buffer.from(JSON.stringify(payload)).toString("base64"),
  });
}

async function handlePausedRequest(params) {
  const url = new URL(params.request.url);
  if (!url.pathname.startsWith("/api/")) {
    await send("Fetch.continueRequest", { requestId: params.requestId });
    return;
  }

  mockRequests.push(`${params.request.method} ${url.pathname}`);

  if (url.pathname === "/api/auth/login") {
    mockAuthenticated = true;
    await jsonResponse(params.requestId, 200, {
      success: true,
      user: mockUser,
      setupStatus,
      appearance,
    });
    return;
  }
  if (url.pathname === "/api/auth/me") {
    await jsonResponse(
      params.requestId,
      mockAuthenticated ? 200 : 401,
      mockAuthenticated
        ? { user: mockUser, setupStatus, appearance }
        : { error: "Unauthorized" },
    );
    return;
  }
  if (url.pathname === "/api/auth/status") {
    await jsonResponse(params.requestId, 200, { initialized: true });
    return;
  }
  if (url.pathname === "/api/billing/status") {
    await jsonResponse(params.requestId, 200, { enabled: false });
    return;
  }
  await jsonResponse(params.requestId, 200, {});
}

socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result);
    return;
  }
  if (message.method === "Fetch.requestPaused") {
    void handlePausedRequest(message.params).catch((error) => {
      process.stderr.write(`${error.stack || error}\n`);
    });
  }
});

async function evaluate(expression) {
  const result = await send("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || "Browser evaluation failed.");
  }
  return result.result.value;
}

async function capture(fileName) {
  const result = await send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
  });
  const outputPath = path.join(artifactsRoot, fileName);
  await writeFile(outputPath, Buffer.from(result.data, "base64"));
  return outputPath;
}

try {
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Fetch.disable").catch(() => undefined);
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 960,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Page.navigate", { url: `${appBase}/operations` });
  await waitForValue(() =>
    evaluate(`Boolean(location.pathname === "/login" &&
      document.title === "登录 · Data Flow" &&
      document.querySelector("#data-flow-username") &&
      document.querySelector("#data-flow-password"))`),
  );

  const loginState = await evaluate(`(() => ({
    pathname: location.pathname,
    title: document.title,
    heading: document.querySelector("#df-login-title")?.innerText,
    brand: document.querySelector(".df-brand strong")?.textContent,
    environment: document.querySelector(".df-environment-badge")?.textContent,
    submit: document.querySelector(".df-login-submit span")?.textContent,
    registerLinks: [...document.querySelectorAll("a")].filter((link) =>
      link.textContent?.includes("注册") || link.getAttribute("href") === "/register"
    ).length,
    forbiddenCopy: ["未完成", "待开发", "占位", "演示版", "Demo"].filter((word) =>
      document.body.innerText.includes(word)
    ),
    innerWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
  }))()`);

  assert.equal(loginState.pathname, "/login");
  assert.equal(loginState.title, "登录 · Data Flow");
  assert.equal(loginState.brand, "Data Flow");
  assert.equal(loginState.environment, "测试环境");
  assert.equal(loginState.submit, "登录工作台");
  assert.equal(loginState.registerLinks, 0);
  assert.deepEqual(loginState.forbiddenCopy, []);
  assert.equal(loginState.innerWidth, 1440);
  assert.equal(loginState.documentWidth, 1440);
  const desktopLoginScreenshot = await capture("data-flow-native-login-desktop.png");

  await send("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await send("Page.navigate", { url: `${appBase}/login` });
  await waitForValue(() => evaluate(`Boolean(document.querySelector("#data-flow-username"))`));
  await evaluate(`(() => {
    for (const element of document.querySelectorAll("#data-flow-username, #data-flow-password")) {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      ).set;
      setter.call(element, "");
      element.dispatchEvent(new Event("input", { bubbles: true }));
    }
  })()`);
  const mobileState = await evaluate(`(() => ({
    innerWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.scrollWidth,
  }))()`);
  assert.equal(mobileState.innerWidth, 390);
  assert.equal(mobileState.documentWidth, 390);
  assert.equal(mobileState.bodyWidth, 390);
  const mobileLoginScreenshot = await capture("data-flow-native-login-mobile.png");

  await send("Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 960,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Fetch.enable", {
    patterns: [{ urlPattern: "*://127.0.0.1:3017/api/*", requestStage: "Request" }],
  });
  await evaluate(`(() => {
    const username = document.querySelector("#data-flow-username");
    const password = document.querySelector("#data-flow-password");
    const setValue = (element, value) => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      ).set;
      setter.call(element, value);
      element.dispatchEvent(new Event("input", { bubbles: true }));
    };
    setValue(username, "qa_operator");
    setValue(password, "browser-check-only");
  })()`);
  await sleep(150);
  await evaluate(`document.querySelector(".df-login-submit").click()`);
  try {
    await waitForValue(() =>
      mockRequests.includes("GET /api/auth/me") && evaluate(`Boolean(
        location.pathname === "/operations" &&
        document.querySelector(".df-workspace-header h1")?.textContent === "运营工作台"
      )`),
    );
  } catch (error) {
    const debugState = await evaluate(`(() => ({
      pathname: location.pathname,
      title: document.title,
      body: document.body.innerText.slice(0, 1200),
      alert: document.querySelector('[role="alert"]')?.textContent,
    }))()`);
    throw new Error(`${error.message}\n${JSON.stringify({ debugState, mockRequests }, null, 2)}`);
  }

  const operationsState = await evaluate(`(() => ({
    pathname: location.pathname,
    heading: document.querySelector(".df-workspace-header h1")?.textContent,
    flowLinks: document.querySelectorAll(".df-flow-rail a").length,
    statCards: document.querySelectorAll(".df-stat-card").length,
    recentTasks: document.querySelectorAll(".df-task-table tbody tr").length,
    hasDataSummary: document.body.innerText.includes("5 类 · 89 条"),
    forbiddenCopy: ["未完成", "待开发", "占位", "演示版", "Demo"].filter((word) =>
      document.body.innerText.includes(word)
    ),
    innerWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
  }))()`);

  assert.equal(operationsState.pathname, "/operations");
  assert.equal(operationsState.heading, "运营工作台");
  assert.equal(operationsState.flowLinks, 4);
  assert.equal(operationsState.statCards, 4);
  assert.equal(operationsState.recentTasks, 3);
  assert.equal(operationsState.hasDataSummary, true);
  assert.deepEqual(operationsState.forbiddenCopy, []);
  assert.equal(operationsState.documentWidth, operationsState.innerWidth);
  await sleep(750);
  await waitForValue(() =>
    evaluate(`Boolean(location.pathname === "/operations" &&
      document.querySelector(".df-operations-page"))`),
  );
  await evaluate(`new Promise((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(resolve)))`);
  const paintedState = await evaluate(`(() => ({
    operationsPages: document.querySelectorAll(".df-operations-page").length,
    loadingObjects: [...document.querySelectorAll("object")].map((element) => ({
      data: element.getAttribute("data"),
      width: element.getBoundingClientRect().width,
      height: element.getBoundingClientRect().height,
    })),
    loadingImages: [...document.querySelectorAll('img[src*="data-flow-mark"]')].map((element) => ({
      width: element.getBoundingClientRect().width,
      height: element.getBoundingClientRect().height,
      parentClass: element.parentElement?.className,
    })),
  }))()`);
  assert.equal(paintedState.operationsPages, 1);
  assert.deepEqual(paintedState.loadingObjects, []);
  assert.equal(paintedState.loadingImages.length, 1);
  assert.equal(paintedState.loadingImages[0].width, 44);
  assert.equal(paintedState.loadingImages[0].height, 44);
  const operationsScreenshot = await capture("data-flow-native-operations.png");

  await evaluate(`document.querySelector('.df-flow-rail a[href="/operations/analysis"]').click()`);
  await waitForValue(() => evaluate(`Boolean(
    location.pathname === "/operations/analysis" &&
    document.querySelector(".df-analysis-layout") &&
    document.querySelectorAll(".df-domain-select-grid button").length === 3
  )`));
  const analysisState = await evaluate(`(() => ({
    source: document.querySelector(".df-source-inline strong")?.textContent,
    testNote: document.querySelector(".df-test-note")?.textContent,
    selectedDomains: document.querySelectorAll(".df-domain-select-grid button.is-selected").length,
    documentWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }))()`);
  assert.equal(analysisState.source, "5 类 · 89 条记录");
  assert.match(analysisState.testNote, /不调用外部模型或第三方服务/);
  assert.equal(analysisState.selectedDomains, 3);
  assert.equal(analysisState.documentWidth, analysisState.innerWidth);
  await evaluate(`document.querySelector(".df-analysis-layout").requestSubmit()`);
  await waitForValue(() => evaluate(`Boolean(document.querySelector(".df-confirm-dialog"))`));
  await evaluate(`document.querySelector(".df-confirm-dialog .df-primary-button").click()`);
  await waitForValue(() => evaluate(`Boolean(
    /^\\/operations\\/tasks\\/[A-F0-9]{12}$/.test(location.pathname) &&
    document.querySelector(".df-result-hero") &&
    document.body.innerText.includes("分析完成")
  )`));
  const resultState = await evaluate(`(() => ({
    pathname: location.pathname,
    findings: document.querySelectorAll(".df-finding-card").length,
    actions: document.querySelectorAll(".df-action-card").length,
    metrics: document.querySelectorAll(".df-metric-grid > div").length,
    hasUnavailable: document.body.innerText.includes("暂不可用"),
    hasReview: document.body.innerText.includes("需要复核"),
    documentWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }))()`);
  assert.match(resultState.pathname, /^\/operations\/tasks\/[A-F0-9]{12}$/);
  assert.equal(resultState.findings, 3);
  assert.equal(resultState.actions, 3);
  assert.ok(resultState.metrics >= 7);
  assert.equal(resultState.hasUnavailable, false);
  assert.equal(resultState.hasReview, false);
  assert.equal(resultState.documentWidth, resultState.innerWidth);
  const resultScreenshot = await capture("data-flow-native-result.png");

  await evaluate(`document.querySelector('.df-flow-rail a[href="/operations/data-sources"]').click()`);
  await waitForValue(() => evaluate(`Boolean(
    location.pathname === "/operations/data-sources" &&
    document.querySelectorAll(".df-dataset-grid > div").length === 5 &&
    document.querySelectorAll(".df-connector-card").length === 7
  )`));
  const sourcesState = await evaluate(`(() => ({
    datasets: [...document.querySelectorAll(".df-dataset-grid > div")].map((item) => item.innerText),
    connectorNames: [...document.querySelectorAll(".df-connector-card h3")].map((item) => item.textContent),
    hasSyntheticLabel: document.body.innerText.includes("合成测试数据"),
    hasVisionCopy: document.body.innerText.includes("视力"),
    documentWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }))()`);
  assert.deepEqual(sourcesState.datasets, ["短视频内容\n18条", "直播场次\n24条", "渠道线索\n18条", "销售跟进\n17条", "订单\n12条"]);
  assert.deepEqual(sourcesState.connectorNames, ["CSV / Excel", "MySQL", "PostgreSQL", "飞书多维表格", "飞书电子表格", "HTTP API", "MCP 数据服务"]);
  assert.equal(sourcesState.hasSyntheticLabel, true);
  assert.equal(sourcesState.hasVisionCopy, false);
  assert.equal(sourcesState.documentWidth, sourcesState.innerWidth);
  await evaluate(`(() => {
    const card = [...document.querySelectorAll(".df-connector-card")].find((item) => item.querySelector("h3")?.textContent === "MySQL");
    card.querySelector("button").click();
  })()`);
  await waitForValue(() => evaluate(`Boolean(document.querySelector(".df-connector-dialog")?.innerText.includes("数据库只读账号"))`));
  const connectorState = await evaluate(`(() => ({
    title: document.querySelector("#connector-title")?.textContent,
    requirements: document.querySelectorAll(".df-requirement-grid li").length,
    readonly: document.querySelector(".df-dialog-footer")?.textContent,
  }))()`);
  assert.equal(connectorState.title, "MySQL 接入要求");
  assert.equal(connectorState.requirements, 9);
  assert.match(connectorState.readonly, /只读权限/);
  await evaluate(`document.querySelector(".df-connector-dialog .df-dialog-close").click()`);
  const sourcesScreenshot = await capture("data-flow-native-data-sources.png");

  await send("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await send("Page.navigate", { url: `${appBase}/operations` });
  await waitForValue(() => evaluate(`Boolean(document.querySelector(".df-stat-grid"))`));
  const mobileOperationsState = await evaluate(`(() => ({
    innerWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.scrollWidth,
    flowLinks: document.querySelectorAll(".df-flow-rail a").length,
  }))()`);
  assert.equal(mobileOperationsState.innerWidth, 390);
  assert.equal(mobileOperationsState.documentWidth, 390);
  assert.equal(mobileOperationsState.bodyWidth, 390);
  assert.equal(mobileOperationsState.flowLinks, 4);
  const mobileOperationsScreenshot = await capture("data-flow-native-operations-mobile.png");

  process.stdout.write(JSON.stringify({
    loginState,
    mobileState,
    operationsState,
    analysisState,
    resultState,
    sourcesState,
    connectorState,
    mobileOperationsState,
    paintedState,
    screenshots: {
      desktopLoginScreenshot,
      mobileLoginScreenshot,
      operationsScreenshot,
      resultScreenshot,
      sourcesScreenshot,
      mobileOperationsScreenshot,
    },
  }, null, 2));
} finally {
  socket.close();
  await fetch(`${debugBase}/json/close/${target.id}`).catch(() => undefined);
}
