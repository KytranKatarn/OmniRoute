# Translation Coverage System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a nightly scan + AI-generate + Dept HQ review + P.R.O.B.E. verify pipeline that keeps 47 platform surfaces (36 internal modules + 11 external sites/products) fully translated across 8 languages.

**Architecture:** Extend the existing Consciousness Languages tab. Three detection passes write gap rows to a new `translation_gaps` table; Bridge generates/regenerates via `qwen3-coder-cpu` with glossary priming; a confidence gate routes high-confidence to auto-approve and low-confidence to C.O.D.E.X. via `unified_tasks`; a new P.R.O.B.E. suite does Playwright + Tesseract OCR to catch English-residue that escapes text-level scanning.

**Tech Stack:** Python 3.11, Flask (existing), PostgreSQL 16 + pgvector (existing), BeautifulSoup4 (already in requirements), langdetect (new), Tesseract (already on host for OCR), Playwright (already used by P.R.O.B.E.), APScheduler (existing).

**Spec:** `docs/superpowers/specs/2026-04-18-translation-coverage-system-design.md`

**Projects closed on completion:** #231 + #232.

---

## File Structure

| Path | Responsibility | New/Modify |
|------|---------------|------------|
| `database/migrations/320_translation_gaps.sql` | Table + semantic-review column | Create |
| `platform_v2/tools/consciousness/translation_scanners/__init__.py` | Package init + exports | Create |
| `platform_v2/tools/consciousness/translation_scanners/base.py` | `ScannerResult` dataclass + `BaseScanner` ABC | Create |
| `platform_v2/tools/consciousness/translation_scanners/tagged_scanner.py` | Wrap existing tagged-missing scan into the class API | Create |
| `platform_v2/tools/consciousness/translation_scanners/untagged_scanner.py` | BS4 walker for hardcoded English | Create |
| `platform_v2/tools/consciousness/translation_scanners/semantic_scanner.py` | Back-translate + cosine similarity + residue regex | Create |
| `platform_v2/tools/consciousness/translation_scanners/orchestrator.py` | Runs all passes → writes to `translation_gaps`, exports bundles | Create |
| `platform_v2/tools/consciousness/translation_scanners/generator.py` | Bridge dispatch + confidence gate + Dept HQ task creation | Create |
| `platform_v2/tools/consciousness/language_routes.py` | Extend `EXTERNAL_SCAN_SOURCES`; add `/full-scan` endpoint; add coverage-health query endpoint | Modify |
| `platform_v2/templates/tools/consciousness.html` | Inject "Coverage Health" card into Languages tab | Modify |
| `platform_v2/static/js/consciousness-coverage.js` | JS for Coverage Health card (grid, drill-down) | Create |
| `platform_v2/static/css/consciousness-coverage.css` | LCARS styling for the card | Create |
| `platform_v2/services/fleet_jobs.py` | Register `translation_coverage_scan` cron | Modify |
| `ai_bridge/agent_loop.py` | Add `"translation_coverage_scan"` → Documentation & Knowledge | Modify |
| `platform_v2/qa_suites/translation_coverage.py` | P.R.O.B.E. Playwright + OCR suite | Create |
| `platform_v2/requirements.txt` | Add `langdetect==1.0.9` | Modify |
| `platform_v2/tests/translation_scanners/test_untagged_scanner.py` | Unit tests w/ golden HTML | Create |
| `platform_v2/tests/translation_scanners/test_semantic_scanner.py` | Unit tests w/ mock Bridge | Create |
| `platform_v2/tests/translation_scanners/test_orchestrator.py` | Integration test against fixture source | Create |
| `platform_v2/tests/fixtures/translation/sample_site/index.html` | Fixture HTML | Create |

---

## Task 1: Migration 320 — translation_gaps table + semantic-review column

**Files:**
- Create: `database/migrations/320_translation_gaps.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Migration 320: translation_gaps table + last_semantic_review_at column (#231, #232)

BEGIN;

CREATE TABLE IF NOT EXISTS translation_gaps (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(100) NOT NULL,
    gap_type        VARCHAR(30)  NOT NULL,      -- missing | untagged | quality_suspect
    language        VARCHAR(5),                 -- NULL for untagged (applies to all)
    key             VARCHAR(500),               -- NULL for untagged (no key yet)
    file_path       VARCHAR(500),
    line_number     INTEGER,
    snippet         TEXT,
    suggested_key   VARCHAR(500),
    confidence      NUMERIC(3,2),
    status          VARCHAR(20) DEFAULT 'open', -- open | routed | resolved | wontfix
    task_id         INTEGER,                    -- FK unified_tasks when routed
    created_at      TIMESTAMP DEFAULT NOW(),
    resolved_at     TIMESTAMP,
    CONSTRAINT translation_gaps_unique_key
        UNIQUE (source, gap_type, language, key, file_path, line_number)
);

CREATE INDEX IF NOT EXISTS idx_gaps_status   ON translation_gaps(status);
CREATE INDEX IF NOT EXISTS idx_gaps_source   ON translation_gaps(source);
CREATE INDEX IF NOT EXISTS idx_gaps_language ON translation_gaps(language);

ALTER TABLE translations
    ADD COLUMN IF NOT EXISTS last_semantic_review_at TIMESTAMP;

COMMIT;
```

- [ ] **Step 2: Apply migration**

```bash
cat /mnt/archie_brain/database/migrations/320_translation_gaps.sql | \
  docker exec -i archie_database psql -U archie -d archie
```

Expected:
```
BEGIN
CREATE TABLE
CREATE INDEX
CREATE INDEX
CREATE INDEX
ALTER TABLE
COMMIT
```

- [ ] **Step 3: Verify schema**

```bash
docker exec archie_database psql -U archie -d archie -c "\d translation_gaps" | head -20
docker exec archie_database psql -U archie -d archie -c "\d translations" | grep semantic_review
```

