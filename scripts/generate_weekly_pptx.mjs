import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import PptxGenJS from "pptxgenjs";

const ROOT = process.cwd();
const args = process.argv.slice(2);
const getArg = (name) => {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : undefined;
};
const week = getArg("--week");
const validateOnly = args.includes("--validate");
const explicitOutput = getArg("--output");
if (!week || !/^\d{4}-W\d{2}$/.test(week)) throw new Error("--week 必須為 YYYY-Www");

const base = path.join(ROOT, "docs/km-modernization/progress");
const dataPath = path.join(base, "data", `${week}.json`);
const weeklyPath = path.join(base, "weekly", `${week}.md`);
const historyOutput = path.join(base, "presentations", `AI-KM-Weekly-${week}.pptx`);
const output = explicitOutput ? path.resolve(explicitOutput) : historyOutput;
const templateOutput = path.join(base, "templates", "weekly-report-template.pptx");

const required = (value, label) => {
  if (value === undefined || value === null || value === "") throw new Error(`缺少必要欄位: ${label}`);
};
const round1 = (value) => Math.round(value * 10) / 10;
const data = JSON.parse(fs.readFileSync(dataPath, "utf8"));

function hasTraditionalDeliveryEvidence(wp) {
  return Boolean(wp.pr && wp.tests && wp.acceptance && wp.merged === true);
}

function hasCanonicalIntegrationEvidence(wp) {
  const integration = wp.integration;
  if (!wp.pr || wp.tests !== true || wp.acceptance !== true || wp.production_gate !== "PASS" || !integration) return false;
  if (integration.status !== "completed" || integration.method !== "fast-forward") return false;
  if (!integration.target_branch || !/^[0-9a-f]{40}$/.test(integration.target_sha || "")) return false;
  if (!integration.evidence_path) return false;
  const compare = integration.compare;
  if (!compare || !["identical", "equivalent"].includes(compare.status)) return false;
  return compare.ahead_by === 0 && compare.behind_by === 0;
}

function validate() {
  for (const key of ["schema_version", "source_baseline", "source_baseline_path", "source_baseline_status", "week", "report_date", "period", "positioning", "current_phase", "weights", "work_packages", "phase_progress", "program_progress", "weekly_outcomes", "quality", "risks", "decisions", "next_week"]) required(data[key], key);
  if (data.week !== week) throw new Error(`week 不一致: ${data.week}`);
  const expectedWeights = { contract: 15, implementation: 35, tests: 25, e2e: 15, delivery: 10 };
  for (const [key, value] of Object.entries(expectedWeights)) if (data.weights[key] !== value) throw new Error(`權重錯誤: ${key}`);
  if (data.work_packages.length !== 15) throw new Error("WP 必須為 15 個（WP10A/WP10B 分開）");
  const ids = data.work_packages.map((wp) => wp.id);
  const expectedIds = ["WP0","WP1","WP2","WP3","WP4","WP5","WP6","WP7","WP8","WP9","WP10A","WP10B","WP11","WP12","WP13"];
  if (JSON.stringify(ids) !== JSON.stringify(expectedIds)) throw new Error("WP 清單或順序錯誤");
  for (const wp of data.work_packages.slice(0, 2)) {
    for (const key of ["branch", "head_sha", "slide_evidence"]) required(wp[key], `${wp.id}.${key}`);
    if (!/^[0-9a-f]{40}$/.test(wp.head_sha)) throw new Error(`${wp.id}.head_sha 格式錯誤`);
    if (!Array.isArray(wp.slide_evidence) || wp.slide_evidence.length === 0) throw new Error(`${wp.id}.slide_evidence 必須為非空陣列`);
  }
  for (const wp of data.work_packages) {
    if (wp.scores) {
      const score = Object.values(wp.scores).reduce((sum, value) => sum + value, 0);
      if (score !== wp.progress) throw new Error(`${wp.id} 加權總和 ${score} != progress ${wp.progress}`);
      for (const [key, value] of Object.entries(wp.scores)) if (value < 0 || value > expectedWeights[key]) throw new Error(`${wp.id}.${key} 超出權重`);
    } else if (wp.progress !== 0) throw new Error(`${wp.id} 無 scores 卻有進度`);
    if (wp.progress === 100 && !hasTraditionalDeliveryEvidence(wp) && !hasCanonicalIntegrationEvidence(wp)) {
      throw new Error(`${wp.id} 缺傳統 merge 或 canonical integration delivery evidence，不得為 100`);
    }
  }
  for (let phase = 1; phase <= 5; phase += 1) {
    const members = data.work_packages.filter((wp) => wp.phase === phase);
    const calculated = round1(members.reduce((sum, wp) => sum + wp.progress, 0) / members.length);
    if (calculated !== data.phase_progress[String(phase)]) throw new Error(`Phase ${phase} 計算錯誤: ${calculated}`);
  }
  const program = round1(data.work_packages.reduce((sum, wp) => sum + wp.progress, 0) / data.work_packages.length);
  if (program !== data.program_progress) throw new Error(`全計畫進度錯誤: ${program}`);
  const weekly = fs.readFileSync(weeklyPath, "utf8");
  for (const token of [`**${data.program_progress}%**`, `**${data.phase_progress["1"]}%**`, `| WP0 | ${data.work_packages[0].progress}%`, `| WP1 | ${data.work_packages[1].progress}%`]) {
    if (!weekly.includes(token)) throw new Error(`Markdown 與 JSON 不一致，缺少: ${token}`);
  }
  return true;
}

