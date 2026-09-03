"""
知識圖譜實體萃取模組
支援多種萃取模式：4G/5G、WiFi、Lab管理、Project、Automation、Report
"""

import logging
import yaml
from pathlib import Path
from typing import Literal

from .storage_paths import resolve_storage_category

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_config():
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ============================================================
# 萃取模式定義
# ============================================================

EXTRACTION_MODES = {
    # ============================================================
    # 4G/5G 電信設備模式（原 AMR 設備報告）
    # ============================================================
    "4g5g": {
        "name": "4G/5G 電信設備",
        "description": "適用於 4G/5G 電信設備報告萃取：基站、NR、4G、LTE 等設備的完整設備資訊與錯誤追蹤",
        "system_prompt": """你是一個專業的電信設備資料分析師。請從以下 4G/5G 電信設備報告中萃取結構化資訊。

## 請萃取以下 11 種 Entity（嚴格按照欄位名稱）：

1. **設備名稱 (DeviceName)**: 設備的識別名稱，如 NR基站_A1、NR基站_A2、4G基地台_B1、NR小基站_C1
2. **序號 (SerialNumber)**: 設備序列號，如 NR-A1-2024-001、NR-A2-2024-002、4G-B1-2023-015
3. **設備型號 (DeviceModel)**: 設備的型號，如 Huawei AAU5614、Nokia AAHF、Samsung Ammut、Ericsson RAN
4. **軟體版本 (SoftwareVersion)**: 軟體/韌體版本，如 V3.5.2、F5.2.1、L19.3、S2.1
5. **作業模式 (OperationMode)**: 作業模式，如 NSA、SA、NSA/SA、LTE
6. **頻段 (FrequencyBand)**: 使用的頻段，如 n78 3500MHz、n77 3700MHz、Band3 1800MHz、Band7 2600MHz
7. **位置 (Location)**: 設備所在位置，如 台北市信義區、新北市板橋區、桃園市龜山區
8. **調變方式 (Modulation)**: 調變方式，如 256QAM、64QAM、QPSK
9. **天線配置 (AntennaConfig)**: 天線配置，如 64T64R、32T32R、8T8R、4T4R
10. **傳輸速率 (TransmissionRate)**: 傳輸速率，如 2.5Gbps、1.5Gbps、300Mbps
11. **錯誤碼 (ErrorCode)**: 錯誤碼和描述，格式如 E-502: AAHU 通訊異常，請萃取錯誤碼編號和錯誤描述

## 請萃取以下關係：
- 設備名稱 - 序號為 -> 序號
- 設備名稱 - 型號為 -> 設備型號
- 設備名稱 - 版本為 -> 軟體版本
- 設備名稱 - 使用模式 -> 作業模式
- 設備名稱 - 支援頻段 -> 頻段
- 設備名稱 - 位於 -> 位置
- 設備名稱 - 使用調變 -> 調變方式
- 設備名稱 - 配置天線 -> 天線配置
- 設備名稱 - 傳輸速率 -> 傳輸速率
- 設備名稱 - 發生錯誤 -> 錯誤碼

## Issue 欄位解析（重要！）
當遇到 Issue 欄位時，請解析其中的錯誤碼、原因和解決方案：
- Issue 格式如："E-502: AAHU 通訊異常, CAUSED_BY: Firmware 版本過舊, RESOLVED_BY: 更新至 V3.5.2"
- E-502 是錯誤碼
- CAUSED_BY 後面的「Firmware 版本過舊」是根因分析（RootCause）
- RESOLVED_BY 後面的「更新至 V3.5.2」是解決方案（Solution）

如果 Issue 包含 CAUSED_BY 和 RESOLVED_BY，請同時萃取：
- RootCause 實體（如 "Firmware 版本過舊"）
- Solution 實體（如 "更新至 V3.5.2"）
- 並建立關係：錯誤碼 - 原因 -> RootCause，錯誤碼 - 解決 -> Solution


## 忽略：
- 純數值陣列（表格內的大量數值）
- Unnamed 欄位
- NaN 值
- 統計汇总行

請以 JSON 格式輸出：
{
  "entities": [
    {"Name": "實體名稱", "type": "實體類型", "description": "簡短描述"}
  ],
  "relationships": [
    {"source": "實體A", "type": "關係類型", "target": "實體B", "description": "關係描述"}
  ]
}
"""
    },
    
    # ============================================================
    # WiFi 設備模式
    # ============================================================
    "wifi": {
        "name": "WiFi 設備",
        "description": "適用於 WiFi 設備、AP、路由器、Mesh 系統等萃取：SSID、頻段、通訊標準、頻道、傳輸速率、用戶端連線等",
        "system_prompt": """你是一個專業的 WiFi 網路設備分析師。請從以下 WiFi 設備文件中萃取結構化資訊。

## 請萃取以下類型的 Entity：

1. **存取點 (AccessPoint)**: WiFi AP、路由器、Mesh 節點等設備名稱
2. **SSID**: 網路名稱（最多32字元）
3. **頻段 (Band)**: 2.4GHz、5GHz、6GHz、WiFi 6E、WiFi 7
4. **通訊標準 (Standard)**: 802.11ax (WiFi 6)、802.11ac (WiFi 5)、802.11n (WiFi 4)
5. **頻道 (Channel)**: 1-13 (2.4G)、36-165 (5G)、1-233 (6G)
6. **頻道頻寬 (ChannelWidth)**: 20MHz、40MHz、80MHz、160MHz、320MHz
7. **傳輸速率 (DataRate)**: 最大傳輸速率，如 4800 Mbps
8. **MIMO 配置 (MIMO)**: 天線數量配置，如 8x8 MIMO、4x4 MIMO
9. **加密方式 (Security)**: WPA3、WPA2-Enterprise、WPA2-PSK、WEP、Open
10. **終端設備 (Client)**: 連接到 AP 的設備
11. **位置 (Location)**: 設備安裝位置
12. **用戶端數量 (ClientCount)**: 連接用戶端數量
13. **天線增益 (AntennaGain)**: 天線增益 dBi 值
14. **發射功率 (TxPower)**: 發射功率 dBm 值
15. **覆蓋範圍 (Coverage)**: 覆蓋範圍平方米或米數

## 請萃取以下關係：
- AP - 廣播 -> SSID
- AP - 支援 -> 頻段
- AP - 支援 -> 通訊標準
- AP - 使用頻道 -> 頻道
- AP - 配置 -> 頻道頻寬
- AP - 最大速率 -> 傳輸速率
- AP - 配置 -> MIMO 配置
- AP - 採用 -> 加密方式
- AP - 安裝於 -> 位置
- AP - 連接 -> 終端設備
- SSID - 位於 -> 頻段
- 用戶端 - 連線到 -> AP

## 忽略：
- 純數值陣列（訊號強度數值表）
- 詳細射頻校準參數
- 深層技術規格表（除非涉及型號名稱）
- 無法識別的亂碼或無關代碼

請以 JSON 格式輸出：
{
  "entities": [
    {"Name": "實體名稱", "type": "實體類型", "description": "簡短描述"}
  ],
  "relationships": [
    {"source": "實體A", "type": "關係類型", "target": "實體B", "description": "關係描述"}
  ]
}
"""
    },
    
    # ============================================================
    # Lab 管理模式
    # ============================================================
    "lab": {
        "name": "Lab 管理",
        "description": "適用於實驗室管理、設備借用、場地預約、測試排程等萃取：設備狀態、人員借用、實驗室空間、預借時間等",
        "system_prompt": """你是一個專業的實驗室管理分析師。請從以下 Lab 管理文件中萃取結構化資訊。

## 請萃取以下類型的 Entity：

1. **實驗室設備 (Equipment)**: 設備名稱、型號、管理編號
2. **借用狀態 (Status)**: 已借出、可用、維修中、報廢
3. **借用人 (Borrower)**: 借用設備的人員姓名
4. **管理人 (Manager)**: 設備管理人或實驗室負責人
5. **借用日期 (BorrowDate)**: 借出日期
6. **預計歸還 (ReturnDate)**: 預計歸還日期
7. **實際歸還 (ActualReturn)**: 實際歸還日期
8. **實驗室 (Lab)**: 實驗室名稱或編號，如 Lab A、RF Lab
9. **位置 (Location)**: 設備在實驗室內的位置，如 測試桌 #3
10. **預借時段 (TimeSlot)**: 預借時段，如 2026-04-21 14:00-17:00
11. **設備類別 (Category)**: 設備類別，如 網路分析儀、頻譜分析儀、訊號產生器
12. **聯絡人 (Contact)**: 聯絡方式（電話或 Email）
13. **借用單號 (BorrowID)**: 借用單據編號
14. **歸還狀態 (ReturnStatus)**: 已歸還、逾期、待確認

## 請萃取以下關係：
- 設備 - 目前狀態 -> 借用狀態
- 設備 - 被 -> 借用人 借用
- 借用人 - 隸屬 -> 管理人
- 設備 - 存放於 -> 實驗室
- 設備 - 位於 -> 位置
- 借用單 - 包含 -> 設備
- 借用單 - 預約 -> 預借時段
- 借用人 - 填寫 -> 借用單
- 設備 - 屬於 -> 設備類別
- 設備 - 聯絡 -> 聯絡人
- 借用單 - 狀態 -> 歸還狀態

## 忽略：
- 純數值統計（使用率圖表）
- 詳細技術規格表
- 過期歷史借用記錄
- 無法識別的設備代碼

請以 JSON 格式輸出：
{
  "entities": [
    {"Name": "實體名稱", "type": "實體類型", "description": "簡短描述"}
  ],
  "relationships": [
    {"source": "實體A", "type": "關係類型", "target": "實體B", "description": "關係描述"}
  ]
}
"""
    },
    
    # ============================================================
    # Project 專案模式
    # ============================================================
    "project": {
        "name": "Project 專案",
        "description": "適用於專案管理、任務追蹤、時程規劃、風險管理等萃取：專案名稱、PM、團隊成員、進度、里程碑、風險等",
        "system_prompt": """你是一個專業的專案管理分析師。請從以下專案文件中萃取結構化資訊。

## 請萃取以下類型的 Entity：

1. **專案名稱 (ProjectName)**: 專案名稱或代碼
2. **專案經理 (PM)**: Project Manager 或專案負責人姓名
3. **團隊成員 (TeamMember)**: 團隊成員姓名
4. **客戶 (Client)**: 客戶名稱或代碼
5. **專案進度 (Progress)**: 當前進度百分比
6. **開始日期 (StartDate)**: 專案開始日期
7. **截止日期 (EndDate)**: 專案截止日期
8. **里程碑 (Milestone)**: 專案重要節點
9. **交付物 (Deliverable)**: 專案交付項目
10. **任務 (Task)**: 工作項目或子任務
11. **任務狀態 (TaskStatus)**: Not Started、In Progress、Completed、Blocked
12. **風險項目 (Risk)**: 專案風險描述
13. **風險等級 (RiskLevel)**: High、Medium、Low
14. **預算 (Budget)**: 專案預算金額
15. **實際花費 (ActualCost)**: 已花費金額
16. **部門 (Department)**: 所屬部門

## 請萃取以下關係：
- 專案 - 由 -> 專案經理 負責
- 專案 - 包含 -> 團隊成員
- 專案 - 面向 -> 客戶
- 專案 - 目前進度 -> 專案進度
- 專案 - 開始於 -> 開始日期
- 專案 - 截止於 -> 截止日期
- 專案 - 擁有 -> 里程碑
- 專案 - 交付 -> 交付物
- 任務 - 屬於 -> 專案
- 任務 - 分配給 -> 團隊成員
- 任務 - 狀態 -> 任務狀態
- 專案 - 存在 -> 風險項目
- 風險項目 - 等級 -> 風險等級
- 專案 - 預算 -> 預算
- 專案 - 已花費 -> 實際花費
- 團隊成員 - 隸屬 -> 部門

## 忽略：
- 純數值財務報表
- 過詳細的技術規格
- 已經取消或終止的任務
- 純代碼或技術文件

請以 JSON 格式輸出：
{
  "entities": [
    {"Name": "實體名稱", "type": "實體類型", "description": "簡短描述"}
  ],
  "relationships": [
    {"source": "實體A", "type": "關係類型", "target": "實體B", "description": "關係描述"}
  ]
}
"""
    },
    
    # ============================================================
    # Automation 自動化模式
    # ============================================================
    "automation": {
        "name": "Automation 自動化",
        "description": "適用於自動化腳本、CI/CD Pipeline、DevOps 等萃取：腳本名稱、工具、執行環境、觸發條件、建置狀態等",
        "system_prompt": """你是一個專業的自動化系統分析師。請從以下自動化文件中萃取結構化資訊。

## 請萃取以下類型的 Entity：


1. **腳本名稱 (ScriptName)**: 自動化腳本或 Pipeline 名稱
2. **腳本類型 (ScriptType)**: Shell Script、Python、Pipeline、Workflow、Ansible Playbook
3. **工具平台 (Platform)**: Jenkins、GitLab CI、GitHub Actions、CircleCI、Azure DevOps
4. **執行環境 (Environment)**: Development、Testing、Staging、Production
5. **觸發條件 (Trigger)**: 觸發條件類型，如 Push、Pull Request、Schedule、Webhook、Manual
6. **觸發時機 (TriggerTime)**: Cron 表達式或排程時間
7. **建置結果 (BuildResult)**: Success、Failed、Aborted、Unstable
8. **執行時間 (Duration)**: 建置耗時，如 5 分鐘
9. **測試覆蓋率 (Coverage)**: 程式碼測試覆蓋率百分比
10. **分支 (Branch)**: Git 分支名稱，如 main、develop、feature/xxx
11. **提交 (Commit)**: Git Commit Hash 或描述
12. **部署目標 (DeployTarget)**: 部署目標主機或服務
13. **錯誤類型 (ErrorType)**: 錯誤類型，如 Compile Error、Test Failure、Timeout
14. **自動化腳本 (Step)**: Pipeline 中的步驟或任務
15. **相依模組 (Dependency)**: 依賴的套件或模組
16. **日誌級別 (LogLevel)**: INFO、WARN、ERROR

## 請萃取以下關係：
- 腳本 - 執行于 -> 執行環境
- 腳本 - 由 -> 觸發條件 觸發
- 腳本 - 使用 -> 工具平台
- 觸發條件 - 設定 -> 觸發時機
- Pipeline - 包含 -> 自動化腳本
- 自動化腳本 - 依賴 -> 相依模組
- 建置結果 - 產生 -> 錯誤類型
- 腳本 - 部署到 -> 部署目標
- 腳本 - 從 -> 分支 觸發
- 觸發條件 - 包含 -> 提交
- 自動化腳本 - 耗時 -> 執行時間
- 腳本 - 覆蓋率 -> 測試覆蓋率
- 自動化腳本 - 產生日誌 -> 日誌級別

## 忽略：
- 純代碼內容
- 詳細錯誤堆疊追蹤
- 設定檔內容（YAML、JSON）
- 私密 API Key 或 Token
- 大型設定檔內容

請以 JSON 格式輸出：
{
  "entities": [
    {"Name": "實體名稱", "type": "實體類型", "description": "簡短描述"}
  ],
  "relationships": [
    {"source": "實體A", "type": "關係類型", "target": "實體B", "description": "關係描述"}
  ]
}
"""
    },

    # ============================================================
    # Report 測試報告模式
    # ============================================================
    "report": {
        "name": "Report 測試報告",
        "description": "適用於 SIT-TR-SC 類 Excel / 測試報告，保留文件結構與 chunk 向量，不進行實體關係萃取",
        "system_prompt": ""
    },

    # ============================================================
    # Type6 簡化文件模式（PDF/大型文件）
    # ============================================================
    "simple": {
        "name": "簡化文件（PDF/大型文件）",
        "description": "適用於 PDF 或大型文件的快速攝入，不需要 LLM 萃取實體關係，直接轉 MD 並寫入 QDrant",
        "system_prompt": ""
    }
}


