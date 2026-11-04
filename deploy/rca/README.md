# RCA(階段 A)TEST 資料區部署記錄 — 2026-11-04

使用者授權直接上線。只動 TEST 平面(kb-web、kb-timescaledb);da40 平面與其他容器沒有變動。

| 項目 | 內容 |
|---|---|
| 新映像 | `km-chat-v2-secure:rca-20261104-on-open-files-c7869ce`(疊加在 `…open-files-20261031-on-feed-c7869ce` 上,sha256:6fff8963…),只加入 compare.py、rca.py、rca_routes.py 與有開關的路由註冊(以 `patch_register.py` 在映像內插入,不覆蓋既有 `__init__.py`) |
| 資料庫 | `kb-timescaledb` / `kb_timeseries`:建立 `km_test` schema(原本不存在)並匯入 13 份真實報告(`tools/rca_demo/import_reports.py` 解析後以 pg_dump 匯出,單一交易);新增唯讀角色 `km_rca_ro`(只能 SELECT km_test,連線上限 8,語句逾時 15 秒) |
| 容器設定 | `KM_RCA_ENABLED=1`、`KM_RCA_DSN_FILE=/run/secrets/km-rca-dsn`(唯讀掛載,檔案在 `~/.km-control/rca-deploy-20261104/`,不進 git)、`KM_RCA_ROLES=CSIT_ENGINEER,CSIT_MANAGER` |
| nginx | 不需要改(`location /api/` 已轉給 web) |
| 回滾 | `bash ~/.km-control/open-files-deploy-20261031/deploy.sh test ~/.km-control/compose/kb-test.open-files.image.override.yml`;資料可 `DROP SCHEMA km_test CASCADE`、`DROP ROLE km_rca_ro` |

## 已驗證(在新容器內)
- `/api/rca/v1/runs|compare|analyze` 三條路由已註冊;資料路徑(DSN 檔、網路、唯讀角色)正常
- 以真實報告比較:Throughput 兩份 165 筆對齊、RvR 三份 538 筆對齊,與本機結果相同
- 唯讀角色寫入被拒;讀其他 schema/資料表被拒;不同類型報告、不存在的報告回 422
- 既有 7 個掛載不變,健康檢查正常

## 未驗證
- 登入後的完整畫面(需要真實登入帳號);da40 資料區的使用者連到產品驗證專區時,會得到「RCA 後端尚未啟用」(da40 尚未部署)
- `/analyze`(LLM)尚未部署到這個容器的工作流程,階段 B 處理
