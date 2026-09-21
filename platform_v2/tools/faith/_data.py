"""Faith module scriptural data layer — loaders, readers, and search helpers.

Moved out of routes.py so the module file sizes the Code Health scanner
(LARGE_FILE / 600-line threshold) can be kept under control. All data
sources live in ``tools/faith/data`` (local saved copies, no network I/O).

Every function here is pure data logic; none of them import or dispatch to
DHQ. Faith JSON handlers import them via ``routes`` re-exports
(``from . import routes as _R``) so tests' ``mock.patch("tools.faith.routes.X")``
calls keep landing on the live attribute at call time.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import cast

from flask import request

from ._constants import (
    ANALECTS_LEGGE_PATH,
    BHAGAVAD_GITA_ARNOLD_PATH,
    DHAMMAPADA_MULLER_PATH,
    ENCYCLOPEDIA_PATH,
    JPS_VPL_PATH,
    MAX_SEARCH_LIMIT,
    MIN_SEARCH_LIMIT,
    QURAN_RODWELL_PATH,
    SCRIPTURE_COLLECTIONS,
    TAO_LEGGE_PATH,
    WEB_BOOK_NAMES,
    WEB_VPL_PATH,
    JsonDict,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_web_bible() -> JsonDict:
    books: list[JsonDict] = []
    by_code: dict[str, JsonDict] = {}
    verses: list[JsonDict] = []

    with WEB_VPL_PATH.open("r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                code, rest = line.split(" ", 1)
                if " " in rest:
                    ref, text = rest.split(" ", 1)
                else:
                    ref, text = rest, ""
                chapter_s, verse_s = ref.split(":", 1)
                chapter = int(chapter_s)
                verse = int(re.match(r"\d+", verse_s).group(0))
            except (AttributeError, ValueError):
                logger.warning("[Faith] Skipping malformed WEB line: %s", line[:80])
                continue

            if code not in by_code:
                book = {
                    "code": code,
                    "name": WEB_BOOK_NAMES.get(code, code),
                    "chapters": [],
                }
                by_code[code] = book
                books.append(book)
            book = by_code[code]
            if chapter not in book["chapters"]:
                book["chapters"].append(chapter)

            verses.append(
                {
                    "book": code,
                    "book_name": book["name"],
                    "chapter": chapter,
                    "verse": verse,
                    "reference": f"{book['name']} {chapter}:{verse}",
                    "text": text.strip(),
                }
            )

    aliases: dict[str, str] = {}
    for book in books:
        aliases[book["code"].lower()] = book["code"]
        aliases[book["name"].lower()] = book["code"]
        aliases[book["name"].replace(" ", "").lower()] = book["code"]
    return {"books": books, "verses": verses, "aliases": aliases}


def _collection_meta(collection_id: str) -> JsonDict:
    return next((item for item in SCRIPTURE_COLLECTIONS if item["id"] == collection_id), {})


def _scripture_record(collection_id: str, reference: str, text: str) -> JsonDict:
    meta = _collection_meta(collection_id)
    normalized_text = " ".join(text.split())
    search_text = " ".join(
        [
            meta.get("name", collection_id),
            meta.get("tradition", ""),
            reference,
            normalized_text,
        ]
    ).lower()
    return {
        "collection": collection_id,
        "collection_name": meta.get("name", collection_id),
        "tradition": meta.get("tradition", ""),
        "reference": reference,
        "text": normalized_text,
        "_search": search_text,
    }


def _public_scripture_record(record: JsonDict) -> JsonDict:
    return {key: value for key, value in record.items() if not key.startswith("_")}


@lru_cache(maxsize=1)
def _load_jps_tanakh() -> list[JsonDict]:
    records: list[JsonDict] = []
    with JPS_VPL_PATH.open("r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                code, rest = line.split(" ", 1)
                ref, text = rest.split(" ", 1)
                chapter_s, verse_s = ref.split(":", 1)
                chapter = int(chapter_s)
                verse = int(re.match(r"\d+", verse_s).group(0))
            except (AttributeError, ValueError):
                logger.warning("[Faith] Skipping malformed JPS line: %s", line[:80])
                continue
            book_name = WEB_BOOK_NAMES.get(code, code)
            records.append(_scripture_record("jps1917", f"{book_name} {chapter}:{verse}", text))
    return records


def _gutenberg_body(path: Path, start_marker: str) -> list[str]:
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    start = 0
    end = len(lines)
    for i, line in enumerate(lines):
        if start_marker in line:
            start = i + 1
            break
    for i, line in enumerate(lines[start:], start):
        if line.startswith("*** END OF THE PROJECT GUTENBERG EBOOK"):
            end = i
            break
    return lines[start:end]


@lru_cache(maxsize=1)
def _load_quran_rodwell() -> list[JsonDict]:
    records: list[JsonDict] = []
    current_sura = ""
    paragraph: list[str] = []

    def flush() -> None:
        nonlocal paragraph
        text = " ".join(part.strip() for part in paragraph if part.strip())
        paragraph = []
        if current_sura and len(text) > 24:
            records.append(_scripture_record("quran_rodwell", current_sura, text))

    for raw in _gutenberg_body(QURAN_RODWELL_PATH, "*** START OF THE PROJECT GUTENBERG EBOOK"):
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("SURA") and line.upper() == line:
            flush()
            current_sura = re.sub(r"\s+", " ", line).strip(" .")
            continue
        if current_sura:
            paragraph.append(line)
    flush()
    return records


@lru_cache(maxsize=1)
def _load_dhammapada_muller() -> list[JsonDict]:
    records: list[JsonDict] = []
    chapter = ""
    verse_no = ""
    verse_lines: list[str] = []

    def flush() -> None:
        nonlocal verse_no, verse_lines
        if verse_no and verse_lines:
            reference = f"Dhammapada {verse_no}" + (f" — {chapter}" if chapter else "")
            records.append(_scripture_record("dhammapada_muller", reference, " ".join(verse_lines)))
        verse_no = ""
        verse_lines = []

    for raw in _gutenberg_body(DHAMMAPADA_MULLER_PATH, "*** START OF THE PROJECT GUTENBERG EBOOK"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Chapter "):
            flush()
            chapter = line
            continue
        match = re.match(r"^(\d+)\.\s+(.*)", line)
        if match:
            flush()
            verse_no = match.group(1)
            verse_lines = [match.group(2)]
        elif verse_no:
            verse_lines.append(line)
    flush()
    return records


def _gutenberg_sectioned_paragraphs(
    collection_id: str,
    path: Path,
    default_reference: str,
    section_patterns: list[tuple[str, str]],
) -> list[JsonDict]:
    records: list[JsonDict] = []
    section = default_reference
    paragraph: list[str] = []

    def flush() -> None:
        nonlocal paragraph
        text = " ".join(part.strip() for part in paragraph if part.strip())
        paragraph = []
        if len(text) > 24:
            records.append(_scripture_record(collection_id, section, text))

    for raw in _gutenberg_body(path, "*** START"):
        line = raw.strip()
        if not line:
            flush()
            continue
        matched_section = None
        for pattern, label in section_patterns:
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                matched_section = label.format(*match.groups()) if match.groups() else line
                break
        if matched_section:
            flush()
            section = matched_section
            continue
        paragraph.append(line)
    flush()
    return records


@lru_cache(maxsize=1)
def _load_bhagavad_gita_arnold() -> list[JsonDict]:
    return _gutenberg_sectioned_paragraphs(
        "bhagavad_gita_arnold",
        BHAGAVAD_GITA_ARNOLD_PATH,
        "Bhagavad Gita",
        [(r"^CHAPTER\s+([IVXLCDM]+)\s*$", "Bhagavad Gita Chapter {}")],
    )


_TAO_CHAPTER_START = re.compile(r"^(?:Ch\.\s+)?(\d+)\.\s+1\.\s*(.*)$")


@lru_cache(maxsize=1)
def _load_tao_legge() -> list[JsonDict]:
    records: list[JsonDict] = []
    section = "Tao Teh King"
    paragraph: list[str] = []

    def flush() -> None:
        nonlocal paragraph
        text = " ".join(part.strip() for part in paragraph if part.strip())
        paragraph = []
        if len(text) > 24:
            records.append(_scripture_record("tao_legge", section, text))

    for raw in _gutenberg_body(TAO_LEGGE_PATH, "*** START"):
        line = raw.strip()
        match = _TAO_CHAPTER_START.match(line)
        if match:
            flush()
            section = f"Tao Teh King Chapter {int(match.group(1))}"
            if match.group(2):
                paragraph.append(match.group(2))
            continue
        paragraph.append(line)
    flush()
    return records


@lru_cache(maxsize=1)
def _load_analects_legge() -> list[JsonDict]:
    return _gutenberg_sectioned_paragraphs(
        "analects_legge",
        ANALECTS_LEGGE_PATH,
        "Analects",
        [
            (r"^BOOK\s+([IVXLCDM]+)\.\s*(.*)$", "Analects Book {}"),
            (r"^\s*CHAPTER\s+([IVXLCDM]+)\.\s*(.*)$", "Analects Chapter {}"),
        ],
    )


@lru_cache(maxsize=1)
def _load_scripture_corpus() -> JsonDict:
    web_records = [_scripture_record("web", verse["reference"], verse["text"]) for verse in _load_web_bible()["verses"]]
    passages = (
        web_records
        + _load_jps_tanakh()
        + _load_quran_rodwell()
        + _load_dhammapada_muller()
        + _load_bhagavad_gita_arnold()
        + _load_tao_legge()
        + _load_analects_legge()
    )
    counts: dict[str, int] = {}
    for passage in passages:
        counts[passage["collection"]] = counts.get(passage["collection"], 0) + 1
    collections = [{**item, "passage_count": counts.get(item["id"], 0)} for item in SCRIPTURE_COLLECTIONS]
    return {"collections": collections, "passages": passages}


def _roman_to_int(value: str) -> int:
    """Parse a classic subtractive roman numeral (I, V, X, L, C, D, M)."""
    numerals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for char in reversed(value.upper().strip()):
        current = numerals.get(char, 0)
        if current < previous:
            total -= current
        else:
            total += current
        previous = current
    return total


def _sura_display_name(reference: str) -> str:
    """Clean a Rodwell sura reference like ``SURA1 XCVI.–THICK BLOOD, OR CLOTS OF BLOOD [I.]``."""
    cleaned = re.sub(r"\[[^\]]*\]", "", str(reference))
    cleaned = re.sub(r"\s*\d+\s*$", "", cleaned)
    dash = re.search(r"[\u2013\u2014-]", cleaned)
    if not dash:
        return reference
    cleaned = re.sub(r"^[^A-Za-z]*", "", cleaned[dash.end() :])
    return cleaned.strip()


@lru_cache(maxsize=1)
def _reader_units() -> list[dict]:
    """Derive reading units from the scripture corpus, tagged per collection.

    Returns NEW dicts (``{**passage, "book": ..., "chapter": ...}``) so the
    cached ``_load_scripture_corpus()`` records are never mutated.
    """
    units: list[dict] = []
    quran_ordinals: dict[str, str] = {}
    current_analects_book: str | None = None
    for passage in _load_scripture_corpus()["passages"]:
        unit = {**passage}
        collection = unit["collection"]
        reference = unit["reference"]
        book: str | None = None
        chapter: str | None = None

        if collection in ("web", "jps1917"):
            match = re.match(r"^(.*?)\s+(\d+):(\d+)$", reference)
            if match:
                book = match.group(1)
                chapter = str(int(match.group(2)))
        elif collection == "quran_rodwell":
            book = "quran"
            ordinal = quran_ordinals.get(reference)
            if ordinal is None:
                ordinal = str(len(quran_ordinals) + 1)
                quran_ordinals[reference] = ordinal
            chapter = ordinal
        elif collection == "dhammapada_muller":
            book = "dhammapada"
            match = re.match(r"^Dhammapada\s+\d+\s+\u2014\s+(.*)$", reference)
            chapter = match.group(1) if match else "Dhammapada"
        elif collection == "bhagavad_gita_arnold":
            book = "gita"
            match = re.match(r"^Bhagavad Gita Chapter\s+([IVXLCDM]+)$", reference)
            if match:
                chapter = str(_roman_to_int(match.group(1)))
        elif collection == "tao_legge":
            book = "tao"
            match = re.match(r"^Tao Teh King Chapter\s+(\d+)$", reference)
            if match:
                chapter = match.group(1)
        elif collection == "analects_legge":
            book_match = re.match(r"^Analects Book\s+([IVXLCDM]+)$", reference)
            if book_match:
                current_analects_book = str(_roman_to_int(book_match.group(1)))
                book = current_analects_book
                chapter = "whole"
            else:
                chapter_match = re.match(r"^Analects Chapter\s+([IVXLCDM]+)$", reference)
                if chapter_match:
                    book = current_analects_book if current_analects_book is not None else "1"
                    chapter = str(_roman_to_int(chapter_match.group(1)))
                else:
                    book = None

        unit["book"] = book
        unit["chapter"] = chapter
        units.append(unit)
    return units


def _reader_book_label(collection: str, book_key: str) -> str:
    if collection in ("web", "jps1917"):
        return book_key
    return _collection_meta(collection).get("name", book_key)


def _reader_chapter_label(collection: str, chapter_key: str, reference: str) -> str:
    if collection in ("web", "jps1917"):
        return f"Chapter {chapter_key}"
    if collection == "quran_rodwell":
        return f"Sura {chapter_key} — {_sura_display_name(reference)}"
    if collection == "dhammapada_muller":
        return "Whole book" if chapter_key == "Dhammapada" else chapter_key
    if collection in ("bhagavad_gita_arnold", "tao_legge"):
        return f"Chapter {chapter_key}"
    if collection == "analects_legge":
        return "Whole book" if chapter_key == "whole" else f"Section {chapter_key}"
    return chapter_key


@lru_cache(maxsize=1)
def _scripture_toc() -> dict[str, JsonDict]:
    """Reading table of contents grouped per collection, in first-appearance order."""
    toc: dict[str, JsonDict] = {}
    for unit in _reader_units():
        collection = unit["collection"]
        book_key = unit.get("book")
        if book_key is None:
            continue
        entry = toc.get(collection)
        if entry is None:
            entry = {"collection": {**_collection_meta(collection), "id": collection}, "books": []}
            toc[collection] = entry
        book_node = next((book for book in entry["books"] if book["key"] == book_key), None)
        if book_node is None:
            book_node = {
                "key": book_key,
                "name": _reader_book_label(collection, book_key),
                "chapters": [],
                "chapter_index": {},
            }
            entry["books"].append(book_node)
        chapter_key = unit.get("chapter")
        if chapter_key is None:
            continue
        key = str(chapter_key)
        if key in book_node["chapter_index"]:
            book_node["chapter_index"][key]["count"] += 1
        else:
            chapter_node = {
                "key": key,
                "name": _reader_chapter_label(collection, key, unit["reference"]),
                "count": 0,
            }
            book_node["chapter_index"][key] = chapter_node
            book_node["chapters"].append(chapter_node)
    for entry in toc.values():
        for book_node in entry["books"]:
            book_node.pop("chapter_index", None)
    return toc


@lru_cache(maxsize=1)
def _load_encyclopedia_entries() -> list[JsonDict]:
    try:
        entries = json.loads(ENCYCLOPEDIA_PATH.read_text(encoding="utf-8"))
        if isinstance(entries, list):
            return cast(list[JsonDict], entries)
        return []
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        logger.exception("[Faith] Failed to load encyclopedia seed")
        return []


def _lookup_book_code(value: str) -> str | None:
    if not value:
        return None
    bible = _load_web_bible()
    key = value.strip().lower()
    return bible["aliases"].get(key) or bible["aliases"].get(key.replace(" ", ""))


def _serialize_book(book: JsonDict) -> JsonDict:
    return {
        "code": book["code"],
        "name": book["name"],
        "chapter_count": len(book["chapters"]),
        "chapters": book["chapters"],
    }


def _clamped_search_limit(default: int) -> int:
    try:
        requested = int(request.args.get("limit", str(default)))
    except (TypeError, ValueError):
        requested = default
    return min(max(requested, MIN_SEARCH_LIMIT), MAX_SEARCH_LIMIT)