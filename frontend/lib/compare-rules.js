const COMPARE_QUERY_RE = /(比較|差異|不同|對比|比對|\bvs\b|\bversus\b)/i

export function normalizeText(value) {
  return String(value || '').trim()
}

export function isCompareLikeQuery(text) {
  const normalized = normalizeText(text)
  if (!normalized) return false
  return COMPARE_QUERY_RE.test(normalized)
}

export function shouldPreferWifiCompare(text, isWifiSpecificQuery) {
  if (typeof isWifiSpecificQuery !== 'function') return false
  return isCompareLikeQuery(text) && isWifiSpecificQuery(text)
}

const compareRules = {
  normalizeText,
  isCompareLikeQuery,
  shouldPreferWifiCompare,
}

if (typeof window !== 'undefined') {
  window.KBCompareRules = compareRules
}

export default compareRules