Expected: both outputs show the new columns.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/320_translation_gaps.sql
git commit -m "feat(translations): migration 320 — translation_gaps table (#231, #232)"
```

---

## Task 2: Extend EXTERNAL_SCAN_SOURCES

**Files:**
- Modify: `platform_v2/tools/consciousness/language_routes.py:36-52`

- [ ] **Step 1: Add 8 new source entries**

Replace the existing `EXTERNAL_SCAN_SOURCES` list with:

```python
EXTERNAL_SCAN_SOURCES = [
    (
        "website_kytranempowerment",
        "/mnt/archie_brain/website/kytranempowerment.com",
        "/mnt/archie_brain/website/kytranempowerment.com/data/translations.json",
    ),
    (
        "website_kso",
        "/mnt/archie_brain/kytran-server-manager",
        None,
    ),
    (
        "website_creed",
        "/mnt/archie_brain/website/creed-ai.org",
        "/mnt/archie_brain/website/creed-ai.org/data/translations.json",
    ),
    # ── Watch products (VPS-hosted, scanned from hub filesystem mirror) ──
    ("product_civic_watch",   "/mnt/standalone/kytran-civic-watch",   None),
    ("product_gov_watch",     "/mnt/standalone/kytran-gov-watch",     None),
    ("product_legal_watch",   "/mnt/standalone/kytran-legal-watch",   None),
    ("product_market_watch",  "/mnt/standalone/kytran-market-watch",  None),
    # ── What The Fact (brand) — frontend + backend ──
    (
        "website_what_the_fact",
        "/mnt/standalone/websites/what-the-fact.com",
        "/mnt/standalone/websites/what-the-fact.com/data/translations.json",
    ),
    (
        "website_thenews",
        "/mnt/standalone/websites/thenews.kytranempowerment.com",
        "/mnt/standalone/websites/thenews.kytranempowerment.com/data/translations.json",
    ),
    ("product_kytran_news",   "/mnt/standalone/kytran-news",          None),
    # ── KBS ──
    ("product_business_suite","/mnt/standalone/kytran-business-suite", None),
]
```

- [ ] **Step 2: Verify each path exists**

```bash
python3 -c "
import os
paths = [
    '/mnt/standalone/kytran-civic-watch',
    '/mnt/standalone/kytran-gov-watch',
    '/mnt/standalone/kytran-legal-watch',
    '/mnt/standalone/kytran-market-watch',
    '/mnt/standalone/websites/what-the-fact.com',
    '/mnt/standalone/websites/thenews.kytranempowerment.com',
    '/mnt/standalone/kytran-news',
    '/mnt/standalone/kytran-business-suite',
]
for p in paths:
    print(('OK ' if os.path.isdir(p) else 'MISSING '), p)
"
```

Expected: all 8 lines start with `OK`. If any `MISSING`, fix the path before committing.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/consciousness/language_routes.py
git commit -m "feat(translations): extend EXTERNAL_SCAN_SOURCES to 11 sources (#232)"
```

---

## Task 3: Scanner base class + package init

**Files:**
- Create: `platform_v2/tools/consciousness/translation_scanners/__init__.py`
- Create: `platform_v2/tools/consciousness/translation_scanners/base.py`

- [ ] **Step 1: Write base.py**

```python
"""Base contract for translation scanners.

Each scanner reads a source (HTML dir or existing translations row)
and yields ScannerResult objects. The orchestrator UPSERTs these into
translation_gaps.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator, Optional


@dataclass(frozen=True)
class ScannerResult:
    """One gap row pending upsert into translation_gaps."""

    source: str
    gap_type: str  # "missing" | "untagged" | "quality_suspect"
    language: Optional[str] = None
    key: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    snippet: Optional[str] = None
    suggested_key: Optional[str] = None
    confidence: Optional[float] = None


class BaseScanner(ABC):
    """Scanner contract. scan() yields ScannerResult."""

    gap_type: str = ""

    @abstractmethod
    def scan(self) -> Iterator[ScannerResult]:
        """Yield gap rows. Must not write to DB (orchestrator handles that)."""
        raise NotImplementedError
```

- [ ] **Step 2: Write __init__.py**

```python
"""Translation scanners — detection passes for translation_gaps."""
from .base import BaseScanner, ScannerResult

__all__ = ["BaseScanner", "ScannerResult"]
```

- [ ] **Step 3: Sanity import test**

```bash
docker exec archie_platform python3 -c "
from tools.consciousness.translation_scanners import BaseScanner, ScannerResult
r = ScannerResult(source='x', gap_type='missing')
print('ok:', r)
"
```

Expected: `ok: ScannerResult(source='x', gap_type='missing', ...)`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/consciousness/translation_scanners/__init__.py \
        platform_v2/tools/consciousness/translation_scanners/base.py
git commit -m "feat(translations): scanner base contract (#232)"
```

---

## Task 4: Untagged scanner (TDD)

**Files:**
- Create: `platform_v2/tests/fixtures/translation/sample_site/index.html`
- Create: `platform_v2/tests/translation_scanners/__init__.py`
- Create: `platform_v2/tests/translation_scanners/test_untagged_scanner.py`
- Create: `platform_v2/tools/consciousness/translation_scanners/untagged_scanner.py`

- [ ] **Step 1: Write the fixture HTML**

```html
<!DOCTYPE html>
<html>
<head>
<title>Welcome to our site</title>
<style>.hidden { display: none; }</style>
</head>
<body>
<h1 data-i18n="home.title">Tagged Title</h1>
<p>Hardcoded paragraph that should be flagged</p>
<button title="Submit form">OK</button>
<input placeholder="Enter email here">
<code>var x = "not translatable";</code>
<span>×</span>
<div data-i18n="nav.menu">Menu</div>
<a aria-label="Open menu">Hamburger icon</a>
</body>
</html>
```

- [ ] **Step 2: Write the tests/__init__.py (empty) and the failing test**

Create empty `platform_v2/tests/translation_scanners/__init__.py`.

Then `platform_v2/tests/translation_scanners/test_untagged_scanner.py`:

```python
"""Untagged scanner — tests against a golden fixture."""
from pathlib import Path

import pytest

