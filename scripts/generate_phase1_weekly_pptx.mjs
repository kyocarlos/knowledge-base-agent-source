import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import PptxGenJS from "pptxgenjs";

const ROOT = process.cwd();
const args = process.argv.slice(2);
const arg = (name) => {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : undefined;
};
const week = arg("--week");
const validateOnly = args.includes("--validate");
const explicitOutput = arg("--output");
if (!week || !/^\d{4}-W\d{2}$/.test(week)) throw new Error("--week 必須為 YYYY-Www");

const base = path.join(ROOT, "docs/km-modernization/progress");
const reportId = `${week}-phase1-v2.6`;
const dataPath = path.join(base, "data", `${reportId}.json`);
const markdownPath = path.join(base, "weekly", `${reportId}.md`);
const historyOutput = path.join(base, "presentations", `AI-KM-Phase1-Weekly-${week}-v2.6.pptx`);
const output = explicitOutput ? path.resolve(explicitOutput) : historyOutput;

const data = JSON.parse(fs.readFileSync(dataPath, "utf8"));
const required = (value, label) => {
  if (value === undefined || value === null || value === "") throw new Error(`缺少必要欄位: ${label}`);
};
const round1 = (value) => Math.round(value * 10) / 10;
const sha256 = (file) => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");

function validate() {
  for (const key of ["schema_version", "report_id", "week", "report_date", "period", "source", "phase", "weights", "work_packages", "weekly_outcomes", "quality_gates", "risks", "decisions", "next_week"]) required(data[key], key);
  if (data.report_id !== reportId || data.week !== week) throw new Error("report_id 或 week 不一致");
  const sourcePath = path.join(ROOT, data.source.path);
  if (!fs.existsSync(sourcePath)) throw new Error(`規劃來源不存在: ${data.source.path}`);
  if (sha256(sourcePath) !== data.source.sha256) throw new Error("v2.6 Excel SHA-256 不一致");
  if (data.source.status !== "present_sha_verified") throw new Error("規劃來源尚未驗證");

  const expectedWeights = { contract: 15, implementation: 35, tests: 25, e2e: 15, delivery: 10 };
  for (const [key, value] of Object.entries(expectedWeights)) if (data.weights[key] !== value) throw new Error(`權重錯誤: ${key}`);
  const ids = data.work_packages.map((wp) => wp.id);
  const expectedIds = ["WP0", "WP1", "WP2", "WP3", "WP4", "WP5", "WP6", "WP7", "WP8"];
  if (JSON.stringify(ids) !== JSON.stringify(expectedIds)) throw new Error("Phase 1 WP 清單或順序錯誤");
  for (const wp of data.work_packages) {
    for (const key of ["id", "title", "owner", "excel_target", "progress", "status"]) required(wp[key], `${wp.id}.${key}`);
    if (wp.scores) {
      const score = Object.values(wp.scores).reduce((sum, value) => sum + value, 0);
      if (score !== wp.progress) throw new Error(`${wp.id} 加權總和 ${score} != ${wp.progress}`);
      for (const [key, value] of Object.entries(wp.scores)) if (value < 0 || value > expectedWeights[key]) throw new Error(`${wp.id}.${key} 超出權重`);
    } else if (wp.progress !== 0) throw new Error(`${wp.id} 無 scores 卻有進度`);
  }
  const phaseProgress = round1(data.work_packages.reduce((sum, wp) => sum + wp.progress, 0) / data.work_packages.length);
  if (phaseProgress !== data.phase.progress) throw new Error(`Phase 1 計算錯誤: ${phaseProgress}`);
  const programProgress = round1(data.work_packages.reduce((sum, wp) => sum + wp.progress, 0) / 15);
  if (programProgress !== data.phase.program_progress) throw new Error(`全計畫計算錯誤: ${programProgress}`);
  const markdown = fs.readFileSync(markdownPath, "utf8");
  for (const token of [`Phase 1：**${data.phase.progress}%**`, `全計畫：**${data.phase.program_progress}%**`, `| WP0 | ${data.work_packages[0].progress}%`, `| WP1 | ${data.work_packages[1].progress}%`, data.source.sha256]) {
    if (!markdown.includes(token)) throw new Error(`Markdown 與 JSON 不一致，缺少: ${token}`);
  }
}

