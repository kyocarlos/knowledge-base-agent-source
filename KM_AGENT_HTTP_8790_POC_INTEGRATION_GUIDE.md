# KM Agent 對接 Anritsu A2A HTTP 8790 POC 指南

更新日期：2026-08-13

## 1. 文件目的

本文件提供 KM Agent 在概念驗證階段直接呼叫 Anritsu A2A Sidecar 所需的固定契約與操作步驟。

POC 使用 Docker userspace Tailscale承載 HTTP TCP 8790，不需要正式DNS、TLS憑證或SSH TCP 22。
此模式僅允許 `dry_run=true`，不會控制儀器、不會啟動iPerf、不會產生正式Excel，也不會呼叫
KM ingest。禁止在Anritsu Windows主機直接執行`tailscale.exe up`；Windows實體gateway／DNS
`100.100.100.100`與Tailscale Quad100衝突，主機模式可能改動Windows路由與DNS。

## 2. 連線架構

```text
KM Agent / A2A Client
        |
        | KM tailnet + HTTP + A2A Bearer Token, TCP 8790
        v
http://<ANRITSU_DOCKER_TAILSCALE_IP>:8790
        |
        v
Anritsu Docker userspace Tailscale + A2A Sidecar（dry-run only）
```

此 HTTP POC 只允許通過同一個受控 Tailscale tailnet 傳輸，不得從公開 Internet 直接開放
TCP 8790。KM 節點目前的 Tailscale IP 是 `100.65.63.58`；Anritsu 加入此 tailnet 後，必須
重新回報實際 Tailscale IP／MagicDNS 名稱，不得假設原本位於其他 tailnet 的 IP 一定維持不變。

端點由Anritsu完成Docker授權後回報，不得沿用Windows實體網路中的舊`100.100.100.51`：

| 用途 | URL |
| --- | --- |
| Health | `http://<ANRITSU_DOCKER_TAILSCALE_IP>:8790/health`、`/healthz` |
| Agent Card | `http://<ANRITSU_DOCKER_TAILSCALE_IP>:8790/.well-known/agent-card.json` |
| A2A JSONRPC | `http://<ANRITSU_DOCKER_TAILSCALE_IP>:8790/a2a` |

## 3. 已完成的 Anritsu 修改

- 新增明確 POC 開關 `ANRITSU_A2A_ALLOW_INSECURE_HTTP=true`。
- Sidecar透過Docker userspace Tailscale對tailnet提供TCP 8790，不修改Windows host路由或DNS。
- Agent Card interface在授權時更新為`http://<ANRITSU_DOCKER_TAILSCALE_IP>:8790/a2a`。
- `Manage-A2ADockerTailscalePoc.ps1 -Action Authorize`以read-only Docker secret注入Tailscale key，
  完成後清除容器內`TS_AUTHKEY`／secret與Windows暫存key。
- HTTP 只允許搭配 `ANRITSU_A2A_MODE=dry-run`。
- 關閉 POC 開關後，HTTP URL 會被拒絕，原本 HTTPS 強制規則仍然保留。
- Bearer Token、scope、固定 Job Schema、冪等與 SQLite journal 均保留。
- 缺 Token 回 HTTP 401；錯 Token或 scope 不足回 HTTP 403。
- 已驗證合法 Token dry-run 可完成，七類禁止副作用計數全部為 0。

## 4. KM 必須完成的修改

KM A2A Client／bridge 建議映射以下設定；實際環境變數名稱可依 KM 現有設定系統調整，但值與語意不可改變：

```text
ANRITSU_A2A_DISCOVERY_BASE_URL=http://<ANRITSU_DOCKER_TAILSCALE_IP>:8790
ANRITSU_A2A_PROFILE_ID=ncq2200b2v-throughput-v1
ANRITSU_A2A_PROTOCOL_VERSION=1.0
ANRITSU_A2A_BINDING=JSONRPC
ANRITSU_A2A_MODE=sdk-dry-run
```

