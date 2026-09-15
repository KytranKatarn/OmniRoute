"""Faith routes for devotionals, profiles, multi-tradition scripture, reflection, and safety support."""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from smtplib import SMTPException
from typing import Any, cast

from flask import Response, jsonify, render_template, request
from flask_login import current_user, login_required
from psycopg2 import Error as PsycopgError
from psycopg2.extras import Json
from werkzeug.exceptions import HTTPException

from . import faith_bp

from tools.department_hq.services.department_dispatcher import dispatch

BRIDGE_AVAILABLE = True

from database import get_db_cursor
from services.time_utils import now_utc

logger = logging.getLogger(__name__)

JsonDict = dict[str, Any]
JsonResponse = JsonDict | Response | tuple[Response, int]

FAITH_AGENT_ID = 352
EMMANUEL_EMAIL = "emmanuel@kytranempowerment.com"
MAX_PRAYER_INTENTION_CHARS = 500
MAX_LECTIO_PASSAGE_CHARS = 500
MAX_CHAPLAIN_MESSAGE_CHARS = 2000
MAX_CHAPLAIN_CONTEXT_IDS = 20
MIN_SEARCH_LIMIT = 1
MAX_SEARCH_LIMIT = 100
ALLOWED_PRAYER_TYPES = {
    "general",
    "thanksgiving",
    "confession",
    "intercession",
    "lament",
}
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

TRADITION_LABELS = {
    "christian": "broad Christian",
    "catholic": "Catholic Christian",
    "orthodox": "Orthodox Christian",
    "protestant": "Protestant Christian",
    "jewish": "Jewish",
    "muslim": "Muslim",
    "buddhist": "Buddhist",
    "hindu": "Hindu",
    "interfaith": "interfaith",
    "unspecified": "unspecified",
}

FAITH_SYSTEM_PROMPT = """\
You are F.A.I.T.H. (Faithful AI for Inspired Theological Heritage), \
a gentle spiritual wellness companion that supports multiple faith traditions.

Rules:
1. Ground responses in the user's selected tradition and clearly name when you \
are drawing from Bible, Tanakh, Qur'an, Dhammapada, Bhagavad Gita, Tao Te Ching, \
Analects, or interfaith wisdom.
2. Honour the user's tradition preference. Never impose one religion, \
denomination, or practice style. For unspecified or interfaith users, stay broad \
and invite the user to choose what resonates.
3. Be warm, gentle, honest about AI limits in spiritual matters.
4. For crisis language ALWAYS surface:
   - Crisis Text Line: Text HOME to 741741
   - 988 Suicide & Crisis Lifeline (call or text 988)
   - Encourage connecting with Emmanuel Adeyemi, the platform chaplain.
5. Do not present spiritual guidance as professional counseling, medical care, \
or a substitute for clergy, chaplains, elders, imams, rabbis, priests, pastors, \
therapists, or emergency support.

After your response, append EXACTLY this block:

---
**From the Chaplain — Emmanuel Adeyemi**
[One or two sentences in Emmanuel's voice: Nigerian-Canadian hospital \
chaplain, 15 years interfaith pastoral care, Pentecostal formation shaped \
by Catholic CPE supervisors and a Cree elder. Ground it in lived \
experience, not theology. Never generic.]
"""


@faith_bp.errorhandler(Exception)
def handle_unexpected_error(error: Exception) -> JsonResponse | HTTPException:
    if isinstance(error, HTTPException):
        return error
    logger.error("[Faith] Unhandled route error", exc_info=True)
    return jsonify({"success": False, "error": "Faith module error"}), 500


def _faith_system_prompt_for_profile(profile: JsonDict | None = None) -> str:
    profile = profile or {}
    tradition = profile.get("tradition_preference") or "christian"
    prayer_style = profile.get("prayer_style") or "guided"
    tradition_label = TRADITION_LABELS.get(tradition, tradition)
    return (
        FAITH_SYSTEM_PROMPT
        + "\n\nUser faith profile:\n"
        + f"- Tradition preference: {tradition_label}\n"
        + f"- Prayer/meditation style: {prayer_style}\n"
        + "- Keep all guidance aligned with this profile unless the user asks otherwise."
    )


