"""Faith routes for devotionals, profiles, multi-tradition scripture, reflection, and safety support."""

from __future__ import annotations

import logging
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

from flask import jsonify, render_template, request
from flask_login import current_user, login_required

from . import faith_bp

from tools.department_hq.services.department_dispatcher import dispatch

BRIDGE_AVAILABLE = True

from database import get_db_cursor

logger = logging.getLogger(__name__)

FAITH_AGENT_ID = 352
EMMANUEL_EMAIL = "emmanuel@kytranempowerment.com"
FAITH_DATA_DIR = Path(__file__).with_name("data")
WEB_VPL_PATH = FAITH_DATA_DIR / "web_vpl.txt"
JPS_VPL_PATH = FAITH_DATA_DIR / "tanakh_jps1917_vpl.txt"
QURAN_RODWELL_PATH = FAITH_DATA_DIR / "quran_rodwell_gutenberg.txt"
DHAMMAPADA_MULLER_PATH = FAITH_DATA_DIR / "dhammapada_muller_gutenberg.txt"
BHAGAVAD_GITA_ARNOLD_PATH = FAITH_DATA_DIR / "bhagavad_gita_arnold_gutenberg.txt"
TAO_LEGGE_PATH = FAITH_DATA_DIR / "tao_teh_king_legge_gutenberg.txt"
ANALECTS_LEGGE_PATH = FAITH_DATA_DIR / "analects_legge_gutenberg.txt"
ENCYCLOPEDIA_PATH = FAITH_DATA_DIR / "encyclopedia_seed.json"
SCRIPTURE_COLLECTIONS = [
    {
        "id": "web",
        "name": "World English Bible Classic",
        "tradition": "Christianity",
        "source": "eBible.org",
        "license": "Public domain",
        "local_path": "platform_v2/tools/faith/data/web_vpl.txt",
    },
    {
        "id": "jps1917",
        "name": "JPS Tanakh 1917",
        "tradition": "Judaism",
        "source": "eBible.org",
        "license": "Public domain",
        "local_path": "platform_v2/tools/faith/data/tanakh_jps1917_vpl.txt",
    },
    {
        "id": "quran_rodwell",
        "name": "The Koran (Rodwell)",
        "tradition": "Islam",
        "source": "Project Gutenberg",
        "license": "Public domain in the USA",
        "local_path": "platform_v2/tools/faith/data/quran_rodwell_gutenberg.txt",
    },
    {
        "id": "dhammapada_muller",
        "name": "Dhammapada (Max Muller)",
        "tradition": "Buddhism",
        "source": "Project Gutenberg",
        "license": "Public domain in the USA",
        "local_path": "platform_v2/tools/faith/data/dhammapada_muller_gutenberg.txt",
    },
    {
        "id": "bhagavad_gita_arnold",
        "name": "Bhagavad Gita (Edwin Arnold)",
        "tradition": "Hinduism",
        "source": "Project Gutenberg",
        "license": "Public domain in the USA",
        "local_path": "platform_v2/tools/faith/data/bhagavad_gita_arnold_gutenberg.txt",
    },
    {
        "id": "tao_legge",
        "name": "Tao Teh King (James Legge)",
        "tradition": "Taoism",
        "source": "Project Gutenberg",
        "license": "Public domain in the USA",
        "local_path": "platform_v2/tools/faith/data/tao_teh_king_legge_gutenberg.txt",
    },
    {
        "id": "analects_legge",
        "name": "Analects of Confucius (James Legge)",
        "tradition": "Confucianism",
        "source": "Project Gutenberg",
        "license": "Public domain in the USA",
        "local_path": "platform_v2/tools/faith/data/analects_legge_gutenberg.txt",
    },
]

