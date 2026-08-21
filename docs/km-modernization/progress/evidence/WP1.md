# WP1 Evidence — Docker／Redis／Celery／Config 正式化

統計截止：2026-08-12 17:00 Asia/Taipei；合併驗收更新：2026-08-20

| 類別 | 得分／權重 | 證據與限制 |
|---|---:|---|
| 規格與 Contract | 15/15 | REQ-JOB-001、REQ-JOB-002、REQ-OPS-001；typed config、Job status、queue/retry contract。 |
| 程式實作 | 35/35 | branch `agent/wp1-job-config-reliability`，head `cfe5eb0d6a463aa4ddfc6e3a936e2f4a8974109a`。 |
| 測試 | 25/25 | 本地 83 passed；GitHub Actions backend、frontend、repository-hygiene 全部成功。 |
| E2E／驗收 | 10/15 | 隔離 Compose 實測 worker restart、Redis persistence、真實 ingest idempotency；未完成正式部署長時間故障注入與 backup/restore。 |
| PR／合併／文件／回滾 | 6/10 | [PR #5](https://github.com/kyocarlos/knowledge-base-agent-source/pull/5) 已由 Owner Acceptance，exact-head CI 全部通過，並於 2026-08-20 合併至 `agent/km-plan-v2.6-anderson`，merge commit `eb1eb9253dd689eac8cd7796646f98321ad454af`；WP1 後續獨立 closure PR #9 仍為 Draft，且 system recovery matrix 尚有 PENDING 項目。 |

暫定總分：**96/100**。WP1 已完成原 v2.6 Owner Acceptance 與整合；目前 closure PR #9 仍在 Final Review，application-level idempotency shadow 已通過，但 system recovery coverage matrix 尚有 PENDING 項目，不宣稱無條件 100%。

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

## 2026-08-20 WP1 Final Closure 補充

- In-flight recovery：isolated shadow PASS；worker 中止後由 application lease recovery 接手 attempt 2，side effect count=`1`，無重複完成。
- Application/business-flow idempotency：isolated shadow PASS；四個 concurrent duplicate submissions 只有一個 live owner，recovery attempt=`2`，late duplicate claim=`false`，final ledger=`succeeded`。
- Evidence：`outputs/inflight-job-recovery-final-shadow-20260820.json` SHA-256=`5db86c8016c75ca4880e0825d67ff08ef8f9871723a770b4882ef5f5280f9f8a`；`outputs/wp1-application-idempotency-shadow-20260820/application-idempotency-shadow-20260820.json` SHA-256=`d11cec9a796ec091c5e5b7d21751b2baa6e937b2f87d82bc8d01cd0dc8b1c6fc`。
- System recovery coverage matrix：overall=`PENDING`。filesystem/data=`PASS`；application registry/database、Neo4j、Qdrant、Redis 完整 restore、configuration=`PENDING`。完整矩陣見 `docs/km-modernization/progress/evidence/WP1-system-recovery-coverage-matrix-20260820.md`，JSON SHA-256=`05e347a3b6cc471343ceacadde434f4a33afae7eada5c294edefb966b5e4d63f`。
- PR #9：`agent/wp1-reliability-closure`，Final Review source head=`fefcc857ee3d3e8531154b5f3b98f38878c93423`，Draft/open，未合併。Production Gate=`NO-GO`。
- Source-of-truth identities：`reviewed commit = CI commit = evidence commit = fefcc857ee3d3e8531154b5f3b98f38878c93423`。本次文件修正的 Git commit 另由 Git history 保存，不取代該 Final Review source identity。

## 2026-08-21 deployment evidence boundary

- 主機曾完成一次 WP0/WP1 release deployment，實際 release source=`5c7ea2dac186bd906a4d7df64db25d55133674cc`，live tag=`kb-wp01-live:65b490df126a-20260821110939`；該 source 不是 PR #9 head，因此不能宣稱 PR #9 已完成 production acceptance。
- Web image digest=`sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`；search worker=`sha256:af2948686fe51e24cb0cf83eda97e6371ddb1bb19d4ec6568ae38fd89420195e`；ingest worker=`sha256:ecf5d163fa3f8f48afe2b585bb9d8894e6e4c6501712e5663ba0b900a64991a0`；beat=`sha256:a4a9d69cadf3f6d48a3dc282899b3e3a172af557046a25df57eb77d45d6a53e1`。
- Backup checkpoint=`/home/da40_ai_gb10/kb-pre-wp01-backups/pre-deploy-wp01-maintenance-20260821-102314`；checkpoint SHA-256=`65e167878d88bfddb7dd1655d485ed5fcbbac0a5883bdc550d14d4bcf42b0327`；rollback drill=`/home/da40_ai_gb10/kb-pre-wp01-drills/20260821_100839/rollback-drill.json`，結果 PASS。
- Health／Version、Celery worker/queue、JobConfig、Beat、WebSocket、Qdrant、Ollama gates 已觀測 PASS；Chat read-only flow 已完成。Upload/Ingest、Report Review、synthetic production run_id、deployment-specific cleanup 及本次 deployment 的精確結束時間沒有形成完整可下載 evidence，故標示為 `PENDING`，不推升 WP1 或關閉 Production Gate。
- 完整 machine-readable deployment boundary record：[WP1-production-deployment-20260821.json](WP1-production-deployment-20260821.json)。
- Production attribution review：PR #9 reviewed source=`fefcc857ee3d3e8531154b5f3b98f38878c93423` 與 deployed source=`5c7ea2dac186bd906a4d7df64db25d55133674cc` 共有祖先但有 93 個檔案差異，包含 application/runtime/test 變更，不能視為 deployment-only fix；`accepted_for_pr9=false`。詳見 [WP1-production-attribution-review-20260821.json](WP1-production-attribution-review-20260821.json)。
