"""Untagged scanner — flags hardcoded English in HTML."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator

from bs4 import BeautifulSoup, NavigableString

from .base import BaseScanner, ScannerResult


_NON_UI_TAGS = {"script", "style", "code", "pre", "svg", "noscript"}
_TRANSLATABLE_ATTRS = ("placeholder", "title", "alt", "aria-label")
_IGNORE_EXACT = {"OK", "×", "✕", "▾", "▸", "·", "—", "–", "•"}
_ALPHA_RUN = re.compile(r"[A-Za-z]{2,}")
_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "site-packages",
    "dist",
    "build",
    ".egg-info",
}


def _slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", text.lower()).strip("_")
    return s[:max_len] or "unnamed"


def _inherits_i18n(el) -> bool:
    while el is not None and getattr(el, "attrs", None) is not None:
        for attr in el.attrs:
            if attr.startswith("data-i18n"):
                return True
        el = el.parent
    return False


def _is_translatable_text(text: str) -> bool:
    t = text.strip()
    if not t or t in _IGNORE_EXACT:
        return False
    if len(t) < 3:
        return False
    if not _ALPHA_RUN.search(t):
        return False
    return True


class UntaggedScanner(BaseScanner):
    gap_type = "untagged"

    def __init__(self, source: str, directory: str):
        self.source = source
        self.directory = directory

    def scan(self) -> Iterator[ScannerResult]:
        if not os.path.isdir(self.directory):
            return
        for root, dirs, files in os.walk(self.directory):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.endswith(".egg-info")]
            for name in files:
                if not name.endswith((".html", ".htm")):
                    continue
                path = os.path.join(root, name)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        raw = f.read()
                except OSError:
                    continue
                yield from self._scan_file(path, raw)

    def _scan_file(self, path: str, raw: str) -> Iterator[ScannerResult]:
        soup = BeautifulSoup(raw, "html.parser")
        for tag_name in _NON_UI_TAGS:
            for tag in soup.find_all(tag_name):
                tag.extract()
        for text_node in soup.find_all(string=True):
            if not isinstance(text_node, NavigableString):
                continue
            parent = text_node.parent
            if parent is None:
                continue
            if _inherits_i18n(parent):
                continue
            text = str(text_node)
            if not _is_translatable_text(text):
                continue
            snippet = text.strip()[:200]
            yield ScannerResult(
                source=self.source,
                gap_type=self.gap_type,
                file_path=path,
                line_number=_line_no_of(raw, snippet),
                snippet=snippet,
                suggested_key=f"{self.source}.{Path(path).stem}.{_slugify(snippet)}",
            )
        for attr in _TRANSLATABLE_ATTRS:
            for el in soup.find_all(attrs={attr: True}):
                if _inherits_i18n(el):
                    continue
                if f"data-i18n-{attr}" in el.attrs:
                    continue
                text = str(el.attrs[attr])
                if not _is_translatable_text(text):
                    continue
                snippet = text.strip()[:200]
                yield ScannerResult(
                    source=self.source,
                    gap_type=self.gap_type,
                    file_path=path,
                    line_number=_line_no_of(raw, snippet),
                    snippet=f"[{attr}] {snippet}",
                    suggested_key=f"{self.source}.{Path(path).stem}.{_slugify(snippet)}",
                )


def _line_no_of(raw: str, snippet: str) -> int:
    idx = raw.find(snippet)
    if idx < 0:
        return 0
    return raw.count("\n", 0, idx) + 1