KM 端需要：

1. 先讀取 Agent Card，不要在程式中自行拼接假的 skill 或 endpoint。
2. 從 `supportedInterfaces` 選擇 `JSONRPC`、protocol version `1.0` 的 interface。
3. 呼叫 `/a2a` 時加入 `Authorization: Bearer <TOKEN>`。
4. 加入 `A2A-Version: 1.0`。
5. 只送本文件定義的固定 JSON，不允許 LLM 增加 command、path、URL、SCPI 或 extra fields。
6. 將連線 timeout、A2A rejection 與業務狀態分開記錄。

## 5. Bearer Token 配置

SSH TCP 22 不是 A2A 執行條件，也不需要為本次 POC 開放。建議由 KM 主機產生 Token，明文只保存在 KM：

```bash
umask 077
TOKEN=$(openssl rand -hex 32)
printf '%s' "$TOKEN" > /home/da40_ai_gb10/knowledge-base/.anritsu-a2a-poc-token
HASH=$(printf '%s' "$TOKEN" | sha256sum | awk '{print $1}')
printf 'Anritsu registration SHA256: %s\n' "$HASH"
unset TOKEN
```

處理原則：

- KM 將明文檔案權限維持為 `0600`。
- 只把 SHA-256 hash 提供給 Anritsu operator 註冊。
- 不要把明文 Token 傳給 Anritsu、貼到聊天、Git、Email 或文件。
- Anritsu Sidecar 只保存 hash，不需要取得 KM 的明文 Token。
- KM bridge 從受控 secret file 或 secret manager 讀取明文。
- 完成新 Token 切換後，撤銷 Anritsu 目前未交付 KM 的舊 Token rule。

## 6. 固定 Job Schema

KM 只允許傳送以下欄位：

```json
{
  "job_schema_version": "1.0",
  "dry_run": true,
  "job_type": "run_iperf_test",
  "environment": "anritsu",
  "profile_id": "ncq2200b2v-throughput-v1",
  "run_id": "run-20260812-001",
  "requested_by": "km-agent-01",
  "duration_seconds": 60,
  "test_cases": ["sa_dl_tcp"]
}
```

限制：

| 欄位 | 限制 |
| --- | --- |
| `job_schema_version` | 固定 `1.0` |
| `dry_run` | 必須為 `true` |
| `job_type` | 固定 `run_iperf_test` |
| `environment` | 固定 `anritsu` |
| `profile_id` | 固定 `ncq2200b2v-throughput-v1` |
| `run_id` | 1 到 128 字元，只允許英數、`.`、`_`、`:`、`-` |
| `requested_by` | 1 到 128 字元，只允許英數、`.`、`_`、`:`、`@`、`-` |
| `duration_seconds` | `1..3600` |
| `test_cases` | `sa_dl_tcp`、`sa_ul_tcp`，最多兩項且不得重複 |

任何額外欄位都會拒絕，包括任意 PowerShell、Python、SCPI、檔案路徑與 callback URL。

### 6.1 age 加密交付至 Docker 授權腳本

Anritsu提供的公開recipient檔為`anritsu-a2a-poc-age-recipient.txt`，其內容必須與帶外確認值
完全一致：

```text
age1euwarvhxvztz2nryglypagc3rcgakh8wp24lhs687p9h429dhszsqrz4hm
```

公開recipient不是秘密；Anritsu私鑰不得離開Windows受限路徑。KM以官方age 1.3.1 ARM64
binary加密：

```bash
SOURCE=/home/da40_ai_gb10/.local/state/km-a2a/tailscale-anritsu-a2a-poc-auth-key
OUTPUT=/home/da40_ai_gb10/.local/state/km-a2a/tailscale-anritsu-a2a-poc-auth-key-r3.age
RECIPIENT_FILE=/home/da40_ai_gb10/knowledge-base/anritsu-a2a-poc-age-recipient.txt

umask 077
/home/da40_ai_gb10/.local/bin/age --encrypt \
  --recipients-file "$RECIPIENT_FILE" \
  --output "$OUTPUT" \
  "$SOURCE"
chmod 600 "$OUTPUT"
```