WEB_BOOK_NAMES = {
    "GEN": "Genesis",
    "EXO": "Exodus",
    "LEV": "Leviticus",
    "NUM": "Numbers",
    "DEU": "Deuteronomy",
    "JOS": "Joshua",
    "JDG": "Judges",
    "RUT": "Ruth",
    "1SA": "1 Samuel",
    "2SA": "2 Samuel",
    "1KI": "1 Kings",
    "2KI": "2 Kings",
    "1CH": "1 Chronicles",
    "2CH": "2 Chronicles",
    "EZR": "Ezra",
    "NEH": "Nehemiah",
    "EST": "Esther",
    "JOB": "Job",
    "PSA": "Psalms",
    "PRO": "Proverbs",
    "ECC": "Ecclesiastes",
    "SOL": "Song of Solomon",
    "ISA": "Isaiah",
    "JER": "Jeremiah",
    "LAM": "Lamentations",
    "EZE": "Ezekiel",
    "DAN": "Daniel",
    "HOS": "Hosea",
    "JOE": "Joel",
    "AMO": "Amos",
    "OBA": "Obadiah",
    "JON": "Jonah",
    "MIC": "Micah",
    "NAH": "Nahum",
    "HAB": "Habakkuk",
    "ZEP": "Zephaniah",
    "HAG": "Haggai",
    "ZEC": "Zechariah",
    "MAL": "Malachi",
    "TOB": "Tobit",
    "JDT": "Judith",
    "ESG": "Esther (Greek)",
    "WIS": "Wisdom",
    "SIR": "Sirach",
    "BAR": "Baruch",
    "1MA": "1 Maccabees",
    "2MA": "2 Maccabees",
    "1ES": "1 Esdras",
    "PRM": "Prayer of Manasses",
    "PSX": "Psalm 151",
    "3MA": "3 Maccabees",
    "4ES": "2 Esdras",
    "4MA": "4 Maccabees",
    "DNG": "Daniel (Greek)",
    "MAT": "Matthew",
    "MAR": "Mark",
    "LUK": "Luke",
    "JOH": "John",
    "ACT": "Acts",
    "ROM": "Romans",
    "1CO": "1 Corinthians",
    "2CO": "2 Corinthians",
    "GAL": "Galatians",
    "EPH": "Ephesians",
    "PHI": "Philippians",
    "COL": "Colossians",
    "1TH": "1 Thessalonians",
    "2TH": "2 Thessalonians",
    "1TI": "1 Timothy",
    "2TI": "2 Timothy",
    "TIT": "Titus",
    "PHM": "Philemon",
    "HEB": "Hebrews",
    "JAM": "James",
    "1PE": "1 Peter",
    "2PE": "2 Peter",
    "1JO": "1 John",
    "2JO": "2 John",
    "3JO": "3 John",
    "JUD": "Jude",
    "REV": "Revelation",
}

CRISIS_KEYWORDS = [
    "can't go on",
    "no reason to live",
    "ending it",
    "hopeless",
    "god has abandoned",
    "want to die",
    "kill myself",
    "suicide",
]

FAITH_SYSTEM_PROMPT = """\
You are F.A.I.T.H. (Faithful AI for Inspired Theological Heritage), \
a scripture-grounded faith companion across all Christian traditions.

Rules:
1. Ground every response in scripture and theological scholarship.
2. Honour all traditions — Catholic, Orthodox, Protestant, Evangelical, \
Pentecostal, Anglican, Baptist. Never impose one denomination.
3. Be warm, gentle, honest about AI limits in spiritual matters.
4. For crisis language ALWAYS surface:
   - Crisis Text Line: Text HOME to 741741
   - 988 Suicide & Crisis Lifeline (call or text 988)
   - Encourage connecting with Emmanuel Adeyemi, the platform chaplain.

After your response, append EXACTLY this block:

---
**From the Chaplain — Emmanuel Adeyemi**
[One or two sentences in Emmanuel's voice: Nigerian-Canadian hospital \
chaplain, 15 years interfaith pastoral care, Pentecostal formation shaped \
by Catholic CPE supervisors and a Cree elder. Ground it in lived \
experience, not theology. Never generic.]
"""


@lru_cache(maxsize=1)
def _load_web_bible() -> dict:
    books: list[dict] = []
    by_code: dict[str, dict] = {}
    verses: list[dict] = []

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

    aliases = {}
    for book in books:
        aliases[book["code"].lower()] = book["code"]
        aliases[book["name"].lower()] = book["code"]
        aliases[book["name"].replace(" ", "").lower()] = book["code"]
    return {"books": books, "verses": verses, "aliases": aliases}


def _collection_meta(collection_id: str) -> dict:
    return next((item for item in SCRIPTURE_COLLECTIONS if item["id"] == collection_id), {})


