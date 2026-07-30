#!/usr/bin/env node
/**
 * Two-session parallel runner for https://127.0.0.1:3030/chat.html
 *
 * Usage:
 *   node scripts/chat_stability_parallel_runner.js --pair-file scripts/chat_stability_parallel_catalog.json
 *
 * Output:
 *   final_runs/chat_stability_parallel/run_YYYYMMDD_HHMMSS/
 *     plan.md
 *     final_script_log.txt
 *     result.json
 *     screenshots/
 */

const fs = require('fs');
const path = require('path');
const { firefox } = require('playwright');
const { classifyConsoleEntries } = require('./chat_stability_console_rules');

const DEFAULT_BASE_URL = 'https://127.0.0.1:3030/chat.html';
const DEFAULT_OUTPUT_ROOT = path.resolve('<project-root>/knowledge-base/final_runs/chat_stability_parallel');
const DEFAULT_PAIR_FILE = path.resolve('<project-root>/knowledge-base/scripts/chat_stability_parallel_catalog.json');

function parseArgs(argv) {
  const args = {
    pairFile: DEFAULT_PAIR_FILE,
    outputRoot: DEFAULT_OUTPUT_ROOT,
    baseUrl: '',
    headless: '',
    timeoutSeconds: '',
    retryCount: '',
    questionDelayMs: '',
  };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    const next = argv[i + 1];
    if (token === '--pair-file' && next) args.pairFile = next;
    else if (token === '--output-root' && next) args.outputRoot = next;
    else if (token === '--base-url' && next) args.baseUrl = next;
    else if (token === '--headless' && next) args.headless = next;
    else if (token === '--timeout-seconds' && next) args.timeoutSeconds = next;
    else if (token === '--retry-count' && next) args.retryCount = next;
    else if (token === '--question-delay-ms' && next) args.questionDelayMs = next;
  }
  return args;
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function nowStamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return [
    d.getFullYear(),
    pad(d.getMonth() + 1),
    pad(d.getDate()),
    '_',
    pad(d.getHours()),
    pad(d.getMinutes()),
    pad(d.getSeconds()),
  ].join('');
}

function safeName(value) {
  return String(value || 'item')
    .trim()
    .replace(/[^\w.-]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 120) || 'item';
}

function createLogger(logPath) {
  const stream = fs.createWriteStream(logPath, { flags: 'a' });
  return {
    line(text) {
      const line = String(text).replace(/\s+$/g, '');
      stream.write(line + '\n');
      console.log(line);
    },
    close() {
      stream.end();
    },
  };
}

function buildPlanMarkdown(pair) {
  return [
    '# Critical Points',
    '',
    `- [ ] Pair ${pair.id}: ${pair.label || 'no label'}`,
    `  - [ ] Session A: ${pair.session_a?.text || ''}`,
    `  - [ ] Session B: ${pair.session_b?.text || ''}`,
    '',
  ].join('\n');
}

async function launchSessionPage(browser, baseUrl, timeoutSeconds) {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1800 },
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();
  page.setDefaultTimeout(timeoutSeconds * 1000);
  page.setDefaultNavigationTimeout(timeoutSeconds * 1000);
  const consoleErrors = [];
  const requestFailures = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' || msg.type() === 'warning') {
      consoleErrors.push({ type: msg.type(), text: msg.text() });
    }
  });
  page.on('pageerror', (error) => {
    consoleErrors.push({
      type: 'pageerror',
      text: error && error.stack ? error.stack : String(error),
    });
  });
  page.on('requestfailed', (request) => {
    requestFailures.push({
      url: request.url(),
      method: request.method(),
      errorText: request.failure() ? request.failure().errorText : 'unknown',
    });
  });
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: timeoutSeconds * 1000 });
  await page.waitForTimeout(2000);
  return { context, page, consoleErrors, requestFailures };
}