validate();
if (validateOnly) {
  console.log(`validated ${dataPath}`);
  process.exit(0);
}
if (!explicitOutput && fs.existsSync(historyOutput)) throw new Error(`歷史 PPTX 已存在，拒絕覆蓋: ${historyOutput}`);
fs.mkdirSync(path.dirname(output), { recursive: true });

const C = {
  navy: "17324D", teal: "087F8C", green: "2E7D5B", amber: "B16D00", red: "A83B3B",
  ink: "26333D", muted: "667783", light: "F4F7F8", pale: "E7F1F2", white: "FFFFFF", line: "CDD9DE"
};
const pptx = new PptxGenJS();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "AI KM Weekly Reporting";
pptx.company = "Askey";
pptx.subject = `AI KM Phase 1 ${week} weekly progress`;
pptx.title = `AI-KM-Phase1-Weekly-${week}-v2.6`;
pptx.lang = "zh-TW";
pptx.theme = { headFontFace: "Microsoft JhengHei", bodyFontFace: "Microsoft JhengHei", lang: "zh-TW" };
pptx.defineSlideMaster({
  title: "PHASE1",
  background: { color: C.white },
  objects: [
    { rect: { x: 0, y: 0, w: 13.333, h: 0.16, fill: { color: C.teal }, line: { color: C.teal } } },
    { text: { text: `AI KM｜Phase 1｜${week}`, options: { x: 0.55, y: 7.06, w: 5.2, h: 0.2, fontFace: "Microsoft JhengHei", fontSize: 9, color: C.muted, margin: 0 } } }
  ],
  slideNumber: { x: 12.2, y: 7.02, w: 0.5, h: 0.22, fontFace: "Aptos", fontSize: 10, color: C.muted, align: "right" }
});

function heading(slide, title, subtitle = "") {
  slide.addText(title, { x: 0.6, y: 0.42, w: 12.05, h: 0.48, fontFace: "Microsoft JhengHei", fontSize: 25, bold: true, color: C.navy, margin: 0, fit: "shrink" });
  if (subtitle) slide.addText(subtitle, { x: 0.62, y: 0.98, w: 11.9, h: 0.28, fontFace: "Microsoft JhengHei", fontSize: 11, color: C.muted, margin: 0, fit: "shrink" });
}

function panel(slide, x, y, w, h, title, body, accent = C.teal, bodySize = 13) {
  slide.addShape(pptx.ShapeType.rect, { x, y, w, h, fill: { color: C.light }, line: { color: C.line, width: 1 } });
  slide.addShape(pptx.ShapeType.rect, { x, y, w: 0.08, h, fill: { color: accent }, line: { color: accent } });
  slide.addText(title, { x: x + 0.2, y: y + 0.14, w: w - 0.35, h: 0.3, fontFace: "Microsoft JhengHei", fontSize: 16, bold: true, color: accent, margin: 0, fit: "shrink" });
  slide.addText(body, { x: x + 0.2, y: y + 0.57, w: w - 0.35, h: h - 0.7, fontFace: "Microsoft JhengHei", fontSize: bodySize, color: C.ink, margin: 0.03, valign: "top", breakLine: false, fit: "shrink" });
}

function progressBar(slide, label, value, x, y, w, color = C.teal) {
  slide.addText(label, { x, y, w: 2.0, h: 0.27, fontFace: "Microsoft JhengHei", fontSize: 13, bold: true, color: C.ink, margin: 0, fit: "shrink" });
  slide.addShape(pptx.ShapeType.rect, { x: x + 2.05, y: y + 0.04, w: w - 2.95, h: 0.16, fill: { color: "E1E8EB" }, line: { color: "E1E8EB" } });
  if (value > 0) slide.addShape(pptx.ShapeType.rect, { x: x + 2.05, y: y + 0.04, w: (w - 2.95) * value / 100, h: 0.16, fill: { color }, line: { color } });
  slide.addText(`${value}%`, { x: x + w - 0.88, y: y - 0.03, w: 0.86, h: 0.27, fontFace: "Aptos", fontSize: 13, bold: true, color, margin: 0, align: "right", fit: "shrink" });
}

function bulletText(items) {
  return items.map((item) => `• ${item}`).join("\n");
}

const wp0 = data.work_packages[0];
const wp1 = data.work_packages[1];