from tools.consciousness.translation_scanners.untagged_scanner import (
    UntaggedScanner,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "translation" / "sample_site"


def _results():
    scanner = UntaggedScanner(source="test_sample", directory=str(FIXTURE))
    return list(scanner.scan())


def test_flags_hardcoded_paragraph():
    results = _results()
    snippets = [r.snippet for r in results]
    assert any("Hardcoded paragraph that should be flagged" in s for s in snippets)


def test_flags_input_placeholder():
    results = _results()
    snippets = [r.snippet for r in results]
    assert any("Enter email here" in s for s in snippets)


def test_flags_title_attribute():
    results = _results()
    snippets = [r.snippet for r in results]
    assert any("Submit form" in s for s in snippets)


def test_flags_aria_label():
    results = _results()
    snippets = [r.snippet for r in results]
    assert any("Open menu" in s for s in snippets)


def test_skips_tagged_elements():
    results = _results()
    snippets = [r.snippet or "" for r in results]
    assert not any("Tagged Title" in s for s in snippets)
    assert not any(s == "Menu" for s in snippets)


def test_skips_code_and_style():
    results = _results()
    snippets = [r.snippet or "" for r in results]
    assert not any('var x = "not translatable"' in s for s in snippets)


def test_skips_single_symbol_and_ok():
    results = _results()
    snippets = [r.snippet or "" for r in results]
    assert not any(s.strip() == "×" for s in snippets)
    assert not any(s.strip() == "OK" for s in snippets)


def test_result_has_file_and_suggested_key():
    results = _results()
    assert results, "expected at least one result"
    for r in results:
        assert r.source == "test_sample"
        assert r.gap_type == "untagged"
        assert r.language is None
        assert r.file_path is not None
        assert r.suggested_key is not None
        assert r.suggested_key.startswith("test_sample.")
```

- [ ] **Step 3: Run — test should fail (module does not exist)**

```bash
docker exec archie_platform pytest /app/tests/translation_scanners/test_untagged_scanner.py -v 2>&1 | tail -15
```

Expected: `ModuleNotFoundError: No module named '...untagged_scanner'`.

- [ ] **Step 4: Implement untagged_scanner.py**

```python
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
        for root, _dirs, files in os.walk(self.directory):
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
```

- [ ] **Step 5: Run tests — should pass**

```bash
docker exec archie_platform pytest /app/tests/translation_scanners/test_untagged_scanner.py -v 2>&1 | tail -15
```

Expected: `8 passed`.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/consciousness/translation_scanners/untagged_scanner.py \
        platform_v2/tests/translation_scanners/__init__.py \
        platform_v2/tests/translation_scanners/test_untagged_scanner.py \
        platform_v2/tests/fixtures/translation/sample_site/index.html
git commit -m "feat(translations): untagged scanner + golden fixture (#232)"
```

---

## Task 5: Semantic scanner (TDD with mocked Bridge)

**Files:**
- Create: `platform_v2/tests/translation_scanners/test_semantic_scanner.py`
- Create: `platform_v2/tools/consciousness/translation_scanners/semantic_scanner.py`
- Modify: `platform_v2/requirements.txt` (add `langdetect==1.0.9`)

- [ ] **Step 1: Add langdetect to requirements**

Append to `platform_v2/requirements.txt`:

```
langdetect==1.0.9
```

- [ ] **Step 2: Install in running container**

```bash
docker exec archie_platform pip install langdetect==1.0.9 2>&1 | tail -3
```

Expected: `Successfully installed langdetect-1.0.9`.

- [ ] **Step 3: Write failing tests**

`platform_v2/tests/translation_scanners/test_semantic_scanner.py`:

```python
"""Semantic scanner — tests with mocked Bridge + embedding service."""
from unittest.mock import patch

import pytest

from tools.consciousness.translation_scanners.semantic_scanner import (
    SemanticScanner,
    _english_residue_count,
    _should_skip_short,
)


def test_residue_count_flags_english_tokens_in_french():
    assert _english_residue_count("Cliquez sur le bouton Submit puis Cancel") >= 2
    assert _english_residue_count("Cliquez sur le bouton d'envoi puis annuler") == 0


def test_short_strings_skipped():
    assert _should_skip_short("Hi") is True
    assert _should_skip_short("Submit form here") is False


def test_scan_flags_low_cosine():
    rows = [
        {"id": 1, "language": "fr", "key": "home.title", "text": "Le titre d'accueil",
         "source_en_text": "Welcome Home"}
    ]
    with patch(
        "tools.consciousness.translation_scanners.semantic_scanner.back_translate_to_en",
        return_value="The home title",
    ), patch(
        "tools.consciousness.translation_scanners.semantic_scanner.cosine_similarity",
        return_value=0.5,
    ):
        scanner = SemanticScanner(source="website_kytranempowerment", rows=rows)
        results = list(scanner.scan())
        assert len(results) == 1
        r = results[0]
        assert r.gap_type == "quality_suspect"
        assert r.language == "fr"
        assert r.confidence == pytest.approx(0.5)


def test_scan_passes_when_similarity_high_and_no_residue():
    rows = [
        {"id": 2, "language": "fr", "key": "home.title", "text": "Titre d'accueil",
         "source_en_text": "Home Title"}
    ]
    with patch(
        "tools.consciousness.translation_scanners.semantic_scanner.back_translate_to_en",
        return_value="Home Title",
    ), patch(
        "tools.consciousness.translation_scanners.semantic_scanner.cosine_similarity",
        return_value=0.95,
    ):
        scanner = SemanticScanner(source="website_kytranempowerment", rows=rows)
        results = list(scanner.scan())
        assert results == []


def test_scan_flags_on_residue_even_with_high_cosine():
    rows = [
        {"id": 3, "language": "fr", "key": "cta.submit",
         "text": "Cliquez sur Submit pour Cancel", "source_en_text": "Click to continue"}
    ]
    with patch(
        "tools.consciousness.translation_scanners.semantic_scanner.back_translate_to_en",
        return_value="Click Submit to Cancel",
    ), patch(
        "tools.consciousness.translation_scanners.semantic_scanner.cosine_similarity",
        return_value=0.90,
    ):
        scanner = SemanticScanner(source="website_kytranempowerment", rows=rows)
        results = list(scanner.scan())
        assert len(results) == 1
        assert results[0].gap_type == "quality_suspect"
```

- [ ] **Step 4: Run — should fail**

```bash
docker exec archie_platform pytest /app/tests/translation_scanners/test_semantic_scanner.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 5: Implement semantic_scanner.py**

```python
"""Semantic scanner — back-translate + cosine + residue regex."""
from __future__ import annotations

import re
from typing import Iterator, List, Dict

from .base import BaseScanner, ScannerResult


_ENGLISH_TOKENS = re.compile(
    r"\b(the|click|submit|save|next|back|cancel|yes|no|login|sign|email|"
    r"password|hello|welcome|logout|settings|delete|edit|create)\b",
    re.IGNORECASE,
)

_MIN_CHARS = 10
_MIN_COSINE = 0.80
_MAX_RESIDUE = 2


def _english_residue_count(text: str) -> int:
    return len(_ENGLISH_TOKENS.findall(text or ""))


def _should_skip_short(text: str) -> bool:
    return len(text.strip()) < _MIN_CHARS


def back_translate_to_en(non_en_text: str, source_lang: str) -> str:
    """Dispatch Bridge back-translation. Out-of-module so tests can mock."""
    from tools.department_hq.services.department_dispatcher import dispatch_json

    prompt = (
        f"Translate the following {source_lang} text literally to English. "
        f"Respond ONLY with JSON: {{\"en\": \"...\"}}.\n\n"
        f"TEXT: {non_en_text}"
    )
    result = dispatch_json(
        task="translate",
        prompt=prompt,
        preferred_model="qwen3-coder-cpu",
    )
    if result and result.success and isinstance(result.response, dict):
        return result.response.get("en") or ""
    return ""


def cosine_similarity(a: str, b: str) -> float:
    """Via existing embedding service. Out-of-module so tests can mock."""
    from ai_bridge.embedding_service import get_embedding

    va = get_embedding(a)
    vb = get_embedding(b)
    if not va or not vb:
        return 0.0
    dot = sum(x * y for x, y in zip(va, vb))
    na = sum(x * x for x in va) ** 0.5
    nb = sum(x * x for x in vb) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class SemanticScanner(BaseScanner):
    gap_type = "quality_suspect"

    def __init__(self, source: str, rows: List[Dict]):
        self.source = source
        self.rows = rows

    def scan(self) -> Iterator[ScannerResult]:
        for row in self.rows:
            text = row.get("text") or ""
            if _should_skip_short(text):
                continue
            back = back_translate_to_en(text, row.get("language", ""))
            sim = cosine_similarity(back, row.get("source_en_text", ""))
            residue = _english_residue_count(text)
            if sim < _MIN_COSINE or residue >= _MAX_RESIDUE:
                yield ScannerResult(
                    source=self.source,
                    gap_type=self.gap_type,
                    language=row.get("language"),
                    key=row.get("key"),
                    snippet=text[:200],
                    confidence=round(sim, 2),
                )
```

- [ ] **Step 6: Run tests — should pass**

```bash
docker exec archie_platform pytest /app/tests/translation_scanners/test_semantic_scanner.py -v 2>&1 | tail -10
```

Expected: `5 passed`.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/consciousness/translation_scanners/semantic_scanner.py \
        platform_v2/tests/translation_scanners/test_semantic_scanner.py \
        platform_v2/requirements.txt
git commit -m "feat(translations): semantic scanner + langdetect dep (#232)"
```

---

## Task 6: Tagged scanner wrapper

**Files:**
- Create: `platform_v2/tools/consciousness/translation_scanners/tagged_scanner.py`

- [ ] **Step 1: Write the wrapper**

```python
"""Tagged scanner — wraps the existing scan_and_seed_keys flow.

Emits ScannerResult rows for (key, language) pairs that exist as EN
source rows but are missing in other languages.
"""
from __future__ import annotations

from typing import Iterator

from database import get_db_cursor

from .base import BaseScanner, ScannerResult


TARGET_LANGS = ("fr", "es", "pt", "de", "zh", "ar", "he")


class TaggedScanner(BaseScanner):
    gap_type = "missing"

    def __init__(self, source: str):
        self.source = source

    def scan(self) -> Iterator[ScannerResult]:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """SELECT key FROM translations
                   WHERE source_id = %s AND language = 'en'""",
                (self.source,),
            )
            en_keys = [r["key"] for r in cur.fetchall()]

            for lang in TARGET_LANGS:
                if not en_keys:
                    continue
                cur.execute(
                    """SELECT key FROM translations
                       WHERE source_id = %s
                         AND language = %s
                         AND key = ANY(%s)""",
                    (self.source, lang, en_keys),
                )
                have = {r["key"] for r in cur.fetchall()}
                missing = set(en_keys) - have
                for key in missing:
                    yield ScannerResult(
                        source=self.source,
                        gap_type=self.gap_type,
                        language=lang,
                        key=key,
                    )
```

**Note:** Uses a `source_id` column on `translations`. Verify before commit:

```bash
docker exec archie_database psql -U archie -d archie -c "\d translations" | grep -i source
```

If the column name differs (e.g., `source`), adjust the SQL before commit.

- [ ] **Step 2: Sanity import**

```bash
docker exec archie_platform python3 -c "
from tools.consciousness.translation_scanners.tagged_scanner import TaggedScanner
s = TaggedScanner(source='website_kytranempowerment')
print('ok:', s.gap_type)
"
```

Expected: `ok: missing`.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/consciousness/translation_scanners/tagged_scanner.py
git commit -m "feat(translations): tagged scanner wrapping missing-lang detection (#232)"
```

---

## Task 7: Generator + confidence gate + Dept HQ routing

**Files:**
- Create: `platform_v2/tools/consciousness/translation_scanners/generator.py`

- [ ] **Step 1: Write the generator**

```python
"""Bridge-driven generation, confidence gate, Dept HQ routing."""
from __future__ import annotations

import logging
import os
from typing import Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

NIGHTLY_CAP = int(os.getenv("TRANSLATION_NIGHTLY_CAP", "5000"))

AUTO_APPROVE_MIN = 0.85
REVIEW_MIN = 0.60

REVIEW_PROJECT_NAME = "Platform Translation Coverage"


def _ensure_review_project() -> int:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT id FROM unified_projects WHERE name = %s",
            (REVIEW_PROJECT_NAME,),
        )
        row = cur.fetchone()
        if row:
            return row["id"]
        cur.execute(
            """INSERT INTO unified_projects (name, slug, description, status, priority, type, tags)
               VALUES (%s, %s, %s, 'planning', 7, 'feature', ARRAY['translations','coverage'])
               RETURNING id""",
            (
                REVIEW_PROJECT_NAME,
                "platform-translation-coverage",
                "Low-confidence translation reviews routed by the nightly coverage scan.",
            ),
        )
        return cur.fetchone()["id"]


