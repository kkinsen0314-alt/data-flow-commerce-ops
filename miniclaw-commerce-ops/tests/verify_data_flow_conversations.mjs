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
const session = `dataflow-conversations-check-${process.pid}`;
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
function clickLink(name) { browser('find', 'role', 'link', 'click', '--name', name, '--exact'); }
function label(name, value) { browser('find', 'label', name, 'fill', value); }
function check(name) { browser('find', 'label', name, 'check'); }

async function submitMessage(content) {
  browser('fill', '.df-chat-composer textarea', content);
  click('发送');
  waitText('向 Data Flow 发送这条消息');
  assert.equal(evaluate('document.querySelector(".df-confirm-dialog .df-primary-button").disabled'), true);
  check('我确认调用已配置的模型，并知晓本次回复可能产生费用。');
  click('确认发送');
}

const initial = await fixture('status', 'GET');
assert.equal(initial.fixture, 'project017-operations-browser-only');
assert.equal(initial.simulated_submissions, 0, 'Restart the isolated harness before testing.');

try {
  open('/operations/conversations');
  waitText('运营后台登录');
  browser('set', 'viewport', '1440', '960');
  label('用户名', 'qa_operator');
  label('密码', 'browser-check-only');
  click('登录工作台');
  waitText('运营概览');
  open('/operations/conversations');
  waitText('直接向 Data Flow 提问');
  assert.equal(evaluate('document.querySelectorAll(".df-navigation-business a").length'), 5);
  assert.equal(evaluate('document.querySelector(".df-navigation-create").getAttribute("href")'), '/operations/analysis');
  checks.push('native_login_and_unified_business_navigation');

  click('新建对话');
  waitText('你想先了解什么？');
  waitText('1 个对话');
  assert.match(evaluate('location.pathname'), /^\/operations\/conversations$/);
  assert.equal(evaluate('document.querySelectorAll(".df-conversation-list > button").length'), 1);
  checks.push('persistent_conversation_created_in_native_workspace');

  click('请总结第 13 期最值得优先处理的经营问题。');
  assert.equal(evaluate('document.querySelector(".df-chat-composer textarea").value.length > 0'), true);
  click('发送');
  waitText('向 Data Flow 发送这条消息');
  assert.equal(evaluate('document.querySelector(".df-confirm-dialog .df-primary-button").disabled'), true);
  check('我确认调用已配置的模型，并知晓本次回复可能产生费用。');
  click('确认发送');
  waitText('Data Flow 正在整理回复');
  assert.equal((await fixture('status', 'GET')).simulated_submissions, 1);
  checks.push('per_message_fee_confirmation_and_single_submission');

  await fixture('complete-conversation');
  waitText('第 13 期应优先提升线索承接与支付转化');
  assert.equal(evaluate('document.querySelectorAll(".df-chat-message.is-user").length'), 1);
  assert.equal(evaluate('document.querySelectorAll(".df-chat-message.is-assistant").length'), 1);
  browser('screenshot', path.join(projectRoot, 'artifacts', 'data-flow-conversations-desktop.png'));
  open('/operations/conversations');
  waitText('第 13 期应优先提升线索承接与支付转化');
  checks.push('assistant_reply_polling_and_reload_persistence');

  const seededTask = await fixture('seed-task');
  open(`/operations/tasks/${seededTask.task_reference}`);
  waitText('内容点击后的承接仍有提升空间');
  clickLink('在对话中继续');
  waitText(`任务 #${seededTask.task_reference}`);
  assert.equal(evaluate('document.querySelectorAll(".df-chat-context-pending").length'), 1);
  assert.equal(evaluate('document.body.innerText.includes("wf_native_result_001")'), false);
  checks.push('validated_analysis_result_context_linked_without_internal_ids');

  open('/operations/visualizations');
  waitText('付款金额趋势');
  clickLink('带到运营对话');
  waitText('使用当前筛选范围和经营指标');
  assert.equal(evaluate('document.querySelectorAll(".df-chat-context-pending").length'), 1);
  await fixture('lose-response');
  await submitMessage('继续把问题拆成三项本周行动。');
  waitText('查询原发送');
  assert.equal((await fixture('status', 'GET')).simulated_submissions, 2);
  click('查询原发送');
  waitText('Data Flow 正在整理回复');
  assert.equal((await fixture('status', 'GET')).simulated_submissions, 2);
  await fixture('complete-conversation');
  waitText('第 13 期应优先提升线索承接与支付转化');
  browser('wait', '2500');
  assert.equal(evaluate('document.querySelectorAll(".df-chat-message.is-assistant").length'), 2);
  assert.equal(evaluate('document.querySelectorAll(".df-chat-context-link").length'), 1);
  assert.equal(evaluate('document.body.innerText.includes("Data Flow 已核验关联上下文")'), false);
  checks.push('lost_response_queries_original_submission_without_resend');
  checks.push('validated_dashboard_context_is_linked_without_exposing_transport_prompt');

  await fixture('uncertain');
  await submitMessage('核对这次发送是否被模型受理。');
  waitText('原消息发送状态待确认');
  click('查询原发送');
  waitText('原消息发送状态待确认');
  assert.equal((await fixture('status', 'GET')).simulated_submissions, 3);
  checks.push('uncertain_submission_remains_read_only_and_not_retried');
  await fixture('reset-send');

  browser('set', 'viewport', '390', '844');
  open('/operations/conversations');
  waitText('原消息发送状态待确认');
  assert.equal(evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
  browser('screenshot', path.join(projectRoot, 'artifacts', 'data-flow-conversations-mobile.png'));
  checks.push('mobile_conversation_workspace_without_horizontal_overflow');

  await fixture('expire');
  open('/operations/conversations');
  waitText('运营后台登录');
  checks.push('expired_session_returns_to_native_login');

  const final = await fixture('status', 'GET');
  assert.equal(final.simulated_submissions, 3);
  assert.equal(final.real_model_calls, 0);
  const report = {
    status: 'pass',
    generated_at: new Date().toISOString(),
    checks,
    backend: 'real project017 conversation API with temporary persistent store',
    mocked: ['MiniClaw identity provider', 'MiniClaw session transport', 'model reply completion'],
    real_model_calls: 0,
    simulated_submissions: final.simulated_submissions,
  };
  await writeFile(
    path.join(projectRoot, 'artifacts', 'data-flow-conversations-browser-validation.json'),
    JSON.stringify(report, null, 2),
  );
  process.stdout.write(JSON.stringify(report, null, 2));
} finally {
  browser('close');
}