async function launchIsolatedSessionPage(userDataDir, baseUrl, timeoutSeconds, headless) {
  ensureDir(userDataDir);
  const context = await firefox.launchPersistentContext(userDataDir, {
    headless,
    viewport: { width: 1280, height: 1800 },
    ignoreHTTPSErrors: true,
  });
  const page = context.pages()[0] || await context.newPage();
  page.setDefaultTimeout(timeoutSeconds * 1000);
  page.setDefaultNavigationTimeout(timeoutSeconds * 1000);
  const consoleErrors = [];
  const requestFailures = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' || msg.type() === 'warning') {
      consoleErrors.push({ type: msg.type(), text: msg.text() });
    }
  });
  page.on('pageerror', (error) => {
    consoleErrors.push({
      type: 'pageerror',
      text: error && error.stack ? error.stack : String(error),
    });
  });
  page.on('requestfailed', (request) => {
    requestFailures.push({
      url: request.url(),
      method: request.method(),
      errorText: request.failure() ? request.failure().errorText : 'unknown',
    });
  });
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: timeoutSeconds * 1000 });
  await page.waitForTimeout(2000);
  return { context, page, consoleErrors, requestFailures };
}

async function openChatWindow(page, timeoutSeconds, logger, sessionLabel) {
  const windowVisible = await page.locator('#chatWindow').isVisible().catch(() => false);
  if (!windowVisible) {
    await page.click('#chatFab');
  }
  await page.waitForFunction(() => {
    const input = document.getElementById('chatInput');
    const status = document.getElementById('chatStatus');
    return Boolean(input) && Boolean(status) && !input.disabled && /連線成功|已連線/.test(status.textContent || '');
  }, null, { timeout: timeoutSeconds * 1000 });
  logger.line(`[${sessionLabel}] chat window ready`);
}

async function prepareSession(browser, pair, sessionLabel, sessionQuestion, runDir, opts, logger) {
  const sessionId = safeName(sessionQuestion.id || sessionQuestion.text || sessionLabel);
  const sessionDir = path.join(runDir, 'screenshots', safeName(pair.id), `session_${sessionLabel}`);
  ensureDir(sessionDir);
  const userDataDir = path.join(runDir, 'profiles', `session_${sessionLabel}`);
  const { context, page, consoleErrors, requestFailures } = await launchIsolatedSessionPage(userDataDir, opts.baseUrl, opts.timeoutSeconds, opts.headless);
  const record = {
    pair_id: pair.id,
    pair_label: pair.label || '',
    session_label: sessionLabel,
    session_id: sessionId,
    question_text: sessionQuestion.text,
    start_at: new Date().toISOString(),
    end_at: '',
    duration_ms: null,
    status: 'failed',
    attempt: 1,
    task_id: '',
    answer_length: 0,
    source_count: 0,
    console_errors: consoleErrors,
    console_issue_summary: { acceptable_warning: [], need_attention: [], hard_fail: [] },
    network_errors: requestFailures,
    screenshot_paths: [],
    final_reply: '',
    note: '',
  };

  try {
    logger.line(`[${sessionLabel}] open chat window`);
    await openChatWindow(page, opts.timeoutSeconds, logger, sessionLabel);
    const openShot = path.join(sessionDir, 'open_chat.png');
    await page.screenshot({ path: openShot });
    record.screenshot_paths.push(openShot);

    logger.line(`[${sessionLabel}] fill question "${sessionQuestion.text}"`);
    await page.locator('#chatInput').fill(sessionQuestion.text);
    const beforeSend = path.join(sessionDir, 'question_before_send.png');
    await page.screenshot({ path: beforeSend });
    record.screenshot_paths.push(beforeSend);
    record.note = 'ready_to_send';
  } catch (error) {
    record.status = 'failed';
    record.note = error && error.stack ? error.stack : String(error);
    logger.line(`[${sessionLabel}] prepare failed - ${record.note.split('\n')[0]}`);
  }

  return { context, page, record, sessionDir };
}