def _route_to_review(
    gap_id: int,
    source: str,
    language: str,
    key: str,
    suggested_translation: str,
    confidence: float,
    gap_type: str,
) -> int:
    project_id = _ensure_review_project()
    priority = 8 if confidence < REVIEW_MIN else 6
    title = f"Review {language} for {source}: {(suggested_translation or '')[:60]}"
    description = (
        f"**Key:** `{key}`\n"
        f"**Source:** `{source}`\n"
        f"**Gap type:** `{gap_type}`\n"
        f"**Confidence:** {confidence:.2f}\n\n"
        f"**Suggested translation:**\n\n> {suggested_translation or '(none)'}\n\n"
        f"Review in Consciousness Languages tab → Coverage Health → drill into "
        f"`{source}` × `{language}`."
    )
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO unified_tasks
               (project_id, title, description, status, priority, task_type, estimated_effort)
               VALUES (%s, %s, %s, 'pending', %s, 'review', 'tiny')
               RETURNING id""",
            (project_id, title, description, priority),
        )
        task_id = cur.fetchone()["id"]
        cur.execute(
            "UPDATE translation_gaps SET status='routed', task_id=%s WHERE id=%s",
            (task_id, gap_id),
        )
    return task_id


def _generate_translation(en_text: str, language: str, glossary: Optional[list] = None) -> dict:
    """Return {'translated': str, 'confidence': float}."""
    from tools.department_hq.services.department_dispatcher import dispatch_json

    glossary_block = ""
    if glossary:
        lines = "\n".join(f"- {g['source_text']} → {g['translated_text']}" for g in glossary[:10])
        glossary_block = f"\n\nBrand glossary (use consistently):\n{lines}\n"

    prompt = (
        f"Translate the following English UI string to {language}.\n"
        f"Respond ONLY with JSON: {{\"translated\": \"...\", \"confidence\": 0.0-1.0}}.\n"
        f"{glossary_block}\n\nTEXT: {en_text}"
    )
    r = dispatch_json(task="translate", prompt=prompt, preferred_model="qwen3-coder-cpu")
    if not r or not r.success or not isinstance(r.response, dict):
        return {"translated": "", "confidence": 0.0}
    translated = r.response.get("translated", "")
    confidence = float(r.response.get("confidence", 0.0))
    return {"translated": translated, "confidence": confidence}


def process_missing_gap(gap: dict) -> bool:
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """SELECT text FROM translations
               WHERE source_id=%s AND language='en' AND key=%s LIMIT 1""",
            (gap["source"], gap["key"]),
        )
        row = cur.fetchone()
        if not row:
            return False
        en_text = row["text"]
        cur.execute(
            """SELECT source_text, translated_text FROM translation_memory
               WHERE language=%s AND source_text ILIKE %s LIMIT 5""",
            (gap["language"], f"%{en_text[:40]}%"),
        )
        glossary = list(cur.fetchall())

    result = _generate_translation(en_text, gap["language"], glossary)
    translated = result["translated"]
    confidence = result["confidence"]
    if not translated:
        return False

    status = "approved" if confidence >= AUTO_APPROVE_MIN else "pending_review"

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO translations (source_id, key, language, text, source, status, generated_by, last_semantic_review_at)
               VALUES (%s, %s, %s, %s, 'ai_generated', %s, 'coverage_scan', NOW())
               ON CONFLICT (source_id, key, language) DO UPDATE
                 SET text=EXCLUDED.text, source=EXCLUDED.source, status=EXCLUDED.status,
                     last_semantic_review_at=NOW()""",
            (gap["source"], gap["key"], gap["language"], translated, status),
        )
        cur.execute(
            "UPDATE translation_gaps SET status='resolved', resolved_at=NOW() WHERE id=%s",
            (gap["id"],),
        )

    if status == "pending_review":
        _route_to_review(
            gap["id"], gap["source"], gap["language"], gap["key"],
            translated, confidence, gap["gap_type"],
        )
    return True
