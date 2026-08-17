# WP1 Evidence — Docker／Redis／Celery／Config 正式化

統計截止：2026-08-12 17:00 Asia/Taipei

| 類別 | 得分／權重 | 證據與限制 |
|---|---:|---|
| 規格與 Contract | 15/15 | REQ-JOB-001、REQ-JOB-002、REQ-OPS-001；typed config、Job status、queue/retry contract。 |
| 程式實作 | 35/35 | branch `agent/wp1-job-config-reliability`，head `cfe5eb0d6a463aa4ddfc6e3a936e2f4a8974109a`。 |
| 測試 | 25/25 | Draft acceptance PR #5 的 GitHub Actions backend 實測 `83 passed`；frontend、repository-hygiene 全部成功。`90 passed` 僅見於部署紀錄敘述，未附可下載的去識別化原始 artifact，故不採計為 GitHub 驗收數字。 |
| E2E／驗收 | 10/15 | 隔離 Compose 實測 worker restart、Redis persistence、真實 ingest idempotency；production deployment／rollback／Webwright 原始證據仍位於主機 `$HOME`／`/tmp`，未形成 GitHub 或去識別化 artifact，且未完成長時間故障注入與 backup/restore。 |
| PR／合併／文件／回滾 | 2/10 | 已有 [Draft acceptance PR #5](https://github.com/kyocarlos/knowledge-base-agent-source/pull/5)，但沒有 WP1 獨立交付 PR、review 或 merge；回滾 runbook 已入庫，production rollback 原始 artifact 未入庫。 |

總分：**87/100**。不可宣稱完成，主要 Gate 缺口為 PR/review/merge 與正式環境故障演練。

CI：原 WP1 分支 [run 31449165822](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/31449165822)；v2.6 驗收分支 [run 31466582953](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/31466582953)，兩者 backend、frontend、repository-hygiene 均成功。

## v2.6 歸類

- `A`：typed job config、queue routing、canonical job status、trace header、retry taxonomy、Redis idempotency、worker restart/health 修正及 CI 可直接保留。
- `B`：原工作包的 Phase 0、REQ-JOB-002／REQ-OPS-001 命名改按 v2.6 歸入 Phase 1 前置與 `REQ-JOB-001`；保留原 commit 歷史。
- `C`：已有 Draft acceptance PR #5，但沒有 WP1 獨立交付 PR、review 或 merge；缺正式環境長時間故障注入與 backup/restore 驗收。
- `D`：CSIT Workflow、正式商業狀態與 Schema 由 Patty 負責，不由 WP1 擴張實作。
- `B`：來源 v2.6 Excel 已納入 `docs/km-modernization/source/KM_Modify/` 並可核對；隔離 runtime 驗證仍沒有可下載的原始 run artifact，不能當成正式 Gate 完成證據。