第一把狀態不明的 single-use key 已撤銷；第二份密文在 Anritsu 舊版流程中
於 Tailscale 認證前被清理。Anritsu 已修正 Compose stderr 判斷與失敗清理流程。
目前沿用的 single-use key 仍未使用，並於 2026-08-12 重新產生第三份密文；
明文來源檔未離開 KM：

```text
檔名：tailscale-anritsu-a2a-poc-auth-key-r3.age
大小：261 bytes
SHA-256：0b377e11ee6589127fa6c606ed7fc629aeef2bc860fe8ac4ad012487628a7644
age format：age-encryption.org/v1 / X25519 / payload 61 bytes
```

只能透過核准的AnyDesk File Transfer傳送`.age`密文；不得傳送無副檔名的明文來源檔。
AnyDesk完成訊息與遠端檔案列表已確認檔名及261-byte大小；Windows仍應先核對SHA-256，
再以系統管理員PowerShell執行：

```powershell
$CiphertextPath = 'C:\Users\SSNR\Documents\tailscale-anritsu-a2a-poc-auth-key-r3.age'

(Get-FileHash -Algorithm SHA256 -LiteralPath $CiphertextPath).Hash.ToLowerInvariant()

cd D:\Anritsu_Control_API

$ExpectedSha256 = '0b377e11ee6589127fa6c606ed7fc629aeef2bc860fe8ac4ad012487628a7644'

.\a2a-sidecar\scripts\Complete-A2ATailscalePocAuthorization.ps1 `
  -CiphertextPath $CiphertextPath `
  -ExpectedSha256 $ExpectedSha256
```

`Complete-A2ATailscalePocAuthorization.ps1`應整合既有安全檢查：拒絕非系統管理員、reparse point、
未受限私鑰、超過1MiB或非`.age`密文；先核對`-ExpectedSha256`，解密後只接受一筆
`tskey-auth-*`，將明文ACL限制為SYSTEM與Administrators，成功後刪除密文且不顯示key。
完成Docker註冊後還必須刪除固定明文key、Docker secret與`TS_AUTHKEY`。

## 7. A2A JSONRPC 範例

Request：

