"""
文件分塊模組 - 智慧分塊工具
"""

import re
import logging
import hashlib
import json
from typing import List, Dict
from pathlib import Path

from ..image_refs import extract_image_refs_from_text, merge_image_refs
from ..knowledge_package import build_chunk_id, build_package_metadata, resolve_document_version

logger = logging.getLogger(__name__)


class TextChunker:
    """文件分塊器"""

    def __init__(
        self,
        max_chunk_size: int = 500,
        overlap: int = 50,
        min_chunk_size: int = 100
    ):
        """
        初始化分塊器

        Args:
            max_chunk_size: 最大區塊字數
            overlap: 重疊字數
            min_chunk_size: 最小區塊字數
        """
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap
        self.min_chunk_size = min_chunk_size

    def chunk_by_headers(self, content: str, doc_name: str = "") -> List[Dict]:
        """
        按標題分塊（保留 Markdown 標題結構）

        Args:
            content: Markdown 內容
            doc_name: 文件名稱

        Returns:
            分塊列表，每個包含 id, content, metadata
        """
        chunks = []

        # 按 ## 標題分割
        header_pattern = r'(^#{1,6}\s+.+)$'
        parts = re.split(header_pattern, content, flags=re.MULTILINE)

        current_header = ""
        current_lines: List[str] = []

        def flush_current_chunk() -> None:
            nonlocal current_lines
            if not current_lines:
                return
            current_chunk = "\n".join(current_lines).strip()
            if len(current_chunk) >= self.min_chunk_size:
                chunks.append({
                    "id": f"{doc_name}_{len(chunks)}",
                    "content": current_chunk,
                    "metadata": {
                        "header": current_header,
                        "doc_name": doc_name
                    }
                })
            current_lines = []

        def push_line(line: str) -> None:
            nonlocal current_lines
            normalized_line = line.rstrip()

            if not normalized_line.strip():
                if current_lines and current_lines[-1] != "":
                    current_lines.append("")
                return

            candidate_lines = current_lines + [normalized_line]
            candidate_text = "\n".join(candidate_lines).strip()

            if len(candidate_text) <= self.max_chunk_size:
                current_lines = candidate_lines
                return

            if current_lines:
                flush_current_chunk()
                candidate_text = normalized_line
                if len(candidate_text) <= self.max_chunk_size:
                    current_lines = [normalized_line]
                    return

            # 單行過長時直接硬切，避免整個 section 被當成一個大塊。
            start = 0
            while start < len(normalized_line):
                piece = normalized_line[start:start + self.max_chunk_size].strip()
                start += self.max_chunk_size
                if not piece:
                    continue
                if len(piece) >= self.min_chunk_size:
                    chunks.append({
                        "id": f"{doc_name}_{len(chunks)}",
                        "content": piece,
                        "metadata": {
                            "header": current_header,
                            "doc_name": doc_name
                        }
                    })

        for i, part in enumerate(parts):
            if re.match(header_pattern, part):
                # 這是一個標題
                if current_lines:
                    flush_current_chunk()
                current_header = part.strip()
            elif part.strip():
                # 這是內容
                text = part.strip()
                for line in text.splitlines():
                    push_line(line)

        # 最後一個區塊
        flush_current_chunk()

        logger.info(f"分塊完成: {len(chunks)} 個區塊")
        return chunks

    def chunk_by_paragraphs(self, content: str, doc_name: str = "") -> List[Dict]:
        """
        按段落分塊（簡單但有效）

        Args:
            content: 文字內容
            doc_name: 文件名稱

        Returns:
            分塊列表
        """
        chunks = []

        # 按換行分割為段落
        paragraphs = re.split(r'\n\s*\n', content)

        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # 如果加上這個段落會超過限制
            if len(current_chunk) + len(para) > self.max_chunk_size:
                if len(current_chunk) >= self.min_chunk_size:
                    chunks.append({
                        "id": f"{doc_name}_{len(chunks)}",
                        "content": current_chunk.strip(),
                        "metadata": {"doc_name": doc_name}
                    })

                current_chunk = para
            else:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para

        # 最後一個區塊
        if len(current_chunk) >= self.min_chunk_size:
            chunks.append({
                "id": f"{doc_name}_{len(chunks)}",
                "content": current_chunk.strip(),
                "metadata": {"doc_name": doc_name}
            })

        logger.info(f"段落分塊完成: {len(chunks)} 個區塊")
        return chunks

    def chunk_markdown(self, content: str, doc_name: str = "") -> List[Dict]:
        """
        智慧分塊 Markdown（先按標題，再按段落）

        Args:
            content: Markdown 內容
            doc_name: 文件名稱

        Returns:
            分塊列表
        """
        # 檢查是否有 Markdown 標題
        has_headers = bool(re.search(r'^#{1,6}\s', content, re.MULTILINE))

        if has_headers:
            return self.chunk_by_headers(content, doc_name)
        else:
            return self.chunk_by_paragraphs(content, doc_name)


def chunk_document(file_path: str) -> List[Dict]:
    """
    對文件進行分塊

    Args:
        file_path: 文件路徑

    Returns:
        分塊列表
    """
    path = Path(file_path)
    doc_name = path.stem
    content = path.read_text(encoding="utf-8")
    source_metadata_path = path.with_name(f"{path.stem}.source.json")
    source_metadata = {}
    if source_metadata_path.exists():
        source_metadata = json.loads(source_metadata_path.read_text(encoding="utf-8"))
    document_id = str(source_metadata.get("document_id") or source_metadata.get("documentId") or doc_name)
    document_version = resolve_document_version(source_metadata)
    document_content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    source_path = str(path.resolve())

    chunker = TextChunker(max_chunk_size=500, overlap=50)
    chunks = chunker.chunk_markdown(content, doc_name)
    for chunk_index, chunk in enumerate(chunks):
        metadata = chunk.setdefault("metadata", {})
        chunk["chunk_index"] = chunk_index
        chunk["id"] = build_chunk_id(document_id, document_version, chunk_index, str(chunk.get("content") or ""))
        metadata.update(build_package_metadata(
            document_id=document_id,
            document_version=document_version,
            content_hash=document_content_hash,
        ))
        chunk_image_refs = extract_image_refs_from_text(chunk.get("content", ""))
        existing_image_refs = metadata.get("image_refs", [])
        merged_image_refs = merge_image_refs(existing_image_refs, chunk_image_refs)
        if merged_image_refs:
            metadata["image_refs"] = merged_image_refs
        metadata.setdefault("source_path", source_path)
        metadata.setdefault("source_name", path.name)
        metadata.setdefault("source_ext", path.suffix.lower())
        metadata.setdefault("source_dir", str(path.parent.resolve()))
    return chunks