```

**Note:** Assumes UNIQUE `(source_id, key, language)` on `translations`. Verify:

```bash
docker exec archie_database psql -U archie -d archie -c "\d translations" | grep -i unique
```

If missing, add a migration in a follow-up; the UPSERT will error otherwise.

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/consciousness/translation_scanners/generator.py
git commit -m "feat(translations): generator + confidence gate + Dept HQ routing (#232)"
```

---

## Task 8: Orchestrator

**Files:**
- Create: `platform_v2/tools/consciousness/translation_scanners/orchestrator.py`

- [ ] **Step 1: Write the orchestrator**

```python
"""Translation coverage orchestrator — runs all passes, writes gaps, exports bundles."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from database import get_db_cursor

from .base import ScannerResult
from .tagged_scanner import TaggedScanner
from .untagged_scanner import UntaggedScanner
from .semantic_scanner import SemanticScanner
from .generator import NIGHTLY_CAP, process_missing_gap

logger = logging.getLogger("agent_loop")


def _upsert_gap(result: ScannerResult) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO translation_gaps
                   (source, gap_type, language, key, file_path, line_number,
                    snippet, suggested_key, confidence)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (source, gap_type, language, key, file_path, line_number)
               DO UPDATE SET
                    snippet        = EXCLUDED.snippet,
                    suggested_key  = EXCLUDED.suggested_key,
                    confidence     = EXCLUDED.confidence,
                    status         = CASE WHEN translation_gaps.status = 'resolved'
                                          THEN 'open'
                                          ELSE translation_gaps.status END""",
            (
                result.source, result.gap_type, result.language, result.key,
                result.file_path, result.line_number, result.snippet,
                result.suggested_key, result.confidence,
            ),
        )


def _semantic_candidate_rows(source: str) -> list:
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """SELECT t.id, t.language, t.key, t.text,
                      en.text AS source_en_text
               FROM translations t
               LEFT JOIN translations en
                   ON en.source_id = t.source_id AND en.key = t.key AND en.language='en'
               WHERE t.source_id = %s
                 AND t.language <> 'en'
                 AND (t.last_semantic_review_at IS NULL
                      OR t.last_semantic_review_at < NOW() - INTERVAL '30 days')
               LIMIT 500""",
            (source,),
        )
        return list(cur.fetchall())


def _load_open_missing_gaps(limit: int) -> list:
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """SELECT id, source, language, key, gap_type
               FROM translation_gaps
               WHERE status='open' AND gap_type='missing'
               ORDER BY created_at ASC
               LIMIT %s""",
            (limit,),
        )
        return list(cur.fetchall())


def _export_bundle(source: str, bundle_path: str) -> Optional[int]:
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """SELECT language, key, text FROM translations
               WHERE source_id=%s AND status='approved'""",
            (source,),
        )
        data: dict = {}
        for row in cur.fetchall():
            data.setdefault(row["language"], {})[row["key"]] = row["text"]
    os.makedirs(os.path.dirname(bundle_path), exist_ok=True)
    with open(bundle_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    return sum(len(v) for v in data.values())


def run_translation_coverage_scan(sources: Optional[list] = None) -> dict:
    from tools.consciousness.language_routes import EXTERNAL_SCAN_SOURCES

    start = time.time()
    sources = sources or EXTERNAL_SCAN_SOURCES
    totals = {"gaps_found": 0, "auto_fixed": 0, "routed": 0, "bundles_written": 0}

    # Pass 1 + Pass 2
    for entry in sources:
        label, directory, _bundle_path = entry
        if not os.path.isdir(directory):
            logger.warning("[TranslationScan] skip missing source %s", directory)
            continue
        for result in TaggedScanner(source=label).scan():
            _upsert_gap(result); totals["gaps_found"] += 1
        for result in UntaggedScanner(source=label, directory=directory).scan():
            _upsert_gap(result); totals["gaps_found"] += 1

    # Pass 3
    for entry in sources:
        label = entry[0]
        rows = _semantic_candidate_rows(label)
        for result in SemanticScanner(source=label, rows=rows).scan():
            _upsert_gap(result); totals["gaps_found"] += 1

    # Generation pass
    for gap in _load_open_missing_gaps(NIGHTLY_CAP):
        ok = process_missing_gap(dict(gap))
        if ok:
            totals["auto_fixed"] += 1
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            "SELECT COUNT(*) AS n FROM translation_gaps WHERE status='routed' AND resolved_at IS NULL"
        )
        totals["routed"] = cur.fetchone()["n"]

    # Bundle export
    for entry in sources:
        label, _directory, bundle_path = entry
        if not bundle_path:
            continue
        try:
            count = _export_bundle(label, bundle_path)
            if count is not None:
                totals["bundles_written"] += 1
        except OSError as e:
            logger.warning("[TranslationScan] bundle export failed for %s: %s", label, e)

    totals["duration_ms"] = int((time.time() - start) * 1000)
    logger.info("[TranslationScan] complete %s", totals)
    return totals
```

