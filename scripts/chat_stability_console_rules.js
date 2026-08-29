const ACCEPTABLE_WARNING_PATTERNS = [
  /\[Chat\] 忽略其他 session 的 chat event:/i,
  /\[Heatmap\]/i,
];

const NEED_ATTENTION_WARNING_PATTERNS = [
  /timeout/i,
  /slow/i,
  /retry/i,
];

const HARD_FAIL_ERROR_PATTERNS = [
  /uncaught/i,
  /referenceerror/i,
  /typeerror/i,
  /syntaxerror/i,
  /networkerror/i,
  /failed request/i,
  /pageerror/i,
];

function classifyConsoleEntry(entry) {
  const type = String(entry?.type || '').toLowerCase();
  const text = String(entry?.text || entry?.errorText || '').trim();
  if (!text) {
    return { level: 'need_attention', text: 'empty console entry' };
  }
  const normalized = `${type} ${text}`.toLowerCase();
  if (type === 'error' || HARD_FAIL_ERROR_PATTERNS.some((pattern) => pattern.test(normalized))) {
    return { level: 'hard_fail', text };
  }
  if (type === 'warning') {
    if (ACCEPTABLE_WARNING_PATTERNS.some((pattern) => pattern.test(text))) {
      return { level: 'acceptable_warning', text };
    }
    if (NEED_ATTENTION_WARNING_PATTERNS.some((pattern) => pattern.test(text))) {
      return { level: 'need_attention', text };
    }
    return { level: 'need_attention', text };
  }
  return { level: 'need_attention', text };
}

function classifyConsoleEntries(entries) {
  const buckets = {
    acceptable_warning: [],
    need_attention: [],
    hard_fail: [],
  };
  for (const entry of Array.isArray(entries) ? entries : []) {
    const classified = classifyConsoleEntry(entry);
    buckets[classified.level].push({
      text: classified.text,
      raw_type: entry?.type || '',
    });
  }
  return buckets;
}

module.exports = {
  ACCEPTABLE_WARNING_PATTERNS,
  NEED_ATTENTION_WARNING_PATTERNS,
  HARD_FAIL_ERROR_PATTERNS,
  classifyConsoleEntry,
  classifyConsoleEntries,
};
