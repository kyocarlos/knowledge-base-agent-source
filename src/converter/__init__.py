"""
檔案轉換模組 - 使用 MarkItDown 將各種格式轉為 Markdown
"""

import os
import logging
import re
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional, List
from markitdown import MarkItDown
import yaml

from ..chunk_assets import get_document_asset_path, relative_asset_path

logger = logging.getLogger(__name__)


class FileConverter:
    """將各式檔案轉換為 Markdown 格式"""

    _shared_default_llm_client = None

    def __init__(self, llm_client=None, llm_model: Optional[str] = None):
        """
        初始化轉換器

        Args:
            llm_client: LLM client（如 OpenAI 兼容），用於圖片描述與 OCR
            llm_model: LLM 模型名稱
        """
        if llm_client is None:
            llm_client = self._build_default_llm_client(llm_model)

        self.md = MarkItDown(
            enable_plugins=True,
            llm_client=llm_client,
            llm_model=llm_model
        )

    def _build_default_llm_client(self, llm_model: Optional[str] = None):
        """從 config.yaml 建立預設 LLM client，讓圖片/OCR 能自動啟用。"""
        if FileConverter._shared_default_llm_client is not None:
            return FileConverter._shared_default_llm_client

        config_path = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
        if not config_path.exists():
            return None

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"載入 LLM 設定失敗，將略過圖片增強：{e}")
            return None

        try:
            from src.web_api.ollama_client import OllamaClient

            ollama_cfg = config.get("ollama", {})
            instances = ollama_cfg.get("instances") or []
            base_url = instances[0] if instances else ollama_cfg.get("base_url", "http://localhost:11434")
            llm = OllamaClient(
                    model=llm_model or ollama_cfg.get("model", config.get("llm_model", "gemma4:12b")),
                base_url=base_url
            )

            FileConverter._shared_default_llm_client = llm
            logger.info("已啟用預設 LLM client 作為圖片/OCR 增強")
            return llm
        except Exception as e:
            logger.warning(f"建立預設 LLM client 失敗，將略過圖片增強：{e}")
            return None

    def convert_file(self, input_path: str, output_path: Optional[str] = None) -> dict:
        """
        轉換單一檔案為 Markdown

        Args:
            input_path: 輸入檔案路徑
            output_path: 輸出 Markdown 路徑（預設為同目錄 .md）

        Returns:
            dict: 轉換結果，包含 text_content 和 metadata
        """
        input_file = Path(input_path)
        if not input_file.exists():
            raise FileNotFoundError(f"檔案不存在: {input_path}")

        # 預設輸出路徑
        if output_path is None:
            output_path = input_file.with_suffix(".md").resolve()

        try:
            logger.info(f"開始轉換: {input_file.name}")
            content_parts = []

            asset_refs: List[str] = []
            suffix = input_file.suffix.lower()

            if suffix == ".pdf":
                enrichment = self._build_pdf_enrichment(input_file)
                enrichment_text = enrichment.get("text", "")
                if enrichment_text.strip():
                    content_parts.append(enrichment_text.strip())
                asset_refs.extend(enrichment.get("image_refs", []))

                # 若 PDF 快照/文字抽取失敗，退回 MarkItDown 原始結果，避免整份檔案失敗。
                if not content_parts:
                    result = self.md.convert(str(input_file))
                    fallback_text = result.text_content.strip()
                    if fallback_text:
                        fallback_text = self._strip_inline_base64_media(fallback_text)
                        content_parts.append(fallback_text)

            else:
                result = self.md.convert(str(input_file))

            if suffix == ".xlsx":
                enrichment = self._build_excel_enrichment(input_file)
                enrichment_text = enrichment.get("text", "")
                if enrichment_text.strip():
                    content_parts.append(enrichment_text.strip())
                asset_refs.extend(enrichment.get("image_refs", []))

            text_content = ""
            if suffix != ".pdf":
                text_content = result.text_content.strip()

            if suffix == ".xlsx" and text_content:
                text_content = self._clean_excel_markdown(text_content)
            if text_content:
                text_content = self._strip_inline_base64_media(text_content)

            if text_content:
                content_parts.append(text_content)

            combined_content = "\n\n".join(content_parts) if content_parts else result.text_content
            if combined_content:
                combined_content = self._strip_inline_base64_media(combined_content)

            # 寫入 Markdown 檔案
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(combined_content, encoding="utf-8")

            logger.info(f"轉換成功: {input_file.name} -> {output_file.name}")
            return {
                "status": "success",
                "source": input_file.name,
                "output": str(output_file),
                "content": combined_content,
                "char_count": len(combined_content),
                "image_refs": asset_refs,
            }
        except Exception as e:
            logger.error(f"轉換失敗 {input_file.name}: {e}")
            return {
                "status": "error",
                "source": input_file.name,
                "error": str(e)
            }

    def _build_pdf_enrichment(self, input_file: Path) -> dict:
        """
        將 PDF 轉成「每頁一段 markdown + 頁面快照 + 內嵌圖片」。

        這條路徑只適用於 PDF，不影響 Excel 的既有圖片輸出邏輯。
        """
        try:
            page_count = self._get_pdf_page_count(input_file)
        except Exception as e:
            logger.warning(f"PDF 頁數取得失敗，略過頁面快照: {e}")
            return {"text": "", "image_refs": []}

        sections: List[str] = []
        image_refs: List[str] = []
        doc_name = input_file.stem
        embedded_images_by_page = self._export_pdf_embedded_image_assets(input_file, doc_name)

        for page_num in range(1, page_count + 1):
            page_asset_ref = self._export_pdf_page_asset(input_file, doc_name, page_num)
            if page_asset_ref:
                image_refs.append(page_asset_ref)

            embedded_refs = embedded_images_by_page.get(page_num, [])
            for ref in embedded_refs:
                if ref not in image_refs:
                    image_refs.append(ref)

            page_text = self._extract_pdf_page_text(input_file, page_num)
            page_text = self._normalize_pdf_text(page_text)
            if not page_text:
                page_text = "（本頁未抽取到可用文字，請參考原圖）"

            section_lines = [f"## PDF 頁面 {page_num}"]
            if page_asset_ref:
                section_lines.append(f"- 頁面快照引用：asset://{page_asset_ref}")
            if embedded_refs:
                section_lines.append("- 內嵌圖片：")
                for index, ref in enumerate(embedded_refs, start=1):
                    section_lines.append(f"  - 圖片 {index}：asset://{ref}")
            section_lines.append("- 頁面文字：")
            section_lines.append(page_text)
            sections.append("\n".join(section_lines))

        return {
            "text": "\n\n".join(sections),
            "image_refs": image_refs,
        }

    def _export_pdf_embedded_image_assets(self, input_file: Path, doc_name: str) -> dict[int, List[str]]:
        """把 PDF 內嵌圖片抽出為獨立資產，回傳以頁碼分組的相對路徑。"""
        try:
            with tempfile.TemporaryDirectory(prefix=f"{doc_name}_pdfimages_") as temp_dir:
                temp_root = Path(temp_dir)
                output_prefix = temp_root / "embedded"
                list_result = subprocess.run(
                    [
                        "pdfimages",
                        "-list",
                        str(input_file),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )

                image_candidates: set[tuple[int, int]] = set()
                for raw_line in list_result.stdout.splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("page") or line.startswith("-"):
                        continue
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    try:
                        page_num = int(parts[0])
                        image_num = int(parts[1])
                    except Exception:
                        continue
                    image_type = parts[2].lower()
                    if image_type != "image":
                        continue
                    image_candidates.add((page_num, image_num))

                if not image_candidates:
                    return {}

                subprocess.run(
                    [
                        "pdfimages",
                        "-all",
                        "-p",
                        str(input_file),
                        str(output_prefix),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )

                page_map: dict[int, List[str]] = {}
                for extracted_path in sorted(temp_root.glob("embedded-*.*")):
                    match = re.match(r"embedded-(\d{3})-(\d{3})\.(.+)", extracted_path.name)
                    if not match:
                        continue
                    page_num = int(match.group(1))
                    image_num = int(match.group(2))
                    if (page_num, image_num) not in image_candidates:
                        continue

                    dest_dir = get_document_asset_path("pdf", doc_name, "embedded", f"page-{page_num:03d}")
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    dest_path = dest_dir / f"image-{image_num:03d}{extracted_path.suffix.lower()}"
                    shutil.copy2(extracted_path, dest_path)
                    page_map.setdefault(page_num, []).append(relative_asset_path(dest_path))

                for refs in page_map.values():
                    refs.sort()
                return page_map
        except Exception as e:
            logger.warning(f"PDF 內嵌圖片輸出失敗，略過原圖抽取: {e}")
            return {}

    def _get_pdf_page_count(self, input_file: Path) -> int:
        """透過 pdfinfo 取得 PDF 頁數。"""
        result = subprocess.run(
            ["pdfinfo", str(input_file)],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            if line.lower().startswith("pages:"):
                return int(line.split(":", 1)[1].strip())
        raise ValueError("無法從 pdfinfo 取得頁數")

    def _extract_pdf_page_text(self, input_file: Path, page_num: int) -> str:
        """抽取單一 PDF 頁面的文字。"""
        result = subprocess.run(
            [
                "pdftotext",
                "-layout",
                "-nopgbrk",
                "-q",
                "-f",
                str(page_num),
                "-l",
                str(page_num),
                str(input_file),
                "-",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout or ""

    def _export_pdf_page_asset(self, input_file: Path, doc_name: str, page_num: int) -> str:
        """把單一 PDF 頁面輸出為 PNG 快照，並回傳相對資產路徑。"""
        try:
            asset_dir = get_document_asset_path("pdf", doc_name, "pages")
            asset_dir.mkdir(parents=True, exist_ok=True)
            output_prefix = asset_dir / f"page-{page_num:03d}"

            subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-singlefile",
                    "-r",
                    "144",
                    "-f",
                    str(page_num),
                    "-l",
                    str(page_num),
                    str(input_file),
                    str(output_prefix),
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            asset_path = output_prefix.with_suffix(".png")
            if asset_path.exists():
                return relative_asset_path(asset_path)
            return ""
        except Exception as e:
            logger.warning(f"PDF 頁面快照輸出失敗（page {page_num}）: {e}")
            return ""

    def _normalize_pdf_text(self, text: str) -> str:
        """整理 PDF 文字抽取結果，保留段落與表格感。"""
        if not text:
            return ""
        cleaned = text.replace("\x0c", "")
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def convert_batch(self, input_folder: str, output_folder: str,
                      file_patterns: Optional[List[str]] = None) -> List[dict]:
        """
        批次轉換資料夾內的所有檔案

        Args:
            input_folder: 輸入資料夾
            output_folder: 輸出資料夾
            file_patterns: 要處理的副檔名列表（如 [".pdf", ".docx"]）
                          預設處理所有 MarkItDown 支援的格式

        Returns:
            List[dict]: 每個檔案的轉換結果
        """
        input_dir = Path(input_folder)
        output_dir = Path(output_folder)
        output_dir.mkdir(parents=True, exist_ok=True)

        if file_patterns is None:
            file_patterns = [".pdf", ".docx", ".pptx", ".xlsx", ".xls",
                             ".txt", ".md", ".html", ".csv", ".json", ".xml"]

        results = []

        # 遞迴處理所有子資料夾
        for file_path in input_dir.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in file_patterns:
                relative_path = file_path.relative_to(input_dir)
                output_path = output_dir / relative_path.with_suffix(".md")

                result = self.convert_file(
                    str(file_path),
                    str(output_path)
                )
                results.append(result)

        return results

    def _build_excel_enrichment(self, input_file: Path) -> dict:
        """
        將 xlsx 內的圖表與嵌入圖片摘要成 Markdown。

        這是補強層，不影響 MarkItDown 原本輸出的文字內容。
        """
        try:
            from openpyxl import load_workbook
        except Exception as e:
            logger.warning(f"openpyxl 不可用，略過 Excel 圖表/圖片摘要: {e}")
            return {"text": "", "image_refs": []}

        try:
            workbook = load_workbook(str(input_file), data_only=True)
        except Exception as e:
            logger.warning(f"載入 Excel 失敗，略過圖表/圖片摘要: {e}")
            return {"text": "", "image_refs": []}

        sections: List[str] = []
        image_refs: List[str] = []
        doc_name = input_file.stem

        for worksheet in workbook.worksheets:
            chart_lines = self._summarize_sheet_charts(worksheet)
            image_lines, sheet_image_refs = self._summarize_sheet_images(worksheet, doc_name)
            image_refs.extend(sheet_image_refs)

            if chart_lines:
                sections.append(
                    f"## Excel 圖表摘要 - {worksheet.title}\n" + "\n".join(chart_lines)
                )
            if image_lines:
                sections.append(
                    f"## Excel 圖片摘要 - {worksheet.title}\n" + "\n".join(image_lines)
                )

        return {
            "text": "\n\n".join(sections),
            "image_refs": image_refs,
        }

    def _clean_excel_markdown(self, content: str) -> str:
        """
        清理 MarkItDown 對 xlsx 產出的 Markdown，移除大量 NaN / Unnamed 空欄位。

        只對 Markdown 表格區塊動手，避免影響一般段落內容。
        """
        lines = content.splitlines()
        cleaned_lines: List[str] = []
        index = 0

        while index < len(lines):
            line = lines[index]
            if not self._looks_like_markdown_table_row(line):
                cleaned_lines.append(line)
                index += 1
                continue

            table_block: List[str] = []
            while index < len(lines) and self._looks_like_markdown_table_row(lines[index]):
                table_block.append(lines[index])
                index += 1

            cleaned_block = self._clean_markdown_table_block(table_block)
            if cleaned_block:
                cleaned_lines.extend(cleaned_block)

        return "\n".join(cleaned_lines)

    def _strip_inline_base64_media(self, content: str) -> str:
        """移除 Markdown/HTML 裡的 inline base64 圖片，避免 chunk 裡混入大量 base64。"""
        if not content:
            return content

        patterns = [
            r"!\[[^\]]*\]\(data:image\/[^)]+\)",
            r"<img[^>]+src=[\"']data:image\/[^\"']+[\"'][^>]*>",
            r"data:image\/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+",
        ]

        cleaned = content
        for pattern in patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.DOTALL)

        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _looks_like_markdown_table_row(self, line: str) -> bool:
        stripped = (line or "").strip()
        return stripped.startswith("|") and "|" in stripped[1:]

    def _clean_markdown_table_block(self, block: List[str]) -> List[str]:
        parsed_rows = []
        max_cell_count = 0

        for raw_line in block:
            if self._is_markdown_table_separator(raw_line):
                cells = self._split_markdown_table_row(raw_line)
                parsed_rows.append({"separator": True, "cells": cells})
                max_cell_count = max(max_cell_count, len(cells))
                continue

            cells = self._split_markdown_table_row(raw_line)
            normalized_cells = [self._normalize_excel_cell(cell) for cell in cells]
            parsed_rows.append({"separator": False, "cells": normalized_cells})
            max_cell_count = max(max_cell_count, len(normalized_cells))

        if not parsed_rows or max_cell_count == 0:
            return []

        for row in parsed_rows:
            row["cells"].extend([""] * (max_cell_count - len(row["cells"])))

        meaningful_rows = [
            row for row in parsed_rows
            if not row["separator"] and any(cell for cell in row["cells"])
        ]
        if not meaningful_rows:
            return []

        non_empty_columns = [
            column_index
            for column_index in range(max_cell_count)
            if any(row["cells"][column_index] for row in meaningful_rows)
        ]
        if not non_empty_columns:
            return []

        cleaned_rows: List[str] = []
        emitted_data_row = False

        for row_index, row in enumerate(parsed_rows):
            projected_cells = [row["cells"][index] for index in non_empty_columns]

            if row["separator"]:
                if emitted_data_row and self._has_later_meaningful_row(parsed_rows, row_index, non_empty_columns):
                    cleaned_rows.append(self._join_markdown_table_row(["---"] * len(projected_cells)))
                continue

            if not any(projected_cells):
                continue

            cleaned_rows.append(self._join_markdown_table_row(projected_cells))
            emitted_data_row = True

        return cleaned_rows

    def _has_later_meaningful_row(self, rows: List[dict], current_index: int, columns: List[int]) -> bool:
        for row in rows[current_index + 1:]:
            if row["separator"]:
                continue
            if any(row["cells"][index] for index in columns):
                return True
        return False

    def _split_markdown_table_row(self, line: str) -> List[str]:
        stripped = (line or "").strip().strip("|")
        return [cell.strip() for cell in stripped.split("|")]

    def _join_markdown_table_row(self, cells: List[str]) -> str:
        return "| " + " | ".join(cells) + " |"

    def _is_markdown_table_separator(self, line: str) -> bool:
        stripped = (line or "").strip()
        if not stripped.startswith("|") or "|" not in stripped[1:]:
            return False

        cells = self._split_markdown_table_row(stripped)
        if not cells:
            return False

        return all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells if cell != "")

    def _normalize_excel_cell(self, value: str) -> str:
        text = self._compact_text(value)
        if not text:
            return ""

        lowered = text.lower()
        if lowered in {"nan", "nat", "none"}:
            return ""
        if text.startswith("Unnamed:"):
            return ""
        return text

    def _summarize_sheet_charts(self, worksheet) -> List[str]:
        chart_lines: List[str] = []
        charts = list(getattr(worksheet, "_charts", []) or [])

        for index, chart in enumerate(charts, start=1):
            chart_lines.extend(self._describe_chart(worksheet.title, index, chart))

        return chart_lines

    def _summarize_sheet_images(self, worksheet, doc_name: str) -> tuple[List[str], List[str]]:
        image_lines: List[str] = []
        image_refs: List[str] = []
        images = list(getattr(worksheet, "_images", []) or [])

        for index, image in enumerate(images, start=1):
            lines, asset_ref = self._describe_image(doc_name, worksheet.title, index, image)
            image_lines.extend(lines)
            if asset_ref:
                image_refs.append(asset_ref)

        return image_lines, image_refs

    def _describe_chart(self, sheet_name: str, index: int, chart) -> List[str]:
        title = self._extract_chart_title(chart)
        chart_type = type(chart).__name__
        anchor = self._anchor_to_cell(getattr(chart, "anchor", None))
        lines = [f"- 圖表 {index}"]

        meta_bits = [f"類型：{chart_type}"]
        if title:
            meta_bits.append(f"標題：{title}")
        if anchor:
            meta_bits.append(f"位置：{anchor}")
        lines.append("  - " + "；".join(meta_bits))

        series_list = list(getattr(chart, "ser", []) or [])
        if not series_list:
            return lines

        for s_index, series in enumerate(series_list, start=1):
            series_bits = []
            series_title = self._extract_series_title(series)
            cats_ref = self._extract_series_reference(series, "cat")
            vals_ref = self._extract_series_reference(series, "val")

            if series_title:
                series_bits.append(f"系列：{series_title}")
            if cats_ref:
                series_bits.append(f"分類範圍：{cats_ref}")
            if vals_ref:
                series_bits.append(f"數值範圍：{vals_ref}")

            if series_bits:
                lines.append(f"  - Series {s_index}：" + "；".join(series_bits))
            else:
                lines.append(f"  - Series {s_index}：{type(series).__name__}")

        return lines

    def _describe_image(self, doc_name: str, sheet_name: str, index: int, image) -> tuple[List[str], str]:
        lines = [f"- 圖片 {index}"]

        anchor = self._anchor_to_cell(getattr(image, "anchor", None))
        width = getattr(image, "width", None)
        height = getattr(image, "height", None)
        fmt = getattr(image, "format", None)

        meta_bits = []
        if fmt:
            meta_bits.append(f"格式：{fmt}")
        if width and height:
            meta_bits.append(f"尺寸：{width}x{height}")
        if anchor:
            meta_bits.append(f"位置：{anchor}")

        image_bytes = self._get_excel_image_bytes(image)
        asset_ref = self._export_excel_image_asset(doc_name, sheet_name, index, image, image_bytes=image_bytes)
        if asset_ref:
            meta_bits.append(f"原圖引用：{asset_ref}")

        summary_text = self._summarize_image_asset(image, image_bytes=image_bytes)
        if summary_text:
            meta_bits.append(f"摘要：{summary_text}")

        if meta_bits:
            lines.append("  - " + "；".join(meta_bits))

        return lines, asset_ref

    def _get_excel_image_bytes(self, image) -> bytes:
        try:
            if not hasattr(image, "_data"):
                return b""
            image_bytes = image._data()
            return image_bytes or b""
        except Exception:
            return b""

    def _export_excel_image_asset(self, doc_name: str, sheet_name: str, index: int, image, image_bytes: bytes | None = None) -> str:
        """將 Excel 內嵌圖片輸出成可回溯資產。"""
        try:
            if image_bytes is None:
                image_bytes = self._get_excel_image_bytes(image)
            if not image_bytes:
                return ""

            fmt = str(getattr(image, "format", "") or "png").lower()
            suffix = ".jpg" if fmt in {"jpeg", "jpg"} else f".{fmt or 'png'}"

            asset_dir = get_document_asset_path(doc_name, "excel", sheet_name)
            asset_dir.mkdir(parents=True, exist_ok=True)
            asset_path = asset_dir / f"image-{index:02d}{suffix}"
            asset_path.write_bytes(image_bytes)
            return relative_asset_path(asset_path)
        except Exception as e:
            logger.warning(f"Excel 圖片資產輸出失敗：{e}")
            return ""

    def _summarize_image_asset(self, image, image_bytes: bytes | None = None) -> str:
        """把 Excel 內嵌圖片輸出成暫存檔，再交給 MarkItDown 做文字摘要。"""
        try:
            if image_bytes is None:
                image_bytes = self._get_excel_image_bytes(image)
            if not image_bytes:
                return ""

            suffix = f".{str(getattr(image, 'format', '')).lower()}" if getattr(image, "format", None) else ".png"

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                tmp_file.write(image_bytes)
                tmp_path = Path(tmp_file.name)

            try:
                extracted = self.md.convert(str(tmp_path))
                text = (extracted.text_content or "").strip()
                return self._compact_text(text)
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Excel 圖片摘要失敗：{e}")
            return ""

    def _extract_chart_title(self, chart) -> str:
        """盡量把 openpyxl chart title 轉為文字。"""
        title = getattr(chart, "title", None)
        if not title:
            return ""

        # openpyxl 的圖表標題通常落在 rich text 結構裡，
        # 直接抽這條路徑通常比泛用遞迴更穩。
        try:
            tx = getattr(title, "tx", None)
            rich = getattr(tx, "rich", None)
            if rich is not None:
                collected = []
                paragraphs = getattr(rich, "p", None) or []
                for paragraph in paragraphs:
                    runs = getattr(paragraph, "r", None) or []
                    paragraph_has_run_text = False
                    for run in runs:
                        text = getattr(run, "t", None)
                        if text:
                            collected.append(str(text))
                            paragraph_has_run_text = True

                    # 某些標題會直接落在 paragraph 的 endParaRPr 之外，
                    # 這裡保留遞迴作為補強。
                    paragraph_text = self._collect_text(paragraph)
                    if paragraph_text and not paragraph_has_run_text:
                        collected.append(paragraph_text)

                deduped = []
                for item in collected:
                    compacted = self._compact_text(item)
                    if compacted and compacted not in deduped:
                        deduped.append(compacted)

                direct_text = self._compact_text(" ".join(deduped))
                if direct_text:
                    return direct_text
        except Exception:
            pass

        text = self._collect_text(title)
        return self._compact_text(text)

    def _extract_series_title(self, series) -> str:
        tx = getattr(series, "tx", None)
        if tx is None:
            return ""

        for attr in ("strRef", "numRef"):
            ref = getattr(tx, attr, None)
            if ref is not None:
                value = getattr(ref, "v", None) or getattr(ref, "f", None)
                if value:
                    return self._compact_text(str(value))

        for attr in ("v", "value", "text"):
            value = getattr(tx, attr, None)
            if value:
                return self._compact_text(self._collect_text(value))

        return self._compact_text(self._collect_text(tx))

    def _extract_series_reference(self, series, attr_name: str) -> str:
        node = getattr(series, attr_name, None)
        if node is None:
            return ""

        for ref_attr in ("numRef", "strRef"):
            ref = getattr(node, ref_attr, None)
            if ref is not None:
                formula = getattr(ref, "f", None)
                if formula:
                    return self._compact_text(str(formula))

        formula = getattr(node, "f", None)
        if formula:
            return self._compact_text(str(formula))

        value = getattr(node, "v", None)
        if value:
            return self._compact_text(str(value))

        return ""

    def _anchor_to_cell(self, anchor) -> str:
        try:
            from_idx = getattr(anchor, "_from", None)
            if from_idx is None:
                return ""

            row = getattr(from_idx, "row", None)
            col = getattr(from_idx, "col", None)
            if row is None or col is None:
                return ""

            return f"{self._column_letter(col + 1)}{row + 1}"
        except Exception:
            return ""

    def _column_letter(self, index: int) -> str:
        index = max(1, int(index))
        letters = []
        while index:
            index, remainder = divmod(index - 1, 26)
            letters.append(chr(65 + remainder))
        return "".join(reversed(letters))

    def _collect_text(self, value, seen=None, depth: int = 0, max_depth: int = 4) -> str:
        if seen is None:
            seen = set()

        if value is None or depth > max_depth:
            return ""

        obj_id = id(value)
        if obj_id in seen:
            return ""
        seen.add(obj_id)

        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, (list, tuple, set)):
            return " ".join(
                part for part in (self._collect_text(item, seen, depth + 1, max_depth) for item in value) if part
            )

        texts = []
        for attr in (
            "text", "plain_text", "value", "v", "t", "tx", "rich", "strRef", "numRef",
            "p", "r", "pt", "strCache", "numCache", "f", "formula"
        ):
            if hasattr(value, attr):
                try:
                    extracted = getattr(value, attr)
                except Exception:
                    continue
                if extracted is not None and extracted is not value:
                    text = self._collect_text(extracted, seen, depth + 1, max_depth)
                    if text:
                        texts.append(text)

        return " ".join(texts).strip()

    def _compact_text(self, text: str) -> str:
        return " ".join((text or "").split()).strip()

    @staticmethod
    def list_supported_formats() -> List[str]:
        """回傳 MarkItDown 支援的格式列表"""
        return [
            # Office 文件
            ".docx", ".xlsx", ".xls", ".pptx",
            # PDF
            ".pdf",
            # 圖片
            ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp",
            # 網頁與標記語言
            ".html", ".htm", ".csv", ".json", ".xml",
            # 其他
            ".txt", ".md", ".epub", ".msg",
        ]


def rebuild_excel_assets(input_path: str) -> List[str]:
    """
    重新建立 Excel 內嵌圖片資產。

    這只負責把原圖落盤到 data/assets，不會覆寫來源 markdown。
    """
    input_file = Path(input_path)
    if input_file.suffix.lower() != ".xlsx" or not input_file.exists():
        return []

    converter = FileConverter()
    enrichment = converter._build_excel_enrichment(input_file)
    return enrichment.get("image_refs", []) or []
