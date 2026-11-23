"""Zone-permission testbed. Runs the REAL zone routes (with the zone gate), ZoneCatalog and ZoneAgent against the TEST collection, plus the REAL KM Control admin API and admin page
(/control-admin.html) on a throw-away SQLite control store. The accounts alice/bob/carol/dave are test accounts without a usable password: you "sign in" as one of them
from the picker at the top of the test page. The admin account is created by whoever runs the stack (python -m tools.zone_acl_testbed.make_admin), so nobody else types a password.
Nothing here is a KM login and nothing touches the real KM, CSIT or km_control database.
"""
import os
import secrets
import time
import uuid

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.control_auth_routes import router as control_router
from src.csit_integration_v1.zones import PAGE_KEY, ZONES
from src.km_control import ControlRegistry
from src.vector_store import VectorStore
from src.web_api import zone_routes
from src.zone_pages import acl
from src.zone_pages.agent import ZoneAgent
from src.zone_pages.catalog import ZoneCatalog

COLL = os.getenv("KM_ACL_TEST_COLLECTION", "km_acl_test_docs")
TEST_ACCOUNTS = {"alice": "Alice", "bob": "Bob", "carol": "Carol", "dave": "Dave"}
zone_routes.PAGES.setdefault("wifi", "wifi")        # the real KM serves the WiFi zone through /api/wifi8 (not covered yet); the testbed lets the zone routes serve it so it can be tested

registry = ControlRegistry.from_environment()


def seed_accounts():
    have = {u.username for u in registry.list_users()}
    for name in TEST_ACCOUNTS:
        if name not in have:
            u = registry.register(name, secrets.token_urlsafe(24))          # nobody knows this password: these accounts are only reachable through the picker
            with registry._connection() as c:
                c.execute(registry._sql("UPDATE km_users SET status = 'active' WHERE user_id = ?"), (u.user_id,))


seed_accounts()
store = VectorStore()
catalog = ZoneCatalog(store.client, store.encode, sources=((COLL, None, "content", ()),), enforce=True, ttl=2)
zone_routes._catalog = lambda: catalog


def complete(messages):
    key = open(os.environ["KM_CSIT_LLM_API_KEY_FILE"], encoding="utf-8").read().strip()
    r = httpx.post(os.environ["KM_CSIT_LLM_BASE_URL"].rstrip("/") + "/chat/completions", headers={"Authorization": "Bearer " + key}, timeout=90,
                   json={"model": os.environ["KM_CSIT_LLM_MODEL"], "messages": messages, "temperature": 0})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


def users_by_name():
    return {u.username: u for u in registry.list_users() if u.username in TEST_ACCOUNTS}


app = FastAPI(title="zone ACL testbed")


@app.middleware("http")
async def session(request: Request, call_next):
    who = users_by_name().get(request.cookies.get("km_test_user", ""))
    if who:
        request.state.km_identity = {"sub": who.user_id, "instance_id": "acl-test", "role": "user"}
    return await call_next(request)


app.include_router(zone_routes.router)                       # the real /api/zones/{zone}/... routes, with the zone gate
app.include_router(zone_routes.access_router)                # the real /api/zone-access (what the left navigation shows)
app.include_router(control_router, prefix="/_control")       # the real KM Control API, where the admin page lives


@app.get("/testbed/accounts")
def accounts(request: Request):
    me = request.cookies.get("km_test_user")
    users = users_by_name()
    out = {}
    for name, label in TEST_ACCOUNTS.items():
        u = users.get(name)
        try:
            units = registry.units_for(u.user_id) if u else []
        except Exception:  # noqa: BLE001
            units = []
        out[name] = {"label": label, "units": units}
    return {"me": me if me in users else None, "accounts": out, "zones": [{"id": z, "page": PAGE_KEY.get(z, z), "label": n} for z, n in ZONES]}


@app.post("/testbed/login")
async def login(request: Request):
    who = (await request.json()).get("user")
    resp = JSONResponse({"ok": who in TEST_ACCOUNTS})
    if who in TEST_ACCOUNTS:
        resp.set_cookie("km_test_user", who, httponly=True, samesite="strict")
    else:
        resp.delete_cookie("km_test_user")
    return resp


@app.post("/testbed/ask")
async def ask(request: Request):
    who = getattr(request.state, "km_identity", None)
    if not who:
        return JSONResponse({"error": "pick an account first"}, status_code=401)
    body = await request.json()
    question, page = body.get("question", "").strip(), body.get("zone", "")
    try:
        zone_routes._gate(page, request)                      # the same zone gate every real zone route has
        _zone_id, label, names = zone_routes._zone(page)
    except HTTPException as exc:
        return JSONResponse({"error": exc.detail, "status": exc.status_code}, status_code=exc.status_code)
    viewer = acl.viewer_for(who, lookup=acl.control_lookup)
    t0 = time.time()
    result = ZoneAgent(catalog, complete).answer(task_id=str(uuid.uuid4()), zone_label=label, zone_names=names, question=question, history=[],
                                                 owner={"user_id": who["sub"]}, file_records={}, emit=lambda e: None, viewer=viewer)
    result.pop("owner", None)
    result["seconds"] = round(time.time() - t0, 1)
    result["as"] = request.cookies.get("km_test_user")
    result["zone"] = label
    return result