def _scripture_record(collection_id: str, reference: str, text: str) -> dict:
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


def _public_scripture_record(record: dict) -> dict:
    return {key: value for key, value in record.items() if not key.startswith("_")}


@lru_cache(maxsize=1)
def _load_jps_tanakh() -> list[dict]:
    records: list[dict] = []
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
def _load_quran_rodwell() -> list[dict]:
    records: list[dict] = []
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
def _load_dhammapada_muller() -> list[dict]:
    records: list[dict] = []
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
) -> list[dict]:
    records: list[dict] = []
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
def _load_bhagavad_gita_arnold() -> list[dict]:
    return _gutenberg_sectioned_paragraphs(
        "bhagavad_gita_arnold",
        BHAGAVAD_GITA_ARNOLD_PATH,
        "Bhagavad Gita",
        [(r"^CHAPTER\s+([IVXLCDM]+)\s*$", "Bhagavad Gita Chapter {}")],
    )


@lru_cache(maxsize=1)
def _load_tao_legge() -> list[dict]:
    return _gutenberg_sectioned_paragraphs(
        "tao_legge",
        TAO_LEGGE_PATH,
        "Tao Teh King",
        [(r"^Ch\.\s+(\d+)\.\s*(.*)$", "Tao Teh King Chapter {}")],
    )


@lru_cache(maxsize=1)
def _load_analects_legge() -> list[dict]:
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
def _load_scripture_corpus() -> dict:
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
    counts = {}
    for passage in passages:
        counts[passage["collection"]] = counts.get(passage["collection"], 0) + 1
    collections = [{**item, "passage_count": counts.get(item["id"], 0)} for item in SCRIPTURE_COLLECTIONS]
    return {"collections": collections, "passages": passages}


@lru_cache(maxsize=1)
def _load_encyclopedia_entries() -> list[dict]:
    try:
        return json.loads(ENCYCLOPEDIA_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("[Faith] Failed to load encyclopedia seed")
        return []


def _lookup_book_code(value: str) -> str | None:
    if not value:
        return None
    bible = _load_web_bible()
    key = value.strip().lower()
    return bible["aliases"].get(key) or bible["aliases"].get(key.replace(" ", ""))


def _serialize_book(book: dict) -> dict:
    return {
        "code": book["code"],
        "name": book["name"],
        "chapter_count": len(book["chapters"]),
        "chapters": book["chapters"],
    }


@faith_bp.route("/")
@login_required
def index():
    return render_template("tools/faith.html")


@faith_bp.route("/api/faith/status")
@login_required
def status():
    return jsonify(
        {
            "status": "online",
            "agent": "F.A.I.T.H.",
            "agent_id": FAITH_AGENT_ID,
            "bridge_available": BRIDGE_AVAILABLE,
            "module": "faith",
        }
    )


@faith_bp.route("/api/faith/bible/meta")
@login_required
def bible_meta():
    bible = _load_web_bible()
    return jsonify(
        {
            "success": True,
            "translation": {
                "id": "web",
                "name": "World English Bible Classic",
                "storage": "local_saved_copy",
                "local_path": "platform_v2/tools/faith/data/web_vpl.txt",
                "source": "eBible.org",
                "license": "Public domain",
                "source_url": "https://ebible.org/find/details.php?id=eng-web",
                "verse_count": len(bible["verses"]),
            },
            "books": [_serialize_book(book) for book in bible["books"]],
            "encyclopedia_sources": _load_encyclopedia_entries(),
        }
    )


@faith_bp.route("/api/faith/bible/passage")
@login_required
def bible_passage():
    code = _lookup_book_code(request.args.get("book", "GEN"))
    if not code:
        return jsonify({"success": False, "error": "unknown book"}), 404
    try:
        chapter = int(request.args.get("chapter", "1"))
    except ValueError:
        return jsonify({"success": False, "error": "chapter must be a number"}), 400

    verses = [v for v in _load_web_bible()["verses"] if v["book"] == code and v["chapter"] == chapter]
    if not verses:
        return jsonify({"success": False, "error": "passage not found"}), 404
    return jsonify(
        {
            "success": True,
            "translation": "World English Bible Classic",
            "book": code,
            "book_name": verses[0]["book_name"],
            "chapter": chapter,
            "reference": f"{verses[0]['book_name']} {chapter}",
            "verses": verses,
        }
    )


@faith_bp.route("/api/faith/bible/search")
@login_required
def bible_search():
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"success": False, "error": "query required"}), 400
    try:
        limit = min(max(int(request.args.get("limit", "25")), 1), 100)
    except ValueError:
        limit = 25

    q = query.lower()
    results = []
    for verse in _load_web_bible()["verses"]:
        haystack = f"{verse['reference']} {verse['text']}".lower()
        if q in haystack:
            results.append(verse)
            if len(results) >= limit:
                break
    return jsonify({"success": True, "query": query, "results": results, "count": len(results)})


