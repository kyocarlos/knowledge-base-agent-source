"""
搜尋引擎模組 - 雙模式 RAG / GraphRAG 搜尋
支援規則式關鍵字萃取 + 混合搜尋 + 四大優化功能
"""

import logging
import os
import yaml
import json
import re
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ===== 安全過濾：特殊字符 =====
# 只允許：中文、英數字、部分常見符號（.-_）
SAFE_CHARS_PATTERN = re.compile(r"[^一-鿿\w\s.,。，、-]")  # 只允許中文、英文數字、空白、部分標點

def sanitize_for_cypher(text: str) -> str:
    """
    過濾危險字符，只保留安全的字元
    
    Args:
        text: 原始文字
        
    Returns:
        str: 過濾後的安全文字
    """
    if not text:
        return ""
    # 只保留允許的字元
    sanitized = SAFE_CHARS_PATTERN.sub("", text)
    # 移除 HTML 標籤防止 XSS
    sanitized = re.sub(r"<[^>]+>", "", sanitized)
    # 清理多餘空白
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized





def is_irrelevant_query(query: str) -> bool:
    """
    判斷是否為不相關查詢（天氣、飲食等與系統無關）
    
    Args:
        query: 原始查詢
        
    Returns:
        bool: True if the query is irrelevant
    """
    irrelevant_patterns = [
        r"^\s*$",  # 空白
        r"天氣", r"氣溫", r"下雨", r"溫度",
        r"午餐", r"晚餐", r"早餐", r"吃.*什麼",
        r"減肥", r"健康",
        r"^[a-zA-Z0-9]{1,10}$",  # 隨機字母（可能是測試）
    ]
    
    query_lower = query.lower().strip()
    for pattern in irrelevant_patterns:
        if re.search(pattern, query_lower, re.IGNORECASE):
            return True
    return False


@lru_cache(maxsize=1024)
def _load_citation_source_metadata(source_path: str) -> dict | None:
    if not source_path:
        return None

    meta_path = Path(source_path).with_suffix(".source.json")
    if not meta_path.exists():
        root_dir = Path(__file__).resolve().parents[2]
        processed_root = root_dir / "data" / "processed"
        if processed_root.exists():
            stem = Path(source_path).stem
            for candidate in processed_root.rglob(f"{stem}.source.json"):
                meta_path = candidate
                break
            else:
                lookup_suffix = "-".join(stem.split("-")[-5:]) if "-" in stem else stem
                if not lookup_suffix:
                    return None

                matched = None
                for candidate in processed_root.rglob("*.source.json"):
                    try:
                        candidate_meta = json.loads(candidate.read_text(encoding="utf-8"))
                    except Exception:
                        continue

                    haystacks = [
                        str(candidate_meta.get("source_name") or ""),
                        str(candidate_meta.get("source_stem") or ""),
                        Path(str(candidate_meta.get("original_path") or "")).name,
                        Path(str(candidate_meta.get("converted_path") or "")).name,
                    ]
                    if any(lookup_suffix in haystack for haystack in haystacks if haystack):
                        matched = candidate
                        break

                if not matched:
                    return None
                meta_path = matched

    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"讀取 citation source metadata 失敗: {meta_path} - {e}")
        return None


def _enrich_citation_source(source: dict) -> dict:
    enriched = dict(source or {})

    source_path = str(enriched.get("source_path") or "").strip()
    source_name = str(
        enriched.get("source")
        or enriched.get("doc_name")
        or enriched.get("name")
        or ""
    ).strip()

    citation_source_name = str(enriched.get("citation_source_name") or "").strip()
    citation_source_path = str(enriched.get("citation_source_path") or "").strip()
    citation_source_ext = str(enriched.get("citation_source_ext") or "").strip()
    citation_source_kind = str(enriched.get("citation_source_kind") or "").strip()

    if source_path:
        meta = _load_citation_source_metadata(source_path)
        if meta:
            original_path = str(meta.get("original_path") or "").strip()
            converted_path = str(meta.get("converted_path") or "").strip()
            source_ext = str(meta.get("source_extension") or "").strip().lower()

            if source_ext == ".xlsx" and original_path:
                citation_source_name = Path(original_path).name
                citation_source_path = original_path
                citation_source_ext = ".xlsx"
                citation_source_kind = "excel"
            else:
                display_path = converted_path or source_path
                citation_source_name = Path(display_path).name
                citation_source_path = display_path
                citation_source_ext = source_ext or Path(display_path).suffix.lower()
                citation_source_kind = "markdown" if citation_source_ext == ".md" else "file"

    if not citation_source_name:
        fallback_path = citation_source_path or source_path
        if fallback_path:
            citation_source_name = Path(fallback_path).name
        elif source_name:
            citation_source_name = source_name

    if not citation_source_path:
        citation_source_path = source_path

    if not citation_source_ext and citation_source_path:
        citation_source_ext = Path(citation_source_path).suffix.lower()

    if not citation_source_kind and citation_source_ext:
        citation_source_kind = "markdown" if citation_source_ext == ".md" else "file"

    if citation_source_name:
        enriched["citation_source_name"] = citation_source_name
    if citation_source_path:
        enriched["citation_source_path"] = citation_source_path
    if citation_source_ext:
        enriched["citation_source_ext"] = citation_source_ext
    if citation_source_kind:
        enriched["citation_source_kind"] = citation_source_kind

    return enriched


