"""
Q&A Cache 模組

用於管理 Cleaned/ 資料夾中的 Q&A 知識庫
支援結構化 Q&A 存儲、相似度查找、衝突偵測
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import hashlib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class QACache:
    """Q&A 知識庫管理器"""

    def __init__(self, cache_folder: str = "/home/da40_ai_gb10/knowledge-base/data/cleaned"):
        self.cache_folder = Path(cache_folder)
        self.cache_folder.mkdir(parents=True, exist_ok=True)
        
        # 確保有 logs 資料夾
        self.logs_folder = self.cache_folder / "logs"
        self.logs_folder.mkdir(parents=True, exist_ok=True)
    
    def _generate_qa_id(self, question: str) -> str:
        """產生唯一的 Q&A ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        question_hash = hashlib.md5(question.encode()).hexdigest()[:6]
        return f"qa_{timestamp}_{question_hash}"
    
    def _extract_keywords(self, question: str, answer: str = "") -> List[str]:
        """從問答中提取關鍵字"""
        # 簡單的關鍵字提取（去除停用詞）
        stop_words = {"是", "的", "了", "在", "和", "是", "有", "我", "你", "他", "她", "它", "什麼", "怎麼", "為什麼"}
        
        text = question + " " + (answer or "")
        words = []
        
        for word in text:
            # 簡單分詞（每個字或英文單詞）
            import re
            tokens = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', text)
        
        # 過濾停用詞
        keywords = [t for t in tokens if t not in stop_words and len(t) > 1]
        
        # 如果關鍵字太少，回退使用原始問答
        if len(keywords) < 3 and len(question) > 5:
            keywords = list(question)[:10]
        
        return list(set(keywords))[:20]  # 最多20個關鍵字
    
    def save_qa(
        self,
        question: str,
        answer: str,
        sources: List[str] = None,
        mode_used: str = "unknown",
        related_qa: List[str] = None
    ) -> Dict:
        """
        儲存新的 Q&A 到 Cleaned 資料夾
        
        Args:
            question: 問題
            answer: 回答
            sources: 來源檔案列表
            mode_used: 使用的搜尋模式
            related_qa: 關聯的 Q&A ID 列表
        
        Returns:
            Q&A 結構字典
        """
        qa_id = self._generate_qa_id(question)
        keywords = self._extract_keywords(question, answer)
        
        qa_data = {
            "qa_id": qa_id,
            "question": question,
            "answer_summary": self._summarize_answer(answer),
            "answer_full": answer,
            "key_points": self._extract_key_points(answer),
            "keywords": keywords,
            "sources": sources or [],
            "mode_used": mode_used,
            "related_qa": related_qa or [],
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "usage_count": 0,
            "last_used": None,
            "conflict_flag": False,
            "verified": False,
            "conflict_with": None,
            "status": "active"
        }
        
        # 寫入檔案
        filename = f"{qa_id}.json"
        filepath = self.cache_folder / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(qa_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Q&A 已儲存: {qa_id}")
        
        # 記錄日誌
        self._log_operation("qa_created", qa_id, question)
        
        # 更新關聯 Q&A 的 related_qa
        if related_qa:
            for related_id in related_qa:
                self._add_related_qa(related_id, qa_id)
        
        return qa_data
    
    def _summarize_answer(self, answer: str, max_length: int = 200) -> str:
        """產生回答摘要"""
        if len(answer) <= max_length:
            return answer
        return answer[:max_length] + "..."
    
    def _extract_key_points(self, answer: str, max_points: int = 5) -> List[str]:
        """提取回答的關鍵點"""
        # 簡單的關鍵點提取（按句號或分號分割）
        import re
        
        sentences = re.split(r'[。；\n]', answer)
        points = [s.strip() for s in sentences if len(s.strip()) > 10][:max_points]
        
        return points
    
    def find_similar(self, question: str, threshold: float = 0.6) -> Optional[Dict]:
        """
        在 Cleaned 資料夾中找相似問題
        
        Args:
            question: 查詢問題
            threshold: 相似度閾值 (0-1)
        
        Returns:
            相似的 Q&A 字典，如果沒有則返回 None
        """
        keywords = self._extract_keywords(question)
        question_lower = question.lower()
        
        best_match = None
        best_score = 0.0
        
        # 掃描所有 Q&A 檔案
        for json_file in self.cache_folder.glob("qa_*.json"):
            if json_file.name.startswith("qa_") and json_file.suffix == ".json":
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        qa_data = json.load(f)
                    
                    # 計算相似度
                    score = self._calculate_similarity(question, qa_data, keywords)
                    
                    if score > best_score and score >= threshold:
                        best_score = score
                        best_match = qa_data
                        
                except Exception as e:
                    logger.warning(f"讀取 Q&A 檔案失敗: {json_file}, {e}")
                    continue
        
        if best_match:
            logger.info(f"找到相似 Q&A: {best_match['qa_id']}, 相似度: {best_score:.2f}")
            # 更新使用次數
            self._increment_usage(best_match['qa_id'])
            self._log_operation("qa_used", best_match['qa_id'], f"相似度 {best_score:.2f}")
        
        return best_match
    
    def _calculate_similarity(self, question: str, qa_data: Dict, keywords: List[str]) -> float:
        """計算問題相似度"""
        score = 0.0
        
        # 1. 關鍵字匹配（40%）
        qa_keywords = set(qa_data.get('keywords', []))
        input_keywords = set(keywords)
        
        if qa_keywords:
            keyword_overlap = len(qa_keywords & input_keywords) / len(qa_keywords)
            score += keyword_overlap * 0.4
        
        # 2. 問題直接匹配（30%）
        q_question = qa_data.get('question', '').lower()
        if q_question:
            if question.lower() == q_question:
                score += 0.3
            elif question.lower() in q_question or q_question in question.lower():
                score += 0.2
        
        # 3. 關鍵字出現在問題中（30%）
        match_count = 0
        for kw in keywords:
            if kw.lower() in q_question:
                match_count += 1
        
        if keywords:
            score += (match_count / len(keywords)) * 0.3
        
        return min(score, 1.0)
    
    def _increment_usage(self, qa_id: str):
        """增加 Q&A 的使用次數"""
        filepath = self.cache_folder / f"{qa_id}.json"
        
        if filepath.exists():
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    qa_data = json.load(f)
                
                qa_data['usage_count'] = qa_data.get('usage_count', 0) + 1
                qa_data['last_used'] = datetime.now().isoformat()
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(qa_data, f, ensure_ascii=False, indent=2)
                    
            except Exception as e:
                logger.warning(f"更新使用次數失敗: {qa_id}, {e}")
    
    def _add_related_qa(self, qa_id: str, related_id: str):
        """新增關聯 Q&A"""
        filepath = self.cache_folder / f"{qa_id}.json"
        
        if filepath.exists():
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    qa_data = json.load(f)
                
                related_list = qa_data.get('related_qa', [])
                if related_id not in related_list:
                    related_list.append(related_id)
                    qa_data['related_qa'] = related_list
                    qa_data['last_updated'] = datetime.now().isoformat()
                    
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(qa_data, f, ensure_ascii=False, indent=2)
                        
            except Exception as e:
                logger.warning(f"新增關聯失敗: {qa_id} -> {related_id}, {e}")
    
    def mark_conflict(self, qa_id: str, conflict_with_qa_id: str):
        """標記 Q&A 衝突"""
        filepath = self.cache_folder / f"{qa_id}.json"
        
        if filepath.exists():
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    qa_data = json.load(f)
                
                qa_data['conflict_flag'] = True
                qa_data['conflict_with'] = conflict_with_qa_id
                qa_data['last_updated'] = datetime.now().isoformat()
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(qa_data, f, ensure_ascii=False, indent=2)
                
                logger.warning(f"Q&A 衝突標記: {qa_id} vs {conflict_with_qa_id}")
                self._log_operation("conflict_detected", qa_id, f"vs {conflict_with_qa_id}")
                
            except Exception as e:
                logger.error(f"標記衝突失敗: {e}")
    
    def resolve_conflict(self, qa_id: str, resolution: str):
        """
        解決衝突
        
        Args:
            qa_id: Q&A ID
            resolution: 解決方式 ("merged", "deleted", "kept_both")
        """
        filepath = self.cache_folder / f"{qa_id}.json"
        
        if filepath.exists():
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    qa_data = json.load(f)
                
                qa_data['conflict_flag'] = False
                qa_data['status'] = resolution
                qa_data['last_updated'] = datetime.now().isoformat()
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(qa_data, f, ensure_ascii=False, indent=2)
                
                logger.info(f"衝突已解決: {qa_id}, 方式: {resolution}")
                self._log_operation("conflict_resolved", qa_id, resolution)
                
            except Exception as e:
                logger.error(f"解決衝突失敗: {e}")
    
    def _log_operation(self, operation: str, qa_id: str, detail: str = ""):
        """記錄操作日誌"""
        log_file = self.logs_folder / f"log_{datetime.now().strftime('%Y-%m')}.md"
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        log_entry = f"## [{timestamp}] {operation} | {qa_id}\n"
        log_entry += f"- **Detail**: {detail}\n"
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    
    def get_all_qa(self) -> List[Dict]:
        """取得所有 Q&A"""
        qa_list = []
        
        for json_file in self.cache_folder.glob("qa_*.json"):
            if json_file.name.startswith("qa_") and json_file.suffix == ".json":
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        qa_data = json.load(f)
                    qa_list.append(qa_data)
                except Exception as e:
                    logger.warning(f"讀取 Q&A 失敗: {json_file}, {e}")
        
        return qa_list
    
    def get_qa_stats(self) -> Dict:
        """取得 Q&A 統計"""
        qa_list = self.get_all_qa()
        
        total = len(qa_list)
        total_usage = sum(qa.get('usage_count', 0) for qa in qa_list)
        conflicts = sum(1 for qa in qa_list if qa.get('conflict_flag', False))
        verified = sum(1 for qa in qa_list if qa.get('verified', False))
        
        return {
            "total_qa": total,
            "total_usage": total_usage,
            "conflicts": conflicts,
            "verified": verified,
            "cache_folder": str(self.cache_folder)
        }


# ============================================================
# 快速函式
# ============================================================

def quick_save_qa(question: str, answer: str, sources: List[str] = None) -> Dict:
    """快速儲存 Q&A"""
    cache = QACache()
    return cache.save_qa(question, answer, sources)


def quick_find_similar(question: str, threshold: float = 0.6) -> Optional[Dict]:
    """快速查找相似 Q&A"""
    cache = QACache()
    return cache.find_similar(question, threshold)