async function sendAndWait(prepared, opts, logger) {
  const { page, record, sessionDir } = prepared;
  if (record.note !== 'ready_to_send') {
    logger.line(`[${record.session_label}] skip send because prepare did not complete`);
    record.end_at = new Date().toISOString();
    return record;
  }

  try {
    const baselineCount = await page.locator('.message.bot .message-bubble:not(.loading)').count();
    record.note = record.note || 'ready_to_send';
    const startedAt = Date.now();
    await page.locator('#chatSendBtn').click();
    await page.waitForFunction((baseline) => {
      const bubbles = Array.from(document.querySelectorAll('.message.bot .message-bubble:not(.loading)'));
      if (bubbles.length <= baseline) return false;
      const last = bubbles[bubbles.length - 1];
      const text = (last && last.textContent ? last.textContent : '').trim();
      return text.length > 0 && !/嗨！我是 CSIT_KM小幫手/.test(text);
    }, baselineCount, { timeout: opts.timeoutSeconds * 1000 });

    await page.waitForTimeout(1200);
    const bubbleTexts = await page.locator('.message.bot .message-bubble:not(.loading)').allInnerTexts();
    const finalReply = bubbleTexts.length ? bubbleTexts[bubbleTexts.length - 1].trim() : '';
    const answerCount = bubbleTexts.length;
    const afterSend = path.join(sessionDir, 'question_after_reply.png');
    await page.screenshot({ path: afterSend });

    const durationMs = Date.now() - startedAt;
    record.duration_ms = durationMs;
    record.status = 'completed';
    record.answer_length = finalReply.length;
    record.final_reply = finalReply;
    record.screenshot_paths.push(afterSend);
    record.note = 'answered';
    logger.line(`[${record.session_label}] reply received in ${durationMs}ms, bot_count=${answerCount}`);
    logger.line(`[${record.session_label}] final reply: ${finalReply.replace(/\n+/g, ' ').slice(0, 500)}`);

    const taskId = await page.evaluate(() => {
      const codeEl = document.querySelector('.task-info code');
      if (codeEl && codeEl.textContent) return codeEl.textContent.trim();
      const taskInfo = Array.from(document.querySelectorAll('.task-info')).find((el) => /任務ID/i.test(el.textContent || ''));
      if (taskInfo) {
        const code = taskInfo.querySelector('code');
        if (code && code.textContent) return code.textContent.trim();
      }
      return '';
    }).catch(() => '');
    record.task_id = taskId || '';
    record.source_count = await page.locator('.source-item').count().catch(() => 0);
    record.console_issue_summary = classifyConsoleEntries(record.console_errors);
    logger.line(`[${record.session_label}] console summary: acceptable=${record.console_issue_summary.acceptable_warning.length} need_attention=${record.console_issue_summary.need_attention.length} hard_fail=${record.console_issue_summary.hard_fail.length}`);
  } catch (error) {
    record.status = 'failed';
    record.note = error && error.stack ? error.stack : String(error);
    logger.line(`[${record.session_label}] failed - ${record.note.split('\n')[0]}`);
    try {
      const failShot = path.join(sessionDir, 'failed.png');
      await page.screenshot({ path: failShot });
      record.screenshot_paths.push(failShot);
    } catch (screenshotError) {
      logger.line(`[${record.session_label}] screenshot failed - ${String(screenshotError).split('\n')[0]}`);
    }
  } finally {
    try {
      await prepared.context.close();
    } catch (_) {}
  }

  record.end_at = new Date().toISOString();
  return record;
}

