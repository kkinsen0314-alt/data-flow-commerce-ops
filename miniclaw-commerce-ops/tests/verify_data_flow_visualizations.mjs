import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const appBase = 'http://127.0.0.1:3017';
const executable = process.env.AGENT_BROWSER_EXECUTABLE || path.join(process.env.APPDATA, 'npm', 'node_modules', 'agent-browser', 'bin', 'agent-browser-win32-x64.exe');
const session = `dataflow-visualizations-${process.pid}`;
const checks = [];
const artifact = (name) => path.join(projectRoot, 'artifacts', name);
const downloadDirectory = await mkdtemp(path.join(projectRoot, 'runtime', 'tmp', 'visualization-downloads-'));
const browserEnvironment = { ...process.env, AGENT_BROWSER_DOWNLOAD_PATH: downloadDirectory };

function browser(...args) {
  if (args[0] === 'open') {
    execFileSync(executable, ['--session', session, ...args], { cwd: projectRoot, stdio: 'inherit', timeout: 40000, env: browserEnvironment });
    return {};
  }
  let output;
  try {
    output = execFileSync(executable, ['--session', session, '--json', ...args], { cwd: projectRoot, encoding: 'utf8', timeout: 40000, env: browserEnvironment });
  } catch (error) {
    if (args[0] === 'download') process.stderr.write(JSON.stringify(browser('get', 'text', '.df-visualizations')) + '\n');
    if (args[0] === 'wait') process.stderr.write(JSON.stringify(evaluate('({inputs:[...document.querySelectorAll(".df-viz-filter-fields input")].map(x=>x.value), error:document.querySelector("[role=alert]")?.textContent, cohort:document.querySelector(".df-viz-cohort")?.textContent, path:location.pathname})')) + '\n');
    throw error;
  }
  const result = JSON.parse(output);
  assert.equal(result.success, true, JSON.stringify(result.error));
  return result.data;
}
function evaluate(code) { return browser('eval', '-b', Buffer.from(code).toString('base64')).result; }
function click(name) { browser('find', 'role', 'button', 'click', '--name', name, '--exact'); }
function waitText(text) { browser('wait', '--text', text); }
function label(name, value) { browser('find', 'label', name, 'fill', value); }
function dateFilter(index, value) {
  const selector = `.df-viz-filter-fields > label:nth-child(${index}) input[type="date"]`;
  const updated = evaluate(`(() => {
    const input = document.querySelector(${JSON.stringify(selector)});
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    if (!(input instanceof HTMLInputElement) || !setter) return null;
    setter.call(input, ${JSON.stringify(value)});
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    return input.value;
  })()`);
  assert.equal(updated, value);
  assert.equal(browser('get', 'value', selector).value, value);
}
function select(name, value) { browser('select', `.df-viz-filter-fields > label:nth-child(${({ 渠道: 3, 内容: 4, 直播场次: 5 })[name]}) select`, value); }
function metric(key) { return evaluate(`document.querySelector('[data-metric="${key}"] strong')?.textContent`); }
function noOverflow() { assert.equal(evaluate('document.documentElement.scrollWidth <= innerWidth && document.body.scrollWidth <= innerWidth'), true); }
async function download(selector, filename) {
  const socket = new WebSocket(browser('get', 'cdp-url').cdpUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let sequence = 0;
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => reject(new Error(`CDP timeout: ${method}`)), 10000);
    const listener = (event) => {
      const result = JSON.parse(event.data);
      if (result.id !== id) return;
      socket.removeEventListener('message', listener); clearTimeout(timer);
      if (result.error) reject(new Error(JSON.stringify(result.error))); else resolve(result.result);
    };
    socket.addEventListener('message', listener); socket.send(JSON.stringify({ id, method, params }));
  });
  try {
    const { browserContextIds } = await call('Target.getBrowserContexts');
    await call('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: downloadDirectory, eventsEnabled: true, ...(browserContextIds[0] ? { browserContextId: browserContextIds[0] } : {}) });
    const completed = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Download completion timed out')), 15000);
      socket.addEventListener('message', (event) => {
        const result = JSON.parse(event.data);
        if (result.method !== 'Browser.downloadProgress') return;
        if (result.params.state === 'completed') { clearTimeout(timer); resolve(); }
        if (result.params.state === 'canceled') { clearTimeout(timer); reject(new Error('Browser canceled download')); }
      });
    });
    browser('click', selector); await completed;
    const content = await readFile(path.join(downloadDirectory, filename));
    await writeFile(artifact(filename), content);
    return content;
  } finally { socket.close(); }
}
async function fixture(action, method = 'POST') {
  const response = await fetch(`${appBase}/__fixture/${action}`, { method });
  assert.equal(response.ok, true); return response.json();
}