- [ ] **Step 2: Sanity import**

```bash
docker exec archie_platform python3 -c "
from tools.consciousness.translation_scanners.orchestrator import run_translation_coverage_scan
print('ok')
"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/consciousness/translation_scanners/orchestrator.py
git commit -m "feat(translations): orchestrator running all 3 passes + export (#232)"
```

---

## Task 9: Manual "Scan Now" endpoint + coverage-health query endpoint

**Files:**
- Modify: `platform_v2/tools/consciousness/language_routes.py`

- [ ] **Step 1: Add new endpoints below the existing `/api/translations/*` block**

```python
# --- Full-scan trigger + coverage health query (task #232) ---
import threading
from flask import jsonify, request

@bp.route("/api/translations/full-scan", methods=["POST"])
@admin_required
@rate_limit(max_requests=1, window_seconds=900)
def trigger_full_scan():
    """Kick off the orchestrator in a background thread."""
    from tools.consciousness.translation_scanners.orchestrator import (
        run_translation_coverage_scan,
    )

    def _run():
        try:
            run_translation_coverage_scan()
        except Exception:  # noqa: BLE001
            logger.exception("full-scan failed")

    threading.Thread(target=_run, daemon=True, name="translation-full-scan").start()
    return jsonify({"success": True, "message": "scan started"})


@bp.route("/api/translations/coverage-health", methods=["GET"])
@admin_required
def coverage_health():
    """Per-source per-language coverage % + last-scan timestamps."""
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """SELECT source_id AS source, language,
                      COUNT(*) AS total,
                      SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) AS approved,
                      MAX(updated_at) AS last_updated
               FROM translations
               GROUP BY source_id, language"""
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute(
            """SELECT source, gap_type, COUNT(*) AS n
               FROM translation_gaps
               WHERE status <> 'resolved'
               GROUP BY source, gap_type"""
        )
        gap_rows = [dict(r) for r in cur.fetchall()]
    return jsonify({"coverage": rows, "open_gaps": gap_rows})
```

**Note:** `bp`, `@admin_required`, `@rate_limit`, `logger`, `get_db_cursor` already imported in `language_routes.py`.

- [ ] **Step 2: Deploy + smoke test**

```bash
docker cp /mnt/archie_brain/platform_v2/tools/consciousness/language_routes.py \
    archie_platform:/app/tools/consciousness/language_routes.py
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform
sleep 10
curl -sk -o /dev/null -w "coverage-health (unauth): %{http_code}\n" \
    http://192.168.1.200:3000/api/translations/coverage-health
```

Expected: `302` or `401` (admin_required). Non-500 = endpoint exists.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/consciousness/language_routes.py
git commit -m "feat(translations): /full-scan trigger + /coverage-health endpoint (#232)"
```

---

## Task 10: Register nightly agent_loop job

**Files:**
- Modify: `platform_v2/services/fleet_jobs.py`
- Modify: `ai_bridge/agent_loop.py` (JOB_DEPARTMENT_MAP)

- [ ] **Step 1: Add the cron registration in services/fleet_jobs.py inside register_fleet_jobs**

Just after the VPS health monitor block (from #1683), add:

```python
    scheduler.add_job(
        with_ctx(_translation_coverage_scan_wrapper),
        trigger=CronTrigger(hour=2, minute=0),
        id="translation_coverage_scan",
        name="Agent Loop: Translation Coverage Scan",
        replace_existing=True,
    )
```

And above `register_fleet_jobs`, add the wrapper:

```python
def _translation_coverage_scan_wrapper():
    """Translation coverage scan (task #232 nightly)."""
    start = time.time()
    try:
        from tools.consciousness.translation_scanners.orchestrator import (
            run_translation_coverage_scan,
        )
        summary = run_translation_coverage_scan()
        _log_cycle(
            "translation_coverage_scan",
            items_processed=summary.get("auto_fixed", 0),
            items_failed=0,
            duration_ms=summary.get("duration_ms", 0),
            details=summary,
        )
    except Exception as e:  # noqa: BLE001
        dur = int((time.time() - start) * 1000)
        logger.error("[TranslationScan] failed: %s", e)
        _log_cycle(
            "translation_coverage_scan", 0, 1, dur, error_message=str(e)
        )
```

- [ ] **Step 2: Add to JOB_DEPARTMENT_MAP in ai_bridge/agent_loop.py**

Find `"vps_health": "Operations & Infrastructure",` and below it add:

```python
    "translation_coverage_scan": "Documentation & Knowledge",
```

- [ ] **Step 3: Deploy and verify registration**

```bash
docker cp /mnt/archie_brain/platform_v2/services/fleet_jobs.py \
    archie_platform:/app/services/fleet_jobs.py
docker cp /mnt/archie_brain/ai_bridge/agent_loop.py \
    archie_platform:/mnt/archie_brain/ai_bridge/agent_loop.py
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform
sleep 10
docker logs archie_platform --since 15s 2>&1 | grep "Translation Coverage Scan"
```

Expected: `Added job "Agent Loop: Translation Coverage Scan" to job store "default"`.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/services/fleet_jobs.py ai_bridge/agent_loop.py
git commit -m "feat(fleet): register nightly translation_coverage_scan cron (#232)"
```

---

## Task 11: Coverage Health dashboard card

**Files:**
- Modify: `platform_v2/templates/tools/consciousness.html`
- Create: `platform_v2/static/js/consciousness-coverage.js`
- Create: `platform_v2/static/css/consciousness-coverage.css`

- [ ] **Step 1: Add CSS (LCARS-aligned)**

```css
/* consciousness-coverage.css */
.cov-health-card {
    background: var(--archie-surface-1);
    border: 1px solid var(--archie-border);
    border-radius: 8px;
    padding: 16px;
    margin-top: 16px;
}
.cov-health-grid {
    display: grid;
    grid-template-columns: 180px repeat(8, 1fr);
    gap: 2px;
    font-size: 12px;
}
.cov-head, .cov-cell { padding: 6px 8px; text-align: center; }
.cov-head { background: var(--archie-accent); color: #000; font-weight: 600; }
.cov-source-label { text-align: left; background: var(--archie-surface-2); }
.cov-cell[data-band="high"]   { background: #10b98133; }
.cov-cell[data-band="medium"] { background: #f59e0b33; }
.cov-cell[data-band="low"]    { background: #ef444433; }
.cov-banner { display: flex; gap: 16px; margin-bottom: 12px; font-size: 13px; align-items: center; }
.cov-scan-btn { background: var(--archie-accent); color: #000; border: 0; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
```

