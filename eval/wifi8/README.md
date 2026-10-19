# WiFi 專區評測題庫

用來衡量 WiFi 專區的檢索與 AI Agent 回答品質。更換模型、Agent 框架或檢索方式前後，都用同一份題庫比較。

## 檔案

- `golden-set.v1.jsonl`：45 題，一行一題，分為 9 類：功能定義、測試驗證、版本判斷、會議紀錄、廠商產品、研究與內部、總覽統計、應拒答、圖片圖表（2026-10-19 新增 F01～F11）。
- `build_golden_set.py`：從匯出包的 `documents.jsonl`／`segments.jsonl` 產生題庫，把標準來源的標題解析成 `revision_id`，每個標題必須唯一對應一份文件。
  - 用法：`python build_golden_set.py <documents.jsonl> <輸出.jsonl>`，`segments.jsonl` 須和 `documents.jsonl` 放在同一目錄；旁邊有 `images.jsonl`（匯出包 v2）時一併產生圖片圖表題。
- `figure_cases.py`：圖片圖表題的定義與產生器。標準圖片以「文件標題開頭＋位置（投影片／頁／段）＋第幾張圖」指定，從 `images.jsonl` 解析成 `image_id`，必須唯一；同一張圖表也出現在其他文件時一併列入。
  - 只更新圖片圖表題（其他題目原樣保留）：`python figure_cases.py <匯出包解開的目錄> golden-set.v1.jsonl`。
  - 選題原則：答案只在圖片中、文件本文沒有，這樣才能看出圖片轉文字與檢索圖片的效果。
- `../../src/wifi8/evaluation.py`：評分規則（純程式，不用模型評分）。
- `../../scripts/eval_wifi8_agent.py`：在資料區的 search worker 內執行評測，輸出 `results.json` 與 `report.md`。

## 題目欄位

| 欄位 | 說明 |
|---|---|
| `gold` | 標準來源 `revision_id`，命中任一份即算命中。 |
| `facts` | 事實組。每組列出可接受的寫法，答案出現任一寫法就算該組命中；比對時忽略大小寫與空白。 |
| `expect_refusal`、`refusal_markers`、`must_not_regex` | 資料庫沒有答案的題目：答案須出現拒答用語，且不得出現捏造的具體數值。 |
| `gold_figures`、`gold_figure_places` | 圖片圖表題的標準圖片 `image_id`（任一張即可）與其位置說明。 |
| `package_id` | 答案會隨匯入資料改變的題目（如總覽統計）。匯入版本不同時，評測會略過這題並在報告中註明。 |

## 出題與標準來源原則

1. 每題的事實都從匯出包原文逐字查證，不由模型產生。
2. 標準來源是「領域人員會接受為此題依據」的文件。WFA 正式文件（MRD 本文、該功能的 MRD contribution、相關 Test Case）一律列入。特定文件或版本的題目只認那一份。
3. 不用「全文同時含有所有事實」自動擴充標準來源：這樣會把只是順帶提到相同數字或詞的文件也算進來。自動結果只當候選，由人工審核。

## 評分

- **檢索**：用問題原文做混合檢索，前 10 筆（以文件計）是否含標準來源（命中@10），以及第一個命中名次的倒數（MRR）。
- **回答通過**：所有事實組都命中，而且引用中至少一筆是標準來源；應拒答的題目則看是否拒答、有沒有捏造數值。
- **圖片**（圖片圖表題）：檢索前 10 筆（以段落計）是否有標準圖片（`figure_hit_at_10`）；回答引用中是否有標準圖片（`cited_figure`）。只引用同文件文字段落時回答仍可通過，但會列為「引用未包含標準圖片」。
- **引用編號**（所有題目）：同一份文件、同一位置有多筆引用時，每筆都要標出第幾段；沒標的回答數記為 `unnumbered_repeat_answers`，應為 0。
- 另外記錄事實覆蓋率、延遲、工具步驟與停止原因。
- 自動品質驗證（`scripts/wifi8_quality_check.py`）只在題庫內容相同時與上次比較是否退步；題庫改變後的第一次執行不比較。

