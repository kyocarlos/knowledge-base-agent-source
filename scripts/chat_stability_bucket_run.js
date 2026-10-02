#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const { classifyConsoleEntries } = require('./chat_stability_console_rules');

function parseArgs(argv) {
  const args = {
    outputRoot: '',
    runDir: '',
  };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    const next = argv[i + 1];
    if (token === '--output-root' && next) args.outputRoot = next;
    else if (token === '--run-dir' && next) args.runDir = next;
  }
  return args;
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function listRunDirs(outputRoot) {
  if (!fs.existsSync(outputRoot)) return [];
  return fs.readdirSync(outputRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && /^run_\d{8}_\d{6}$/.test(entry.name))
    .map((entry) => {
      const fullPath = path.join(outputRoot, entry.name);
      const stat = fs.statSync(fullPath);
      return { name: entry.name, path: fullPath, mtimeMs: stat.mtimeMs };
    })
    .sort((a, b) => b.mtimeMs - a.mtimeMs);
}

function classifyRun(result) {
  const questions = Array.isArray(result?.sessions)
    ? result.sessions
    : (Array.isArray(result?.slots)
      ? result.slots.flatMap((slot) => Array.isArray(slot.questions) ? slot.questions : [])
      : []);
  const issues = [];
  if (!questions.length) {
    issues.push('no_questions_found');
  }
  for (const [index, q] of questions.entries()) {
    const qLabel = `${q?.session_label || q?.question_id || `question_${index + 1}`}`;
    const status = String(q?.status || 'missing');
    const reply = String(q?.final_reply || '').trim();
    const consoleErrors = Array.isArray(q?.console_errors) ? q.console_errors : [];
    const networkErrors = Array.isArray(q?.network_errors) ? q.network_errors : [];
    const consoleIssueSummary = q?.console_issue_summary && typeof q.console_issue_summary === 'object'
      ? q.console_issue_summary
      : classifyConsoleEntries(consoleErrors);
    const acceptableWarnings = Array.isArray(consoleIssueSummary.acceptable_warning) ? consoleIssueSummary.acceptable_warning : [];
    const needAttentionWarnings = Array.isArray(consoleIssueSummary.need_attention) ? consoleIssueSummary.need_attention : [];
    const hardFails = Array.isArray(consoleIssueSummary.hard_fail) ? consoleIssueSummary.hard_fail : [];
    if (status !== 'completed') {
      issues.push(`${qLabel}: status=${status}`);
    }
    if (!reply.length) {
      issues.push(`${qLabel}: empty_final_reply`);
    }
    if (hardFails.length > 0) {
      const first = hardFails[0];
      issues.push(`${qLabel}: hard_fail_console=${hardFails.length}${first?.text ? ` first=${first.text}` : ''}`);
    } else if (needAttentionWarnings.length > 0) {
      const first = needAttentionWarnings[0];
      issues.push(`${qLabel}: need_attention_console=${needAttentionWarnings.length}${first?.text ? ` first=${first.text}` : ''}`);
    } else if (acceptableWarnings.length > 0) {
      const first = acceptableWarnings[0];
      issues.push(`${qLabel}: acceptable_warning_console=${acceptableWarnings.length}${first?.text ? ` first=${first.text}` : ''}`);
    }
    if (networkErrors.length > 0) {
      const first = networkErrors[0];
      issues.push(`${qLabel}: network_errors=${networkErrors.length}${first?.errorText ? ` first=${first.errorText}` : ''}`);
    }
  }
  const hardFailCount = issues.filter((issue) => /status=|empty_final_reply|hard_fail_console=|network_errors=/.test(issue)).length;
  const bucket = hardFailCount > 0 ? 'FAIL' : 'PASS';
  return { bucket, issues, questionCount: questions.length };
}

function moveDir(src, dest) {
  if (fs.existsSync(dest)) {
    fs.rmSync(dest, { recursive: true, force: true });
  }
  fs.renameSync(src, dest);
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.outputRoot) {
    throw new Error('Missing --output-root');
  }

  const candidateRunDir = args.runDir
    ? path.resolve(args.runDir)
    : listRunDirs(args.outputRoot)[0]?.path;

  if (!candidateRunDir || !fs.existsSync(candidateRunDir)) {
    throw new Error(`No run directory found under ${args.outputRoot}`);
  }

  const resultPath = path.join(candidateRunDir, 'result.json');
  const result = fs.existsSync(resultPath) ? readJson(resultPath) : null;
  const verdict = classifyRun(result);
  const bucket = verdict.bucket;
  const bucketRoot = path.join(args.outputRoot, bucket);
  ensureDir(bucketRoot);
  const targetDir = path.join(bucketRoot, path.basename(candidateRunDir));

  moveDir(candidateRunDir, targetDir);

  const report = {
    bucket,
    source_run_dir: candidateRunDir,
    final_run_dir: targetDir,
    question_count: verdict.questionCount,
    issues: verdict.issues,
    evaluated_at: new Date().toISOString(),
  };
  fs.writeFileSync(path.join(targetDir, 'bucket_report.json'), JSON.stringify(report, null, 2), 'utf8');

  if (bucket === 'FAIL') {
    console.log('[bucket] decision=FAIL');
  } else if (verdict.issues.length) {
    console.log('[bucket] decision=PASS (warnings only)');
  } else {
    console.log('[bucket] decision=PASS');
  }
  for (const issue of verdict.issues) {
    console.log(`[bucket] note=${issue}`);
  }

  console.log(JSON.stringify(report, null, 2));
}

main();
