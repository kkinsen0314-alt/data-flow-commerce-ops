const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const baseUrl = process.env.MINICLAW_WEB_TEST_BASE_URL || "http://127.0.0.1:3023";
const taskReference = "A1B2C3D4E5F6";

const responses = {
  "/v1/native/configuration": {
    mode: "miniclaw_native",
    base_url: "http://127.0.0.1:3017",
    workspace_configured: true,
    credentials_configured: true,
    ready: true,
    agent_profile_name: "电商运营多 Agent 工作流总控",
    project_root: "project017",
    model_submission_requires_explicit_authorization: true,
    automatic_model_retry: false,
  },
  "/v1/native/data-sources": {
    default_source_id: "sample-commerce-data",
    sources: [
      {
        source_id: "sample-commerce-data",
        display_name: "电商运营测试数据",
        description: "短视频、直播场次、渠道线索、销售跟进和订单数据。",
        source_type: "local_file",
        source_type_label: "本地文件（CSV）",
        status: "ready",
        synthetic: true,
        access_mode: "read_only",
        dataset_count: 5,
        record_count: 89,
        available_domains: [
          "content_growth",
          "live_conversion",
          "attribution_leads",
        ],
        dataset_types: [
          "short_video",
          "live_session",
          "channel_lead",
          "sales_followup",
          "order",
        ],
        dataset_labels: ["短视频", "直播场次", "渠道线索", "销售跟进", "订单"],
        data_period: "2026-08-31 09:00:00 至 2026-09-06 22:30:00",
      },
    ],
    source_types: [
      {
        type_id: "local_file",
        display_name: "CSV / Excel",
        category: "file",
        status: "enabled",
        description: "上传或读取受控目录中的表格文件。",
        connection_method: "本地只读文件",
        requires_authorization: false,
        read_only_supported: true,
      },
      {
        type_id: "mysql",
        display_name: "MySQL",
        category: "database",
        status: "configurable",
        description: "使用只读账号连接指定数据库、表或视图。",
        connection_method: "数据库只读连接器",
        requires_authorization: true,
        read_only_supported: true,
      },
      {
        type_id: "feishu_bitable",
        display_name: "飞书多维表格",
        category: "application",
        status: "configurable",
        description: "通过飞书开放平台读取已授权的数据表记录。",
        connection_method: "MiniClaw MCP / 飞书 OpenAPI",
        requires_authorization: true,
        read_only_supported: true,
      },
    ],
  },
  "/v1/native/tasks": {
    schema_version: "1.0",
    result_type: "miniclaw_operator_task_catalog",
    returned_count: 1,
    has_more: false,
    tasks: [
      {
        schema_version: "1.0",
        result_type: "miniclaw_operator_task",
        task_reference: taskReference,
        view_state: "ready",
        terminal_status: "completed",
        requested_domains: ["content_growth", "live_conversion"],
        include_strategy: true,
        created_at: "2026-09-09T08:00:00Z",
        updated_at: "2026-09-09T08:06:00Z",
        headline: "优先修复内容到直播的承接断点",
        summary: "高互动内容已经带来点击，应优先优化直播间商品访问路径。",
      },
    ],
  },
  [`/v1/native/tasks/${taskReference}/result`]: {
    schema_version: "1.0",
    result_type: "miniclaw_operator_result",
    task_reference: taskReference,
    view_state: "ready",
    terminal_status: "completed",
    requested_domains: ["content_growth", "live_conversion"],
    synthetic: true,
    updated_at: "2026-09-09T08:06:00Z",
    headline: "优先修复内容到直播的承接断点",
    summary: "高互动内容已经带来点击，应优先优化直播间商品访问路径。",
    findings: [],
    actions: [],
    notices: ["结果来自电商运营测试数据。"],
  },
};

async function run() {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const browserErrors = [];
    let postCount = 0;
    let taskListReads = 0;
    let resultReads = 0;

    page.on("console", (message) => {
      if (message.type() === "error") browserErrors.push(message.text());
    });
    page.on("pageerror", (error) => browserErrors.push(error.message));
    page.on("request", (request) => {
      if (request.method() === "POST") postCount += 1;
    });
    await page.route("**/v1/native/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/v1/native/tasks") taskListReads += 1;
      if (path.endsWith(`/tasks/${taskReference}/result`)) resultReads += 1;
      const body = responses[path];
      if (!body) {
        await route.fulfill({ status: 404, json: { detail: "not found" } });
        return;
      }
      await route.fulfill({ status: 200, json: body });
    });

    await page.goto(`${baseUrl}/native`, { waitUntil: "networkidle" });
    const item = page.locator(`[data-task-reference="${taskReference}"]`);
    await item.waitFor();
    await assert.doesNotReject(() => item.click());
    await page.locator("[data-results-panel]:not([hidden])").waitFor();

    assert.equal(await page.locator("[data-task-count]").textContent(), "1 项");
    assert.equal(await page.locator("[data-source-count]").textContent(), "1 个已连接");
    assert.equal(await page.locator("[data-source-type=\"mysql\"] strong").textContent(), "MySQL");
    assert.equal(await page.locator("[data-source-type=\"feishu_bitable\"] strong").textContent(), "飞书多维表格");
    assert.equal(await page.locator("[data-result-headline]").textContent(), responses[`/v1/native/tasks/${taskReference}/result`].headline);
    assert.equal(taskListReads, 1);
    assert.equal(resultReads, 1);
    assert.equal(postCount, 0);
    assert.deepEqual(browserErrors, []);

    const desktopOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    assert.equal(desktopOverflow, false);
    await page.setViewportSize({ width: 390, height: 844 });
    const mobileOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    assert.equal(mobileOverflow, false);

    const bodyText = await page.locator("body").innerText();
    for (const forbidden of [
      "wf_native_",
      "service_run_id",
      "commerce_ops_supervisor",
      "第 13 期数据底座",
    ]) {
      assert.equal(bodyText.includes(forbidden), false);
    }

    process.stdout.write(
      JSON.stringify({
        status: "pass",
        task_list_reads: taskListReads,
        result_reads: resultReads,
        post_count: postCount,
        browser_errors: browserErrors.length,
        desktop_overflow: desktopOverflow,
        mobile_overflow: mobileOverflow,
      }),
    );
  } finally {
    await browser.close();
  }
}

run().catch((error) => {
  process.stderr.write(error.stack || String(error));
  process.exitCode = 1;
});
