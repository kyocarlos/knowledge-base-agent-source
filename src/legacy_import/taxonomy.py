"""CSIT document taxonomy (L1/L2/L3) and the topic zone each row routes to.

The table lives in config/csit-topic-map.csv (CSIT document-centre classification + topic mapping). The classifier may only
choose one of its rows, so a legacy document always lands in a defined topic zone or in the review queue.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parents[2] / "config" / "csit-topic-map.csv"

# Rows that do not describe NAS files: requests / weekly reports kept in Jira or Confluence.
NOT_FILES = {"3b", "30b"}
# Time Report, HR and procurement documents are imported like any other (decision A of the 2026-11-10 mapping table: no access rules, everyone sees them).

MISC_ZONE = "CSIT雜項專區"


@dataclass(frozen=True)
class Row:
    id: str
    l1: str
    l2: str
    l3: str
    condition: str
    topic: str
    note: str

    def label(self) -> str:
        return " / ".join(part for part in (self.l1, self.l2, self.l3) if part)


UNCLASSIFIED = Row("unclassified", "未分類", "", "", "信心不足，待人工確認", MISC_ZONE, "")


def load(path: Path = CSV_PATH) -> list[Row]:
    with open(path, encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        next(reader)  # header
        return [Row(*[cell.strip() for cell in (record + [""] * 7)[:7]]) for record in reader if record and record[0].strip()]


# Only contracts and confidentiality agreements stay out: the topic table has no row for them. HR, procurement and Time Report documents have rows (32, 33, 29).
SENSITIVE_PATH_TERMS = ("合約", "合同", "contract", "nda", "保密")

# Driver packages, binaries and vendor codec source trees: no knowledge value, never read.
NOISE_PATH_TERMS = ("/drivers/", "/binaries/", "/binary/", "g729", "g.729", "g723", "g.723", "/node_modules/", "/.git/",
                    "/program files/", "/program files (x86)/")
NOISE_NAMES = ("readme.txt", "readme", "release.txt", "makefile", "thumbs.db")


def sensitive_path(path: str) -> str | None:
    """The first sensitive term in a legacy path, or None. Such files are never read, analysed or imported."""
    lowered = path.lower().replace("\\", "/")
    return next((term for term in SENSITIVE_PATH_TERMS if _term_in(term, lowered)), None)


def _term_in(term: str, lowered: str) -> bool:
    if term.isascii() and len(term) <= 3:                  # "nda" must not match inside "standard" or "agenda"
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lowered) is not None
    return term in lowered


def noise_path(path: str) -> str | None:
    """A reason to leave a legacy file out as low-value (driver / binary / codec source tree / readme of a software package), or None."""
    lowered = "/" + path.lower().replace("\\", "/")
    term = next((t for t in NOISE_PATH_TERMS if t in lowered), None)
    if term:
        return f"noise path '{term.strip('/')}'"
    return f"noise file '{lowered.rsplit('/', 1)[-1]}'" if lowered.rsplit("/", 1)[-1] in NOISE_NAMES else None


# Documents the CSIT table has no row for. They route to an existing topic zone; ids start with "s" so they are never confused with table rows.
SUPPLEMENT = (
    Row("s1", "技術相關文件", "技術名稱：xDSL", "（技術細項）", "技術名稱為 xDSL／ADSL／VDSL／DSLAM", "固網寬頻知識專區", "補充列：附件未列 xDSL"),
    Row("s2", "設備儀器管理", "設備預約系統", "Project System 文件", "設備預約系統（Project System）的說明與操作文件", "設備預約知識專區", "補充列"),
    Row("s3", "實驗室內部管理", "實驗室管理辦法", "", "實驗室使用、管理規則與辦法", "實驗室與測試環境知識專區", "補充列"),
    Row("s4", "國際組織規範", "其他標準（IEEE 802.3／ITU-T 等）", "Test Plan／MRD／SPEC", "組織為 IEEE 802.11 以外的標準（例如 802.3 乙太網路、ITU-T）", "CSIT雜項專區", "補充列：附件未列"),
)


def choices(rows: list[Row] | None = None) -> list[Row]:
    """Rows a legacy document may be classified into."""
    return [row for row in (rows if rows is not None else load()) if row.id not in NOT_FILES] + list(SUPPLEMENT)


def zones(rows: list[Row] | None = None) -> list[str]:
    return sorted({row.topic for row in choices(rows)})