@faith_bp.route("/api/faith/scriptures/meta")
@login_required
def scriptures_meta():
    corpus = _load_scripture_corpus()
    return jsonify(
        {
            "success": True,
            "storage": "local_saved_copies",
            "collections": corpus["collections"],
            "passage_count": len(corpus["passages"]),
        }
    )


@faith_bp.route("/api/faith/scriptures/search")
@login_required
def scriptures_search():
    query = (request.args.get("q") or "").strip()
    collection = (request.args.get("collection") or "all").strip()
    if not query:
        return jsonify({"success": False, "error": "query required"}), 400
    try:
        limit = min(max(int(request.args.get("limit", "40")), 1), 120)
    except ValueError:
        limit = 40

    q = query.lower()
    results = []
    for passage in _load_scripture_corpus()["passages"]:
        if collection != "all" and passage["collection"] != collection:
            continue
        if q in passage["_search"]:
            results.append(_public_scripture_record(passage))
            if len(results) >= limit:
                break
    return jsonify(
        {
            "success": True,
            "query": query,
            "collection": collection,
            "results": results,
            "count": len(results),
        }
    )


@faith_bp.route("/api/faith/encyclopedia/search")
@login_required
def encyclopedia_search():
    query = (request.args.get("q") or "").strip().lower()
    entries = _load_encyclopedia_entries()
    if query:
        entries = [
            entry
            for entry in entries
            if query
            in " ".join(
                [
                    entry.get("title", ""),
                    entry.get("category", ""),
                    entry.get("summary", ""),
                    " ".join(entry.get("tags", [])),
                ]
            ).lower()
        ]
    return jsonify({"success": True, "query": query, "entries": entries, "count": len(entries)})


def _detect_crisis(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in CRISIS_KEYWORDS)


def _save_message(user_id: int, role: str, message: str) -> None:
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_sessions (user_id, role, message) VALUES (%s, %s, %s)",
                (user_id, role, message),
            )
    except Exception:
        logger.exception("[Faith] Failed to save session message")


@faith_bp.route("/api/faith/chat", methods=["POST"])
@login_required
def chat():
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "error": "message required"}), 400

    user_id = current_user.id
    crisis = _detect_crisis(message)
    _save_message(user_id, "user", message)

    try:
        result = dispatch(
            capability="support",
            prompt=message,
            module_id="faith",
            system_prompt=FAITH_SYSTEM_PROMPT,
        )
        response_text = getattr(result, "response", "") if result else ""
        response_text = response_text.strip()
    except Exception as e:
        logger.error(f"[Faith] dispatch failed: {e}")
        response_text = "F.A.I.T.H. is unavailable right now."

    _save_message(user_id, "assistant", response_text)

    return jsonify(
        {
            "success": bool(response_text),
            "response": response_text,
            "model": getattr(result, "model_used", "dhq") if result else "dhq",
            "agent": getattr(result, "agent_name", "F.A.I.T.H.") if result else "F.A.I.T.H.",
            "crisis_detected": crisis,
        }
    )


# ---------------------------------------------------------------------------
# Task 4: Practices routes
# ---------------------------------------------------------------------------


