"""
日誌系統優化模組

提供完整的 Q&A 操作日誌追蹤、分析、統計功能
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LogCategory(Enum):
    """日誌類別"""
    QA_CREATED = "qa_created"           # Q&A 新增
    QA_USED = "qa_used"                 # Q&A 被使用
    QA_UPDATED = "qa_updated"           # Q&A 更新
    QA_DELETED = "qa_deleted"           # Q&A 刪除
    CONFLICT_DETECTED = "conflict_detected"  # 衝突偵測
    CONFLICT_RESOLVED = "conflict_resolved"  # 衝突解決
    SEARCH_PERFORMED = "search_performed"    # 搜尋查詢
    SYSTEM_ERROR = "system_error"            # 系統錯誤


class LogLevel(Enum):
    """日誌等級"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class LogEntry:
    """日誌條目"""
    timestamp: str
    category: str
    level: str
    qa_id: str
    detail: str
    extra_data: Dict

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_markdown(self) -> str:
        return f"## [{self.timestamp}] {self.category} | {self.qa_id}\n- **Level**: {self.level}\n- **Detail**: {self.detail}\n"


class QALogger:
    """
    Q&A 日誌管理器（優化版）
    
    功能：
    - Markdown 日誌（人類可讀）
    - JSON 日誌（機器可讀）
    - 統計分析
    - 每日摘要
    """

    def __init__(self, logs_folder: str = "/home/da40_ai_gb10/knowledge-base/data/cleaned/logs"):
        self.logs_folder = Path(logs_folder)
        self.logs_folder.mkdir(parents=True, exist_ok=True)
        
        # Markdown 日誌檔案
        self.markdown_log = self.logs_folder / f"log_{datetime.now().strftime('%Y-%m')}.md"
        
        # JSON 日誌檔案（用於分析）
        self.json_log = self.logs_folder / f"log_{datetime.now().strftime('%Y-%m')}.json"
        
        # 初始化日誌檔案
        self._init_log_files()
    
    def _init_log_files(self):
        """初始化日誌檔案"""
        # 初始化 Markdown 如果不存在
        if not self.markdown_log.exists():
            with open(self.markdown_log, 'w', encoding='utf-8') as f:
                f.write(f"# Q&A 操作日誌\n\n")
                f.write(f"## {datetime.now().strftime('%Y-%m')} 月度日誌\n\n")
        
        # 初始化 JSON 如果不存在
        if not self.json_log.exists():
            with open(self.json_log, 'w', encoding='utf-8') as f:
                json.dump([], f)
    
    def log(
        self,
        category: LogCategory,
        qa_id: str,
        detail: str,
        level: LogLevel = LogLevel.INFO,
        extra_data: Dict = None
    ) -> LogEntry:
        """
        記錄一筆日誌
        
        Args:
            category: 日誌類別
            qa_id: Q&A ID
            detail: 詳細說明
            level: 日誌等級
            extra_data: 額外資料
        
        Returns:
            LogEntry: 日誌條目
        """
        entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            category=category.value,
            level=level.value,
            qa_id=qa_id,
            detail=detail,
            extra_data=extra_data or {}
        )
        
        # 寫入 Markdown
        self._write_markdown(entry)
        
        # 寫入 JSON
        self._write_json(entry)
        
        logger.info(f"日誌記錄: [{category.value}] {qa_id} - {detail}")
        
        return entry
    
    def _write_markdown(self, entry: LogEntry):
        """寫入 Markdown 日誌"""
        with open(self.markdown_log, 'a', encoding='utf-8') as f:
            f.write(entry.to_markdown())
            if entry.extra_data:
                f.write(f"- **Extra**: {json.dumps(entry.extra_data, ensure_ascii=False)}\n")
            f.write("\n")
    
    def _write_json(self, entry: LogEntry):
        """寫入 JSON 日誌"""
        try:
            with open(self.json_log, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            logs = []
        
        logs.append(entry.to_dict())
        
        with open(self.json_log, 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
    
    def log_qa_created(self, qa_id: str, question: str, sources: List[str] = None):
        """記錄 Q&A 新增"""
        return self.log(
            LogCategory.QA_CREATED,
            qa_id,
            f"新增 Q&A: {question[:50]}...",
            level=LogLevel.INFO,
            extra_data={"question": question, "sources": sources or []}
        )
    
    def log_qa_used(self, qa_id: str, similarity: float, time_saved: float = 0):
        """
        記錄 Q&A 被使用
        
        Args:
            qa_id: Q&A ID
            similarity: 相似度
            time_saved: 估計節省的時間（秒）
        """
        return self.log(
            LogCategory.QA_USED,
            qa_id,
            f"使用 Q&A，相似度 {similarity:.2f}，節省約 {time_saved:.1f}秒",
            level=LogLevel.INFO,
            extra_data={"similarity": similarity, "time_saved": time_saved}
        )
    
    def log_conflict(self, qa_id: str, conflict_with: str, conflict_type: str):
        """記錄衝突"""
        return self.log(
            LogCategory.CONFLICT_DETECTED,
            qa_id,
            f"發現衝突 vs {conflict_with}, 類型: {conflict_type}",
            level=LogLevel.WARNING,
            extra_data={"conflict_with": conflict_with, "conflict_type": conflict_type}
        )
    
    def log_search(self, query: str, found_qa_id: str, cache_hit: bool):
        """記錄搜尋查詢"""
        return self.log(
            LogCategory.SEARCH_PERFORMED,
            found_qa_id or "none",
            f"搜尋: {query[:50]}... -> {'命中' if cache_hit else '未命中'}",
            level=LogLevel.INFO,
            extra_data={"query": query, "cache_hit": cache_hit}
        )
    
    def get_daily_summary(self, date: datetime = None) -> Dict:
        """
        取得每日摘要
        
        Args:
            date: 日期，預設今天
        
        Returns:
            Dict: 每日統計摘要
        """
        if date is None:
            date = datetime.now()
        
        target_date = date.strftime("%Y-%m-%d")
        
        try:
            with open(self.json_log, 'r', encoding='utf-8') as f:
                all_logs = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
        
        # 篩選當日日誌
        daily_logs = [
            log for log in all_logs
            if log.get('timestamp', '').startswith(target_date)
        ]
        
        # 統計
        stats = {
            "date": target_date,
            "total_operations": len(daily_logs),
            "qa_created": sum(1 for log in daily_logs if log['category'] == 'qa_created'),
            "qa_used": sum(1 for log in daily_logs if log['category'] == 'qa_used'),
            "conflicts_detected": sum(1 for log in daily_logs if log['category'] == 'conflict_detected'),
            "searches": sum(1 for log in daily_logs if log['category'] == 'search_performed'),
            "cache_hits": sum(1 for log in daily_logs if log.get('extra_data', {}).get('cache_hit', False)),
            "errors": sum(1 for log in daily_logs if log['level'] == 'ERROR')
        }
        
        # 計算命中率
        if stats['searches'] > 0:
            stats['cache_hit_rate'] = f"{stats['cache_hits'] / stats['searches'] * 100:.1f}%"
        else:
            stats['cache_hit_rate'] = "0%"
        
        return stats
    
    def get_weekly_report(self) -> Dict:
        """取得每週報告"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        weekly_stats = {
            "period": f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}",
            "daily_stats": [],
            "total_qa_created": 0,
            "total_qa_used": 0,
            "total_cache_hits": 0,
            "total_conflicts": 0
        }
        
        # 收集每日統計
        for i in range(7):
            date = end_date - timedelta(days=i)
            daily = self.get_daily_summary(date)
            if daily:
                weekly_stats['daily_stats'].append(daily)
                weekly_stats['total_qa_created'] += daily.get('qa_created', 0)
                weekly_stats['total_qa_used'] += daily.get('qa_used', 0)
                weekly_stats['total_cache_hits'] += daily.get('cache_hits', 0)
                weekly_stats['total_conflicts'] += daily.get('conflicts_detected', 0)
        
        # 計算總命中率
        total_searches = sum(d.get('searches', 0) for d in weekly_stats['daily_stats'])
        if total_searches > 0:
            weekly_stats['cache_hit_rate'] = f"{weekly_stats['total_cache_hits'] / total_searches * 100:.1f}%"
        else:
            weekly_stats['cache_hit_rate'] = "0%"
        
        return weekly_stats
    
    def get_top_qa(self, limit: int = 10) -> List[Dict]:
        """取得最熱門 Q&A"""
        try:
            with open(self.json_log, 'r', encoding='utf-8') as f:
                all_logs = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []
        
        # 統計每個 Q&A 的使用次數
        usage_count = {}
        for log in all_logs:
            if log['category'] == 'qa_used':
                qa_id = log['qa_id']
                usage_count[qa_id] = usage_count.get(qa_id, 0) + 1
        
        # 排序
        sorted_qa = sorted(usage_count.items(), key=lambda x: x[1], reverse=True)
        
        return [
            {"qa_id": qa_id, "usage_count": count}
            for qa_id, count in sorted_qa[:limit]
        ]
    
    def export_markdown_report(self, output_path: str = None) -> str:
        """
        匯出 Markdown 報告
        
        Returns:
            str: 報告內容
        """
        if output_path is None:
            output_path = str(self.logs_folder / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
        
        report_lines = [
            f"# Q&A 系統報告",
            f"",
            f"## 產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"",
            f"## 每日摘要（最近7天）",
            f""
        ]
        
        weekly = self.get_weekly_report()
        report_lines.append(f"- 期間：{weekly['period']}")
        report_lines.append(f"- 新增 Q&A：{weekly['total_qa_created']}")
        report_lines.append(f"- Q&A 使用次數：{weekly['total_qa_used']}")
        report_lines.append(f"- 快取命中：{weekly['total_cache_hits']}")
        report_lines.append(f"- 命中率：{weekly['cache_hit_rate']}")
        report_lines.append(f"- 衝突偵測：{weekly['total_conflicts']}")
        report_lines.append(f"")
        
        # Top 10 Q&A
        report_lines.append(f"## 熱門 Q&A Top 10")
        report_lines.append(f"")
        top_qa = self.get_top_qa(10)
        for i, qa in enumerate(top_qa, 1):
            report_lines.append(f"{i}. {qa['qa_id']} - 使用 {qa['usage_count']} 次")
        report_lines.append(f"")
        
        # 寫入檔案
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(report_lines))
        
        return output_path


# ============================================================
# 整合到 QACache
# ============================================================

class QACacheWithLogger:
    """
    增強版 QACache（包含日誌系統）
    
    這個類別包裝原本的 QACache，並整合 QALogger
    """
    
    def __init__(
        self,
        cache_folder: str = "/home/da40_ai_gb10/knowledge-base/data/cleaned",
        logs_folder: str = None
    ):
        if logs_folder is None:
            logs_folder = str(Path(cache_folder) / "logs")
        
        self.logger = QALogger(logs_folder)
        
        # 原始 QACache 功能
        from .qa_cache import QACache as BaseQACache
        self.base = BaseQACache(cache_folder)
    
    def save_qa(self, question: str, answer: str, sources: List[str] = None, mode_used: str = "unknown") -> Dict:
        """儲存 Q&A 並記錄日誌"""
        result = self.base.save_qa(question, answer, sources, mode_used)
        
        # 記錄日誌
        self.logger.log_qa_created(result['qa_id'], question, sources)
        
        return result
    
    def find_similar(self, question: str, threshold: float = 0.6) -> Optional[Dict]:
        """查找相似 Q&A 並記錄日誌"""
        result = self.base.find_similar(question, threshold)
        
        # 記錄搜尋
        cache_hit = result is not None
        self.logger.log_search(
            question,
            result['qa_id'] if result else None,
            cache_hit
        )
        
        if result:
            self.logger.log_qa_used(result['qa_id'], 0.8)  # 相似度約 0.8
        
        return result


# ============================================================
# 快速函式
# ============================================================

def get_logger() -> QALogger:
    """取得日誌管理器"""
    return QALogger()


def log_qa_created(qa_id: str, question: str, sources: List[str] = None):
    """快速記錄 Q&A 新增"""
    logger = get_logger()
    return logger.log_qa_created(qa_id, question, sources)


def log_qa_used(qa_id: str, similarity: float = 0.8, time_saved: float = 15):
    """快速記錄 Q&A 使用"""
    logger = get_logger()
    return logger.log_qa_used(qa_id, similarity, time_saved)


def get_daily_summary(date: datetime = None) -> Dict:
    """快速取得每日摘要"""
    logger = get_logger()
    return logger.get_daily_summary(date)


def export_report() -> str:
    """快速匯出報告"""
    logger = get_logger()
    return logger.export_markdown_report()