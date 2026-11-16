# 設備層級跨文件綜合分析:KM 分析核心與 CSIT↔KM 最小介接契約(提案)

狀態:**KM 分析核心已實作並測試;下方第 3 節的 API / Callback 契約是 KM 的提案,尚未獲 CSIT 同意,未接到任何路由。**
範圍:只在 KM DEV 驗證;不動 Production、不重送既有 Completed Job、不改單檔 KM v2 契約、不寫 CSIT 設備主檔。

## 1. 分階段(重要)

| 階段 | 內容 | 狀態 |
|---|---|---|
| A. 綜合核心 | 讀取各文件**已存**的 Completed.result,依 Manifest 合併、標示衝突、版本與冪等 | 已實作(`src/csit_integration_v1/equipment_synthesis.py`) |
| B. 單檔 Technical 擷取 | 讓單檔結果真的有 specifications / measurements / capabilitySummary / limitations | **未完成**(另案,待 CSIT 方向確認) |
| C. 介接 | Manifest 進件 API、結果 Callback、持久化(SQL) | 待 CSIT 確認第 3 節契約後實作 |

階段 B 未完成時,多數文件的相關欄位仍是空的。核心因此不把「空的 Metadata」合併成成功結果:
沒有任何文件提供規格、量測、能力或限制時,狀態是 `InsufficientEvidence`,結果內容全空,
不會是 `Completed`。DEV 實測見第 5 節。

## 2. 核心行為

- **Manifest 為準:** KM 不推測文件屬於哪台設備;只處理 Manifest 列出的文件。`equipmentId` 是 CSIT 現有字串識別碼,
  不當 UUID 解析。
- **不重做解析/索引:** 核心只讀 KM 已存的 per-document Completed.result(以 `documentId + version` 取得,並要求
  `sha256` 與 Manifest 相同,否則該文件排除為 `metadata_sha_mismatch`)。每份文件的貢獻以內容指紋快取,未變更的文件
  不再重新萃取。
- **合併:**
  - 規格:同欄位、同值(數字會做單位前綴換算,1.2 Gbps = 1200 Mbps;大小寫與空白忽略)合併為一筆並列出全部來源;
    `agreement` 為 `single`(一份文件)或 `agreed`(多份文件一致)。
  - **衝突:** 同欄位不同值 → 放入 `conflicts[]`,列出每個說法與其來源,`resolution` 固定為 `none`;
    **不選其中一個、不覆蓋**,`specifications[]` 也不含該欄位。
  - 量測(`measurements`)與規格分開,不互相比較(量測值不同於額定規格不算衝突)。
  - 測試能力 / 限制 / 識別資訊(型號、產品名、標準…):去重後列出,各附來源。型號或產品名不只一種時加
    `IDENTITY_VARIANTS` 警告,不自行挑選。
- **來源追溯:** 每一項都有 `sources[]`:`documentId / version / sha256 / sourceType / sourceEntityId / kmJobId / evidence`。
- **狀態:** `Completed`(所有文件都有貢獻)/ `Partial`(部分文件被排除,`coverage.excluded[]` 列出原因)/
  `InsufficientEvidence`(沒有任何貢獻)/ `NoDocuments`(Manifest 為空)。
  排除原因:`metadata_missing`、`metadata_sha_mismatch`、`no_technical_content`、`identity_only`。
- **版本與冪等:**
  - `analysisResultId` 由 `equipmentId + manifestHash + algorithmVersion + inputsFingerprint` 決定;同樣輸入再送一次得到同一筆(`Duplicate`),不新增版本。
  - `inputsFingerprint` 含每份被使用文件的內容指紋,所以文件 Metadata 被更新(例如單檔擷取改善)時,即使 Manifest 不變,也會產生新的 `analysisVersion`。
  - `analysisVersion` 逐筆遞增,`supersedesAnalysisResultId` 指向前一版。
  - **舊結果不得覆蓋新結果:** `manifestRevision` 小於已分析的最新版 → 拒絕(`StaleManifest`),不寫入;同 revision 但 `manifestHash` 不同 → 拒絕(`ManifestConflict`);寫入為單一鎖內的 compare-and-set,並行請求亂序到達時最終留下最大的 revision(已有並行測試)。
  - `changes` 欄位說明與上一版的差異:`added / replaced / removed / unchanged`(依 documentId 與 sha256)。
- **摘要:** `summary.documentSummaries[]` 為擷取式(各被使用文件原有的摘要與來源)。`summary.text` 預設為 `null`;
  程式留有 `summarizer` 掛鉤可產生敘述文字,但目前沒有接 LLM(避免在階段 B 未完成前產生沒有證據的敘述)。

## 3. 最小介接契約(提案,待 CSIT 確認)

### 3.1 CSIT → KM:提交 Manifest

```
POST /v2/equipment-analyses            (沿用現有 v2 服務驗證與 Idempotency 慣例)
{
  "schemaVersion": "1.0",
  "equipmentId": "<CSIT 現有字串識別碼>",
  "manifestHash": "<CSIT 計算的 Manifest 雜湊,8–128 字元>",
  "manifestRevision": <整數 ≥1,同一設備單調遞增>,
  "generatedAt": "<帶時區的時間>",
  "documents": [
    { "documentId": "...", "version": 2, "sha256": "<64 位十六進位>",
      "sourceType": "EquipmentAttachment|TestReport|VendorFile|VerificationApplicationAttachment|DocumentLibraryFile",
      "sourceEntityId": "...", "analysisResultId": "<CSIT 的單檔分析結果識別,選填,原樣回傳>", "fileName": "..." }
  ]
}
→ 202 { "equipmentId", "manifestHash", "manifestRevision", "kmAnalysisJobId", "status": "Accepted" }
```

