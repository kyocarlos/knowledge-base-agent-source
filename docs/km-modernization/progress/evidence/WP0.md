# WP0 Evidence — FastAPI contract 與測試基線

統計截止：2026-08-12 17:00 Asia/Taipei；合併驗收更新：2026-08-20

| 類別 | 得分／權重 | 證據與限制 |
|---|---:|---|
| 規格與 Contract | 15/15 | REQ-API-001、REQ-API-002、REQ-OPS-001；PR #2 描述具 ADR、相容與回滾。 |
| 程式實作 | 35/35 | branch `agent/wp0-fastapi-contract`，head `19d0751e9dda6f7d9ebf3128ff3aa7b945be3b0e`；主要實作 commit `2c46c834d8d1aef170dc4862101db02cb536e3ca`。 |
| 測試 | 25/25 | PR 記錄 76 passed；驗收分支 Actions backend、frontend、repository-hygiene 全部成功，包含 credential scan 與完整 Git 歷史差異檢查。 |
| E2E／驗收 | 14/15 | 受控 production synthetic write E2E 已完成 upload／approve／ingest、Neo4j 1/1/1、Qdrant 4/4 cleanup、submission 404、Health／rollback PASS；未使用真實使用者資料或儀器。仍保留 1 分作為正式入口與長期 artifact 限制。 |
| PR／合併／文件／回滾 | 5/10 | [PR #5](https://github.com/kyocarlos/knowledge-base-agent-source/pull/5) 已由 Owner Acceptance，exact-head CI 全部通過，並於 2026-08-20 合併至 `agent/km-plan-v2.6-anderson`，merge commit `eb1eb9253dd689eac8cd7796646f98321ad454af`。仍保留個人開發無獨立 Reviewer 及正式長期 artifact 的限制。 |

總分：**94/100**。WP0 已完成本輪 Owner Acceptance 與 v2.6 整合；仍保留正式入口長期 artifact 與獨立 Reviewer 限制，不宣稱無條件 100%。

CI：原始失敗證據 [WP0 run 31405151388](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/31405151388)；修正後成功證據 [WP0 run 31466582947](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/31466582947)。

## v2.6 歸類

- `A`：FastAPI application shell、versioned router、統一 response／error／trace、secret-safe exception、legacy compatibility 與對應測試可直接保留。
- `B`：原 PR 使用的 REQ／ADR 編號沿用舊規劃；後續驗收以 v2.6 `REQ-API-001` 與 Phase 1 前置工作重新追溯，不改寫既有 commit。
- `A`：原 repository-hygiene 使用 shallow checkout 的問題已以完整 checkout 修正；PR #5 exact-head CI 全部成功，並已由 Owner Acceptance 後合併至 v2.6 base。
- `D`：CSIT Web、DB Schema、Workflow 與商業邏輯不屬於 WP0／Anderson，不納入完成率。
- `E`：`01_AI_KM_Phase規劃_v2.6.xlsx` 尚未存在於 Git，不能認定規劃來源 Gate 已完成。

## 2026-08-20 cutoff 後補充證據

- Production synthetic write E2E 已完成，使用 pinned image `kb-wp01-e2e:20260820-cleanup-fix`，run `TR-E2E-WP0-20260820-PROD-CLEANUP-FIX-001`。
- Upload `202`、approve `200`、ingest `completed`；Neo4j TestRun/TestCase/Measurement `1/1/1`；Qdrant scoped points `4`，cleanup 刪除 `4`；cleanup 後 submission `404`，Qdrant post-check 剩餘 `0`。
- Production synthetic window 結束後已 rollback 至 pre-WP01 checkpoint，Health PASS，E2E flags disabled。未使用真實使用者資料，未操作真實儀器。
- Evidence：[production E2E](../../../outputs/wp0-write-e2e-20260819/production-write-e2e-cleanup-fix-20260820.json)、[Qdrant diagnosis](../../../outputs/wp0-write-e2e-20260819/production-qdrant-resolution-diagnosis-20260820.json)、[rollback](../../../outputs/wp0-write-e2e-20260819/rollback-shadow-evidence-20260819.json)。
- 此證據產生於 W33 cutoff 之後，現已補上 PR #5 Owner Acceptance、exact-head CI 與 merge evidence；本次驗收更新 WP0 為 **94/100**。

## 2026-08-20 merge evidence

- PR #5 head `2b60cfb10aca41ef7c29bd63c461544800c0aa97` 已合併至 `agent/km-plan-v2.6-anderson`。
- Merge commit：`eb1eb9253dd689eac8cd7796646f98321ad454af`。
