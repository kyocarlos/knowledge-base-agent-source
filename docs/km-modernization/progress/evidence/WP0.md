# WP0 Evidence — FastAPI contract 與測試基線

統計截止：2026-08-17 Asia/Taipei

| 類別 | 得分／權重 | 證據與限制 |
|---|---:|---|
| 規格與 Contract | 15/15 | REQ-API-001、REQ-API-002、REQ-OPS-001；PR #2 描述具 ADR、相容與回滾。 |
| 程式實作 | 35/35 | PR #2 最新 head 為 `ccdfd8cdf29dabc5a5ac2706cd20b26ec7973c21`（branch `agent/wp0-fastapi-contract`）；主要實作與相容層已在該 head 可核對。 |
| 測試 | 25/25 | CI run [31992802540](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/31992802540) 全部 job success；E2E artifact [9275878943](https://github.com/kyocarlos/knowledge-base-agent-source/actions/artifacts/9275878943) 對應 head SHA `ccdfd8c`。 |
| E2E／驗收 | 7/15 | Health/Version 與 Chat/Search/Upload/Report Review 僅完成 route load + redacted screenshot，均 PASS。WebSocket、Chat submit、Search submit 為 SKIP；Upload/Ingest 寫入與 Report approve/reject 為 SKIP_WRITE_PATH，因無 disposable fixture／cleanup／scoped token。這不是完整正式 E2E，故不提高本項分數。 |
| PR／合併／文件／回滾 | 3/10 | [PR #2](https://github.com/kyocarlos/knowledge-base-agent-source/pull/2) 仍 open、未 merge；Owner Acceptance review id `4948316961` 明確為 `NO-GO`，不是 acceptance。舊 base `agent/km-modify-codex-plan` 與 v2.6 acceptance [PR #5](https://github.com/kyocarlos/knowledge-base-agent-source/pull/5) 的整合決策仍未關閉。回滾 runbook 已入庫，production rollback 原始 artifact 未入庫。 |

總分：**85/100**。不可宣稱完成；維持 85 分，直到 Owner Acceptance、正確整合、完整功能 E2E 關閉。主要 Gate 缺口為 Owner Acceptance、merge、正式入口 E2E 與可下載驗收 artifact。

Artifact [9275878943](https://github.com/kyocarlos/knowledge-base-agent-source/actions/artifacts/9275878943) 暫存至 **2026-08-24**；永久驗收前必須保存去識別化副本或重跑，不能將目前 artifact 視為永久證據。

## v2.6 歸類

- `A`：FastAPI application shell、versioned router、統一 response／error／trace、secret-safe exception、legacy compatibility 與對應測試可直接保留。
- `B`：原 PR 使用的 REQ／ADR 編號沿用舊規劃；後續驗收以 v2.6 `REQ-API-001` 與 Phase 1 前置工作重新追溯，不改寫既有 commit。
- `C`：原 repository-hygiene 使用 shallow checkout，對 base SHA 執行 diff 時發生 `fatal: bad object`；驗收分支改用 `fetch-depth: 0` 後 CI run 31992802540 已全部 job success。Owner Acceptance review id `4948316961` 為 `NO-GO`，仍未完成 Owner Acceptance／merge，且未完成正式入口完整功能 E2E 與永久可下載驗收 artifact。
- `D`：CSIT Web、DB Schema、Workflow 與商業邏輯不屬於 WP0／Anderson，不納入完成率。
- `A`：`01_AI_KM_Phase規劃_v2.6.xlsx` 已納入 `docs/km-modernization/source/KM_Modify/`，SHA-256 已由來源索引登錄；這只代表規劃來源可核對，不代表 WP0 已完成。