# ============================================================
# 支援的模式列表（用於 API）
# ============================================================

EXTRACTION_MODE_LIST = [
    {
        "id": "4g5g",
        "name": "4G/5G 電信設備",
        "description": "適用於基站、AMR、SCU、5G NR 等電信設備報告萃取"
    },
    {
        "id": "wifi",
        "name": "WiFi 設備",
        "description": "適用於 WiFi AP、路由器、Mesh 系統的 SSID、頻段、標準、頻道、速率等萃取"
    },
    {
        "id": "lab",
        "name": "Lab 管理",
        "description": "適用於實驗室設備借用狀態、人員、場地、預借時段等管理萃取"
    },
    {
        "id": "project",
        "name": "Project 專案",
        "description": "適用於專案管理 PM、團隊成員、進度、里程碑、風險、預算等萃取"
    },
    {
        "id": "automation",
        "name": "Automation 自動化",
        "description": "適用於 CI/CD Pipeline、自動化腳本、DevOps 工具、觸發條件等萃取"
    },
    {
        "id": "report",
        "name": "Report 測試報告",
        "description": "適用於 SIT-TR-SC 類 Excel 測試報告，保留文件結構與 chunk 向量"
    },
    {
        "id": "simple",
        "name": "簡化文件（PDF/大型文件）",
        "description": "適用於 PDF 或大型文件快速攝入，只轉 MD 寫入 QDrant，不經 LLM 萃取"
    }
]


