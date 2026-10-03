import assert from "node:assert/strict";

const debugBase = process.env.DATA_FLOW_CDP_URL || "http://127.0.0.1:9333";
const appUrl = process.env.DATA_FLOW_WEB_URL || "http://127.0.0.1:3023/native";

const sleep = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

async function waitForValue(readValue, timeoutMilliseconds = 8000) {
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    const value = await readValue();
    if (value) return value;
    await sleep(100);
  }
  throw new Error("Timed out while waiting for the Data Flow page.");
}

const target = await fetch(
  `${debugBase}/json/new?${encodeURIComponent(appUrl)}`,
  { method: "PUT" },
).then((response) => response.json());
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

let requestId = 0;
const pending = new Map();
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (!message.id || !pending.has(message.id)) return;
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(message.error.message));
  else resolve(message.result);
});

function send(method, params = {}) {
  requestId += 1;
  const id = requestId;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
  });
}

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

try {
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await send("Page.navigate", { url: appUrl });
  await waitForValue(() =>
    evaluate(`document.readyState === "complete" &&
      document.querySelectorAll(".connector-card:not(.connector-card--loading)").length > 0 &&
      document.querySelectorAll(".task-history-item").length > 0`),
  );

  const pageState = await evaluate(`(() => ({
    innerWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.scrollWidth,
    brand: document.querySelector(".brand strong")?.textContent,
    source: document.querySelector(".source-name strong")?.textContent,
    sourceType: document.querySelector(".source-type")?.textContent,
    sourceAmount: document.querySelector(".data-row:not(.data-row--header) .data-detail:nth-of-type(3)")?.textContent,
    connectorCount: document.querySelectorAll(".connector-card").length,
    connectors: [...document.querySelectorAll(".connector-card strong")].map((item) => item.textContent),
  }))()`);

  assert.equal(pageState.innerWidth, 390);
  assert.equal(pageState.documentWidth, 390);
  assert.equal(pageState.bodyWidth, 390);
  assert.equal(pageState.brand, "Data Flow");
  assert.equal(pageState.source, "电商运营测试数据");
  assert.equal(pageState.sourceType, "本地文件（CSV）");
  assert.equal(pageState.connectorCount, 7);
  assert.ok(pageState.connectors.includes("MySQL"));
  assert.ok(pageState.connectors.includes("飞书多维表格"));

  await evaluate(`document.querySelector(".task-history-item").click()`);
  await waitForValue(() =>
    evaluate(`!document.querySelector("[data-results-panel]").hidden &&
      document.querySelectorAll(".finding-card").length === 3 &&
      document.querySelectorAll(".action-card").length === 3`),
  );
  const resultState = await evaluate(`(() => ({
    status: document.querySelector("[data-result-status]")?.textContent,
    headline: document.querySelector("[data-result-headline]")?.textContent,
    findings: document.querySelectorAll(".finding-card").length,
    actions: document.querySelectorAll(".action-card").length,
    documentWidth: document.documentElement.scrollWidth,
  }))()`);

  assert.equal(resultState.status, "分析完成 · 含数据提示");
  assert.ok(resultState.headline.length > 0);
  assert.equal(resultState.findings, 3);
  assert.equal(resultState.actions, 3);
  assert.equal(resultState.documentWidth, 390);
  process.stdout.write(JSON.stringify({ pageState, resultState }, null, 2));
} finally {
  socket.close();
  await fetch(`${debugBase}/json/close/${target.id}`).catch(() => undefined);
}