@app.get("/testbed/truth")
def truth():
    """Ground truth for the tester only (NOT permission-filtered): every document in the test collection and the permission stored on it."""
    docs, offset = {}, None
    while True:
        try:
            pts, offset = store.client.scroll(COLL, limit=256, offset=offset, with_payload=True, with_vectors=False)
        except Exception:
            return {"documents": []}
        for p in pts:
            pl = p.payload or {}
            d = docs.setdefault(pl.get("document_file_id") or pl.get("document_id"), {"name": pl.get("doc_name"), "zone": pl.get("topic_zone"), "acl_mode": pl.get("acl_mode"),
                                "acl_version": pl.get("acl_version"), "allowed": pl.get("allowed_principals"), "chunks": 0})
            d["chunks"] += 1
        if offset is None:
            break
    return {"documents": sorted(docs.values(), key=lambda d: (d["zone"] or "", d["name"] or ""))}


PAGE = """<!doctype html><meta charset=utf-8><title>專區與文件權限測試</title>
<style>body{font:15px/1.5 system-ui,'Noto Sans TC',sans-serif;margin:0;background:#16222e;color:#e6edf4}header{padding:12px 20px;background:#1d3144;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.app{display:grid;grid-template-columns:230px 1fr;min-height:calc(100vh - 56px)}@media(max-width:900px){.app{grid-template-columns:1fr}}
nav{background:#12202d;padding:14px 10px}nav h3{margin:6px 8px;font-size:12px;color:#7fffe3;letter-spacing:.1em}nav a{display:block;padding:9px 12px;border-radius:8px;color:#d6e6f2;text-decoration:none;cursor:pointer;margin:2px 0}
nav a:hover{background:#1d3144}nav a.on{background:#e8fbff;color:#06303a;font-weight:700}main{padding:18px 22px;display:grid;grid-template-columns:1fr 1fr;gap:18px;align-content:start}@media(max-width:1100px){main{grid-template-columns:1fr}}
a{color:#8fc4ff}.card{background:#1d3144;border-radius:10px;padding:16px}h2{margin:0 0 10px;font-size:16px}select,input,button,textarea{font:inherit;padding:7px 10px;border-radius:6px;border:1px solid #456;background:#0f1923;color:#e6edf4}
button{background:#2f6fb3;border:0;cursor:pointer}table{width:100%;border-collapse:collapse;font-size:13.5px}td,th{padding:5px 6px;border-bottom:1px solid #2c4258;text-align:left;vertical-align:top}
.mute{color:#9ab}.deny{background:#4a1f24;border:1px solid #b3261e;padding:10px;border-radius:8px}.ok{background:#1b3a2a;border:1px solid #2e8b57;padding:10px;border-radius:8px}.pill{background:#2c4258;border-radius:10px;padding:1px 8px;margin-right:4px;font-size:12px}
.wide{grid-column:1/-1}.s200{color:#6fe3a0}.s403{color:#ff8a80}</style>
<header><b>專區與文件權限測試</b><label>目前帳號 <select id=who onchange=login()></select></label><span id=pr class=mute></span>
<a href="/login.html" target=_blank>管理者登入</a><a href="/control-admin.html" target=_blank>KM 帳號與授權管理頁</a><span class=mute>(測試堆疊 · 不連真實 KM)</span></header>
<div class=app><nav><h3>KM 左側選單(依帳號權限顯示)</h3><div id=side class=mute style="padding:8px">請先選帳號</div></nav>
<main>
<div class=card><h2 id=ztitle>請先在左側選一個專區</h2><div id=docs class=mute></div></div>
<div class=card><h2>在這個專區提問</h2><textarea id=q rows=3 style="width:100%" placeholder="先選專區,再輸入問題"></textarea>
<p><button onclick=ask()>送出問題</button> <span id=st class=mute></span></p><div id=ans></div></div>
<div class="card wide"><h2>強行開啟測試:這個帳號直接呼叫每個專區的結果</h2><div class=mute style="margin-bottom:8px">沒有權限的專區,即使不經過選單、直接輸入網址,也應該被擋下(403)。</div><div id=probe class=mute></div></div>
<div class="card wide"><h2>真實資料(測試用,不受權限限制)</h2><div id=truth class=mute></div></div>
</main></div><script>
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
let A={},ZONES=[],ME=null,CUR=null;
async function init(){const r=await (await fetch('/testbed/accounts')).json();A=r.accounts;ZONES=r.zones;ME=r.me;
 $('who').innerHTML='<option value="">(未登入)</option>'+Object.entries(A).map(([u,a])=>`<option value="${u}" ${r.me===u?'selected':''}>${esc(a.label)}</option>`).join('');await show();truth()}
async function show(){const r=await (await fetch('/testbed/accounts')).json();A=r.accounts;const me=$('who').value||null;ME=me;
 $('pr').innerHTML=me?'所屬單位:'+(A[me].units.length?A[me].units.map(p=>`<span class=pill>${esc(p)}</span>`).join(''):'<span class=mute>(沒有)</span>'):'';await side();probe()}
async function side(){
 if(!ME){$('side').innerHTML='請先選帳號';CUR=null;$('docs').innerHTML='';$('ztitle').textContent='請先在左側選一個專區';return}
 const r=await fetch('/api/zone-access');if(!r.ok){$('side').textContent='未登入';return}
 const z=(await r.json()).zones;
 $('side').innerHTML=z.length?z.map(x=>`<a data-p="${x.page}" class="${CUR===x.page?'on':''}" onclick="pick('${x.page}')">${esc(x.label)}</a>`).join(''):'<div class=deny>這個帳號沒有任何專區的權限,選單是空的。</div>';
 if(CUR&&!z.some(x=>x.page===CUR)){CUR=null;$('docs').innerHTML='';$('ztitle').textContent='請先在左側選一個專區'}
 if(!CUR&&z.length)pick(z[0].page)}
async function pick(p){CUR=p;$('ans').innerHTML='';document.querySelectorAll('#side a').forEach(a=>a.classList.toggle('on',a.dataset.p===p));await docs()}
async function docs(){if(!CUR)return;const z=ZONES.find(x=>x.page===CUR);$('ztitle').textContent=(z?z.label:CUR)+' · 這個帳號看得到的文件';
 const r=await fetch('/api/zones/'+CUR+'/documents');if(!r.ok){$('docs').innerHTML='<div class=deny>'+r.status+' 無法開啟這個專區</div>';return}
 const d=(await r.json()).documents;$('docs').innerHTML=d.length?'<table><tr><th>文件</th><th>類型</th></tr>'+d.map(x=>`<tr><td>${esc(x.title)}</td><td class=mute>${esc(x.document_role||'')}</td></tr>`).join('')+'</table>':'<span class=mute>(這個專區沒有可看的文件)</span>'}
async function probe(){if(!ME){$('probe').textContent='請先選帳號';return}
 const rows=await Promise.all(ZONES.map(async z=>{const r=await fetch('/api/zones/'+z.page+'/documents');let n='';if(r.ok){n=(await r.json()).documents.length+' 份可看'}return `<tr><td>${esc(z.label)}</td><td class="s${r.status}">${r.status}${r.status==403?' 擋下':''}</td><td class=mute>${n}</td></tr>`}));
 $('probe').innerHTML='<table><tr><th>專區</th><th>直接呼叫結果</th><th></th></tr>'+rows.join('')+'</table>'}
async function login(){const u=$('who').value;await fetch('/testbed/login',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({user:u})});$('ans').innerHTML='';CUR=null;await show()}
async function truth(){const d=(await (await fetch('/testbed/truth')).json()).documents;
 $('truth').innerHTML=d.length?'<table><tr><th>專區</th><th>文件</th><th>權限</th><th>可讀的單位</th></tr>'+d.map(x=>`<tr><td>${esc(x.zone)}</td><td>${esc(x.name)}</td><td>${x.acl_mode?esc(x.acl_mode):'<span class=mute>未標示</span>'}</td><td class=mute>${esc((x.allowed||[]).map(k=>k.replace(/^unit:\\|/,'')).join(', '))}</td></tr>`).join('')+'</table>':'<span class=mute>測試資料庫還沒有文件</span>'}
async function ask(){const q=$('q').value.trim();if(!q)return;if(!CUR){$('ans').innerHTML='<div class=deny>請先在左側選專區</div>';return}$('st').textContent='處理中…';$('ans').innerHTML='';
 const r=await fetch('/testbed/ask',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({question:q,zone:CUR})});const d=await r.json();$('st').textContent='';
 if(!r.ok){$('ans').innerHTML='<div class=deny>'+esc(d.error||r.status)+'</div>';return}
 const denied=String(d.stop_reason).startsWith('access_denied');
 $('ans').innerHTML=`<div class="${denied?'deny':'ok'}"><b>${denied?'已拒答(無權限)':'已回答'}</b> · 以 ${esc(d.as)} 身分 · ${esc(d.zone)} · ${d.seconds}s</div><p style="white-space:pre-wrap">${esc(d.answer_main)}</p>`
  +(d.citations.length?'<div class=mute>引用:'+d.citations.map(c=>esc(c.source)).join('、')+'</div>':'')+`<div class=mute>stop_reason: ${esc(d.stop_reason)}</div>`}
init();setInterval(()=>{truth();if(ME){side();probe();docs()}},8000)
</script>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


# the real login page and KM Control admin page (static files of the KM frontend); mounted last so the routes above win
app.mount("/", StaticFiles(directory=os.getenv("KM_ACL_TEST_FRONTEND", "/app/frontend")), name="frontend")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8800, log_level="warning")
