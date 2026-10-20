"""Webwright：各頁面下拉選單（<select> 與選項）的可讀性驗收（不輸出密碼與 session）。

用法：python scripts/webwright_select_contrast.py RUN_DIR ZONE USER PASS_KEY [--admin-pages]
環境變數見 webwright_wifi8_common.py。

逐頁找出所有 <select>，讀出關閉時與每個選項的實際文字色／背景色，檢查：
  opaque       背景不透明（半透明背景會讓瀏覽器以自己的灰色畫開啟後的清單）
  contrast     文字與背景對比度 ≥ 4.5:1（WCAG AA），包含選取中與停用的選項
  dark         背景夠深（亮度 < 0.2），符合整體深色風格
並把清單展開（size=N）後截圖，供肉眼確認。--admin-pages 另外檢查 /control-admin.html 與 /source-credentials.html（需管理員帳號）。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webwright_wifi8_common import BASE, Run, login_to_wifi, wifi_page  # noqa: E402

SCAN = """() => {
  const parse = (c) => { const m = c.match(/rgba?\\(([^)]+)\\)/); const p = m ? m[1].split(',').map(Number) : [0,0,0,0]; return {r:p[0], g:p[1], b:p[2], a: p.length > 3 ? p[3] : 1}; };
  const lum = ({r,g,b}) => { const f = (v) => { v/=255; return v <= .03928 ? v/12.92 : Math.pow((v+.055)/1.055, 2.4); }; return .2126*f(r)+.7152*f(g)+.0722*f(b); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x,y)+.05)/(Math.min(x,y)+.05); };
  const out = [];
  document.querySelectorAll('select').forEach((s, i) => {
    const cs = getComputedStyle(s); const bg = parse(cs.backgroundColor), fg = parse(cs.color);
    const item = {i, name: s.name || s.id || s.getAttribute('aria-label') || s.className || 'select', visible: !!(s.offsetWidth || s.offsetHeight), disabled: s.disabled,
                  select: {bg: cs.backgroundColor, fg: cs.color, alpha: bg.a, ratio: +ratio(bg, fg).toFixed(2), lum: +lum(bg).toFixed(3)}, options: []};
    s.querySelectorAll('option').forEach((o) => { const oc = getComputedStyle(o); const ob = parse(oc.backgroundColor), of = parse(oc.color);
      item.options.push({text: o.textContent.trim().slice(0, 24), alpha: ob.a, ratio: +ratio(ob, of).toFixed(2), lum: +lum(ob).toFixed(3)}); });
    out.push(item);
  });
  return out;
}"""


def check(run: Run, pg, label: str) -> int:
    pg.wait_for_timeout(800)
    found = pg.evaluate(SCAN)
    bad = []
    for s in found:
        if not s["visible"]:
            continue
        for what, v in [("關閉時", s["select"])] + [(f"選項「{o['text']}」", o) for o in s["options"]]:
            if v["alpha"] < 1 or v["ratio"] < 4.5 or v["lum"] >= 0.2:
                bad.append(f"{s['name']}／{what}：不透明={v['alpha'] == 1}、對比 {v['ratio']}、亮度 {v['lum']}")
    visible = [s for s in found if s["visible"]]
    shown = pg.evaluate("() => { let n = 0; document.querySelectorAll('select').forEach((s) => { if (s.offsetWidth) { s.size = Math.min(Math.max(s.options.length, 2), 8); n++; } }); return n; }")
    ratios = [min([s["select"]["ratio"]] + [o["ratio"] for o in s["options"]]) for s in visible]
    run.act(pg, label, f"{len(visible)} 個下拉選單，最低對比 {min(ratios) if ratios else '—'}:1" + (f"；不合格：{bad[:3]}" if bad else ""), bool(visible) and not bad)
    return len(visible)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("run_dir", "zone", "user", "pass_key"):
        parser.add_argument(name)
    parser.add_argument("--admin-pages", action="store_true")
    args = parser.parse_args()
    run = Run(args.run_dir, args.zone, args.user)
    with wifi_page(run) as pg:
        login_to_wifi(pg, args.zone, args.user, args.pass_key)
        pg.goto(BASE + "/wifi8/#/jobs")
        pg.locator("#summary-notify-hour").wait_for(timeout=15000)
        check(run, pg, "wifi_jobs_time_selects")
        for route in ("documents", "research", "overview"):
            pg.goto(BASE + f"/wifi8/#/{route}")
            pg.wait_for_timeout(1500)
            if pg.locator("select").count():
                check(run, pg, f"wifi_{route}_selects")
        if args.admin_pages:
            for page in ("control-admin.html", "source-credentials.html"):
                pg.goto(BASE + "/" + page)
                pg.wait_for_timeout(2000)
                if pg.locator("select").count():
                    check(run, pg, page.split(".")[0].replace("-", "_") + "_selects")
    return run.finish()


if __name__ == "__main__":
    raise SystemExit(main())
