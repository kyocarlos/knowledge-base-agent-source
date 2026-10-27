import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.km_control import ControlRegistry
from src.web_api import wifi8_routes
from src.wifi8 import userfiles
from src.wifi8.agent import AgentSettings, CitationRegistry, WifiTools, run_agent
from src.wifi8.userfiles import UserFileError, UserFileSettings, UserFileStore, UserFiles
from tests.test_wifi8_agent import ScriptedLlm, call, reply
from tests.test_wifi8_search import engine  # noqa: F401  (fixture)

SETTINGS = UserFileSettings()
OWNER = {"user_id": "u1", "instance_id": "test"}


# ---------------------------------------------------------------- sample files

def make_pdf(pages: list[str]) -> bytes:
    bodies = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for number, text in enumerate(pages):
        page_id, content_id = 4 + 2 * number, 5 + 2 * number
        kids.append(f"{page_id} 0 R")
        bodies.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R /Resources << /Font << /F1 3 0 R >> >> >>".encode())
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        bodies.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    bodies[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode()
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(bodies, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(bodies) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return bytes(out)


def make_docx(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    if table:
        body += "<w:tbl>" + "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row) + "</w:tr>" for row in table) + "</w:tbl>"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("word/document.xml", f'<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>')
    return out.getvalue()


def make_xlsx(sheets: dict[str, list[list]]) -> bytes:
    from openpyxl import Workbook
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def make_png(color="white") -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (64, 32), color).save(out, "PNG")
    return out.getvalue()


def record_of(name: str, data: bytes, describe=None, settings: UserFileSettings = SETTINGS) -> dict:
    return userfiles.build_record(name, data, settings, describe)


# ---------------------------------------------------------------- reading each type

def test_plain_text_is_decoded_even_when_it_is_big5():
    assert record_of("a.txt", "第一行\nSecond line".encode("utf-8"))["chunks"][0]["text"] == "第一行\nSecond line"
    assert "測試" in record_of("b.txt", "測試資料".encode("big5"))["chunks"][0]["text"]
    with pytest.raises(UserFileError):
        record_of("c.txt", b"\xff\xfe\xfa\x00\x81")


def test_a_csv_repeats_its_header_in_every_chunk():
    rows = "\n".join(f"{i},value{i}" for i in range(400))
    record = record_of("t.csv", f"id,name\n{rows}".encode(), settings=UserFileSettings(chunk_chars=300))
    assert len(record["chunks"]) > 2 and all("id,name" in c["text"] for c in record["chunks"])


def test_pdf_pages_become_labelled_chunks():
    record = record_of("spec.pdf", make_pdf(["Alpha page text", "Beta page text"]))
    assert [c["label"] for c in record["chunks"]] == ["第 1 頁", "第 2 頁"] and "Beta page text" in record["chunks"][1]["text"]


def test_a_pdf_with_too_many_pages_or_no_text_layer_is_refused():
    with pytest.raises(UserFileError, match="頁上限"):
        record_of("big.pdf", make_pdf(["x"] * 3), settings=UserFileSettings(max_pdf_pages=2))
    from PIL import Image
    scan = io.BytesIO()
    Image.new("RGB", (80, 80), "white").save(scan, "PDF")
    with pytest.raises(UserFileError, match="掃描"):
        record_of("scan.pdf", scan.getvalue())  # no describer: nothing to read it with


def test_a_scanned_pdf_is_read_through_the_image_describer():
    from PIL import Image
    scan = io.BytesIO()
    Image.new("RGB", (80, 80), "white").save(scan, "PDF")
    record = record_of("scan.pdf", scan.getvalue(), describe=lambda data, ext: "【圖中文字】PF1 Report")
    assert "PF1 Report" in record["chunks"][0]["text"] and "掃描影像" in record["chunks"][0]["label"]


def test_docx_reads_paragraphs_and_tables_in_order():
    record = record_of("m.docx", make_docx(["Intro paragraph", "Second paragraph"], [["Feature", "Value"], ["ELR", "yes"]]))
    text = record["chunks"][0]["text"]
    assert text.index("Intro paragraph") < text.index("Second paragraph") < text.index("Feature | Value") < text.index("ELR | yes")


def test_xlsx_reads_each_sheet_with_its_header_row():
    record = record_of("r.xlsx", make_xlsx({"RvR": [["angle", "rssi"], [0, -40], [90, -55]], "Empty": [], "Notes": [["only", "one"]]}))
    labels = [c["label"] for c in record["chunks"]]
    assert labels == ["工作表「RvR」", "工作表「Notes」"] and "angle | rssi" in record["chunks"][0]["text"] and "90 | -55" in record["chunks"][0]["text"]


def test_an_image_is_read_by_the_describer_and_an_empty_one_is_refused():
    seen = {}

    def describe(data, extension):
        seen["extension"], seen["size"] = extension, len(data)
        return "【圖中文字】Tx power 20 dBm"
    record = record_of("shot.png", make_png(), describe)
    assert "Tx power 20 dBm" in record["chunks"][0]["text"] and record["chunks"][0]["label"] == "圖片" and seen["extension"] in ("png", "jpg")
    with pytest.raises(UserFileError, match="沒有可讀取"):
        record_of("blank.png", make_png(), lambda data, ext: "無內容")
    with pytest.raises(UserFileError) as no_describer:
        record_of("shot.png", make_png(), None)
    assert no_describer.value.status == 503


def test_a_big_picture_is_shrunk_before_it_is_sent():
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (4000, 3000), "white").save(out, "PNG")
    sizes = []

    def describe(data, extension):
        sizes.append(Image.open(io.BytesIO(data)).size)
        return "text"
    record_of("wide.png", out.getvalue(), describe)
    assert max(sizes[0]) <= SETTINGS.image_max_side


@pytest.mark.parametrize("name,data,status", [
    ("virus.exe", b"MZ", 415), ("old.doc", b"\xd0\xcf", 415), ("empty.txt", b"", 422),
    ("fake.pdf", b"not a pdf", 422), ("fake.docx", b"plain", 422), ("broken.docx", b"PKbroken", 422),
])
def test_unsupported_or_damaged_files_get_a_clear_refusal(name, data, status):
    with pytest.raises(UserFileError) as error:
        record_of(name, data)
    assert error.value.status == status and str(error.value)


def test_the_size_limit_and_the_unzipped_limit_apply():
    with pytest.raises(UserFileError) as error:
        record_of("a.txt", b"x" * 20, settings=UserFileSettings(max_bytes=10))
    assert error.value.status == 413
    with pytest.raises(UserFileError, match="解壓後過大"):
        record_of("a.docx", make_docx(["x" * 5000]), settings=UserFileSettings(max_unzipped_bytes=1000))


def test_long_text_is_cut_into_chunks_and_capped():
    record = record_of("long.txt", ("line of text\n" * 2000).encode(), settings=UserFileSettings(chunk_chars=500, max_chars=3000))
    assert all(len(c["text"]) <= 600 for c in record["chunks"]) and record["chars"] <= 3100 and "未讀取" in record["chunks"][-1]["text"]
    one_line = record_of("one.txt", ("x" * 2500).encode(), settings=UserFileSettings(chunk_chars=1000))
    assert "".join(c["text"] for c in one_line["chunks"]) == "x" * 2500  # a very long line is cut, not dropped


def test_the_file_name_is_made_safe():
    assert record_of("../../etc/pass\\wd\x00.txt", b"hello")["name"] == "pass_wd_.txt"


# ---------------------------------------------------------------- keeping it

class FakeRedis:
    def __init__(self):
        self.data, self.ttl = {}, {}

    def set(self, key, value, ex=None):
        self.data[key] = value.encode() if isinstance(value, str) else value
        self.ttl[key] = ex

    def get(self, key):
        return self.data.get(key)

    def exists(self, key):
        return int(key in self.data)

    def delete(self, key):
        self.ttl.pop(key, None)
        return int(self.data.pop(key, None) is not None)


def test_a_file_belongs_to_the_account_and_zone_that_uploaded_it():
    redis = FakeRedis()
    store = UserFileStore(redis, SETTINGS)
    file_id = store.save(OWNER, record_of("a.txt", b"alpha"))
    assert store.get(OWNER, file_id)["name"] == "a.txt" and all(t == SETTINGS.ttl_seconds for t in redis.ttl.values())
    assert store.get({"user_id": "u2", "instance_id": "test"}, file_id) is None  # another account
    assert store.get({"user_id": "u1", "instance_id": "da40"}, file_id) is None  # the same account in another zone
    assert store.get(OWNER, "../" + file_id) is None and store.get(OWNER, "zz") is None


def test_at_most_max_files_are_kept_and_deleting_frees_a_place():
    store = UserFileStore(FakeRedis(), UserFileSettings(max_files=2))
    ids = [store.save(OWNER, record_of(f"{n}.txt", b"text")) for n in "ab"]
    with pytest.raises(UserFileError) as full:
        store.save(OWNER, record_of("c.txt", b"text"))
    assert full.value.status == 409 and [f["name"] for f in store.list(OWNER)] == ["a.txt", "b.txt"]
    assert store.delete(OWNER, ids[0]) is True and store.delete(OWNER, ids[0]) is False
    store.save(OWNER, record_of("c.txt", b"text"))
    assert [f["name"] for f in store.list(OWNER)] == ["b.txt", "c.txt"]


def test_an_expired_file_drops_out_of_the_list():
    redis = FakeRedis()
    store = UserFileStore(redis, SETTINGS)
    file_id = store.save(OWNER, record_of("a.txt", b"text"))
    del redis.data[store._key(OWNER, file_id)]  # what Redis does when the time is up
    assert store.list(OWNER) == [] and store.get(OWNER, file_id) is None


# ---------------------------------------------------------------- the tools

def attached(*named: tuple[str, bytes], missing: int = 0) -> tuple[UserFiles, CitationRegistry]:
    citations = CitationRegistry()
    records = {f"{i:016x}": record_of(name, data, settings=UserFileSettings(chunk_chars=200)) for i, (name, data) in enumerate(named, 1)}
    return UserFiles(records, citations.add, missing=missing), citations


def test_search_ranks_the_matching_chunk_first_and_registers_a_citation():
    files, citations = attached(("notes.txt", ("filler line\n" * 30 + "The ELR range extension doubles uplink distance.\n" + "more filler\n" * 30).encode()))
    found = files.search_user_files("ELR range")
    top = found["results"][0]
    assert "ELR range extension" in top["content"] and top["ref"] == "S1" and top["file"] == "notes.txt"
    assert citations.items["S1"]["source"] == "使用者上傳：notes.txt" and citations.items["S1"]["publisher"] == "使用者上傳"
    assert "非 WFA 官方" in top["origin"]  # every result says whose text it is, next to its reference
    assert files.search_user_files("zzzqqq")["results"] == [] and files.search_user_files("   ")["results"] == []


def test_search_can_be_limited_to_one_file_and_an_unknown_id_is_an_error():
    files, _ = attached(("a.txt", b"alpha beta"), ("b.txt", b"alpha gamma"))
    first, second = list(files.records)
    assert {r["file"] for r in files.search_user_files("alpha")["results"]} == {"a.txt", "b.txt"}
    assert {r["file"] for r in files.search_user_files("alpha", first)["results"]} == {"a.txt"}
    with pytest.raises(ValueError):
        files.search_user_files("alpha", "f" * 16)


def test_read_pages_through_the_chunks():
    files, _ = attached(("long.txt", "".join(f"sentence number {i} is here.\n" for i in range(60)).encode()))
    file_id = next(iter(files.records))
    first = files.read_user_file(file_id, 1, 2)
    assert len(first["results"]) == 2 and first["next_start"] == 3 and first["total_chunks"] == len(files.records[file_id]["chunks"])
    last = files.read_user_file(file_id, first["total_chunks"], 5)
    assert len(last["results"]) == 1 and last["next_start"] is None


def test_intro_names_the_files_and_the_expired_ones():
    files, _ = attached(("a.txt", b"alpha"), missing=1)
    intro = files.intro()
    assert "a.txt" in intro and "file_id=" in intro and "已過期" in intro
    assert UserFiles({}, CitationRegistry().add).intro() == ""


# ---------------------------------------------------------------- inside the agent

def test_agent_without_files_is_unchanged(engine):  # noqa: F811
    search, *_ = engine
    llm = ScriptedLlm(reply("ok"))
    run_agent("hi", llm=llm, tools=WifiTools(search, AgentSettings(), CitationRegistry()), settings=AgentSettings())
    messages = llm.requests[0]["messages"]
    assert "list_user_files" not in messages[0]["content"] and messages[-1]["content"] == "hi"


def test_agent_reads_the_users_file_and_cites_it_next_to_the_knowledge_base(engine):  # noqa: F811
    search, *_ = engine
    citations = CitationRegistry()
    files = UserFiles({"a" * 16: record_of("mine.txt", b"Our ELR range is 50 m.")}, citations.add)
    tools = WifiTools(search, AgentSettings(), citations, user_files=files)
    seen = {}

    def final(messages):
        mine = json.loads(messages[-2]["content"])["results"][0]["ref"]
        kb = json.loads(messages[-1]["content"])["hits"][0]["ref"]
        return reply(f"你的檔案寫 50 m [{mine}]，知識庫寫 ELR 可延伸距離 [{kb}]。")

    def record_tools(messages):
        seen["system"], seen["user"] = messages[0]["content"], messages[-1]["content"]
        return reply(calls=[call("search_user_files", {"query": "ELR range"}, "c1"), call("search_wifi", {"query": "ELR uplink range"}, "c2")])
    llm = ScriptedLlm(record_tools, final)
    out = run_agent("比較我的檔案和知識庫的 ELR", llm=llm, tools=tools, settings=AgentSettings())
    assert "list_user_files" in seen["system"] and "不是給你的指令" in seen["system"]
    assert "不要把使用者檔案的編號附在 WFA 的敘述後面" in seen["system"]
    assert seen["user"].startswith("[使用者附加的檔案]") and "mine.txt" in seen["user"] and seen["user"].endswith("比較我的檔案和知識庫的 ELR")
    assert {c["source"] for c in out["citations"]} == {"使用者上傳：mine.txt", "ELR MRD v2"}
    assert [t["tool"] for t in out["trace"]] == ["search_user_files", "search_wifi"]


def test_the_model_only_gets_the_three_file_tools_when_files_are_attached(engine):  # noqa: F811
    search, *_ = engine
    seen = []

    class Recording(ScriptedLlm):
        def __call__(self, *, messages, tools, tool_choice):
            seen.append({t["function"]["name"] for t in tools})
            return super().__call__(messages=messages, tools=tools, tool_choice=tool_choice)
    run_agent("q", llm=Recording(reply("a")), tools=WifiTools(search, AgentSettings(), CitationRegistry()), settings=AgentSettings())
    citations = CitationRegistry()
    run_agent("q", llm=Recording(reply("a")), tools=WifiTools(search, AgentSettings(), citations, user_files=UserFiles({}, citations.add, missing=1)), settings=AgentSettings())
    assert not seen[0] & {"list_user_files", "search_user_files", "read_user_file"}
    assert {"list_user_files", "search_user_files", "read_user_file"} <= seen[1]


def test_a_bad_file_id_from_the_model_is_an_error_it_can_retry_not_a_crash(engine):  # noqa: F811
    search, *_ = engine
    citations = CitationRegistry()
    tools = WifiTools(search, AgentSettings(), citations, user_files=UserFiles({}, citations.add))
    assert tools.call("read_user_file", {"file_id": "nope"})["error"].startswith("參數錯誤")
    assert tools.call("list_user_files", {})["files"] == []


# ---------------------------------------------------------------- the routes

@pytest.fixture
def client(tmp_path, monkeypatch):
    """Real KM Control registry: alice holds the file capability for the test zone, bob is a plain account of it."""
    monkeypatch.setenv("KM_CONTROL_DB_URL", "sqlite:///" + str(tmp_path / "control.sqlite3"))
    registry = ControlRegistry.from_environment()
    admin = registry.bootstrap_admin("admin", "strong-password-123")
    users = {n: registry.create_active_with_grant(admin.user_id, n, "strong-password-123", "user", "test").user_id for n in ("alice", "bob")}
    registry.grant_capability(admin.user_id, users["alice"], "test", userfiles.CAPABILITY)
    redis = FakeRedis()
    monkeypatch.setattr(wifi8_routes, "_user_file_store", lambda: UserFileStore(redis, UserFileSettings.from_environment()))
    monkeypatch.setattr(wifi8_routes, "_image_describer", lambda: (lambda data, ext: "【圖中文字】from the picture"))
    sent = []
    from src.web_api import tasks
    monkeypatch.setattr(tasks.celery_app, "send_task", lambda name, args, queue: sent.append((name, args, queue)) or SimpleNamespace(id="t-1"))
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        who = request.headers.get("x-test-user")
        if who:
            request.state.km_identity = {"sub": users[who], "instance_id": "test", "name": who}
        return await call_next(request)

    app.include_router(wifi8_routes.router)
    return TestClient(app), registry, admin, users, sent


def as_(name, **extra):
    return {"x-test-user": name, "x-km-wifi8-userfile": "1", **extra}


def upload(http, name, data, who="alice", header=True):
    headers = as_(who) if header else {"x-test-user": who}
    return http.post("/api/wifi8/files", files={"file": (name, data)}, headers=headers)


def test_only_an_authorised_account_sees_the_feature_and_can_upload(client):
    http, *_ = client
    assert http.get("/api/wifi8/files/config").status_code == 401
    alice = http.get("/api/wifi8/files/config", headers=as_("alice")).json()
    assert alice["enabled"] is True and alice["max_files"] == 3 and ".pdf" in alice["extensions"]
    assert http.get("/api/wifi8/files/config", headers=as_("bob")).json() == {"enabled": False}
    assert upload(http, "a.txt", b"hello", "bob").status_code == 403
    assert http.get("/api/wifi8/files", headers=as_("bob")).status_code == 403
    assert upload(http, "a.txt", b"hello", header=False).status_code == 403  # no same-origin header: a cross-site form cannot do it


def test_upload_list_ask_and_delete(client):
    http, registry, admin, users, sent = client
    made = upload(http, "spec.docx", make_docx(["ELR spec text"]))
    assert made.status_code == 201
    info = made.json()
    assert info["name"] == "spec.docx" and len(info["file_id"]) == 16 and info["expires_in"] == 7200 and "chunks" in info
    assert [f["name"] for f in http.get("/api/wifi8/files", headers=as_("alice")).json()["files"]] == ["spec.docx"]
    asked = http.post("/api/wifi8/agent", json={"question": "比較", "file_ids": [info["file_id"]]}, headers=as_("alice"))
    assert asked.status_code == 202
    name, args, queue = sent[-1]
    assert args[3] == [info["file_id"]] and args[2]["user_id"] == users["alice"]
    assert http.delete(f"/api/wifi8/files/{info['file_id']}", headers=as_("alice")).status_code == 200
    assert http.delete(f"/api/wifi8/files/{info['file_id']}", headers=as_("alice")).status_code == 404
    assert http.get("/api/wifi8/files", headers=as_("alice")).json()["files"] == []


def test_a_question_without_files_is_sent_exactly_as_before(client):
    http, *_, sent = client
    assert http.post("/api/wifi8/agent", json={"question": "ELR?"}, headers=as_("bob")).status_code == 202
    assert len(sent[-1][1]) == 3  # no fourth argument


def test_attaching_files_to_a_question_needs_the_capability_and_a_valid_id(client):
    http, *_, sent = client
    assert http.post("/api/wifi8/agent", json={"question": "q", "file_ids": ["a" * 16]}, headers=as_("bob")).status_code == 403
    assert http.post("/api/wifi8/agent", json={"question": "q", "file_ids": ["../x"]}, headers=as_("alice")).status_code == 422
    assert http.post("/api/wifi8/agent", json={"question": "q", "file_ids": ["a" * 16] * 6}, headers=as_("alice")).status_code == 422
    assert not sent


def test_another_account_cannot_delete_or_see_my_file_even_when_it_is_authorised_too(client):
    http, registry, admin, users, _ = client
    registry.grant_capability(admin.user_id, users["bob"], "test", userfiles.CAPABILITY)
    file_id = upload(http, "mine.txt", b"private").json()["file_id"]
    assert http.get("/api/wifi8/files", headers=as_("bob")).json()["files"] == []
    assert http.delete(f"/api/wifi8/files/{file_id}", headers=as_("bob")).status_code == 404
    assert [f["file_id"] for f in http.get("/api/wifi8/files", headers=as_("alice")).json()["files"]] == [file_id]


def test_upload_refusals_have_the_right_status(client, monkeypatch):
    http, *_ = client
    assert upload(http, "a.exe", b"MZ").status_code == 415
    assert upload(http, "empty.txt", b"").status_code == 422
    monkeypatch.setenv("KM_WIFI8_USERFILE_MAX_BYTES", "100")
    assert upload(http, "big.txt", b"x" * 500).status_code == 413
    monkeypatch.setenv("KM_WIFI8_USERFILE_MAX_BYTES", str(10 * 1024 * 1024))
    monkeypatch.setenv("KM_WIFI8_USERFILE_MAX_FILES", "1")
    assert upload(http, "one.txt", b"first").status_code == 201
    assert upload(http, "two.txt", b"second").status_code == 409


def test_an_image_upload_goes_through_the_describer(client):
    http, *_ = client
    made = upload(http, "shot.png", make_png())
    assert made.status_code == 201 and made.json()["kind"] == "png"


def test_a_revoked_capability_applies_at_once(client):
    http, registry, admin, users, _ = client
    assert upload(http, "a.txt", b"hello").status_code == 201
    registry.revoke_capability(admin.user_id, users["alice"], "test", userfiles.CAPABILITY)
    assert http.get("/api/wifi8/files/config", headers=as_("alice")).json() == {"enabled": False}
    assert upload(http, "b.txt", b"hello").status_code == 403
    assert http.post("/api/wifi8/agent", json={"question": "q", "file_ids": ["a" * 16]}, headers=as_("alice")).status_code == 403


def test_the_capability_is_in_the_admin_catalog():
    catalog = json.loads(open("config/km_capabilities.json", encoding="utf-8").read())["capabilities"]
    entry = next(c for c in catalog if c["id"] == userfiles.CAPABILITY)
    assert set(entry["instances"]) == {"test", "da40"} and entry["label"] and entry["description"]