```http
POST /a2a HTTP/1.1
Host: <ANRITSU_DOCKER_TAILSCALE_IP>:8790
Authorization: Bearer <TOKEN>
A2A-Version: 1.0
Content-Type: application/json
```

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "message/send",
  "params": {
    "message": {
      "messageId": "msg-run-20260812-001",
      "role": "ROLE_USER",
      "parts": [
        {
          "data": {
            "job_schema_version": "1.0",
            "dry_run": true,
            "job_type": "run_iperf_test",
            "environment": "anritsu",
            "profile_id": "ncq2200b2v-throughput-v1",
            "run_id": "run-20260812-001",
            "requested_by": "km-agent-01",
            "duration_seconds": 60,
            "test_cases": ["sa_dl_tcp"]
          }
        }
      ]
    }
  }
}
```

KM 需檢查回應中的：

```text
task.id
task.contextId
task.status.state
task.metadata.context_id
task.metadata.a2a_task_id
task.metadata.run_id
task.metadata.test_status
task.metadata.report_status
task.metadata.ingest_status
task.metadata.dry_run_side_effect_counts
```

成功的 POC dry-run 應符合：

```text
task.status.state = TASK_STATE_COMPLETED
test_status = pending
report_status = pending
ingest_status = pending
所有 dry_run_side_effect_counts = 0
```

`TASK_STATE_COMPLETED` 在此只代表 dry-run 契約驗證完成，不代表真實測試、Excel 或 KM ingest 已完成。

## 8. 冪等與錯誤處理

- 相同 `environment + run_id + payload` 重送：回原本 Task，不重跑。
- 相同 `environment + run_id` 但 payload 不同：回 `idempotency_conflict`。
- 未知 profile：`profile_not_allowed`。
- 非法 Schema：`invalid_request`。
- 缺少 Bearer Token：HTTP 401，`missing_credential`。
- 錯誤 Bearer Token：HTTP 403，`invalid_credential`。
- Token scope 不足：HTTP 403，`insufficient_scope`。
- 未開放的方法：`policy_denied` 或 method not found。

KM 不得因 timeout 自動改用新 `run_id` 重送。應先用原 Task ID 或原 run ID 查詢，避免建立重複工作。

## 9. KM 主機驗證程序

在 KM Linux 主機執行：

```bash
tailscale ping <ANRITSU_DOCKER_TAILSCALE_IP>
curl --fail http://<ANRITSU_DOCKER_TAILSCALE_IP>:8790/health
curl --fail http://<ANRITSU_DOCKER_TAILSCALE_IP>:8790/healthz
curl --fail http://<ANRITSU_DOCKER_TAILSCALE_IP>:8790/.well-known/agent-card.json
```

若 timeout：

1. 執行 `tailscale status`，確認 KM 與 Anritsu 同時出現在相同 tailnet。
2. 執行 `tailscale ping <ANRITSU_TAILSCALE_IP>`，不得出現 `no matching peer`。
3. 確認Docker userspace節點已帶`tag:anritsu-a2a-poc`，且沒有publish Windows host port。
4. 確認 KM 的 discovery endpoint 已更新為 Anritsu 加入此 tailnet 後的實際 IP／MagicDNS。
5. 不要把 route timeout 誤判為 Bearer 認證失敗。

預期 Health 關鍵值：

```json
{
  "mode": "dry-run",
  "public_base_url": "http://<ANRITSU_DOCKER_TAILSCALE_IP>:8790",
  "transport_security": "poc-http",
  "poc_only": true,
  "service_status": "ready",
  "instrument_available": false
}
```

## 10. Tailscale 管理與最小權限 Policy

KM 位於 tailnet `kusanagi.huang@gmail.com`。以下操作必須由該 tailnet 的 Owner、Admin 或具備
相應權限的管理員在 Tailscale Admin Console 完成，不能由 KM 節點的一般 CLI 代替：

### Docker userspace短效 Auth Key

建立 single-use、短效、pre-authorized auth key，並預先套用 `tag:anritsu-a2a-poc`。Key 是秘密，
只能透過核准的 secret channel交付 Anritsu operator；不得寫入 Git、文件、聊天或長期 script。
完成節點註冊後立即撤銷或確認 key 已失效。

管理員實際操作順序：

1. 先在 Tailscale Admin Console 的 Access controls 合併並儲存本節下方的 `tagOwners` 與
   `grants`；先建立 tag，才能在 auth key中選取它。
2. 開啟 Admin Console 的 Keys 頁面，選擇 **Generate auth key**。
3. Description填入可稽核名稱，例如 `Anritsu A2A POC 2026-08-12`。
4. 關閉 **Reusable**，建立 one-off key。
5. Expiration選最短可用的 `1 day`。這是「註冊用key」的有效期，不是節點自動撤銷期限。
6. 關閉 **Ephemeral**；Anritsu sidecar是持續服務，不應因短暫離線就自動從tailnet移除。
7. 在 Tags只選 `tag:anritsu-a2a-poc`。此tailnet的Device Approval目前為off，因此表單不顯示
   **Pre-approved**；key加入後不會停在pending approval。若未來啟用Device Approval，才必須
   建立pre-approved key或由管理員另外核准節點。
8. 產生後只顯示／複製一次；經核准secret channel交給Anritsu operator，不要貼進一般聊天。

Anritsu Windows應先透過核准secret channel將key建立為以下ACL受限暫存檔，再由系統管理員
PowerShell執行Docker授權腳本。禁止執行`tailscale.exe up`：

```powershell
$AUTH_KEY_FILE = 'C:\ProgramData\Tailscale\anritsu-a2a-poc-auth.key'

