# Release Pipeline

這個目錄只負責產生獨立的 B2B/on-prem 安裝包，不會修改原始系統檔案。

## 產線目標

- 以獨立 bundle 輸出 install package
- 每次 build 都會寫入 release version / git commit / package format metadata
- package 內含自己的 `app/`、`runtime/`、`config overlay` 與 `OpenClaw overlay`
- 安裝後使用獨立的 Docker Compose project、獨立資料目錄與獨立前端 runtime
- 與原始 knowledge-base 系統完全隔離

## 目錄規則

- `app/`：release 用的應用程式副本
- `runtime/`：Docker Compose、Dockerfile、前端靜態檔、TLS 憑證、OpenClaw overlay
- `config/`：安裝後生成的 overlay 設定
- `data/`：安裝後使用的資料根目錄
- `install.sh`：客戶端執行的安裝器
- `manifest.json`：發行資訊與內容清單
- `release-info.json`：可直接讀取的版本資訊

## 建置方式

在專案根目錄執行：

```bash
./release/build_release.sh
```

完成後會在 `release/dist/` 產生一份 `.tar.gz` 安裝包。
完整的非技術人員安裝說明請看 `docs/onprem-install-guide.md`。

## 安裝方式

1. 解壓安裝包。
2. 執行 `install.sh`。
3. 互動式問答會依序確認：
   - 安裝路徑
   - Compose project name
   - HTTPS port
   - Neo4j 密碼
   - Ollama endpoint
   - OpenClaw gateway
   - 是否自訂 OpenClaw 身分值
   - 是否匯入資料 bundle
   - 是否匯入 OpenClaw bundle
   - 若主機上已存在 `~/.openclaw/identity`，安裝器會自動同步它到 release runtime
4. 如有需要，仍可透過參數指定：
   - 安裝路徑
   - Web port
   - Neo4j 密碼
   - Ollama endpoint
   - OpenClaw overlay / session key
   - 客戶資料 bundle
   - `--auto-install-deps` 讓 installer 在有權限時嘗試補裝缺少的系統依賴
   - `--check-only` 只做前置條件掃描，不會進入安裝、不會補裝、不會改寫任何檔案
   - `--offline` 完全停用網路補裝；若有缺件會直接失敗，不會嘗試 apt-get 或其他線上修復
5. 若偵測到既有安裝，install.sh 會走升級流程：
   - 讀取現有 `install-state.env`
   - 保留 `app/data`、`app/config/config.yaml`、`runtime/openclaw`
   - 先建立升級備份
   - 再套用新版本的 app / runtime payload

## 前置條件掃描

- 安裝器啟動後會先掃描必要依賴
- 會顯示每個元件是否可用，以及缺少的項目
- 若是互動式執行，會先詢問是否嘗試自動補裝
- 若提供 `--auto-install-deps`，則會直接嘗試補裝可由系統套件管理的依賴
- 若提供 `--check-only`，則只輸出前置條件掃描結果並結束，exit code 會反映是否缺少必要元件
- 若提供 `--offline`，則完全不會嘗試網路補裝；若必要元件缺失，安裝器會在進入安裝前直接停止
- 若同時提供 `--offline` 與 `--auto-install-deps`，以 `--offline` 為準，安裝器只會掃描與報告，不會進行線上修復
- 自動補裝目前以 Debian / Ubuntu 的 `apt-get` 為主，其他發行版會退回純檢查模式
- OpenClaw 主機 nginx 站台預設不會被修改；若要讓 installer 自動建立 `https://<host>:18789` 的對外入口，必須明確加上 `--configure-openclaw-nginx`
- 若啟用 `--configure-openclaw-nginx`，可再搭配 `--openclaw-nginx-listen-ip`、`--openclaw-nginx-listen-port`、`--openclaw-nginx-backend-host`、`--openclaw-nginx-backend-port` 調整對外 listen 與反代目標
- 若 OpenClaw 與 KB 安裝在同一台主機，installer 會把 OpenClaw gateway 預設值正規化為本機 IP + 18790，而不是舊的 `127.0.0.1:18789`

## 版本與升級

- `manifest.json` 會記錄 `format_version`、`release_version`、`release_channel`、`git_commit` 與 `created_at`
- `release-info.json` 會在 package root 與安裝後 root 各存一份
- 安裝後會在目標根目錄寫入：
  - `install-state.env`
  - `release-info.json`
- 升級時只會更新 release payload，不會主動覆寫客戶資料與 OpenClaw overlay
- 若要完全重建，可刪除安裝目錄後重新執行 installer
- 若 target 主機已裝好 OpenClaw，installer 會優先沿用主機的 `~/.openclaw/identity`，避免手動搬移私鑰與公鑰

## 隔離原則

- 不沿用原始 repo 的啟動腳本
- 不沿用原始系統的 container name
- 不沿用原始系統的 host path
- 不沿用原始系統的 runtime directory
- 不依賴原始系統既有容器或服務
