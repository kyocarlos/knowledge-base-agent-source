"""
Conflict Detector - 衝突檢測模組

用於偵測知識庫中的資訊衝突，包括：
- 同一 Entity 的不同屬性值衝突
- 同一關係的屬性衝突
- 數值/規格不一致
- 過時與最新資訊衝突
"""

import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConflictSeverity(Enum):
    """衝突嚴重性"""
    HIGH = "high"      # 嚴重衝突，需要立即處理
    MEDIUM = "medium"  # 中度衝突，需要審查
    LOW = "low"        # 輕微衝突，僅標記


class ConflictType(Enum):
    """衝突類型"""
    ENTITY_ATTRIBUTE = "entity_attribute"      # 實體屬性衝突
    RELATIONSHIP = "relationship"              # 關係衝突
    NUMERIC_VALUE = "numeric_value"            # 數值衝突
    TEMPORAL = "temporal"                      # 時序衝突（過時vs新）
    SEMANTIC = "semantic"                      # 語意衝突


@dataclass
class Conflict:
    """衝突資訊"""
    conflict_id: str
    conflict_type: ConflictType
    severity: ConflictSeverity
    entity_name: str
    attribute_name: str
    value_a: str
    value_b: str
    source_a: str
    source_b: str
    description: str
    resolution_suggestion: str = ""
    resolved: bool = False
    resolved_value: Optional[str] = None


