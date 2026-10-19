# WiFi 專區驗收報告（Patty 需求第 1、4 項）

- 產生時間：2026-10-19T14:22:05+00:00　　程式 commit：539922d　　題庫：957da2a211bf6c1b
- 結論：**⚠️ WARN**（只要任一專區有 FAIL／MISMATCH／STALE 就不是通過；WARN 與未驗證代表尚未完整驗收）

## 第 0 項：部署身分與可追溯

需求：驗收的是正在服務的版本：映像、commit 與部署程式必須能對帳（AGENTS.md 第 6 條）

| 編號 | 驗收項目 | TEST | DA40 |
|---|---|---|---|
| 0.1 | 部署中的程式 = 已核准的 git commit | ✅ PASS | ✅ PASS |

## 第 1 項：文件清理 / Normalize / Chunk / Metadata

需求：完整驗收「清理狀態、chunk、metadata、版本、失敗狀態可見」

| 編號 | 驗收項目 | TEST | DA40 |
|---|---|---|---|
| 1.1 | 排除政策已執行並留有紀錄 | ✅ PASS | ✅ PASS |
| 1.2 | 文字狀態（已索引／未索引）逐份可查 | ✅ PASS | ✅ PASS |
| 1.3 | 每個檢索單位都有內容、位置與完成向量化 | ✅ PASS | ✅ PASS |
| 1.4 | 每份已索引文件都有檢索單位，單位序號連續 | ✅ PASS | ✅ PASS |
| 1.5 | 匯出包段落都落在檢索單位內（不遺漏） | ✅ PASS | ✅ PASS |
| 1.6 | 必要 metadata 齊全 | ✅ PASS | ✅ PASS |
| 1.7 | 檢索單位帶的 metadata 與文件一致 | ✅ PASS | ✅ PASS |
| 1.8 | 選填 metadata 覆蓋率已揭露（來源本身缺值，不是處理遺失） | ✅ PASS | ✅ PASS |
| 1.9 | 取代關係完整：被取代的文件不再是目前版本 | ✅ PASS | ✅ PASS |
| 1.10 | 同一版本系列只有一份目前版本 | ⚠️ WARN | ⚠️ WARN |
| 1.11 | 畫面看得到處理狀態：排除、文字狀態、檢索單位、metadata 覆蓋率 | ✅ PASS | ✅ PASS |
| 1.12 | 畫面看得到版本關係、metadata 與來源段落 | ✅ PASS | ✅ PASS |
| 1.13 | 失敗狀態可見：驗證失敗立即顯示原因、任務清單留有紀錄、目前版本不受影響 | ✅ PASS | ✅ PASS |

## 第 4 項：Knowledge Search / RAG

需求：Qdrant semantic search、hybrid retrieval、rerank、引用證據

| 編號 | 驗收項目 | TEST | DA40 |
|---|---|---|---|
| 4.1 | Qdrant 同時存放語意向量與全文（BM25）向量 | ✅ PASS | ✅ PASS |
| 4.2 | 混合檢索（語意＋全文，RRF 融合）不劣於單一路徑 | ✅ PASS | ✅ PASS |
| 4.3 | 檢索結果都帶得出引用證據（標題、位置、WFA ID） | ✅ PASS | ✅ PASS |
| 4.4 | rerank（cross-encoder 重排） | ⏸ 未啟用 | ⏸ 未啟用 |
| 4.5 | Agent 回答附引用、引用能對到標準來源 | ✅ PASS | ✅ PASS |
| 4.6 | 使用者流程：混合檢索、AI Agent 附引用回答 | ✅ PASS | ✅ PASS |

## 證據明細

### TEST（資料版本 wifi8-4524d8071d6e37f3）

