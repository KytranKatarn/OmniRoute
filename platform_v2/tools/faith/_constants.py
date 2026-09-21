"""Faith module constants, static data, and shared type aliases.

Moved out of routes.py so the module file sizes the Code Health scanner
(LARGE_FILE / 600-line threshold) can be kept under control. No handler
logic lives here — only values routes and the Faith submodules import.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Response

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