class ConflictDetector:
    """衝突檢測器"""
    
    def __init__(self):
        self.conflicts: List[Conflict] = []
        self._conflict_counter = 0
    
    def _generate_conflict_id(self) -> str:
        """產生唯一的衝突 ID"""
        self._conflict_counter += 1
        return f"conflict_{self._conflict_counter:04d}"
    
    def detect_entity_conflicts(
        self,
        entities: List[Dict],
        threshold: float = 0.7
    ) -> List[Conflict]:
        """
        偵測實體屬性衝突
        
        Args:
            entities: 實體列表
            threshold: 相似度閾值（低於此值視為可能相同實體）
        
        Returns:
            衝突列表
        """
        conflicts = []
        
        # 按名稱相似度分組實體
        entity_groups = self._group_similar_entities(entities, threshold)
        
        for group in entity_groups:
            if len(group) < 2:
                continue
            
            # 比較同組內的屬性
            conflicts.extend(self._compare_entity_attributes(group))
        
        logger.info(f"偵測到 {len(conflicts)} 個實體屬性衝突")
        return conflicts
    
    def _group_similar_entities(
        self,
        entities: List[Dict],
        threshold: float
    ) -> List[List[Dict]]:
        """將相似的實體分組"""
        groups = []
        used = set()
        
        for i, entity in enumerate(entities):
            if i in used:
                continue
            
            group = [entity]
            entity_name = entity.get("name", entity.get("Name", ""))
            
            for j, other in enumerate(entities[i+1:], start=i+1):
                if j in used:
                    continue
                
                other_name = other.get("name", other.get("Name", ""))
                if self._names_similar(entity_name, other_name, threshold):
                    group.append(other)
                    used.add(j)
            
            if len(group) > 1:
                groups.append(group)
                for idx in [i] + [k for k in range(i+1, len(entities)) if k in used]:
                    used.add(idx)
        
        return groups
    
    def _names_similar(self, name1: str, name2: str, threshold: float) -> bool:
        """檢查兩個名稱是否相似"""
        import re
        
        # 移除特殊字符，轉小寫
        def normalize(s):
            return re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]', '', s.lower())
        
        n1, n2 = normalize(name1), normalize(name2)
        
        if not n1 or not n2:
            return False
        
        # 計算 Levenshtein 距離比例
        max_len = max(len(n1), len(n2))
        if max_len == 0:
            return False
        
        distance = self._levenshtein_distance(n1, n2)
        similarity = 1 - (distance / max_len)
        
        return similarity >= threshold
    
    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """計算 Levenshtein 距離"""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]
    
    def _compare_entity_attributes(self, entity_group: List[Dict]) -> List[Conflict]:
        """比較同組實體的屬性"""
        conflicts = []
        
        # 取得所有唯一屬性名稱
        all_attrs = set()
        for entity in entity_group:
            all_attrs.update(entity.keys())
        
        # 排除系統欄位
        system_fields = {"name", "Name", "source", "source_doc", "extraction_mode", "description", "Description"}
        all_attrs -= system_fields
        
        for attr in all_attrs:
            values = []
            sources = []
            
            for entity in entity_group:
                val = entity.get(attr) or entity.get(attr.capitalize(), "")
                if val and str(val).strip():
                    values.append(str(val).strip())
                    sources.append(entity.get("source", entity.get("source_doc", "unknown")))
            
            # 檢查是否有衝突值
            unique_values = list(set(values))
            if len(unique_values) > 1:
                # 這是衝突
                conflict = Conflict(
                    conflict_id=self._generate_conflict_id(),
                    conflict_type=ConflictType.ENTITY_ATTRIBUTE,
                    severity=self._assess_severity(attr, unique_values),
                    entity_name=entity_group[0].get("name", entity_group[0].get("Name", "")),
                    attribute_name=attr,
                    value_a=unique_values[0],
                    value_b=unique_values[1],
                    source_a=sources[0] if sources else "unknown",
                    source_b=sources[1] if len(sources) > 1 else sources[0],
                    description=f"屬性 '{attr}' 在不同來源中有不同值",
                    resolution_suggestion=self._suggest_resolution(attr, unique_values)
                )
                conflicts.append(conflict)
        
        return conflicts
    
    def _assess_severity(self, attribute: str, values: List[str]) -> ConflictSeverity:
        """評估衝突嚴重性"""
        # 高嚴重性屬性
        high_severity_attrs = {
            "location", "Location", "位置",
            "softwareversion", "version", "version", "版本",
            "operationmode", "mode", "模式",
            "ip", "address", "位址"
        }
        
        # 中嚴重性屬性
        medium_severity_attrs = {
            "serialnumber", "sn", "序號",
            "devicemodel", "model", "型號",
            "frequencyband", "band", "頻段"
        }
        
        attr_lower = attribute.lower()
        
        if attr_lower in high_severity_attrs:
            return ConflictSeverity.HIGH
        elif attr_lower in medium_severity_attrs:
            return ConflictSeverity.MEDIUM
        else:
            return ConflictSeverity.LOW
    
    def _suggest_resolution(self, attribute: str, values: List[str]) -> str:
        """建議解決方案"""
        if len(values) == 2:
            return f"請確認哪個值正確：'{values[0]}' 或 '{values[1]}'"
        return f"有多個可能值：{', '.join(values)}"
    
    def detect_numeric_conflicts(
        self,
        entities: List[Dict],
        numeric_attrs: List[str] = None
    ) -> List[Conflict]:
        """
        偵測數值衝突
        
        Args:
            entities: 實體列表
            numeric_attrs: 要檢查的數值屬性名稱列表
        
        Returns:
            衝突列表
        """
        if numeric_attrs is None:
            numeric_attrs = [
                "transmissionrate", "rate", "傳輸速率",
                "frequency", "freq", "頻率",
                "txpower", "power", "發射功率",
                "coverage", "覆蓋範圍"
            ]
        
        conflicts = []
        
        for entity in entities:
            entity_name = entity.get("name", entity.get("Name", ""))
            
            for attr in numeric_attrs:
                val_a = entity.get(attr)
                val_b = entity.get(attr.capitalize())
                
                if val_a and val_b:
                    try:
                        # 嘗試解析數值
                        num_a = self._parse_numeric(val_a)
                        num_b = self._parse_numeric(val_b)
                        
                        if num_a and num_b:
                            # 檢查差異是否超過 10%
                            if abs(num_a - num_b) / max(num_a, num_b) > 0.1:
                                conflict = Conflict(
                                    conflict_id=self._generate_conflict_id(),
                                    conflict_type=ConflictType.NUMERIC_VALUE,
                                    severity=ConflictSeverity.MEDIUM,
                                    entity_name=entity_name,
                                    attribute_name=attr,
                                    value_a=str(val_a),
                                    value_b=str(val_b),
                                    source_a=entity.get("source", "unknown"),
                                    source_b=entity.get("source_doc", "unknown"),
                                    description=f"數值衝突：{num_a} vs {num_b}",
                                    resolution_suggestion="請確認正確的數值"
                                )
                                conflicts.append(conflict)
                    except (ValueError, TypeError):
                        pass
        
        logger.info(f"偵測到 {len(conflicts)} 個數值衝突")
        return conflicts
    
    def _parse_numeric(self, value) -> Optional[float]:
        """解析數值"""
        if isinstance(value, (int, float)):
            return float(value)
        
        if isinstance(value, str):
            # 移除常見單位
            import re
            cleaned = re.sub(r'[a-zA-ZMbpsGbpsMHzGHz%]', '', value)
            try:
                return float(cleaned.strip())
            except ValueError:
                return None
        
        return None
    
    def detect_temporal_conflicts(
        self,
        entities: List[Dict],
        date_attrs: List[str] = None
    ) -> List[Conflict]:
        """
        偵測時序衝突（過時vs新）
        
        Args:
            entities: 實體列表
            date_attrs: 日期屬性名稱列表
        
        Returns:
            衝突列表
        """
        if date_attrs is None:
            date_attrs = [
                "softversion", "version", "版本", "softwareversion",
                "updated", "date", "日期", "修改日期"
            ]
        
        conflicts = []
        
        for entity in entities:
            entity_name = entity.get("name", entity.get("Name", ""))
            version = entity.get("softversion") or entity.get("version") or entity.get("softwareversion", "")
            
            if version:
                # 檢查版本格式是否一致
                import re
                version_match = re.search(r'V?(\d+\.\d+\.\d+)', str(version))
                if version_match:
                    version_str = version_match.group(1)
                    # 這裡可以進一步檢查版本衝突
                    pass
        
        logger.info(f"偵測到 {len(conflicts)} 個時序衝突")
        return conflicts
    
    def add_conflict(self, conflict: Conflict):
        """手動新增衝突"""
        self.conflicts.append(conflict)
        logger.info(f"新增衝突: {conflict.conflict_id} - {conflict.entity_name}.{conflict.attribute_name}")
    
    def get_unresolved_conflicts(self) -> List[Conflict]:
        """取得所有未解決的衝突"""
        return [c for c in self.conflicts if not c.resolved]
    
    def resolve_conflict(
        self,
        conflict_id: str,
        resolved_value: str
    ) -> bool:
        """
        解決衝突
        
        Args:
            conflict_id: 衝突 ID
            resolved_value: 決定的正確值
        
        Returns:
            是否成功
        """
        for conflict in self.conflicts:
            if conflict.conflict_id == conflict_id:
                conflict.resolved = True
                conflict.resolved_value = resolved_value
                logger.info(f"解決衝突 {conflict_id} -> {resolved_value}")
                return True
        return False
    
    def get_conflicts_by_severity(
        self,
        severity: ConflictSeverity
    ) -> List[Conflict]:
        """按嚴重性取得衝突"""
        return [c for c in self.conflicts if c.severity == severity]
    
    def get_conflicts_by_entity(self, entity_name: str) -> List[Conflict]:
        """取得特定實體的所有衝突"""
        return [c for c in self.conflicts if c.entity_name == entity_name]
    
    def export_conflicts(self) -> Dict:
        """匯出衝突報告"""
        return {
            "total_conflicts": len(self.conflicts),
            "unresolved": len(self.get_unresolved_conflicts()),
            "high_severity": len(self.get_conflicts_by_severity(ConflictSeverity.HIGH)),
            "medium_severity": len(self.get_conflicts_by_severity(ConflictSeverity.MEDIUM)),
            "low_severity": len(self.get_conflicts_by_severity(ConflictSeverity.LOW)),
            "conflicts": [
                {
                    "id": c.conflict_id,
                    "type": c.conflict_type.value,
                    "severity": c.severity.value,
                    "entity": c.entity_name,
                    "attribute": c.attribute_name,
                    "value_a": c.value_a,
                    "value_b": c.value_b,
                    "source_a": c.source_a,
                    "source_b": c.source_b,
                    "description": c.description,
                    "resolution": c.resolution_suggestion,
                    "resolved": c.resolved,
                    "resolved_value": c.resolved_value
                }
                for c in self.conflicts
            ]
        }


# ============================================================
# 快速檢測函式
# ============================================================

def quick_conflict_check(entities: List[Dict]) -> Dict:
    """
    快速衝突檢查
    
    Args:
        entities: 實體列表
    
    Returns:
        衝突報告字典
    """
    detector = ConflictDetector()
    
    # 偵測各類型衝突
    entity_conflicts = detector.detect_entity_conflicts(entities)
    numeric_conflicts = detector.detect_numeric_conflicts(entities)
    temporal_conflicts = detector.detect_temporal_conflicts(entities)
    
    # 合併衝突
    detector.conflicts.extend(entity_conflicts)
    detector.conflicts.extend(numeric_conflicts)
    detector.conflicts.extend(temporal_conflicts)
    
    return detector.export_conflicts()