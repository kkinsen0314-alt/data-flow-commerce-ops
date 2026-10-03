import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const appBase = 'http://127.0.0.1:3017';
const executable = process.env.AGENT_BROWSER_EXECUTABLE || path.join(
  process.env.APPDATA, 'npm', 'node_modules', 'agent-browser', 'bin', 'agent-browser-win32-x64.exe',
);
const session = `dataflow-operations-check-${process.pid}`;
const checks = [];

function browser(...args) {
  if (args[0] === 'open') {
    execFileSync(executable, ['--session', session, ...args], {
      cwd: projectRoot, stdio: 'inherit', timeout: 40000,
    });
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

async function fixture(action, method = 'POST') {
  const response = await fetch(`${appBase}/__fixture/${action}`, { method });
  assert.equal(response.ok, true);
  return response.json();
}

function waitText(text) { browser('wait', '--text', text); }
function open(route) { browser('open', `${appBase}${route}`); }
function click(name) { browser('find', 'role', 'button', 'click', '--name', name, '--exact'); }
function label(name, value) { browser('find', 'label', name, 'fill', value); }
function check(name) { browser('find', 'label', name, 'check'); }

async function submit(title, strategy = true) {
  open('/operations/analysis');
  waitText('新建运营分析');
  label('任务名称', title);
  if (!strategy) browser('uncheck', '.df-toggle-row input');
  click('生成分析结果');
  waitText('生成本次运营分析');
  assert.equal(evaluate('document.querySelector(".df-confirm-dialog .df-primary-button").disabled'), true);
  check('我确认调用已配置的模型，并知晓本次分析可能产生费用。');
  click('确认生成');
}

const initial = await fixture('status', 'GET');
assert.equal(initial.fixture, 'project017-operations-browser-only', 'Only run against the isolated test harness.');
assert.equal(initial.simulated_submissions, 0, 'Restart the isolated harness before testing.');

try {
  open('/operations');
  waitText('运营后台登录');
  browser('set', 'viewport', '1440', '960');
  label('用户名', 'qa_operator');
  label('密码', 'browser-check-only');
  click('登录工作台');
  waitText('运营概览');
  browser('wait', '--fn', 'Boolean(document.querySelector(".df-stat-grid"))');
  assert.equal(evaluate('document.querySelectorAll(".df-task-table tbody tr").length'), 0);
  assert.equal(evaluate('document.body.innerText.includes("5 类 · 89 条")'), true);
  checks.push('native_login_cookie_and_empty_server_history');

  open('/operations/data-sources');
  waitText('已接入数据源');
  assert.equal(evaluate('document.querySelectorAll(".df-connector-card").length'), 7);
  assert.deepEqual(evaluate('[...document.querySelectorAll(".df-dataset-grid strong")].map((node) => Number(node.textContent))'), [18, 24, 18, 17, 12]);
  checks.push('backend_source_counts_and_seven_connector_types');

  await submit('真实接口联调任务');
  waitText('分析正在进行');
  const resultUrl = evaluate('location.pathname');
  assert.match(resultUrl, /^\/operations\/tasks\/[A-F0-9]{12}$/);
  assert.equal((await fixture('status', 'GET')).simulated_submissions, 1);
  open(resultUrl);
  waitText('分析正在进行');
  await fixture('complete');
  waitText('内容点击后的承接仍有提升空间');
  assert.equal(evaluate('document.querySelectorAll(".df-finding-card").length'), 1);
  assert.equal(evaluate('document.querySelectorAll(".df-action-card").length'), 1);
  assert.equal(evaluate('document.body.innerText.includes("真实接口联调任务")'), true);
  browser('screenshot', path.join(projectRoot, 'artifacts', 'data-flow-api-result-desktop.png'));
  open(resultUrl);
  waitText('内容点击后的承接仍有提升空间');
  checks.push('fee_gate_submission_processing_polling_result_and_reload');

  await submit('不含策略的接口联调', false);
  waitText('分析正在进行');
  await fixture('complete');
  waitText('内容点击后的承接仍有提升空间');
  assert.equal(evaluate('document.querySelectorAll(".df-action-card").length'), 0);
  checks.push('strategy_selection_preserved_by_server');

  await fixture('lose-response');
  await submit('提交响应中断恢复');
  waitText('查询上次提交');
  assert.equal((await fixture('status', 'GET')).simulated_submissions, 3);
  open('/operations/analysis');
  waitText('查询上次提交');
  click('查询上次提交');
  waitText('分析正在进行');
  assert.equal((await fixture('status', 'GET')).simulated_submissions, 3);
  await fixture('complete');
  waitText('内容点击后的承接仍有提升空间');
  checks.push('lost_confirmation_recovery_after_reload_without_resubmit');

  browser('set', 'viewport', '390', '844');
  open('/operations/data-sources');
  waitText('已接入数据源');
  assert.equal(evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
  browser('screenshot', path.join(projectRoot, 'artifacts', 'data-flow-api-sources-mobile.png'));
  checks.push('mobile_sources_without_horizontal_overflow');

  await fixture('block');
  open('/operations');
  waitText('当前账号没有此运营工作区的访问权限。');
  assert.equal(evaluate('document.querySelectorAll(".df-stat-card").length'), 0);
  await fixture('unblock');
  click('重新加载');
  waitText('运营概览');
  browser('wait', '--fn', 'Boolean(document.querySelector(".df-stat-grid"))');
  checks.push('workspace_denial_and_manual_recovery');

  await fixture('uncertain');
  await submit('模型受理状态待确认');
  waitText('提交状态待确认');
  open('/operations/analysis');
  waitText('查询上次提交');
  click('查询上次提交');
  waitText('提交状态待确认');
  open('/operations/analysis');
  waitText('查询上次提交');
  assert.equal((await fixture('status', 'GET')).simulated_submissions, 4);
  checks.push('uncertain_submission_key_retained_after_response_and_recovery');

  open('/operations/tasks');
  waitText('分析任务');
  await fixture('expire');
  waitText('运营后台登录');
  assert.equal(evaluate('document.querySelectorAll(".df-task-table").length'), 0);
  checks.push('expired_session_clears_authenticated_view');

  const final = await fixture('status', 'GET');
  assert.equal(final.simulated_submissions, 4);
  assert.equal(final.real_model_calls, 0);
  const report = {
    status: 'pass', generated_at: new Date().toISOString(), checks,
    backend: 'real project017 FastAPI operations endpoints and temporary NativeRunStore',
    mocked: ['MiniClaw identity provider', 'model and agent completion responses'],
    real_model_calls: 0, simulated_submissions: final.simulated_submissions,
  };
  await writeFile(path.join(projectRoot, 'artifacts', 'data-flow-api-browser-validation.json'), JSON.stringify(report, null, 2));
  process.stdout.write(JSON.stringify(report, null, 2));
} finally {
  browser('close');
}