規則:同一 `equipmentId + manifestHash` 重送回同一個結果(冪等);`manifestRevision` 比已處理的小 → `409`(stale);
同 revision 不同 hash → `409`(conflict);一份 Manifest 中同一 `documentId` 只能出現一個版本。

### 3.2 KM → CSIT:結果 Callback

```
POST <CSIT 提供的 callback 位置>
{ "schemaVersion": "1.0-proposal", "analysisResultId", "equipmentId", "manifestHash", "manifestRevision",
  "analysisVersion", "supersedesAnalysisResultId", "algorithmVersion", "inputsFingerprint",
  "status": "Completed|Partial|InsufficientEvidence|NoDocuments", "statusReason", "analyzedAt",
  "coverage": {...}, "summary": {...}, "identity": {...}, "specifications": [...], "measurements": [...],
  "capabilities": [...], "limitations": [...], "conflicts": [...], "warnings": [...], "changes": {...},
  "documents": [...] }
```

完整欄位見 `equipment_synthesis.py`(`_RESULT` JSON Schema 與 `tests/fixtures/equipment_three_documents.json` 的實際輸出範例)。
CSIT 以 `equipmentId + manifestHash + manifestRevision + analysisVersion` 判斷是否為最新結果;
KM 不寫 CSIT 設備主檔,CSIT 自行決定如何使用結果。

## 4. 需要 CSIT 配合 / 確認的項目

1. **設備識別:** `equipmentId` 的字串格式、長度與大小寫規則(KM 目前接受 1–128 字元可列印字串,不改大小寫)。
2. **Manifest 規則:** `manifestHash` 的計算方式;`manifestRevision` 是否同一設備單調遞增(KM 靠它拒絕舊結果);Manifest 是否只含「有效」文件、被取代的舊版本是否一律不列;文件刪除是否就是「新 Manifest 不再列出」。
3. **文件 Metadata 更新:** Metadata 變更時 CSIT 是否一定發新的 `manifestRevision`,還是由 KM 在單檔結果變更時主動重新綜合(目前核心兩種都支援)。
4. **`analysisResultId`:** 單檔分析結果在 CSIT 端的識別碼是什麼?KM 現在以 `documentId + version + sha256` 找單檔結果,`analysisResultId` 只原樣記錄。
5. **來源類型:** 哪些 `sourceType` 納入設備綜合(目前五種都接受;規格欄位只在 EquipmentAttachment 的 `sourceSpecific.specifications` 有定義)。
6. **API 與 Callback:** 進件路徑、驗證(沿用現有 service token?)、Callback 位置、重試與 ACK 規則、`status` 名稱是否可接受(尤其 `Partial` / `InsufficientEvidence` 與 CSIT 現有 Processing / Completed / Failed 三態的對應)。
7. **衝突處理:** CSIT 端是否有人工確認衝突的流程;KM 只標示、不裁決。
8. **階段 B 方向:** 單檔 Technical 擷取的欄位格式與驗收(specifications 的 field/value/unit/evidence、gold set、門檻)。在此之前,真實文件多半會得到 `InsufficientEvidence`。

## 5. 驗證

- 單元測試:`tests/test_csit_equipment_synthesis.py`(36 項):合併/單位前綴、衝突不選值、來源必附、空 Metadata → `InsufficientEvidence`、`Partial` 與排除原因、sha 不符/缺 Metadata、冪等、版本遞增與 `changes`、舊 revision 拒絕、同 revision 不同 hash 拒絕、Metadata 更新觸發新版、未變更文件不重做萃取、文件順序無關、並行寫入、輸入不被改動、Manifest 驗證。
- 合成範例(5 份文件,**虛構資料**,`tests/fixtures/equipment_three_documents.json`):結果 `Partial`,3 份有貢獻、2 份排除;`Max throughput`(資料表 1.2 Gbps、手冊 1200 Mbps)合併為 `agreed`,附兩份來源;`TX power`(資料表 23 dBm、手冊 20 dBm)列為衝突,兩個說法與證據位置都保留,不選值。
- KM DEV 真實資料(唯讀):對 DEV 資料庫中 Completed 的兩份 EquipmentAttachment(KM-ING-000021、KM-ING-000022)用測試 Manifest 執行,結果為 `InsufficientEvidence`:兩份的規格、量測、能力、限制皆為空,核心沒有合併出任何內容。這是階段 B 尚未完成的正確反映,不是綜合分析成功。
  該 Manifest 由 KM 為測試自建(`equipmentId=DEV-TEST-EQUIPMENT`),不是 CSIT 發出的;未寫入任何資料庫,未呼叫 CSIT、LLM、Qdrant、Neo4j。
- 執行方式:`python scripts/equipment_synthesis_demo.py --fixture tests/fixtures/equipment_three_documents.json`

## 6. 尚未做

- 持久化(SQL 表、migration)與 Celery 工作:規則已在記憶體版 store 以測試固定,SQL 版待契約確認後實作。
- 進件 API 路由與 Callback 送出:待 CSIT 確認第 3 節。
- LLM 敘述摘要:待階段 B 與 CSIT 對「證據」的要求確認。