class SearchEngine:
    """雙模式搜尋引擎 + 四大優化功能"""

    # ===== 優化一:意圖分類 =====
    INTENT_PATTERNS = {
        "設備查詢": [r"設備", r"型號", r"規格", r"哪.*(?:設備|型號|型號)", r"有哪些.*設備"],
        "狀態查詢": [r"狀態", r"如何", r"正常", r"運作", r"運行了多久"],
        "人員查詢": [r"誰", r"負責.*人", r"管理員", r"PM", r"隸屬.*人"],
        "進度查詢": [r"進度", r"完成.*%?", r"进度", r"落後", r"落後多少"],
        "位置查詢": [r"在哪", r"位置", r"地址", r"位於", r"安裝.*哪"],
        "數值查詢": [r"多少", r"數量", r"幾.*(?:個|台|筆)", r"總計", r"數據"],
        "關係查詢": [r"關係", r"關聯.*是", r"差異", r"比較", r"有.*關係"],
        "原因查詢": [r"為什麼", r"原因", r"為何", r"失效", r"故障"],
        "方法查詢": [r"如何", r"怎麼", r"設定.*方法", r"解決"],
    }

    # ===== 優化二:同義詞擴展 =====
    SYNONYM_DICT = {
        # 4G/5G 電信設備
        "基站": ["基地台", "BS", "NodeB", "eNB", "gNB", "NR", "5G基站", "4G基站"],
        "基地台": ["基站", "BS", "NodeB", "eNB", "gNB", "NR"],
        "NR": ["New Radio", "5G", "新空口"],
        "天線": ["天線", " Antenna", "AAU", "RRU", "射頻單元"],
        "頻段": ["Band", "頻段", "頻率", "n78", "n79", "band3"],
        "調變": ["QAM", "QPSK", "Modulation", "調變方式"],
        "韌體": ["Firmware", "版本", "韌體版本", "軟體版本"],
        # WiFi 設備
        "AP": ["Access Point", "基地台", "WiFi AP", "存取點"],
        "SSID": ["網路名稱", "WiFi名稱", "SSID名稱"],
        "頻道": ["Channel", "頻道", "WiFi頻道"],
        # Lab 管理
        "設備": ["儀器", "器材", "實驗設備", "Equipment"],
        "借用": ["借出", "租借", " Borrow", "使用中"],
        "歸還": ["歸還", "還回", "Return", "繳回"],
        # Project
        "專案": ["項目", "Project", "案子", "計畫"],
        "PM": ["專案經理", "專案主管", "專案負責人", "Project Manager"],
        "進度": ["進度", "進度", "Progress", "完成度"],
        "里程碑": ["Milestone", "階段", "里程碑", "關卡"],
        # Automation
        "CI/CD": ["Pipeline", "建置流程", "部署流程", "自動化流程"],
        "建置": ["Build", "編譯", "建置", "編譯部署"],
        "部署": ["Deploy", "部署", "Release", "發布"],
        "觸發": ["Trigger", "觸發條件", "觸發事件"],
        # 通用
        "查詢": ["搜尋", "找", "搜", "查"],
        "哪個": ["哪一個", "哪个", "哪一支"],
    }

    def __init__(
        self,
        neo4j_uri: str = "bolt://neo4j:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "#*cda40da40",
        llm_client = None,
        llm_model: str = "gemma4:12b"
    ):
        """
        初始化搜尋引擎

        Args:
            neo4j_uri: Neo4j 連線 URI
            neo4j_user: Neo4j 使用者
            neo4j_password: Neo4j 密碼
            llm_client: LLM 用戶端
            llm_model: LLM 模型名稱
        """
        self.neo4j_uri = os.getenv("NEO4J_URI") or neo4j_uri or "bolt://neo4j:7687"
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.llm_client = llm_client
        self.llm_model = llm_model
        self.vector_store = None  # 可被外部注入預載入的 vector store
        self.default_basic_top_k = 3
        self.default_deep_top_k = 6

        # 嘗試載入 config，根據設定選擇 LLM Provider
        if self.llm_client is None:
            config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
                    from ..web_api.llm_factory import create_llm_client
                    self.llm_client = create_llm_client(config)
                    search_config = config.get("search", {})
                    self.default_basic_top_k = int(search_config.get("basic_top_k", self.default_basic_top_k))
                    self.default_deep_top_k = int(search_config.get("deep_top_k", self.default_deep_top_k))
                    self.llm_model = config.get("ollama", {}).get("model", "gemma4:12b")
        else:
            config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
                    search_config = config.get("search", {})
                    self.default_basic_top_k = int(search_config.get("basic_top_k", self.default_basic_top_k))
                    self.default_deep_top_k = int(search_config.get("deep_top_k", self.default_deep_top_k))

    def _get_neo4j_driver(self):
        """取得 Neo4j 驅動"""
        try:
            from neo4j import GraphDatabase
            return GraphDatabase.driver(
                self.neo4j_uri,
                auth=(self.neo4j_user, self.neo4j_password)
            )
        except ImportError:
            logger.error("neo4j 模組未安裝")
            return None

    def _resolve_limit(self, requested: Optional[int], default: int) -> int:
        """將可選的 top_k 轉成有效的限制值。"""
        if requested is None or requested <= 0:
            return max(1, int(default))
        return int(requested)

    def _extract_doc_hints(self, query: str) -> List[str]:
        """從查詢中抽取文件代號，優先用於同文件檢索。"""
        if not query:
            return []
        hints = set()
        patterns = [
            r"SCU\d{4}",
            r"SCE\d{4}",
            r"SIT[-_ ]?[A-Z]{2,}[-_ ]?[A-Z0-9-]+",
        ]
        normalized_query = query.upper()
        for pattern in patterns:
            for match in re.findall(pattern, normalized_query):
                normalized = re.sub(r"[\s_]+", "-", match.upper()).strip("-")
                if normalized:
                    hints.add(normalized)
        return sorted(hints)

    def _extract_document_name_hints(self, query: str) -> List[str]:
        """從查詢中抽取更通用的文件名稱片段。"""
        if not query:
            return []

        hints: set[str] = set(self._extract_doc_hints(query))
        hints.update(self._extract_wifi_doc_hints(query))

        text = query.upper()
        generic_patterns = [
            r"(?<![A-Z0-9])[A-Z]{2,}[A-Z0-9]*\d[A-Z0-9-]*(?![A-Z0-9-])",
            r"(?<![A-Z0-9])TYPE[1-6](?![A-Z0-9])",
            r"(?<![A-Z0-9])SIT[-_ ]?[A-Z0-9-]+(?![A-Z0-9-])",
        ]
        for pattern in generic_patterns:
            for match in re.finditer(pattern, text):
                value = re.sub(r"[\s_]+", "-", match.group(0).strip("-"))
                if value:
                    hints.add(value)

        return sorted(hints)

    def _extract_document_search_tokens(self, query: str) -> List[str]:
        """從查詢中抽出可用於文件匹配的 token。"""
        if not query:
            return []

        stopwords = {
            "wifi", "throughput", "report", "reports", "比較", "差異", "不同", "對比", "比對",
            "請", "查詢", "測試", "數據", "內容", "結果", "相關", "文件", "報告",
            "and", "or", "the", "of", "to", "for",
        }
        tokens: list[str] = []

        for hint in self._extract_document_name_hints(query):
            normalized = self._compact_alnum(hint)
            if normalized and normalized not in stopwords:
                tokens.append(normalized)

        for token in re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", query or ""):
            normalized = self._compact_alnum(token)
            if len(normalized) < 3 or normalized in stopwords:
                continue
            tokens.append(normalized)

        for token in re.findall(r"[\u4e00-\u9fff]{2,}", query or ""):
            normalized = token.strip()
            if len(normalized) >= 2:
                tokens.append(normalized)

        ordered: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            if token in seen:
                continue
            seen.add(token)
            ordered.append(token)
        return ordered

    def _document_storage_category(self, profile: dict) -> str:
        """從文件 profile 取得標準類別名稱。"""
        category = str(profile.get("storage_category") or "").strip()
        if category in {"4G/5G", "WiFi", "Lab", "Project", "Automation", "Report", "Simple"}:
            return category

        extraction_mode = str(profile.get("extraction_mode") or "").strip().lower()
        mode_map = {
            "4g5g": "4G/5G",
            "wifi": "WiFi",
            "lab": "Lab",
            "project": "Project",
            "automation": "Automation",
            "report": "Report",
            "simple": "Simple",
        }
        resolved = mode_map.get(extraction_mode, "")
        if resolved:
            return resolved

        blob = " ".join(
            str(profile.get(field) or "")
            for field in ("doc_name", "source_path", "source", "citation_source_name")
        ).lower()
        if any(marker in blob for marker in ("sit-tr-wl", "wifi", "wi-fi", "wireless", "ssid", "mesh", "access point")):
            return "WiFi"
        if any(marker in blob for marker in ("sit-tr-sc", "handover", "nr-handover", "performance test", "report")):
            return "Report"
        return ""

    def _find_document_profiles_for_query(self, query: str, limit: int = 6) -> list[dict]:
        """依 query 從 Neo4j 找出最可能的文件與其類別。"""
        tokens = self._extract_document_search_tokens(query)
        if not tokens:
            return []

        driver = self._get_neo4j_driver()
        if driver is None:
            return []

        try:
            with driver.session() as session:
                result = session.run(
                    """
                    MATCH (d:Document)
                    WHERE any(token IN $tokens WHERE
                        toLower(coalesce(d.name, "")) CONTAINS token OR
                        toLower(coalesce(d.source, "")) CONTAINS token OR
                        replace(toLower(coalesce(d.name, "")), "-", "") CONTAINS token OR
                        replace(toLower(coalesce(d.source, "")), "-", "") CONTAINS token OR
                        replace(replace(toLower(coalesce(d.name, "")), "-", ""), "_", "") CONTAINS token OR
                        replace(replace(toLower(coalesce(d.source, "")), "-", ""), "_", "") CONTAINS token
                    )
                    RETURN d.name AS doc_name,
                           d.source AS source_path,
                           coalesce(d.extraction_mode, "") AS extraction_mode,
                           coalesce(d.storage_category, "") AS storage_category
                    LIMIT $scan_limit
                    """,
                    tokens=tokens,
                    scan_limit=max(20, limit * 5),
                )
                candidates = [dict(record) for record in result]
        except Exception as exc:
            logger.warning(f"Neo4j 文件 profile 查詢失敗: {exc}")
            return []
        finally:
            try:
                driver.close()
            except Exception:
                pass

        if not candidates:
            return []

        query_lower = (query or "").lower()
        scored: list[tuple[int, dict]] = []
        for item in candidates:
            doc_name = str(item.get("doc_name") or "").strip()
            source_path = str(item.get("source_path") or "").strip()
            extraction_mode = str(item.get("extraction_mode") or "").strip()
            storage_category = self._document_storage_category(item)
            blob = " ".join([doc_name, source_path, extraction_mode, storage_category]).lower()
            compact_blob = self._compact_alnum(blob)

            score = 0
            if doc_name and doc_name.lower() in query_lower:
                score += 300
            if source_path and Path(source_path).name.lower() in query_lower:
                score += 250

            for token in tokens:
                token_lower = token.lower()
                compact_token = self._compact_alnum(token_lower)
                if token_lower and token_lower in blob:
                    score += 40
                elif compact_token and compact_token in compact_blob:
                    score += 40

            if storage_category == "WiFi" and any(hint in query_lower for hint in ("wifi", "throughput", "2.4", "5ghz", "6ghz")):
                score += 80
            if storage_category == "Report" and self._is_report_like_query(query):
                score += 80

            enriched = _enrich_citation_source({
                "source": doc_name or Path(source_path).name,
                "doc_name": doc_name or Path(source_path).name,
                "source_path": source_path,
                "content": "",
            })
            enriched["extraction_mode"] = extraction_mode
            enriched["storage_category"] = storage_category or extraction_mode
            scored.append((score, enriched))

        scored.sort(key=lambda item: (item[0], str(item[1].get("doc_name") or "")), reverse=True)
        return [profile for score, profile in scored[:limit] if score > 0]

    def _extract_wifi_doc_hints(self, query: str) -> List[str]:
        """從 WiFi 查詢中抽出明確的型號/文件代號。"""
        if not query:
            return []

        hints: set[str] = set()
        query_upper = query.upper()

        # 先抓像 CHS3320N-D388、NCQ2200B2V-D294、BE805 這類帶數字的型號。
        for match in re.finditer(r"(?<![A-Z0-9])[A-Z]{2,}[A-Z0-9]*\d[A-Z0-9-]*(?![A-Z0-9-])", query_upper):
            value = match.group(0).strip("-")
            if value:
                hints.add(value)

        # 若查詢中出現完整檔名片段，也保留。
        for match in re.finditer(r"(?<![A-Z0-9])(?:TP-?LINK\s+)?ARCHER\s+[A-Z0-9-]*\d[A-Z0-9-]*(?![A-Z0-9-])", query_upper):
            value = re.sub(r"\s+", " ", match.group(0)).strip()
            if value:
                hints.add(value)

        return sorted(hints)

    def _extract_case_hints(self, query: str) -> List[str]:
        """從查詢中抽取明確的 case 編號，用於數值題的精準檢索。"""
        if not query:
            return []

        q = query.lower()
        hints: set[str] = set()

        # 明確 case 代號：Case 13、Test Case 16、4.13 Test Case 13
        for match in re.finditer(r"(?:test\s*)?case\s*(\d{1,3})(?!\d)", q, re.IGNORECASE):
            hints.add(match.group(1))

        # range 型：case 13-16、case 13~16
        range_match = re.search(r"(?:test\s*)?case\s*(\d{1,3})\s*[-~]\s*(\d{1,3})(?!\d)", q, re.IGNORECASE)
        if range_match:
            start, end = sorted((int(range_match.group(1)), int(range_match.group(2))))
            for num in range(start, end + 1):
                hints.add(str(num))

        return sorted(hints, key=lambda x: int(x))

    def _extract_case_number(self, text: str) -> Optional[int]:
        """從文字中抽取 case 編號。"""
        if not text:
            return None
        match = re.search(r"(?:test\s*)?case\s*(\d{1,3})(?!\d)", text, re.IGNORECASE)
        if not match:
            match = re.search(r"4\.(\d{1,3})\s*test\s*case", text, re.IGNORECASE)
        if not match:
            return None
        try:
            return int(match.group(1))
        except Exception:
            return None

    def _annotate_case_numbers(self, sources: List[dict]) -> list[tuple[int | None, int, dict]]:
        """為沒有顯式 case 標記的 chunk 補上鄰近 case 編號。

        報告型文件常把同一個 case 切成多個 chunk，後半段 chunk 不一定再重複
        `Test Case XX` 標頭。這裡會沿著 chunk 順序，把同一份報告、同一章節中
        缺少 case 標記的 chunk 視為前一個顯式 case 的延續。
        """
        ordered_sources = sorted(
            list(sources or []),
            key=lambda item: int(item.get("chunk_index", 0) or 0),
        )

        annotated: list[tuple[int | None, int, dict]] = []
        last_case_num: int | None = None
        last_report_key: str = ""
        last_section_title: str = ""

        for idx, src in enumerate(ordered_sources):
            source_key = str(
                src.get("source")
                or src.get("doc_name")
                or src.get("citation_source_name")
                or src.get("report_title")
                or ""
            ).strip().lower()
            section_title = str(src.get("section_title") or "").strip().lower()
            blob = " ".join([
                str(src.get("section_title", "") or ""),
                str(src.get("content", "") or ""),
            ])
            case_num = self._extract_case_number(blob)

            if case_num is not None:
                last_case_num = case_num
                last_report_key = source_key
                last_section_title = section_title
            elif (
                last_case_num is not None
                and source_key
                and source_key == last_report_key
                and section_title
                and section_title == last_section_title
            ):
                case_num = last_case_num

            annotated.append((case_num, idx, src))

        return annotated

    def _extract_case_sections(self, content: str) -> list[tuple[int | None, list[str]]]:
        """將單一 chunk 依 case 標題切成多個片段。

        有些報告 chunk 會在同一段內同時包含前一個 case 的尾巴與下一個 case 的開頭。
        這時不能直接把整段內容都算進同一個 case，否則會把上一個 case 的數值一起帶進來。
        """
        lines = [line.rstrip() for line in str(content or "").splitlines()]
        if not lines:
            return []

        marker_indices: list[tuple[int, int]] = []
        for idx, line in enumerate(lines):
            lower = line.lower()
            if "test case" not in lower:
                continue
            case_num = self._extract_case_number(line)
            if case_num is None:
                continue
            marker_indices.append((idx, case_num))

        if not marker_indices:
            return []

        sections: list[tuple[int | None, list[str]]] = []
        for pos, (start_idx, case_num) in enumerate(marker_indices):
            end_idx = marker_indices[pos + 1][0] if pos + 1 < len(marker_indices) else len(lines)
            segment = [line for line in lines[start_idx:end_idx] if line.strip()]
            if segment:
                sections.append((case_num, segment))
        return sections

    def _extract_case_content_from_text(self, content: str, case_num: int | None) -> str:
        """從合併後的內容中擷取指定 case 的完整區段。

        會保留 target case 標頭之後、下一個 case 標頭之前的所有內容。
        這用來處理 case 尾段落在下一個 chunk、且下一個 chunk 以新 case 標頭開頭的情況。
        """
        if case_num is None:
            return str(content or "").strip()

        lines = [line.rstrip() for line in str(content or "").splitlines()]
        if not lines:
            return ""

        start_idx: int | None = None
        end_idx: int = len(lines)
        target_patterns = [
            re.compile(rf"(?:test\s*)?case\s*{case_num}(?!\d)", re.IGNORECASE),
            re.compile(rf"4\.{case_num}\s*test\s*case\s*{case_num}(?!\d)", re.IGNORECASE),
        ]

        for idx, line in enumerate(lines):
            if any(pattern.search(line) for pattern in target_patterns):
                start_idx = idx
                break

        if start_idx is None:
            return str(content).strip()

        for idx in range(start_idx + 1, len(lines)):
            lower = lines[idx].lower()
            if "test case" not in lower:
                continue
            next_case = self._extract_case_number(lines[idx])
            if next_case is not None and next_case != case_num:
                end_idx = idx
                break

        extracted = "\n".join(line for line in lines[start_idx:end_idx] if line.strip()).strip()
        return extracted or str(content).strip()

    def _preferred_report_section_titles(self, query: str) -> list[str]:
        """依查詢內容推斷應優先使用的章節名稱。"""
        text = (query or "").lower()
        if self._is_report_summary_query(text):
            return ["summary", "test result summary"]
        if any(hint in text for hint in ("performance test", "throughput", "latency", "bler", "rtt", "tcp", "udp", "數據", "數值", "case", "test case")):
            return ["performance test"]
        return []

    def _prefer_report_section_sources(self, query: str, sources: List[dict]) -> List[dict]:
        """優先保留與查詢意圖相符的章節來源。"""
        if not sources:
            return []

        preferred_titles = self._preferred_report_section_titles(query)
        if not preferred_titles:
            return sources

        normalized = []
        for source in sources:
            section_blob = " ".join([
                str(source.get("section_title") or ""),
                str(source.get("content") or ""),
            ]).lower()
            normalized.append((source, section_blob))

        preferred = [
            source for source, section_blob in normalized
            if any(title in section_blob for title in preferred_titles)
        ]

        # 若找到偏好的章節，就只保留它；找不到才退回原始來源。
        return preferred if preferred else sources

    def _merge_numeric_case_sources_for_output(self, query: str, sources: List[dict]) -> List[dict]:
        """將同一 case 的多個 chunk 合併成單一輸出來源。

        這個 helper 會同時處理：
        - 顯式 case 標頭
        - 沒有重複 case 標頭但屬於同一章節延續的 chunk
        - 只保留每個 case 的合併後內容，避免 direct output 只顯示前半段
        """
        selected_sources = self._select_numeric_case_sources(query, sources)
        if not selected_sources:
            return []

        all_sources = self._prefer_report_section_sources(query, sources)
        all_annotated = self._annotate_case_numbers(all_sources)
        grouped_sources: dict[int, list[dict]] = {}
        ordered_sources = []
        annotated = self._annotate_case_numbers(selected_sources)
        for case_num, _, src in annotated:
            chunk_index = int(src.get("chunk_index", 0) or 0)
            ordered_sources.append((case_num if case_num is not None else 9999, chunk_index, src))

        ordered_sources.sort(key=lambda item: (item[0], item[1]))
        for case_num, _, src in ordered_sources:
            grouped_sources.setdefault(case_num, []).append(src)

        merged_sources: List[dict] = []
        for case_num, _, _ in ordered_sources:
            if case_num not in grouped_sources:
                continue
            sources_for_case = grouped_sources.pop(case_num)

            section_title = ""
            source_name = ""
            doc_name = ""
            source_path = ""
            project_code = ""
            report_type = ""
            test_items = ""
            for src in sources_for_case:
                section_title = section_title or str(src.get("section_title") or "").strip()
                source_name = source_name or str(src.get("citation_source_name") or src.get("source") or src.get("doc_name") or "").strip()
                doc_name = doc_name or str(src.get("doc_name") or src.get("source") or "").strip()
                source_path = source_path or str(src.get("source_path") or "").strip()
                project_code = project_code or str(src.get("project_code") or "").strip()
                report_type = report_type or str(src.get("report_type") or "").strip()
                test_items = test_items or str(src.get("test_items") or "").strip()
            report_key = str(doc_name or source_name).strip().lower()

            # 補上 case 結尾後方的第一個相鄰 chunk，避免尾段落在下一個 chunk 時被截掉。
            selected_keys = {self._source_dedup_key(src) for src in sources_for_case}
            same_section_sources = [
                src for case_annotation, _, src in all_annotated
                if case_annotation is not None
                and int(src.get("chunk_index", 0) or 0) >= min(int(item.get("chunk_index", 0) or 0) for item in sources_for_case)
                and str(src.get("section_title") or "").strip().lower() == section_title.lower()
                and str(src.get("doc_name") or src.get("source") or src.get("source_name") or "").strip().lower() == report_key
            ]
            if same_section_sources:
                max_chunk_index = max(int(src.get("chunk_index", 0) or 0) for src in sources_for_case)
                for _, _, src in all_annotated:
                    chunk_index = int(src.get("chunk_index", 0) or 0)
                    if chunk_index != max_chunk_index + 1:
                        continue
                    if str(src.get("section_title") or "").strip().lower() != section_title.lower():
                        continue
                    if str(src.get("doc_name") or src.get("source") or src.get("source_name") or "").strip().lower() != report_key:
                        continue
                    src_key = self._source_dedup_key(src)
                    if src_key in selected_keys:
                        break
                    sources_for_case = sources_for_case + [src]
                    break

            merged_chunks: list[tuple[int, str]] = []
            for src in sorted(sources_for_case, key=lambda item: int(item.get("chunk_index", 0) or 0)):
                content = str(src.get("content") or "").strip()
                if not content:
                    continue
                case_sections = self._extract_case_sections(content)
                if case_sections:
                    selected_segments = [
                        "\n".join(segment).strip()
                        for section_case, segment in case_sections
                        if section_case == case_num
                    ]
                    if selected_segments:
                        for segment in selected_segments:
                            if segment:
                                merged_chunks.append((int(src.get("chunk_index", 0) or 0), segment))
                        continue
                merged_chunks.append((int(src.get("chunk_index", 0) or 0), content))

            merged_content = "\n".join(
                segment for _, segment in sorted(merged_chunks, key=lambda item: item[0])
                if segment.strip()
            ).strip()
            merged_content = self._extract_case_content_from_text(merged_content, case_num) or merged_content

            merged_sources.append({
                "source": source_name or doc_name,
                "doc_name": doc_name or source_name,
                "content": merged_content or self._merge_numeric_case_sources(sources_for_case),
                "score": max(float(src.get("score", 0) or 0) for src in sources_for_case),
                "chunk_index": min(int(src.get("chunk_index", 0) or 0) for src in sources_for_case),
                "section_title": section_title,
                "source_path": source_path,
                "report_title": source_name or doc_name,
                "project_code": project_code,
                "report_type": report_type,
                "test_items": test_items,
            })

        return merged_sources

    def _merge_numeric_case_sources_for_output_all_cases(self, query: str, sources: List[dict]) -> List[dict]:
        """將同一份報告中所有 case 的多個 chunk 依序合併。

        compare 類全 case 對照需要保留所有 case，而不是只挑最高 4 個 case。
        """
        if not sources:
            return []

        all_sources = self._prefer_report_section_sources(query, sources)
        annotated = self._annotate_case_numbers(all_sources)
        grouped_sources: dict[int, list[dict]] = {}
        ordered_cases: list[int] = []

        for case_num, _, src in annotated:
            if case_num is None:
                continue
            if case_num not in grouped_sources:
                grouped_sources[case_num] = []
                ordered_cases.append(case_num)
            grouped_sources[case_num].append(src)

        merged_sources: List[dict] = []
        for case_num in sorted(ordered_cases):
            sources_for_case = grouped_sources.get(case_num, [])
            if not sources_for_case:
                continue

            section_title = ""
            source_name = ""
            doc_name = ""
            source_path = ""
            project_code = ""
            report_type = ""
            test_items = ""
            for src in sources_for_case:
                section_title = section_title or str(src.get("section_title") or "").strip()
                source_name = source_name or str(src.get("citation_source_name") or src.get("source") or src.get("doc_name") or "").strip()
                doc_name = doc_name or str(src.get("doc_name") or src.get("source") or "").strip()
                source_path = source_path or str(src.get("source_path") or "").strip()
                project_code = project_code or str(src.get("project_code") or "").strip()
                report_type = report_type or str(src.get("report_type") or "").strip()
                test_items = test_items or str(src.get("test_items") or "").strip()

            merged_chunks: list[tuple[int, str]] = []
            for src in sorted(sources_for_case, key=lambda item: int(item.get("chunk_index", 0) or 0)):
                content = str(src.get("content") or "").strip()
                if not content:
                    continue
                case_sections = self._extract_case_sections(content)
                if case_sections:
                    selected_segments = [
                        "\n".join(segment).strip()
                        for section_case, segment in case_sections
                        if section_case == case_num
                    ]
                    if selected_segments:
                        for segment in selected_segments:
                            if segment:
                                merged_chunks.append((int(src.get("chunk_index", 0) or 0), segment))
                        continue
                merged_chunks.append((int(src.get("chunk_index", 0) or 0), content))

            merged_content = "\n".join(
                segment for _, segment in sorted(merged_chunks, key=lambda item: item[0])
                if segment.strip()
            ).strip()
            merged_content = self._extract_case_content_from_text(merged_content, case_num) or merged_content

            merged_sources.append({
                "source": source_name or doc_name,
                "doc_name": doc_name or source_name,
                "content": merged_content or self._merge_numeric_case_sources(sources_for_case),
                "score": max(float(src.get("score", 0) or 0) for src in sources_for_case),
                "chunk_index": min(int(src.get("chunk_index", 0) or 0) for src in sources_for_case),
                "section_title": section_title,
                "source_path": source_path,
                "report_title": source_name or doc_name,
                "project_code": project_code,
                "report_type": report_type,
                "test_items": test_items,
            })

        return merged_sources

    def _should_preserve_all_numeric_cases(self, query: str) -> bool:
        """判斷數值題是否應輸出所有 case，而不是只保留尾段 case。"""
        if not query:
            return False
        if self._extract_case_hints(query):
            return False

        q = str(query).lower()
        signals = [
            "詳細",
            "完整",
            "全部",
            "所有",
            "逐case",
            "逐 case",
            "列出",
            "顯示",
            "明細",
            "測試數據",
            "完整數據",
            "全部數據",
            "詳細數據",
        ]
        return any(signal.lower() in q for signal in signals)

    def _source_dedup_key(self, source: dict) -> tuple[str, str, str, str]:
        """來源去重鍵：文件 + chunk + 章節 + 內容雜湊。"""
        content = str(source.get("content", "") or "")
        return (
            str(source.get("source", "") or source.get("doc_name", "") or source.get("name", "")).strip().lower(),
            str(source.get("chunk_index", "") or ""),
            str(source.get("section_title", "") or "").strip().lower(),
            hashlib.sha1(content.encode("utf-8", errors="ignore")).hexdigest()[:16],
        )

    def _source_matches_case_hints(self, source_text: str, case_hints: List[str]) -> bool:
        """判斷來源是否明確命中查詢中的 case 編號。"""
        if not case_hints:
            return False
        text = (source_text or "").lower()
        for case_num in case_hints:
            # 支援 Test Case 13、4.13 Test Case 13、case 13 這幾種常見寫法
            if re.search(rf"(?:test\s*)?case\s*{re.escape(case_num)}(?!\d)", text, re.IGNORECASE):
                return True
        return False

    def _section_boost(self, text: str, numeric_mode: bool = False) -> int:
        """依章節名稱給予權重，讓報告型文件優先帶出關鍵章節。"""
        lower = (text or "").lower()
        if numeric_mode:
            boost_map = [
                ("performance test", 120),
                ("test result summary", 5),
                ("result summary", 5),
                ("test summary", 0),
                ("summary", -10),
                ("reference", 40),
                ("test config", 20),
                ("test configuration", 20),
                ("test env", 15),
                ("test environment", 15),
                ("introduction", 5),
                ("preface", -20),
                ("table of contents", -40),
                ("cover", -50),
                ("screenshot", -10),
                ("appendix", -10),
            ]
            for keyword, weight in boost_map:
                if keyword in lower:
                    return weight
            return 0

        boost_map = [
            ("performance test", 80),
            ("reference", 70),
            ("test result summary", 65),
            ("result summary", 60),
            ("test summary", 55),
            ("summary", 45),
            ("test config", 30),
            ("test configuration", 30),
            ("test env", 20),
            ("test environment", 20),
            ("introduction", 10),
            ("preface", -10),
            ("table of contents", -30),
            ("cover", -40),
            ("screenshot", -5),
            ("appendix", -5),
        ]
        for keyword, weight in boost_map:
            if keyword in lower:
                return weight
        return 0

    def _rank_vector_results(self, results: List[dict], query: str, top_k: int) -> List[dict]:
        """根據文件代號與章節權重重排向量結果。"""
        if not results:
            return []

        doc_hints = self._extract_doc_hints(query)
        case_hints = self._extract_case_hints(query)
        query_terms = [
            term.lower()
            for term in re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", query or "")
            if len(term) >= 3
        ]
        query_terms = list(dict.fromkeys(query_terms))
        matching_results = []
        if doc_hints:
            for item in results:
                doc_name = str(item.get("doc_name", "")).upper()
                if any(hint in doc_name for hint in doc_hints):
                    matching_results.append(item)
            if matching_results:
                logger.info(
                    "Doc hints matched, narrowing vector results to %d/%d items: %s",
                    len(matching_results),
                    len(results),
                    doc_hints,
                )
                results = matching_results

        if case_hints:
            case_matching_results = []
            for item in results:
                blob = " ".join(
                    str(item.get(field, "") or "")
                    for field in ("doc_name", "section_title", "content", "answer")
                )
                if self._source_matches_case_hints(blob, case_hints):
                    case_matching_results.append(item)
            if case_matching_results:
                logger.info(
                    "Case hints matched, narrowing vector results to %d/%d items: %s",
                    len(case_matching_results),
                    len(results),
                    case_hints,
                )
                results = case_matching_results

        def _sort_key(item: dict):
            doc_name = str(item.get("doc_name", ""))
            score = float(item.get("score", 0.0) or 0.0)
            section_title = str(item.get("section_title", ""))
            numeric_mode = self._is_numeric_extraction_query(query)
            section_boost = self._section_boost(section_title, numeric_mode=numeric_mode)
            doc_boost = 0
            if doc_hints and any(hint in doc_name.upper() for hint in doc_hints):
                doc_boost = 200
            case_boost = 0
            if case_hints:
                blob = " ".join(
                    str(item.get(field, "") or "")
                    for field in ("doc_name", "section_title", "content", "answer")
                )
                if self._source_matches_case_hints(blob, case_hints):
                    case_boost = 400

            source_name = str(item.get("source_name") or "").strip()
            source_path = str(item.get("source_path") or "").strip()
            source_blob = " ".join(
                part for part in (
                    source_name,
                    source_path,
                    str(item.get("doc_name", "") or ""),
                    str(item.get("section_title", "") or ""),
                )
                if part
            ).lower()
            filename_boost = 0
            if query_terms and source_blob:
                matched_terms = [term for term in query_terms if term in source_blob]
                if matched_terms:
                    # 檔名/來源名稱精準命中時，優先於單純語意相近的結果。
                    filename_boost = 250 + min(len(matched_terms), 5) * 40

            # 保留原始 score，但把同文件與關鍵章節優先權拉高
            return (doc_boost + case_boost + filename_boost + section_boost + score, score)

        ranked = sorted(results, key=_sort_key, reverse=True)
        return ranked[:top_k]

    # ===== 優化一:意圖分類 =====
    def classify_intent(self, query: str) -> Tuple[str, float]:
        """
        使用規則匹配分類使用者查詢意圖

        Args:
            query: 使用者問題

        Returns:
            Tuple[str, float]: (意圖類型, 信心度)
        """
        query_lower = query.lower()
        scores = {}

        for intent, patterns in self.INTENT_PATTERNS.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    score += 1
            if score > 0:
                scores[intent] = score

        if not scores:
            return "一般查詢", 0.5

        # 取得最高分的意圖
        best_intent = max(scores, key=scores.get)
        confidence = min(scores[best_intent] / 3.0, 1.0)  # 正規化到 0-1

        logger.info(f"意圖分類: {best_intent} (信心度: {confidence:.2f})")
        return best_intent, confidence

    # ===== 優化二:同義詞擴展 =====
    def expand_synonyms(self, keywords: List[str]) -> List[str]:
        """
        擴展關鍵字的同義詞

        Args:
            keywords: 原始關鍵字列表

        Returns:
            List[str]: 擴展後的關鍵字列表(包含同義詞)
        """
        expanded = list(keywords)  # 保留原始關鍵字

        for kw in keywords:
            # 檢查是否有同義詞
            for key, synonyms in self.SYNONYM_DICT.items():
                if key in kw or kw in key:
                    for syn in synonyms:
                        if syn not in expanded:
                            expanded.append(syn)

        # 額外的中英文擴展
        for kw in keywords:
            # 轉換大小寫
            if kw.lower() != kw:
                expanded.append(kw.lower())
            if kw.upper() != kw:
                expanded.append(kw.upper())

        logger.info(f"同義詞擴展: {keywords} -> {expanded}")
        return expanded

    # ===== 優化三:語意相似度過濾 =====
    def filter_by_similarity(self, results: List[Dict], threshold: float = 0.3) -> List[Dict]:
        """
        過濾低相似度的搜尋結果

        Args:
            results: 搜尋結果列表
            threshold: 相似度閾值(預設 0.3)

        Returns:
            List[Dict]: 過濾後的結果
        """
        if not results:
            return []

        # 檢查結果是否有 score 欄位
        filtered = []
        for r in results:
            score = r.get("score", r.get("similarity", 0.5))
            if score >= threshold:
                filtered.append(r)
            else:
                logger.info(f"過濾低相似度結果: {r.get('name', r.get('entity', 'unknown'))} (score={score:.3f})")

        logger.info(f"語意相似度過濾: {len(results)} -> {len(filtered)} (threshold={threshold})")
        return filtered

    # ===== 優化四:Entity Type 感知搜尋 =====
    def get_entity_types_for_intent(self, intent: str) -> List[str]:
        """
        根據意圖取得要搜尋的 Entity 類型

        Args:
            intent: 意圖類型

        Returns:
            List[str]: 要搜尋的 Entity 類型列表
        """
        intent_type_map = {
            "設備查詢": ["設備", "設備型號", "SerialNumber", "Firmware"],
            "狀態查詢": ["狀態", "Status", "設備", "參數"],
            "人員查詢": ["Borrower", "Manager", "PM", "TeamMember"],
            "進度查詢": ["Progress", "Milestone", "專案", "ProjectName"],
            "位置查詢": ["Location", "測試位置", "安裝位置", "覆蓋範圍"],
            "數值查詢": ["Parameter", "功率", "頻段", "DataRate"],
            "關係查詢": ["Entity", "設備", "網路"],
            "原因查詢": ["Status", "Fault", "Error", "異常"],
            "方法查詢": ["ScriptName", "Trigger", "BuildResult"],
            "一般查詢": ["設備", "Entity", "ProjectName", "AccessPoint"],
        }
        return intent_type_map.get(intent, ["Entity"])

    def extract_keywords(self, query: str) -> List[str]:
        """
        使用規則式萃取關鍵字，避免每次查詢都額外呼叫 LLM。

        Args:
            query: 使用者的原始問題

        Returns:
            List[str]: 萃取出的關鍵字列表
        """
        if not query:
            return []

        text = sanitize_for_cypher(query)
        if not text:
            return [query]

        # 抽出中英文技術片段，保留像 SCU2140、5GHz、4G/5G 這類關鍵字。
        raw_tokens = re.findall(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*|[\u4e00-\u9fff]{2,}", text)
        raw_tokens.extend(re.findall(r"\d+(?:\.\d+)?\s?(?:GHz|MHz|kHz|G|M|K)|\d+G/\d+G|\d+G|\d+GHz", text, re.IGNORECASE))

        keywords: List[str] = []
        seen = set()
        for token in raw_tokens:
            normalized = token.strip()
            if len(normalized) < 2:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            keywords.append(normalized)
            if len(keywords) >= 5:
                break

        if not keywords:
            keywords = [query]

        logger.info(f"規則式萃取關鍵字: {keywords}")
        return keywords

    def basic_search(self, query: str, top_k: Optional[int] = None) -> Dict:
        """
        基本搜尋模式 - 使用萃取關鍵字搜尋文件內容
        整合四大優化功能:意圖分類、同義詞擴展、語意過濾、Entity Type感知

        Args:
            query: 搜尋查詢
            top_k: 回傳結果數

        Returns:
            Dict: 搜尋結果與 LLM 生成答案
        """
        top_k = self._resolve_limit(top_k, self.default_basic_top_k)

        # ===== 優化一:意圖分類 =====
        intent, confidence = self.classify_intent(query)
        logger.info(f"basic_search 意圖分類: {intent} (信心度: {confidence:.2f})")

        # 先萃取關鍵字
        keywords = self.extract_keywords(query)

        # ===== 安全過濾 =====
        # 檢查不相關查詢
        if is_irrelevant_query(query):
            logger.info(f"檢測到不相關查詢: {query}")
            return {
                "status": "success",
                "mode": "basic",
                "query": query,
                "intent": "不相關",
                "intent_confidence": 1.0,
                "keywords_used": [],
                "expanded_keywords": [],
                "answer": "這個問題與系統知識庫無關，無法回答。",
                "sources": []
            }

        # ===== 優化二:同義詞擴展 =====
        expanded_keywords = self.expand_synonyms(keywords)

        # 對關鍵字進行安全過濾，防止 Cypher 注入
        expanded_keywords = [sanitize_for_cypher(kw) for kw in expanded_keywords]
        expanded_keywords = [kw for kw in expanded_keywords if kw]  # 移除空字串

        handover_result = self._build_handover_general_summary_result(query)
        if handover_result is not None:
            handover_result.update({
                "mode": "basic",
                "query": query,
                "intent": intent,
                "intent_confidence": confidence,
                "keywords_used": keywords,
                "expanded_keywords": expanded_keywords,
            })
            return handover_result

        driver = self._get_neo4j_driver()
        if driver is None:
            return {"status": "error", "message": "Neo4j 未連線", "mode": "basic"}

        # 如果沒有有效關鍵字，返回空結果
        if not expanded_keywords:
            logger.info(f"沒有有效關鍵字可用於搜尋")
            return {
                "status": "success",
                "mode": "basic",
                "query": query,
                "intent": intent,
                "intent_confidence": confidence,
                "keywords_used": keywords,
                "expanded_keywords": [],
                "answer": "無法理解這個問題的關鍵字，請重新描述。",
                "sources": []
            }


        try:
            with driver.session() as session:
                # 使用 OR 條件搜尋多個關鍵字(使用擴展後的關鍵字)
                keyword_conditions = " OR ".join([
                    f"(d.content CONTAINS '{kw}' OR d.name CONTAINS '{kw}')"
                    for kw in expanded_keywords
                ])

                cypher = f"""
                    MATCH (d:Document)
                    WHERE {keyword_conditions}
                    RETURN d.name as name, d.content as content, d.source as source
                    LIMIT $limit
                """

                result = session.run(cypher, limit=top_k)
                docs = [dict(record) for record in result]

            driver.close()

            # ===== 優化三:語意相似度過濾 =====
            docs = self.filter_by_similarity(docs, threshold=0.3)

            if not docs:
                return {
                    "status": "success",
                    "mode": "basic",
                    "query": query,
                    "intent": intent,
                    "intent_confidence": confidence,
                    "keywords_used": keywords,
                    "expanded_keywords": expanded_keywords,
                    "answer": f"在知識庫中找不到與「{'、'.join(keywords)}」相關的文件。",
                    "sources": []
                }

            if self._should_return_no_performance_section(query, docs):
                return {
                    "status": "success",
                    "mode": "basic",
                    "query": query,
                    "intent": intent,
                    "intent_confidence": confidence,
                    "keywords_used": keywords,
                    "expanded_keywords": expanded_keywords,
                    "answer": self._build_no_performance_section_answer(docs),
                    "sources": [{"source": doc["name"], "content": doc.get("content", "")[:500]} for doc in docs],
                }

            # 組合上下文
            context = "\n\n".join([
                f"文件:{doc['name']}\n內容:{doc.get('content', '')[:500]}"
                for doc in docs
            ])

            # 使用 LLM 生成答案(帶意圖資訊)
            answer = self._generate_answer(query, context, docs, keywords, intent)

            return {
                "status": "success",
                "mode": "basic",
                "query": query,
                "intent": intent,
                "intent_confidence": confidence,
                "keywords_used": keywords,
                "expanded_keywords": expanded_keywords,
                "answer": answer,
                "sources": [{"source": doc["name"], "content": doc.get("content", "")[:500]} for doc in docs]
            }

        except Exception as e:
            logger.error(f"基本搜尋失敗: {e}")
            return {"status": "error", "message": str(e), "mode": "basic"}

    def deep_search(self, query: str, mode: str = "local", top_k: Optional[int] = None) -> Dict:
        """
        深層搜尋模式 - 使用萃取關鍵字搜尋知識圖譜
        整合四大優化功能：意圖分類、同義詞擴展、語意過濾、Entity Type感知

        Args:
            query: 搜尋查詢
            mode: "local"(局部圖譜搜尋) / "global"(全局)

        Returns:
            Dict: 搜尋結果與 LLM 生成答案
        """
        top_k = self._resolve_limit(top_k, self.default_deep_top_k)

        # ===== 優化一：意圖分類 =====
        intent, confidence = self.classify_intent(query)
        logger.info(f"deep_search 意圖分類: {intent} (信心度: {confidence:.2f})")
        
        # 先萃取關鍵字
        keywords = self.extract_keywords(query)
        
        # ===== 優化二：同義詞擴展 =====
        expanded_keywords = self.expand_synonyms(keywords)
        
        # ===== 優化四：Entity Type 感知搜尋 =====
        target_types = self.get_entity_types_for_intent(intent)
        type_condition = " OR ".join([f"e.type = '{t}'" for t in target_types])
        
        driver = self._get_neo4j_driver()
        if driver is None:
            return {"status": "error", "message": "Neo4j 未連線", "mode": "deep"}

        try:
            with driver.session() as session:
                if mode == "local":
                    # Local Search:找相關實體及其連接(使用萃取關鍵字+擴展+Type感知)
                    keyword_conditions = " OR ".join([
                        f"(e.name CONTAINS '{kw}' OR e.description CONTAINS '{kw}')"
                        for kw in expanded_keywords
                    ])
                    
                    # 加入 Entity Type 條件
                    type_clause = f"AND ({type_condition})" if type_condition else ""
                    
                    cypher = f"""
                        MATCH (e:Entity)
                        WHERE {keyword_conditions} {type_clause}
                    WITH e LIMIT $limit
                        OPTIONAL MATCH (e)-[r]-(related)
                        RETURN e.name as entity, e.type as type,
                               e.description as description,
                               collect(DISTINCT related.name) as connections
                        LIMIT $limit
                    """

                    result = session.run(cypher, limit=top_k)
                    graph_data = [dict(record) for record in result]

                    # ===== 優化三：語意相似度過濾 =====
                    graph_data = self.filter_by_similarity(graph_data, threshold=0.3)

                    if not graph_data:
                        return {
                            "status": "success",
                            "mode": "deep",
                            "query": query,
                            "intent": intent,
                            "intent_confidence": confidence,
                            "keywords_used": keywords,
                            "expanded_keywords": expanded_keywords,
                            "target_entity_types": target_types,
                            "answer": f"在知識圖譜中找不到與「{'、'.join(keywords)}」相關的實體。",
                            "sources": []
                        }

                    # 格式化圖譜上下文
                    context = self._format_graph_context(graph_data)

                    # 使用 LLM 生成答案(帶圖譜推理+意圖)
                    answer = self._generate_answer_with_graph(query, context, graph_data, keywords, intent)

                    return {
                        "status": "success",
                        "mode": "deep",
                        "query": query,
                        "intent": intent,
                        "intent_confidence": confidence,
                        "keywords_used": keywords,
                        "expanded_keywords": expanded_keywords,
                        "target_entity_types": target_types,
                        "answer": answer,
                        "graph_results": graph_data
                    }

                else:
                    # Global Search:用關鍵字搜尋文件(使用擴展後的關鍵字)
                    keyword_conditions = " OR ".join([
                        f"(d.content CONTAINS '{kw}' OR d.name CONTAINS '{kw}')"
                        for kw in expanded_keywords
                    ])

                    cypher = f"""
                        MATCH (d:Document)
                        WHERE {keyword_conditions}
                        RETURN d.name as name, d.content as content
                        LIMIT $limit
                    """

                    result = session.run(cypher, limit=top_k)
                    docs = [dict(record) for record in result]

                    # 語意相似度過濾
                    docs = self.filter_by_similarity(docs, threshold=0.3)

                    if not docs:
                        return {
                            "status": "success",
                            "mode": "deep",
                            "query": query,
                            "intent": intent,
                            "intent_confidence": confidence,
                            "keywords_used": keywords,
                            "expanded_keywords": expanded_keywords,
                            "answer": f"在知識圖譜中找不到與「{'、'.join(keywords)}」相關的文件。",
                            "sources": []
                        }

                    context = "\n\n".join([
                        f"文件:{doc['name']}\n內容:{doc.get('content', '')[:500]}"
                        for doc in docs
                    ])

                    answer = self._generate_answer_with_graph(query, context, docs, keywords, intent)

                    return {
                        "status": "success",
                        "mode": "deep",
                        "query": query,
                        "intent": intent,
                        "intent_confidence": confidence,
                        "keywords_used": keywords,
                        "expanded_keywords": expanded_keywords,
                        "answer": answer,
                        "sources": docs
                    }

        except Exception as e:
            logger.error(f"深層搜尋失敗: {e}")
            return {"status": "error", "message": str(e), "mode": "deep"}

    def _generate_answer(self, query: str, context: str, docs: List, keywords: List, intent: str = "一般查詢") -> str:
        """使用 LLM 根據上下文生成答案(包含來源+意圖感知)"""
        if self.llm_client is None:
            return f"根據文件內容,關於「{query}」的回答:\n\n{context[:500]}..."

        try:
            # 組合來源清單
            source_list = [f"- {doc['name']}" for doc in docs]
            source_str = "\n".join(source_list)

            prompt = f"""根據以下上下文回答問題。如果無法從上下文找到答案,請說「無法從提供的文件回答這個問題」。

使用者意圖：{intent}
關鍵字：{keywords}

規則：
- 若查詢明確在詢問 `Performance Test` / throughput / latency / BLER / RTT / case / test case 等性能數據，且來源是 Handover 報告而沒有 `Performance Test` 章節，請直接回答「這份 Handover 報告沒有 Performance Test 章節，因此無對應章節可回覆。」不得自行補數據或改答其他章節。
- 若只是一般報告資訊、摘要或其他章節內容，請正常整理可用資料，不要僅因為沒有 `Performance Test` 就直接拒答。

參考文件:
{source_str}

上下文:
{context}

問題:{query}

【重要】如果回答中包含 JSON 資料,請使用美化的格式(indent=2, 多行顯示),不要放在同一行。

請根據以上文件回答,並在答案結尾列出相關的檔案來源。"""

            response = self.llm_client.chat([
                {"role": "user", "content": prompt}
            ], temperature=0.3)

            return response.strip()

        except Exception as e:
            logger.error(f"LLM 生成答案失敗: {e}")
            return f"生成答案時發生錯誤: {e}"

    def _generate_answer_with_graph(self, query: str, context: str, graph_data: any, keywords: List, intent: str = "一般查詢") -> str:
        """使用 LLM 根據圖譜上下文生成答案(包含來源+意圖感知)"""
        if self.llm_client is None:
            return f"根據知識圖譜,關於「{query}」的回答:\n\n{context[:500]}..."

        try:
            # 組合實體清單
            entity_list = [f"- {record.get('entity', '未知')} ({record.get('type', '未知類型')})"
                         for record in graph_data if isinstance(record, dict)]
            entity_str = "\n".join(entity_list)

            prompt = f"""你是一個使用知識圖譜進行推理的專家。請根據以下圖譜資訊回答問題。

使用者意圖：{intent}
關鍵字:{keywords}

圖譜中的相關實體:
{entity_str}

圖譜上下文:
{context}

問題:{query}

【重要】如果回答中包含 JSON 資料,請使用美化的格式(indent=2, 多行顯示),不要放在同一行。

請利用圖譜中的實體關係進行推理,並给出結構化的答案。如果無法從圖譜找到答案,請說「無法從知識圖譜回答這個問題」。

在答案結尾,請標注涉及的實體來源。"""

            response = self.llm_client.chat([
                {"role": "user", "content": prompt}
            ], temperature=0.3)

            return response.strip()

        except Exception as e:
            logger.error(f"LLM 生成答案失敗: {e}")
            return f"生成答案時發生錯誤: {e}"

    def _format_graph_context(self, graph_results: List[Dict]) -> str:
        """將圖譜查詢結果格式化為上下文字串"""
        if not graph_results:
            return "(無相關圖譜資訊)"

        context_parts = []
        for record in graph_results:
            entity = record.get("entity", "未知實體")
            etype = record.get("type", "未知類型")
            desc = record.get("description", "")
            connections = record.get("connections", [])

            conn_str = ", ".join([c for c in connections if c]) if connections else "無"

            context_parts.append(
                f"實體:{entity}(類型:{etype})\n"
                f"描述:{desc}\n"
                f"相關連接:{conn_str}"
            )

        return "\n\n".join(context_parts) if context_parts else "(無相關圖譜資訊)"

    def _is_numeric_extraction_query(self, query: str) -> bool:
        """判斷是否為數值抽取題。這類題應逐列轉寫，不做跨 case 摘要。"""
        q = query.lower()
        numeric_keywords = [
            "performance test", "performance", "throughput", "吞吐", "throughput數", "throughput數據",
            "latency", "延遲", "rtt", "sinr", "rsrp", "rsrq",
            "bler", "rssi", "dbm", "mbps", "kbps", "mb/s", "case",
            "test case", "peak", "average", "平均", "最大", "最小", "最高", "最低",
            "數據", "數值",
        ]
        return any(keyword in q for keyword in numeric_keywords) or bool(re.search(r"scu\d+(?!\d)", q, re.IGNORECASE))

    def _is_report_like_query(self, query: str) -> bool:
        """判斷是否為報告型查詢。"""
        text = (query or "").lower()
        report_hints = (
            "report",
            "報告",
            "測試",
            "throughput",
            "performance",
            "test result",
            "test results",
            "summary",
            "rtt",
            "bler",
            "latency",
            "吞吐",
            "吞吐量",
        )
        if any(hint in text for hint in report_hints):
            return True
        return bool(re.search(r"(?:scu|sce)\d+(?!\d)", text))

    def _is_report_performance_data_query(self, query: str) -> bool:
        """判斷是否為 Performance Test 數據查詢。"""
        text = (query or "").lower()
        return any(
            hint in text
            for hint in (
                "performance test",
                "performance",
                "throughput",
                "latency",
                "bler",
                "rtt",
                "tcp",
                "udp",
                "性能",
                "case",
                "test case",
                "throughput 數據",
                "throughput data",
            )
        )

    def _is_report_summary_query(self, query: str) -> bool:
        """判斷是否為摘要型報告查詢。"""
        text = (query or "").lower()
        return any(hint in text for hint in ("summary", "摘要", "總結", "概覽"))

    def _is_wifi_specific_query(self, query: str) -> bool:
        """判斷是否為 WiFi / specific device 查詢。"""
        text = (query or "").lower()
        if not text:
            return False
        if re.search(r"(?:scu|sce)\d+(?!\d)", text):
            return False
        wifi_hints = (
            "tp-link",
            "tp link",
            "archer",
            "be805",
            "mesh",
            "ssid",
            "router",
            "access point",
            "ap",
            "2.4ghz",
            "5ghz",
            "6ghz",
            "wifi",
            "wi-fi",
            "wifi6",
            "wifi7",
            "wireless",
            "unii",
        )
        return any(hint in text for hint in wifi_hints)

    def _compact_alnum(self, value: str) -> str:
        """將文字壓縮成只保留英數字，便於做檔名精準比對。"""
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    def _find_wifi_document_metadatas_for_query(self, query: str, limit: int = 4) -> list[dict]:
        """依 query 推回最可能的 WiFi 文件 metadata 清單。"""
        document_profiles = self._find_document_profiles_for_query(query, limit=max(limit * 2, 6))
        wifi_profiles = [
            profile for profile in document_profiles
            if self._document_storage_category(profile) == "WiFi"
        ]
        query_intent = self.classify_query_intent(query)
        if wifi_profiles and not (query_intent == "compare" and len(wifi_profiles) < 2):
            return [
                self._build_wifi_metadata_source(profile)
                for profile in wifi_profiles[: max(1, int(limit))]
            ]

        if not self._is_wifi_specific_query(query):
            return []

        query_compact = self._compact_alnum(query)
        if not query_compact:
            return []

        specific_hints = self._extract_wifi_doc_hints(query)
        specific_compacts = [self._compact_alnum(hint) for hint in specific_hints if self._compact_alnum(hint)]

        root_dir = Path(__file__).resolve().parents[2]
        search_roots = [
            root_dir / "data" / "uploads",
            root_dir / "data" / "raw",
            root_dir / "data" / "processed",
        ]

        candidates: list[tuple[int, dict]] = []
        best_by_doc: dict[str, tuple[int, dict]] = {}
        for base_dir in search_roots:
            if not base_dir.exists():
                continue
            for md_file in base_dir.rglob("*.md"):
                converted_path = str(md_file)
                doc_name = md_file.stem
                candidate_text = " ".join([
                    md_file.name,
                    doc_name,
                    str(md_file.parent.name),
                    str(md_file.parent.parent.name) if md_file.parent.parent else "",
                    converted_path,
                ])
                candidate_compact = self._compact_alnum(candidate_text)
                if not candidate_compact:
                    continue

                score = 0
                if specific_compacts:
                    specific_match = False
                    for hint_compact in specific_compacts:
                        if hint_compact and hint_compact in candidate_compact:
                            specific_match = True
                            score += 700
                            break
                    if not specific_match:
                        continue
                else:
                    if query_compact == candidate_compact:
                        score += 500
                    if query_compact in candidate_compact:
                        score += 300

                query_tokens = [
                    token.lower()
                    for token in re.findall(r"[A-Za-z0-9]+", query)
                    if len(token) >= 2
                ]
                if specific_compacts:
                    query_tokens = [
                        token for token in query_tokens
                        if token not in {"wifi", "throughput", "report", "reports", "測試", "數據", "內容"}
                    ]
                matched_tokens = [token for token in query_tokens if token in candidate_text.lower()]
                if matched_tokens:
                    score += 80 + min(len(matched_tokens), 5) * 20

                if score <= 0:
                    continue

                original_path = md_file.parent.parent / "original" / f"{md_file.stem}.xlsx"
                if not original_path.exists():
                    original_path = md_file.parent.parent / "original" / md_file.with_suffix(".xlsx").name

                candidates.append((score, {
                    "source_name": original_path.name if original_path.exists() else md_file.stem,
                    "source_stem": md_file.stem,
                    "original_path": str(original_path) if original_path.exists() else "",
                    "converted_path": converted_path,
                    "doc_name": md_file.stem,
                    "storage_category": "WiFi",
                    "extraction_mode": "wifi",
                    "category_folder": "WiFi",
                }))

        if not candidates:
            return []

        candidates.sort(key=lambda item: (item[0], len(str(item[1].get("converted_path") or ""))), reverse=True)
        for score, meta in candidates:
            doc_key = str(meta.get("doc_name") or meta.get("source_stem") or meta.get("source_name") or "").lower().strip()
            if not doc_key:
                continue
            existing = best_by_doc.get(doc_key)
            if existing is None or score > existing[0]:
                best_by_doc[doc_key] = (score, meta)

        ordered = sorted(best_by_doc.values(), key=lambda item: (item[0], len(str(item[1].get("converted_path") or ""))), reverse=True)
        return [meta for _, meta in ordered[: max(1, int(limit))]]

    def _find_wifi_document_metadata_for_query(self, query: str) -> dict | None:
        """依 query 推回最可能的 WiFi 文件 metadata。"""
        metas = self._find_wifi_document_metadatas_for_query(query, limit=1)
        return metas[0] if metas else None

    def _merge_wifi_metadata_candidates(self, primary: list[dict], secondary: list[dict]) -> list[dict]:
        """合併 WiFi 文件候選，保留先前順序並去重。"""
        merged: list[dict] = []
        seen: set[str] = set()
        for meta in list(primary or []) + list(secondary or []):
            doc_key = self._compact_alnum(
                str(meta.get("doc_name") or meta.get("source_name") or meta.get("source_stem") or "")
            )
            if not doc_key or doc_key in seen:
                continue
            seen.add(doc_key)
            merged.append(meta)
        return merged

    def _extract_wifi_band_query_targets(self, query: str) -> list[str]:
        """從 WiFi throughput 題目中萃取所有被提及的頻段，保留原始出現順序。"""
        text = (query or "").lower()
        if not text:
            return []

        pattern_map = [
            (r"2\.4(?:\s*ghz|\s*g)?", "2.4"),
            (r"(?<!\d)5(?:\s*ghz|\s*g)?(?!\d)", "5"),
            (r"(?<!\d)6(?:\s*ghz|\s*g)?(?!\d)", "6"),
        ]

        hits: list[tuple[int, str]] = []
        for pattern, band in pattern_map:
            for match in re.finditer(pattern, text):
                hits.append((match.start(), band))

        if not hits:
            return []

        hits.sort(key=lambda item: item[0])
        ordered_bands: list[str] = []
        for _, band in hits:
            if band not in ordered_bands:
                ordered_bands.append(band)
        return ordered_bands

    def _build_wifi_throughput_band_answer(self, query: str, wifi_meta: dict) -> dict | None:
        """直接輸出 WiFi Throughput 指定頻段的原文區塊，避免 LLM/排序漏掉子章節。"""
        raw_body = self._build_wifi_throughput_band_raw_body(query, wifi_meta)
        if not raw_body:
            return None

        raw_then_interpretation = self._compose_raw_then_interpretation(
            query,
            raw_body,
            [self._build_wifi_metadata_source(wifi_meta)],
        )
        if not raw_then_interpretation:
            return None

        return {
            "status": "success",
            "mode": "wifi_band_raw",
            "query": query,
            "answer": raw_then_interpretation,
            "sources": [self._build_wifi_metadata_source(wifi_meta)],
        }

    def _build_wifi_throughput_band_raw_body(self, query: str, wifi_meta: dict) -> str | None:
        """輸出 WiFi Throughput 指定頻段的原文區塊。"""
        bands = self._extract_wifi_band_query_targets(query)

        query_lower = (query or "").lower()
        throughput_hints = ("throughput", "測試數據", "throughput data", "throughput數據", "數據", "data")
        has_throughput_hint = any(hint in query_lower for hint in throughput_hints)
        # WiFi 使用者常直接問「80MHz / 160MHz 數據」，未必明寫 throughput。
        # 只要 query 本身已被判定為 WiFi 題，且又帶有頻段資訊，就允許進入 throughput 原文路徑。
        if not has_throughput_hint and not bands:
            return None

        if not bands:
            # 使用者只問「WiFi Throughput 報告內容」但沒有指定頻段時，
            # 直接回傳報告中常見的 2.4 / 5 / 6GHz throughput 章節，
            # 避免退回 vector search 後只召回前言、圖片索引或目錄 chunk。
            bands = ["2.4", "5", "6"]

        converted_path = str(wifi_meta.get("converted_path") or "").strip()
        if not converted_path:
            return None

        converted_file = Path(converted_path)
        if not converted_file.exists():
            return None

        try:
            converted_text = converted_file.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning(f"讀取 WiFi converted markdown 失敗: {converted_file} - {exc}")
            return None

        section_map = {
            "2.4": [
                "4.1 2.4GHz Test",
            ],
            "5": [
                "4.2 5GHz Test",
            ],
            "6": [
                "4.3 6GHz Test",
            ],
        }

        digests: list[tuple[str, str]] = []
        missing_bands: list[str] = []
        for band in bands:
            target_sections = section_map.get(band, [])
            band_found = False
            for heading in target_sections:
                block = self._find_markdown_section_block_exact(converted_text, heading)
                if block is None:
                    continue
                title, body = block
                body = body.strip()
                if body:
                    digests.append((title, body))
                    band_found = True
            if not band_found:
                missing_bands.append(band)

        if not digests and not missing_bands:
            return None

        source_name = str(wifi_meta.get("source_name") or wifi_meta.get("doc_name") or "WiFi 文件").strip()
        band_label_map = {
            "2.4": "2.4GHz",
            "5": "5GHz",
            "6": "6GHz",
        }
        band_label = " / ".join(band_label_map.get(band, band) for band in bands) if bands else "WiFi"

        original_path = str(wifi_meta.get("original_path") or "").strip()
        citation_source_name = source_name
        if original_path:
            citation_source_name = Path(original_path).name

        raw_lines: list[str] = []
        raw_lines.append(f"來源文件：{citation_source_name}")
        raw_lines.append(f"查詢目標：{band_label} Throughput")
        raw_lines.append("")
        for title, body in digests:
            raw_lines.append(f"### {title}")
            raw_lines.append(body)
            raw_lines.append("")

        for band in missing_bands:
            raw_lines.append(f"### {band_label_map.get(band, band)}")
            raw_lines.append("未找到對應的章節內容。")
            raw_lines.append("")

        raw_body = "\n".join(raw_lines).strip()
        return raw_body

    def _build_wifi_throughput_compare_llm_comment(self, query: str, compare_raw: str, sources: list[dict]) -> str:
        """為 WiFi Throughput compare 生成簡短評論，不新增數字。"""
        if not compare_raw or not sources:
            return ""

        source_names = "\n".join(
            f"- {str(source.get('source_name') or source.get('doc_name') or 'WiFi 文件').strip()}"
            for source in sources
        )

        if self.llm_client is None:
            return self._build_wifi_throughput_compare_comment_fallback(query, compare_raw, sources)

        prompt = f"""請根據下面兩份 WiFi Throughput 報告的原文，輸出 2~4 條簡短比較重點。

限制：
- 只能根據原文比較，不可新增數字或推測未出現的數值。
- 若某一份文件某頻段沒有完整數值，請直接說該頻段原文不足以做精準數值比對。
- 盡量比較 2.4GHz / 5GHz / 6GHz 的 throughput 覆蓋、bandwidth 覆蓋與整體表現差異。
- 使用條列式，不要長篇摘要。

查詢：{query}

來源文件：
{source_names}

原文：
{compare_raw}
"""

        try:
            comment = self.llm_client.chat([
                {"role": "user", "content": prompt}
            ], temperature=0.2)
            comment = (comment or "").strip()
            if comment:
                return comment
        except Exception as e:
            logger.warning(f"WiFi compare LLM 評論生成失敗: {e}")

        return self._build_wifi_throughput_compare_comment_fallback(query, compare_raw, sources)

    def _build_wifi_throughput_compare_comment_fallback(self, query: str, compare_raw: str, sources: list[dict]) -> str:
        """WiFi compare 的保底評論。"""
        source_names = [str(source.get("source_name") or source.get("doc_name") or "WiFi 文件").strip() for source in sources]
        lines = []
        if len(source_names) >= 2:
            lines.append(f"- 已完成 {source_names[0]} 與 {source_names[1]} 的 WiFi Throughput 對照。")
        else:
            lines.append("- 已完成 WiFi Throughput 對照。")
        lines.append("- 這類比較應優先看兩份文件都實際提供數值的頻段與 bandwidth，再比較 Tx / Rx 的高低與 Pass / Fail。")
        lines.append("- 若某一份文件的 6GHz 或特定 bandwidth 沒有完整數值，代表該頻段不適合做直接性能排序。")
        return "\n".join(lines).strip()

    def _build_wifi_throughput_compare_answer(self, query: str, wifi_metas: list[dict]) -> dict | None:
        """將兩份 WiFi Throughput 報告組成比較答案。"""
        if len(wifi_metas) < 2:
            return None

        compare_sources: list[dict] = []
        compare_sections: list[str] = []
        for meta in wifi_metas[:2]:
            raw_body = self._build_wifi_throughput_band_raw_body(query, meta)
            if not raw_body:
                continue
            compare_sources.append(self._build_wifi_metadata_source(meta))
            source_title = str(meta.get("source_name") or meta.get("doc_name") or "WiFi 文件").strip()
            compare_sections.append(f"### {source_title}\n{raw_body}")

        if len(compare_sections) < 2:
            return None

        compare_raw = "\n\n".join(compare_sections).strip()
        llm_comment = self._build_wifi_throughput_compare_llm_comment(query, compare_raw, compare_sources)

        answer_parts = ["## 原文", compare_raw, "", "## 解讀"]
        if llm_comment:
            answer_parts.append(llm_comment.strip())
        else:
            answer_parts.append("- 目前已列出兩份 WiFi 報告的原文，可逐 band 比對 throughput 表現。")

        return {
            "status": "success",
            "mode": "wifi_compare",
            "query": query,
            "answer": "\n".join(answer_parts).strip(),
            "sources": compare_sources,
        }

    def _build_wifi_metadata_source(self, meta: dict) -> dict:
        """把 WiFi 文件 metadata 轉成前端可顯示的來源物件。"""
        original_path = str(
            meta.get("original_path")
            or meta.get("citation_source_path")
            or ""
        ).strip()
        converted_path = str(
            meta.get("converted_path")
            or meta.get("source_path")
            or ""
        ).strip()
        source_name = str(
            meta.get("source_name")
            or meta.get("citation_source_name")
            or ""
        ).strip()
        doc_name = str(meta.get("doc_name") or "").strip() or source_name
        citation_name = Path(original_path).name if original_path else (source_name or doc_name)
        reference_path = original_path or converted_path
        citation_ext = ".xlsx" if original_path.lower().endswith(".xlsx") else Path(reference_path).suffix.lower()
        return {
            "source": source_name or doc_name or citation_name,
            "doc_name": doc_name or citation_name,
            "content": "",
            "source_path": converted_path or original_path,
            "converted_path": converted_path or original_path,
            "original_path": original_path or converted_path,
            "citation_source_name": citation_name,
            "citation_source_path": original_path or converted_path,
            "citation_source_ext": citation_ext,
            "citation_source_kind": "excel" if citation_ext == ".xlsx" else "file",
        }

    def _profile_to_wifi_meta(self, profile: dict) -> dict:
        """將 Neo4j 的文件 profile 轉成 WiFi compare 使用的 metadata。"""
        profile = dict(profile or {})
        return {
            "source": profile.get("citation_source_name") or profile.get("source") or profile.get("doc_name") or "",
            "doc_name": profile.get("doc_name") or profile.get("source") or "",
            "source_name": profile.get("citation_source_name") or profile.get("source_name") or "",
            "source_path": profile.get("source_path") or profile.get("citation_source_path") or "",
            "converted_path": profile.get("source_path") or profile.get("citation_source_path") or "",
            "original_path": profile.get("citation_source_path") or profile.get("source_path") or "",
            "citation_source_name": profile.get("citation_source_name") or profile.get("source_name") or profile.get("doc_name") or "",
            "citation_source_path": profile.get("citation_source_path") or profile.get("source_path") or "",
            "citation_source_ext": profile.get("citation_source_ext") or Path(str(profile.get("citation_source_path") or profile.get("source_path") or "")).suffix.lower(),
            "citation_source_kind": profile.get("citation_source_kind") or "file",
        }

    def _sanitize_numeric_response(self, response: str) -> str:
        """將數值題回答中的摘要/總結段落移除，只保留原始 case table 與來源。"""
        stop_patterns = [
            r"^\s*###\s*(?:🔑\s*)?(?:快速參考|summary|peak performance|key takeaways|重點整理|趨勢觀察|最佳值|最高值|快速結論|總結|摘要)\b",
            r"^\s*##\s*(?:🔑\s*)?(?:快速參考|summary|peak performance|key takeaways|重點整理|趨勢觀察|最佳值|最高值|快速結論|總結|摘要)\b",
            r"^\s*(?:🔑\s*)?(?:快速參考|summary|peak performance|key takeaways|重點整理|趨勢觀察|最佳值|最高值|快速結論|總結|摘要)\b",
        ]
        lines = response.splitlines()
        kept: List[str] = []
        for line in lines:
            if any(re.search(pattern, line, re.IGNORECASE) for pattern in stop_patterns):
                break
            kept.append(line)
        sanitized = "\n".join(kept).strip()
        return sanitized if sanitized else response.strip()

    def _source_search_blob(self, source: dict) -> str:
        """組合來源可用於規則判斷的文字。"""
        return " ".join(
            str(source.get(field, "") or "")
            for field in (
                "citation_source_name",
                "source",
                "doc_name",
                "name",
                "section_title",
                "source_path",
                "content",
            )
        ).lower()

    def _is_handover_report_source(self, source: dict) -> bool:
        """判斷來源是否屬於 Handover 報告。"""
        blob = self._source_search_blob(source)
        if not blob:
            return False
        return "handover" in blob and (
            "nr-handover" in blob
            or "handover test report" in blob
            or "ng handover" in blob
            or "xn handover" in blob
            or "inter handover" in blob
            or "intra handover" in blob
        )

    def _has_report_performance_sources(self, sources: List[dict] | None) -> bool:
        """判斷來源是否包含真正的 Performance Test 詳細內容。"""
        for source in sources or []:
            blob = self._source_search_blob(source)
            if any(hint in blob for hint in ("performance test",)):
                if any(detail_hint in blob for detail_hint in ("test case", "tcp throughput", "latency test")):
                    return True
        return False

    def _find_handover_report_metadata(self, query: str) -> dict | None:
        """依 query 推回對應的 Handover 報告 metadata；若沒有 Performance Test 章節則回傳 metadata。"""
        if not self._is_report_like_query(query) or not self._is_report_performance_data_query(query):
            return None

        query_lower = (query or "").lower()
        project_match = re.search(r"(?:scu|sce)\d+", query_lower)
        if not project_match:
            return None

        project_code = project_match.group(0).lower()
        root_dir = Path(__file__).resolve().parents[2]
        processed_root = root_dir / "data" / "processed"
        if not processed_root.exists():
            return None

        for meta_path in processed_root.rglob("*.source.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            source_name = str(meta.get("source_name") or "").strip()
            source_stem = str(meta.get("source_stem") or "").strip()
            original_path = str(meta.get("original_path") or "").strip()
            converted_path = str(meta.get("converted_path") or "").strip()
            haystack = " ".join([source_name, source_stem, original_path, converted_path]).lower()
            if project_code not in haystack or "handover" not in haystack:
                continue

            converted_file = Path(converted_path) if converted_path else None
            if converted_file and converted_file.exists():
                try:
                    converted_text = converted_file.read_text(encoding="utf-8", errors="ignore").lower()
                except Exception:
                    converted_text = ""
                if "performance test" in converted_text:
                    continue

            return meta

        return None

    def _find_handover_report_metadata_for_general_query(self, query: str) -> dict | None:
        """依 query 推回對應的 Handover 報告 metadata；供一般報告摘要使用。"""
        if not self._is_report_like_query(query):
            return None

        query_lower = (query or "").lower()
        project_match = re.search(r"(?:scu|sce)\d+", query_lower)
        if not project_match:
            return None

        project_code = project_match.group(0).lower()
        root_dir = Path(__file__).resolve().parents[2]
        processed_root = root_dir / "data" / "processed"
        if not processed_root.exists():
            return None

        for meta_path in processed_root.rglob("*.source.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            source_name = str(meta.get("source_name") or "").strip()
            source_stem = str(meta.get("source_stem") or "").strip()
            original_path = str(meta.get("original_path") or "").strip()
            converted_path = str(meta.get("converted_path") or "").strip()
            haystack = " ".join([source_name, source_stem, original_path, converted_path]).lower()
            if project_code not in haystack or "handover" not in haystack:
                continue
            return meta

        return None

    def _build_handover_general_summary_result(self, query: str) -> Dict | None:
        """為 Handover 一般查詢建立完整原文摘要結果。"""
        handover_meta = self._find_handover_report_metadata_for_general_query(query)
        if handover_meta is None:
            return None

        result = self._build_handover_general_summary_answer(query, handover_meta)
        if not result:
            return None

        result.setdefault("status", "success")
        result.setdefault("sources", [self._build_handover_metadata_source(handover_meta)])
        result.setdefault("query", query)
        result.setdefault("mode", "report_graph")
        return result

    def _build_handover_general_summary_answer(self, query: str, meta: dict) -> Dict:
        """為一般 Handover 報告查詢建立摘要型回答。"""
        original_path = str(meta.get("original_path") or "").strip()
        converted_path = str(meta.get("converted_path") or "").strip()
        source_name = str(meta.get("source_name") or "").strip()
        source_label = source_name or (Path(original_path).name if original_path else "") or (Path(converted_path).name if converted_path else "")

        converted_file = Path(converted_path) if converted_path else None
        if not converted_file or not converted_file.exists():
            return {}

        try:
            converted_text = converted_file.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            logger.warning(f"讀取 Handover converted md 失敗: {converted_file}, {exc}")
            return {}

        section_digests = self._build_handover_section_digest(converted_text)
        if not section_digests:
            return {}

        raw_lines: list[str] = [
            f"根據文件內容，以下為 {source_label} 的原文摘要與重點章節摘錄：",
            "",
        ]
        for title, body in section_digests:
            raw_lines.append(f"## {title}")
            raw_lines.append(body.strip())
            raw_lines.append("")

        raw_lines.extend([
            "檔案來源：",
            source_label,
        ])

        raw_body = "\n".join(raw_lines).strip()
        raw_body = re.sub(r"^原文\s*\n", "", raw_body, count=1, flags=re.MULTILINE)
        project_match = re.search(r"(?:scu|sce)\d+", source_name or original_path or converted_path, re.IGNORECASE)
        project_code = project_match.group(0).upper() if project_match else "-"
        relation_lines = [
            f"專案：{project_code}",
            f"原始文件：{source_label or '-'}",
            f"來源路徑：{original_path or converted_path or '-'}",
            f"轉換檔：{converted_path or '-'}",
            f"TestItem：handover",
            f"命中章節：{', '.join(title for title, _ in section_digests[:8]) or '-'}",
        ]
        relation_body = "\n".join(f"- {line}" for line in relation_lines)
        interpretation = self._build_report_graph_interpretation(query, raw_body, [self._build_handover_metadata_source(meta)])
        if not interpretation:
            interpretation = "\n".join([
                "- 這份 Handover 報告已直接抽出原始章節內容，適合逐段檢視設備背景、測試配置與 Handover 測試結果。",
                "- 若要比對細節，可直接從原文中的 Test Result Summary、Xn Handover 與 NG Handover 章節逐列比對。",
            ])

        answer = "\n".join([
            "## 原文",
            raw_body,
            "",
            "## 圖譜關聯",
            relation_body,
            "",
            "## 解讀",
            interpretation.strip(),
        ]).strip()

        return {
            "status": "success",
            "mode": "basic",
            "query": query,
            "answer": answer,
            "sources": [self._build_handover_metadata_source(meta)],
        }

    def _is_handover_catalog_query(self, query: str) -> bool:
        """判斷是否為「有哪些 Handover 報告/專案」這類清單型查詢。"""
        query_lower = (query or "").lower()
        if "handover" not in query_lower:
            return False
        if "compare" in query_lower or "比較" in query_lower or "差異" in query_lower:
            return False
        return any(
            phrase in query_lower
            for phrase in (
                "有哪些",
                "哪些",
                "列出",
                "清單",
                "專案",
                "報告",
                "測試項目",
                "共通",
            )
        )

    def _collect_handover_catalog_entries(self) -> list[dict]:
        """彙整所有 Handover 報告的來源與主要章節。"""
        root_dir = Path(__file__).resolve().parents[2]
        processed_root = root_dir / "data" / "processed"
        if not processed_root.exists():
            return []

        entries: list[dict] = []
        seen_keys: set[tuple[str, str]] = set()

        for meta_path in processed_root.rglob("*.source.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            original_path = str(meta.get("original_path") or "").strip()
            converted_path = str(meta.get("converted_path") or "").strip()
            source_name = str(meta.get("source_name") or "").strip()
            source_stem = str(meta.get("source_stem") or "").strip()
            haystack = " ".join([source_name, source_stem, original_path, converted_path]).lower()
            if "handover" not in haystack:
                continue

            converted_file = Path(converted_path) if converted_path else None
            if not converted_file or not converted_file.exists():
                continue

            try:
                converted_text = converted_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            if "handover" not in converted_text.lower():
                continue

            source_label = source_name or (Path(original_path).name if original_path else "") or (Path(converted_path).name if converted_path else "")
            project_match = re.search(r"(?:scu|sce)\d+", source_name or source_stem or original_path or converted_path, re.IGNORECASE)
            project_code = project_match.group(0).upper() if project_match else ""
            key = (project_code or "", source_label or "")
            if key in seen_keys:
                continue
            seen_keys.add(key)

            section_digests = self._build_handover_section_digest(converted_text)
            section_titles = [title for title, _ in section_digests]
            entries.append({
                "meta": meta,
                "project_code": project_code,
                "source_label": source_label,
                "section_titles": section_titles,
                "source_obj": self._build_handover_metadata_source(meta),
            })

        entries.sort(key=lambda item: ((item.get("project_code") or ""), (item.get("source_label") or "")))
        return entries

    def _build_handover_catalog_answer(self, query: str) -> Dict:
        """建立 Handover 測試項目清單型回答。"""
        entries = self._collect_handover_catalog_entries()
        if not entries:
            return {}

        lines: list[str] = [
            "根據知識庫目前已攝入的 Handover 報告，包含 Handover 測試項目的專案如下：",
            "",
            "| 專案 | 原始文件 | TestItem | 章節 |",
            "|---|---|---|---|",
        ]
        sources: list[dict] = []
        for entry in entries:
            project_code = entry.get("project_code") or "-"
            source_label = entry.get("source_label") or "-"
            section_titles = entry.get("section_titles") or []
            sections = "；".join(section_titles[:6]) if section_titles else "-"
            lines.append(f"| {project_code} | {source_label} | handover | {sections} |")
            sources.append(entry["source_obj"])

        raw_answer = "\n".join(lines).strip()
        interpretation = self._build_report_graph_interpretation(query, raw_answer, sources)
        if not interpretation:
            interpretation = "\n".join([
                "- 目前知識庫中已有多份 Handover 報告，可直接以專案與原始文件名稱對照。",
                "- 若要看各報告內容，可進一步查詢單一專案的 Handover 摘要或原文章節。",
            ])

        answer = "\n".join([
            "## 原文",
            raw_answer,
            "",
            "## 解讀",
            interpretation.strip(),
        ]).strip()

        return {
            "status": "success",
            "mode": "report_graph",
            "query": query,
            "answer": answer,
            "sources": sources,
        }

    def _should_return_no_performance_section(self, query: str, sources: List[dict] | None) -> bool:
        """判斷是否應直接回覆 Handover 報告沒有 Performance Test 章節。"""
        if self._find_handover_report_metadata(query) is not None:
            return True

        if not self._is_report_like_query(query) or not self._is_report_performance_data_query(query):
            return False

        normalized_sources = [source for source in (sources or []) if source]
        if not normalized_sources:
            return False

        if self._has_report_performance_sources(normalized_sources):
            return False

        handover_sources = [source for source in normalized_sources if self._is_handover_report_source(source)]
        if not handover_sources:
            return False

        # 只在來源明顯都是 Handover 報告時才直接回覆，避免混合來源誤攔。
        return len(handover_sources) == len(normalized_sources)

    def _build_no_performance_section_answer(self, sources: List[dict] | None) -> str:
        """建立 Handover 報告缺少 Performance Test 章節的固定回覆。"""
        source_names: List[str] = []
        for source in sources or []:
            source_name = str(
                source.get("citation_source_name")
                or source.get("source")
                or source.get("doc_name")
                or source.get("name")
                or ""
            ).strip()
            if source_name and source_name not in source_names:
                source_names.append(source_name)

        prefix = ""
        if source_names:
            prefix = f"目前來源文件為 {', '.join(source_names[:3])}。"
            if len(source_names) > 3:
                prefix += "…"
            prefix += " "

        return f"{prefix}這份 Handover 報告沒有 `Performance Test` 章節，因此無對應章節可回覆。"

    def _build_handover_metadata_source(self, meta: dict) -> dict:
        """把 metadata 轉成前端可顯示的來源物件。"""
        original_path = str(meta.get("original_path") or "").strip()
        converted_path = str(meta.get("converted_path") or "").strip()
        source_name = str(meta.get("source_name") or "").strip()
        return {
            "source": source_name or (Path(original_path).name if original_path else ""),
            "doc_name": source_name or (Path(original_path).name if original_path else ""),
            "content": "",
            "source_path": converted_path or original_path,
            "citation_source_name": Path(original_path).name if original_path else source_name,
            "citation_source_path": original_path or converted_path,
            "citation_source_ext": ".xlsx" if original_path.lower().endswith(".xlsx") else Path(original_path or converted_path).suffix.lower(),
            "citation_source_kind": "excel" if original_path.lower().endswith(".xlsx") else "file",
        }

    def _split_markdown_sections(self, text: str) -> list[tuple[str, str]]:
        """將 markdown 依 heading 切成 (title, body) 區塊。"""
        if not text:
            return []

        headings = list(re.finditer(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE))
        if not headings:
            return []

        sections: list[tuple[str, str]] = []
        for idx, match in enumerate(headings):
            level = len(match.group(1))
            title = match.group(2).strip()
            start = match.end()
            end = len(text)
            for next_match in headings[idx + 1:]:
                if len(next_match.group(1)) <= level:
                    end = next_match.start()
                    break
            body = text[start:end].strip()
            sections.append((title, body))
        return sections

    def _find_markdown_section_block(self, text: str, heading_prefix: str) -> tuple[str, str] | None:
        """以 heading 前綴尋找對應的 markdown 區塊。"""
        prefix = (heading_prefix or "").strip().lower()
        if not prefix:
            return None

        for title, body in self._split_markdown_sections(text):
            normalized = re.sub(r"\s+", " ", title).strip().lower()
            if normalized.startswith(prefix):
                return title, body
        return None

    def _find_markdown_section_block_exact(self, text: str, heading_title: str) -> tuple[str, str] | None:
        """以 heading 精準名稱尋找對應的 markdown 區塊。"""
        target = re.sub(r"\s+", " ", (heading_title or "")).strip().lower()
        if not target:
            return None

        fallback: tuple[str, str] | None = None
        for title, body in self._split_markdown_sections(text):
            normalized = re.sub(r"\s+", " ", title).strip().lower()
            if normalized == target:
                return title, body
            if fallback is None and normalized.endswith(target):
                fallback = (title, body)
        return fallback

    def _find_text_block_between_markers(self, text: str, start_markers: list[str], end_markers: list[str], start_from: int = 0) -> str:
        """以多個 marker 搜尋單一連續區塊。"""
        if not text:
            return ""

        lowered = text.lower()
        start_pos: int | None = None
        start_marker = ""
        for marker in start_markers:
            marker_lower = (marker or "").lower()
            if not marker_lower:
                continue
            idx = lowered.find(marker_lower, start_from)
            if idx == -1:
                continue
            if start_pos is None or idx < start_pos:
                start_pos = idx
                start_marker = marker

        if start_pos is None:
            return ""

        end_pos = len(text)
        search_from = start_pos + max(len(start_marker), 1)
        for marker in end_markers:
            marker_lower = (marker or "").lower()
            if not marker_lower:
                continue
            idx = lowered.find(marker_lower, search_from)
            if idx == -1:
                continue
            if idx < end_pos:
                end_pos = idx

        return text[start_pos:end_pos].strip()

    def _compact_handover_section_block(self, block_text: str, max_head_lines: int = 24, max_tail_lines: int = 8) -> str:
        """將大型 Handover 區塊壓成可讀的原文節錄，保留頭尾與關鍵統計列。"""
        if not block_text:
            return ""

        lines = [line.rstrip() for line in block_text.splitlines()]
        if len(lines) <= max_head_lines + max_tail_lines + 10:
            return "\n".join(lines).strip()

        keep_indices: set[int] = set()
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if idx < max_head_lines or idx >= len(lines) - max_tail_lines:
                keep_indices.add(idx)
                continue
            if re.match(r"^\|\s*(?:max|avg\.|min|sum|countif)\b", stripped, re.IGNORECASE):
                keep_indices.add(idx)
                continue
            if "handover 100 times" in stripped.lower():
                keep_indices.update(range(max(0, idx - 1), min(len(lines), idx + 2)))
                continue
            if "no | avg. latency" in stripped.lower() or "before | after" in stripped.lower():
                keep_indices.update(range(max(0, idx - 1), min(len(lines), idx + 3)))

        compact_lines: list[str] = []
        previous_kept = -2
        for idx, line in enumerate(lines):
            if idx not in keep_indices:
                continue
            if previous_kept != -2 and idx - previous_kept > 1:
                if compact_lines and compact_lines[-1] != "... 省略中間大量逐 case 數據 ...":
                    compact_lines.append("... 省略中間大量逐 case 數據 ...")
            compact_lines.append(line)
            previous_kept = idx

        return "\n".join(compact_lines).strip()

    def _build_handover_section_digest(self, converted_text: str) -> list[tuple[str, str]]:
        """抽出 Handover 報告中最重要的原文章節，避免 LLM 摘要漏數據。"""
        digests: list[tuple[str, str]] = []

        # 先抓 3.x 摘要區塊，再依報告模板拆成 3.1/3.2。
        summary_block = self._find_text_block_between_markers(
            converted_text,
            ["## 3. Test Result Summary"],
            ["## 4.1", "## 4.2", "## 4.3", "## 4.4", "## 5. Reference", "## 5 Reference"],
        )
        if summary_block:
            if "| Intra-Band Test |" in summary_block and "| Inter-Band Test |" in summary_block:
                intra_block = self._find_text_block_between_markers(
                    summary_block,
                    ["| Intra-Band Test |"],
                    ["| Inter-Band Test |"],
                )
                if intra_block:
                    digests.append(("3.1 Intra-Band Handover Test Summary", intra_block.strip()))

                inter_block = self._find_text_block_between_markers(
                    summary_block,
                    ["| Inter-Band Test |"],
                    ["## 4.1", "## 4.2", "## 4.3", "## 4.4", "## 5. Reference", "## 5 Reference"],
                )
                if inter_block:
                    digests.append(("3.2 Inter-Band Handover Test Summary", inter_block.strip()))

            elif "| Xn Handover Test |" in summary_block and "| N2 Handover Test |" in summary_block:
                xn_block = self._find_text_block_between_markers(
                    summary_block,
                    ["| Xn Handover Test |"],
                    ["| N2 Handover Test |"],
                )
                if xn_block:
                    digests.append(("3.1 Xn Handover Test Summary", xn_block.strip()))

                ng_block = self._find_text_block_between_markers(
                    summary_block,
                    ["| N2 Handover Test |"],
                    ["## 4.1", "## 4.2", "## 5. Reference", "## 5 Reference"],
                )
                if ng_block:
                    digests.append(("3.2 NG Handover Test Summary", ng_block.strip()))
            else:
                compact_summary = self._compact_handover_section_block(summary_block.strip(), max_head_lines=18, max_tail_lines=6)
                if compact_summary:
                    digests.append(("3. Test Result Summary", compact_summary))

        section_specs = [
            (
                "4.1 Intra-band Xn Handover Test",
                ["## 4.1 Intra-band Xn Handover Test", "## 4.1 Xn Handover Test", "## 4.1 Xn Handover"],
                ["## 4.2 Intra-band NG Handover Test", "## 4.2 NG Handover Test", "## 4.2 NG Handover", "## 4.3", "## 4.4", "## 5. Reference", "## 5 Reference"],
            ),
            (
                "4.2 Intra-band NG Handover Test",
                ["## 4.2 Intra-band NG Handover Test", "## 4.2 NG Handover Test", "## 4.2 NG Handover"],
                ["## 4.3", "## 4.4", "## 5. Reference", "## 5 Reference"],
            ),
            (
                "4.3 Inter-band Xn Handover Test",
                ["## 4.3 Inter-band Xn Handover Test", "## 4.3 Inter-band Xn Handover", "## 4.3 Inter Xn"],
                ["## 4.4 Inter-band NG Handover Test", "## 4.4 Inter-band NG Handover", "## 5. Reference", "## 5 Reference"],
            ),
            (
                "4.4 Inter-band NG Handover Test",
                ["## 4.4 Inter-band NG Handover Test", "## 4.4 Inter-band NG Handover", "## 4.4 Inter NG"],
                ["## 5. Reference", "## 5 Reference"],
            ),
        ]

        for title, start_markers, end_markers in section_specs:
            block = self._find_text_block_between_markers(converted_text, start_markers, end_markers)
            if not block:
                continue
            body = self._compact_handover_section_block(block.strip())
            if body:
                digests.append((title, body))

        if not digests:
            # 回退：至少給第一個非圖片摘要的 heading 區塊，避免完全空答。
            for title, body in self._split_markdown_sections(converted_text):
                normalized = title.strip().lower()
                if normalized.startswith("excel 圖片摘要"):
                    continue
                if normalized.startswith("cover") or normalized.startswith("table of contents"):
                    continue
                body = body.strip()
                if body:
                    digests.append((title, body))
                    break

        return digests

    def _merge_numeric_case_sources(self, sources: List[dict]) -> str:
        """將同一 case 的多個 chunk 依順序合併，避免表格被切段後只顯示第一段。"""
        if not sources:
            return ""

        merged_lines: list[str] = []
        seen_lines: set[str] = set()
        for source in sorted(sources, key=lambda item: int(item.get("chunk_index", 0) or 0)):
            content = str(source.get("content") or "").strip()
            if not content:
                continue
            for line in content.splitlines():
                normalized = line.rstrip()
                key = normalized.strip()
                if not key or key in seen_lines:
                    continue
                seen_lines.add(key)
                merged_lines.append(normalized)

        return "\n".join(merged_lines).strip()

    def _extract_report_test_item_hints(self, query: str) -> List[str]:
        """從報告查詢中萃取標準化測試項目。"""
        if not query:
            return []

        text = query.lower()
        hints: list[str] = []

        mapping = [
            (
                "throughput",
                (
                    "performance test",
                    "throughput",
                    "吞吐",
                    "ota throughput",
                    "download speed",
                    "downlink speed",
                    "下載速度",
                    "下載速率",
                    "下載速",
                    "網速",
                ),
            ),
            ("handover", ("handover", "handover test", "ng handover", "xn handover", "inter handover", "intra handover")),
            ("latency", ("latency", "rtt", "延遲")),
            ("bler", ("bler",)),
            ("udp", ("udp",)),
            ("tcp", ("tcp",)),
        ]
        for canonical_name, keywords in mapping:
            if any(keyword in text for keyword in keywords):
                hints.append(canonical_name)

        return sorted(set(hints))

    def _build_report_graph_answer(self, query: str, sources: List[dict]) -> str:
        """根據 report graph 來源建立簡潔回答。"""
        if not sources:
            return f"在 Neo4j 關聯圖譜中找不到與「{query}」相關的報告。"

        query_lower = (query or "").lower()
        asks_case_list = any(
            phrase in query_lower
            for phrase in ("有哪些case", "有哪些 case", "列出throughput底下有哪些case", "底下有哪些case", "底下有哪些 case", "有哪些 case", "列出case")
        )
        asks_latency_reports = "latency" in query_lower or "延遲" in query_lower

        numeric_mode = self._is_numeric_extraction_query(query)
        unique_reports = {}
        for source in sources:
            report_name = str(
                source.get("report_title")
                or source.get("citation_source_name")
                or source.get("source")
                or source.get("doc_name")
                or source.get("name")
                or ""
            ).strip()
            if not report_name:
                continue
            project_code = str(source.get("project_code") or "").strip()
            key = (project_code, report_name)
            entry = unique_reports.setdefault(key, {
                "project_code": project_code,
                "report_name": report_name,
                "source_file": str(source.get("citation_source_name") or source.get("source") or source.get("doc_name") or "").strip(),
                "section_titles": [],
                "test_items": [],
                "case_numbers": [],
                "has_latency": False,
            })
            section_title = str(source.get("section_title") or "").strip()
            if section_title and section_title not in entry["section_titles"]:
                entry["section_titles"].append(section_title)
            test_items = str(source.get("test_items") or "").strip()
            if test_items:
                for item in [part.strip() for part in test_items.split(",") if part.strip()]:
                    if item not in entry["test_items"]:
                        entry["test_items"].append(item)
            content_blob = " ".join([
                str(source.get("content") or ""),
                section_title,
                str(source.get("source_name") or ""),
            ])
            case_numbers = sorted({int(num) for num in re.findall(r"case\s*(\d{1,3})", content_blob, re.IGNORECASE)})
            for case_num in case_numbers:
                if case_num not in entry["case_numbers"]:
                    entry["case_numbers"].append(case_num)
            if "latency test" in content_blob.lower() or "rtt (ms)" in content_blob.lower():
                entry["has_latency"] = True

        if asks_case_list:
            case_lines = [f"根據 Neo4j 關聯圖譜，以下為與「{query}」相關的 Case 清單：", ""]
            case_lines.append("| 專案 | 原始文件 | Case | 章節 |")
            case_lines.append("|---|---|---|---|")
            sorted_entries = sorted(
                unique_reports.values(),
                key=lambda item: (
                    item["project_code"] or "",
                    item["report_name"] or "",
                ),
            )
            for entry in sorted_entries[:12]:
                project_code = entry["project_code"] or "-"
                report_name = entry["report_name"] or "-"
                case_text = ", ".join(str(num) for num in sorted(set(entry["case_numbers"]))) if entry["case_numbers"] else "-"
                sections = "；".join(entry["section_titles"][:3]) if entry["section_titles"] else "-"
                case_lines.append(f"| {project_code} | {report_name} | {case_text} | {sections} |")
            if len(sorted_entries) > 12:
                case_lines.append("| ... | ... | ... | ... |")
            return "\n".join(case_lines).strip()

        if asks_latency_reports:
            latency_entries = [entry for entry in unique_reports.values() if entry.get("has_latency")]
            if latency_entries:
                latency_lines = [f"根據 Neo4j 關聯圖譜，以下報告包含 Latency 測試項目：", ""]
                latency_lines.append("| 專案 | 原始文件 | TestItem | 章節 |")
                latency_lines.append("|---|---|---|---|")
                sorted_entries = sorted(
                    latency_entries,
                    key=lambda item: (
                        item["project_code"] or "",
                        item["report_name"] or "",
                    ),
                )
                for entry in sorted_entries[:12]:
                    project_code = entry["project_code"] or "-"
                    report_name = entry["report_name"] or "-"
                    sections = "；".join(entry["section_titles"][:3]) if entry["section_titles"] else "-"
                    latency_lines.append(f"| {project_code} | {report_name} | latency | {sections} |")
                if len(sorted_entries) > 12:
                    latency_lines.append("| ... | ... | ... | ... |")
                return "\n".join(latency_lines).strip()

        if numeric_mode and len(unique_reports) == 1:
            direct_answer = self._build_numeric_direct_answer(query, sources)
            if direct_answer:
                return direct_answer

        if len(unique_reports) <= 1:
            report_summaries: list[str] = []
            for entry in unique_reports.values():
                parts = [entry["report_name"]]
                if entry["project_code"]:
                    parts.append(entry["project_code"])
                if entry["section_titles"]:
                    parts.append(entry["section_titles"][0])
                if entry["test_items"]:
                    parts.append(f"TestItem={', '.join(entry['test_items'][:3])}")
                report_summaries.append(" / ".join(parts))

            if not report_summaries:
                return f"在 Neo4j 關聯圖譜中找不到與「{query}」相關的報告。"

            lines = [f"根據 Neo4j 關聯圖譜，找到 {len(unique_reports)} 份相關報告：", ""]
            lines.extend(f"- {item}" for item in report_summaries[:8])
            if len(unique_reports) > 8:
                lines.append("...")
            return "\n".join(lines).strip()

        # 跨專案對照表：讓同一個 TestItem 的多份報告能一眼比較
        sorted_entries = sorted(
            unique_reports.values(),
            key=lambda item: (
                item["project_code"] or "",
                item["report_name"] or "",
            ),
        )

        lines = [f"根據 Neo4j 關聯圖譜，找到 {len(unique_reports)} 份相關報告，跨專案對照如下：", ""]
        lines.append("| 專案 | 原始文件 | TestItem | 章節 |")
        lines.append("|---|---|---|---|")
        for entry in sorted_entries[:12]:
            project_code = entry["project_code"] or "-"
            report_name = entry["report_name"] or "-"
            test_items = ", ".join(entry["test_items"][:3]) if entry["test_items"] else "-"
            sections = "；".join(entry["section_titles"][:3]) if entry["section_titles"] else "-"
            lines.append(f"| {project_code} | {report_name} | {test_items} | {sections} |")
        if len(sorted_entries) > 12:
            lines.append("| ... | ... | ... | ... |")

        return "\n".join(lines).strip()

    def _build_report_graph_interpretation(self, query: str, raw_answer: str, sources: List[dict]) -> str:
        """根據原文與來源，產生不改動數字的補充解讀。"""
        if self.llm_client is None or not raw_answer or not sources:
            return ""

        source_lines = []
        for src in sources[:8]:
            source_name = str(src.get("citation_source_name") or src.get("source") or src.get("doc_name") or "").strip()
            section_title = str(src.get("section_title") or "").strip()
            chunk_index = src.get("chunk_index")
            extra_bits = []
            if section_title:
                extra_bits.append(section_title)
            if chunk_index is not None:
                extra_bits.append(f"chunk {chunk_index}")
            extra = f" [{' / '.join(extra_bits)}]" if extra_bits else ""
            source_lines.append(f"- {source_name}{extra}")

        raw_excerpt = self._build_balanced_raw_excerpt(raw_answer, max_chars=2600)

        prompt = f"""你是一個知識庫報告解讀助手。請根據下面已由系統整理好的原文與來源，輸出簡短解讀。

規則：
- 只能根據原文與來源內容做解讀，不可新增原文沒有的數字、峰值、平均值或結論。
- 不要重寫原文表格，不要把原文再完整貼一次。
- 只輸出「解讀」段落，格式請用 2~4 個條列。
- 可以說明趨勢、高低差異、同一報告中各 case 的相對關係。
- 如果原文只是對照表或摘要，就做摘要級解讀，不要硬補細節。
- 若原文不足以做出有把握的解讀，請明確說明資料不足，不能推測。

問題：
{query}

來源：
{chr(10).join(source_lines)}

原文：
{raw_excerpt}

請只輸出解讀段落，避免重複原文，也不要再重複寫出「解讀」這個標題。"""

        try:
            interpretation = self.llm_client.chat([{"role": "user", "content": prompt}], temperature=0.2).strip()
            interpretation = re.sub(r"^\s*(?:#{1,6}\s*)?解讀\s*[:：]?\s*", "", interpretation, flags=re.IGNORECASE).strip()
            if not interpretation:
                raw_text = raw_answer.lower()
                case_matches = sorted(set(re.findall(r"case\s*(\d{1,3})", raw_answer, re.IGNORECASE)), key=lambda x: int(x))
                case_label = ""
                if len(case_matches) == 1:
                    case_label = f"Case {case_matches[0]}"
                elif len(case_matches) > 1:
                    case_label = f"多個 Case（{case_matches[0]}~{case_matches[-1]}）"
                bullets = []
                if "udp throughput" in raw_text and "latency test" in raw_text:
                    bullets.append("原文同時包含 TCP、UDP 與 Latency 區塊，表示這份案例的核心測試資訊已完整列出。")
                if "uplink" in raw_text and "bidirection - ul" in raw_text:
                    bullets.append("Uplink 與 Bidirection - UL 也有對應數值，可直接和原始 Excel 做逐列比對。")
                if "rtt (ms)" in raw_text:
                    bullets.append("RTT 數值已出現在原文中，代表延遲結果沒有被截斷。")
                if not bullets:
                    bullets.append("原文保留了可追溯的逐 case 表格，適合直接與來源 Excel 對照。")
                if case_label:
                    bullets[0] = f"{case_label} 的原文已完整保留。 " + bullets[0]
                interpretation = "\n".join(f"- {bullet}" for bullet in bullets[:3]).strip()
            return interpretation
        except Exception as e:
            logger.warning(f"report_graph 解讀生成失敗: {e}")
            return ""

    def _build_balanced_raw_excerpt(self, raw_answer: str, max_chars: int = 2600) -> str:
        """保留原文開頭與結尾，避免後段章節被截掉。"""
        raw_text = str(raw_answer or "").strip()
        if not raw_text or len(raw_text) <= max_chars:
            return raw_text

        separator = "\n...\n"
        keep_total = max_chars - len(separator)
        if keep_total <= 0:
            return raw_text[:max_chars]

        head_chars = max(800, int(keep_total * 0.6))
        tail_chars = max(400, keep_total - head_chars)
        if head_chars + tail_chars > keep_total:
            tail_chars = keep_total - head_chars
        if tail_chars < 200:
            tail_chars = min(400, keep_total // 3)
            head_chars = keep_total - tail_chars
        if head_chars < 1:
            head_chars = max(1, keep_total // 2)
            tail_chars = keep_total - head_chars

        return f"{raw_text[:head_chars]}{separator}{raw_text[-tail_chars:]}"

    def _compose_raw_then_interpretation(self, query: str, raw_answer: str, sources: List[dict]) -> str:
        """將原文與解讀組成雙段式回答。"""
        raw_answer = (raw_answer or "").strip()
        if not raw_answer:
            return ""

        interpretation = self._build_report_graph_interpretation(query, raw_answer, sources)
        if not interpretation:
            return raw_answer

        return "\n\n".join([
            "## 原文",
            raw_answer,
            "",
            "## 解讀",
            interpretation.strip(),
        ]).strip()

    def _extract_compare_project_sections(self, raw_answer: str) -> list[tuple[str, str]]:
        """從 compare raw answer 中切出各專案區塊。"""
        if not raw_answer:
            return []

        pattern = re.compile(r"(?m)^###\s+(SCU\d+|SCE\d+)\b.*$")
        matches = list(pattern.finditer(raw_answer))
        sections: list[tuple[str, str]] = []
        for idx, match in enumerate(matches):
            project_code = match.group(1).upper().strip()
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw_answer)
            section_text = raw_answer[start:end].strip()
            if project_code and section_text:
                sections.append((project_code, section_text))
        return sections

    def _extract_compare_table_cells(self, section_text: str, label: str, block_marker: str | None = None) -> list[str]:
        """從 markdown 表格中擷取指定列的 cells。"""
        if not section_text or not label:
            return []

        search_text = section_text
        candidate_texts = [search_text]
        if block_marker and block_marker in search_text:
            before, _, after = search_text.partition(block_marker)
            candidate_texts = [part for part in (after, before) if part.strip()]

        pattern = re.compile(rf"(?m)^\|\s*{re.escape(label)}\s*\|(?P<cells>.*)$")
        for candidate_text in candidate_texts:
            match = pattern.search(candidate_text)
            if not match:
                continue
            cells = [cell.strip() for cell in match.group("cells").split("|")]
            cleaned = [cell for cell in cells if cell != ""]
            if cleaned:
                return cleaned
        return []

    def _format_compare_metric_summary(self, metric_label: str, cells_by_project: list[tuple[str, list[str]]], is_rtt: bool = False) -> tuple[str, str]:
        """將多個專案的同一 metric cells 轉成對照列與觀察摘要。"""
        project_values: list[str] = []
        numeric_scores: list[tuple[str, float]] = []

        for project_code, cells in cells_by_project:
            if not cells:
                project_values.append("-")
                continue

            if is_rtt:
                min_v = cells[0] if len(cells) > 0 else "-"
                avg_v = cells[1] if len(cells) > 1 else "-"
                max_v = cells[2] if len(cells) > 2 else "-"
                loss_v = cells[3] if len(cells) > 3 else "-"
                summary = f"Min {min_v} / Avg {avg_v} / Max {max_v} / Loss {loss_v}"
                project_values.append(summary)
                try:
                    numeric_scores.append((project_code, float(str(avg_v).replace(",", ""))))
                except Exception:
                    pass
                continue

            peak_v = cells[3] if len(cells) > 3 else "-"
            avg_v = cells[4] if len(cells) > 4 else "-"
            bler_v = cells[5] if len(cells) > 5 else "-"
            summary = f"Peak {peak_v} / Avg {avg_v} / BLER {bler_v}"
            project_values.append(summary)
            try:
                numeric_scores.append((project_code, float(str(avg_v).replace(",", ""))))
            except Exception:
                pass

        observation = "資料不足以穩定比較"
        if len(numeric_scores) >= 2:
            if is_rtt:
                ordered = sorted(numeric_scores, key=lambda item: item[1])
                best = ordered[0][0]
                worst = ordered[-1][0]
                observation = f"平均 RTT 最低：{best}；最高：{worst}"
            else:
                ordered = sorted(numeric_scores, key=lambda item: item[1], reverse=True)
                best = ordered[0][0]
                worst = ordered[-1][0]
                observation = f"平均值最高：{best}；最低：{worst}"

        return " / ".join(project_values), observation

    def _extract_compare_metric_targets(self, query: str) -> list[str]:
        """根據 compare query 判斷應顯示哪些指標。"""
        text = (query or "").lower()
        targets: list[str] = []

        throughput_hints = (
            "throughput",
            "吞吐",
            "下載速度",
            "下載速率",
            "download speed",
            "downlink speed",
            "網速",
        )
        latency_hints = ("latency", "rtt", "延遲")
        bler_hints = ("bler", "packet loss", "loss rate", "丟包")

        if any(hint in text for hint in throughput_hints):
            targets.append("throughput")
        if any(hint in text for hint in latency_hints):
            targets.append("latency")
        if any(hint in text for hint in bler_hints):
            targets.append("bler")

        if not targets:
            targets = ["throughput", "latency"]

        return targets

    def _extract_case_bler_summary(self, metrics: dict) -> tuple[str, float | None]:
        """從 throughput rows 彙整 BLER 摘要與可比較數值。"""
        bler_bits: list[str] = []
        bler_scores: list[float] = []

        for label, display in (
            ("dl", "DL"),
            ("ul", "UL"),
            ("bidi_dl", "Bidirection DL"),
            ("bidi_ul", "Bidirection UL"),
        ):
            entry = metrics.get(label) or {}
            bler_v = str(entry.get("bler") or "").strip()
            if not bler_v or bler_v == "-":
                continue
            bler_bits.append(f"{display} BLER {bler_v}")
            try:
                bler_scores.append(float(bler_v.replace(",", "")))
            except Exception:
                pass

        summary = " / ".join(bler_bits) if bler_bits else "-"
        if bler_scores:
            return summary, sum(bler_scores) / len(bler_scores)
        return summary, None

    def _extract_case_metric_summary(self, section_text: str, metric_targets: list[str] | None = None) -> tuple[str, dict, dict]:
        """從單一 case 內容抽出可比較的 throughput / latency / BLER 指標摘要。"""
        section_text = str(section_text or "").strip()
        if not section_text:
            return "", {}, {}

        metric_targets = metric_targets or ["throughput", "latency"]
        metric_targets_set = set(metric_targets)
        case_num = self._extract_case_number(section_text)
        metrics: dict[str, dict[str, str]] = {}

        metric_specs = [
            ("dl", "Downlink", None),
            ("ul", "Uplink", None),
            ("bidi_dl", "Bidirection - DL", None),
            ("bidi_ul", "Bidirection - UL", None),
            ("rtt", "RTT (ms)", "Latency Test"),
        ]
        for key, row_label, block_marker in metric_specs:
            cells = self._extract_compare_table_cells(section_text, row_label, block_marker=block_marker)
            if not cells:
                continue
            if key == "rtt":
                min_v = cells[0] if len(cells) > 0 else "-"
                avg_v = cells[1] if len(cells) > 1 else "-"
                max_v = cells[2] if len(cells) > 2 else "-"
                loss_v = cells[3] if len(cells) > 3 else "-"
                metrics[key] = {"min": min_v, "avg": avg_v, "max": max_v, "loss": loss_v}
            else:
                peak_v = cells[3] if len(cells) > 3 else "-"
                avg_v = cells[4] if len(cells) > 4 else "-"
                bler_v = cells[5] if len(cells) > 5 else "-"
                metrics[key] = {"peak": peak_v, "avg": avg_v, "bler": bler_v}

        summary_parts = []
        if "throughput" in metric_targets_set:
            if "dl" in metrics:
                summary_parts.append(f"DL {metrics['dl'].get('avg', '-')}")
            if "ul" in metrics:
                summary_parts.append(f"UL {metrics['ul'].get('avg', '-')}")
            if "bidi_dl" in metrics:
                summary_parts.append(f"Bidirection DL {metrics['bidi_dl'].get('avg', '-')}")
            if "bidi_ul" in metrics:
                summary_parts.append(f"Bidirection UL {metrics['bidi_ul'].get('avg', '-')}")
        if "latency" in metric_targets_set and "rtt" in metrics:
            summary_parts.append(f"RTT {metrics['rtt'].get('avg', '-')}")
        if "bler" in metric_targets_set:
            bler_summary, _ = self._extract_case_bler_summary(metrics)
            if bler_summary != "-":
                summary_parts.append(bler_summary)

        summary = " / ".join(summary_parts) if summary_parts else "-"
        case_label = f"Case {case_num}" if case_num is not None else "Case -"
        return case_label, metrics, {"summary": summary, "case_num": case_num}

    def _build_report_graph_compare_llm_comment(self, query: str, raw_answer: str, compare_table: str) -> str:
        """為 compare 表格生成 LLM 簡短評論，不新增數字。"""
        if self.llm_client is None or not raw_answer or not compare_table:
            return ""

        raw_excerpt = self._build_balanced_raw_excerpt(raw_answer, max_chars=900)

        prompt = f"""你是一個知識庫比較評論助手。請根據下列跨專案固定對照表，輸出 2~3 條簡短評論。

規則：
- 只能根據原文與對照表做評論，不可新增原文沒有的數字、峰值、平均值或結論。
- 不要重寫表格，不要把原文再完整貼一次。
- 只輸出評論段落，使用條列格式。
- 可以說明哪個專案整體較高、哪個較低、哪些指標差距最明顯，但不要補充表格之外的新數字。
- 若資料不足，請直接說資料不足，不要推測。

問題：
{query}

固定對照表：
{compare_table}

請只輸出評論段落，不要加標題。"""

        try:
            comment = ""
            if hasattr(self.llm_client, "generate"):
                comment = str(self.llm_client.generate(prompt, temperature=0.2) or "").strip()
            if not comment and hasattr(self.llm_client, "chat"):
                fallback_prompt = f"請根據下面的跨專案對照表，輸出 2~3 條簡短評論，只能做比較，不可新增數字。\n\n問題：{query}\n\n對照表：\n{compare_table}"
                comment = str(self.llm_client.chat([{"role": "user", "content": fallback_prompt}], temperature=0.2) or "").strip()
            comment = re.sub(r"^\s*(?:#{1,6}\s*)?(?:解讀|評論)\s*[:：]?\s*", "", comment, flags=re.IGNORECASE).strip()
            if comment and self._looks_like_truncated_compare_comment(comment):
                comment = ""
            if not comment:
                comment = self._build_report_graph_compare_comment_fallback(query, raw_answer, compare_table)
            if not comment:
                return ""
            if not comment.lstrip().startswith("-"):
                comment = "\n".join(f"- {line.strip()}" for line in comment.splitlines() if line.strip())
            return comment.strip()
        except Exception as e:
            logger.warning(f"report_graph compare LLM 評論生成失敗: {e}")
            return ""

    def _build_report_graph_compare_all_cases_table(self, query: str, project_case_map: dict[str, dict[int, list[str]]]) -> str:
        """建立跨專案的全 case 對照表。"""
        if not project_case_map:
            return ""

        ordered_projects = list(project_case_map.keys())
        all_case_nums = sorted({case_num for cases in project_case_map.values() for case_num in cases.keys()})
        if not all_case_nums:
            return ""

        metric_targets = self._extract_compare_metric_targets(query)

        table_lines = [
            "| Case | " + " | ".join(ordered_projects) + " | 差異摘要 |",
            "|---|" + "|".join(["---"] * len(ordered_projects)) + "|---|",
        ]

        def _to_float(value: str) -> float | None:
            try:
                return float(str(value).replace(",", "").strip())
            except Exception:
                return None

        for case_num in all_case_nums:
            project_summaries: list[str] = []
            compare_scores: list[tuple[str, float]] = []
            rtt_scores: list[tuple[str, float]] = []
            bler_scores: list[tuple[str, float]] = []

            for project in ordered_projects:
                texts = project_case_map.get(project, {}).get(case_num) or []
                if not texts:
                    project_summaries.append("-")
                    continue
                merged_text = "\n\n".join(texts).strip()
                _, metrics, summary_meta = self._extract_case_metric_summary(merged_text, metric_targets=metric_targets)
                summary = summary_meta.get("summary") or "-"
                project_summaries.append(summary)

                dl_avg = _to_float(metrics.get("dl", {}).get("avg", "")) if metrics.get("dl") else None
                rtt_avg = _to_float(metrics.get("rtt", {}).get("avg", "")) if metrics.get("rtt") else None
                _, bler_avg = self._extract_case_bler_summary(metrics)
                if "throughput" in metric_targets and dl_avg is not None:
                    compare_scores.append((project, dl_avg))
                if "latency" in metric_targets and rtt_avg is not None:
                    rtt_scores.append((project, rtt_avg))
                if "bler" in metric_targets and bler_avg is not None:
                    bler_scores.append((project, bler_avg))

            observation = "資料不足以穩定比較"
            if compare_scores or rtt_scores or bler_scores:
                parts = []
                if "throughput" in metric_targets and compare_scores:
                    best_dl = max(compare_scores, key=lambda item: item[1])[0]
                    worst_dl = min(compare_scores, key=lambda item: item[1])[0]
                    parts.append(f"DL 平均最高：{best_dl}；最低：{worst_dl}")
                if "latency" in metric_targets and rtt_scores:
                    best_rtt = min(rtt_scores, key=lambda item: item[1])[0]
                    worst_rtt = max(rtt_scores, key=lambda item: item[1])[0]
                    parts.append(f"RTT 平均最低：{best_rtt}；最高：{worst_rtt}")
                if "bler" in metric_targets and bler_scores:
                    best_bler = min(bler_scores, key=lambda item: item[1])[0]
                    worst_bler = max(bler_scores, key=lambda item: item[1])[0]
                    parts.append(f"BLER 平均最低：{best_bler}；最高：{worst_bler}")
                if parts:
                    observation = "；".join(parts)

            table_lines.append(f"| Case {case_num} | " + " | ".join(project_summaries) + f" | {observation} |")

        return "\n".join(table_lines).strip()

    def _extract_case_blocks_from_answer(self, answer: str) -> dict[int, list[str]]:
        """從逐 case 原文答案中切出 case block。"""
        if not answer:
            return {}

        lines = [line.rstrip() for line in str(answer).splitlines()]
        case_indices: list[tuple[int, int]] = []
        for idx, line in enumerate(lines):
            match = re.match(r"^\s*###\s*Case\s*(\d{1,3})\b", line, re.IGNORECASE)
            if not match:
                continue
            try:
                case_num = int(match.group(1))
            except Exception:
                continue
            case_indices.append((idx, case_num))

        if not case_indices:
            return {}

        case_map: dict[int, list[str]] = {}
        for pos, (start_idx, case_num) in enumerate(case_indices):
            end_idx = case_indices[pos + 1][0] if pos + 1 < len(case_indices) else len(lines)
            block = "\n".join(line for line in lines[start_idx:end_idx] if line.strip()).strip()
            if not block:
                continue
            case_map.setdefault(case_num, []).append(block)
        return case_map

    def _looks_like_truncated_compare_comment(self, comment: str) -> bool:
        """檢查 compare LLM 評論是否看起來被截斷。"""
        text = (comment or "").strip()
        if not text:
            return True

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return True

        last_line = lines[-1]
        if last_line.endswith(("「", "『", "（", "(", "：", ":", "-", "—", "、")):
            return True
        if last_line.count("「") > last_line.count("」"):
            return True
        if last_line.count("『") > last_line.count("』"):
            return True
        if last_line.count("（") > last_line.count("）"):
            return True
        if len(last_line) < 8 and not re.search(r"[。！？.!?]$", last_line):
            return True
        return False

    def _build_report_graph_compare_comment_fallback(self, query: str, raw_answer: str, compare_table: str) -> str:
        """當 compare LLM 評論被截斷或失敗時，產生保底評論。"""
        rows = [
            line.strip()
            for line in compare_table.splitlines()
            if line.strip().startswith("|") and not line.startswith("|---")
        ]
        if len(rows) < 2:
            return ""

        data_rows = rows[1:] if rows and rows[0].lower().startswith("| 指標 |") else rows
        if not data_rows:
            return ""

        table_text = "\n".join(data_rows)
        project_names = re.findall(r"\|\s*(SCU\d+|SCE\d+)\s*\|", compare_table, re.IGNORECASE)
        project_names = [name.upper() for name in project_names]
        unique_projects = list(dict.fromkeys(project_names))
        common_items = []
        for line in data_rows:
            if "throughput" in line.lower():
                common_items.append("throughput")
            if "latency" in line.lower():
                common_items.append("latency")
            if "handover" in line.lower():
                common_items.append("handover")
        common_items = list(dict.fromkeys(common_items))

        lines = []
        if unique_projects:
            if common_items:
                lines.append(f"- {', '.join(unique_projects[:4])} 的共通測試項目為 {', '.join(common_items[:3])}。")
            else:
                lines.append(f"- {', '.join(unique_projects[:4])} 的對照表已列出相同項目，可直接逐項比較。")
        if "4. Performance Test" in table_text:
            lines.append("- 各專案主要都集中在 4. Performance Test 章節，測試結構一致。")
        if not lines:
            return ""
        return "\n".join(lines[:3]).strip()

    def _build_report_graph_case_list_answer_from_rows(self, query: str, rows: List[dict]) -> str:
        """從 report_graph raw rows 直接組出 case 清單。"""
        if not rows:
            return f"在 Neo4j 關聯圖譜中找不到與「{query}」相關的報告。"

        rows_by_report: dict[str, list[dict]] = {}
        report_order: list[str] = []
        for row in rows:
            report_key = str(row.get("doc_name") or row.get("report_title") or "").strip()
            if not report_key:
                continue
            if report_key not in rows_by_report:
                rows_by_report[report_key] = []
                report_order.append(report_key)
            rows_by_report[report_key].append(row)

        lines = [f"根據 Neo4j 關聯圖譜，以下為與「{query}」相關的 Case 清單：", ""]
        lines.append("| 專案 | 原始文件 | Case | 章節 |")
        lines.append("|---|---|---|---|")

        for report_key in report_order[:12]:
            report_rows = rows_by_report[report_key]
            if not report_rows:
                continue
            project_code = str(report_rows[0].get("project_code") or "-").strip() or "-"
            report_name = str(report_rows[0].get("report_title") or report_rows[0].get("doc_name") or "-").strip() or "-"
            sections = []
            fallback_sections = []
            case_numbers = set()
            for row in report_rows:
                section_title = str(row.get("section_title") or row.get("header") or "").strip()
                if section_title and section_title not in fallback_sections:
                    fallback_sections.append(section_title)
                if section_title:
                    section_lower = section_title.lower()
                    if any(hint in section_lower for hint in ("performance test", "throughput", "test case")):
                        if section_title not in sections:
                            sections.append(section_title)
                content_blob = " ".join([
                    str(row.get("content") or ""),
                    section_title,
                    str(row.get("source_name") or ""),
                ])
                for num in re.findall(r"case\s*(\d{1,3})", content_blob, re.IGNORECASE):
                    case_numbers.add(int(num))
            case_text = ", ".join(str(num) for num in sorted(case_numbers)) if case_numbers else "-"
            section_text = "；".join((sections or fallback_sections)[:3]) if (sections or fallback_sections) else "-"
            lines.append(f"| {project_code} | {report_name} | {case_text} | {section_text} |")

        if len(report_order) > 12:
            lines.append("| ... | ... | ... | ... |")
        return "\n".join(lines).strip()

    def _build_report_graph_compare_interpretation(self, query: str, raw_answer: str, sources: List[dict]) -> str:
        """根據跨專案原文與來源，產生真正的比較解讀。"""
        if not raw_answer or not sources:
            return ""

        sections = self._extract_compare_project_sections(raw_answer)
        if not sections:
            return ""

        ordered_projects = [project_code for project_code, _ in sections]
        project_order_index = {project: idx for idx, project in enumerate(ordered_projects)}

        metric_specs = [
            ("DL TCP", "Downlink", False, None),
            ("UL TCP", "Uplink", False, None),
            ("Bidirection - DL", "Bidirection - DL", False, None),
            ("Bidirection - UL", "Bidirection - UL", False, None),
            ("RTT", "RTT (ms)", True, "Latency Test"),
        ]

        table_lines = [
            "| 指標 | " + " | ".join(ordered_projects) + " | 差異摘要 |",
            "|---|" + "|".join(["---"] * len(ordered_projects)) + "|---|",
        ]

        metric_rows: list[tuple[str, list[tuple[str, list[str]]], bool]] = []
        for metric_label, row_label, is_rtt, block_marker in metric_specs:
            cells_by_project: list[tuple[str, list[str]]] = []
            for project_code, section_text in sections:
                block_text = section_text
                if block_marker and block_marker in section_text:
                    start = section_text.find(block_marker)
                    block_text = section_text[start:]
                if not is_rtt and "TCP Throuhgput" in block_text and "UDP Throughput" in block_text:
                    block_text = block_text.split("UDP Throughput", 1)[0]
                cells = self._extract_compare_table_cells(block_text, row_label)
                cells_by_project.append((project_code, cells))
            metric_rows.append((metric_label, cells_by_project, is_rtt))

        for metric_label, cells_by_project, is_rtt in metric_rows:
            project_cells: list[str] = []
            _, observation = self._format_compare_metric_summary(metric_label, cells_by_project, is_rtt=is_rtt)
            for project_code, cells in sorted(cells_by_project, key=lambda item: project_order_index.get(item[0], 0)):
                if not cells:
                    project_cells.append("-")
                    continue
                if is_rtt:
                    min_v = cells[0] if len(cells) > 0 else "-"
                    avg_v = cells[1] if len(cells) > 1 else "-"
                    max_v = cells[2] if len(cells) > 2 else "-"
                    loss_v = cells[3] if len(cells) > 3 else "-"
                    project_cells.append(f"Min {min_v} / Avg {avg_v} / Max {max_v} / Loss {loss_v}")
                else:
                    peak_v = cells[3] if len(cells) > 3 else "-"
                    avg_v = cells[4] if len(cells) > 4 else "-"
                    bler_v = cells[5] if len(cells) > 5 else "-"
                    project_cells.append(f"Peak {peak_v} / Avg {avg_v} / BLER {bler_v}")
            table_lines.append(f"| {metric_label} | " + " | ".join(project_cells) + f" | {observation} |")

        compare_table = "\n".join(table_lines).strip()
        llm_comment = self._build_report_graph_compare_llm_comment(query, raw_answer, compare_table)

        if llm_comment:
            return "\n\n".join([
                compare_table,
                "### LLM 簡短評論",
                llm_comment.strip(),
            ]).strip()

        return compare_table

    def _build_source_raw_evidence_block(self, query: str, result: Dict, max_sources: int = 6) -> str:
        """將一般搜尋結果整理成可展示的原始資料區塊。"""
        if not result:
            return ""

        sources = list(result.get("sources") or [])
        if not sources:
            graph_results = list(result.get("graph_results") or [])
            if graph_results:
                sources = [
                    {
                        "source": item.get("entity") or item.get("name") or item.get("source") or "",
                        "type": item.get("type") or "",
                        "content": item.get("description") or item.get("content") or "",
                    }
                    for item in graph_results
                ]

        if not sources:
            return ""

        raw_lines: list[str] = [
            "## 原文",
            f"根據查詢結果，以下為「{query}」的原始資料摘錄：",
            "",
        ]

        appended = 0
        for idx, source in enumerate(sources):
            content = str(
                source.get("content")
                or source.get("description")
                or source.get("text")
                or source.get("summary")
                or ""
            ).strip()
            if not content:
                continue

            source_name = str(
                source.get("citation_source_name")
                or source.get("doc_name")
                or source.get("source")
                or source.get("name")
                or source.get("entity")
                or f"來源 {idx + 1}"
            ).strip()
            section_title = str(source.get("section_title") or source.get("type") or "").strip()
            chunk_index = source.get("chunk_index")
            header_bits = [bit for bit in [source_name, section_title, f"chunk {chunk_index}" if chunk_index is not None else ""] if bit]
            raw_lines.append(f"### {' / '.join(header_bits)}")
            raw_lines.append(content[:1200].strip())
            raw_lines.append("")
            appended += 1
            if appended >= max_sources:
                break

        if appended == 0:
            return ""

        if len(sources) > appended:
            raw_lines.extend([f"... 另有 {len(sources) - appended} 筆來源略去 ...", ""])

        return "\n".join(raw_lines).strip()

    def _prepend_raw_evidence_if_missing(self, query: str, result: Dict) -> Dict:
        """若結果尚未包含原文區塊，則自動補上原文，再保留原本的 LLM 解讀。"""
        if not isinstance(result, dict):
            return result
        if result.get("status") != "success":
            return result

        answer = str(result.get("answer") or "").strip()
        if not answer:
            return result

        normalized_answer = answer.lstrip()
        if normalized_answer.startswith("## 原文"):
            return result
        if "## 原文" in normalized_answer[:300] and "## 解讀" in normalized_answer:
            return result

        raw_block = self._build_source_raw_evidence_block(query, result)
        if not raw_block:
            return result

        wrapped_answer = "\n\n".join([
            raw_block,
            "",
            "## 解讀",
            answer,
        ]).strip()

        new_result = dict(result)
        new_result["answer"] = wrapped_answer
        return new_result

    def _compose_compare_raw_then_interpretation(self, query: str, raw_answer: str, sources: List[dict]) -> str:
        """將跨專案原文與比較解讀組成雙段式回答。"""
        raw_answer = (raw_answer or "").strip()
        if not raw_answer:
            return ""

        interpretation = self._build_report_graph_compare_interpretation(query, raw_answer, sources)
        if not interpretation:
            return raw_answer

        return "\n\n".join([
            "## 原文",
            raw_answer,
            "",
            "## 解讀",
            interpretation.strip(),
        ]).strip()

    def _rows_to_report_graph_sources(self, query: str, rows: List[dict], preserve_all: bool = False) -> List[dict]:
        """把 report graph 原始 rows 轉成可供前端與答案組裝使用的 sources。"""
        if not rows:
            return []

        report_rows: list[tuple[str, list[dict]]] = []
        rows_by_report: dict[str, list[dict]] = {}
        report_order: list[str] = []
        for row in rows:
            report_key = str(row.get("doc_name") or row.get("report_title") or "").strip()
            if not report_key:
                continue
            if report_key not in rows_by_report:
                rows_by_report[report_key] = []
                report_order.append(report_key)
            rows_by_report[report_key].append(row)

        numeric_mode = self._is_numeric_extraction_query(query)

        def _report_row_priority(row: dict) -> tuple[int, int, int]:
            section_title = str(row.get("section_title") or row.get("header") or "").strip()
            content = str(row.get("content") or "").strip()
            section_blob = " ".join([section_title, content[:500]])
            section_boost = self._section_boost(section_blob, numeric_mode=numeric_mode)
            case_boost = 1 if "test case" in section_blob.lower() else 0
            metric_boost = 1 if any(hint in section_blob.lower() for hint in ("throughput", "latency", "bler", "rtt", "tcp", "udp")) else 0
            return (section_boost, case_boost, metric_boost)

        diversify_reports = (
            not preserve_all
            and bool(self._extract_report_test_item_hints(query))
            and not self._extract_doc_hints(query)
            and not self._extract_case_hints(query)
            and len(rows_by_report) > 1
        )
        if diversify_reports:
            per_report_limit = max(2, min(4, self._resolve_limit(None, self.default_basic_top_k) // max(1, len(rows_by_report))))
            selected_rows = []
            for report_key in report_order:
                ranked_rows = sorted(
                    rows_by_report[report_key],
                    key=lambda row: (
                        _report_row_priority(row),
                        -(int(row.get("section_order", 0) or 0)),
                        -(int(row.get("chunk_index", 0) or 0)),
                    ),
                    reverse=True,
                )
                selected_rows.extend(ranked_rows[:per_report_limit])
        else:
            selected_rows = sorted(
                rows,
                key=lambda row: (
                    _report_row_priority(row),
                    -(int(row.get("section_order", 0) or 0)),
                    -(int(row.get("chunk_index", 0) or 0)),
                ),
                reverse=True,
            )

        results: list[dict] = []
        for row in selected_rows:
            results.append({
                "doc_name": row.get("doc_name") or row.get("report_title") or "",
                "content": row.get("content") or "",
                "score": 1.0,
                "chunk_index": row.get("chunk_index", 0) or 0,
                "section_title": row.get("section_title") or row.get("header") or "",
                "source_path": row.get("source_path") or "",
                "report_title": row.get("report_title") or "",
                "project_code": row.get("project_code") or "",
                "report_type": row.get("report_type") or "",
                "test_items": ", ".join([item for item in (row.get("test_items") or []) if item]),
                "source_name": row.get("source_name") or "",
            })

        if self._is_numeric_extraction_query(query) and bool(self._extract_case_hints(query)):
            results = self._merge_numeric_case_sources_for_output(query, results)

        return [
            _enrich_citation_source({
                "source": result["doc_name"],
                "doc_name": result["doc_name"],
                "content": result["content"],
                "score": result["score"],
                "chunk_index": result["chunk_index"],
                "section_title": result["section_title"],
                "source_path": result["source_path"],
                "report_title": result.get("report_title", ""),
                "project_code": result.get("project_code", ""),
                "test_items": result.get("test_items", ""),
            })
            for result in results
        ]

    def _report_graph_query_rows(
        self,
        session,
        query: str,
        project_hints: List[str],
        test_item_hints: List[str],
        case_hints: List[str],
        top_k: int,
    ) -> List[dict]:
        """執行 Neo4j report graph rows 查詢。"""
        cypher = """
            MATCH (r:Report)
            WHERE coalesce(r.publish_status, 'published') = 'published'
              AND coalesce(r.is_current, true) = true
              AND ($project_count = 0 OR toUpper(r.project_code) IN $project_hints)
              AND (
                $test_item_count = 0 OR EXISTS {
                    MATCH (r)-[:HAS_TEST_ITEM]->(t:TestItem)
                    WHERE toLower(t.canonical_name) IN $test_item_hints
                }
              )
            OPTIONAL MATCH (r)-[:HAS_TEST_ITEM]->(t:TestItem)
            OPTIONAL MATCH (r)-[:HAS_SECTION]->(s:Section)
            OPTIONAL MATCH (s)-[:HAS_SOURCE_CHUNK]->(sc:SourceChunk)
            WHERE (
                $case_count = 0 OR any(case_hint IN $case_hints WHERE
                    toLower(coalesce(sc.content, '') + ' ' + coalesce(s.text, '')) CONTAINS ('case ' + case_hint)
                )
            )
            WITH r, s, sc, collect(DISTINCT t.canonical_name) AS test_items
            RETURN
                r.doc_name AS doc_name,
                r.title AS report_title,
                r.project_code AS project_code,
                r.report_type AS report_type,
                test_items AS test_items,
                s.title AS section_title,
                s.header AS header,
                s.section_order AS section_order,
                sc.content AS content,
                sc.chunk_index AS chunk_index,
                sc.source_path AS source_path,
                sc.source_name AS source_name
            ORDER BY project_code, doc_name, section_order, chunk_index
            LIMIT $limit
        """
        result = session.run(
            cypher,
            limit=max(top_k * 40, 200),
            project_count=len(project_hints),
            project_hints=[hint.upper() for hint in project_hints],
            test_item_count=len(test_item_hints),
            test_item_hints=[hint.lower() for hint in test_item_hints],
            case_count=len(case_hints),
            case_hints=[str(hint) for hint in case_hints],
        )
        return [dict(record) for record in result]

    def _build_report_graph_compare_answer(self, query: str, compare_sections: List[str]) -> str:
        """將 compare 類報告答案組成跨專案對照格式。"""
        if not compare_sections:
            return f"在 Neo4j 關聯圖譜中找不到與「{query}」相關的報告。"
        return "\n\n".join([
            f"根據 Neo4j 關聯圖譜，以下為各專案同一 Case 的對照：",
            "",
            "\n\n".join(compare_sections),
        ]).strip()

    def _report_graph_search_raw(self, query: str, top_k: Optional[int] = None) -> Dict:
        """使用 report graph 做關聯檢索，回傳可直接組答案的來源。"""
        top_k = self._resolve_limit(top_k, self.default_basic_top_k)

        handover_result = self._build_handover_general_summary_result(query)
        if handover_result is not None:
            handover_result["mode"] = "report_graph"
            handover_result["query"] = query
            return handover_result

        project_hints = self._extract_doc_hints(query)
        test_item_hints = self._extract_report_test_item_hints(query)
        case_hints = self._extract_case_hints(query)
        query_lower = (query or "").lower()
        asks_case_list = any(
            phrase in query_lower
            for phrase in ("有哪些case", "有哪些 case", "列出throughput底下有哪些case", "底下有哪些case", "底下有哪些 case", "有哪些 case", "列出case")
        )
        asks_latency_reports = "latency" in query_lower or "延遲" in query_lower

        if self._is_handover_catalog_query(query):
            handover_catalog_result = self._build_handover_catalog_answer(query)
            if handover_catalog_result:
                return handover_catalog_result

        if not project_hints and not test_item_hints and not case_hints:
            return {"status": "success", "mode": "report_graph", "query": query, "answer": "", "sources": []}

        driver = self._get_neo4j_driver()
        if driver is None:
            return {"status": "error", "message": "Neo4j 未連線", "mode": "report_graph"}

        try:
            with driver.session() as session:
                intent = self.classify_query_intent(query)
                compare_mode = intent == "compare" and len(project_hints) > 1 and (case_hints or test_item_hints)
                compare_metric_targets = set(self._extract_compare_metric_targets(query))
                effective_test_item_hints = list(test_item_hints)
                if compare_mode and ("latency" in compare_metric_targets or "bler" in compare_metric_targets):
                    if "throughput" not in effective_test_item_hints:
                        effective_test_item_hints.append("throughput")

                if compare_mode:
                    numeric_mode = self._is_numeric_extraction_query(query)
                    compare_without_case_hint = numeric_mode and not case_hints
                    compare_sections: list[str] = []
                    compare_sources: list[dict] = []
                    compare_case_map: dict[str, dict[int, list[str]]] = {}
                    for project_hint in project_hints:
                        rows = self._report_graph_query_rows(
                            session,
                            query,
                            [project_hint],
                            effective_test_item_hints,
                            case_hints,
                            top_k,
                        )
                        project_sources = self._rows_to_report_graph_sources(query, rows, preserve_all=compare_without_case_hint)
                        compare_sources.extend(project_sources)

                        if compare_without_case_hint:
                            project_case_map = compare_case_map.setdefault(project_hint.upper(), {})
                            use_raw_case_blocks = "throughput" not in compare_metric_targets
                            if not use_raw_case_blocks:
                                all_case_sources = self._merge_numeric_case_sources_for_output_all_cases(query, project_sources)
                                direct_answer = self._build_numeric_direct_answer(query, all_case_sources, all_cases=True)
                                if not direct_answer:
                                    direct_answer = self._build_report_graph_answer(query, project_sources)

                                case_blocks = self._extract_case_blocks_from_answer(direct_answer)
                                if case_blocks:
                                    for case_num, blocks in case_blocks.items():
                                        project_case_map.setdefault(case_num, []).extend(blocks)
                                    continue

                            for source in project_sources:
                                content = str(source.get("content") or "").strip()
                                if not content:
                                    continue
                                section_chunks = self._extract_case_sections(content)
                                if section_chunks:
                                    for case_num, segment in section_chunks:
                                        if case_num is None:
                                            continue
                                        project_case_map.setdefault(case_num, []).append("\n".join(segment).strip())
                                    continue
                                case_num = self._extract_case_number(" ".join([
                                    str(source.get("section_title") or ""),
                                    content,
                                ]))
                                if case_num is None:
                                    continue
                                project_case_map.setdefault(case_num, []).append(content)
                            continue

                        project_answer = ""
                        if self._is_numeric_extraction_query(query):
                            project_answer = self._build_numeric_direct_answer(query, project_sources)
                        if not project_answer:
                            project_answer = self._build_report_graph_answer(query, project_sources)
                        if not project_answer:
                            project_answer = f"在 Neo4j 關聯圖譜中找不到與「{project_hint}」相關的報告。"
                        compare_sections.append(f"### {project_hint}\n{project_answer}")

                    if compare_without_case_hint and compare_case_map:
                        if "latency" in compare_metric_targets:
                            for source in compare_sources:
                                content = str(source.get("content") or "").strip()
                                if not content:
                                    continue
                                if "rtt (ms)" not in content.lower() and "latency test" not in content.lower():
                                    continue
                                project_code = str(source.get("project_code") or "").strip().upper()
                                if not project_code:
                                    continue
                                case_num = self._extract_case_number(" ".join([
                                    str(source.get("section_title") or ""),
                                    str(source.get("report_title") or ""),
                                    content,
                                ]))
                                if case_num is None:
                                    continue
                                project_case_map = compare_case_map.setdefault(project_code, {})
                                case_texts = project_case_map.setdefault(case_num, [])
                                if content not in case_texts:
                                    case_texts.append(content)

                        compare_table = self._build_report_graph_compare_all_cases_table(query, compare_case_map)
                        if compare_table:
                            llm_comment = self._build_report_graph_compare_llm_comment(query, compare_table, compare_table)
                            answer_parts = ["## 原文", compare_table, "", "## 解讀"]
                            if llm_comment:
                                answer_parts.extend(["### LLM 簡短評論", llm_comment.strip()])
                            else:
                                answer_parts.append("- 目前已列出各專案所有 case 的對照表，可逐 case 比對整體差異。")
                            return {
                                "status": "success",
                                "mode": "report_graph",
                                "query": query,
                                "answer": "\n".join(answer_parts).strip(),
                                "sources": compare_sources,
                            }

                    if compare_sources:
                        compare_raw_answer = self._build_report_graph_compare_answer(query, compare_sections)
                        return {
                            "status": "success",
                            "mode": "report_graph",
                            "query": query,
                            "answer": self._compose_compare_raw_then_interpretation(query, compare_raw_answer, compare_sources),
                            "sources": compare_sources,
                        }

                rows = self._report_graph_query_rows(
                    session,
                    query,
                    project_hints,
                    effective_test_item_hints,
                    case_hints,
                    top_k,
                )

            preserve_all = asks_case_list or asks_latency_reports
            if preserve_all and rows:
                sources = self._rows_to_report_graph_sources(query, rows, preserve_all=True)
                case_list_answer = self._build_report_graph_case_list_answer_from_rows(query, rows)
                if asks_case_list and case_list_answer:
                    return {
                        "status": "success",
                        "mode": "report_graph",
                        "query": query,
                        "answer": self._compose_raw_then_interpretation(query, case_list_answer, sources),
                        "sources": sources,
                    }

            if not rows:
                return {
                    "status": "success",
                    "mode": "report_graph",
                    "query": query,
                    "answer": f"在 Neo4j 關聯圖譜中找不到與「{query}」相關的報告。",
                    "sources": [],
                }

            sources = self._rows_to_report_graph_sources(query, rows, preserve_all=preserve_all)

            context = "\n\n".join([
                f"報告:{row['doc_name']}\n章節:{row.get('section_title', '')}\n內容:{row.get('content', '')[:500]}"
                for row in sources
            ])

            answer = self._build_report_graph_answer(query, sources)
            if not answer:
                answer = self._generate_answer_vector(query, context, sources)
            answer = self._compose_raw_then_interpretation(query, answer, sources)

            return {
                "status": "success",
                "mode": "report_graph",
                "query": query,
                "answer": answer,
                "sources": sources,
            }
        except Exception as e:
            logger.error(f"report_graph_search_raw 失敗: {e}")
            return {"status": "error", "message": str(e), "mode": "report_graph", "sources": []}
        finally:
            try:
                driver.close()
            except Exception:
                pass

    def _select_numeric_case_sources(self, query: str, sources: List[dict]) -> List[dict]:
        """挑選數值題要輸出的來源。

        - 有明確 case hints 時，僅保留對應 case。
        - 沒有 case hints 時，優先保留同文件中 case 編號最高的 4 個 case，避免 generic 問法只拿到單一 case。
        """
        if not sources:
            return []

        sources = self._prefer_report_section_sources(query, sources)
        case_hints = self._extract_case_hints(query)
        annotated = self._annotate_case_numbers(sources)

        report_keys = {
            str(
                src.get("report_title")
                or src.get("citation_source_name")
                or src.get("source")
                or src.get("doc_name")
                or ""
            ).strip().lower()
            for _, _, src in annotated
            if str(
                src.get("report_title")
                or src.get("citation_source_name")
                or src.get("source")
                or src.get("doc_name")
                or ""
            ).strip()
        }

        if case_hints:
            wanted = {int(hint) for hint in case_hints}
            selected = [src for case_num, _, src in annotated if case_num in wanted]
            if selected:
                return selected
            return sources

        if len(report_keys) <= 1:
            return sources

        numeric_cases = sorted({case_num for case_num, _, _ in annotated if case_num is not None})
        if not numeric_cases:
            return sources

        top_cases = set(numeric_cases[-4:])
        selected = [src for case_num, _, src in annotated if case_num in top_cases]
        return selected if selected else sources

    def _build_numeric_direct_answer(self, query: str, sources: List[dict], all_cases: bool = False) -> str:
        """直接用來源內容組合數值題答案，避免 LLM 把多個 case 縮成單一片段。"""
        all_cases = all_cases or self._should_preserve_all_numeric_cases(query)
        selected_sources = (
            self._merge_numeric_case_sources_for_output_all_cases(query, sources)
            if all_cases
            else self._merge_numeric_case_sources_for_output(query, sources)
        )
        if not selected_sources:
            return ""

        lines = []
        lines.append("根據提供的參考來源，以下為來源文件逐 case 原文摘錄：")
        lines.append("")

        for src in selected_sources:
            section_title = str(src.get("section_title") or "").strip()
            source_name = str(src.get("citation_source_name") or src.get("source") or src.get("doc_name") or "").strip()
            content = str(src.get("content") or "").strip()

            case_num = self._extract_case_number(" ".join([section_title, content]))

            if case_num is not None:
                lines.append(f"### Case {case_num}")
            elif section_title:
                lines.append(f"### {section_title}")
            elif source_name:
                lines.append(f"### {source_name}")

            if source_name:
                lines.append(f"來源：{source_name}")

            if content:
                lines.append("```markdown")
                lines.append(content)
                lines.append("```")
            lines.append("")

        if len(lines) <= 2:
            return ""
        return "\n".join(lines).strip()

    def vector_search(self, query: str, top_k: Optional[int] = None, filter_doc: Optional[str] = None, filters: Optional[dict] = None) -> Dict:
        """
        向量搜尋模式 - 使用語意向量搜尋

        Args:
            query: 搜尋查詢
            top_k: 回傳結果數

        Returns:
            Dict: 搜尋結果與 LLM 生成答案
        """
        top_k = self._resolve_limit(top_k, self.default_basic_top_k)
        case_hints = self._extract_case_hints(query)
        if self._is_numeric_extraction_query(query):
            top_k = max(top_k, 20 if case_hints else 12)

        handover_result = self._build_handover_general_summary_result(query)
        if handover_result is not None:
            handover_result["mode"] = "vector"
            handover_result["query"] = query
            return handover_result

        try:
            from ..vector_store import get_vector_store

            # 使用注入的 vector_store 或取得新的
            vector_store = self.vector_store if self.vector_store is not None else get_vector_store()
            logger.info(f"vector_search 使用 vector_store: {vector_store is not None}, 類型: {type(vector_store).__name__}")

            # 語意搜尋
            results = vector_store.search(query, top_k=max(top_k * 3, top_k), filter_doc=filter_doc, filters=filters)
            logger.info(f"vector_search 原始結果: {len(results)} 筆")
            results = self._rank_vector_results(results, query, top_k)
            logger.info(f"vector_search 重排後結果: {len(results)} 筆")

            if not results:
                return {
                    "status": "success",
                    "mode": "vector",
                    "query": query,
                    "answer": f"在向量資料庫中找不到與「{query}」相似的內容。",
                    "sources": []
                }

            # 組合上下文
            context = "\n\n".join([
                f"文件:{r['doc_name']}\n內容:{r['content']}"
                for r in results
            ])

            # 提取來源文件
            sources = [
                _enrich_citation_source({
                    "source": r["doc_name"],
                    "content": r["content"],
                    "score": r["score"],
                    "chunk_index": r.get("chunk_index", 0),
                    "section_title": r.get("section_title", ""),
                    "source_path": r.get("source_path", ""),
                    "storage_category": r.get("storage_category", ""),
                    "extraction_mode": r.get("extraction_mode", ""),
                    **{key: r.get(key, "") for key in ("run_id", "environment", "project_code", "dut_model", "band", "protocol", "direction", "verdict", "started_at", "schema_version", "source_system", "environment_id", "project_id", "artifact_type", "report_schema", "document_id", "idempotency_key", "package_id", "document_version", "chunk_id", "publish_status", "is_current")},
                })
                for r in results
            ]

            if self._should_return_no_performance_section(query, sources):
                return {
                    "status": "success",
                    "mode": "vector",
                    "query": query,
                    "answer": self._build_no_performance_section_answer(sources),
                    "sources": sources,
                }

            # 生成答案
            answer = self._generate_answer_vector(query, context, results)

            return {
                "status": "success",
                "mode": "vector",
                "query": query,
                "answer": answer,
                "sources": sources
            }

        except Exception as e:
            logger.error(f"向量搜尋失敗: {e}")
            return {"status": "error", "message": str(e), "mode": "vector"}

    def hybrid_search(self, query: str, top_k: Optional[int] = None) -> Dict:
        """
        混合搜尋 - 同時使用向量搜尋和 Neo4j GraphRAG
        優化版：直接取 raw sources，不做中間 LLM 生成

        Args:
            query: 搜尋查詢
            top_k: 回傳結果數

        Returns:
            Dict: 結合兩種搜尋結果的回答
        """
        top_k = self._resolve_limit(top_k, self.default_basic_top_k)
        case_hints = self._extract_case_hints(query)
        if self._is_numeric_extraction_query(query):
            top_k = max(top_k, 20 if case_hints else 12)

        handover_result = self._build_handover_general_summary_result(query)
        if handover_result is not None:
            handover_result["mode"] = "hybrid"
            handover_result["query"] = query
            handover_result["keywords_used"] = self.extract_keywords(query)
            return handover_result

        # 先萃取關鍵字（LLM #1）
        keywords = self.extract_keywords(query)
        logger.info(f"Hybrid 關鍵字萃取: {keywords}")

        # 執行向量搜尋和圖譜搜尋（無 LLM 生成）
        vector_raw = self._vector_search_raw(query, top_k)
        graph_raw = self._deep_search_raw(query, mode="local", top_k=self.default_deep_top_k)

        # 組合所有來源(去重)
        all_sources = []
        seen_sources = set()  # 用於去重

        if vector_raw.get("sources"):
            for src in vector_raw["sources"]:
                src["mode"] = "vector"
                src_key = self._source_dedup_key(src)
                if src_key not in seen_sources:
                    seen_sources.add(src_key)
                    all_sources.append(_enrich_citation_source(src))

        if graph_raw.get("graph_results"):
            for src in graph_raw["graph_results"]:
                src_key = src.get("entity", "")
                if src_key not in seen_sources:
                    seen_sources.add(src_key)
                    all_sources.append({
                        "source": src_key,
                        "type": src.get("type", ""),
                        "content": src.get("description", ""),
                        "mode": "graph"
                    })

        if not all_sources:
            return {
                "status": "success",
                "mode": "hybrid",
                "query": query,
                "keywords_used": keywords,
                "answer": f"在知識庫中找不到與「{query}」相關的內容。",
                "sources": []
            }

        if self._should_return_no_performance_section(query, all_sources):
            return {
                "status": "success",
                "mode": "hybrid",
                "query": query,
                "keywords_used": keywords,
                "answer": self._build_no_performance_section_answer(all_sources),
                "sources": all_sources[:top_k],
            }

        # 組合上下文
        context_parts = []
        for src in all_sources[:top_k]:
            if src.get("mode") == "vector":
                context_parts.append(f"文件:{src['source']}\n內容:{src.get('content', '')}")
            else:
                context_parts.append(f"實體:{src['source']}\n描述:{src.get('content', '')}")

        context = "\n\n".join(context_parts)

        # LLM 生成混合答案（LLM #2，最終一次）
        answer = self._generate_hybrid_answer(query, context, all_sources, keywords)

        result = {
            "status": "success",
            "mode": "hybrid",
            "query": query,
            "keywords_used": keywords,
            "answer": answer,
            "sources": all_sources[:top_k]
        }
        
        return result


    def hybrid_plus_search(self, query: str, top_k: Optional[int] = None) -> Dict:
        """
        Hybrid Plus 搜尋 - Neo4j + QDrant + Cleaned 三合一
        等於是 Enhanced Hybrid：所有 RAG 來源全部查

        Args:
            query: 搜尋查詢
            top_k: 回傳結果數

        Returns:
            Dict: 結合三種搜尋結果的回答
        """
        top_k = self._resolve_limit(top_k, self.default_basic_top_k)

        logger.info(f"Hybrid Plus 搜尋: {query}")

        handover_result = self._build_handover_general_summary_result(query)
        if handover_result is not None:
            handover_result["mode"] = "hybrid_plus"
            handover_result["query"] = query
            handover_result["keywords_used"] = self.extract_keywords(query)
            return handover_result
        
        # 萃取關鍵字（LLM #1）
        keywords = self.extract_keywords(query)
        logger.info(f"Hybrid Plus 關鍵字萃取: {keywords}")

        # 執行三種搜尋
        vector_raw = self._vector_search_raw(query, top_k)
        graph_raw = self._deep_search_raw(query, mode="local", top_k=self.default_deep_top_k)
        cleaned_raw = self._cleaned_search_raw(query, top_k)

        # 組合所有來源（去重）
        all_sources = []
        seen_sources = set()

        # Vector sources
        if vector_raw.get("sources"):
            for src in vector_raw["sources"]:
                src["mode"] = "vector"
                src_key = self._source_dedup_key(src)
                if src_key not in seen_sources:
                    seen_sources.add(src_key)
                    all_sources.append(_enrich_citation_source(src))

        # Graph sources
        if graph_raw.get("graph_results"):
            for src in graph_raw["graph_results"]:
                src_key = src.get("entity", "")
                if src_key not in seen_sources:
                    seen_sources.add(src_key)
                    all_sources.append({
                        "source": src_key,
                        "type": src.get("type", ""),
                        "content": src.get("description", ""),
                        "mode": "graph"
                    })

        # Cleaned sources
        if cleaned_raw.get("sources"):
            for src in cleaned_raw["sources"]:
                src["mode"] = "cleaned"
                src_key = self._source_dedup_key(src)
                if src_key not in seen_sources:
                    seen_sources.add(src_key)
                    all_sources.append(_enrich_citation_source(src))

        if not all_sources:
            return {
                "status": "success",
                "mode": "hybrid_plus",
                "query": query,
                "keywords_used": keywords,
                "answer": f"在知識庫中找不到與「{query}」相關的內容。",
                "sources": []
            }

        if self._should_return_no_performance_section(query, all_sources):
            return {
                "status": "success",
                "mode": "hybrid_plus",
                "query": query,
                "keywords_used": keywords,
                "answer": self._build_no_performance_section_answer(all_sources),
                "sources": all_sources[:top_k],
            }

        # 組合上下文
        context_parts = []
        for src in all_sources[:top_k]:
            mode = src.get("mode", "")
            if mode == "vector":
                line = "[Vector] 文件:" + src.get("source", "") + "\n內容:" + src.get("content", "")
            elif mode == "graph":
                line = "[Graph] 實體:" + src.get("source", "") + "\n描述:" + src.get("content", "")
            elif mode == "cleaned":
                line = "[Cleaned] 文件:" + src.get("source", "") + "\n摘要:" + src.get("content", "")
            else:
                line = "來源:" + src.get("source", "") + "\n內容:" + src.get("content", "")
            context_parts.append(line)

        context = "\n\n".join(context_parts)

        # LLM 生成答案（LLM #2，最終一次）
        answer = self._generate_hybrid_answer(query, context, all_sources, keywords)

        result = {
            "status": "success",
            "mode": "hybrid_plus",
            "query": query,
            "keywords_used": keywords,
            "answer": answer,
            "sources": all_sources[:top_k]
        }
        
        return result

    def _cleaned_search_raw(self, query: str, top_k: Optional[int] = None) -> Dict:
        """
        搜尋 Cleaned 資料夾（Dual RAG Source）
        
        Args:
            query: 搜尋查詢
            top_k: 回傳結果數

        Returns:
            Dict: 包含 sources 的原始結果
        """
        top_k = self._resolve_limit(top_k, self.default_basic_top_k)

        logger.info(f"搜尋 Cleaned 資料夾: {query}")
        
        cleaned_folder = Path("/home/da40_ai_gb10/knowledge-base/data/cleaned")
        
        if not cleaned_folder.exists():
            logger.info(f"Cleaned 資料夾不存在: {cleaned_folder}")
            return {"sources": [], "mode": "cleaned"}

        # 萃取關鍵字用於比對
        keywords = self.extract_keywords(query)
        
        results = []
        
        # 掃描所有 JSON 檔案
        for json_file in cleaned_folder.rglob("*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                doc_name = data.get("doc_name", json_file.stem)
                
                # 檢查是否符合關鍵字
                content_for_search = json.dumps(data, ensure_ascii=False)
                
                # 簡單關鍵字比對
                matched = False
                for kw in keywords:
                    if kw.lower() in doc_name.lower() or kw.lower() in content_for_search.lower():
                        matched = True
                        break
                
                # 如果有匹配或沒有關鍵字（則全部返回）
                if matched or not keywords:
                    # 取得主要內容（摘要）
                    content = data.get("llm_summary", "") or data.get("content", "")
                    if not content and data.get("key_facts"):
                        content = "、".join(data.get("key_facts", []))
                    if not content:
                        content = json.dumps(data, ensure_ascii=False)[:500]
                    
                    results.append(_enrich_citation_source({
                        "source": doc_name,
                        "doc_name": doc_name,
                        "content": content,
                        "doc_type": data.get("doc_type", "unknown"),
                        "version": data.get("version", ""),
                        "mode": "cleaned"
                    }))
                    
            except Exception as e:
                logger.warning(f"讀取 Cleaned 檔案失敗: {json_file}, {e}")
                continue

        logger.info(f"Cleaned 搜尋結果: {len(results)} 筆")
        
        return {
            "sources": results[:top_k],
            "mode": "cleaned"
        }


    def _vector_search_raw(self, query: str, top_k: Optional[int] = None, filters: Optional[dict] = None) -> Dict:
        """
        向量搜尋 - 純資料取得，不生成答案（供 Hybrid 模式使用）

        Args:
            query: 搜尋查詢
            top_k: 回傳結果數

        Returns:
            Dict: 只包含 sources，不包含 answer
        """
        top_k = self._resolve_limit(top_k, self.default_basic_top_k)
        case_hints = self._extract_case_hints(query)
        if self._is_numeric_extraction_query(query):
            top_k = max(top_k, 20 if case_hints else 12)

        try:
            from ..vector_store import get_vector_store
            vector_store = self.vector_store if self.vector_store is not None else get_vector_store()

            results = vector_store.search(query, top_k=max(top_k * 3, top_k), filters=filters)
            logger.info(f"_vector_search_raw 原始結果: {len(results)} 筆")
            results = self._rank_vector_results(results, query, top_k)
            logger.info(f"_vector_search_raw 重排後結果: {len(results)} 筆")

            if not results:
                return {"status": "success", "mode": "vector", "sources": []}

            sources = [
                _enrich_citation_source({
                    "source": r["doc_name"],
                    "content": r["content"],
                    "score": r["score"],
                    "chunk_index": r.get("chunk_index", 0),
                    "section_title": r.get("section_title", ""),
                    "source_path": r.get("source_path", ""),
                    **{key: r.get(key, "") for key in ("run_id", "environment", "project_code", "dut_model", "band", "protocol", "direction", "verdict", "started_at", "schema_version", "source_system", "environment_id", "project_id", "artifact_type", "report_schema", "document_id", "idempotency_key", "package_id", "document_version", "chunk_id", "publish_status", "is_current")},
                })
                for r in results
            ]
            return {"status": "success", "mode": "vector", "sources": sources}

        except Exception as e:
            logger.error(f"_vector_search_raw 失敗: {e}")
            return {"status": "error", "sources": []}

    def _deep_search_raw(self, query: str, mode: str = "local", top_k: Optional[int] = None) -> Dict:
        """
        圖譜搜尋 - 純資料取得，不生成答案（供 Hybrid 模式使用）

        Args:
            query: 搜尋查詢
            mode: local/global
            top_k: 回傳結果數

        Returns:
            Dict: 只包含 graph_results，不包含 answer
        """
        top_k = self._resolve_limit(top_k, self.default_deep_top_k)

        # 意圖分類
        intent, confidence = self.classify_intent(query)
        logger.info(f"_deep_search_raw 意圖分類: {intent} (信心度: {confidence:.2f})")

        # 萃取關鍵字
        keywords = self.extract_keywords(query)

        # 同義詞擴展
        expanded_keywords = self.expand_synonyms(keywords)

        # Entity Type 感知
        target_types = self.get_entity_types_for_intent(intent)
        type_condition = " OR ".join([f"e.type = '{t}'" for t in target_types])

        driver = self._get_neo4j_driver()
        if driver is None:
            return {"status": "error", "graph_results": []}

        try:
            with driver.session() as session:
                if mode == "local":
                    keyword_conditions = " OR ".join([
                        f"(e.name CONTAINS '{kw}' OR e.description CONTAINS '{kw}')"
                        for kw in expanded_keywords
                    ])
                    type_clause = f"AND ({type_condition})" if type_condition else ""

                    cypher = f"""
                        MATCH (e:Entity)
                        WHERE {keyword_conditions} {type_clause}
                        WITH e LIMIT $limit
                        OPTIONAL MATCH (e)-[r]-(related)
                        RETURN e.name as entity, e.type as type,
                               e.description as description,
                               collect(DISTINCT related.name) as connections
                        LIMIT $limit
                    """

                    result = session.run(cypher, limit=top_k)
                    graph_data = [dict(record) for record in result]

                    # 語意相似度過濾
                    graph_data = self.filter_by_similarity(graph_data, threshold=0.3)

                    return {
                        "status": "success",
                        "mode": "deep",
                        "graph_results": graph_data
                    }
                else:
                    keyword_conditions = " OR ".join([
                        f"(d.content CONTAINS '{kw}' OR d.name CONTAINS '{kw}')"
                        for kw in expanded_keywords
                    ])

                    cypher = f"""
                        MATCH (d:Document)
                        WHERE {keyword_conditions}
                        RETURN d.name as name, d.content as content
                        LIMIT $limit
                    """

                    result = session.run(cypher, limit=top_k)
                    docs = [dict(record) for record in result]
                    docs = self.filter_by_similarity(docs, threshold=0.3)

                    return {
                        "status": "success",
                        "mode": "deep",
                        "graph_results": [{"entity": d["name"], "type": "Document", "description": d["content"][:200]} for d in docs]
                    }

        except Exception as e:
            logger.error(f"_deep_search_raw 失敗: {e}")
            return {"status": "error", "graph_results": []}


    def _generate_answer_vector(self, query: str, context: str, results: List) -> str:
        """使用 LLM 根據向量搜尋結果生成答案"""
        if self.llm_client is None:
            return f"根據向量搜尋結果,關於「{query}」的回答:\n\n{context[:500]}..."

        try:
            numeric_mode = self._is_numeric_extraction_query(query)
            if numeric_mode:
                direct_answer = self._build_numeric_direct_answer(query, results)
                if direct_answer:
                    return self._compose_raw_then_interpretation(query, direct_answer, results)
                results = self._merge_numeric_case_sources_for_output(query, results)
                context = "\n\n".join([
                    f"文件:{r['doc_name']}\n內容:{r['content']}"
                    for r in results
                ]) or context

            # 組合來源清單
            source_list = []
            for r in results:
                extra_bits = []
                if r.get("section_title"):
                    extra_bits.append(r["section_title"])
                if r.get("chunk_index") is not None:
                    extra_bits.append(f"chunk {r.get('chunk_index')}")
                extra = f" [{' / '.join(extra_bits)}]" if extra_bits else ""
                source_list.append(f"- {r['doc_name']}{extra} (相似度: {r['score']:.3f})")
            source_str = "\n".join(source_list)

            numeric_rules = ""
            if numeric_mode:
                numeric_rules = """
數值抽取模式（必須嚴格遵守）：
- 這是一題逐 case / 逐 row 抽取題，請直接轉寫本次 sources 中的 case table。
- 只准輸出本次 sources 內明確存在的 case、row、column 與數字，不可做跨 case 合併。
- 如果來源同時包含 `Test Result Summary` 與 `Performance Test`，且問題是 `Performance Test` / throughput / latency / BLER / RTT 類型，請只使用 `Performance Test` 章節的逐 case 數據；`Test Result Summary` 只能當作索引或補充，不得拿來對應 case 13~16 的詳細數值。
- 若查詢明確在詢問 `Performance Test` / throughput / latency / BLER / RTT / case / test case 等性能數據，且來源是 Handover 報告而沒有 `Performance Test` 章節，請直接回答「這份 Handover 報告沒有 Performance Test 章節，因此無對應章節可回覆。」不得自行補數據或改答其他章節。
- 若只是一般報告資訊、摘要或其他章節內容，請正常整理可用資料，不要僅因為沒有 `Performance Test` 就直接拒答。
- 不要自行整理成「最佳值 / Peak / 濃縮版 / 趨勢摘要」來替代原始表格。
- 若來源文件已有 Summary 段落，必須明確標註為「來源摘要」，不可把它當成其他 case 的數據來源。
- 不要借用其他報告、先前對話或記憶中的任何數字。
- 若同一份報告有多個 case，請優先完整列出；若篇幅較長，也不能刪改數字或改寫數值。
"""

            prompt = f"""根據以下搜尋結果回答問題。

規則：
- 只有在完全沒有相關來源時，才可以說「無法從提供的結果回答這個問題」。
- 只要有找到相關來源，就不能說「沒有資料」或「查無資料」。
- 若來源片段不足以重建完整數據，請明確說明「已找到相關文件，但片段不足以重建完整答案」。
- 只能使用本次提供的 sources / context 內的資訊回答；不得引用其他文件、先前對話、記憶中的數字，或從別份報告借用數值。
- 若 sources 內沒有明確出現某個數字、表格列、最大值或結論，就不能自行補值或推測。
- 若同一題有多份來源，優先只使用與問題文件代號最一致的來源，不要混用其他報告的數值。
- 若查詢明確在詢問 `Performance Test` / throughput / latency / BLER / RTT / case / test case 等性能數據，且來源是 Handover 報告而沒有 `Performance Test` 章節，請直接回答「這份 Handover 報告沒有 Performance Test 章節，因此無對應章節可回覆。」不得自行補數據或改答其他章節。
- 若只是一般報告資訊、摘要或其他章節內容，請正常整理可用資料，不要僅因為沒有 `Performance Test` 就直接拒答。
{numeric_rules}

語意向量搜尋結果:
{source_str}

內容:
{context}

問題:{query}

【重要】如果回答中包含 JSON 資料,請使用美化的格式(indent=2, 多行顯示),不要放在同一行。

請根據以上內容回答,並在答案結尾標注相關的檔案來源和相似度分數。"""

            response = self.llm_client.chat([
                {"role": "user", "content": prompt}
            ], temperature=0.3)
            response = response.strip()
            if numeric_mode:
                response = self._sanitize_numeric_response(response)
            return response

        except Exception as e:
            logger.error(f"LLM 生成答案失敗: {e}")
            return f"生成答案時發生錯誤: {e}"

    def _generate_hybrid_answer(self, query: str, context: str, sources: List, keywords: List) -> str:
        """使用 LLM 根據混合搜尋結果生成答案"""
        if self.llm_client is None:
            return f"根據混合搜尋結果,關於「{query}」的回答:\n\n{context[:500]}..."

        try:
            numeric_mode = self._is_numeric_extraction_query(query)
            if numeric_mode:
                direct_answer = self._build_numeric_direct_answer(query, sources)
                if direct_answer:
                    return self._compose_raw_then_interpretation(query, direct_answer, sources)
                sources = self._merge_numeric_case_sources_for_output(query, sources)
                context = "\n\n".join([
                    f"文件:{src['source']}\n內容:{src.get('content', '')}"
                    for src in sources
                ]) or context

            # 組合來源清單
            source_list = []
            for src in sources[:5]:
                mode = src.get("mode", "unknown")
                extra_bits = []
                if src.get("section_title"):
                    extra_bits.append(src["section_title"])
                if src.get("chunk_index") is not None:
                    extra_bits.append(f"chunk {src.get('chunk_index')}")
                extra = f" [{' / '.join(extra_bits)}]" if extra_bits else ""
                if mode == "vector":
                    source_list.append(f"- {src['source']}{extra} (向量搜尋, 相似度: {src.get('score', 0):.3f})")
                elif mode == "graph":
                    source_list.append(f"- {src['source']}{extra} (知識圖譜)")
                else:
                    source_list.append(f"- {src['source']}{extra}")

            source_str = "\n".join(source_list)
            numeric_rules = ""
            if numeric_mode:
                numeric_rules = """
數值抽取模式（必須嚴格遵守）：
- 這是一題逐 case / 逐 row 抽取題，請直接轉寫本次 sources 中的 case table。
- 只准輸出本次 sources 內明確存在的 case、row、column 與數字，不可做跨 case 合併。
- 如果來源同時包含 `Test Result Summary` 與 `Performance Test`，且問題是 `Performance Test` / throughput / latency / BLER / RTT 類型，請只使用 `Performance Test` 章節的逐 case 數據；`Test Result Summary` 只能當作索引或補充，不得拿來對應 case 13~16 的詳細數值。
- 若查詢明確在詢問 `Performance Test` / throughput / latency / BLER / RTT / case / test case 等性能數據，且來源是 Handover 報告而沒有 `Performance Test` 章節，請直接回答「這份 Handover 報告沒有 Performance Test 章節，因此無對應章節可回覆。」不得自行補數據或改答其他章節。
- 若只是一般報告資訊、摘要或其他章節內容，請正常整理可用資料，不要僅因為沒有 `Performance Test` 就直接拒答。
- 不要自行整理成「最佳值 / Peak / 濃縮版 / 趨勢摘要」來替代原始表格。
- 若來源文件已有 Summary 段落，必須明確標註為「來源摘要」，不可把它當成其他 case 的數據來源。
- 不要借用其他報告、先前對話或記憶中的任何數字。
- 若同一份報告有多個 case，請優先完整列出；若篇幅較長，也不能刪改數字或改寫數值。
"""
            
            prompt = f"""你是一個專業的知識庫助理。請根據以下混合搜尋結果回答問題。

規則：
- 只有在完全沒有相關來源時，才可以說「無法回答」。
- 只要有找到相關來源，就不能說「沒有資料」或「查無資料」。
- 若來源片段不足以重建完整數據，請明確說明「已找到相關文件，但片段不足以重建完整答案」。
- 只能使用本次提供的 sources / context 內的資訊回答；不得引用其他文件、先前對話、記憶中的數字，或從別份報告借用數值。
- 若 sources 內沒有明確出現某個數字、表格列、最大值或結論，就不能自行補值或推測。
- 若同一題有多份來源，優先只使用與問題文件代號最一致的來源，不要混用其他報告的數值。
- 若查詢明確在詢問 `Performance Test` / throughput / latency / BLER / RTT / case / test case 等性能數據，且來源是 Handover 報告而沒有 `Performance Test` 章節，請直接回答「這份 Handover 報告沒有 Performance Test 章節，因此無對應章節可回覆。」不得自行補數據或改答其他章節。
- 若只是一般報告資訊、摘要或其他章節內容，請正常整理可用資料，不要僅因為沒有 `Performance Test` 就直接拒答。
{numeric_rules}

關鍵字:{keywords}

參考來源:
{source_str}

上下文:
{context}

問題:{query}

請結合知識庫資料、向量搜尋(語義相似)和知識圖譜(實體關係)給出全面的回答。如果無法回答,請說「無法回答」。

【重要】如果回答中包含 JSON 資料,請使用美化的格式(indent=2, 多行顯示),不要放在同一行。

在答案結尾,請標注所有參考的來源。"""

            response = self.llm_client.chat([
                {"role": "user", "content": prompt}
            ], temperature=0.3)
            response = response.strip()
            if numeric_mode:
                response = self._sanitize_numeric_response(response)
            return response

        except Exception as e:
            logger.error(f"LLM 生成答案失敗: {e}")
            return f"生成答案時發生錯誤: {e}"
    # ===== Dynamic Mode Selection =====
    def classify_query_intent(self, query: str) -> str:
        """
        分類查詢意圖（不需要 LLM，規則匹配）
        
        Returns:
            str: intent type
        """
        query_lower = query.lower()
        
        # 比較意圖
        if any(kw in query for kw in ["比較", "差異", "不同", "vs", "versus"]):
            return "compare"
        
        # 設備查詢
        if any(kw in query for kw in ["設備", "基站", "型號", "規格", "哪個"]):
            return "device"
        
        # 狀態/問題查詢
        if any(kw in query for kw in ["錯誤", "故障", "異常", "問題", "狀態"]):
            return "status"
        
        # 位置查詢
        if any(kw in query for kw in ["在哪", "位置", "地址", "位於"]):
            return "location"
        
        # 數量查詢
        if any(kw in query for kw in ["多少", "數量", "幾個", "總共"]):
            return "count"
        
        # 人員查詢
        if any(kw in query for kw in ["誰", "負責", "管理", "人"]):
            return "person"
        
        # 原因查詢
        if any(kw in query for kw in ["為什麼", "原因", "為何", "因為"]):
            return "cause"
        
        # 方法查詢
        if any(kw in query for kw in ["怎麼", "如何", "方法", "解決", "處理"]):
            return "method"
        
        # 列表查詢
        if any(kw in query for kw in ["哪些", "有什麼", "列舉", "列出"]):
            return "list"
        
        return "general"
    
    def detect_entity_types(self, query: str) -> list:
        """
        偵測查詢需要的實體類型
        """
        entity_map = {
            "error": ["錯誤碼", "ErrorCode"],
            "device": ["設備名稱", "DeviceName", "設備型號"],
            "location": ["位置", "Location"],
            "version": ["軟體版本", "SoftwareVersion"],
            "frequency": ["頻段", "FrequencyBand"],
            "modulation": ["調變方式", "Modulation"],
            "rate": ["傳輸速率", "TransmissionRate"],
            "person": ["管理員", "Borrower", "PM"],
            "project": ["專案", "ProjectName"],
        }
        
        detected = []
        query_lower = query.lower()
        
        for kw, types in entity_map.items():
            if kw in query_lower:
                detected.extend(types)
        
        return list(set(detected))
    
    def assess_complexity(self, query: str) -> str:
        """
        評估查詢複雜度
        """
        length = len(query)
        
        # 短且簡單
        if length < 15 and not any(kw in query for kw in ["分析", "比較", "哪些", "如何"]):
            return "low"
        
        # 長或包含複雜關鍵字
        if length > 50 or any(kw in query for kw in ["分析", "解釋", "說明", "比較", "評估"]):
            return "high"
        
        return "medium"
    
    def needs_graph_reasoning(self, query: str, intent: str, complexity: str) -> bool:
        """
        判斷是否需要圖譜推理
        """
        # 明確需要推理的意圖
        if intent in ["compare", "cause", "method"]:
            return True
        
        # 複雜查詢需要推理
        if complexity == "high":
            return True
        
        # 包含推理關鍵字
        推理_keywords = ["關係", "原因", "為什麼", "如何導致", "因果", "推論"]
        if any(kw in query for kw in 推理_keywords):
            return True
        
        return False
    
    def select_best_mode(self, query: str) -> str:
        """
        動態選擇最佳搜尋模式（只對 auto 模式生效）
        
        分析維度：
        1. 查詢意圖 (Intent)
        2. 實體類型需求
        3. 複雜度
        4. 是否需要圖譜推理
        
        Returns:
            str: 最佳模式 (basic/deep/vector/hybrid)
        """
        # 分析查詢特性
        intent = self.classify_query_intent(query)
        entity_types = self.detect_entity_types(query)
        complexity = self.assess_complexity(query)
        needs_reasoning = self.needs_graph_reasoning(query, intent, complexity)
        
        logger.info(f"Dynamic Mode Selection: intent={intent}, complexity={complexity}, needs_reasoning={needs_reasoning}, entities={entity_types}")
        
        # ===== 決策邏輯 =====
        
        # 1. 需要推理 → deep
        if needs_reasoning:
            return "deep"
        
        # 2. 比較意圖 → deep（需要圖譜比對）
        if intent == "compare":
            return "deep"
        
        # 3. 原因查詢 → deep
        if intent == "cause":
            return "deep"
        
        # 4. 混合意圖（多實體類型）→ hybrid
        if len(entity_types) >= 2:
            return "hybrid"
        
        # 5. 高複雜度 → hybrid
        if complexity == "high":
            return "hybrid"
        
        # 6. 簡單查詢 → basic
        if complexity == "low" and intent in ["general", "location", "count"]:
            return "basic"
        
        # 7. 列表查詢 → vector
        if intent == "list":
            return "vector"
        
        # 8. 設備/狀態查詢 → vector（這些不需要複雜推理）
        if intent in ["device", "status"]:
            return "vector"
        
        # 預設
        return "basic"
    
    def search(self, query: str, mode: str = "auto", top_k: Optional[int] = None, filters: Optional[dict] = None) -> Dict:
        """
        統一搜尋介面

        Args:
            query: 搜尋查詢
            mode: "basic"(基本RAG)/ "deep"(GraphRAG)/ "vector"(向量搜尋)/ "hybrid"(混合)/ "auto"(自動選擇)
            top_k: 回傳結果數

        Returns:
            Dict: 搜尋結果
        """
        if filters:
            return self.vector_search(query, top_k=top_k, filters=filters)
        if mode == "auto":
            # 使用 Dynamic Mode Selection 選擇最佳模式
            mode = self.select_best_mode(query)
            logger.info(f"Auto mode selected: {mode}")

        query_intent = self.classify_query_intent(query)
        document_profiles = self._find_document_profiles_for_query(query, limit=6)
        wifi_profiles = [
            profile for profile in document_profiles
            if self._document_storage_category(profile) == "WiFi"
        ]
        wifi_metas = [self._profile_to_wifi_meta(profile) for profile in wifi_profiles]
        if query_intent == "compare" and len(wifi_metas) < 2:
            wifi_fallback_metas = self._find_wifi_document_metadatas_for_query(query, limit=4)
            wifi_metas = self._merge_wifi_metadata_candidates(wifi_metas, wifi_fallback_metas)
        wifi_meta = wifi_metas[0] if wifi_metas else None
        wifi_specific_hints = self._extract_document_name_hints(query)
        if query_intent == "compare":
            if len(wifi_metas) >= 2:
                wifi_compare_result = self._build_wifi_throughput_compare_answer(query, wifi_metas)
                if wifi_compare_result is not None:
                    logger.info(
                        "WiFi compare query matched documents %s; returning WiFi compare results",
                        ", ".join(
                            str(meta.get("doc_name") or meta.get("source_name") or "WiFi 文件").strip()
                            for meta in wifi_metas[:2]
                        ),
                    )
                    return self._prepend_raw_evidence_if_missing(query, wifi_compare_result)
            elif wifi_specific_hints and wifi_metas:
                matched_wifi_docs = {
                    self._compact_alnum(str(meta.get("doc_name") or meta.get("source_name") or ""))
                    for meta in wifi_metas
                }
                matched_wifi_docs.discard("")
                missing_hints = [
                    hint for hint in wifi_specific_hints
                    if self._compact_alnum(hint) not in matched_wifi_docs
                ]
                if missing_hints:
                    answer_lines = ["## 原文", "未找到足夠的 WiFi 文件可進行比較。", "", "## 解讀"]
                    if wifi_metas:
                        answer_lines.append(
                            "- 目前只找到：" + "、".join(
                                str(meta.get("source_name") or meta.get("doc_name") or "WiFi 文件").strip()
                                for meta in wifi_metas[:2]
                            )
                        )
                    answer_lines.append("- 未命中的查詢文件：" + "、".join(missing_hints))
                    return self._prepend_raw_evidence_if_missing(query, {
                        "status": "success",
                        "mode": "wifi_compare",
                        "query": query,
                        "answer": "\n".join(answer_lines).strip(),
                        "sources": [self._build_wifi_metadata_source(meta) for meta in wifi_metas[:2]],
                    })

        if wifi_meta is not None:
            wifi_doc_name = str(wifi_meta.get("doc_name") or "").strip()
            if wifi_doc_name:
                wifi_band_result = self._build_wifi_throughput_band_answer(query, wifi_meta)
                if wifi_band_result is not None and wifi_band_result.get("answer"):
                    logger.info(
                        "WiFi throughput band query matched document %s; returning raw band sections",
                        wifi_doc_name,
                    )
                    return self._prepend_raw_evidence_if_missing(query, wifi_band_result)

                wifi_result = self.vector_search(query, top_k=top_k, filter_doc=wifi_doc_name)
                if wifi_result.get("status") == "success" and wifi_result.get("sources"):
                    logger.info(
                        "WiFi-specific query matched document %s; returning vector results before report graph",
                        wifi_doc_name,
                    )
                    return self._prepend_raw_evidence_if_missing(query, wifi_result)

        if document_profiles:
            primary_profile = document_profiles[0]
            primary_doc_name = str(primary_profile.get("doc_name") or "").strip()
            primary_category = self._document_storage_category(primary_profile)
            if primary_doc_name and primary_category != "Report":
                filtered_result = self.vector_search(query, top_k=top_k, filter_doc=primary_doc_name)
                if filtered_result.get("status") == "success" and filtered_result.get("sources"):
                    logger.info(
                        "Document profile matched %s (%s); returning filtered vector results",
                        primary_doc_name,
                        primary_category or "unknown",
                    )
                    return self._prepend_raw_evidence_if_missing(query, filtered_result)

        if self._is_report_like_query(query):
            report_result = self._report_graph_search_raw(query, top_k=top_k)
            if report_result.get("status") == "success" and report_result.get("sources"):
                logger.info("Report graph search hit; returning report graph results")
                return self._prepend_raw_evidence_if_missing(query, report_result)

            if not self._is_report_performance_data_query(query):
                handover_meta = self._find_handover_report_metadata_for_general_query(query)
                if handover_meta is not None:
                    general_handover_result = self._build_handover_general_summary_answer(query, handover_meta)
                    if general_handover_result:
                        logger.info("General Handover summary path hit; returning converted md summary")
                        return self._prepend_raw_evidence_if_missing(query, general_handover_result)

        if mode == "basic":
            return self._prepend_raw_evidence_if_missing(query, self.basic_search(query, top_k=top_k))
        elif mode == "deep":
            return self._prepend_raw_evidence_if_missing(query, self.deep_search(query, mode="local", top_k=top_k))
        elif mode == "vector":
            return self._prepend_raw_evidence_if_missing(query, self.vector_search(query, top_k=top_k))
        elif mode == "hybrid":
            return self._prepend_raw_evidence_if_missing(query, self.hybrid_search(query, top_k=top_k))
        elif mode == "hybrid_plus":
            return self._prepend_raw_evidence_if_missing(query, self.hybrid_plus_search(query, top_k=top_k))
        else:
            return {"status": "error", "message": f"未知模式: {mode}"}