assert.equal((await fixture('status', 'GET')).fixture, 'project017-operations-browser-only');
try {
  browser('open', `${appBase}/operations/visualizations`);
  waitText('运营后台登录');
  browser('set', 'viewport', '1440', '1080');
  label('用户名', 'qa_operator'); label('密码', 'browser-check-only'); click('登录工作台');
  waitText('运营概览');
  browser('click', 'a[href="/operations/visualizations"]');
  waitText('当前范围：18 条线索');
  assert.equal(metric('gmv'), '¥10,591'); assert.equal(metric('paid_conversion'), '50%'); assert.equal(metric('followup_24h'), '72.22%');
  assert.equal(evaluate('document.querySelectorAll("[data-chart]").length'), 6);
  assert.equal(evaluate('document.querySelectorAll(".df-viz-plot svg").length'), 6);
  noOverflow();
  browser('screenshot', artifact('data-flow-visualizations-desktop.png'), '--full');
  checks.push('authenticated_navigation_six_charts_and_five_verified_kpis');

  const png = await download('[aria-label="导出付款金额趋势图片"]', 'data-flow-sales.png');
  assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  assert.ok(png.length > 5000); assert.ok(png.readUInt32BE(16) >= 1240);
  checks.push('real_png_download_with_source_and_scope');

  select('渠道', '直播承接'); click('应用筛选'); waitText('当前范围：6 条线索');
  assert.equal(metric('gmv'), '¥5,795');
  browser('click', '[data-chart="orders"] footer > button');
  waitText('共 6 条');
  const csv = (await download('.df-viz-details > header .df-secondary-button', 'data-flow-orders.csv')).toString('utf8');
  assert.equal(csv.replace(/^\uFEFF/, '').trim().split(/\r?\n/).length, 7);
  assert.equal(csv.includes('短视频自然流量'), false);
  assert.ok(csv.includes('直播承接'));
  checks.push('channel_filter_drilldown_and_filtered_csv_download');
  click('关闭明细');

  click('重置'); waitText('当前范围：18 条线索');
  dateFilter(1, '2026-08-31'); dateFilter(2, '2026-08-31'); click('应用筛选');
  waitText('当前范围：3 条线索'); assert.equal(metric('gmv'), '¥899');
  checks.push('inclusive_cohort_dates_preserve_later_payments');
  click('重置'); waitText('当前范围：18 条线索');
  select('内容', 'p13_cnt_008'); select('直播场次', '1302'); click('应用筛选');
  waitText('当前范围：1 条线索'); assert.equal(metric('gmv'), '¥999');
  select('内容', 'p13_cnt_001'); click('应用筛选'); waitText('当前筛选范围没有线索');
  assert.equal(metric('paid_conversion'), '—');
  checks.push('content_session_intersection_and_zero_denominator');

  click('重置'); waitText('当前范围：18 条线索');
  browser('click', '[data-chart="live"] footer > button'); waitText('共 24 条');
  assert.equal(evaluate('document.querySelectorAll(".df-viz-details tbody tr").length'), 20);
  click('下一页'); waitText('第 2 页');
  assert.equal(evaluate('document.querySelectorAll(".df-viz-details tbody tr").length'), 4);
  click('关闭明细'); checks.push('live_detail_pagination_20_plus_4');

  browser('set', 'viewport', '390', '844');
  browser('scrollintoview', '.df-viz-filters');
  noOverflow(); browser('screenshot', artifact('data-flow-visualizations-mobile.png'), '--full');
  checks.push('390px_mobile_layout_without_horizontal_overflow');

  await fixture('block'); click('刷新数据'); waitText('看板读取失败');
  assert.equal(evaluate('document.querySelectorAll("[data-chart]").length'), 0);
  await fixture('unblock'); click('重新读取'); waitText('当前范围：18 条线索');
  await fixture('expire'); click('刷新数据'); waitText('运营后台登录');
  checks.push('permission_failure_hides_data_recovery_and_session_expiration');
  const status = await fixture('status', 'GET');
  assert.equal(status.simulated_submissions, 0); assert.equal(status.real_model_calls, 0);
  await writeFile(artifact('data-flow-visualizations-browser-validation.json'), JSON.stringify({ status: 'pass', checked_at: new Date().toISOString(), checks, real_model_calls: 0, simulated_submissions: 0, authentication: 'isolated MiniClaw identity fixture', data: 'project017 period-13 synthetic CSV', api: 'production visualization endpoints' }, null, 2) + '\n');
  process.stdout.write(JSON.stringify({ status: 'pass', checks: checks.length, real_model_calls: 0 }) + '\n');
} finally {
  browser('close');
  const relative = path.relative(path.join(projectRoot, 'runtime', 'tmp'), downloadDirectory);
  assert.match(relative, /^visualization-downloads-[A-Za-z0-9]+$/);
  await rm(downloadDirectory, { recursive: true, force: true });
}