validate();
if (validateOnly) {
  console.log(`validated ${dataPath}`);
  process.exit(0);
}
if (!explicitOutput && fs.existsSync(historyOutput)) throw new Error(`歷史 PPTX 已存在，拒絕覆蓋: ${historyOutput}`);
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.mkdirSync(path.dirname(templateOutput), { recursive: true });

const C = { navy:"17324D", teal:"087F8C", cyan:"DDEFF1", green:"2E7D5B", amber:"B16D00", red:"A83B3B", ink:"26333D", muted:"667783", light:"F4F7F8", white:"FFFFFF", line:"CDD9DE" };
const pptx = new PptxGenJS();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "AI KM Weekly Reporting";
pptx.subject = `AI KM ${week} weekly report`;
pptx.title = `AI-KM-Weekly-${week}`;
pptx.company = "Askey";
pptx.lang = "zh-TW";
pptx.theme = { headFontFace:"Microsoft JhengHei", bodyFontFace:"Microsoft JhengHei", lang:"zh-TW" };
pptx.defineSlideMaster({
  title: "WEEKLY",
  background: { color: C.white },
  objects: [
    { rect: { x:0, y:0, w:13.333, h:0.18, fill:{color:C.teal}, line:{color:C.teal} } },
    { text: { text:`AI KM｜${week}`, options:{x:0.55,y:7.08,w:4.5,h:0.22,fontFace:"Microsoft JhengHei",fontSize:9,color:C.muted,margin:0} } }
  ],
  slideNumber: { x:12.2, y:7.02, w:0.5, h:0.25, fontFace:"Aptos", fontSize:10, color:C.muted, align:"right" }
});

function title(slide, heading, sub="") {
  slide.addText(heading, {x:0.6,y:0.45,w:12.1,h:0.48,fontFace:"Microsoft JhengHei",fontSize:25,bold:true,color:C.navy,margin:0,breakLine:false,fit:"shrink"});
  if (sub) slide.addText(sub, {x:0.62,y:1.02,w:11.9,h:0.3,fontFace:"Microsoft JhengHei",fontSize:11,color:C.muted,margin:0,fit:"shrink"});
}
function box(slide, x,y,w,h, heading, body, accent=C.teal) {
  slide.addShape(pptx.ShapeType.roundRect,{x,y,w,h,rectRadius:0.04,fill:{color:C.light},line:{color:C.line,width:1}});
  slide.addShape(pptx.ShapeType.rect,{x,y,w:0.08,h,fill:{color:accent},line:{color:accent}});
  slide.addText(heading,{x:x+0.2,y:y+0.17,w:w-0.35,h:0.3,fontFace:"Microsoft JhengHei",fontSize:16,bold:true,color:accent,margin:0,fit:"shrink"});
  slide.addText(body,{x:x+0.2,y:y+0.62,w:w-0.35,h:h-0.78,fontFace:"Microsoft JhengHei",fontSize:13,color:C.ink,margin:0.02,breakLine:false,fit:"shrink",valign:"top"});
}
function progress(slide, label, value, x,y,w, color=C.teal) {
  slide.addText(label,{x,y,w:2.0,h:0.28,fontFace:"Microsoft JhengHei",fontSize:13,bold:true,color:C.ink,margin:0,fit:"shrink"});
  slide.addShape(pptx.ShapeType.rect,{x:x+2.05,y:y+0.03,w:w-2.75,h:0.18,fill:{color:"E4EAED"},line:{color:"E4EAED"}});
  if (value > 0) slide.addShape(pptx.ShapeType.rect,{x:x+2.05,y:y+0.03,w:(w-2.75)*value/100,h:0.18,fill:{color},line:{color}});
  slide.addText(`${value}%`,{x:x+w-0.62,y:y-0.03,w:0.6,h:0.28,fontFace:"Aptos",fontSize:13,bold:true,color,margin:0,align:"right"});
}
function bullets(slide, items, x,y,w,h, size=15) {
  slide.addText(items.map((text)=>({text,options:{bullet:{indent:14},breakLine:true,hanging:3}})),{x,y,w,h,fontFace:"Microsoft JhengHei",fontSize:size,color:C.ink,margin:0.04,paraSpaceAfterPt:9,breakLine:false,fit:"shrink"});
}

