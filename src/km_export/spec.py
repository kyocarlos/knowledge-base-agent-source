"""The document an export produces: one validated description that every file format is built from.

The language model only ever fills this description in; the files themselves are written by ``builders``.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

FORMATS = ("pptx", "docx", "xlsx", "md", "csv", "html")
MAX_SECTIONS = 30
MAX_ITEMS = 24
MAX_ROWS = 200
MAX_COLUMNS = 12
DISCLAIMER = "本檔案由 AI 依知識庫回答整理而成，內容請對照來源再使用。"


def _clean(value: str) -> str:
    return " ".join(str(value).replace("\r", "\n").split()) if value is not None else ""


class Table(BaseModel):
    columns: list[str] = Field(default_factory=list, max_length=MAX_COLUMNS)
    rows: list[list[str]] = Field(default_factory=list, max_length=MAX_ROWS)

    @field_validator("columns", mode="before")
    @classmethod
    def _columns(cls, value):
        return [_clean(v)[:80] for v in (value or [])]

    @field_validator("rows", mode="before")
    @classmethod
    def _rows(cls, value):
        return [[_clean(c)[:400] for c in row] for row in (value or []) if isinstance(row, (list, tuple))]

    def usable(self) -> bool:
        return bool(self.columns and self.rows)

    def square(self) -> "Table":
        """Every row gets exactly as many cells as there are columns."""
        width = len(self.columns)
        return Table(columns=self.columns, rows=[(row + [""] * width)[:width] for row in self.rows])


class Section(BaseModel):
    heading: str = Field(default="", max_length=200)
    paragraphs: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    bullets: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    table: Table | None = None
    sources: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)

    @field_validator("heading", mode="before")
    @classmethod
    def _heading(cls, value):
        return _clean(value)[:200]

    @field_validator("paragraphs", "bullets", "sources", mode="before")
    @classmethod
    def _lines(cls, value):
        return [text for text in (_clean(v)[:1200] for v in (value or [])) if text]


class ExportSpec(BaseModel):
    format: str
    title: str = Field(min_length=1, max_length=200)
    subtitle: str = Field(default="", max_length=300)
    sections: list[Section] = Field(min_length=1, max_length=MAX_SECTIONS)

    @field_validator("format")
    @classmethod
    def _format(cls, value):
        value = str(value).strip().lower().lstrip(".")
        if value not in FORMATS:
            raise ValueError(f"format must be one of {', '.join(FORMATS)}")
        return value

    @field_validator("title", "subtitle", mode="before")
    @classmethod
    def _text(cls, value):
        return _clean(value)[:300]

    def outline(self) -> list[str]:
        return [s.heading or "（無標題）" for s in self.sections]