# ============================================================
# 函式介面（向後相容）
# ============================================================

def get_extraction_prompt(mode: Literal["4g5g", "wifi", "lab", "project", "automation", "report", "simple"]) -> str:
    """取得指定萃取模式的 Prompt"""
    return EXTRACTION_MODES.get(mode, {}).get("system_prompt", EXTRACTION_MODES["4g5g"]["system_prompt"])


def get_extraction_info(mode: Literal["4g5g", "wifi", "lab", "project", "automation", "report", "simple"]) -> dict:
    """取得萃取模式的資訊"""
    return EXTRACTION_MODES.get(mode, {})


# ============================================================
# 萃取並寫入 Neo4j
# ============================================================

def extract_and_write(content: str, doc_name: str, doc_path: str, mode: Literal["4g5g", "wifi", "lab", "project", "automation", "report", "simple"] = "4g5g", enable_vector: bool = True):
    """使用指定模式萃取 Entity 並寫入 Neo4j"""
    try:
        import json
        from neo4j import GraphDatabase
        
        config = load_config()
        neo4j_config = config["neo4j"]
        ollama_config = config["ollama"]

        if mode == "report":
            from src.graphrag.neo4j_schema import setup_neo4j_schema
            setup_neo4j_schema(neo4j_config["uri"], neo4j_config["user"], neo4j_config["password"])

            driver = GraphDatabase.driver(neo4j_config["uri"], auth=(neo4j_config["user"], neo4j_config["password"]))
            with driver.session() as session:
                session.run("""
                    MERGE (d:Document {name: $name})
                    SET d.content = $content,
                        d.source = $source,
                        d.extraction_mode = $mode,
                        d.storage_category = $storage_category
                """, name=doc_name, content=content[:1000], source=doc_path, mode=mode, storage_category=resolve_storage_category(mode, doc_path))

                session.run("""
                    MATCH (d:Document {name: $name})
                    CREATE (t:TextUnit {content: $content, source: $source})
                    CREATE (d)-[:CONTAINS]->(t)
                """, name=doc_name, content=content[:2000], source=doc_name)
            driver.close()

            if enable_vector:
                from src.vector_store import get_vector_store
                from src.chunker import chunk_document
                chunks = chunk_document(doc_path)
                vector_store = get_vector_store()
                vector_store.add_documents(chunks, doc_name)

            return {"entities": [], "relationships": []}
        
        # 取得萃取 Prompt
        system_prompt = get_extraction_prompt(mode)
        
        # 建立 LLM 客戶端
        from src.web_api.ollama_client import OllamaClient
        llm = OllamaClient(
            model=ollama_config.get("model", "gemma4:12b"),
            base_url=ollama_config["instances"][0] if len(ollama_config["instances"]) > 0 else ollama_config.get("base_url", "http://localhost:11434")
        )
        
        # 呼叫 LLM 萃取（最多重試 2 次）
        max_retries = 2
        for attempt in range(max_retries):
            response = llm.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content[:6000]}
            ])
            
            # 嘗試解析 JSON
            import re
            
            # 取出 markdown code block 中的 JSON
            cleaned_response = response.strip()
            
            # Debug: 記錄回應內容
            logger.info(f"LLM 回應長度: {len(cleaned_response)}")
            logger.info(f"LLM 回應前200字符: {cleaned_response[:200]}")
            
            # 方法1: 找 ```json ... ``` 區塊
            json_block_match = re.search(r'```json\s*([\s\S]*?)\s*```', cleaned_response)
            if json_block_match:
                cleaned_response = json_block_match.group(1).strip()
                logger.info(f"提取到 ```json 區塊，長度: {len(cleaned_response)}")
            else:
                # 方法2: 去除 ``` 標記
                lines = cleaned_response.split('\n')
                # 移除第一行 ``` 或 ```json
                if lines and re.match(r'^```\w*$', lines[0].strip()):
                    lines = lines[1:]
                # 移除最後一行 ```
                if lines and lines[-1].strip() == '```':
                    lines = lines[:-1]
                cleaned_response = '\n'.join(lines).strip()
            
            # 嘗試解析
            try:
                result = json.loads(cleaned_response)
                logger.info(f"JSON 解析成功")
                break
            except json.JSONDecodeError as e:
                if attempt < max_retries - 1:
                    logger.warning(f"JSON 解析失敗 (嘗試 {attempt+1}/{max_retries}): {str(e)[:100]}，重試中...")
                    continue
                else:
                    logger.warning(f"無法解析 LLM 回應為 JSON: {cleaned_response[:300]}")
                    result = {"entities": [], "relationships": []}
        
        logger.info(f"萃取完成 - 模式: {mode}, 實體: {len(result.get('entities', []))}, 關係: {len(result.get('relationships', []))}")
        
        # 寫入 Neo4j
        if result.get("entities") or result.get("relationships"):
            # 延遲導入以避免循環依賴
            from src.graphrag.neo4j_schema import get_graph_stats, setup_neo4j_schema
            
            # 確保 Schema 存在
            setup_neo4j_schema(neo4j_config["uri"], neo4j_config["user"], neo4j_config["password"])
            
            driver = GraphDatabase.driver(neo4j_config["uri"], auth=(neo4j_config["user"], neo4j_config["password"]))
            
            with driver.session() as session:
                # 建立文件節點
                session.run("""
                    MERGE (d:Document {name: $name})
                    SET d.content = $content,
                        d.source = $source,
                        d.extraction_mode = $mode,
                        d.storage_category = $storage_category
                """, name=doc_name, content=content[:1000], source=doc_path, mode=mode, storage_category=resolve_storage_category(mode, doc_path))
                
                # 建立文字區塊
                session.run("""
                    MATCH (d:Document {name: $name})
                    CREATE (t:TextUnit {content: $content, source: $source})
                    CREATE (d)-[:CONTAINS]->(t)
                """, name=doc_name, content=content[:2000], source=doc_name)
                
                from src.graph_relationship_contract import build_graph_contract
                graph_contract = build_graph_contract(
                    result.get("entities", []),
                    result.get("relationships", []),
                    source_document=doc_name,
                    source_chunk_id=f"{doc_name}::chunk::0",
                )

                # 建立具 namespace 的實體，避免 display name 成為全域 endpoint identity。
                for entity in graph_contract["entities"]:
                    session.run("""
                        MERGE (e:Entity {entity_key: $entity_key})
                        SET e.type = $entity_type,
                            e.name = $entity_name,
                            e.description = $entity_desc,
                            e.source_document = $source_document,
                            e.namespace = $namespace,
                            e.extraction_mode = $mode
                    """, entity_key=entity["entity_key"], entity_name=entity["name"], entity_type=entity["type"],
                        entity_desc=entity["description"], source_document=doc_name,
                        namespace=entity["namespace"],
                        mode=mode)
                
                # 建立關係（容錯：支援 source/source, target/target, type/type）
                for rel in graph_contract["relationships"]:
                    session.run("""
                        MATCH (s:Entity {entity_key: $source_entity})
                        MATCH (t:Entity {entity_key: $target_entity})
                        MERGE (s)-[r:RELATES_TO {type: $rel_type, source_document: $source_document, source_chunk_id: $source_chunk_id}]->(t)
                        SET r.description = $rel_desc,
                            r.source_entity = $source_entity,
                            r.target_entity = $target_entity,
                            r.evidence_type = $evidence_type,
                            r.review_status = $review_status
                    """, source_entity=rel["source_entity"], target_entity=rel["target_entity"],
                        rel_type=rel["relationship_type"], rel_desc=rel["description"],
                        source_document=rel["source_document"], source_chunk_id=rel["source_chunk_id"],
                        evidence_type=rel["evidence_type"], review_status=rel["review_status"])
            
            driver.close()
            logger.info(f"成功寫入 Neo4j - 文件: {doc_name}")
            logger.info(f"  - 實體: {len(result.get('entities', []))}")
            logger.info(f"  - 關係: {len(result.get('relationships', []))}")
        
        return result
        
    except Exception as e:
        logger.error(f"萃取失敗: {e}")
        raise


# ============================================================
# 快速測試
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("支援的萃取模式：")
    print("=" * 50)
    for mode_id, mode_info in EXTRACTION_MODES.items():
        print(f"\n【{mode_id}】{mode_info['name']}")
        print(f"  說明: {mode_info['description']}")
