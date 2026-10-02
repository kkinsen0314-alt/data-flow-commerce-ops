import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const appBase = 'http://127.0.0.1:3017';
const executable = process.env.AGENT_BROWSER_EXECUTABLE || path.join(
  process.env.APPDATA, 'npm', 'node_modules', 'agent-browser', 'bin', 'agent-browser-win32-x64.exe',
);
const session = `dataflow-design-${process.pid}`;
const artifactRoot = path.join(projectRoot, 'artifacts', 'design-system');
const checks = [];

function browser(...args) {
  if (args[0] === 'open') {
    execFileSync(executable, ['--session', session, ...args], { cwd: projectRoot, stdio: 'inherit', timeout: 40000 });
    return {};
  }
  const output = execFileSync(executable, ['--session', session, '--json', ...args], {
    cwd: projectRoot, encoding: 'utf8', timeout: 40000,
  });
  const result = JSON.parse(output);
  assert.equal(result.success, true, JSON.stringify(result.error));
  return result.data;
}

function evaluate(code) {
  return browser('eval', '-b', Buffer.from(code).toString('base64')).result;
}
function open(route) { browser('open', `${appBase}${route}`); }
function waitText(text) { browser('wait', '--text', text); }
function click(name) { browser('find', 'role', 'button', 'click', '--name', name, '--exact'); }
function viewport(width, height = 960) { browser('set', 'viewport', String(width), String(height)); }
function screenshot(name) { browser('screenshot', path.join(artifactRoot, `${name}.png`)); }
function noOverflow() { assert.equal(evaluate('document.documentElement.scrollWidth <= innerWidth'), true); }
function closeDialog() {
  browser('press', 'Escape');
  browser('wait', '--fn', 'document.querySelectorAll("[role=dialog]").length === 0');
}

async function fixture(action, method = 'POST') {
  const response = await fetch(`${appBase}/__fixture/${action}`, { method });
  assert.equal(response.ok, true);
  return response.json();
}

const initial = await fixture('status', 'GET');
assert.equal(initial.fixture, 'project017-operations-browser-only');
await mkdir(artifactRoot, { recursive: true });