cd D:\Anritsu_Control_API

.\a2a-sidecar\scripts\Manage-A2ADockerTailscalePoc.ps1 `
  -Action Authorize
```

腳本必須使用Docker userspace networking，不啟用exit node、subnet routes、Tailscale SSH或
Funnel。完成後需證明Windows DNS、外網連線及到`100.100.100.100`的路由未改變，並回報新的
Docker Tailscale IP與A2A endpoint。不得將auth key放在PowerShell命令列、Compose環境變數、
image、log或一般volume。

one-off auth key使用後會自動撤銷，但已加入的machine不會因此自動失去授權。POC結束後，
管理員必須在Machines頁面刪除／停用Anritsu machine，並移除不再需要的grant與tag，才是
完整撤銷。若key尚未使用但不再需要，應立即在Keys頁面按Revoke。

本POC不邀請human account，也不讓Windows host加入tailnet。最終只有Docker userspace machine
出現在同一tailnet，並套用指定tag。

在既有 tailnet policy 中「合併」以下內容，不得直接以此片段覆蓋原 policy：

```json
{
  "tagOwners": {
    "tag:anritsu-a2a-poc": ["autogroup:admin"]
  },
  "grants": [
    {
      "src": ["100.65.63.58"],
      "dst": ["tag:anritsu-a2a-poc"],
      "ip": ["tcp:8790"]
    }
  ]
}
```

若既有 policy 已有 `tagOwners` 或 `grants`，只新增對應 entry。不要加入 `src: ["*"]`、
`dst: ["*"]` 或 `ip: ["*"]`。Policy 儲存前應使用 Admin Console 的 policy test／preview，
確認 KM 可以連到 tag 的 TCP 8790，其他來源與其他 ports不因本次規則取得權限。

Tailscale grant 是累加規則，這條最小權限 grant 不會覆蓋既有的寬鬆規則。管理員必須同步
稽核既有 `*`、`autogroup:member`、使用者或群組規則，確認沒有其他規則也能連到
`tag:anritsu-a2a-poc`；否則不能宣稱「只有 KM 可以存取 TCP 8790」。

## 11. Docker userspace 網路與防火牆待辦

TCP 8790只應出現在Docker userspace Tailscale節點內，不直接bind／publish到Windows實體LAN
或公網介面。Tailscale policy已限制source=`100.65.63.58`、destination=
`tag:anritsu-a2a-poc`、IP=`tcp:8790`。不得新增Windows `RemoteAddress Any`規則、Docker
`0.0.0.0:8790:8790` host publish、exit node、subnet routes、Tailscale SSH或Funnel。

若Docker實作需要host port forwarding，必須先停止並重新做威脅模型與來源限制驗證；本POC
不以開放Windows host 8790作為替代方案。

## 12. POC 限制與正式化條件

HTTP Bearer Token 沒有 TLS 保護，只能在受控內網 POC 使用，不可公開到 Internet。

目前禁止：

- 真實儀器控制。
- 真實 iPerf。
- 正式 Excel 產生與 KM ingest。
- 將 HTTP POC Agent Card 當成正式 production discovery。
- 使用 `verify=False` 掩蓋未來正式 TLS 問題。

正式化時 Anritsu 會關閉：

```text
ANRITSU_A2A_ALLOW_INSECURE_HTTP=false
```

並恢復 HTTPS DNS、可信 TLS、CA chain、reverse proxy、共用 instrument lock，以及真機
timeout／cancel／cleanup／safe-state 驗證。

## 13. 目前驗證結果

