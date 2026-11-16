# 備援 LLM:SAM 算力中心 ModaOne ModelSpace

## 行為
呼叫順序:**主要閘道(Sub2API / OpenAI)→ ModaOne(備援)→ 本機 Ollama(最後手段,既有)**。

- 只有主要閘道失敗(HTTP 錯誤、429 額度用完、逾時、回覆格式錯誤)才改呼叫 ModaOne;主要閘道正常時完全不用,不消耗點數。
- 主要閘道失敗後,`KM_LLM_FAILOVER_COOLDOWN_SECONDS`(預設 30 秒)內直接走 ModaOne,避免閘道掛掉時每個請求都先等一次逾時;冷卻結束再試主要閘道。ModaOne 也失敗時,冷卻中的主要閘道會再試一次。
- 串流回答若已送出部分文字才中斷,不改送備援(避免重複),維持原本的中斷行為。
- 呼叫端傳的模型名稱屬於主要閘道,備援一律用自己的模型。
- 備援關閉(未設 `KM_LLM_BACKUP_PROVIDER`)時行為與原本完全相同。

走這條鏈的呼叫點:所有經 `_build_primary_client` 的地方(聊天助理、RCA、ingest 語意擷取、Wi-Fi8 摘要、`OllamaClient`)。
另外 `km_export`、`keeper_routes`、`legacy_routes`(main 版本)也套用同一個備援;CSIT worker 的直連閘道(`doclib_llm._gateway`)用 `KM_CSIT_LLM_BACKUP_*`(見下)。
圖片轉文字(Wi-Fi8 圖片、CSIT 看圖)**不接備援**:gpt-oss-120b 不是多模態模型。

## ModaOne 連線資訊(來自 SAM 提供的算力中心資料)
- Base URL:`https://modaone-llm-api.dginfra.gov.tw/api/v1`;支援 OpenAI 格式 `POST /chat/completions` 與 `GET /models`,金鑰可用 `Authorization: Bearer` 或 `X-API-KEY`(KM 用 Bearer)。
- 預設模型:`gpt-oss-120b`(OpenAI 開源模型,聊天類)。其他可用聊天模型見 `GET /models`(Llama-3.3-70B、Mistral-Large-3、gemma-4、Nemotron 等)。
- gpt-oss 是推理模型:推理 token 也算在 `max_tokens` 內,所以備援 client 把 `max_tokens` 下限設為 2048,並預設送 `reasoning_effort=low`(實測 low 約 6 個推理 token,medium 約 120)。
- 金鑰:`/home/da40_ai_gb10/.km-control/llm/modaone-km.env`(`MODAONE_API_KEY=...`,權限 600,不進 git、不寫入日誌)。登入平台用的帳號密碼 KM 不需要,沒有存放。

## 平台規範(SAM / 台智雲通知,務必遵守)
- 只能從**申請時登記的固定 IP**呼叫(每家最多 4 組);DA40 目前連線測試成功(2026-11-16)。換出口 IP 或新增主機要先向 service@twcloud.ai 登記。
- 不得串接到中港澳的遠端 IP;不得使用中國或中資開源模型(DeepSeek、Kimi 等)——預設的 gpt-oss-120b 符合,更換模型時請避開。
- 使用範圍限於核定的專案;核定期間 2026-09-09 ~ 2026-12-08,**期間結束服務即結束**。
- 計量:1 點 = 10 萬個 input 或 output token(含推理 token),L1 核定 1,000 點(約 1 億 token)、L2 2,000、L3 6,000;額度用完或錢包為負會無法使用。點數每日通知專案使用成員。
- 連續未使用達核定期間一半(約 10/24)會被列入提醒、之後可能被停權;備援只在主要閘道失敗時才用,若主要閘道一直正常,要留意這條規定。
- **資料外送:** 備援被觸發時,該次請求的內容(問題、文件節錄、提示詞)會送到政府算力平台。若該請求含 CSIT 或客戶機密文件內容,需確認這符合資料處理規範;不想讓某類請求外送時,不要把該路徑接上備援(例如只設定 web/ingest,不設定 CSIT worker 的 `KM_CSIT_LLM_BACKUP_*`)。

## 設定(都在環境變數,預設關閉)
| 變數 | 預設 | 說明 |
|---|---|---|
| `KM_LLM_BACKUP_PROVIDER` | 空(關閉) | 例如 `modaone`;空、`off`、`0` 皆為關閉 |
| `KM_LLM_BACKUP_MODEL` / `KM_LLM_BACKUP_BASE_URL` | 必填 | 缺一個會記錄錯誤並不啟用備援 |
| `KM_LLM_BACKUP_API_KEY_ENV` | `MODAONE_API_KEY` | 放金鑰的環境變數名稱 |
| `KM_LLM_BACKUP_TIMEOUT_SECONDS` | 120 | |
| `KM_LLM_BACKUP_MAX_TOKENS` / `KM_LLM_BACKUP_MAX_TOKENS_FLOOR` | 8192 / 2048 | |
| `KM_LLM_BACKUP_REASONING_EFFORT` | low | `off` 不送此欄位 |
| `KM_LLM_FAILOVER_COOLDOWN_SECONDS` | 30 | |
| `KM_CSIT_LLM_BACKUP_BASE_URL` / `_MODEL` / `_API_KEY_FILE` | 空(關閉) | 只給 CSIT worker 的直連閘道(`doclib_llm`)用;另有 `_REASONING_EFFORT`(low)、`_MAX_TOKENS`(4096)、`_TIMEOUT` |

DA40 的 compose 覆蓋檔:`deploy/dev-3030/compose/km-da40.llm-backup.override.yml`(最後套用;image 為現有映像加上本分支 3 個檔案)。

## 還原
移除該覆蓋檔(或清空 `KM_LLM_BACKUP_PROVIDER`)後重建容器,即回到原本的主要閘道 → Ollama。

## 驗證
- `tests/test_llm_backup.py`(22 項):主要正常不碰備援、各種失敗都轉備援、冷卻、雙失敗、串流中斷不重送、模型名稱不外流、設定缺漏會記錄、key 不入日誌、完整鏈(主要→備援→Ollama)、CSIT worker 直連閘道。
- 實測(2026-11-16,DA40,主要閘道故意指向不存在的位址):走備援取得 gpt-oss-120b 的繁體中文回答,約 0.5 秒;呼叫端傳入的主要模型名稱與過小的 `max_tokens` 不影響備援。
- 既有的 `test_ollama_client_primary`、`test_openai_compatible_llm`、`test_km_export` 全數通過。