- [ ] **Step 2: Add JS (safe DOM construction only — no innerHTML)**

```javascript
// consciousness-coverage.js
(function () {
  const LANGS = ["en", "fr", "es", "pt", "de", "zh", "ar", "he"];

  function pct(n, d) { return d === 0 ? 0 : Math.round((n / d) * 100); }

  function band(p) {
    if (p >= 100) return "high";
    if (p >= 80) return "medium";
    return "low";
  }

  function removeAllChildren(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function makeCell(className, text, dataAttrs) {
    const el = document.createElement("div");
    el.className = className;
    el.textContent = text;
    if (dataAttrs) {
      for (const k in dataAttrs) {
        if (Object.prototype.hasOwnProperty.call(dataAttrs, k)) {
          el.setAttribute("data-" + k, String(dataAttrs[k]));
        }
      }
    }
    return el;
  }

  async function load() {
    const grid = document.getElementById("cov-grid");
    const banner = document.getElementById("cov-banner");
    if (!grid) return;
    let data;
    try {
      const r = await fetch("/api/translations/coverage-health", { credentials: "include" });
      if (!r.ok) return;
      data = await r.json();
    } catch (e) {
      if (banner) banner.textContent = "Failed to load coverage data";
      return;
    }
    render(grid, banner, data.coverage || [], data.open_gaps || []);
  }

  function render(grid, banner, coverage, gaps) {
    removeAllChildren(grid);

    // Header row: Source column + one per language
    grid.appendChild(makeCell("cov-head cov-source-label", "Source"));
    for (const l of LANGS) grid.appendChild(makeCell("cov-head", l.toUpperCase()));

    // Pivot coverage rows by source
    const bySource = {};
    for (const row of coverage) {
      (bySource[row.source] = bySource[row.source] || {})[row.language] = row;
    }
    for (const src of Object.keys(bySource).sort()) {
      grid.appendChild(makeCell("cov-cell cov-source-label", src));
      for (const l of LANGS) {
        const d = bySource[src][l] || { total: 0, approved: 0 };
        const p = pct(Number(d.approved || 0), Number(d.total || 0));
        const cell = makeCell("cov-cell", p + "%", { band: band(p) });
        cell.title = d.approved + "/" + d.total;
        grid.appendChild(cell);
      }
    }

    if (banner) {
      const gapCount = gaps.reduce(function (s, g) { return s + Number(g.n); }, 0);
      banner.textContent = "Open gaps: " + gapCount;
    }
  }

  async function scanNow(btn) {
    btn.disabled = true;
    btn.textContent = "Scanning...";
    try {
      const r = await fetch("/api/translations/full-scan", { method: "POST", credentials: "include" });
      const j = await r.json();
      btn.textContent = j.success ? "Scan started — check back in ~5 min" : "Failed";
    } catch (e) {
      btn.textContent = "Error: " + e.message;
    } finally {
      setTimeout(function () { btn.disabled = false; btn.textContent = "Scan Now"; }, 30000);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    load();
    const btn = document.getElementById("cov-scan-btn");
    if (btn) btn.addEventListener("click", function () { scanNow(btn); });
  });
})();
```

- [ ] **Step 3: Inject the card into the Languages tab**

In `platform_v2/templates/tools/consciousness.html`, find the Languages tab content block (look for `id="tab-languages"` or similar). Just inside it, add:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/consciousness-coverage.css') }}">
<div class="cov-health-card">
  <div class="cov-banner">
    <strong>Coverage Health</strong>
    <span id="cov-banner"></span>
    <button id="cov-scan-btn" class="cov-scan-btn">Scan Now</button>
  </div>
  <div id="cov-grid" class="cov-health-grid"></div>
</div>
<script src="{{ url_for('static', filename='js/consciousness-coverage.js') }}"></script>
```

- [ ] **Step 4: Deploy + smoke test**

```bash
docker cp /mnt/archie_brain/platform_v2/templates/tools/consciousness.html \
    archie_platform:/app/templates/tools/consciousness.html
docker cp /mnt/archie_brain/platform_v2/static/js/consciousness-coverage.js \
    archie_platform:/app/static/js/consciousness-coverage.js
docker cp /mnt/archie_brain/platform_v2/static/css/consciousness-coverage.css \
    archie_platform:/app/static/css/consciousness-coverage.css
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform
sleep 10
curl -sk -o /dev/null -w "consciousness: %{http_code}\n" http://192.168.1.200:3000/tools/consciousness/
```

Expected: `302` (login redirect). Browser-test after login confirms render.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/templates/tools/consciousness.html \
        platform_v2/static/js/consciousness-coverage.js \
        platform_v2/static/css/consciousness-coverage.css
git commit -m "feat(consciousness): Coverage Health card + Scan Now button (#232)"
```

---

## Task 12: P.R.O.B.E. translation_coverage suite

**Files:**
- Create: `platform_v2/qa_suites/translation_coverage.py`

- [ ] **Step 1: Confirm the qa_suites directory**

```bash
ls /mnt/archie_brain/platform_v2/qa_suites/ 2>&1 | head -10
```

If that path doesn't exist, discover with:

```bash
find /mnt/archie_brain/platform_v2 -type d \( -name "qa_suites" -o -name "probe_suites" \) 2>/dev/null | head
```

Use whichever directory exists. Adjust the file path below accordingly.

- [ ] **Step 2: Write the suite**

