# WP0 Evidence — FastAPI contract 與測試基線

統計截止：2026-08-12 17:00 Asia/Taipei

| 類別 | 得分／權重 | 證據與限制 |
|---|---:|---|
| 規格與 Contract | 15/15 | REQ-API-001、REQ-API-002、REQ-OPS-001；PR #2 描述具 ADR、相容與回滾。 |
| 程式實作 | 35/35 | branch `agent/wp0-fastapi-contract`，head `19d0751e9dda6f7d9ebf3128ff3aa7b945be3b0e`；主要實作 commit `2c46c834d8d1aef170dc4862101db02cb536e3ca`。 |
| 測試 | 22/25 | PR 記錄 76 passed；Actions backend、frontend 成功，但 hygiene job 因 shallow checkout 缺少 base commit 而失敗，credential scan 被跳過。 |
| E2E／驗收 | 7/15 | PR 記錄本機 Uvicorn、release package、Webwright Portal smoke；未部署正式 `61.216.9.52:3030`，無 GitHub artifact。 |
| PR／合併／文件／回滾 | 3/10 | [PR #2](https://github.com/kyocarlos/knowledge-base-agent-source/pull/2) open、非 draft、無 review、未合併；PR 有 rollback 說明。 |

總分：**82/100**。不可宣稱完成，主要 Gate 缺口為既有 PR CI overall failure、review 與 merge。

CI：[WP0 run 31405151388](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/31405151388)。

## v2.6 歸類

- `A`：FastAPI application shell、versioned router、統一 response／error／trace、secret-safe exception、legacy compatibility 與對應測試可直接保留。
- `B`：原 PR 使用的 REQ／ADR 編號沿用舊規劃；後續驗收以 v2.6 `REQ-API-001` 與 Phase 1 前置工作重新追溯，不改寫既有 commit。
- `C`：repository-hygiene 使用 shallow checkout，對 base SHA 執行 diff 時發生 `fatal: bad object`；另無 review／merge、未完成正式入口 E2E 與可下載驗收 artifact。驗收分支已改用 `fetch-depth: 0`，仍須以新 CI run 證明修正。
- `D`：CSIT Web、DB Schema、Workflow 與商業邏輯不屬於 WP0／Anderson，不納入完成率。
- `E`：`01_AI_KM_Phase規劃_v2.6.xlsx` 尚未存在於 Git，不能認定規劃來源 Gate 已完成。
