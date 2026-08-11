# WP0 Evidence — FastAPI contract 與測試基線

本週證據截止：2026-08-11 16:42 Asia/Taipei

| 類別 | 得分／權重 | 證據與限制 |
|---|---:|---|
| 規格與 Contract | 15/15 | v2.6 Excel「FastAPI／REST API 骨架」由 Anderson 主實作；REQ-API-001、REQ-API-002、REQ-OPS-001 與 ADR-002。 |
| 程式實作 | 35/35 | 原 WP0 `2c46c834`；live integration `3f93beef`；production rollout 同步分支 `agent/wp01-production-rollout`。 |
| 測試 | 25/25 | 驗收分支 Actions backend／frontend／repository-hygiene 成功；rollout 分支 pytest `90 passed`、frontend build、compile、Compose、shell、credential scan 通過。 |
| E2E／驗收 | 13/15 | production legacy health、v1 health/live/ready/version、agent auth contract、search 與 Webwright chat 通過；Webwright 原始 run 仍只在部署主機，尚未形成 GitHub artifact。 |
| PR／合併／文件／回滾 | 6/10 | PR #2 與 Draft PR #5 歷史保留；部署與 rollback 文件、乾淨同步分支已進 GitHub；尚無 rollout PR review／merge。 |

總分：**94/100**。已在真實系統運行，但未 Review／Merge，不得宣稱 GitHub Gate 完成或 100%。

## 本週新增證據

- 正式入口 `/health` 與 `/api/v1/health`、live、ready、version 均為 HTTP 200。
- 未帶 Agent headers 的 `/api/agent/v1/health` 維持既有 HTTP 401 contract。
- Webwright 以 `https://61.216.9.52:3030/chat.html` 完成連線、送出與非空回覆；console／failed network 均為 0。
- pre-WP01 checkpoint、shadow rollback、production rollback 與第二次部署均記錄於 `docs/pre-wp01-deployment-record-20260811.md`。
- GitHub rollout branch head：`10706a5780d105427b1dc1e38b701023336fe26f`。

## 截止後 CI

- rollout commit `dce63ae6` 的 WP0 run `31475084397`：backend、frontend、repository-hygiene 全部成功。
- Weekly run `31475084373`：v2.6 source／JSON 驗證與 Phase 1 PPTX candidate artifact 產生成功。

## v2.6 歸類

- `A`：FastAPI shell、versioned router、統一 response／error／trace、secret-safe exception、legacy compatibility 與測試可保留。
- `B`：舊 Phase 0 命名改列 Phase 1 前置；保留原 commit 歷史。
- `C`：缺 rollout PR review／merge 與 durable Webwright artifact。
- `D`：CSIT Web、DB Schema、Workflow 與商業邏輯由 Patty 負責，不納入 WP0。
- v2.6 Excel 已納入 Git並核對 SHA，原本的來源缺失 Gate 已解除。
