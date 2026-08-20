# WP1 Evidence — Docker／Redis／Celery／Config 正式化

統計截止：2026-08-12 17:00 Asia/Taipei；合併驗收更新：2026-08-20

| 類別 | 得分／權重 | 證據與限制 |
|---|---:|---|
| 規格與 Contract | 15/15 | REQ-JOB-001、REQ-JOB-002、REQ-OPS-001；typed config、Job status、queue/retry contract。 |
| 程式實作 | 35/35 | branch `agent/wp1-job-config-reliability`，head `cfe5eb0d6a463aa4ddfc6e3a936e2f4a8974109a`。 |
| 測試 | 25/25 | 本地 83 passed；GitHub Actions backend、frontend、repository-hygiene 全部成功。 |
| E2E／驗收 | 10/15 | 隔離 Compose 實測 worker restart、Redis persistence、真實 ingest idempotency；未完成正式部署長時間故障注入與 backup/restore。 |
| PR／合併／文件／回滾 | 6/10 | [PR #5](https://github.com/kyocarlos/knowledge-base-agent-source/pull/5) 已由 Owner Acceptance，exact-head CI 全部通過，並於 2026-08-20 合併至 `agent/km-plan-v2.6-anderson`，merge commit `eb1eb9253dd689eac8cd7796646f98321ad454af`；仍無 WP1 獨立交付 PR，且保留正式長時間故障注入與 backup/restore 限制。 |

總分：**96/100**。WP1 已完成本輪 Owner Acceptance 與 v2.6 整合；仍保留 WP1 專屬正式長時間故障注入與 backup/restore 限制，不宣稱無條件 100%。

CI：原 WP1 分支 [run 31449165822](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/31449165822)；v2.6 驗收分支 [run 31466582953](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/31466582953)，兩者 backend、frontend、repository-hygiene 均成功。

## v2.6 歸類

- `A`：typed job config、queue routing、canonical job status、trace header、retry taxonomy、Redis idempotency、worker restart/health 修正及 CI 可直接保留。
- `B`：原工作包的 Phase 0、REQ-JOB-002／REQ-OPS-001 命名改按 v2.6 歸入 Phase 1 前置與 `REQ-JOB-001`；保留原 commit 歷史。
- `A`：PR #5 已完成 Owner Acceptance、exact-head CI 與合併至 v2.6 base；WP1 獨立交付 PR 仍未建立，保留為文件追溯限制。
- `D`：CSIT Workflow、正式商業狀態與 Schema 由 Patty 負責，不由 WP1 擴張實作。
- `E`：隔離 runtime 驗證已有提交紀錄，但沒有可下載的原始 run artifact；來源 v2.6 Excel 也未存在於 Git，兩者不能當成正式 Gate 完成證據。

## 2026-08-20 cutoff 後補充證據

- 共用 production synthetic write E2E 已完成並安全 rollback；這證明目前正式部署的 report／ingest／Neo4j／Qdrant cleanup path 可受控執行，但不取代 WP1 專屬的 worker restart、Redis idempotency、長時間故障注入與 backup/restore 驗收。
- Production synthetic run：`TR-E2E-WP0-20260820-PROD-CLEANUP-FIX-001`；Qdrant `4/4`、Neo4j `1/1/1`、cleanup 後 submission `404`，Health 與 rollback PASS。
- Evidence：[production E2E](../../../outputs/wp0-write-e2e-20260819/production-write-e2e-cleanup-fix-20260820.json)、[rollback diagnosis](../../../outputs/wp0-write-e2e-20260819/production-qdrant-resolution-diagnosis-20260820.json)。
- 此證據產生於 W33 cutoff 之後，現已補上 PR #5 Owner Acceptance、exact-head CI 與 merge evidence；本次驗收更新 WP1 為 **96/100**，仍保留正式長時間故障注入與 backup/restore 限制。

## 2026-08-20 merge evidence

- PR #5 head `2b60cfb10aca41ef7c29bd63c461544800c0aa97` 已合併至 `agent/km-plan-v2.6-anderson`。
- Merge commit：`eb1eb9253dd689eac8cd7796646f98321ad454af`。