## 執行（以 TEST 為例）

```bash
C=kb-celery-search
for f in scripts/eval_wifi8_agent.py src/wifi8/evaluation.py eval/wifi8/golden-set.v1.jsonl; do docker cp "$f" $C:/tmp/km-eval/; done
docker exec -w /app $C python /tmp/km-eval/eval_wifi8_agent.py --cases /tmp/km-eval/golden-set.v1.jsonl \
    --out /tmp/km-eval/out --source-commit "$(git rev-parse --short HEAD)" [--retrieval-only] [--ids D01,T02]
docker cp $C:/tmp/km-eval/out ./wifi8-eval-out
```

- `--retrieval-only` 不呼叫 LLM；`--rescore <results.json>` 沿用已保存的回答重新評分；`--candidate-wifi8 <dir>` 在部署前評估候選版的 `src/wifi8`。
- 評分規則以和執行程式放在一起的 `evaluation.py` 為準（請一起複製），不使用映像內的版本，避免評分規則隨部署版本改變。
- 完整評測每題會呼叫主要 LLM 數次（依工具步數而定），34 題約 15～30 分鐘。
- DA40 的 search worker 是 `km-da40-celery_search_worker-1`。

## 匯入新資料後

匯入新的匯出包後，`revision_id` 可能改變，總覽統計的數字也會變。要用新匯出包重新執行 `build_golden_set.py`，並檢查新文件是否需要新增題目或擴充標準來源。

## 基準結果（2026-10-17，TEST）

- 匯入版本 `wifi8-0216bc31ebf95107`；模型 `sub2api:gpt-5.6-luna`；`max_steps=6`、時間上限 90 秒。
- 檢索命中@10 為 93.3%，MRR 0.788；回答通過 97.1%（33/34）；事實覆蓋 98.4%；引用標準來源 100%；延遲 p50 8.7 秒。
- 未通過的 3 題（皆為有效發現，不是評分問題）：
  - **D07（回答）**：Agent 沒有答出「AP 若實作 WPA3-Enterprise 就必須實作 DBE」，查了 9 次工具仍回答「尚未查證」。MRD v1.0 和 DBE Contribution v5 都有這條。
  - **T01（檢索）**：前 10 筆是只提到 PF2 的會議議程，沒有同時談 Security Profile 的文件。Agent 改用其他查詢後仍答對。
  - **M02（檢索）**：「blind poll」沒有找到 Ballot Package - Results，前 10 筆都是 Ballot Package 本體和草稿。Agent 用 read_document 補查後仍答對。
- 第一次評分時另有 3 題沒通過，經人工核對原文後，確認是題庫本身的錯誤，已修正：
  - D01 的速率應為 1.67／3.33 Mbps，MRD v4 的「1.5」是修訂殘留；
  - D10 的「26-tone」不是回答這題的必要事實；
  - T05 補上 2xLDPC Test Case v14 作為標準來源。

  修正後用 `--rescore` 沿用原本的回答重新評分，沒有再呼叫 LLM。

## 2026-10-17 摘錄修正（commit 7d28c7d，部署為 *-excerpt-7d28c7d）

- 根因：Agent 工具只把段落開頭 700 字（search）／1500 字（read）交給模型。73.8% 的段落超過 700 字，D07 的關鍵句位在第 785～868 字。改成依查詢詞挑選句子的摘錄後，D07 從修正前的 3/5 提升到 4/4（TEST），已部署版本再問 3/3。
- DA40 已部署版本（34 題）：檢索命中@10 93.3%、回答通過 94.1%（32/34）、引用標準來源 100%、p50 7.2 秒。
  - D09：舊版 0/3、新版 1/4，常漏答「只能用 LDPC」。
  - T03：舊版 3/3、新版 3/4，有一次把 Test Plan 答成 v0.1.2。
  - 兩題都不是這次修正造成的退步。
