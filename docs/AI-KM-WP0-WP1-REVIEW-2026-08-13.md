# AI KM WP0／WP1 主管 Review Index

日期：2026-08-13  
本次發布範圍：只更新 WP0 與 WP1，並補齊 v2.6 原始規劃與進度依據。
本次不納入：A2A 新功能、R0/R1/R2 real-run、Anritsu OpenClaw 延伸功能及其他後續 WP。

## 目前結論

```text
WP0：85%，CI green；尚未完成 review、merge、正式入口 E2E artifact
WP1：87%，CI green；尚未完成 PR、review、merge、正式環境故障與 backup/restore 證據
WP2 以後：本次不執行、不宣稱有進度
```

完整 v2.6 原始資料已納入 `docs/km-modernization/source/KM_Modify/`，來源檔案、SHA-256、用途與 Phase/WP 對應見 [`docs/km-modernization/07-v2.6-source-index.md`](km-modernization/07-v2.6-source-index.md)。

進度採既有加權規則：規格與 Contract 15%、程式實作 35%、測試 25%、E2E/驗收 15%、PR/review/merge/文件/回滾 10%。沒有證據的項目不計入完成率。

## WP0 證據

- 實作分支：`agent/wp0-fastapi-contract`
- 實作 commit：`2c46c834d8d1aef170dc4862101db02cb536e3ca`
- 最新分支 HEAD：`19d0751e9dda6f7d9ebf3128ff3aa7b945be3b0e`
- PR：[#2](https://github.com/kyocarlos/knowledge-base-agent-source/pull/2)，目前未合併、尚無 review
- CI 成功：[WP0 run 31466582947](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/31466582947)
- 實作範圍：FastAPI application shell、versioned router、統一 response/error/trace、secret-safe exception、legacy compatibility、測試基線。
- 限制：尚缺正式 `61.216.9.52:3030` 入口 E2E artifact、PR review 與 merge。

## WP1 證據

- 實作分支：`agent/wp1-job-config-reliability`
- 最新分支 HEAD：`cfe5eb0d6a463aa4ddfc6e3a936e2f4a8974109a`
- PR：GitHub 目前查無 WP1 PR，未宣稱已 review 或 merge
- CI：[WP1 run 31449165822](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/31449165822)、[v2.6 acceptance run 31466582953](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/31466582953)
- 實作範圍：typed JobConfig、canonical job status、queue routing、retry taxonomy、trace propagation、Redis idempotency、worker restart/health 與相關測試。
- 限制：尚缺正式環境長時間故障注入、backup/restore 證據、PR review 與 merge。

## GitHub 內可直接閱讀的證據

- `docs/km-modernization/progress/evidence/WP0.md`
- `docs/km-modernization/progress/evidence/WP1.md`
- `docs/km-modernization/progress/evidence/WP0-WP1-v2.6-gap-assessment.md`
- `docs/km-modernization/progress/weekly/2026-W33.md`
- `docs/km-modernization/progress/data/2026-W33.json`
- `docs/km-modernization/progress/presentations/AI-KM-Weekly-2026-W33.pptx`
- `docs/km-modernization/06-v2.6-anderson-scope.md`
- `docs/km-modernization/07-v2.6-source-index.md`
- `docs/km-modernization/source/KM_Modify/`（5 份規劃 Excel、5 份技術規格 DOCX、2 張原始圖）

主管若要看簡報，可下載：

`docs/km-modernization/progress/presentations/AI-KM-Weekly-2026-W33.pptx`

本週 v2.6 主管版正式簡報：

`docs/AI-KM-Phase1-Weekly-2026-W33-v2.6.pptx`

下載連結：[AI-KM-Phase1-Weekly-2026-W33-v2.6.pptx](AI-KM-Phase1-Weekly-2026-W33-v2.6.pptx)

正式簡報發布規則：以 `/home/da40_ai_gb10/knowledge-base/AI-KM-Phase1-Weekly-YYYY-Www-v2.6.pptx` 為來源，確認可開啟與 SHA-256 後複製至本分支 `docs/` 再提交；每週建立新檔名，不覆蓋歷史週次。W33 主機檔與 GitHub 檔案 SHA-256 均為 `c5ceb4093dd7dc1b3b44fad7e24ee7b85b6bcba75b3a553269f27a028d017979`。

## 本次明確不應作出的結論

1. 不得因 CI green 宣稱 WP0/WP1 已 100% 完成。
2. 不得把 v2.6 基準中原本已存在的 A2A 檔案，當成本次 WP0/WP1 新增進度。
3. 不得在本分支宣稱已完成 A2A、Anritsu 真實測試或後續 WP。
4. CSIT Web、DB Schema、Workflow 與正式商業邏輯仍屬 Patty 責任範圍。

## Review 建議

主管或 review agent 請優先檢查：

1. WP0/WP1 的 branch、commit、CI 與 evidence 是否一致。
2. 85%／87% 是否符合加權規則及缺口證據。
3. WP0 PR #2 與 WP1 PR/review/merge Gate 是否關閉。
4. 既有 Portal、chat、search、report、review、ingest 是否維持相容。
5. 後續是否應先補 PR 與正式驗收，再開始 WP2。

## 每週固定更新方式

每週四報告前，週三 17:00 統計截止，17:10 由 GitHub Actions 產生候選 artifact。人工核對通過後，將該週簡報以新檔名提交到 `docs/AI-KM-Phase1-Weekly-YYYY-Www-v2.6.pptx`；同一 commit 更新該週 `progress/data`、`progress/weekly` 與 Evidence。歷史週次不覆蓋，候選失敗不影響前週正式簡報。

## 本次本機重跑

在乾淨 review worktree 使用 `requirements.txt` 重跑 WP0/WP1 focused tests：`18 passed, 1 failed`。唯一失敗為 `test_legacy_business_and_websocket_routes_are_registered_once`，在此 worktree 的 test settings 下缺少 `/api/agent/v1/reports` route；沒有因此修改既有程式。GitHub v2.6 acceptance 的既有 CI 證據仍以 WP0 run `31466582947` 與 WP1 run `31466582953` 為準，主管 review 時應同時檢查該差異。