| 項目 | 結果 |
| --- | --- |
| Anritsu 回報的 focused tests | 21 passed；測試清單待交付核對 |
| Anritsu 本機 health／Agent Card／dry-run | PASS；KM跨機實測通過 |
| KM bridge focused tests | 61 passed |
| KM bridge health／control auth | PASS |
| KM Token provisioning | PASS；Anritsu尚待登錄 hash |
| Tagged single-use auth key | PASS；第三份age密文已透過AnyDesk使用者確認流程送達 `C:\Users\SSNR\Documents`，下載回KM後SHA-256 round-trip一致 |
| Tailnet最小權限 policy | PASS；已移除預設全開grant並保存policy test |
| Anritsu Docker userspace Tailscale | PASS；peer=`100.72.21.115`、tag=`tag:anritsu-a2a-poc`、DERP pong成功 |
| Docker Tailscale IP／A2A endpoint | IP已回報；KM設定為`http://100.72.21.115:8790` |
| Windows DNS／外網／Quad100路由不變 | Anritsu回報PASS；待KM取得可核對的腳本證據 |
| KM bridge endpoint | PASS；`http://100.72.21.115:8790` |
| KM 跨電腦 fixed-schema dry-run | PASS；SDK相容fallback使用`message/send`，七項side-effect counters全為0 |

## 14. 目前交接狀態（2026-08-12）

第一份密文已由 Anritsu 清理且不可再用；原 single-use key 已在 Tailscale 管理介面撤銷。
第二份密文已在 Tailscale 認證前被舊版流程清理；Anritsu 回報 `loggedIn=false`、
`NeedsLogin`，因此目前沿用的 single-use key 尚未使用。Anritsu 已修正 Compose stderr
誤判及失敗時保留密文的流程。第三份密文已透過核准的 AnyDesk File Transfer
使用者確認流程交付，KM 未傳送明文 Tailscale key：

```text
C:\Users\SSNR\Documents\tailscale-anritsu-a2a-poc-auth-key-r3.age
大小：261 bytes
SHA-256：0b377e11ee6589127fa6c606ed7fc629aeef2bc860fe8ac4ad012487628a7644
```

Anritsu必須先以系統管理員PowerShell核對SHA-256，再執行：

```powershell
$CiphertextPath = 'C:\Users\SSNR\Documents\tailscale-anritsu-a2a-poc-auth-key-r3.age'

$ExpectedSha256 = '0b377e11ee6589127fa6c606ed7fc629aeef2bc860fe8ac4ad012487628a7644'

(Get-FileHash -Algorithm SHA256 -LiteralPath $CiphertextPath).Hash.ToLowerInvariant()

cd D:\Anritsu_Control_API

.\a2a-sidecar\scripts\Complete-A2ATailscalePocAuthorization.ps1 `
  -CiphertextPath $CiphertextPath `
  -ExpectedSha256 $ExpectedSha256
```

完成後只需回報以下非秘密資訊：

```text
Docker Tailscale IP: <實際IP>
A2A endpoint: http://<實際IP>:8790
```

KM已收到實際IP並更新`KM_A2A_AGENT_ENDPOINTS`。Anritsu修正Tailscale Serve為
`100.72.21.115:8790 -> 127.0.0.1:8791`後，KM實測`/health`、`/healthz`與
`/.well-known/agent-card.json`均HTTP 200，GET `/a2a`為405且Allow=POST；無Bearer POST
`/a2a`為401，錯Bearer為403，正確Bearer fixed-schema dry-run為200且完成。七項
`dry_run_side_effect_counts`全部為0。因A2A SDK 1.1.2送出`SendMessage`而Anritsu依契約
接受`message/send`，KM `sdk_transport.py`加入只在`InvalidParamsError`時啟用的受控
JSON-RPC相容fallback；既有SDK contract tests仍通過。KM bridge目前恢復
`KM_A2A_ENABLED=true`、transport=`sdk-dry-run`、`real_instrument_access=false`。
本Gate只證明dry-run委派鏈路，不代表已開放真實儀器、iPerf、Excel或KM ingest。