- **0.1 部署中的程式 = 已核准的 git commit**　✅ PASS　映像 commit 32ded88；search_worker 比對 17 檔, web 比對 17 檔, ingest_worker 比對 17 檔；與 git 該 commit 不同的檔案 0 個；目前 HEAD 539922d 之後改過這些程式的檔案 0 個
- **1.1 排除政策已執行並留有紀錄**　✅ PASS　排除 7 份（confidentiality:internal=7）；被排除等級的文件留在庫內：0 份；匯出包宣告不包含：5 類
- **1.2 文字狀態（已索引／未索引）逐份可查**　✅ PASS　文字狀態 {'indexed': 492, 'not_indexed': 11}；未索引 11 份，其中非圖片檔 0 份（未索引的圖片檔由圖片轉文字進入檢索：11 份有檢索單位）
- **1.3 每個檢索單位都有內容、位置與完成向量化**　✅ PASS　檢索單位 32380 個；空內容 0、缺位置 0、不屬任何文件 0、向量未完成 0
- **1.4 每份已索引文件都有檢索單位，單位序號連續**　✅ PASS　有段落的已索引文件 492 份，沒有檢索單位 0 份；序號不連續 0 份
- **1.5 匯出包段落都落在檢索單位內（不遺漏）**　✅ PASS　匯出包段落 94528 個，已被檢索單位引用 94528 個（100.00%，門檻 99%）
- **1.6 必要 metadata 齊全**　✅ PASS　必要欄位 revision_id 100%、title 100%、publisher 100%、document_role 100%、source_sha256 100%（503 份文件）
- **1.7 檢索單位帶的 metadata 與文件一致**　✅ PASS　發布者、文件角色、WFA ID／版次、版本系列、生命週期不一致的檢索單位：0 個
- **1.8 選填 metadata 覆蓋率已揭露（來源本身缺值，不是處理遺失）**　✅ PASS　wfa_document_id 65%；wfa_revision 65%；document_date 34%；version_label 54%；lifecycle_status 100%；topics 100%
- **1.9 取代關係完整：被取代的文件不再是目前版本**　✅ PASS　取代對象不存在 0 筆；被取代卻仍是目前版本 0 份；標為已取代卻可分析 0 份
- **1.10 同一版本系列只有一份目前版本**　⚠️ WARN　目前版本 367 份，分屬 366 個系列；同系列有多份目前版本的 1 組（來源端未判定取代關係，屬已知待釐清：confirmed-series-febc631a39c2a9ce3c06 → ['wfa-wifi-certified-8-test-plan-comments--unversioned-clean-d1c60c18', 'wfa-wifi-certified-8-test-plan-comments--v2-clean-ed1d25fd']）
- **1.11 畫面看得到處理狀態：排除、文字狀態、檢索單位、metadata 覆蓋率**　✅ PASS　processing_panel=通過
- **1.12 畫面看得到版本關係、metadata 與來源段落**　✅ PASS　version_relation=通過
- **1.13 失敗狀態可見：驗證失敗立即顯示原因、任務清單留有紀錄、目前版本不受影響**　✅ PASS　failure_visible=通過
- **4.1 Qdrant 同時存放語意向量與全文（BM25）向量**　✅ PASS　集合 wifi8_chunks：向量 ['dense']、稀疏向量 ['text']；抽樣一點同時帶有 ['dense', 'text']；embedding 模型 BAAI/bge-base-zh-v1.5
- **4.2 混合檢索（語意＋全文，RRF 融合）不劣於單一路徑**　✅ PASS　54 題題庫：只用語意 94.4%／MRR 0.7416；只用全文 90.7%／MRR 0.8117；混合 96.3%／MRR 0.8552（門檻 ≥90% 且不低於單一路徑 2% 以內）；兩條路徑各自漏掉不同題目 6 題
- **4.3 檢索結果都帶得出引用證據（標題、位置、WFA ID）**　✅ PASS　抽 20 題、共 200 筆檢索結果；缺標題／位置／WFA ID 的 0 筆
- **4.4 rerank（cross-encoder 重排）**　⏸ 未啟用　此專區未啟用：程式為選配、預設關閉（KM_WIFI8_RERANK_MODEL 未設定）；10/17 DA40 試驗命中前 10 由 93.3% 升至 96.7%、每次檢索多約 8.6 秒，是否啟用待決定
- **4.5 Agent 回答附引用、引用能對到標準來源**　✅ PASS　69 題：回答通過 98.6%、引用到標準來源 100.0%（門檻 ≥90%）、事實涵蓋 100.0%、禁止的回答 0、執行錯誤 0；未通過題 ['L01']；報告 2026-10-19T13:49:29+00:00（commit 32ded88）
- **4.6 使用者流程：混合檢索、AI Agent 附引用回答**　✅ PASS　search_1=通過；search_2=通過；search_3=通過；agent=通過

### DA40（資料版本 wifi8-4524d8071d6e37f3）