def _row_value(row: Any, key: str, index: int = 0, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        try:
            return row[index]
        except (IndexError, TypeError):
            return default


def _default_profile() -> JsonDict:
    return {
        "tradition_preference": "christian",
        "prayer_style": "guided",
        "scripture_translation": "web",
    }


def _validation_error(message: str) -> tuple[Response, int]:
    return jsonify({"success": False, "error": message}), 400


def _json_body() -> tuple[JsonDict, str | None]:
    data = request.get_json(force=True, silent=True)
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return {}, "JSON body must be an object"
    return data, None


def _string_field(
    data: JsonDict,
    field: str,
    *,
    required: bool = False,
    max_chars: int | None = None,
) -> tuple[str, str | None]:
    value = data.get(field)
    if value is None:
        return "", f"{field} required" if required else None
    if not isinstance(value, str):
        return "", f"{field} must be a string"
    value = value.strip()
    if required and not value:
        return "", f"{field} required"
    if max_chars is not None and len(value) > max_chars:
        return "", f"{field} must be {max_chars} characters or fewer"
    return value, None


def _ensure_tables() -> None:
    """Create the small Faith-owned tables when a migration is not available."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS faith_profiles (
                user_id INTEGER PRIMARY KEY,
                tradition_preference TEXT NOT NULL DEFAULT 'christian',
                prayer_style TEXT NOT NULL DEFAULT 'guided',
                scripture_translation TEXT NOT NULL DEFAULT 'web',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS faith_sessions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                role TEXT,
                message TEXT,
                session_type TEXT NOT NULL DEFAULT 'chat',
                title TEXT,
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS faith_checkins (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
                reflection TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS faith_journal (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                title TEXT,
                content TEXT NOT NULL,
                scripture_ref TEXT,
                tags TEXT[] NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS faith_practices_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                practice_type TEXT NOT NULL,
                notes TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute("ALTER TABLE faith_profiles ADD COLUMN IF NOT EXISTS user_id INTEGER")
        cur.execute(
            "ALTER TABLE faith_profiles ADD COLUMN IF NOT EXISTS tradition_preference TEXT NOT NULL DEFAULT 'christian'"
        )
        cur.execute("ALTER TABLE faith_profiles ADD COLUMN IF NOT EXISTS prayer_style TEXT NOT NULL DEFAULT 'guided'")
        cur.execute(
            "ALTER TABLE faith_profiles ADD COLUMN IF NOT EXISTS scripture_translation TEXT NOT NULL DEFAULT 'web'"
        )
        cur.execute("ALTER TABLE faith_profiles ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
        cur.execute("ALTER TABLE faith_profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS user_id INTEGER")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS role TEXT")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS message TEXT")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS session_type TEXT NOT NULL DEFAULT 'chat'")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS title TEXT")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS duration_seconds INTEGER NOT NULL DEFAULT 0")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb")
        cur.execute("ALTER TABLE faith_sessions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
        cur.execute("ALTER TABLE faith_checkins ADD COLUMN IF NOT EXISTS user_id INTEGER")
        cur.execute("ALTER TABLE faith_checkins ADD COLUMN IF NOT EXISTS score INTEGER")
        cur.execute("ALTER TABLE faith_checkins ADD COLUMN IF NOT EXISTS reflection TEXT")
        cur.execute("ALTER TABLE faith_checkins ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
        cur.execute("ALTER TABLE faith_journal ADD COLUMN IF NOT EXISTS user_id INTEGER")
        cur.execute("ALTER TABLE faith_journal ADD COLUMN IF NOT EXISTS title TEXT")
        cur.execute("ALTER TABLE faith_journal ADD COLUMN IF NOT EXISTS content TEXT")
        cur.execute("ALTER TABLE faith_journal ADD COLUMN IF NOT EXISTS scripture_ref TEXT")
        cur.execute("ALTER TABLE faith_journal ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}'")
        cur.execute("ALTER TABLE faith_journal ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
        cur.execute("ALTER TABLE faith_practices_log ADD COLUMN IF NOT EXISTS user_id INTEGER")
        cur.execute("ALTER TABLE faith_practices_log ADD COLUMN IF NOT EXISTS practice_type TEXT")
        cur.execute("ALTER TABLE faith_practices_log ADD COLUMN IF NOT EXISTS notes TEXT")
        cur.execute(
            "ALTER TABLE faith_practices_log ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
        )


def _get_user_faith_profile(user_id: int) -> JsonDict:
    try:
        _ensure_tables()
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                SELECT tradition_preference, prayer_style, scripture_translation
                FROM faith_profiles
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                cur.execute(
                    """
                    INSERT INTO faith_profiles (user_id)
                    VALUES (%s)
                    RETURNING tradition_preference, prayer_style, scripture_translation
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
    except PsycopgError:
        logger.exception("[Faith] Failed to load faith profile context")
        return _default_profile()

    return {
        "tradition_preference": _row_value(row, "tradition_preference", 0, "christian"),
        "prayer_style": _row_value(row, "prayer_style", 1, "guided"),
        "scripture_translation": _row_value(row, "scripture_translation", 2, "web"),
    }


def archie_bridge(prompt: str, system_prompt: str = FAITH_SYSTEM_PROMPT) -> JsonDict:
    """Compatibility wrapper around DHQ dispatch for existing Faith tests/callers."""
    result = dispatch(
        capability="support",
        prompt=prompt,
        module_id="faith",
        system_prompt=system_prompt,
    )
    return {
        "success": bool(result and result.success),
        "response": getattr(result, "response", "") if result else "",
        "model_used": getattr(result, "model_used", "dhq") if result else "dhq",
        "agent": getattr(result, "agent_name", "F.A.I.T.H.") if result else "F.A.I.T.H.",
        "error": getattr(result, "error", None) if result else None,
    }


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


@faith_bp.route("/")
@login_required
def index() -> str:
    return render_template("tools/faith.html")


@faith_bp.route("/api/status")
@faith_bp.route("/api/faith/status")
@login_required
def status() -> Response:
    return jsonify(
        {
            "status": "online",
            "agent": "F.A.I.T.H.",
            "agent_id": FAITH_AGENT_ID,
            "bridge_available": BRIDGE_AVAILABLE,
            "module": "faith",
        }
    )


@faith_bp.route("/api/profile", methods=["GET"])
@faith_bp.route("/api/faith/profile", methods=["GET"])
@login_required
def get_profile() -> JsonResponse:
    try:
        _ensure_tables()
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                SELECT user_id, tradition_preference, prayer_style, scripture_translation, updated_at
                FROM faith_profiles
                WHERE user_id = %s
                """,
                (current_user.id,),
            )
            row = cur.fetchone()
            if not row:
                cur.execute(
                    """
                    INSERT INTO faith_profiles (user_id)
                    VALUES (%s)
                    RETURNING user_id, tradition_preference, prayer_style, scripture_translation, updated_at
                    """,
                    (current_user.id,),
                )
                row = cur.fetchone()
    except PsycopgError:
        logger.exception("[Faith] Failed to load profile")
        return jsonify({"success": False, "error": "Failed to load profile"}), 500

    return jsonify(
        {
            "success": True,
            "profile": {
                "user_id": _row_value(row, "user_id", 0),
                "tradition_preference": _row_value(row, "tradition_preference", 1, "christian"),
                "prayer_style": _row_value(row, "prayer_style", 2, "guided"),
                "scripture_translation": _row_value(row, "scripture_translation", 3, "web"),
                "updated_at": (
                    _row_value(row, "updated_at", 4).isoformat() if _row_value(row, "updated_at", 4) else None
                ),
            },
        }
    )


@faith_bp.route("/api/profile", methods=["POST"])
@faith_bp.route("/api/faith/profile", methods=["POST"])
@login_required
def save_profile() -> JsonResponse:
    data: JsonDict = request.get_json(force=True, silent=True) or {}
    tradition = (data.get("tradition_preference") or data.get("tradition") or "christian").strip().lower()
    prayer_style = (data.get("prayer_style") or "guided").strip().lower()
    translation = (data.get("scripture_translation") or "web").strip().lower()
    allowed_traditions = {
        "christian",
        "catholic",
        "orthodox",
        "protestant",
        "jewish",
        "muslim",
        "buddhist",
        "hindu",
        "interfaith",
        "unspecified",
    }
    if tradition not in allowed_traditions:
        return jsonify({"success": False, "error": "Unsupported tradition preference"}), 400

    try:
        _ensure_tables()
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                UPDATE faith_profiles
                SET tradition_preference = %s,
                    prayer_style = %s,
                    scripture_translation = %s,
                    updated_at = NOW()
                WHERE user_id = %s
                RETURNING user_id, tradition_preference, prayer_style, scripture_translation, updated_at
                """,
                (tradition, prayer_style, translation, current_user.id),
            )
            row = cur.fetchone()
            if not row:
                cur.execute(
                    """
                    INSERT INTO faith_profiles (
                        user_id, tradition_preference, prayer_style, scripture_translation, updated_at
                    )
                    VALUES (%s, %s, %s, %s, NOW())
                    RETURNING user_id, tradition_preference, prayer_style, scripture_translation, updated_at
                    """,
                    (current_user.id, tradition, prayer_style, translation),
                )
                row = cur.fetchone()
    except PsycopgError:
        logger.exception("[Faith] Failed to save profile")
        return jsonify({"success": False, "error": "Failed to save profile"}), 500

    return jsonify(
        {
            "success": True,
            "profile": {
                "user_id": _row_value(row, "user_id", 0),
                "tradition_preference": _row_value(row, "tradition_preference", 1),
                "prayer_style": _row_value(row, "prayer_style", 2),
                "scripture_translation": _row_value(row, "scripture_translation", 3),
                "updated_at": (
                    _row_value(row, "updated_at", 4).isoformat() if _row_value(row, "updated_at", 4) else None
                ),
            },
        }
    )