- 評分與題庫修正：
  - 比對時統一 Unicode 連字號與乘號（4×4、Wi‑Fi）。
  - D01 補上 ELR Test Case v1、D02 補上兩份 NPCA 專文作為標準來源。
  - D06 移除題目沒問的「選用」事實組。
  - 評分規則改為以執行程式旁邊的 `evaluation.py` 為準。

## 2026-10-17 Rerank 試驗（DA40，只評檢索，CPU）

在 RRF 合併後，取前 N 個候選段落交給 cross-encoder 重新排序（`src/wifi8/rerank.py`，預設關閉，由 `KM_WIFI8_RERANK_MODEL` 開啟）。

| 設定 | 命中@10 | MRR | 每次檢索 p50 |
|---|---|---|---|
| 不用 rerank | 93.3% | 0.794 | 0.16 秒 |
| bge-reranker-base，候選 30 | 93.3% | 0.789 | 3.9 秒 |
| bge-reranker-v2-m3，候選 30 | 93.3% | 0.825 | 13.6 秒 |
| bge-reranker-base，候選 80 | **96.7%** | **0.828** | 8.6 秒 |

- T01、M02 的標準來源在 RRF 合併後排第 36～58 名（只被全文檢索找到）。候選 30 時 rerank 看不到它們；候選 80 時 base 能把它們排到第 3、第 1 名，v2-m3 兩題都排到第 1 名，但每次檢索要 17～27 秒。
- base 候選 80 的副作用：T03 從第 6 名掉出前 10 名；D09、D11、V03 各下降 1 名。D02、D03 各上升 1 名。
- 結論：在 CPU 上，品質提升有限，延遲卻增加 50～80 倍（Agent 每題會檢索 1～7 次）。暫不上線。若要再試：使用 GPU、加大 RRF 候選數，或對全文和語意兩路分別保留較多候選。

## 2026-10-17 依據檢核（grounding）

每則 Agent 回答都附上 `grounding`（`src/wifi8/grounding.py`），前端顯示在「依據檢核」區塊。全部用程式計算，不呼叫 LLM。

