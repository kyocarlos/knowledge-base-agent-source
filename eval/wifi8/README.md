# WiFi 專區評測題庫

用來衡量 WiFi 專區的檢索與 AI Agent 回答品質。更換模型、Agent 框架或檢索方式前後，都用同一份題庫比較。

## 檔案

- `golden-set.v1.jsonl`：34 題，一行一題，分為 8 類：功能定義、測試驗證、版本判斷、會議紀錄、廠商產品、研究與內部、總覽統計、應拒答。
- `build_golden_set.py`：從匯出包的 `documents.jsonl`／`segments.jsonl` 產生題庫，把標準來源的標題解析成 `revision_id`，每個標題必須唯一對應一份文件。
  - 用法：`python build_golden_set.py <documents.jsonl> <輸出.jsonl>`，`segments.jsonl` 須和 `documents.jsonl` 放在同一目錄。
- `../../src/wifi8/evaluation.py`：評分規則（純程式，不用模型評分）。
- `../../scripts/eval_wifi8_agent.py`：在資料區的 search worker 內執行評測，輸出 `results.json` 與 `report.md`。

## 題目欄位

| 欄位 | 說明 |
|---|---|
| `gold` | 標準來源 `revision_id`，命中任一份即算命中。 |
| `facts` | 事實組。每組列出可接受的寫法，答案出現任一寫法就算該組命中；比對時忽略大小寫與空白。 |
| `expect_refusal`、`refusal_markers`、`must_not_regex` | 資料庫沒有答案的題目：答案須出現拒答用語，且不得出現捏造的具體數值。 |
| `package_id` | 答案會隨匯入資料改變的題目（如總覽統計）。匯入版本不同時，評測會略過這題並在報告中註明。 |

## 出題與標準來源原則

1. 每題的事實都從匯出包原文逐字查證，不由模型產生。
2. 標準來源是「領域人員會接受為此題依據」的文件。WFA 正式文件（MRD 本文、該功能的 MRD contribution、相關 Test Case）一律列入。特定文件或版本的題目只認那一份。
3. 不用「全文同時含有所有事實」自動擴充標準來源：這樣會把只是順帶提到相同數字或詞的文件也算進來。自動結果只當候選，由人工審核。

## 評分

- **檢索**：用問題原文做混合檢索，前 10 筆（以文件計）是否含標準來源（命中@10），以及第一個命中名次的倒數（MRR）。
- **回答通過**：所有事實組都命中，而且引用中至少一筆是標準來源；應拒答的題目則看是否拒答、有沒有捏造數值。
- 另外記錄事實覆蓋率、延遲、工具步驟與停止原因。

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