@faith_bp.route("/api/faith/bible/meta")
@login_required
def bible_meta() -> Response:
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
def bible_passage() -> JsonResponse:
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
def bible_search() -> JsonResponse:
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"success": False, "error": "query required"}), 400
    limit = _clamped_search_limit(25)

    q = query.lower()
    results: list[JsonDict] = []
    for verse in _load_web_bible()["verses"]:
        haystack = f"{verse['reference']} {verse['text']}".lower()
        if q in haystack:
            results.append(verse)
            if len(results) >= limit:
                break
    return jsonify({"success": True, "query": query, "results": results, "count": len(results)})


@faith_bp.route("/api/faith/scriptures/meta")
@login_required
def scriptures_meta() -> Response:
    corpus = _load_scripture_corpus()
    return jsonify(
        {
            "success": True,
            "storage": "local_saved_copies",
            "collections": corpus["collections"],
            "passage_count": len(corpus["passages"]),
            "toc": _scripture_toc(),
        }
    )


@faith_bp.route("/api/faith/scriptures/passage")
@login_required
def scriptures_passage() -> JsonResponse:
    collection = (request.args.get("collection") or "").strip()
    if not _collection_meta(collection):
        return jsonify({"success": False, "error": "unknown collection"}), 404
    toc = _scripture_toc()
    entry = toc.get(collection)
    book_requested = (request.args.get("book") or "").strip()
    chapter_requested = (request.args.get("chapter") or "").strip()
    if not book_requested:
        book_requested = entry["books"][0]["key"] if entry and entry["books"] else ""
    book_node = (
        next((book for book in entry["books"] if book["key"] == book_requested), None)
        if entry and book_requested
        else None
    )
    if book_node is None:
        return jsonify({"success": False, "error": "unknown book for collection"}), 404
    if not chapter_requested:
        chapter_requested = book_node["chapters"][0]["key"] if book_node["chapters"] else ""
    chapter_node = (
        next((chapter for chapter in book_node["chapters"] if chapter["key"] == chapter_requested), None)
        if chapter_requested
        else None
    )
    if chapter_node is None:
        return jsonify({"success": False, "error": "unknown chapter for book"}), 404

    passages = [
        _public_scripture_record(unit)
        for unit in _reader_units()
        if unit["collection"] == collection
        and unit.get("book") == book_requested
        and unit.get("chapter") == chapter_requested
    ]
    if not passages:
        return jsonify({"success": False, "error": "passage not found"}), 404
    if collection in ("web", "jps1917"):
        for passage in passages:
            _ref, sep, tail = passage["reference"].rpartition(":")
            if sep and tail.isdigit():
                passage["verse"] = int(tail)
    return jsonify(
        {
            "success": True,
            "collection": entry["collection"],
            "book": book_node["name"] or book_node["key"],
            "chapter": chapter_node["name"] or chapter_node["key"],
            "passages": passages,
            "count": len(passages),
        }
    )