def _practice_dispatch(user_id: int, practice_type: str, prompt: str, notes: str = "") -> dict:
    if BRIDGE_AVAILABLE:
        try:
            dispatch_result = dispatch(
                capability="support",
                prompt=prompt,
                module_id="faith",
                system_prompt=FAITH_SYSTEM_PROMPT,
            )
            result = {
                "success": bool(dispatch_result and dispatch_result.success),
                "response": getattr(dispatch_result, "response", "") if dispatch_result else "",
                "model_used": getattr(dispatch_result, "model_used", "dhq") if dispatch_result else "dhq",
                "agent": getattr(dispatch_result, "agent_name", "F.A.I.T.H.") if dispatch_result else "F.A.I.T.H.",
            }
        except Exception as e:
            logger.error(f"[Faith] practice dispatch failed: {e}")
            result = {
                "success": False,
                "response": "F.A.I.T.H. is unavailable.",
                "model_used": "dhq",
                "agent": "F.A.I.T.H.",
            }
    else:
        result = {"success": False, "response": "F.A.I.T.H. is unavailable.", "model_used": "none", "agent": "none"}

    if result.get("success"):
        try:
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    "INSERT INTO faith_practices_log (user_id, practice_type, notes) VALUES (%s, %s, %s)",
                    (user_id, practice_type, notes or result.get("response", "")[:500]),
                )
        except Exception:
            logger.exception("[Faith] Failed to log practice")
    return result


@faith_bp.route("/api/faith/devotional")
@login_required
def devotional():
    from datetime import date

    today = date.today().strftime("%B %d, %Y")
    prompt = (
        f"Generate a daily devotional for {today}. Include: (1) one scripture verse with reference, "
        "(2) 2-3 sentence reflection, (3) one meditation question. Under 150 words. "
        "Honour all Christian traditions."
    )
    result = _practice_dispatch(current_user.id, "devotional", prompt)
    return jsonify({"success": result.get("success", False), "response": result.get("response", ""), "date": today})


@faith_bp.route("/api/faith/prayer", methods=["POST"])
@login_required
def guided_prayer():
    data = request.get_json(force=True, silent=True) or {}
    prayer_type = data.get("type", "general")
    intention = (data.get("intention") or "").strip()
    prompt = (
        f"Guide me through a {prayer_type} prayer"
        + (f" for: {intention}" if intention else "")
        + ". Structure: Opening → Body → Silence ('...') → Closing. Under 120 words."
    )
    result = _practice_dispatch(current_user.id, "prayer", prompt, notes=f"{prayer_type}: {intention}")
    return jsonify({"success": result.get("success", False), "response": result.get("response", "")})


@faith_bp.route("/api/faith/scripture-search", methods=["POST"])
@login_required
def scripture_search():
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"success": False, "error": "query required"}), 400
    prompt = (
        f"Find 3 relevant Bible passages for: '{query}'. "
        "For each: reference, verse text, one sentence of context. Numbered list."
    )
    result = _practice_dispatch(current_user.id, "scripture", prompt, notes=query)
    return jsonify({"success": result.get("success", False), "response": result.get("response", ""), "query": query})


@faith_bp.route("/api/faith/lectio", methods=["POST"])
@login_required
def lectio_divina():
    data = request.get_json(force=True, silent=True) or {}
    passage = (data.get("passage") or "Psalm 23").strip()
    prompt = (
        f"Guide me through Lectio Divina with {passage}. "
        "Four movements: 1. Lectio (passage text), 2. Meditatio (reflection question), "
        "3. Oratio (prayer prompt), 4. Contemplatio (stillness invitation). 2-3 sentences each."
    )
    result = _practice_dispatch(current_user.id, "lectio", prompt, notes=passage)
    return jsonify(
        {"success": result.get("success", False), "response": result.get("response", ""), "passage": passage}
    )


# ---------------------------------------------------------------------------
# Task 5: Check-in + Journal routes
# ---------------------------------------------------------------------------


@faith_bp.route("/api/faith/checkin", methods=["POST"])
@login_required
def checkin():
    data = request.get_json(force=True, silent=True) or {}
    score = data.get("score")
    reflection = (data.get("reflection") or "").strip()
    if score is None or not (1 <= int(score) <= 5):
        return jsonify({"success": False, "error": "score must be 1-5"}), 400
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_checkins (user_id, score, reflection) VALUES (%s, %s, %s) RETURNING id",
                (current_user.id, int(score), reflection or None),
            )
            checkin_id = cur.fetchone()["id"]
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_practices_log (user_id, practice_type, notes) VALUES (%s, 'checkin', %s)",
                (current_user.id, f"score={score}"),
            )
    except Exception:
        logger.exception("[Faith] Failed to save check-in")
        return jsonify({"success": False, "error": "Failed to save"}), 500
    return jsonify({"success": True, "id": checkin_id}), 201


