// CPE and Smallcell are not zones of their own: their sample material is part of the 4G/5G zone (runs after all three data sets are defined).
(() => {
  const zones = window.KM_ZONES, mobile = zones.mobile;
  ['cpe', 'smallcell'].forEach((id) => {
    const part = zones[id]; if (!part) return;
    const offset = mobile.families.length;  // updates and the answers' {n} / {n:m} source marks point at a document by its position
    mobile.families.push(...part.families);
    part.cats.forEach((cat) => { if (!mobile.cats.some((c) => c[0] === cat[0])) mobile.cats.push(cat); });
    part.topics.forEach(([name, count]) => { const own = mobile.topics.find((t) => t[0] === name); if (own) own[1] += count; else mobile.topics.push([name, count]); });
    mobile.attention.push(...part.attention);
    mobile.updates.push(...part.updates.map(([type, days, index]) => [type, days, index + offset]));
    mobile.qa.push(...part.qa.map((item) => ({ ...item, a: item.a.replace(/\{(\d+)(:\d+)?\}/g, (all, n, chunk) => `{${Number(n) + offset}${chunk || ''}}`) })));
    mobile.digest.sources.push(...part.digest.sources.filter((s) => !mobile.digest.sources.includes(s)));
    mobile.digest.highlights.push(...part.digest.highlights.slice(0, 1));
    mobile.digest.items.push(...part.digest.items);
    delete zones[id];
  });
})();