let slide = pptx.addSlide();
slide.background = { color: C.navy };
slide.addShape(pptx.ShapeType.rect, { x: 0.72, y: 0.95, w: 0.1, h: 4.95, fill: { color: C.teal }, line: { color: C.teal } });
slide.addText("AI KM Phase 1 本週進度", { x: 1.08, y: 1.12, w: 10.8, h: 0.75, fontFace: "Microsoft JhengHei", fontSize: 32, bold: true, color: C.white, margin: 0, fit: "shrink" });
slide.addText(`${week}｜v2.6 來源核對與 WP0/WP1 正式部署`, { x: 1.1, y: 2.03, w: 10.6, h: 0.42, fontFace: "Microsoft JhengHei", fontSize: 19, color: "BFE7EA", margin: 0, fit: "shrink" });
slide.addText(`${data.phase.name}\n報告日期：${data.report_date}\n證據截止：${data.period.cutoff}（${data.period.timezone}）\n${data.period.status}`, { x: 1.1, y: 2.9, w: 9.3, h: 1.65, fontFace: "Microsoft JhengHei", fontSize: 17, color: C.white, margin: 0, fit: "shrink", paraSpaceAfterPt: 6 });
slide.addText(`Phase 1  ${data.phase.progress}%`, { x: 8.8, y: 5.15, w: 3.3, h: 0.5, fontFace: "Microsoft JhengHei", fontSize: 24, bold: true, color: "78D6DA", align: "right", margin: 0 });
slide.addText("1 / 7", { x: 11.85, y: 6.96, w: 0.65, h: 0.22, fontFace: "Aptos", fontSize: 10, color: "AFC1CD", align: "right", margin: 0 });

slide = pptx.addSlide("PHASE1");
heading(slide, "主管摘要", "來源 Gate 已解除；技術 Gate 通過，流程 Gate 尚未關閉");
panel(slide, 0.7, 1.48, 3.75, 1.75, "Phase 1", `${data.phase.progress}%\n${data.phase.duration}｜目標 ${data.phase.planned_end}`, C.teal, 16);
panel(slide, 4.78, 1.48, 3.75, 1.75, "WP0／WP1", `${wp0.progress}%／${wp1.progress}%\n已部署至真實系統`, C.green, 16);
panel(slide, 8.86, 1.48, 3.75, 1.75, "來源基準", `v2.6 Excel 已納管\nSHA ${data.source.sha256.slice(0, 12)}…`, C.navy, 15);
panel(slide, 0.7, 3.65, 11.91, 2.4, "本週結論", bulletText(data.weekly_outcomes), C.amber, 15);

slide = pptx.addSlide("PHASE1");
heading(slide, "Phase 1 範圍與時程", "依 v2.6 Excel：WP0～WP8，Production Ready MVP 12～16 週");
data.work_packages.forEach((wp, index) => {
  const column = index < 5 ? 0 : 1;
  const row = column === 0 ? index : index - 5;
  const x = column === 0 ? 0.75 : 6.85;
  const y = 1.38 + row * 1.06;
  const color = wp.progress > 0 ? C.teal : (wp.id === "WP2" ? C.amber : C.muted);
  slide.addShape(pptx.ShapeType.rect, { x, y, w: 5.75, h: 0.82, fill: { color: wp.progress > 0 ? C.pale : C.light }, line: { color: C.line } });
  slide.addText(`${wp.id}  ${wp.title}`, { x: x + 0.16, y: y + 0.1, w: 3.9, h: 0.25, fontFace: "Microsoft JhengHei", fontSize: 13, bold: true, color, margin: 0, fit: "shrink" });
  slide.addText(`${wp.owner}｜${wp.excel_target}`, { x: x + 0.16, y: y + 0.46, w: 4.3, h: 0.19, fontFace: "Microsoft JhengHei", fontSize: 10, color: C.muted, margin: 0, fit: "shrink" });
  slide.addText(`${wp.progress}%`, { x: x + 4.72, y: y + 0.22, w: 0.78, h: 0.25, fontFace: "Aptos", fontSize: 14, bold: true, color, align: "right", margin: 0 });
});