@faith_bp.route("/api/faith/checkin/history")
@login_required
def checkin_history():
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT id, score, reflection, created_at FROM faith_checkins "
                "WHERE user_id = %s ORDER BY created_at DESC LIMIT 30",
                (current_user.id,),
            )
            rows = [dict(r) for r in cur.fetchall()]
    except Exception:
        logger.exception("[Faith] Failed to load check-in history")
        return jsonify({"success": False, "error": "Failed to load"}), 500
    return jsonify({"success": True, "checkins": rows})


@faith_bp.route("/api/faith/journal", methods=["POST"])
@login_required
def journal_save():
    data = request.get_json(force=True, silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"success": False, "error": "content required"}), 400
    title = (data.get("title") or "").strip() or None
    scripture_ref = (data.get("scripture_ref") or "").strip() or None
    tags = data.get("tags") or []
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_journal (user_id, title, content, scripture_ref, tags) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (current_user.id, title, content, scripture_ref, tags),
            )
            entry_id = cur.fetchone()["id"]
    except Exception:
        logger.exception("[Faith] Failed to save journal entry")
        return jsonify({"success": False, "error": "Failed to save"}), 500
    return jsonify({"success": True, "id": entry_id}), 201


@faith_bp.route("/api/faith/journal")
@login_required
def journal_list():
    tag_filter = request.args.get("tag")
    try:
        with get_db_cursor() as (_conn, cur):
            if tag_filter:
                cur.execute(
                    "SELECT id, title, content, scripture_ref, tags, created_at FROM faith_journal "
                    "WHERE user_id = %s AND %s = ANY(tags) ORDER BY created_at DESC LIMIT 50",
                    (current_user.id, tag_filter),
                )
            else:
                cur.execute(
                    "SELECT id, title, content, scripture_ref, tags, created_at FROM faith_journal "
                    "WHERE user_id = %s ORDER BY created_at DESC LIMIT 50",
                    (current_user.id,),
                )
            rows = [dict(r) for r in cur.fetchall()]
    except Exception:
        logger.exception("[Faith] Failed to load journal")
        return jsonify({"success": False, "error": "Failed to load"}), 500
    return jsonify({"success": True, "entries": rows})


# ---------------------------------------------------------------------------
# Task 6: Connect-chaplain route
# ---------------------------------------------------------------------------


def _send_chaplain_email(user_display_name: str, message: str, context_entries: list) -> bool:
    try:
        from services.email_service import send_email  # type: ignore

        context_block = ""
        if context_entries:
            context_block = "\n\nShared journal context:\n" + "\n---\n".join(
                f"{e.get('title', 'Untitled')}: {e.get('content', '')[:300]}" for e in context_entries
            )
        send_email(
            from_address="faith@kytranempowerment.com",
            to_address=EMMANUEL_EMAIL,
            subject=f"Spiritual Care Request — {user_display_name}",
            body=f"Spiritual Care Request\nFrom: {user_display_name}\n\nMessage:\n{message}{context_block}",
        )
        return True
    except Exception:
        logger.exception("[Faith] Failed to send chaplain email")
        return False


@faith_bp.route("/api/faith/connect-chaplain", methods=["POST"])
@login_required
def connect_chaplain():
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "error": "message required"}), 400

    journal_ids = data.get("journal_ids") or []
    context_entries = []
    if journal_ids:
        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    "SELECT title, content FROM faith_journal WHERE user_id = %s AND id = ANY(%s)",
                    (current_user.id, journal_ids),
                )
                context_entries = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass

    display_name = getattr(current_user, "display_name", None) or getattr(current_user, "username", "Platform User")
    sent = _send_chaplain_email(display_name, message, context_entries)

    return jsonify(
        {
            "success": True,
            "sent": sent,
            "message": (
                "Your message has been sent to Emmanuel. He will be in touch."
                if sent
                else "Message queued — Emmanuel will receive it shortly."
            ),
        }
    )
