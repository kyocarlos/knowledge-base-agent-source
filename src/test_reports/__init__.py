"""Canonical Anritsu/Amarisoft test-report ingestion support."""

from .excel_contract import ReportValidationError, parse_and_validate_report, render_report_markdown
from .registry import SubmissionConflict, SubmissionRegistry

__all__ = [
    "ReportValidationError",
    "SubmissionConflict",
    "SubmissionRegistry",
    "parse_and_validate_report",
    "render_report_markdown",
]