- **句子依據：** 把回答拆成技術句。句子本身沒有 [S#] 時，依序沿用同一行、條列或表格的引言行，以及同一區塊其他項目的引用。拒答句和標題不檢核。沒有引用、但所有數值都能在工具資料中找到的句子算「依工具資料」。
- **數值核對：** 抽出數字、版本、型號與代碼，依序比對：該句引用的完整原文（verified）→ 其他引用（other_source）→ Agent 這次拿到的所有工具結果，包括文件資料、版本清單、總覽（tool_data）→ 都找不到（not_found）。
- **相似度：** 預設關閉（`KM_WIFI8_GROUNDING_SIMILARITY`）。用 `scripts/calibrate_wifi8_grounding.py` 在 DA40 校準：答案與自身引用原文的相似度 p50 為 0.665，與不相干原文的 p90 為 0.635，兩者大量重疊，照門檻會把 36% 正確引用的句子標成「低」，所以不顯示給使用者。
- **校正誤判（DA40，34 題）：** 第一版有 19.5% 的數值被判找不到，原因是沒比對文件資料（版本、文件 ID、總覽數字）、Markdown 底線被刪、序數被當成數值、數字和單位之間有連字號。修正後降到 4.2%。剩下的抽查結果：原文錯字（MS19）、Agent 自行推論的否定句（不適用 2.4 GHz），以及單位寫法差異（已再修正）。

## 使用者流程驗收（Webwright）

四支腳本共用 `scripts/webwright_wifi8_common.py`，負責登入、進入 WiFi 專區、提問 Agent、記錄截圖、console／失敗請求，以及產生 `summary.json`。每支都以 `RUN_DIR ZONE USER PASS_KEY` 開頭，全部通過時 exit 0、有失敗 exit 1、參數錯誤 exit 2。密碼從 `KM_TEST_ACCOUNTS_FILE`（預設 `~/.km-control/test-accounts.env`）讀取，不會輸出；結束時登出。入口網址可用 `KM_BASE_URL` 修改。

| 腳本 | 驗收內容 |
|---|---|
| `webwright_wifi8_accept.py` | 8 項回歸：總覽、文件瀏覽、文件段落、3 組混合檢索、AI Agent（含 [S#] 與引用清單）、WiFi API 無錯誤。預期數量讀自 `/api/wifi8/overview`，不寫死 |
| `webwright_wifi8_render.py [--static DIR]` | 顯示：檢索標題是文件名稱、AI 回答以 Markdown 呈現、引用清單與內文 [S#] 一致。`--static frontend/wifi8` 可在部署前改用本機前端 |
| `webwright_wifi8_grounding.py [--scenario all\|panel\|table\|code_block]` | 依據檢核：區塊與標籤、D07 的 WPA3-Enterprise 條件、表格標題列與程式碼區塊不被當成句子 |
| `webwright_wifi8_upload.py --package ZIP [--dry-run]` | 從「匯入與進度」頁上傳匯出包（202／queued／submitted_by）；`--dry-run` 只驗證到選好檔案，不送出 |

- 例：`python scripts/webwright_wifi8_accept.py /tmp/run-da40 da40 km-clude3 KM_TEST_PASS1`
- accept 的 Agent 判定：不是錯誤訊息、答案含 [S#]、引用清單 ≥1 筆、長度 ≥ `KM_ACCEPT_AGENT_MIN_CHARS`（預設 40）。題目與檢索詞可用 `KM_ACCEPT_AGENT_QUESTION`、`KM_ACCEPT_SEARCH_QUERIES` 修改。
- grounding 的程式碼區塊判定是單向的：檢核句子是區塊內某一行的一部分，才算誤判。只是包含區塊中短標籤（例如「一般 RU」）的正常句子不算。

## 自動品質驗證（三層）

`scripts/wifi8_quality_check.py [--zones test,da40] [--levels retrieval,agent,trust]` 在主機上執行；題庫評測在各區 search worker 內跑。

| 層級 | 回答的問題 | 指標 | 成本 |
|---|---|---|---|
| ① retrieval | 檢索找文件的能力 | 命中@10、MRR、檢索耗時 | 不呼叫 LLM |
| ② agent | Agent 整體答得準不準 | 回答通過、事實覆蓋、引用標準來源、耗時、錯誤數 | 每區約 34～100 次 LLM 呼叫 |
| ③ trust | 真實回答可不可信 | 數值找不到比例、沒有依據的句子比例、檢核錯誤、未完成回答、延遲 p95 | 不呼叫 LLM |

- ③ 的資料來自 search worker 的 `WIFI8_ANSWER_QUALITY` 紀錄。Agent 每則回答寫一行，只有統計數字，不含問題、回答或原文。題庫評測執行時設定 `KM_WIFI8_QUALITY_LOG=0`，不計入。Webwright 驗收用測試帳號實際提問，會計入。回答數少於 `trust_min_answers` 時判為資料不足，不判定。
- 門檻與退步容許值在 `quality-config.json`。每項判為 PASS、WARN 或 FAIL；比上次退步超過容許值時至少為 WARN。結束碼：0 PASS、3 WARN、1 FAIL、2 錯誤。
- 輸出在 `~/.km-control/wifi8-quality/`（可用 `KM_WIFI8_QUALITY_ROOT` 修改）：每次一個目錄（report.md／report.json／原始結果）、`latest.md`、`history.jsonl`。
- 排程入口：`scripts/wifi8_quality_cron.sh daily`（①③）、`weekly`（①②③），用 flock 避免重複執行，紀錄在 `cron_logs/`。
- 首次執行（2026-10-17）兩區皆 PASS：①命中 93.3%／MRR 0.794；② TEST 97.1%、DA40 90.9%。DA40 的 D10、V03 是標準來源列得太窄，已補上，重新評分後為 97.0%。③ 數值找不到 TEST 0%、DA40 1.4%。

### WARN／FAIL 通知（Telegram／LINE）

- 通知時機：
  - `wifi8_quality_check.py` 判定總結為 `quality-config.json` 的 `notify.on`（預設 WARN、FAIL）時通知；
  - 排程執行本身失敗（結束碼不是 0／1／3）時，`wifi8_quality_cron.sh` 另外送一則「執行失敗」通知。
- 設定：`~/.km-control/notify/wifi8-quality.env`（權限必須 0600，不進 git；可用 `KM_WIFI8_NOTIFY_ENV` 指定位置）。
  - `KM_NOTIFY_CHANNEL=telegram|line`；
  - Telegram：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`；
  - LINE Messaging API：`LINE_CHANNEL_ACCESS_TOKEN`、`LINE_TO`（LINE Notify 已停止服務）。
- 填好後用 `python3 scripts/wifi8_quality_notify.py --test` 確認。
- 訊息只含總結、區、層、未通過指標與數值、報告路徑，不含題目、回答或文件內容；錯誤訊息只列管道與 HTTP 狀態碼，不含 token。
- 通知失敗不影響驗證：報告照常寫入，並在報告末尾註明通知結果；`--no-notify` 可關閉通知。

## 圖片圖表題基準（2026-10-19，TEST 與 DA40，commit `6e1f5ec`）

- 匯入版本 `wifi8-4524d8071d6e37f3`（含 985 個圖片段落）；全部 43 題：兩區檢索命中@10 94.9%、MRR 0.804；回答通過 TEST 95.1%、DA40 97.6%。
- 圖片圖表 9 題：檢索前 10 筆有標準圖片 88.9%（兩區相同）；回答引用標準圖片 TEST 87.5%（F03 該次 LLM 請求失敗，重跑通過）、DA40 88.9%。
- 同一位置多筆引用卻沒標出第幾段的回答：兩區都是 0。
- 有效發現：
  - **F05（回答錯誤，兩區相同）**：PF1 Report 的 UHR-4.5.2 應為 25／30／30，Agent 答成 6／9／9，這是 EE1 Report 同一測試項目的數值；引用的是 PF1 的文字投影片而不是結果圖。兩份報告的結果表版面幾乎相同，Agent 把兩份報告混在一起。
  - **F04（檢索）**：「Wi-Fi NOW - Co-SR - Image」沒進前 10 筆，但 Agent 從 Part Five 文章中的同一張表找到並引用，回答正確。

## F05 混淆 PF1／EE1 的修正（2026-10-19）

- 重現：TEST 同一題跑 5 次，3 次答 6／9／9、1 次答對、1 次說無法確認。檢索每次相同（正確的 PF1 圖排第 5），差別在 Agent：答錯的都只搜尋 1 次就回答，答對的搜尋 8 步並讀了文件。
- 原因：兩份報告的結果圖文字裡沒有「PF1」「EE1」，題目指名的文件無法影響排序（EE1 排第 1）；Agent 沒核對標題；依據檢核對「2.4G：6」這種短數值不檢查，所以沒有旗標。
- 修正（皆不需重新匯入）：
  1. 檢索：題目含文件短名（PF1、EE1 這類「大寫字母＋數字」，只出現在 10 份以內的目前版本標題）時，該文件段落的融合分數乘 `KM_WIFI8_TITLE_MATCH_WEIGHT`（預設 1.3，1.0 為關閉）。Agent 自己改寫查詢時，也參考使用者原本的問題。題庫檢索評測：命中@10 94.9%→95.1%、MRR 0.804→0.826、圖片命中 88.9%→90.9%。
  2. Agent 搜尋工具：題目指名文件時，`search_wifi` 預設只搜尋那份文件（回傳有 `scope`），文件內圖片段落不降權；需要比較其他文件時模型可設 `all_documents=true`。找不到時退回搜尋全部。這是程式規則，不靠提示詞。
  3. 依據檢核新增兩項：`value_not_in_cited`（標籤後的短數值不在引用段落）、`source_name_mismatch`（句子或題目指名的文件，不是引用的文件）。第三層新增 `trust.answers_with_cited_mismatch_rate`（警示 10%、失敗 25%；尚未用實際流量校準）。
- 比較測試（F05、F06、F10、F11 各 4 輪 × 兩區 = 32 次）：原樣 答對 9／答錯 20／拒答 2；只加權 18／7／6；加限定文件 13／0／19（圖片降權，找不到表）；限定文件＋圖片不降權 **31／0／1**（採用）。系統提示加「核對標題」規則反而使拒答增加到 24 次，已移除。
- 題庫新增 F10、F11（PF1 STAUT 結果表），與 F05／F06 一起檢查「兩份報告的表長得一樣、數字不同」；題庫變動後第一次執行不與上次比較。

## 拒答不補推測、列舉註明依據（2026-10-19）

- 模擬 17 題（議程、版本、規範、錯誤前提、跨文件比較、計算、圖表、應拒答、英文、提示注入、模糊、列舉、摘要）兩區事實全部正確；發現兩個小問題：
  1. 拒答時會補上文件沒有的建議（例如「費用通常取決於…」「建議向…詢價」）。
  2. 列舉類問題斷言「共有 5 篇」，但標題沒寫出 Coordinated Spatial Reuse、內文才大量討論的論文沒被列入。
- 修正：系統提示新增規則 7（資料不足時只說明已確認與缺少的，不補一般常識、可能原因或建議）、規則 8（列舉類問題用兩個以上關鍵字搜尋，註明清單依據，沒有明確總數時不斷言「只有／共 N 筆」）。
- 驗證（拒答 4 題＋列舉 4 題，兩區各 3 輪）：拒答含推測用語 3/12 → 0/24；列舉斷言總數 2/12 → 0/24；註明依據 4/12 → 11/24。D05 回歸 8/8（規則 7 曾多一句「每一句都要有工具結果支持」，D05 掉到約 9/12，已拿掉）。
- 限制：列舉題仍可能漏掉內文才討論主題的文件（召回不變），只是會註明依據範圍；平均多用約 1.7 步。

## 列舉題召回：依文件彙整檢索 find_documents（2026-10-19）

- 問題：「有哪些文件／論文討論 X」用 `search_wifi` 時，每份文件最多回 3 段，內文才大量談到 X 的論文（例如 Flow Matching、A Tutorial on Wi-Fi 8 Multi-AP Coordination）被只有一段很強的文件擠掉；Agent 要多搜好幾次，仍漏。
- 修正：新增 `Wifi8Search.documents()` 與 Agent 工具 `find_documents`：用同一套混合檢索掃 200 個候選段落，按文件分組排名（最相關三段的分數＋每個內文有比對到的段落加分 `LEXICAL_CHUNK_BONUS`），回傳每份文件的最相關段落與 `matching_chunks`；系統提示規則 8 改為列舉題先用它。
- 標準答案：由匯出包原文計算（Co-SR 論文＝arXiv 內文提到 ≥10 次；DSO ≥25；NPCA 會議紀錄 ≥3；SMD Roaming ≥40；ELR ≥40；Qualcomm 全部文件）。
- 6 題列舉題、兩區各 3 輪（共 36 次）召回：部署版 77.2% → 初版 find_documents 84.0% → 加排名加分後 80.2%；平均步數 5.3 → 1.6；註明依據範圍 16/36 → 30/36；斷言總數且沒註明 1 → 0。
  - 排名加分在離線檢查（5 個主題）前 10 名召回 0.84 → 0.89、前 5 名 0.43 → 0.62；端到端 80.2% 與 84.0% 差 6 個命中，在 36 次樣本的雜訊範圍內，無法分辨。
- 限制：標準答案以提及次數計，Agent 會把「主題不限於 X」的綜合性文件排除（例如 R&S 的 ELR 簡報、MRD v1.0），這類漏失不全是缺陷；Kom8ndor（模擬器論文）在 Co-SR 題中六次都沒被列出。
- 回歸（最終版，兩區）：模擬 17 題事實全對、平均步數 1.6；F05／F06／F10／F11／D05／D07／D09 各 2 輪全過。