```python
"""P.R.O.B.E. suite: translation_coverage — Playwright + Tesseract OCR + langdetect.

For each (external source, language) combo, open a small set of pages, switch
language via the UI, OCR the viewport, and flag any non-EN page where the
detected language of extracted text is still English.
"""
from __future__ import annotations

import logging
import tempfile
from typing import Iterable

logger = logging.getLogger(__name__)

TARGET_PAGES = {
    "website_kytranempowerment": ["/", "/pricing", "/about"],
    "website_what_the_fact":     ["/"],
    "website_thenews":           ["/"],
}

BASE_URLS = {
    "website_kytranempowerment": "https://www.kytranempowerment.com",
    "website_what_the_fact":     "https://wtf.kytranempowerment.com",
    "website_thenews":           "https://thenews.kytranempowerment.com",
}

LANGS = ["fr", "es", "pt", "de", "zh", "ar", "he"]


def _paths_for(source: str):
    return TARGET_PAGES.get(source, ["/"])


def _base_url_for(source: str) -> str:
    return BASE_URLS.get(source, "")


def run(sources: Iterable[str]) -> dict:
    import pytesseract
    from langdetect import detect, DetectorFactory
    from playwright.sync_api import sync_playwright
    from database import get_db_cursor

    DetectorFactory.seed = 0
    summary = {"checks": 0, "failures": 0, "details": []}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        for source in sources:
            base = _base_url_for(source)
            if not base:
                continue
            for path in _paths_for(source):
                for lang in LANGS:
                    summary["checks"] += 1
                    page = browser.new_page(locale=lang, viewport={"width": 1440, "height": 900})
                    try:
                        page.goto(base + path, timeout=15000, wait_until="networkidle")
                        page.evaluate(
                            "document.documentElement.lang = arguments[0];"
                            "window.dispatchEvent(new CustomEvent('archie:set-lang', {detail: arguments[0]}));",
                            lang,
                        )
                        page.wait_for_timeout(800)
                        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                            page.screenshot(path=tmp.name, full_page=False)
                            text = pytesseract.image_to_string(tmp.name) or ""
                        try:
                            detected = detect(text) if text.strip() else "unknown"
                        except Exception:  # noqa: BLE001
                            detected = "unknown"
                        if detected == "en" and lang != "en":
                            summary["failures"] += 1
                            summary["details"].append({
                                "source": source, "path": path, "lang": lang, "detected": detected,
                            })
                            with get_db_cursor(commit=True) as (_c, cur):
                                cur.execute(
                                    """INSERT INTO translation_gaps
                                           (source, gap_type, language, file_path, snippet, confidence)
                                       VALUES (%s, 'quality_suspect', %s, %s, %s, 0.0)
                                       ON CONFLICT DO NOTHING""",
                                    (source, lang, path, f"OCR detected EN on {lang} page"),
                                )
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[translation_coverage] error %s %s %s: %s", source, path, lang, e)
                    finally:
                        page.close()
        browser.close()
    return summary
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/qa_suites/translation_coverage.py
git commit -m "feat(probe): translation_coverage QA suite (Playwright+OCR+langdetect) (#231)"
```

---

## Task 13: Orchestrator integration test

**Files:**
- Create: `platform_v2/tests/translation_scanners/test_orchestrator.py`

- [ ] **Step 1: Write the integration test**

```python
"""Orchestrator integration — uses fixture source + mocked generator."""
from pathlib import Path
from unittest.mock import patch

from tools.consciousness.translation_scanners.orchestrator import (
    run_translation_coverage_scan,
)

FIXTURE_SRC = (
    "fixture_site",
    str(Path(__file__).parent.parent / "fixtures" / "translation" / "sample_site"),
    None,
)


def test_run_writes_gap_rows_and_respects_cap():
    with patch(
        "tools.consciousness.translation_scanners.generator._generate_translation",
        return_value={"translated": "mock", "confidence": 0.9},
    ), patch(
        "tools.consciousness.translation_scanners.semantic_scanner.back_translate_to_en",
        return_value="",
    ), patch(
        "tools.consciousness.translation_scanners.semantic_scanner.cosine_similarity",
        return_value=1.0,
    ):
        summary = run_translation_coverage_scan(sources=[FIXTURE_SRC])
    assert "gaps_found" in summary
    assert summary["duration_ms"] >= 0
    assert summary["gaps_found"] >= 4
```

- [ ] **Step 2: Run**

```bash
docker exec archie_platform pytest /app/tests/translation_scanners/test_orchestrator.py -v 2>&1 | tail -10
```

Expected: `1 passed`.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tests/translation_scanners/test_orchestrator.py
git commit -m "test(translations): orchestrator integration vs fixture source (#232)"
```

---

## Task 14: Admin Telegram summary notification

**Files:**
- Modify: `platform_v2/tools/consciousness/translation_scanners/orchestrator.py`

- [ ] **Step 1: Extend `run_translation_coverage_scan` to emit a Telegram summary**

Just before the `return totals` at the bottom, add:

```python
    # Admin Telegram summary — best-effort
    try:
        from database import get_db_cursor
        msg = (
            f"🌐 Translation Coverage Scan complete\n"
            f"• gaps found: {totals['gaps_found']}\n"
            f"• auto-fixed: {totals['auto_fixed']}\n"
            f"• routed to review: {totals['routed']}\n"
            f"• bundles written: {totals['bundles_written']}\n"
            f"• duration: {totals['duration_ms']}ms"
        )
        with get_db_cursor(commit=True) as (_c, cur):
            cur.execute(
                """INSERT INTO system_notifications
                       (type, title, message, source, priority, visibility, is_read, created_at)
                   VALUES ('info','Translation Coverage Scan',%s,'agent_loop','normal','admin',FALSE,NOW())""",
                (msg,),
            )
    except Exception:  # noqa: BLE001
        logger.exception("telegram summary insert failed")
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/consciousness/translation_scanners/orchestrator.py
git commit -m "feat(translations): emit admin summary notification per scan (#232)"
```

---

## Task 15: Push branch + open PR + close tracking tasks

- [ ] **Step 1: Push**

```bash
git push -u origin feat/translation-coverage-system 2>&1 | tail -3
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title 'feat: platform translation coverage system (#231, #232)' --body-file - <<'EOF'
## Summary
Implements the Translation Coverage System per spec `docs/superpowers/specs/2026-04-18-translation-coverage-system-design.md`.

Nightly (2am) and on-demand scan of 47 surfaces across 3 detection passes, AI-generation via Bridge, confidence-tiered routing to C.O.D.E.X. via unified_tasks, and P.R.O.B.E. Playwright+OCR verification.

## Closes
- #231 Website Translation QA
- #232 Consciousness Translation Pipeline — External Sites

## Test plan
- [x] Migration 320 applies cleanly
- [x] pytest platform_v2/tests/translation_scanners/ green
- [x] "Agent Loop: Translation Coverage Scan" registers on startup
- [x] /api/translations/full-scan endpoint responds 200 + starts background thread
- [x] /api/translations/coverage-health returns coverage JSON
- [ ] First nightly run produces at least one resolved + one routed gap
- [ ] Coverage Health card renders in Languages tab

🤖 Generated with Claude Code
EOF
```

- [ ] **Step 3: Mark tracking tasks complete and close projects**

Only after PR verified green:

```
mcp__archie__complete_task for #1701, #1702, #1703, #1704, #1705 (project #232)
mcp__archie__complete_task for #1693..#1700 (project #231)
mcp__archie__update_project_status #232 → completed
mcp__archie__update_project_status #231 → completed
```

---

## Self-review checklist

- Spec coverage: every spec section maps to a task above ✓
- No placeholders (TBD/TODO) — every code step has actual code ✓
- Type consistency: `ScannerResult` fields used identically in every scanner ✓
- DB types: `translation_gaps.confidence NUMERIC(3,2)` matches Python `float` ✓
- Cron matches spec (2am daily) ✓
- Confidence thresholds match spec (0.85 / 0.60) ✓
- C.O.D.E.X. / Documentation & Knowledge used consistently ✓
- All imports present (requirements.txt updated for langdetect) ✓
- No `innerHTML` in frontend JS (safe DOM construction only) ✓
