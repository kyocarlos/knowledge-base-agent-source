// Home page of the knowledge zones (part 1.5 of 3): the zone cards as an archipelago. Every zone is an island with its own "library"; a click shows the
// zone's numbers beside the map, the label links to the zone. The numbers come from hub.data (the same data the cards used). The drawing is plain SVG:
// no 3D library, no image files, and every island is a real link, so keyboard and screen readers work.
const Islands = (() => {
  const R = 74, K = 0.56, GAP = 1.3, T = 20;
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pts = (list) => list.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
  const hex = (s = 1) => [0, 1, 2, 3, 4, 5].map((i) => { const a = Math.PI / 3 * i; return [R * s * Math.cos(a), R * s * Math.sin(a) * K]; });
  const shade = (hexColor, f) => { const n = parseInt(hexColor.slice(1), 16); const c = (v) => Math.max(0, Math.min(255, Math.round(v * f))); return `rgb(${c(n >> 16)},${c((n >> 8) & 255)},${c(n & 255)})`; };

  function roof(x, y, w, h, rh, color) {
    const top = y - h, apex = [x, top - w * 0.5 - rh];
    const left = [[x - w, top - w * 0.5], [x, top], apex], right = [[x, top], [x + w, top - w * 0.5], apex];
    return `<polygon points="${pts(left)}" fill="${shade(color, .82)}"/><polygon points="${pts(right)}" fill="${color}"/>`;
  }
  const tree = (x, y, s = 1) => `<rect x="${x - 2 * s}" y="${y - 12 * s}" width="${4 * s}" height="${12 * s}" fill="var(--trunk)"/><ellipse cx="${x}" cy="${y + 1}" rx="${9 * s}" ry="${3.5 * s}" fill="var(--shadow)"/>`
    + `<circle cx="${x}" cy="${y - 20 * s}" r="${11 * s}" fill="var(--leaf)"/><circle cx="${x - 3 * s}" cy="${y - 23 * s}" r="${7 * s}" fill="var(--leaf2)"/>`;
  const pine = (x, y, s = 1) => `<ellipse cx="${x}" cy="${y + 1}" rx="${8 * s}" ry="${3 * s}" fill="var(--shadow)"/><path d="M${x},${y - 34 * s} L${x + 10 * s},${y - 10 * s} L${x - 10 * s},${y - 10 * s} Z" fill="var(--leaf2)"/><path d="M${x},${y - 24 * s} L${x + 12 * s},${y} L${x - 12 * s},${y} Z" fill="var(--leaf)"/>`;
  /* ---- libraries: one per zone, each with its own style and a sculpture that says what the zone is about ---- */
  const box = (x, y, wl, wr, h, wall, wall2) => `<polygon points="${pts([[x - wl, y - wl * .5], [x, y], [x, y - h], [x - wl, y - h - wl * .5]])}" fill="${wall2}"/><polygon points="${pts([[x, y], [x + wr, y - wr * .5], [x + wr, y - h - wr * .5], [x, y - h]])}" fill="${wall}"/>`;
  const cube = (x, y, w, h, a = 'var(--wall)', b = 'var(--wall2)') => box(x, y, w, w, h, a, b);
  const topFace = (x, y, wl, wr, h, fill) => { const t = y - h; return `<polygon points="${pts([[x - wl, t - wl * .5], [x, t], [x + wr, t - wr * .5], [x + wr - wl, t - wr * .5 - wl * .5]])}" fill="${fill}"/>`; };
  const rq = (x, y, w, u0, u1, v0, v1, fill) => { const f = (u, v) => [x + w * u, y - w * .5 * u - v]; return `<polygon points="${pts([f(u0, v0), f(u1, v0), f(u1, v1), f(u0, v1)])}" fill="${fill}"/>`; };
  const lq = (x, y, w, u0, u1, v0, v1, fill) => { const f = (u, v) => [x - w * u, y - w * .5 * u - v]; return `<polygon points="${pts([f(u0, v0), f(u1, v0), f(u1, v1), f(u0, v1)])}" fill="${fill}"/>`; };
  const cols = (face, x, y, w, n, v0, v1, fill) => Array.from({ length: n }, (_, i) => face(x, y, w, (i + .3) / n, (i + .62) / n, v0, v1, fill)).join('');
  const cyl = (x, y, r, h, a = 'var(--wall)', b = 'var(--wall2)') => `<path d="M${x - r},${y - h} L${x - r},${y} A${r},${r * .4} 0 0 0 ${x + r},${y} L${x + r},${y - h} Z" fill="${a}"/><path d="M${x - r},${y - h} L${x - r},${y} A${r},${r * .4} 0 0 0 ${x},${y + r * .4} L${x},${y - h} Z" fill="${b}"/>`;
  const line = (x1, y1, x2, y2, c, w = 1.4) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${c}" stroke-width="${w}" stroke-linecap="round"/>`;
  const wifiMark = (cx, cy, s, c, sw = 1.6) => [1, 2, 3].map((k) => { const r = s * k * 3.4, d = r * .707; return `<path d="M${cx - d},${cy - d} A${r},${r} 0 0 1 ${cx + d},${cy - d}" fill="none" stroke="${c}" stroke-width="${sw}" stroke-linecap="round"/>`; }).join('') + `<circle cx="${cx}" cy="${cy}" r="${1.6 * s}" fill="${c}"/>`;
  const star = (cx, cy, r, c) => `<polygon points="${pts(Array.from({ length: 10 }, (_, i) => { const a = -Math.PI / 2 + i * Math.PI / 5, q = i % 2 ? r * .45 : r; return [cx + q * Math.cos(a), cy + q * Math.sin(a)]; }))}" fill="${c}"/>`;
  const gear = (x, y, r, c) => Array.from({ length: 8 }, (_, i) => `<rect x="-1.7" y="${-r - 2.4}" width="3.4" height="4.6" fill="${c}" transform="translate(${x},${y}) rotate(${i * 45})"/>`).join('') + `<circle cx="${x}" cy="${y}" r="${r}" fill="${c}"/><circle cx="${x}" cy="${y}" r="${r * .42}" fill="var(--top)"/>`;
  const DARK = '#27434a', GLASS = '#7fcbe6', GOLD = '#f2b632';

  const BUILD = {
    /* Wi-Fi: glass pavilion with an access point (disc, antennas, signal arcs) on the roof */
    wifi: (x, y, g) => box(x, y, 19, 19, 20, 'var(--wall)', 'var(--wall2)') + rq(x, y, 19, .1, .9, 5, 16, GLASS) + [1, 2, 3].map((k) => rq(x, y, 19, k * .225 - .012, k * .225 + .012, 5, 16, '#e6f4f8')).join('')
      + lq(x, y, 19, .15, .85, 5, 16, '#5fb4d3') + topFace(x, y, 19, 19, 20, g.rim)
      + `<rect x="${x - 1.3}" y="${y - 39}" width="2.6" height="10" fill="#b9c7cb"/><ellipse cx="${x}" cy="${y - 40}" rx="11" ry="4" fill="#dfe9eb"/><ellipse cx="${x}" cy="${y - 41.5}" rx="10" ry="3.1" fill="#fff"/><circle cx="${x + 5.5}" cy="${y - 40.4}" r="1" fill="#4cd964"/>`
      + line(x - 7, y - 42, x - 10, y - 50, '#cfd8dc', 1.8) + line(x + 7, y - 42, x + 10, y - 50, '#cfd8dc', 1.8) + wifiMark(x, y - 47, .95, '#ffd36b'),
    /* 4G/5G: hall with a lattice base-station mast, sector panels and signal waves */
    mobile: (x, y, g) => {
      const top = y - 16 - 10, h = 46, w0 = 7, w1 = 1.3, wi = (k) => w0 + (w1 - w0) * k;
      let m = '';
      for (let i = 0; i < 5; i++) { const a = i / 5, b = (i + 1) / 5, ya = top - h * a, yb = top - h * b; m += line(x - wi(a), ya, x + wi(b), yb, '#dbe5e8', 1) + line(x + wi(a), ya, x - wi(b), yb, '#dbe5e8', 1); }
      return cube(x, y, 20, 16) + cols(rq, x, y, 20, 4, 0, 14, '#f4f7f6') + rq(x, y, 20, .38, .62, 0, 8, DARK) + topFace(x, y, 20, 20, 16, '#e6dcc3')
        + `<polygon points="${pts([[x - w0, top], [x - w1, top - h], [x + w1, top - h], [x + w0, top]])}" fill="none" stroke="#dbe5e8" stroke-width="1.5"/>` + m
        + `<rect x="${x - 7}" y="${top - h + 3}" width="3.6" height="9" fill="${g.roof}"/><rect x="${x + 3.4}" y="${top - h + 3}" width="3.6" height="9" fill="${g.roof}"/><circle cx="${x}" cy="${top - h - 2}" r="1.8" fill="#ff5a4f"/>`
        + [1, 2].map((k) => `<path d="M${x + 8 + k * 4},${top - h + 2} A${k * 5},${k * 5} 0 0 1 ${x + 8 + k * 4},${top - h + 12}" fill="none" stroke="#ffd36b" stroke-width="1.4" stroke-linecap="round"/><path d="M${x - 8 - k * 4},${top - h + 2} A${k * 5},${k * 5} 0 0 0 ${x - 8 - k * 4},${top - h + 12}" fill="none" stroke="#ffd36b" stroke-width="1.4" stroke-linecap="round"/>`).join('');
    },
    /* Broadband: long arched hall with a fibre cable reel and an orange fibre running to the door */
    broadband: (x0, y, g) => {
      const x = x0 - 6;
      return box(x, y, 12, 28, 14, 'var(--wall)', 'var(--wall2)') + [0, 1, 2, 3].map((i) => rq(x, y, 28, .08 + i * .22, .24 + i * .22, 3, 11, DARK) + rq(x, y, 28, .08 + i * .22, .24 + i * .22, 11, 12.4, '#cfe3e8')).join('')
        + topFace(x, y, 12, 28, 14, g.roof)
        + `<path d="M${x - 14},${y + 10} C${x - 4},${y + 14} ${x + 4},${y + 6} ${x + 10},${y + 1}" fill="none" stroke="#ffb74d" stroke-width="1.6" stroke-linecap="round"/><circle cx="${x + 10}" cy="${y + 1}" r="2" fill="#ffe08a"/>`
        + `<ellipse cx="${x - 22}" cy="${y + 14}" rx="9" ry="3" fill="var(--shadow)"/><circle cx="${x - 22}" cy="${y + 4}" r="10" fill="${g.roof}"/><circle cx="${x - 22}" cy="${y + 4}" r="7.2" fill="${shade(g.roof, .75)}"/><circle cx="${x - 22}" cy="${y + 4}" r="5.2" fill="none" stroke="#ffb74d" stroke-width="1.4"/><circle cx="${x - 22}" cy="${y + 4}" r="3.3" fill="none" stroke="#ffb74d" stroke-width="1.2"/><circle cx="${x - 22}" cy="${y + 4}" r="1.6" fill="#e9f2f3"/>`;
    },
    /* CSIT: stepped test-lab library with a clipboard / checklist statue */
    csit: (x, y, g) => cube(x, y, 18, 14) + rq(x, y, 18, .36, .64, 0, 8, DARK) + cols(lq, x, y, 18, 3, 3, 11, '#f4f7f6') + topFace(x, y, 18, 18, 14, '#e6dcc3')
      + cube(x, y - 18, 10, 9) + rq(x, y - 18, 10, .2, .8, 2, 6, GLASS) + topFace(x, y - 18, 10, 10, 9, g.roof)
      + cube(x - 30, y + 4, 5, 4, '#cfd9dc', '#b5c2c6') + `<rect x="${x - 37}" y="${y - 18}" width="14" height="18" rx="2" fill="#7a5a34"/><rect x="${x - 35.5}" y="${y - 16}" width="11" height="14" fill="#fff"/><rect x="${x - 33}" y="${y - 19.4}" width="6" height="3.4" rx="1" fill="#9aa7ab"/>`
      + `<polyline points="${x - 34},${y - 10} ${x - 32.2},${y - 8} ${x - 29},${y - 13}" fill="none" stroke="#2fb67c" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>${line(x - 29, y - 7, x - 26, y - 7, '#b9c7cb', 1.2)}${line(x - 34, y - 5, x - 26, y - 5, '#b9c7cb', 1.2)}`,
    /* Certification: Greek-style temple with a medal and ribbon on the pediment */
    cert: (x, y, g) => cube(x, y, 20, 13) + cols(rq, x, y, 20, 6, 0, 13, '#fbf8ef') + cols(lq, x, y, 20, 4, 0, 13, '#e4ddc8') + topFace(x, y, 20, 20, 13, '#efe6cf')
      + roof(x, y, 21, 13, 9, '#e8dcc0') + `<path d="M${x - 5},${y - 38} L${x - 8},${y - 29} L${x - 3},${y - 31} L${x - 1},${y - 28} Z" fill="#d8403a"/><path d="M${x + 5},${y - 38} L${x + 8},${y - 29} L${x + 3},${y - 31} L${x + 1},${y - 28} Z" fill="#b8312d"/>`
      + `<circle cx="${x}" cy="${y - 41}" r="8" fill="${GOLD}"/><circle cx="${x}" cy="${y - 41}" r="5.8" fill="#ffd66b"/>` + star(x, y - 41, 4.2, '#d08a12'),
    /* Integrations: twin towers linked by a skywalk, with a three-node network on top */
    integrations: (x, y, g) => box(x + 14, y - 3, 9, 9, 26, 'var(--wall)', 'var(--wall2)') + roof(x + 14, y - 3, 9, 26, 8, g.roof) + rq(x + 14, y - 3, 9, .3, .7, 8, 20, GLASS)
      + `<polygon points="${pts([[x - 6, y - 12], [x + 5, y - 17.5], [x + 5, y - 14], [x - 6, y - 8.5]])}" fill="#dbe5e8"/>`
      + box(x - 14, y + 3, 9, 9, 26, 'var(--wall)', 'var(--wall2)') + roof(x - 14, y + 3, 9, 26, 8, g.roof) + rq(x - 14, y + 3, 9, .3, .7, 8, 20, GLASS)
      + line(x - 14, y - 42, x + 14, y - 48, '#9fd8cc', 1.4) + line(x - 14, y - 42, x, y - 56, '#9fd8cc', 1.4) + line(x + 14, y - 48, x, y - 56, '#9fd8cc', 1.4)
      + `<circle cx="${x - 14}" cy="${y - 42}" r="3.6" fill="#ff9d4d"/><circle cx="${x + 14}" cy="${y - 48}" r="3.6" fill="#4aa8ff"/><circle cx="${x}" cy="${y - 56}" r="3.6" fill="#4cd7a0"/>`,
    /* Equipment: industrial hall with a saw-tooth roof, a gear and a booking calendar */
    equipment: (x0, y, g) => {
      const x = x0 - 4;
      return box(x, y, 14, 22, 14, 'var(--wall)', 'var(--wall2)') + rq(x, y, 22, .12, .42, 0, 9, '#8f9fa3') + [0, 1, 2].map((i) => rq(x, y, 22, .52 + i * .15, .62 + i * .15, 4, 10, GLASS)).join('')
        + topFace(x, y, 14, 22, 14, '#cfd9dc') + [.2, .55, .9].map((u) => { const px = x + 22 * u, py = y - 14 - 11 * u; return `<polygon points="${pts([[px - 7, py], [px + 7, py - 9], [px + 7, py]])}" fill="${g.roof}"/>`; }).join('')
        + `<rect x="${x - 3}" y="${y - 44}" width="2.4" height="22" fill="#b9c7cb"/>` + gear(x - 2, y - 46, 7.5, '#ffcf5a')
        + `<rect x="${x - 29}" y="${y - 14}" width="13" height="14" rx="1.5" fill="#fff"/><rect x="${x - 29}" y="${y - 14}" width="13" height="4.4" rx="1.5" fill="#e4503f"/>` + [0, 1, 2].flatMap((r) => [0, 1, 2].map((c) => `<rect x="${x - 27.5 + c * 3.8}" y="${y - 8 + r * 2.8}" width="2.2" height="1.6" fill="#8aa0a5"/>`)).join('');
    },
    /* Lab: observatory-style library (dome with a slit) and a conical flask sculpture */
    lab: (x, y, g) => cube(x, y, 16, 12) + rq(x, y, 16, .36, .64, 0, 8, DARK) + lq(x, y, 16, .25, .75, 4, 9, GLASS) + topFace(x, y, 16, 16, 12, '#e6dcc3')
      + `<ellipse cx="${x}" cy="${y - 20}" rx="14" ry="5.6" fill="var(--wall2)"/><path d="M${x - 14},${y - 20} A14,14 0 0 1 ${x + 14},${y - 20} Z" fill="#e9f1f2"/><path d="M${x},${y - 34} A14,14 0 0 1 ${x + 14},${y - 20} L${x},${y - 20} Z" fill="#cdd9dc"/><path d="M${x + 1},${y - 33.6} L${x + 5},${y - 31} L${x + 5},${y - 21} L${x + 1},${y - 21} Z" fill="${DARK}"/>` + line(x + 3, y - 31, x + 9, y - 39, '#9aa7ab', 3)
      + cube(x + 28, y + 3, 5, 3, '#cfd9dc', '#b5c2c6') + `<path d="M${x + 25},${y - 26} L${x + 31},${y - 26} L${x + 31},${y - 17} L${x + 39},${y - 2} L${x + 17},${y - 2} L${x + 25},${y - 17} Z" fill="rgba(210,242,252,.85)" stroke="#9fd0e0" stroke-width="1"/>`
      + `<path d="M${x + 20},${y - 7} L${x + 36},${y - 7} L${x + 39},${y - 2} L${x + 17},${y - 2} Z" fill="#4cd7a0"/><circle cx="${x + 26}" cy="${y - 11}" r="1.6" fill="#b8f3da"/><circle cx="${x + 31}" cy="${y - 14}" r="1.1" fill="#b8f3da"/>`,
    /* Admin: clock-tower library with a filing cabinet */
    admin: (x, y, g) => cube(x, y, 18, 14) + rq(x, y, 18, .36, .64, 0, 8, DARK) + cols(lq, x, y, 18, 3, 3, 11, '#f4f7f6') + topFace(x, y, 18, 18, 14, '#e6dcc3')
      + box(x, y - 19, 8, 8, 18, 'var(--wall)', 'var(--wall2)') + roof(x, y - 19, 8, 18, 9, g.roof) + `<circle cx="${x + 4}" cy="${y - 33}" r="4.4" fill="#fff" stroke="#8aa0a5" stroke-width=".8"/>${line(x + 4, y - 33, x + 4, y - 36, '#27434a', 1)}${line(x + 4, y - 33, x + 6.4, y - 32, '#27434a', 1)}`
      + box(x + 30, y + 2, 5, 5, 15, '#9db0b6', '#869ba2') + [0, 1, 2].map((i) => rq(x + 30, y + 2, 5, .15, .85, 2 + i * 4.2, 4.6 + i * 4.2, '#c2d0d4')).join('') + [0, 1, 2].map((i) => rq(x + 30, y + 2, 5, .4, .6, 3.2 + i * 4.2, 3.9 + i * 4.2, '#59707a')).join(''),
  };
  /* CPE and Small Cell live in the 4G/5G zone: a little home router and a pole-mounted small cell stand beside its base-station library. */
  const baseStation = BUILD.mobile;
  BUILD.mobile = (x, y, g) => baseStation(x, y, g)
    + cube(x - 34, y + 8, 6, 3, '#f4f7f6', '#cfd9dc') + topFace(x - 34, y + 8, 6, 6, 3, '#fff') + line(x - 36.5, y - 1, x - 39, y - 11, '#eef3f4', 1.6) + line(x - 31.5, y - 1.5, x - 29, y - 11.5, '#eef3f4', 1.6)
    + `<circle cx="${x - 32}" cy="${y + 3.6}" r=".8" fill="#4cd964"/>`
    + `<rect x="${x + 33}" y="${y - 13}" width="2" height="22" fill="#b9c7cb"/><rect x="${x + 28.5}" y="${y - 27}" width="11" height="15" rx="4" fill="#f4f7f6"/><rect x="${x + 28.5}" y="${y - 22}" width="11" height="2.4" fill="#3fcf8e"/>`
    + [1, 2].map((k) => `<path d="M${x + 41 + k * 3},${y - 24} A${k * 4},${k * 4} 0 0 1 ${x + 41 + k * 3},${y - 16}" fill="none" stroke="#ffd36b" stroke-width="1.3" stroke-linecap="round"/>`).join('');
  const LAYOUT = [
    { b: [-4, -14], t: [[-48, 8, .9], [50, 2, .8]], p: [[54, -14, .8]] }, { b: [4, -16], t: [[-50, 4, 1]], p: [[48, 8, .9], [-40, -12, .7]] },
    { b: [-6, -12], t: [[50, -4, .9], [44, 14, .7]], p: [[-52, 6, .9]] }, { b: [2, -14], t: [[-46, 10, .9]], p: [[50, -6, 1]] },
  ];


  /* ---- the zones as islands ---- */
  const THEMES = [{ rim: '#2f9bd4', roof: '#e4673d' }, { rim: '#e0a82e', roof: '#8a72c0' }, { rim: '#e0603f', roof: '#2f78b0' }];  // one per group of GROUPS
  const SLOTS = { wifi: [0, -1], mobile: [1, -1], broadband: [1, 0], csit: [-1, 0], cert: [-1, 1], integrations: [0, 0], equipment: [0, 1], lab: [1, 1], admin: [0, 2] };
  const SHORT = { integrations: 'Jira / TestRail', lab: '實驗室與測試環境' };
  const state = { selected: 'wifi' };
  const GEO = {};         // where each island's library stands, so the visitors keep clear of it
  let showIsland = null;  // set by bind(): selects an island and shows its numbers
  const groupIndex = (id) => Math.max(0, GROUPS.findIndex((g) => g.ids.includes(id)));
  const theme = (id) => ({ ...THEMES[groupIndex(id)] });
  const shortName = (id) => SHORT[id] || META[id].label.replace(' 知識專區', '').replace('知識專區', '').replace('專區', '');
  const todo = (id) => (hub.data[id] && hub.data[id].ok ? hub.data[id].attention.length : 0);
  const ids = () => GROUPS.flatMap((g) => g.ids).filter((id) => SLOTS[id] && hub.data[id]);

  function island(id, cx, cy, index) {
    const g = theme(id), top = hex(1), grass = hex(.84), L = LAYOUT[index % LAYOUT.length], s = hub.data[id], warn = todo(id);
    const side = (a, b, dy, fill) => `<polygon points="${pts([top[a], top[b], [top[b][0], top[b][1] + dy], [top[a][0], top[a][1] + dy]])}" fill="${fill}"/>`;
    let svg = `<ellipse cx="0" cy="${T + 12}" rx="${R * 1.05}" ry="${R * K * 1.1}" fill="var(--shadow)"/>`;
    svg += side(2, 3, T, 'var(--base)') + side(1, 2, T, 'var(--base2)') + side(0, 1, T, 'var(--base3)');
    svg += side(2, 3, 6, g.rim) + side(1, 2, 6, shade(g.rim, .82)) + side(0, 1, 6, shade(g.rim, .66));
    svg += `<polygon points="${pts(top)}" fill="var(--top)"/><polygon points="${pts(top)}" fill="none" stroke="${g.rim}" stroke-width="2.5" stroke-linejoin="round"/><polygon points="${pts(grass)}" fill="var(--grass)"/>`;
    GEO[id] = { bx: L.b[0], by: L.b[1] };
    const things = [{ y: L.b[1], s: `<g transform="translate(${L.b[0]} ${L.b[1]}) scale(.8) translate(${-L.b[0]} ${-L.b[1]})">${BUILD[id](L.b[0], L.b[1], g)}</g>` }];
    L.t.forEach(([x, y, k]) => things.push({ y, s: tree(x, y, k) }));
    L.p.forEach(([x, y, k]) => things.push({ y, s: pine(x, y, k) }));
    svg += things.sort((a, b) => a.y - b.y).map((t) => t.s).join('');
    svg += `<g class="isl-people" data-island="${id}"></g>`;
    const text = shortName(id), w = Math.max(70, [...text].reduce((n, c) => n + (c.charCodeAt(0) > 255 ? 14 : 8), 0) + 28), at = `translate(${cx.toFixed(1)},${cy.toFixed(1)})`, down = s && !s.ok;
    const url = zoneUrl(id);
    const label = `<a class="isl-hit isl-label${down ? ' down' : ''}" href="${esc(url)}" data-id="${id}" aria-label="${esc(META[id].label)}${warn ? `，待處理 ${warn} 項` : ''}" transform="${at}"><g class="isl-lab" transform="translate(0,27)"><rect x="${-w / 2}" y="-13" width="${w}" height="26" rx="13"/><text y="5">${esc(text)}</text></g>`
      + (warn ? `<g class="isl-badge" transform="translate(${w / 2 - 2},17)"><circle r="9"/><text y="4">${warn}</text></g>` : '') + (META[id].live ? `<circle class="isl-live" cx="${-w / 2 + 2}" cy="27" r="4"/>` : '') + '</a>';
    const body = `<a class="isl-hit isl-body${down ? ' down' : ''}" href="${esc(url)}" data-id="${id}" tabindex="-1" aria-hidden="true" transform="${at}"><g class="isl-lift">${svg}</g></a>`;
    return { body, label };
  }

  function scene() {
    const placed = ids().map((id) => { const [q, r] = SLOTS[id]; return { id, cx: 1.5 * R * q * GAP, cy: Math.sqrt(3) * R * (r + q / 2) * K * GAP }; }).sort((a, b) => a.cy - b.cy || a.cx - b.cx);
    const minX = Math.min(...placed.map((p) => p.cx)) - R - 40, maxX = Math.max(...placed.map((p) => p.cx)) + R + 40;
    const minY = Math.min(...placed.map((p) => p.cy)) - 80, maxY = Math.max(...placed.map((p) => p.cy)) + T + R * K + 60;
    const ripples = [[-.55, .5, 150], [.6, -.35, 190], [.1, 1.05, 130]].map(([fx, fy, rx]) => `<ellipse class="isl-ripple" cx="${minX + (maxX - minX) * (.5 + fx / 2)}" cy="${minY + (maxY - minY) * (.5 + fy / 2)}" rx="${rx}" ry="${rx * .28}"/>`).join('');
    const drawn = placed.map((p, i) => island(p.id, p.cx, p.cy, i));
    return `<svg class="isl-scene" viewBox="${minX} ${minY} ${maxX - minX} ${maxY - minY}" preserveAspectRatio="xMidYMid meet" role="group" aria-label="知識專區群島">${ripples}${drawn.map((d) => d.body).join('')}${drawn.map((d) => d.label).join('')}</svg>`;
  }

  function detail(id) {
    const m = META[id], s = hub.data[id], warn = todo(id);
    const stat = (value, name, tone = '') => `<div class="hub-stat ${tone}"><strong>${s.ok ? num(value) : '—'}</strong><small>${name}</small></div>`;
    const latest = !s.ok ? '暫時無法讀取這個專區的資料' : s.latest ? `最新：${esc(s.latest.title)}（${day(s.latest.time)}）` : '近期沒有更新';
    return `<div class="isl-d1"><p class="isl-eyebrow">${esc(GROUPS[groupIndex(id)].label)}</p><h3>${esc(m.label)} <span class="hub-tag ${m.live ? 'live' : 'demo'}">${m.live ? '即時' : '示範'}</span></h3><p class="isl-tagline">${esc(m.tagline)}</p><p class="hub-latest">${latest}</p><p class="isl-crowd"></p></div>
      <div class="isl-d2"><div class="hub-stats">${stat(s.current, '有效來源檔案')}${stat(s.history, '舊版來源檔案')}${stat(s.week, '本週更新')}${stat(warn, '待處理', s.ok && s.attention.some((a) => a.level === 'warning') ? 'warn' : '')}</div>
      <div class="hub-actions"><a class="primary-button" href="${zoneUrl(id)}">進入專區</a><a class="secondary-button" href="${zoneUrl(id, 'ai')}">直接提問</a></div></div>`;
  }

  /* The markup of the whole block; bind() makes it live once it is in the page. */
  function html() {
    const legend = GROUPS.map((g, i) => `<span><i style="background:${THEMES[i].rim}"></i>${esc(g.label)}</span>`).join('');
    const list = ids().map((id) => `<li><a href="${zoneUrl(id)}"><span class="isl-dot" style="background:${theme(id).rim}"></span><span>${esc(META[id].label)}</span>${todo(id) ? `<em>${todo(id)}</em>` : ''}</a></li>`).join('');
    if (!hub.data[state.selected]) state.selected = 'wifi';
    return `<div class="isl-stage"><div class="isl-map">${scene()}<div class="isl-legend">${legend}</div></div><aside class="isl-detail" aria-live="polite"></aside></div><ul class="isl-list">${list}</ul>`;
  }

  function bind(root) {
    const map = root.querySelector('.isl-map'), side = root.querySelector('.isl-detail'); if (!map || !side) return;
    const show = (id, visit = false) => {
      if (!hub.data[id]) return;
      state.selected = id; side.innerHTML = detail(id);
      map.querySelectorAll('.isl-hit').forEach((n) => n.classList.toggle('on', n.dataset.id === id));
      People.select(id, visit);
    };
    const hot = (e, on) => { const a = e.target.closest && e.target.closest('.isl-hit'); if (a) map.querySelectorAll(`.isl-hit[data-id="${a.dataset.id}"]`).forEach((n) => n.classList.toggle('hot', on)); };
    map.addEventListener('click', (e) => { const a = e.target.closest('.isl-hit'); if (!a) return; e.preventDefault(); show(a.dataset.id, true); });
    map.addEventListener('dblclick', (e) => { const a = e.target.closest('.isl-hit'); if (a) location.assign(a.getAttribute('href')); });
    map.addEventListener('keydown', (e) => { const a = e.target.closest('.isl-hit'); if (a && e.key === ' ') { e.preventDefault(); show(a.dataset.id); } });  // Enter follows the link, Space looks at it
    map.addEventListener('focusin', (e) => { const a = e.target.closest && e.target.closest('.isl-label'); if (a) show(a.dataset.id); });
    map.addEventListener('mouseover', (e) => hot(e, true));
    map.addEventListener('mouseout', (e) => hot(e, false));
    showIsland = show;
    show(state.selected);
    People.attach(map);
    pushStats();
  }

  /* The keeper (a frame on the same page) only needs to know which islands have news; the numbers are the ones the page already shows. */
  function pushStats() {
    const frame = document.querySelector('.hub-assistant-frame');
    if (!frame || !frame.contentWindow) return;
    const stats = {};
    ids().forEach((id) => { const s = hub.data[id]; stats[id] = { week: s.ok ? s.week : 0, todo: todo(id) }; });
    frame.contentWindow.postMessage({ type: 'km-keeper-stats', stats }, location.origin);
  }

  /* "Take me there": select the island, bring it into view and make it bounce a few times. */
  function focus(id) {
    if (!showIsland || !SLOTS[id] || !hub.data[id]) return;
    showIsland(id, true);
    const map = document.querySelector('.isl-map'); if (!map) return;
    map.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    map.querySelectorAll('.isl-hit.pulse').forEach((n) => n.classList.remove('pulse'));
    map.querySelectorAll(`.isl-hit[data-id="${id}"]`).forEach((n) => { void n.getBoundingClientRect(); n.classList.add('pulse'); setTimeout(() => n.classList.remove('pulse'), 2400); });
  }

  window.addEventListener('message', (e) => {
    if (e.origin !== location.origin || !e.data || e.data.type !== 'km-keeper-go' || typeof e.data.zone !== 'string') return;
    focus(e.data.zone);
  });
  document.addEventListener('load', (e) => { if (e.target && e.target.classList && e.target.classList.contains('hub-assistant-frame') && hub.data) pushStats(); }, true);

  return { html, bind, helpers: { esc, hex, shade, geo: (id) => GEO[id] || { bx: 0, by: -14 }, ids, shortName } };
})();