try {
  open('/operations');
  waitText('运营后台登录');
  viewport(1440);
  screenshot('login-1440');
  browser('find', 'label', '用户名', 'fill', 'qa_operator');
  browser('find', 'label', '密码', 'fill', 'browser-check-only');
  click('登录工作台');
  browser('wait', '--fn', 'Boolean(document.querySelector(".df-stat-grid"))');
  assert.equal(evaluate(`document.querySelectorAll('nav[aria-label="主导航"]').length`), 1);
  waitText('运营概览');
  assert.deepEqual(evaluate('[...document.querySelectorAll(".df-navigation-business a")].map(node => node.textContent.trim())'),
    ['运营概览', '数据看板', '运营对话', '分析任务', '数据源']);
  assert.equal(evaluate('document.querySelectorAll(".df-flow-rail").length'), 0);
  assert.equal(evaluate('document.querySelectorAll(".df-navigation a[aria-current=page]").length'), 1);
  noOverflow();
  screenshot('overview-1440');
  checks.push('one_business_navigation_without_numbered_rail');

  const seeded = await fixture('seed-task');
  open(`/operations/tasks/${seeded.task_reference}`);
  waitText('内容点击后的承接仍有提升空间');
  assert.deepEqual(evaluate('[...document.querySelectorAll(".df-navigation a[aria-current=page]")].map(node => node.getAttribute("href"))'), ['/operations/tasks']);
  screenshot('result-1440');
  checks.push('nested_result_highlights_tasks_only');

  for (const [route, heading, name] of [
    ['/operations/analysis', '新建运营分析', 'analysis'],
    ['/operations/tasks', '分析任务', 'tasks'],
    ['/operations/visualizations', '经营核心指标', 'dashboard'],
    ['/operations/data-sources', '已接入数据源', 'sources'],
  ]) {
    open(route); waitText(heading === '经营核心指标' ? '当前范围：' : heading);
    noOverflow(); screenshot(`${name}-1440`);
  }
  assert.equal(evaluate('document.querySelectorAll(".df-connector-card").length'), 7);
  browser('find', 'first', '.df-connector-card button', 'click');
  waitText('接入要求');
  closeDialog();
  assert.equal(evaluate('document.querySelectorAll("[role=dialog]").length'), 0);
  checks.push('existing_routes_and_connector_guide_keyboard_close');

  viewport(1280, 800);
  open('/operations/conversations'); waitText('运营对话');
  click('新建对话'); waitText('你想先了解什么？');
  noOverflow(); screenshot('conversation-1280');
  browser('fill', '.df-chat-composer textarea', '界面测试：不发送模型请求');
  click('发送'); waitText('向 Data Flow 发送这条消息');
  assert.equal(evaluate('document.querySelector(".df-confirm-dialog .df-primary-button").disabled'), true);
  closeDialog();
  assert.equal(evaluate('document.querySelectorAll("[role=dialog]").length'), 0);
  assert.equal(evaluate('document.querySelector(".df-chat-composer textarea").value'), '界面测试：不发送模型请求');
  checks.push('conversation_fee_gate_and_escape_preserve_draft');

  open('/settings?tab=preferences'); waitText('界面外观');
  browser('find', 'text', '深色', 'click', '--exact');
  open('/operations/visualizations'); waitText('当前范围：');
  assert.equal(evaluate('document.documentElement.classList.contains("dark")'), true);
  assert.notEqual(evaluate('getComputedStyle(document.querySelector(".df-viz-card")).backgroundColor'), 'rgb(255, 255, 255)');
  assert.equal(evaluate('getComputedStyle(document.querySelector(".df-viz-card")).backgroundColor'), evaluate('getComputedStyle(document.querySelector(".df-navigation")).backgroundColor'));
  screenshot('dashboard-dark-1280');
  open('/settings?tab=preferences'); waitText('界面外观');
  browser('find', 'text', '浅色', 'click', '--exact');
  checks.push('native_settings_theme_shared_by_business_pages');

  for (const width of [768, 390]) {
    viewport(width, 844);
    open('/operations'); waitText('运营概览');
    assert.equal(evaluate(`document.querySelectorAll('nav[aria-label="主导航"]').length`), 0);
    assert.equal(evaluate('document.querySelectorAll(".df-mobile-header").length'), 1);
    click('打开导航'); waitText('自动化任务');
    assert.equal(evaluate(`document.querySelectorAll('[role=dialog] a[href="/operations/data-sources"]').length`), 1);
    browser('wait', '--fn', '(() => { const rect = document.querySelector(".df-mobile-navigation").getBoundingClientRect(); return rect.top === 0 && rect.right <= innerWidth; })()');
    const menu = evaluate('document.querySelector(".df-mobile-navigation").getBoundingClientRect().toJSON()');
    assert.ok(menu.left >= 0 && menu.right <= width && menu.bottom <= 844);
    screenshot(`navigation-${width}`);
    closeDialog();
    assert.equal(evaluate('document.querySelectorAll("[role=dialog]").length'), 0);
    assert.equal(evaluate('document.activeElement?.getAttribute("aria-label")'), '打开导航');
    click('打开导航');
    browser('find', 'role', 'link', 'click', '--name', '数据源', '--exact');
    waitText('已接入数据源');
    browser('wait', '--fn', 'document.querySelectorAll("[role=dialog]").length === 0');
    assert.equal(evaluate('document.querySelectorAll("[role=dialog]").length'), 0);
    noOverflow(); screenshot(`sources-${width}`);
    open('/operations/visualizations'); waitText('当前范围：');
    noOverflow(); screenshot(`dashboard-${width}`);
    open('/operations/conversations'); waitText('你想先了解什么？');
    noOverflow(); screenshot(`conversation-${width}`);
    assert.equal(evaluate('document.querySelector(".df-chat-composer").getBoundingClientRect().bottom <= innerHeight'), true);
  }
  checks.push('tablet_and_phone_single_navigation_focus_and_visible_composer');

  for (const height of [400, 320]) {
    viewport(390, height);
    open('/operations/conversations?context=visualization');
    waitText('使用当前筛选范围和经营指标');
    const composer = evaluate('document.querySelector(".df-chat-composer").getBoundingClientRect().toJSON()');
    assert.ok(composer.top >= 0 && composer.bottom <= height);
    const panel = evaluate('document.querySelector(".df-chat-panel").getBoundingClientRect().toJSON()');
    assert.ok(composer.bottom <= panel.bottom);
    browser('fill', '.df-chat-composer textarea', '短视口草稿，不发送');
    screenshot(`conversation-short-${height}`);
  }
  checks.push('short_viewport_with_context_keeps_composer_visible');

  const final = await fixture('status', 'GET');
  assert.equal(final.simulated_submissions, initial.simulated_submissions);
  assert.equal(final.real_model_calls, 0);
  await writeFile(path.join(artifactRoot, 'verification.json'), `${JSON.stringify({ passed: true, checks, real_model_calls: 0 }, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify({ passed: true, checks, real_model_calls: 0 }, null, 2)}\n`);
} finally {
  browser('close');
}
