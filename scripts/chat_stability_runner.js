#!/usr/bin/env node
/**
 * Chat stability runner for https://127.0.0.1:3030/chat.html
 *
 * Usage:
 *   node scripts/chat_stability_runner.js --schedule-file scripts/chat_stability_schedule.example.json
 *   node scripts/chat_stability_runner.js --schedule-file ... --slot s1_morning
 *
 * Output:
 *   final_runs/chat_stability/run_YYYYMMDD_HHMMSS/
 *     plan.md
 *     final_script_log.txt
 *     result.json
 *     screenshots/
 */

const fs = require('fs');
const path = require('path');
const { firefox } = require('playwright');

const DEFAULT_BASE_URL = 'https://127.0.0.1:3030/chat.html';
const DEFAULT_OUTPUT_ROOT = path.resolve('<project-root>/knowledge-base/final_runs/chat_stability');
const DEFAULT_SCHEDULE_FILE = path.resolve('<project-root>/knowledge-base/scripts/chat_stability_schedule.example.json');

function parseArgs(argv) {
  const args = {
    scheduleFile: DEFAULT_SCHEDULE_FILE,
    slot: '',
    all: false,
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
    if (token === '--schedule-file' && next) args.scheduleFile = next;
    else if (token === '--slot' && next) args.slot = next;
    else if (token === '--all') args.all = true;
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
  const raw = fs.readFileSync(filePath, 'utf8');
  return JSON.parse(raw);
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

function buildPlanMarkdown(runPlan) {
  const lines = ['# Critical Points', ''];
  for (const slot of runPlan.slots) {
    lines.push(`- [ ] Slot ${slot.id}: ${slot.label || slot.cron || 'no label'}`);
    for (const question of slot.questions) {
      lines.push(`  - [ ] ${question.id}: ${question.text}`);
    }
  }
  lines.push('');
  return lines.join('\n');
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

function selectSlots(schedule, args) {
  const slots = Array.isArray(schedule.slots) ? schedule.slots : [];
  if (args.all || !args.slot) return slots;
  const wanted = new Set(String(args.slot).split(',').map((s) => s.trim()).filter(Boolean));
  const picked = slots.filter((slot) => wanted.has(slot.id));
  return picked;
}

async function launchQuestionPage(browser, baseUrl, timeoutSeconds) {
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
      consoleErrors.push({
        type: msg.type(),
        text: msg.text(),
      });
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

async function openChatWindow(page, timeoutSeconds) {
  const windowVisible = await page.locator('#chatWindow').isVisible().catch(() => false);
  if (!windowVisible) {
    await page.click('#chatFab');
  }
  await page.waitForFunction(() => {
    const input = document.getElementById('chatInput');
    const status = document.getElementById('chatStatus');
    return Boolean(input) && Boolean(status) && !input.disabled && /連線成功|已連線/.test(status.textContent || '');
  }, null, { timeout: timeoutSeconds * 1000 });
}

async function askQuestion(page, questionText, screenshotPrefix, timeoutSeconds, logger) {
  const input = page.locator('#chatInput');
  const sendBtn = page.locator('#chatSendBtn');

  const baselineCount = await page.locator('.message.bot .message-bubble:not(.loading)').count();
  await input.fill(questionText);
  await page.screenshot({ path: `${screenshotPrefix}_before_send.png` });

  const startedAt = Date.now();
  await sendBtn.click();

  await page.waitForFunction((baseline) => {
    const bubbles = Array.from(document.querySelectorAll('.message.bot .message-bubble:not(.loading)'));
    if (bubbles.length <= baseline) return false;
    const last = bubbles[bubbles.length - 1];
    const text = (last && last.textContent ? last.textContent : '').trim();
    return text.length > 0 && !/嗨！我是 CSIT_KM小幫手/.test(text);
  }, baselineCount, { timeout: timeoutSeconds * 1000 });

  await page.waitForTimeout(1200);
  const bubbleTexts = await page.locator('.message.bot .message-bubble:not(.loading)').allInnerTexts();
  const finalReply = bubbleTexts.length ? bubbleTexts[bubbleTexts.length - 1].trim() : '';
  const answerCount = bubbleTexts.length;
  await page.screenshot({ path: `${screenshotPrefix}_after_reply.png` });

  const durationMs = Date.now() - startedAt;
  logger.line(`  reply received in ${durationMs}ms, bot_count=${answerCount}`);
  logger.line(`  final reply: ${finalReply.replace(/\n+/g, ' ').slice(0, 500)}`);

  return {
    durationMs,
    answerCount,
    finalReply,
    baselineCount,
  };
}

async function runQuestion(browser, runDir, slot, question, opts, logger) {
  const questionId = safeName(question.id || question.text);
  const questionDir = path.join(runDir, 'screenshots', safeName(slot.id), questionId);
  ensureDir(questionDir);
  const { context, page, consoleErrors, requestFailures } = await launchQuestionPage(browser, opts.baseUrl, opts.timeoutSeconds);
  const record = {
    slot_id: slot.id,
    slot_label: slot.label || '',
    question_id: questionId,
    question_text: question.text,
    start_at: new Date().toISOString(),
    duration_ms: null,
    status: 'failed',
    attempt: 1,
    task_id: '',
    answer_length: 0,
    source_count: 0,
    console_errors: consoleErrors,
    network_errors: requestFailures,
    screenshot_paths: [],
    final_reply: '',
    note: '',
  };

  try {
    logger.line(`question ${questionId}: open chat window`);
    await openChatWindow(page, opts.timeoutSeconds);
    await page.screenshot({ path: `${questionDir}/open_chat.png` });
    record.screenshot_paths.push(`${questionDir}/open_chat.png`);

    logger.line(`question ${questionId}: send "${question.text}"`);
    const result = await askQuestion(
      page,
      question.text,
      `${questionDir}/question`,
      opts.timeoutSeconds,
      logger,
    );
    record.duration_ms = result.durationMs;
    record.status = 'completed';
    record.answer_length = result.finalReply.length;
    record.final_reply = result.finalReply;
    record.note = 'answered';
    record.screenshot_paths.push(
      `${questionDir}/question_before_send.png`,
      `${questionDir}/question_after_reply.png`,
    );

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

    const sourceCount = await page.locator('.source-item').count().catch(() => 0);
    record.source_count = sourceCount;

    logger.line(`question ${questionId}: status=completed source_count=${sourceCount}`);
  } catch (error) {
    record.duration_ms = record.duration_ms || null;
    record.status = 'failed';
    record.note = error && error.stack ? error.stack : String(error);
    logger.line(`question ${questionId}: failed - ${record.note.split('\n')[0]}`);
    try {
      const failShot = `${questionDir}/failed.png`;
      await page.screenshot({ path: failShot });
      record.screenshot_paths.push(failShot);
    } catch (screenshotError) {
      logger.line(`question ${questionId}: screenshot failed - ${String(screenshotError).split('\n')[0]}`);
    }
  } finally {
    try {
      await context.close();
    } catch (_) {}
  }

  record.end_at = new Date().toISOString();
  return record;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const schedule = readJson(args.scheduleFile);
  const selectedSlots = selectSlots(schedule, args);
  if (!selectedSlots.length) {
    console.error(`No slots selected. Check --slot or schedule file: ${args.scheduleFile}`);
    process.exit(1);
  }

  const baseUrl = args.baseUrl || schedule.base_url || DEFAULT_BASE_URL;
  const headless = args.headless === ''
    ? (schedule.headless !== undefined ? Boolean(schedule.headless) : true)
    : args.headless !== 'false';
  const timeoutSeconds = Number(args.timeoutSeconds || schedule.timeout_seconds || 120);
  const retryCount = Number(args.retryCount || schedule.retry_count || 2);
  const questionDelayMs = Number(args.questionDelayMs || schedule.question_delay_ms || 1000);

  const runId = `run_${nowStamp()}`;
  const runDir = path.join(args.outputRoot, runId);
  const screenshotsDir = path.join(runDir, 'screenshots');
  ensureDir(screenshotsDir);

  const logPath = path.join(runDir, 'final_script_log.txt');
  const resultPath = path.join(runDir, 'result.json');
  const planPath = path.join(runDir, 'plan.md');
  const logger = createLogger(logPath);
  fs.writeFileSync(planPath, buildPlanMarkdown({ slots: selectedSlots }), 'utf8');

  const result = {
    run_id: runId,
    base_url: baseUrl,
    schedule_file: path.resolve(args.scheduleFile),
    created_at: new Date().toISOString(),
    timeout_seconds: timeoutSeconds,
    retry_count: retryCount,
    headless,
    slots: [],
  };

  logger.line(`step 0 params: baseUrl=${baseUrl} slots=${selectedSlots.map((s) => s.id).join(',')} timeout=${timeoutSeconds}s retry=${retryCount} headless=${headless}`);
  logger.line(`output dir: ${runDir}`);

  const browser = await firefox.launch({ headless });
  try {
    for (const slot of selectedSlots) {
      const slotResult = {
        slot_id: slot.id,
        slot_label: slot.label || '',
        cron: slot.cron || '',
        questions: [],
        started_at: new Date().toISOString(),
        finished_at: '',
      };

      logger.line(`slot ${slot.id}: start (${slot.label || slot.cron || 'no label'})`);
      for (const question of slot.questions || []) {
        let attempt = 0;
        let record = null;
        let lastError = null;
        while (attempt <= retryCount) {
          attempt += 1;
          logger.line(`step ${attempt}: question ${question.id || question.text} attempt ${attempt}`);
          try {
            record = await runQuestion(browser, runDir, slot, question, { baseUrl, timeoutSeconds }, logger);
            record.attempt = attempt;
            if (record.status === 'completed') break;
          } catch (error) {
            lastError = error;
            logger.line(`  attempt ${attempt} failed: ${error && error.stack ? error.stack.split('\n')[0] : String(error)}`);
          }
          if (attempt <= retryCount) {
            await new Promise((resolve) => setTimeout(resolve, 1500));
          }
        }

        if (!record) {
          record = {
            slot_id: slot.id,
            slot_label: slot.label || '',
            question_id: safeName(question.id || question.text),
            question_text: question.text,
            start_at: new Date().toISOString(),
            end_at: new Date().toISOString(),
            duration_ms: null,
            status: 'failed',
            attempt,
            task_id: '',
            answer_length: 0,
            source_count: 0,
            console_errors: [],
            network_errors: [],
            screenshot_paths: [],
            final_reply: '',
            note: lastError ? (lastError.stack || String(lastError)) : 'unknown error',
          };
        }

        slotResult.questions.push(record);
        await new Promise((resolve) => setTimeout(resolve, questionDelayMs));
      }
      slotResult.finished_at = new Date().toISOString();
      result.slots.push(slotResult);
      logger.line(`slot ${slot.id}: finished`);
    }
  } finally {
    await browser.close();
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

  const failedCount = result.slots
    .flatMap((slot) => slot.questions)
    .filter((q) => q.status !== 'completed').length;
  process.exitCode = failedCount > 0 ? 1 : 0;
}

function summarizeResult(result) {
  const allQuestions = result.slots.flatMap((slot) => slot.questions);
  const total = allQuestions.length;
  const completed = allQuestions.filter((q) => q.status === 'completed').length;
  const failed = total - completed;
  const durations = allQuestions
    .map((q) => Number(q.duration_ms))
    .filter((n) => Number.isFinite(n) && n >= 0)
    .sort((a, b) => a - b);
  const avg = durations.length ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length) : 0;
  const p50 = durations.length ? durations[Math.floor((durations.length - 1) * 0.5)] : 0;
  const p95 = durations.length ? durations[Math.floor((durations.length - 1) * 0.95)] : 0;
  const errors = [];
  for (const q of allQuestions) {
    if (q.status !== 'completed') errors.push(q.note || 'unknown');
  }
  return {
    total_questions: total,
    completed_questions: completed,
    failed_questions: failed,
    success_rate: total ? Number((completed / total).toFixed(3)) : 0,
    avg_duration_ms: avg,
    p50_duration_ms: p50,
    p95_duration_ms: p95,
    failure_notes: errors.slice(0, 10),
  };
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
