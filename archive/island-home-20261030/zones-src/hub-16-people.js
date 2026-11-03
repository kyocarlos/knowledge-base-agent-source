// Home page of the knowledge zones (part 1.6 of 3): visitors, zone badges and animals on the islands.
// DEMO DATA: the people walking on the islands and every score are simulated in the browser (the "me" scores are kept in localStorage); there is no server
// behind it yet. The page says so ("示範資料"), and the real source of the numbers will be the per-account question log of each zone.
// Each zone has one badge with 8 levels (a colour each); the level rises with points from on-topic questions in that zone. Every badge level counts 1
// towards a "badge level total", which unlocks more animals to choose from.
const People = (() => {
  const H = Islands.helpers, NS = 'http://www.w3.org/2000/svg', esc = H.esc, shade = H.shade, ACC = 'var(--green)';
  const TIERS = [
    { n: '灰', c: '#9aa5a8', at: 5 }, { n: '綠', c: '#4cc27a', at: 15 }, { n: '藍', c: '#4aa8ff', at: 35 }, { n: '紫', c: '#a07cf0', at: 70 },
    { n: '紅', c: '#ef5b5b', at: 120 }, { n: '橙', c: '#ff9d3d', at: 200 }, { n: '金', c: '#f2c230', at: 320 }, { n: '彩虹', c: 'url(#km-rainbow)', at: 500 },
  ];
  const ANIMALS = [
    { id: 'cat', name: '小貓', at: 0, color: '#f4a259' }, { id: 'duck', name: '小鴨', at: 0, color: '#f6d55c' }, { id: 'bunny', name: '兔兔', at: 3, color: '#ece6dc' },
    { id: 'fox', name: '狐狸', at: 6, color: '#e8793a' }, { id: 'bear', name: '小熊', at: 10, color: '#a9744f' }, { id: 'deer', name: '小鹿', at: 15, color: '#c99a6b' },
    { id: 'owl', name: '貓頭鷹', at: 22, color: '#8d7b68' }, { id: 'penguin', name: '企鵝', at: 30, color: '#2f4858' }, { id: 'unicorn', name: '獨角獸', at: 45, color: '#f1e6ff' },
    { id: 'dragon', name: '小龍', at: 60, color: '#4cc27a' },
  ];
  const ANIMAL = Object.fromEntries(ANIMALS.map((a) => [a.id, a]));
  const GLYPH = { wifi: '⌁', mobile: '◌', broadband: '≋', csit: '◈', cert: '✦', integrations: '⌕', equipment: '▣', lab: '⚗', admin: '▤' };
  const ADJ = ['好奇', '認真', '悠閒', '機靈', '溫柔', '勤勞', '愛問', '開朗', '安靜', '活潑'];
  const AVATAR = 1.7, STORE = 'km-island-demo', MAX_USERS = 40;
  const REDUCED = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const rnd = (a, b) => a + Math.random() * (b - a);
  const pick = (list) => list[Math.floor(Math.random() * list.length)];
  const tierOf = (points) => TIERS.filter((t) => points >= t.at).length;
  const levelSum = (scores) => Object.values(scores).reduce((n, p) => n + tierOf(p), 0);
  const unlocked = (scores) => ANIMALS.filter((a) => levelSum(scores) >= a.at);
  const topTier = (scores) => Math.max(0, ...Object.values(scores).map(tierOf));
  const tierName = (t) => `${TIERS[t - 1].n}徽章`;
  const shortZone = (id) => H.shortName(id);
  const zoneIds = () => H.ids();
  const earned = (scores) => zoneIds().filter((id) => tierOf(scores[id] || 0) > 0).sort((a, b) => tierOf(scores[b]) - tierOf(scores[a]));
  const fakeScores = () => {
    const scores = {};
    zoneIds().sort(() => Math.random() - .5).slice(0, 1 + Math.floor(Math.random() * 6)).forEach((id) => { scores[id] = Math.floor(Math.pow(Math.random(), 2.2) * 520); });
    return scores;
  };
  const DEFAULT_ME = () => ({ scores: { wifi: 38, mobile: 6, cert: 16 }, animal: 'cat' });
  const loadMine = () => {
    try { const v = JSON.parse(localStorage.getItem(STORE) || 'null'); if (v && v.scores && ANIMAL[v.animal]) return v; } catch (_) { /* no storage: use the defaults */ }
    return DEFAULT_ME();
  };
  const saveMine = (m) => { try { localStorage.setItem(STORE, JSON.stringify({ scores: m.scores, animal: m.kind })); } catch (_) { /* not saved */ } };
  const badgeSvg = (tier, glyph, size = 30) => `<svg class="bsvg" width="${size}" height="${Math.round(size * 1.08)}" viewBox="0 0 24 26" aria-hidden="true"><path d="M12 1.5 L21.5 5 V12.5 C21.5 18 17.5 22.5 12 24.5 C6.5 22.5 2.5 18 2.5 12.5 V5 Z" fill="${tier ? TIERS[tier - 1].c : 'none'}" stroke="${tier ? 'rgba(0,0,0,.4)' : 'currentColor'}" stroke-width="1" ${tier ? '' : 'stroke-dasharray="2 2" opacity=".5"'}/>`
    + (tier ? `<path d="M12 4 L19 6.6 V12.4 C19 16.6 16 20 12 21.8 C8 20 5 16.6 5 12.4 V6.6 Z" fill="rgba(255,255,255,.2)"/><text x="12" y="15.2" text-anchor="middle" font-size="9" font-weight="700" fill="#fff" stroke="rgba(0,0,0,.35)" stroke-width=".4">${glyph}</text>` : `<text x="12" y="15.2" text-anchor="middle" font-size="9" fill="currentColor" opacity=".5">${glyph}</text>`) + `</svg>`;
  const ringHtml = (u) => { const t = topTier(u.scores); return (t ? `<ellipse cx="0" cy="1" rx="5.8" ry="2.2" fill="none" stroke="${TIERS[t - 1].c}" stroke-width="1.3"/>` : '') + (u.me ? `<ellipse cx="0" cy="1" rx="8" ry="3" fill="none" stroke="${ACC}" stroke-width="1.2"/>` : ''); };

  /* ---- the animals ---- */
  function figure(u) {
    const k = u.kind, c = u.color, dark = shade(c, .7), light = shade(c, 1.18);
    let ears = '', beak = '', cheek = '', tail = '', behind = '', front = '', eyes = true, feet = dark, belly = light;
    if (k === 'cat' || k === 'fox') ears = [-1, 1].map((s) => `<polygon points="${s * 4},-12 ${s * 2.8},-16.6 ${s * .6},-13.6" fill="${c}"/>`).join('');
    if (k === 'bunny') ears = [-1, 1].map((s) => `<ellipse cx="${s * 2}" cy="-16" rx="1.4" ry="3.6" fill="${c}"/><ellipse cx="${s * 2}" cy="-16" rx=".6" ry="2.4" fill="#f7c6d0"/>`).join('');
    if (k === 'bear') ears = [-1, 1].map((s) => `<circle cx="${s * 3.6}" cy="-13.6" r="1.8" fill="${c}"/>`).join('');
    if (k === 'deer') ears = [-1, 1].map((s) => `<ellipse cx="${s * 4.2}" cy="-12.6" rx="1.6" ry=".9" fill="${c}"/><path d="M${s * 2},-14 L${s * 3},-18 M${s * 2.6},-16.2 L${s * 4.6},-17.4" stroke="#8a6a48" stroke-width=".9" fill="none" stroke-linecap="round"/>`).join('');
    if (k === 'duck') beak = `<polygon points="4.2,-10.4 7.2,-9.4 4.2,-8.4" fill="#ff9d2e"/><path d="M-1,-14.4 Q0,-17 1.4,-14.6" stroke="${dark}" stroke-width=".9" fill="none"/>`;
    if (k === 'fox') { cheek = `<ellipse cx="0" cy="-8.4" rx="3.2" ry="1.8" fill="#fff7ea"/>`; tail = `<ellipse cx="-5" cy="-4" rx="3" ry="1.8" fill="${c}" transform="rotate(-30 -5 -4)"/><circle cx="-7.6" cy="-5.6" r="1" fill="#fff7ea"/>`; }
    if (k === 'bunny') tail = `<circle cx="-4.3" cy="-3.2" r="1.5" fill="#fff"/>`;
    if (k === 'owl') {
      ears = [-1, 1].map((s) => `<polygon points="${s * 3.8},-13.2 ${s * 2.9},-16.8 ${s * .8},-14.2" fill="${c}"/>`).join('');
      behind = [-1, 1].map((s) => `<ellipse cx="${s * 4.2}" cy="-4.6" rx="1.3" ry="3.4" fill="${dark}"/>`).join('');
      eyes = false;
      front = [-1, 1].map((s) => `<circle cx="${s * 1.9}" cy="-10.3" r="2" fill="#fff"/><circle cx="${s * 1.9}" cy="-10.3" r=".9" fill="#1d3238"/>`).join('') + `<polygon points="-.7,-9 .7,-9 0,-7.6" fill="#ff9d2e"/>`;
      feet = '#ff9d2e';
    }
    if (k === 'penguin') {
      belly = '#f5f7f7'; feet = '#ff9d2e';
      behind = [-1, 1].map((s) => `<ellipse cx="${s * 4.3}" cy="-4.6" rx="1.2" ry="3.2" fill="${dark}" transform="rotate(${s * -12} ${s * 4.3} -4.6)"/>`).join('');
      front = `<ellipse cx="0" cy="-9.6" rx="2.6" ry="2.7" fill="#f5f7f7"/><polygon points="-1,-9.6 1,-9.6 0,-8.2" fill="#ff9d2e"/>`;
      eyes = false; front += [-1, 1].map((s) => `<circle cx="${s * 1.4}" cy="-10.6" r=".75" fill="#1d3238"/>`).join('');
    }
    if (k === 'unicorn') {
      ears = [-1, 1].map((s) => `<ellipse cx="${s * 3.6}" cy="-13.4" rx="1.3" ry="1.6" fill="${c}"/>`).join('') + `<polygon points="-.9,-14 0,-19.6 .9,-14" fill="#f2c230"/><line x1="-.7" y1="-16" x2=".7" y2="-15.4" stroke="#fff3b0" stroke-width=".6"/>`;
      behind = `<ellipse cx="-3.6" cy="-9.4" rx="1.5" ry="3.4" fill="#f7a8d8"/>`;
      tail = `<path d="M-4,-4 Q-8,-6 -7,-1.5" stroke="#f7a8d8" stroke-width="1.8" fill="none" stroke-linecap="round"/>`;
    }
    if (k === 'dragon') {
      behind = [-1, 1].map((s) => `<polygon points="${s * 3},-7.4 ${s * 8.6},-12.6 ${s * 5},-3" fill="${shade(c, .78)}"/>`).join('');
      ears = [-1, 1].map((s) => `<polygon points="${s * 2.2},-13.6 ${s * 3.6},-18 ${s * .8},-14.2" fill="#f5e6b3"/>`).join('');
      tail = `<path d="M-4,-3 Q-9,-4 -8.6,-.6" stroke="${c}" stroke-width="2" fill="none" stroke-linecap="round"/><polygon points="-9.6,-1.6 -7.4,-1.6 -8.6,.6" fill="#f5e6b3"/>`;
      belly = '#f5e6b3';
    }
    const bodyFill = k === 'penguin' ? dark : c;
    const head = k === 'penguin' ? dark : c;
    return `<ellipse cx="0" cy="1" rx="4.6" ry="1.5" fill="var(--shadow)"/>${behind}${tail}<ellipse class="ft1" cx="-1.9" cy="-.4" rx="1.6" ry="1" fill="${feet}"/><ellipse class="ft2" cx="1.9" cy="-.4" rx="1.6" ry="1" fill="${feet}"/>`
      + `<ellipse cx="0" cy="-4.6" rx="3.9" ry="4.7" fill="${bodyFill}"/><ellipse cx="0" cy="-3.6" rx="2.4" ry="3" fill="${belly}"/>${ears}<circle cx="0" cy="-10" r="4.5" fill="${head}"/>${cheek}`
      + (eyes ? `<circle cx="-1.7" cy="-10.5" r=".75" fill="#1d3238"/><circle cx="1.7" cy="-10.5" r=".75" fill="#1d3238"/>` : '') + beak + front;
  }

  /* ---- walking: each person is a small animal that wanders on the free ground of the island they are in ---- */
  const walkArea = H.hex(.8);
  const inPoly = (x, y, poly) => { let inside = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) { const [xi, yi] = poly[i], [xj, yj] = poly[j]; if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside; } return inside; };
  /* free ground: inside the island, in front of the library (not behind or in it) and above the name label */
  const walkable = (id, x, y) => { const g = H.geo(id); return inPoly(x, y, walkArea) && y > -30 && y < 9 && !(Math.abs(x - g.bx) < 38 && y < g.by + 9); };
  const sample = (id) => { for (let i = 0; i < 60; i++) { const x = rnd(-64, 64), y = rnd(-28, 8); if (walkable(id, x, y)) return { x, y }; } return { x: H.geo(id).bx + 44, y: 0 }; };
  const clearPath = (id, a, b) => { for (let k = 1; k <= 8; k++) if (!walkable(id, a.x + (b.x - a.x) * k / 8, a.y + (b.y - a.y) * k / 8)) return false; return true; };

  const users = [];
  let seq = 0, scene = null, selected = 'wifi', started = false, wired = false, meTab = 'badges', toastTimer = 0, last = 0, sortAt = 0;
  let tipEl, meEl, cardEl, toastEl;
  const layer = (id) => scene && scene.querySelector(`.isl-people[data-island="${id}"]`);
  const nameFor = (kind) => { for (let i = 0; i < 20; i++) { const n = pick(ADJ) + '的' + ANIMAL[kind].name; if (!users.some((u) => u.name === n)) return n; } return pick(ADJ) + '的' + ANIMAL[kind].name + (seq % 90 + 10); };
  const place = (u) => u.el.setAttribute('transform', `translate(${u.pos.x.toFixed(1)},${u.pos.y.toFixed(1)})`);

  function spawn(island, opts = {}) {
    const where = layer(island); if (!where) return null;
    const scores = opts.scores || fakeScores(), kind = opts.kind || pick(unlocked(scores)).id;
    const u = { id: ++seq, name: opts.name || nameFor(kind), kind, color: ANIMAL[kind].color, scores, island, speed: rnd(9, 15), wait: rnd(0, 3), me: !!opts.me, phase: rnd(0, 6), pos: sample(island), target: null };
    u.el = document.createElementNS(NS, 'g');
    u.el.setAttribute('class', 'av' + (u.me ? ' me' : ''));
    u.el.dataset.uid = u.id;
    u.el.innerHTML = `<g class="fig pop"><ellipse class="hitbox" cx="0" cy="-12" rx="13" ry="22"/><g transform="scale(${AVATAR})">${ringHtml(u)}</g><g class="walk" transform="scale(${AVATAR})">${figure(u)}</g>${u.me ? `<g transform="translate(0,-37) scale(1.3)"><rect x="-6" y="-6" width="12" height="9" rx="4" fill="${ACC}"/><text y="1.8" text-anchor="middle" font-size="6" font-weight="700" fill="#04202a">你</text></g>` : ''}</g>`;
    const fig = u.el.querySelector('.fig');
    fig.addEventListener('animationend', (e) => { if (e.animationName === 'kmPop') fig.classList.remove('pop'); });  // a node that is moved in the DOM must not replay its entrance
    where.appendChild(u.el);
    users.push(u);
    place(u);
    return u;
  }
  function leave(u) { const fig = u.el.querySelector('.fig'); fig.classList.remove('pop'); fig.classList.add('out'); users.splice(users.indexOf(u), 1); setTimeout(() => u.el.remove(), 380); count(); }
  function moveTo(u, island) {
    if (!layer(island)) return;
    const fig = u.el.querySelector('.fig'); fig.classList.remove('pop'); fig.classList.add('out');
    setTimeout(() => {
      const where = layer(island); if (!where) return;
      u.island = island; u.pos = sample(island); u.target = null; where.appendChild(u.el); place(u);
      fig.classList.remove('out'); void fig.getBoundingClientRect(); fig.classList.add('pop'); count();
    }, 340);
  }

  function tick(now) {
    const dt = Math.min(.1, (now - last) / 1000); last = now;
    if (scene && scene.isConnected && !document.hidden) {
      for (const u of users) {
        if (REDUCED) break;
        if (u.hover) { u.walking = false; continue; }   // standing still while the pointer is on them, so a click lands
        if (u.wait > 0) { u.wait -= dt; u.walking = false; }
        else {
          if (!u.target) {
            for (let i = 0; i < 8 && !u.target; i++) { const t = sample(u.island); if (clearPath(u.island, u.pos, t)) u.target = t; }
            if (!u.target) { u.wait = rnd(1, 3); continue; }
          }
          const dx = u.target.x - u.pos.x, dy = u.target.y - u.pos.y, d = Math.hypot(dx, dy), step = u.speed * dt;
          if (d <= step) { u.pos = u.target; u.target = null; u.wait = rnd(1.5, 6); u.walking = false; }
          else { u.pos = { x: u.pos.x + dx / d * step, y: u.pos.y + dy / d * step }; u.walking = true; if (Math.abs(dx) > .5) u.face = dx < 0 ? -1 : 1; }
          place(u);
        }
        const walk = u.el.querySelector('.walk'), t = now / 1000 + u.phase;
        walk.setAttribute('transform', `scale(${(u.face || 1) * AVATAR},${AVATAR}) translate(0,${u.walking ? (-Math.abs(Math.sin(t * 9)) * 1.4).toFixed(2) : 0})`);
        const f1 = walk.querySelector('.ft1'), f2 = walk.querySelector('.ft2');
        if (u.walking && f1 && f2) { f1.setAttribute('cy', (-.4 - Math.max(0, Math.sin(t * 9)) * 1.3).toFixed(2)); f2.setAttribute('cy', (-.4 - Math.max(0, -Math.sin(t * 9)) * 1.3).toFixed(2)); }
      }
      if (now - sortAt > 400) {  // paint the ones further back first; only touch the DOM when the order really changed
        sortAt = now;
        const yOf = new Map(users.map((u) => [u.el, u.pos.y]));
        scene.querySelectorAll('.isl-people').forEach((g) => { const cur = [...g.children], want = cur.slice().sort((a, b) => (yOf.get(a) || 0) - (yOf.get(b) || 0)); if (want.some((n, i) => n !== cur[i])) want.forEach((n) => g.appendChild(n)); });
      }
    }
    requestAnimationFrame(tick);
  }

  /* simulated comings and goings, as the real page would see them when it polls the server */
  function churn() {
    const others = users.filter((u) => !u.me), r = Math.random();
    if (!document.hidden && scene && scene.isConnected) {
      if (r < .34 && others.length > 3) leave(pick(others));
      else if (r < .68 && users.length < MAX_USERS) { spawn(pick(WEIGHTS())); count(); }
      else if (others.length) moveTo(pick(others), pick(zoneIds()));
    }
    setTimeout(churn, rnd(5000, 12000));
  }
  const WEIGHTS = () => { const ids = zoneIds(); return ids.concat(ids.filter((id) => id === 'wifi' || id === 'mobile'), ['wifi']); };

  /* ---- who is where: the corner pill and the line in the island's side panel ---- */
  function count() {
    const pill = document.getElementById('pp-online'); if (pill) pill.textContent = `${users.length} 人在線（示範）`;
    const crowd = document.querySelector('.isl-crowd'); if (!crowd) return;
    const here = users.filter((u) => u.island === selected);
    crowd.innerHTML = here.length ? `島上現在有 <strong>${here.length}</strong> 人：${here.map((u) => esc(u.me ? '你' : u.name)).join('、')}` : '島上目前沒有人';
  }

  /* ---- badge wall, animal picker, and the card that opens when a person is clicked ---- */
  const meUser = () => users.find((u) => u.me);
  const animalSvg = (id, size = 64) => `<svg width="${size}" height="${Math.round(size * 1.15)}" viewBox="-12 -23 24 27" aria-hidden="true">${figure({ kind: id, color: ANIMAL[id].color, scores: {} })}</svg>`;
  function toast(text) { toastEl.textContent = text; toastEl.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { toastEl.hidden = true; }, 3800); }

  function renderMe() {
    const m = meUser(); if (!m) return;
    const sc = m.scores, total = levelSum(sc), have = earned(sc).length;
    const rows = zoneIds().map((id) => {
      const p = sc[id] || 0, t = tierOf(p), next = TIERS[t], prev = t ? TIERS[t - 1].at : 0, pct = next ? Math.round((p - prev) / (next.at - prev) * 100) : 100;
      return `<li class="pp-brow"><span class="pp-bi">${badgeSvg(t, GLYPH[id] || '◇', 36)}</span><div><div class="pp-bline"><strong>${esc(shortZone(id))}</strong><span>${t ? `${tierName(t)}・Lv.${t}` : '尚未取得徽章'}</span></div>
        <div class="pp-bar"><i style="width:${pct}%;background:${t ? (TIERS[t - 1].c.startsWith('url') ? 'linear-gradient(90deg,#ff5b5b,#ffc83d,#4cd7a0,#4aa8ff,#b57cff)' : TIERS[t - 1].c) : ACC}"></i></div>
        <small>${p} 分${next ? `・再 ${next.at - p} 分升為${tierName(t + 1)}（${next.at} 分）` : '・已達最高等級'}</small></div></li>`;
    }).join('');
    const animals = ANIMALS.map((a) => {
      const ok = total >= a.at, on = m.kind === a.id;
      return `<li class="pp-acard${ok ? '' : ' locked'}${on ? ' on' : ''}"><div class="pp-apic">${animalSvg(a.id, 58)}</div><strong>${a.name}</strong>
        ${ok ? `<button type="button" class="pp-btn small" data-pick="${a.id}" ${on ? 'disabled' : ''}>${on ? '使用中' : '選擇'}</button>` : `<small>徽章等級合計 ${a.at}<br>（目前 ${total}）</small>`}</li>`;
    }).join('');
    meEl.querySelector('.pp-sheet').innerHTML = `<button type="button" class="pp-x" data-close aria-label="關閉">×</button><h2 id="pp-me-title">我的徽章與動物</h2>
      <p class="pp-sum">已取得 <strong>${have}</strong> 枚徽章・徽章等級合計 <strong>${total}</strong>（每個專區的徽章每升一級計 1）</p>
      <div class="pp-tabs" role="tablist"><button type="button" role="tab" data-tab="badges" aria-selected="${meTab === 'badges'}">徽章</button><button type="button" role="tab" data-tab="animals" aria-selected="${meTab === 'animals'}">動物</button></div>
      ${meTab === 'badges' ? `<ul class="pp-list">${rows}</ul>` : `<p class="pp-note">徽章等級合計越高，解鎖越多動物，可以自由選擇要使用哪一隻。</p><ul class="pp-agrid">${animals}</ul>`}
      <div class="pp-sim"><span>示範資料・加分工具：</span><select id="pp-sim-zone" aria-label="模擬提問的專區">${zoneIds().map((id) => `<option value="${id}">${esc(shortZone(id))}</option>`).join('')}</select>
        <button type="button" class="pp-btn small" data-add="1">＋1 分（一次符合主題的提問）</button><button type="button" class="pp-btn small" data-add="10">＋10 分</button><button type="button" class="pp-btn small" data-reset>重設</button></div>`;
  }
  function openMe(tab) { if (tab) meTab = tab; renderMe(); meEl.hidden = false; meEl.querySelector('[data-close]').focus(); }
  function refreshMeAvatar() {
    const m = meUser(); if (!m) return;
    m.el.querySelector('.walk').innerHTML = figure(m);
    m.el.querySelector('.fig > g').innerHTML = ringHtml(m);
  }
  function addPoints(zone, n) {
    const m = meUser(), before = m.scores[zone] || 0, t0 = tierOf(before), total0 = levelSum(m.scores);
    m.scores[zone] = before + n; saveMine(m);
    const t1 = tierOf(m.scores[zone]), total1 = levelSum(m.scores), fresh = ANIMALS.filter((a) => a.at > total0 && a.at <= total1), lines = [];
    if (t1 > t0) lines.push(`${shortZone(zone)}專區升為${tierName(t1)}（Lv.${t1}）`);
    if (fresh.length) lines.push(`解鎖新動物：${fresh.map((a) => a.name).join('、')}`);
    if (lines.length) toast(lines.join('　'));
    refreshMeAvatar(); renderMe(); count();
  }
  function openCard(u, x, y) {
    const list = earned(u.scores), total = levelSum(u.scores);
    cardEl.innerHTML = `<button type="button" class="pp-x" data-close aria-label="關閉">×</button><div class="pp-chead"><div class="pp-apic">${animalSvg(u.kind, 44)}</div><div><strong>${esc(u.me ? '你' : u.name)}</strong><small>${ANIMAL[u.kind].name}・在${esc(shortZone(u.island))}</small></div></div>
      <p class="pp-csum">${list.length ? `已取得 ${list.length} 枚徽章・徽章等級合計 ${total}` : '還沒有取得徽章'}（示範資料）</p>
      <ul class="pp-clist">${list.map((id) => { const t = tierOf(u.scores[id]); return `<li>${badgeSvg(t, GLYPH[id] || '◇', 26)}<span>${esc(shortZone(id))}</span><em>${tierName(t)}${u.me ? `・${u.scores[id]} 分` : ''}</em></li>`; }).join('')}</ul>
      ${u.me ? '<button type="button" class="pp-btn small" data-open-me>管理我的徽章與動物</button>' : ''}`;
    cardEl.hidden = false;
    const r = cardEl.getBoundingClientRect();
    cardEl.style.left = `${Math.max(8, Math.min(x + 14, innerWidth - r.width - 8))}px`;
    cardEl.style.top = `${Math.max(8, Math.min(y - 20, innerHeight - r.height - 8))}px`;
  }

  /* the pieces that live outside the map (modal, card, tip, toast) exist once; the map itself is drawn again on every refresh */
  function ensureUi() {
    if (meEl) return;
    const box = document.createElement('div');
    box.innerHTML = `<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><linearGradient id="km-rainbow" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="#ff5b5b"/><stop offset=".25" stop-color="#ffc83d"/><stop offset=".5" stop-color="#4cd7a0"/><stop offset=".75" stop-color="#4aa8ff"/><stop offset="1" stop-color="#b57cff"/></linearGradient></defs></svg>
      <div id="pp-tip" class="pp-tip" hidden></div><div id="pp-me" class="pp-modal" hidden role="dialog" aria-modal="true" aria-labelledby="pp-me-title"><div class="pp-sheet"></div></div>
      <div id="pp-card" class="pp-card" hidden role="dialog" aria-label="人物徽章"></div><div id="pp-toast" class="pp-toast" role="status" hidden></div>`;
    document.body.append(...box.children);
    tipEl = document.getElementById('pp-tip'); meEl = document.getElementById('pp-me'); cardEl = document.getElementById('pp-card'); toastEl = document.getElementById('pp-toast');
    const closeMe = () => { meEl.hidden = true; };
    meEl.addEventListener('click', (e) => {
      if (e.target === meEl || e.target.closest('[data-close]')) return closeMe();
      const tab = e.target.closest('[data-tab]'); if (tab) { meTab = tab.dataset.tab; return renderMe(); }
      const choose = e.target.closest('[data-pick]');
      if (choose) { const m = meUser(); m.kind = choose.dataset.pick; m.color = ANIMAL[m.kind].color; saveMine(m); refreshMeAvatar(); renderMe(); return toast(`現在使用：${ANIMAL[m.kind].name}`); }
      const add = e.target.closest('[data-add]'); if (add) return addPoints(document.getElementById('pp-sim-zone').value, Number(add.dataset.add));
      if (e.target.closest('[data-reset]')) { const m = meUser(), d = DEFAULT_ME(); m.scores = d.scores; m.kind = d.animal; m.color = ANIMAL[m.kind].color; saveMine(m); refreshMeAvatar(); renderMe(); }
    });
    cardEl.addEventListener('click', (e) => { if (e.target.closest('[data-close]')) cardEl.hidden = true; if (e.target.closest('[data-open-me]')) { cardEl.hidden = true; openMe('badges'); } });
    document.addEventListener('mousedown', (e) => { if (!cardEl.hidden && !cardEl.contains(e.target) && !(e.target.closest && e.target.closest('.av'))) cardEl.hidden = true; });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { cardEl.hidden = true; closeMe(); } });
  }

  /* called by Islands.bind() each time the map is drawn */
  function attach(map) {
    scene = map.querySelector('.isl-scene'); if (!scene) return;
    ensureUi();
    const bar = document.createElement('div');
    bar.className = 'pp-toolbar';
    bar.innerHTML = '<span class="pp-pill" title="示範資料：人物與分數都是模擬的"><i></i><span id="pp-online"></span></span><button type="button" class="pp-btn small" data-pp="me">我的徽章與動物</button><button type="button" class="pp-btn small" data-pp="hide" aria-pressed="true">隱藏人物</button>';
    map.appendChild(bar);
    bar.addEventListener('click', (e) => {
      const b = e.target.closest('[data-pp]'); if (!b) return;
      if (b.dataset.pp === 'me') return openMe('badges');
      const off = scene.classList.toggle('nopeople'); b.setAttribute('aria-pressed', String(!off)); b.textContent = off ? '顯示人物' : '隱藏人物';
    });
    scene.addEventListener('mousemove', (e) => {
      const av = e.target.closest && e.target.closest('.av');
      if (!av) { tipEl.hidden = true; return; }
      const u = users.find((x) => String(x.id) === av.dataset.uid); if (!u) return;
      tipEl.textContent = `${u.me ? '你' : u.name}・${shortZone(u.island)}`;
      tipEl.hidden = false; tipEl.style.left = `${e.clientX + 12}px`; tipEl.style.top = `${e.clientY - 28}px`;
    });
    scene.addEventListener('mouseleave', () => { tipEl.hidden = true; });
    const hover = (e, on) => { const av = e.target.closest && e.target.closest('.av'); const u = av && users.find((x) => String(x.id) === av.dataset.uid); if (u) u.hover = on; };
    scene.addEventListener('mouseover', (e) => hover(e, true));
    scene.addEventListener('mouseout', (e) => hover(e, false));
    scene.addEventListener('click', (e) => {   // capture phase: a click on a person opens the card instead of selecting the island
      const av = e.target.closest && e.target.closest('.av'); if (!av) return;
      e.preventDefault(); e.stopImmediatePropagation();
      const u = users.find((x) => String(x.id) === av.dataset.uid); if (u) openCard(u, e.clientX, e.clientY);
    }, true);
    if (!started) {
      started = true;
      const mine = loadMine(), target = Math.max(0, Math.min(MAX_USERS, Number(new URLSearchParams(location.search).get('users') ?? 11)));
      spawn(layer('wifi') ? 'wifi' : zoneIds()[0], { me: true, name: '你', scores: mine.scores, kind: mine.animal });
      for (let i = 0; i < target - 1; i++) spawn(pick(WEIGHTS()));
      last = performance.now();
      requestAnimationFrame(tick);
      setTimeout(churn, 6000);
    } else {
      users.forEach((u) => { const where = layer(u.island) || layer('wifi'); if (where) { if (u.island !== where.dataset.island) { u.island = where.dataset.island; u.pos = sample(u.island); } where.appendChild(u.el); } });
    }
    count();
  }

  /* an island was selected: remember it for the "who is here" line; a click (not a hover or a refresh) also walks "you" over there */
  function select(id, visit) {
    selected = id;
    if (visit) { const me = meUser(); if (me && me.island !== id) moveTo(me, id); }
    count();
  }

  return { attach, select };
})();