slide = pptx.addSlide("PHASE1");
heading(slide, `WP0｜${wp0.progress}%`, "FastAPI／REST API 與測試基線｜Excel 目標 2026-08-14");
progressBar(slide, "Contract", wp0.scores.contract / data.weights.contract * 100, 0.8, 1.45, 5.7, C.navy);
progressBar(slide, "Implementation", wp0.scores.implementation / data.weights.implementation * 100, 0.8, 1.92, 5.7, C.teal);
progressBar(slide, "Tests", wp0.scores.tests / data.weights.tests * 100, 0.8, 2.39, 5.7, C.green);
progressBar(slide, "E2E", round1(wp0.scores.e2e / data.weights.e2e * 100), 0.8, 2.86, 5.7, C.amber);
progressBar(slide, "Delivery", wp0.scores.delivery / data.weights.delivery * 100, 0.8, 3.33, 5.7, C.red);
panel(slide, 6.85, 1.42, 5.75, 2.55, "本週證據", bulletText(wp0.evidence), C.teal, 14);
panel(slide, 0.8, 4.35, 11.8, 1.75, "剩餘 Gate", "rollout Draft PR、Reviewer、Merge 與去識別化 Webwright artifact；未完成前保留 6 分 delivery 與 2 分 E2E 缺口。", C.amber, 16);

slide = pptx.addSlide("PHASE1");
heading(slide, `WP1｜${wp1.progress}%`, "Docker／Redis／Celery／環境正式化｜Excel 目標 2026-08-21");
progressBar(slide, "Contract", 100, 0.8, 1.45, 5.7, C.navy);
progressBar(slide, "Implementation", 100, 0.8, 1.92, 5.7, C.teal);
progressBar(slide, "Tests", 100, 0.8, 2.39, 5.7, C.green);
progressBar(slide, "E2E", 100, 0.8, 2.86, 5.7, C.green);
progressBar(slide, "Delivery", wp1.scores.delivery / data.weights.delivery * 100, 0.8, 3.33, 5.7, C.red);
panel(slide, 6.85, 1.42, 5.75, 2.8, "本週證據", bulletText(wp1.evidence), C.green, 14);
panel(slide, 0.8, 4.55, 11.8, 1.55, "實際故障處理", "第一次 cutover 的 /search 500 立即觸發 production rollback；修正 HTTP Request trace propagation、補 regression test，再通過 candidate 與第二次正式部署。", C.amber, 15);

slide = pptx.addSlide("PHASE1");
heading(slide, "Gate、風險與待決策", "技術通過不等於 PR／Review／Merge 流程完成");
data.quality_gates.forEach((gate, index) => {
  const color = gate.status === "阻塞" ? C.red : C.amber;
  panel(slide, 0.72, 1.38 + index * 1.38, 5.9, 1.08, `${gate.id} ${gate.name}｜${gate.status}`, gate.detail, color, 11);
});
panel(slide, 6.86, 1.38, 5.75, 2.2, "主要風險", bulletText(data.risks), C.red, 12);
panel(slide, 6.86, 3.87, 5.75, 2.2, "待主管決策", bulletText(data.decisions), C.amber, 12);

slide = pptx.addSlide("PHASE1");
heading(slide, "下週承諾", "以可下載證據、Contract 與 Gate 為完成單位");
data.next_week.forEach((item, index) => {
  const y = 1.42 + index * 1.23;
  slide.addShape(pptx.ShapeType.ellipse, { x: 0.85, y, w: 0.55, h: 0.55, fill: { color: index < 2 ? C.teal : C.navy }, line: { color: index < 2 ? C.teal : C.navy } });
  slide.addText(String(index + 1), { x: 0.85, y: y + 0.08, w: 0.55, h: 0.22, fontFace: "Aptos", fontSize: 14, bold: true, color: C.white, align: "center", margin: 0 });
  slide.addText(item, { x: 1.7, y: y - 0.02, w: 10.65, h: 0.58, fontFace: "Microsoft JhengHei", fontSize: 18, bold: index < 2, color: C.ink, margin: 0, fit: "shrink" });
});
slide.addShape(pptx.ShapeType.rect, { x: 0.9, y: 6.25, w: 11.5, h: 0.52, fill: { color: C.pale }, line: { color: C.line } });
slide.addText("完成定義：Evidence 可下載、PR 有 reviewer、Gate 狀態明確；WP2 Contract 未取得前不開始正式實作。", { x: 1.1, y: 6.37, w: 11.1, h: 0.22, fontFace: "Microsoft JhengHei", fontSize: 13, bold: true, color: C.navy, align: "center", margin: 0, fit: "shrink" });

await pptx.writeFile({ fileName: output });
if (!fs.existsSync(output) || fs.statSync(output).size === 0) throw new Error("PPTX 產生失敗或為空檔");
console.log(`generated ${output}`);