function summarizeResult(result) {
  const sessions = Array.isArray(result.sessions) ? result.sessions : [];
  const durations = sessions
    .map((s) => Number(s.duration_ms))
    .filter((n) => Number.isFinite(n) && n >= 0)
    .sort((a, b) => a - b);
  const total = sessions.length;
  const completed = sessions.filter((s) => s.status === 'completed').length;
  const failed = total - completed;
  const avg = durations.length ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length) : 0;
  const p50 = durations.length ? durations[Math.floor((durations.length - 1) * 0.5)] : 0;
  const p95 = durations.length ? durations[Math.floor((durations.length - 1) * 0.95)] : 0;
  return {
    total_sessions: total,
    completed_sessions: completed,
    failed_sessions: failed,
    success_rate: total ? Number((completed / total).toFixed(3)) : 0,
    avg_duration_ms: avg,
    p50_duration_ms: p50,
    p95_duration_ms: p95,
    failure_notes: sessions.filter((s) => s.status !== 'completed').map((s) => `${s.session_label}: ${s.note || 'unknown'}`).slice(0, 10),
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const pairFile = readJson(args.pairFile);
  const pairs = Array.isArray(pairFile.pairs) ? pairFile.pairs : [];
  if (!pairs.length) {
    throw new Error(`No pairs found in pair file: ${args.pairFile}`);
  }

  const baseUrl = args.baseUrl || pairFile.base_url || DEFAULT_BASE_URL;
  const headless = args.headless === ''
    ? (pairFile.headless !== undefined ? Boolean(pairFile.headless) : true)
    : args.headless !== 'false';
  const timeoutSeconds = Number(args.timeoutSeconds || pairFile.timeout_seconds || 120);
  const retryCount = Number(args.retryCount || pairFile.retry_count || 1);
  const questionDelayMs = Number(args.questionDelayMs || pairFile.question_delay_ms || 1000);

  const runId = `run_${nowStamp()}`;
  const runDir = path.join(args.outputRoot, runId);
  ensureDir(path.join(runDir, 'screenshots'));

  const logPath = path.join(runDir, 'final_script_log.txt');
  const resultPath = path.join(runDir, 'result.json');
  const planPath = path.join(runDir, 'plan.md');
  const logger = createLogger(logPath);

  const pair = pairs[0];
  fs.writeFileSync(planPath, buildPlanMarkdown(pair), 'utf8');

  const result = {
    run_id: runId,
    base_url: baseUrl,
    pair_file: path.resolve(args.pairFile),
    created_at: new Date().toISOString(),
    timeout_seconds: timeoutSeconds,
    retry_count: retryCount,
    headless,
    pair: {
      id: pair.id,
      label: pair.label || '',
    },
    sessions: [],
  };

  logger.line(`step 0 params: baseUrl=${baseUrl} pair=${pair.id} timeout=${timeoutSeconds}s retry=${retryCount} headless=${headless}`);
  logger.line(`output dir: ${runDir}`);
  logger.line(`pair label: ${pair.label || ''}`);

  try {
    const preparedA = await prepareSession(null, pair, 'A', pair.session_a, runDir, { baseUrl, timeoutSeconds, headless }, logger);
    const preparedB = await prepareSession(null, pair, 'B', pair.session_b, runDir, { baseUrl, timeoutSeconds, headless }, logger);

    logger.line(`[pair ${pair.id}] both sessions ready, sending simultaneously`);
    const [recordA, recordB] = await Promise.all([
      sendAndWait(preparedA, { timeoutSeconds }, logger),
      sendAndWait(preparedB, { timeoutSeconds }, logger),
    ]);

    result.sessions.push(recordA, recordB);
  } catch (error) {
    logger.line(`pair ${pair.id} failed - ${error && error.stack ? error.stack.split('\n')[0] : String(error)}`);
    result.sessions.push(
      {
        pair_id: pair.id,
        pair_label: pair.label || '',
        session_label: 'A',
        session_id: safeName(pair.session_a?.id || 'session_a'),
        question_text: pair.session_a?.text || '',
        start_at: new Date().toISOString(),
        end_at: new Date().toISOString(),
        duration_ms: null,
        status: 'failed',
        attempt: 1,
        task_id: '',
        answer_length: 0,
        source_count: 0,
        console_errors: [],
        console_issue_summary: { acceptable_warning: [], need_attention: [], hard_fail: [] },
        network_errors: [],
        screenshot_paths: [],
        final_reply: '',
        note: error && error.stack ? error.stack : String(error),
      },
      {
        pair_id: pair.id,
        pair_label: pair.label || '',
        session_label: 'B',
        session_id: safeName(pair.session_b?.id || 'session_b'),
        question_text: pair.session_b?.text || '',
        start_at: new Date().toISOString(),
        end_at: new Date().toISOString(),
        duration_ms: null,
        status: 'failed',
        attempt: 1,
        task_id: '',
        answer_length: 0,
        source_count: 0,
        console_errors: [],
        console_issue_summary: { acceptable_warning: [], need_attention: [], hard_fail: [] },
        network_errors: [],
        screenshot_paths: [],
        final_reply: '',
        note: error && error.stack ? error.stack : String(error),
      },
    );
  } finally {
    logger.close();
  }

  result.finished_at = new Date().toISOString();
  result.summary = summarizeResult(result);
  fs.writeFileSync(resultPath, JSON.stringify(result, null, 2), 'utf8');

  console.log(JSON.stringify({
    run_id: result.run_id,
    summary: result.summary,
    result_path: resultPath,
    log_path: logPath,
    plan_path: planPath,
  }, null, 2));

  const failedCount = result.sessions.filter((s) => s.status !== 'completed').length;
  process.exitCode = failedCount > 0 ? 1 : 0;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