- **0.1 部署中的程式 = 已核准的 git commit**　✅ PASS　映像 commit 32ded88；search_worker 比對 17 檔, web 比對 17 檔, ingest_worker 比對 17 檔；與 git 該 commit 不同的檔案 0 個；目前 HEAD 539922d 之後改過這些程式的檔案 0 個
- **1.1 排除政策已執行並留有紀錄**　✅ PASS　排除 7 份（confidentiality:internal=7）；被排除等級的文件留在庫內：0 份；匯出包宣告不包含：5 類
- **1.2 文字狀態（已索引／未索引）逐份可查**　✅ PASS　文字狀態 {'indexed': 492, 'not_indexed': 11}；未索引 11 份，其中非圖片檔 0 份（未索引的圖片檔由圖片轉文字進入檢索：11 份有檢索單位）
- **1.3 每個檢索單位都有內容、位置與完成向量化**　✅ PASS　檢索單位 32380 個；空內容 0、缺位置 0、不屬任何文件 0、向量未完成 0
- **1.4 每份已索引文件都有檢索單位，單位序號連續**　✅ PASS　有段落的已索引文件 492 份，沒有檢索單位 0 份；序號不連續 0 份
- **1.5 匯出包段落都落在檢索單位內（不遺漏）**　✅ PASS　匯出包段落 94528 個，已被檢索單位引用 94528 個（100.00%，門檻 99%）
- **1.6 必要 metadata 齊全**　✅ PASS　必要欄位 revision_id 100%、title 100%、publisher 100%、document_role 100%、source_sha256 100%（503 份文件）
- **1.7 檢索單位帶的 metadata 與文件一致**　✅ PASS　發布者、文件角色、WFA ID／版次、版本系列、生命週期不一致的檢索單位：0 個
- **1.8 選填 metadata 覆蓋率已揭露（來源本身缺值，不是處理遺失）**　✅ PASS　wfa_document_id 65%；wfa_revision 65%；document_date 34%；version_label 54%；lifecycle_status 100%；topics 100%
- **1.9 取代關係完整：被取代的文件不再是目前版本**　✅ PASS　取代對象不存在 0 筆；被取代卻仍是目前版本 0 份；標為已取代卻可分析 0 份
- **1.10 同一版本系列只有一份目前版本**　⚠️ WARN　目前版本 367 份，分屬 366 個系列；同系列有多份目前版本的 1 組（來源端未判定取代關係，屬已知待釐清：confirmed-series-febc631a39c2a9ce3c06 → ['wfa-wifi-certified-8-test-plan-comments--unversioned-clean-d1c60c18', 'wfa-wifi-certified-8-test-plan-comments--v2-clean-ed1d25fd']）
- **1.11 畫面看得到處理狀態：排除、文字狀態、檢索單位、metadata 覆蓋率**　✅ PASS　processing_panel=通過
- **1.12 畫面看得到版本關係、metadata 與來源段落**　✅ PASS　version_relation=通過
- **1.13 失敗狀態可見：驗證失敗立即顯示原因、任務清單留有紀錄、目前版本不受影響**　✅ PASS　failure_visible=通過
- **4.1 Qdrant 同時存放語意向量與全文（BM25）向量**　✅ PASS　集合 wifi8_chunks：向量 ['dense']、稀疏向量 ['text']；抽樣一點同時帶有 ['dense', 'text']；embedding 模型 BAAI/bge-base-zh-v1.5
- **4.2 混合檢索（語意＋全文，RRF 融合）不劣於單一路徑**　✅ PASS　54 題題庫：只用語意 94.4%／MRR 0.7416；只用全文 90.7%／MRR 0.8117；混合 96.3%／MRR 0.8552（門檻 ≥90% 且不低於單一路徑 2% 以內）；兩條路徑各自漏掉不同題目 6 題
- **4.3 檢索結果都帶得出引用證據（標題、位置、WFA ID）**　✅ PASS　抽 20 題、共 200 筆檢索結果；缺標題／位置／WFA ID 的 0 筆
- **4.4 rerank（cross-encoder 重排）**　⏸ 未啟用　此專區未啟用：程式為選配、預設關閉（KM_WIFI8_RERANK_MODEL 未設定）；10/17 DA40 試驗命中前 10 由 93.3% 升至 96.7%、每次檢索多約 8.6 秒，是否啟用待決定
- **4.5 Agent 回答附引用、引用能對到標準來源**　✅ PASS　69 題：回答通過 97.1%、引用到標準來源 100.0%（門檻 ≥90%）、事實涵蓋 99.5%、禁止的回答 0、執行錯誤 0；未通過題 ['D09', 'L01']；報告 2026-10-19T13:49:29+00:00（commit 32ded88）
- **4.6 使用者流程：混合檢索、AI Agent 附引用回答**　✅ PASS　search_1=通過；search_2=通過；search_3=通過；agent=通過

## 未通過或有保留的項目

- 1.10 同一版本系列只有一份目前版本：⚠️ WARN — 目前版本 367 份，分屬 366 個系列；同系列有多份目前版本的 1 組（來源端未判定取代關係，屬已知待釐清：confirmed-series-febc631a39c2a9ce3c06 → ['wfa-wifi-certified-8-test-plan-comments--unversioned-clean-d1c60c18', 'wfa-wifi-certified-8-test-plan-comments--v2-clean-ed1d25fd']）
- 4.4 rerank（cross-encoder 重排）：⏸ 未啟用 — 此專區未啟用：程式為選配、預設關閉（KM_WIFI8_RERANK_MODEL 未設定）；10/17 DA40 試驗命中前 10 由 93.3% 升至 96.7%、每次檢索多約 8.6 秒，是否啟用待決定

## 如何重跑

```bash
python scripts/wifi8_acceptance.py --out DIR --ui test=DIR --ui da40=DIR
```

規格與門檻：`eval/wifi8/acceptance-spec.json`；檢查程式：`src/wifi8/acceptance.py`；畫面流程：`scripts/webwright_wifi8_item1.py`、`scripts/webwright_wifi8_accept.py`。