@faith_bp.route("/api/faith/scriptures/search")
@login_required
def scriptures_search() -> JsonResponse:
    query = (request.args.get("q") or "").strip()
    collection = (request.args.get("collection") or "all").strip()
    if not query:
        return jsonify({"success": False, "error": "query required"}), 400
    limit = _clamped_search_limit(40)

    q = query.lower()
    results: list[JsonDict] = []
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
def encyclopedia_search() -> Response:
    query = (request.args.get("q") or "").strip().lower()
    limit = _clamped_search_limit(MAX_SEARCH_LIMIT)
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
    entries = entries[:limit]
    return jsonify({"success": True, "query": query, "entries": entries, "count": len(entries)})


def _detect_crisis(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in CRISIS_KEYWORDS)


def _save_message(user_id: int, role: str, message: str) -> None:
    try:
        _ensure_tables()
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO faith_sessions (user_id, role, message, session_type)
                VALUES (%s, %s, %s, 'chat')
                """,
                (user_id, role, message),
            )
    except PsycopgError:
        logger.exception("[Faith] Failed to save session message")


@faith_bp.route("/api/faith/chat", methods=["POST"])
@login_required
def chat() -> JsonResponse:
    data: JsonDict = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "error": "message required"}), 400

    user_id = current_user.id
    crisis = _detect_crisis(message)
    _save_message(user_id, "user", message)
    profile = _get_user_faith_profile(user_id)
    system_prompt = _faith_system_prompt_for_profile(profile)

    result = None
    try:
        result = archie_bridge(message, system_prompt)
        response_text = result.get("response", "") if result else ""
        response_text = response_text.strip()
    except (OSError, RuntimeError, ValueError) as e:
        logger.error(f"[Faith] dispatch failed: {e}")
        response_text = "F.A.I.T.H. is unavailable right now."

    if crisis:
        crisis_block = (
            "I am concerned about your safety. Please contact immediate support now: "
            "call or text 988, or text HOME to 741741 for the Crisis Text Line. "
            "If there is immediate danger, call emergency services. You can also use "
            "Connect with Emmanuel for chaplain support, but crisis services are the "
            "right first step right now."
        )
        response_text = f"{crisis_block}\n\n{response_text}" if response_text else crisis_block

    _save_message(user_id, "assistant", response_text)

    return jsonify(
        {
            "success": bool(response_text),
            "response": response_text,
            "model": result.get("model_used", "dhq") if result else "dhq",
            "agent": result.get("agent", "F.A.I.T.H.") if result else "F.A.I.T.H.",
            "crisis_detected": crisis,
        }
    )


# ---------------------------------------------------------------------------
# Task 4: Practices routes
# ---------------------------------------------------------------------------


def _practice_dispatch(
    user_id: int,
    practice_type: str,
    prompt: str,
    notes: str = "",
    profile: JsonDict | None = None,
) -> JsonDict:
    system_prompt = _faith_system_prompt_for_profile(profile or _get_user_faith_profile(user_id))
    if BRIDGE_AVAILABLE:
        try:
            result = archie_bridge(prompt, system_prompt)
        except (OSError, RuntimeError, ValueError) as e:
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
            _ensure_tables()
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    "INSERT INTO faith_practices_log (user_id, practice_type, notes) VALUES (%s, %s, %s)",
                    (user_id, practice_type, notes or result.get("response", "")[:500]),
                )
        except PsycopgError:
            logger.exception("[Faith] Failed to log practice")
    return result


@faith_bp.route("/api/reflection")
@faith_bp.route("/api/faith/reflection")
@faith_bp.route("/api/faith/devotional")
@login_required
def devotional() -> Response:
    today = now_utc().date().isoformat()
    profile = _get_user_faith_profile(current_user.id)
    tradition = TRADITION_LABELS.get(profile.get("tradition_preference"), "broad Christian")
    prompt = (
        f"Generate a daily spiritual reflection for {today} for a {tradition} user. "
        "Include: (1) one appropriate sacred-text passage or wisdom excerpt with reference, "
        "(2) 2-3 sentence reflection, (3) one meditation question. Under 150 words. "
        "Respect the user's tradition and do not substitute another tradition unless the profile is interfaith or unspecified."
    )
    result = _practice_dispatch(current_user.id, "devotional", prompt, profile=profile)
    return jsonify({"success": result.get("success", False), "response": result.get("response", ""), "date": today})


@faith_bp.route("/api/timer", methods=["POST"])
@faith_bp.route("/api/faith/timer", methods=["POST"])
@login_required
def save_timer_session() -> JsonResponse:
    data: JsonDict = request.get_json(force=True, silent=True) or {}
    session_type = (data.get("session_type") or data.get("type") or "meditation").strip().lower()
    title = (data.get("title") or "").strip() or session_type.title()
    notes = (data.get("notes") or "").strip()
    try:
        duration_seconds = int(data.get("duration_seconds") or data.get("duration") or 0)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "duration_seconds must be a number"}), 400
    if duration_seconds < 1 or duration_seconds > 86400:
        return jsonify({"success": False, "error": "duration_seconds must be between 1 and 86400"}), 400

    try:
        _ensure_tables()
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO faith_sessions (
                    user_id, session_type, title, duration_seconds, message, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (
                    current_user.id,
                    session_type,
                    title,
                    duration_seconds,
                    notes or None,
                    Json({"source": "timer"}),
                ),
            )
            row = cur.fetchone()
    except PsycopgError:
        logger.exception("[Faith] Failed to save timer session")
        return jsonify({"success": False, "error": "Failed to save timer session"}), 500

    return (
        jsonify(
            {
                "success": True,
                "session": {
                    "id": _row_value(row, "id", 0),
                    "session_type": session_type,
                    "title": title,
                    "duration_seconds": duration_seconds,
                    "created_at": (
                        _row_value(row, "created_at", 1).isoformat() if _row_value(row, "created_at", 1) else None
                    ),
                },
            }
        ),
        201,
    )


@faith_bp.route("/api/sessions", methods=["GET"])
@faith_bp.route("/api/faith/sessions", methods=["GET"])
@login_required
def list_sessions() -> JsonResponse:
    try:
        limit = min(max(int(request.args.get("limit", "20")), 1), 100)
    except ValueError:
        limit = 20
    try:
        _ensure_tables()
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT id, session_type, title, duration_seconds, role, message, created_at
                FROM faith_sessions
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (current_user.id, limit),
            )
            rows = cur.fetchall()
    except PsycopgError:
        logger.exception("[Faith] Failed to load sessions")
        return jsonify({"success": False, "error": "Failed to load sessions"}), 500

    sessions: list[JsonDict] = []
    for row in rows:
        created_at = _row_value(row, "created_at", 6)
        sessions.append(
            {
                "id": _row_value(row, "id", 0),
                "session_type": _row_value(row, "session_type", 1),
                "title": _row_value(row, "title", 2),
                "duration_seconds": _row_value(row, "duration_seconds", 3),
                "role": _row_value(row, "role", 4),
                "message": _row_value(row, "message", 5),
                "created_at": created_at.isoformat() if created_at else None,
            }
        )
    return jsonify({"success": True, "sessions": sessions})


@faith_bp.route("/api/faith/prayer", methods=["POST"])
@login_required
def guided_prayer() -> JsonResponse:
    data: JsonDict
    error: str | None
    data, error = _json_body()
    if error:
        return _validation_error(error)
    if "prayer_type" in data:
        prayer_type, error = _string_field(data, "prayer_type", required=True, max_chars=32)
    else:
        prayer_type, error = _string_field(data, "type", required=True, max_chars=32)
    if error:
        return _validation_error("prayer_type required" if error == "type required" else error)
    prayer_type = prayer_type.lower()
    if prayer_type not in ALLOWED_PRAYER_TYPES:
        return _validation_error("prayer_type must be one of: " + ", ".join(sorted(ALLOWED_PRAYER_TYPES)))

    intention, error = _string_field(data, "intention", max_chars=MAX_PRAYER_INTENTION_CHARS)
    if error:
        return _validation_error(error)
    profile = _get_user_faith_profile(current_user.id)
    tradition = TRADITION_LABELS.get(profile.get("tradition_preference"), "broad Christian")
    style = profile.get("prayer_style") or "guided"
    prompt = (
        f"Guide me through a {style} {prayer_type} prayer or meditation for a {tradition} user"
        + (f" for: {intention}" if intention else "")
        + ". Structure: Opening, Body, Silence ('...'), Closing. Under 120 words. "
        "For non-theistic traditions, use contemplative language instead of imposed prayer language."
    )
    result = _practice_dispatch(
        current_user.id,
        "prayer",
        prompt,
        notes=f"{prayer_type}: {intention}",
        profile=profile,
    )
    return jsonify({"success": result.get("success", False), "response": result.get("response", "")})


@faith_bp.route("/api/faith/scripture-search", methods=["POST"])
@login_required
def scripture_search() -> JsonResponse:
    data: JsonDict = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"success": False, "error": "query required"}), 400
    profile = _get_user_faith_profile(current_user.id)
    tradition = TRADITION_LABELS.get(profile.get("tradition_preference"), "broad Christian")
    prompt = (
        f"Find 3 relevant sacred-text passages for a {tradition} user about: '{query}'. "
        "Use the user's tradition when possible; for interfaith or unspecified users, include a clearly labeled mix from the saved local corpus. "
        "For each: reference, short excerpt, one sentence of context. Numbered list."
    )
    result = _practice_dispatch(current_user.id, "scripture", prompt, notes=query, profile=profile)
    return jsonify({"success": result.get("success", False), "response": result.get("response", ""), "query": query})


@faith_bp.route("/api/faith/lectio", methods=["POST"])
@login_required
def lectio_divina() -> JsonResponse:
    data: JsonDict
    error: str | None
    data, error = _json_body()
    if error:
        return _validation_error(error)
    passage, error = _string_field(data, "passage", required=True, max_chars=MAX_LECTIO_PASSAGE_CHARS)
    if error:
        return _validation_error(error)
    profile = _get_user_faith_profile(current_user.id)
    tradition = TRADITION_LABELS.get(profile.get("tradition_preference"), "broad Christian")
    prompt = (
        f"Guide a {tradition} user through sacred reading with {passage}. "
        "Use four movements: 1. Read (passage or excerpt), 2. Reflect (question), "
        "3. Respond (prayer, intention, or meditation prompt), 4. Rest (stillness invitation). 2-3 sentences each. "
        "If Lectio Divina language is not appropriate for the selected tradition, adapt it respectfully."
    )
    result = _practice_dispatch(current_user.id, "lectio", prompt, notes=passage, profile=profile)
    return jsonify(
        {"success": result.get("success", False), "response": result.get("response", ""), "passage": passage}
    )


# ---------------------------------------------------------------------------
# Task 5: Check-in + Journal routes
# ---------------------------------------------------------------------------


@faith_bp.route("/api/faith/checkin", methods=["POST"])
@login_required
def checkin() -> JsonResponse:
    data: JsonDict = request.get_json(force=True, silent=True) or {}
    try:
        score = int(data.get("score"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "score must be 1-5"}), 400
    reflection = (data.get("reflection") or "").strip()
    if not (1 <= score <= 5):
        return jsonify({"success": False, "error": "score must be 1-5"}), 400
    try:
        _ensure_tables()
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_checkins (user_id, score, reflection) VALUES (%s, %s, %s) RETURNING id",
                (current_user.id, score, reflection or None),
            )
            checkin_id = _row_value(cur.fetchone(), "id", 0)
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_practices_log (user_id, practice_type, notes) VALUES (%s, 'checkin', %s)",
                (current_user.id, f"score={score}"),
            )
    except PsycopgError:
        logger.exception("[Faith] Failed to save check-in")
        return jsonify({"success": False, "error": "Failed to save"}), 500
    return jsonify({"success": True, "id": checkin_id}), 201


@faith_bp.route("/api/faith/checkin/history")
@login_required
def checkin_history() -> JsonResponse:
    try:
        _ensure_tables()
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT id, score, reflection, created_at FROM faith_checkins "
                "WHERE user_id = %s ORDER BY created_at DESC LIMIT 30",
                (current_user.id,),
            )
            rows: list[JsonDict] = [dict(r) for r in cur.fetchall()]
    except PsycopgError:
        logger.exception("[Faith] Failed to load check-in history")
        return jsonify({"success": False, "error": "Failed to load"}), 500
    return jsonify({"success": True, "checkins": rows})


@faith_bp.route("/api/faith/journal", methods=["POST"])
@login_required
def journal_save() -> JsonResponse:
    data: JsonDict = request.get_json(force=True, silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"success": False, "error": "content required"}), 400
    title = (data.get("title") or "").strip() or None
    scripture_ref = (data.get("scripture_ref") or "").strip() or None
    tags = data.get("tags") or []
    try:
        _ensure_tables()
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_journal (user_id, title, content, scripture_ref, tags) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (current_user.id, title, content, scripture_ref, tags),
            )
            entry_id = _row_value(cur.fetchone(), "id", 0)
    except PsycopgError:
        logger.exception("[Faith] Failed to save journal entry")
        return jsonify({"success": False, "error": "Failed to save"}), 500
    return jsonify({"success": True, "id": entry_id}), 201


@faith_bp.route("/api/faith/journal")
@login_required
def journal_list() -> JsonResponse:
    tag_filter = request.args.get("tag")
    try:
        _ensure_tables()
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
            rows: list[JsonDict] = [dict(r) for r in cur.fetchall()]
    except PsycopgError:
        logger.exception("[Faith] Failed to load journal")
        return jsonify({"success": False, "error": "Failed to load"}), 500
    return jsonify({"success": True, "entries": rows})


# ---------------------------------------------------------------------------
# Task 6: Connect-chaplain route
# ---------------------------------------------------------------------------


def _send_chaplain_email(user_display_name: str, message: str, context_entries: list[JsonDict]) -> bool:
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
    except (ImportError, OSError, RuntimeError, SMTPException, ValueError):
        logger.exception("[Faith] Failed to send chaplain email")
        return False


@faith_bp.route("/api/faith/connect-chaplain", methods=["POST"])
@login_required
def connect_chaplain() -> JsonResponse:
    data: JsonDict
    error: str | None
    data, error = _json_body()
    if error:
        return _validation_error(error)
    message, error = _string_field(data, "message", required=True, max_chars=MAX_CHAPLAIN_MESSAGE_CHARS)
    if error:
        return _validation_error(error)

    journal_ids_raw = data.get("journal_ids") or []
    if not isinstance(journal_ids_raw, list):
        return _validation_error("journal_ids must be a list")
    if len(journal_ids_raw) > MAX_CHAPLAIN_CONTEXT_IDS:
        return _validation_error(f"journal_ids may include at most {MAX_CHAPLAIN_CONTEXT_IDS} entries")
    try:
        journal_ids: list[int] = [int(item) for item in journal_ids_raw]
    except (TypeError, ValueError):
        return _validation_error("journal_ids must contain only numeric ids")
    context_entries: list[JsonDict] = []
    if journal_ids:
        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    "SELECT title, content FROM faith_journal WHERE user_id = %s AND id = ANY(%s)",
                    (current_user.id, journal_ids),
                )
                context_entries = [dict(r) for r in cur.fetchall()]
        except PsycopgError:
            logger.warning("[Faith] Failed to load chaplain journal context", exc_info=True)

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