let s = pptx.addSlide("WEEKLY");
s.background = {color:C.navy};
s.addShape(pptx.ShapeType.rect,{x:0,y:0,w:13.333,h:7.5,fill:{color:C.navy},line:{color:C.navy}});
s.addShape(pptx.ShapeType.rect,{x:0.7,y:1.0,w:0.11,h:4.7,fill:{color:C.teal},line:{color:C.teal}});
s.addText("AI KM 改善進度週報",{x:1.05,y:1.1,w:10.9,h:0.7,fontFace:"Microsoft JhengHei",fontSize:32,bold:true,color:C.white,margin:0,fit:"shrink"});
s.addText(`${week}｜${data.positioning}`,{x:1.08,y:2.0,w:10.6,h:0.45,fontFace:"Microsoft JhengHei",fontSize:20,color:"BFE7EA",margin:0});
s.addText(`${data.current_phase}\n報告日期：${data.report_date}\n統計期間：${data.period.start}～${data.period.cutoff}（${data.period.timezone}）`,{x:1.08,y:3.0,w:8.9,h:1.45,fontFace:"Microsoft JhengHei",fontSize:18,color:C.white,margin:0,breakLine:false,fit:"shrink",paraSpaceAfterPt:8});
s.addText(`全計畫 ${data.program_progress}%`,{x:9.8,y:4.7,w:2.5,h:0.55,fontFace:"Microsoft JhengHei",fontSize:24,bold:true,color:"78D6DA",align:"right",margin:0});
s.addText("1 / 7",{x:11.8,y:6.95,w:0.7,h:0.25,fontFace:"Aptos",fontSize:10,color:"AFC1CD",align:"right",margin:0});

s = pptx.addSlide("WEEKLY"); title(s,"主管摘要","本週結論：Phase 1 已有前置實作成果，但 Gate 尚未正式關閉");
box(s,0.65,1.55,3.8,2.0,"全計畫",`${data.program_progress}%\n${data.source_baseline}`,C.navy);
box(s,4.75,1.55,3.8,2.0,"Phase 1",`${data.phase_progress["1"]}%\nWP0 ${data.work_packages[0].progress}%｜WP1 ${data.work_packages[1].progress}%`,C.teal);
box(s,8.85,1.55,3.8,2.0,"主管關注",data.risks.slice(0,2).join("\n"),C.amber);
bullets(s,data.weekly_outcomes,0.9,4.15,11.6,1.95,16);

s = pptx.addSlide("WEEKLY"); title(s,"Phase 1～5 總進度","規劃完成不等於實作完成；Phase 分數由所屬 WP 平均");
const phaseNames=["Phase 1 AI KM MVP","Phase 2 Compile-Time RAG","Phase 3 Agentic RAG","Phase 4 AI Analysis","Phase 5 Enterprise Evolution"];
phaseNames.forEach((name,index)=>progress(s,name,data.phase_progress[String(index+1)],0.9,1.55+index*0.82,11.5,index===0?C.teal:C.muted));
s.addText(`全計畫進度 ${data.program_progress}%（15 個 WP 等權平均）`,{x:0.9,y:6.15,w:11.5,h:0.42,fontFace:"Microsoft JhengHei",fontSize:18,bold:true,color:C.navy,align:"center",margin:0});

