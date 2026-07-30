# Anritsu／Amarisoft 測試報告整合架構圖

> 兩個測試環境各自獨立，測試完成後以標準 Excel report 透過 HTTPS API 傳入 Knowledge Base；報告經 KB 待審台核准後才正式入庫。

```mermaid
flowchart TB
    subgraph AN["Anritsu 測試環境"]
        AN_I["Anritsu 儀器／DUT"] --> AN_C["測試控制程式／Agent"]
        AN_C --> AN_T["執行測試案例"] --> AN_R["產生標準 Excel Report"]
        AN_R --> AN_V["Schema／數值驗證"] --> AN_O["本機 Outbox\n斷線重送"]
    end

    subgraph AM["Amarisoft 測試環境"]
        AM_I["Amarisoft 儀器／DUT"] --> AM_C["測試控制程式／Agent"]
        AM_C --> AM_T["執行測試案例"] --> AM_R["產生標準 Excel Report"]
        AM_R --> AM_V["Schema／數值驗證"] --> AM_O["本機 Outbox\n斷線重送"]
    end

    AN_O -->|"VPN／TLS\nAgent Token"| GW
    AM_O -->|"VPN／TLS\nAgent Token"| GW

    subgraph KB["Knowledge Base 平台"]
        GW["Nginx／API Gateway"] --> API["Agent Report API\n驗證 environment、hash、run_id"]
        API --> ST["Staging File Store\n原始 Excel／附件"]
        API --> REG["Submission Registry\n持久化狀態／稽核"]
        REG --> RV["KB 待審管理頁\n預覽／核准／退回"]
        RV -->|"核准"| Q["Redis／Celery Ingest Queue"]
        RV -->|"退回＋原因"| REG
        Q --> P["Canonical Excel Parser"]
        P --> M["Markdown／Source Chunk 轉換"]
        M --> W["冪等寫入／Reconciliation"]
    end

    W --> F["正式 File Store\n原始檔／Markdown"]
    W --> N["Neo4j\nTestRun／TestCase／Measurement"]
    W --> V["Qdrant\n向量與環境 metadata"]

    subgraph USE["使用與分析"]
        S["Search API"]
        C["chat.html／AI Assistant"]
        X["跨環境比較／趨勢／Fail 分析"]
    end
    F --> S
    N --> S
    V --> S
    S --> C
    S --> X

    classDef env fill:#e8f3ff,stroke:#2878b5,color:#102a43
    classDef kb fill:#fff3d6,stroke:#c98200,color:#3d2b00
    classDef data fill:#e8f7e8,stroke:#3f8f4f,color:#16351b
    class AN_I,AN_C,AN_T,AN_R,AN_V,AN_O,AM_I,AM_C,AM_T,AM_R,AM_V,AM_O env
    class GW,API,ST,REG,RV,Q,P,M,W kb
    class F,N,V,S,C,X data
```

## 審核與攝入狀態

```text
received → validating → pending_review → approved → queued
                                      └──── rejected

queued → parsing → converting → writing_neo4j → writing_qdrant
       → refreshing_index → completed
       └──────────────────────────────────────→ ingest_failed
```

## 關鍵系統邊界

- Anritsu／Amarisoft 不直接連線 Neo4j、Qdrant、Redis 或 KB 主機檔案系統。
- 核准前只保存於 staging；核准後才進入正式知識庫索引。
- `environment` 固定為 `anritsu` 或 `amarisoft`；`run_id + environment` 用於冪等與衝突檢查。
- Neo4j 保存可精確比較的測試結構與數值；Qdrant 保存報告文字、來源 chunk 與篩選 metadata。
