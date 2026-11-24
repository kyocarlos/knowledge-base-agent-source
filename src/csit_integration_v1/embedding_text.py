"""The text a passage is embedded as.

The PDF converter writes, for every page, lines that name the page snapshot and the embedded images (asset://...), and a "頁面文字：" label. They are references for the
viewers that show the page, not content. Left in the text that is embedded they dilute the vector of every passage they sit in: the cover of a product brochure
(30 MHz to 3.8 GHz) ranked 22nd for "which frequencies does it support", behind passages with no such statement, and never reached the model (2026-11-23).

Only the vector is computed from the cleaned text. The passage that is stored, cited and shown is unchanged, so passage numbers, ids and citations stay as they were.
"""
import re

_REFERENCE_LINES = re.compile(
    r"^[ \t]*(?:- )?(?:頁面快照引用|內嵌圖片|圖片 \d+|頁面文字)[：:].*$"      # "- 頁面快照引用：asset://...", "  - 圖片 1：asset://...", "- 頁面文字：..."
    r"|^[ \t]*- (?:內嵌圖片|頁面文字)[：:]?[ \t]*$"                      # the bare labels
    r"|asset://\S+",                                                  # any reference left inside a line
    re.M)


def embedding_text(chunk: str) -> str:
    """The chunk without its reference lines; the chunk itself when nothing else is left (a page that is only references still gets a vector)."""
    cleaned = _REFERENCE_LINES.sub(" ", chunk or "")
    return cleaned if cleaned.strip() else chunk