s = pptx.addSlide("WEEKLY"); title(s,"本週 WP 成果","只呈現有 commit、PR、CI 或驗收證據的工作");
const wp0 = data.work_packages[0];
const wp1 = data.work_packages[1];
box(s,0.7,1.5,5.8,3.55,`${wp0.id}｜${wp0.progress}%`,`${wp0.title}\n• head ${wp0.head_sha.slice(0,8)}\n• ${wp0.slide_evidence.join("\n• ")}`,C.amber);
box(s,6.83,1.5,5.8,3.55,`${wp1.id}｜${wp1.progress}%`,`${wp1.title}\n• head ${wp1.head_sha.slice(0,8)}\n• ${wp1.slide_evidence.join("\n• ")}`,C.teal);
s.addText("WP2～WP13：0%｜依 v2.6 新 WP 對應，無實作證據",{x:1.0,y:5.55,w:11.3,h:0.48,fontFace:"Microsoft JhengHei",fontSize:19,bold:true,color:C.muted,align:"center",margin:0});

s = pptx.addSlide("WEEKLY"); title(s,"Gate 與品質狀態","Gate 未通過，不以程式存在或單一測試成功替代");
data.quality.forEach((item,index)=>box(s,0.75,1.5+index*1.55,11.8,1.18,`${item.gate}｜${item.status}`,item.detail,item.status==="阻塞"?C.red:(item.status==="條件通過"?C.amber:C.muted)));

s = pptx.addSlide("WEEKLY"); title(s,"風險與待主管決策","本週需要明確 owner 與 Gate 判定");
box(s,0.7,1.45,5.85,4.75,"主要風險",data.risks.map((x,i)=>`${i+1}. ${x}`).join("\n\n"),C.red);
box(s,6.8,1.45,5.85,4.75,"待主管決策",data.decisions.map((x,i)=>`${i+1}. ${x}`).join("\n\n"),C.amber);

s = pptx.addSlide("WEEKLY"); title(s,"下週承諾","承諾以可驗證輸出與 Gate 為單位");
data.next_week.forEach((item,index)=>{
  const y=1.45+index*1.25;
  s.addShape(pptx.ShapeType.ellipse,{x:0.9,y,w:0.55,h:0.55,fill:{color:index<2?C.teal:C.navy},line:{color:index<2?C.teal:C.navy}});
  s.addText(String(index+1),{x:0.9,y:y+0.07,w:0.55,h:0.25,fontFace:"Aptos",fontSize:14,bold:true,color:C.white,align:"center",margin:0});
  s.addText(item,{x:1.7,y:y-0.02,w:10.6,h:0.58,fontFace:"Microsoft JhengHei",fontSize:18,bold:index<2,color:C.ink,margin:0,fit:"shrink"});
});
s.addText("下週完成定義：有 commit、測試、Evidence、PR/Gate 狀態，且 W34 JSON／Markdown／PPTX 數字一致。",{x:0.95,y:6.35,w:11.5,h:0.38,fontFace:"Microsoft JhengHei",fontSize:13,color:C.muted,align:"center",margin:0});

await pptx.writeFile({ fileName: output });
if (!fs.existsSync(output) || fs.statSync(output).size === 0) throw new Error("PPTX 產生失敗或為空檔");

if (!fs.existsSync(templateOutput)) {
  const template = new PptxGenJS();
  template.layout = "LAYOUT_WIDE";
  template.author = "AI KM Weekly Reporting";
  template.theme = pptx.theme;
  for (let i=1;i<=7;i+=1) {
    const slide=template.addSlide(); slide.background={color:C.white};
    slide.addShape(template.ShapeType.rect,{x:0,y:0,w:13.333,h:0.18,fill:{color:C.teal},line:{color:C.teal}});
    slide.addText(`第 ${i} 頁標題`,{x:0.6,y:0.5,w:11.8,h:0.5,fontFace:"Microsoft JhengHei",fontSize:25,bold:true,color:C.navy,margin:0});
    slide.addText("內容由 data/YYYY-Www.json 與 generate_weekly_pptx.mjs 產生",{x:0.8,y:1.5,w:11.5,h:0.4,fontFace:"Microsoft JhengHei",fontSize:16,color:C.muted,align:"center",margin:0});
    slide.addText(`${i} / 7`,{x:11.8,y:7.0,w:0.7,h:0.25,fontFace:"Aptos",fontSize:10,color:C.muted,align:"right",margin:0});
  }
  await template.writeFile({ fileName: templateOutput });
}
console.log(`generated ${output}`);
