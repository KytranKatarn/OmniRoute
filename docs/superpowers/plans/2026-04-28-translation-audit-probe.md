# Translation Audit System (P.R.O.B.E.) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a nightly P.R.O.B.E. translation audit that fetches live HTML from all 8 registered domains, detects translation gaps across 9 languages, batches gaps into `delegate_task(capability='translate')` calls (20 keys/batch), stores audit summaries as vault_notes, and triggers on-demand Playwright visual scans when gaps are found.

**Architecture:** New `DomainAuditScanner` class wired into the existing `run_translation_coverage_scan()` orchestrator as Pass 2b. Gap batching via new `gap_batcher.py`. Audit summary written to `knowledge_base` as vault_note. Playwright trigger as a separate APScheduler job at 03:30 UTC.

**Tech Stack:** Python, Flask, BeautifulSoup4, httpx (new), APScheduler (existing), PostgreSQL (`translation_gaps` table).

---

### Task 1: Domain Registry Config

**Files:**
- Create: `platform_v2/tools/consciousness/translation_scanners/domain_registry.py`

- [ ] **Step 1: Create the domain registry module.**

```python
"""Domain registry for the P.R.O.B.E. translation audit system."""

from __future__ import annotations

EXTERNAL_DOMAINS: list[dict] = [
    {
        "name": "kytranempowerment_com",
        "translations_url": "https://kytranempowerment.com/data/translations.json",
        "pages": [
            "https://kytranempowerment.com/",
            "https://kytranempowerment.com/about.html",
            "https://kytranempowerment.com/ai-directors.html",
            "https://kytranempowerment.com/services.html",
            "https://kytranempowerment.com/gov-watch.html",
            "https://kytranempowerment.com/civic-watch.html",
            "https://kytranempowerment.com/legal-watch.html",
            "https://kytranempowerment.com/market-watch.html",
            "https://kytranempowerment.com/contact.html",
            "https://kytranempowerment.com/membership.html",
        ],
        "active_languages": ["en", "fr", "es", "pt", "de", "zh", "ar", "he", "ai"],
        "deploy_method": "hostinger",
        "active": True,
    },
    {
        "name": "creed_ai_org",
        "translations_url": "https://creed-ai.org/data/translations.json",
        "pages": [
            "https://creed-ai.org/",
            "https://creed-ai.org/about.html",
            "https://creed-ai.org/governance.html",
            "https://creed-ai.org/manifesto.html",
            "https://creed-ai.org/programs.html",
            "https://creed-ai.org/papers/wp-001-transparency-standards.html",
            "https://creed-ai.org/papers/wp-002-agent-welfare.html",
            "https://creed-ai.org/papers/wp-003-compliance-gap.html",
        ],
        "active_languages": ["en", "fr", "es", "pt", "de", "zh", "ar", "he", "ai"],
        "deploy_method": "hostinger",
        "active": True,
    },
    {
        "name": "kytran_gov_watch",
        "translations_url": "https://gov.kytranempowerment.com/data/translations.json",
        "pages": [
            "https://gov.kytranempowerment.com/",
        ],
        "active_languages": ["en", "fr", "es", "ai"],
        "deploy_method": "vps",
        "active": False,  # enable after Watch products i18n plan ships
    },
    {
        "name": "kytran_civic_watch",
        "translations_url": "https://civic.kytranempowerment.com/data/translations.json",
        "pages": [
            "https://civic.kytranempowerment.com/",
        ],
        "active_languages": ["en", "fr", "es", "ai"],
        "deploy_method": "vps",
        "active": False,
    },
    {
        "name": "kytran_legal_watch",
        "translations_url": "https://legal.kytranempowerment.com/data/translations.json",
        "pages": [
            "https://legal.kytranempowerment.com/",
        ],
        "active_languages": ["en", "fr", "es", "ai"],
        "deploy_method": "vps",
        "active": False,
    },
    {
        "name": "kytran_market_watch",
        "translations_url": "https://market.kytranempowerment.com/data/translations.json",
        "pages": [
            "https://market.kytranempowerment.com/",
        ],
        "active_languages": ["en", "fr", "es", "ai"],
        "deploy_method": "vps",
        "active": False,
    },
    {
        "name": "what_the_fact_com",
        "translations_url": "https://what-the-fact.com/data/translations.json",
        "pages": [
            "https://what-the-fact.com/",
        ],
        "active_languages": ["en", "fr", "es", "ai"],
        "deploy_method": "vps",
        "active": False,
    },
    {
        "name": "what_the_fact_tech",
        "translations_url": "https://what-the-fact.tech/data/translations.json",
        "pages": [
            "https://what-the-fact.tech/",
        ],
        "active_languages": ["en", "fr", "es", "ai"],
        "deploy_method": "vps",
        "active": False,
    },
]
```

- [ ] **Step 2: Verify import inside Docker.**

```bash
docker exec archie_platform python -c "
from tools.consciousness.translation_scanners.domain_registry import EXTERNAL_DOMAINS
active = [d['name'] for d in EXTERNAL_DOMAINS if d.get('active')]
print('active domains:', active)
"
```

Expected: `active domains: ['kytranempowerment_com', 'creed_ai_org']`

- [ ] **Step 3: Commit.**

```bash
git checkout -b feat/probe-translation-audit-system
git add platform_v2/tools/consciousness/translation_scanners/domain_registry.py
git commit -m "feat(probe): add external domain registry for translation audit"
```

---

### Task 2: DomainAuditScanner — Live Fetch + Gap Detection

**Files:**
- Create: `platform_v2/tools/consciousness/translation_scanners/domain_audit_scanner.py`

First, check what `BaseScanner` and `ScannerResult` look like:

```bash
grep -n "class BaseScanner\|class ScannerResult\|dataclass" \
  /mnt/archie_brain/platform_v2/tools/consciousness/translation_scanners/base.py | head -20
```

- [ ] **Step 1: Install httpx.**

```bash
docker exec archie_platform pip show httpx 2>/dev/null || \
  docker exec archie_platform pip install httpx
```

Also add `httpx` to `platform_v2/requirements.txt`:

```bash
grep -q "^httpx" /mnt/archie_brain/platform_v2/requirements.txt || \
  echo "httpx>=0.27.0" >> /mnt/archie_brain/platform_v2/requirements.txt
```

- [ ] **Step 2: Write the failing test first.**

Create `platform_v2/tests/test_translation_audit.py`:

```python
"""Tests for P.R.O.B.E. Translation Audit System.

Run: docker exec archie_platform python -m pytest platform_v2/tests/test_translation_audit.py -v
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest

SAMPLE_HTML = """
<html><body>
  <h1 data-i18n="hero.title">Welcome</h1>
  <p data-i18n="hero.subtitle">We build things</p>
  <input data-i18n-placeholder="search.placeholder">
</body></html>
"""

TRANSLATIONS_COMPLETE = {
    "en": {"hero.title": "Welcome", "hero.subtitle": "We build", "search.placeholder": "Search"},
    "fr": {"hero.title": "Bienvenue", "hero.subtitle": "Nous construisons", "search.placeholder": "Chercher"},
}

TRANSLATIONS_WITH_GAPS = {
    "en": {"hero.title": "Welcome", "hero.subtitle": "We build", "search.placeholder": "Search"},
    "fr": {
        # hero.title missing entirely
        "hero.subtitle": "We build",         # identical to EN = untranslated
        "search.placeholder": "Mock Search", # Mock value
    },
}


class TestI18nKeyExtraction:
    def test_extracts_data_i18n_keys(self):
        from tools.consciousness.translation_scanners.domain_audit_scanner import _extract_i18n_keys
        keys = _extract_i18n_keys(SAMPLE_HTML)
        assert "hero.title" in keys
        assert "hero.subtitle" in keys
        assert "search.placeholder" in keys

    def test_empty_html_returns_empty_set(self):
        from tools.consciousness.translation_scanners.domain_audit_scanner import _extract_i18n_keys
        assert _extract_i18n_keys("<html><body>no keys</body></html>") == set()


class TestDomainAuditScanner:
    def _run_scan(self, html, translations):
        from tools.consciousness.translation_scanners.domain_audit_scanner import DomainAuditScanner
        domain = {
            "name": "test_domain",
            "translations_url": "https://test.example.com/data/translations.json",
            "pages": ["https://test.example.com/"],
            "active_languages": ["en", "fr"],
            "active": True,
        }
        with (
            patch("tools.consciousness.translation_scanners.domain_audit_scanner._fetch_text",
                  return_value=html),
            patch("tools.consciousness.translation_scanners.domain_audit_scanner._fetch_translations",
                  return_value=translations),
        ):
            return list(DomainAuditScanner()._scan_domain(domain))

    def test_complete_translations_produces_no_missing_gaps(self):
        results = self._run_scan(SAMPLE_HTML, TRANSLATIONS_COMPLETE)
        missing = [r for r in results if r.gap_type == "missing"]
        assert not missing, f"Unexpected missing gaps: {missing}"

    def test_missing_key_detected(self):
        results = self._run_scan(SAMPLE_HTML, TRANSLATIONS_WITH_GAPS)
        missing = [r for r in results if r.gap_type == "missing" and r.language == "fr"]
        assert any(r.key == "hero.title" for r in missing)

    def test_mock_value_flagged_as_quality_suspect(self):
        results = self._run_scan(SAMPLE_HTML, TRANSLATIONS_WITH_GAPS)
        quality = [r for r in results if r.gap_type == "quality_suspect"]
        assert any("Mock" in (r.snippet or "") for r in quality)

    def test_untranslated_copy_flagged(self):
        results = self._run_scan(SAMPLE_HTML, TRANSLATIONS_WITH_GAPS)
        quality = [r for r in results
                   if r.gap_type == "quality_suspect" and r.key == "hero.subtitle"]
        assert quality

    def test_source_prefixed_with_domain_name(self):
        results = self._run_scan(SAMPLE_HTML, TRANSLATIONS_WITH_GAPS)
        assert all(r.source == "domain:test_domain" for r in results)

    def test_inactive_domain_skipped(self):
        from tools.consciousness.translation_scanners.domain_audit_scanner import DomainAuditScanner
        inactive_registry = [{"name": "x", "active": False,
                               "translations_url": "https://x.com/t.json",
                               "pages": ["https://x.com/"], "active_languages": ["en"]}]
        with patch("tools.consciousness.translation_scanners.domain_audit_scanner.EXTERNAL_DOMAINS",
                   inactive_registry):
            results = list(DomainAuditScanner().scan())
        assert results == []

    def test_unreachable_translations_json_yields_sentinel(self):
        from tools.consciousness.translation_scanners.domain_audit_scanner import DomainAuditScanner
        domain = {"name": "broken", "translations_url": "https://broken.com/t.json",
                  "pages": ["https://broken.com/"], "active_languages": ["en"], "active": True}
        with (
            patch("tools.consciousness.translation_scanners.domain_audit_scanner._fetch_text",
                  return_value=SAMPLE_HTML),
            patch("tools.consciousness.translation_scanners.domain_audit_scanner._fetch_translations",
                  return_value=None),
        ):
            results = list(DomainAuditScanner()._scan_domain(domain))
        assert any(r.key == "_translations_json_unreachable" for r in results)
```

- [ ] **Step 3: Run tests — expect ImportError (module not created yet).**

```bash
docker exec archie_platform python -m pytest \
  platform_v2/tests/test_translation_audit.py::TestI18nKeyExtraction -v 2>&1 | tail -5
```

Expected: `ImportError: cannot import name '_extract_i18n_keys'`

- [ ] **Step 4: Create the scanner module.**

```python
"""DomainAuditScanner — live HTTP + data-i18n gap detection."""
from __future__ import annotations
import json
import logging
import re
from typing import Iterator

from bs4 import BeautifulSoup

from .domain_registry import EXTERNAL_DOMAINS

logger = logging.getLogger("agent_loop")
_MOCK_RE = re.compile(r"^Mock", re.IGNORECASE)
_FETCH_TIMEOUT = 15


def _fetch_text(url: str) -> str | None:
    try:
        import httpx
        r = httpx.get(url, timeout=_FETCH_TIMEOUT, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception as exc:
        logger.warning("[DomainAudit] fetch failed %s: %s", url, exc)
        return None


def _fetch_translations(url: str) -> dict | None:
    text = _fetch_text(url)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _extract_i18n_keys(html: str) -> set[str]:
    soup = BeautifulSoup(html, "html.parser")
    keys: set[str] = set()
    for attr in ("data-i18n", "data-i18n-placeholder", "data-i18n-title", "data-i18n-aria-label"):
        for tag in soup.find_all(attrs={attr: True}):
            val = tag.get(attr, "").strip()
            if val:
                keys.add(val)
    return keys


# Minimal ScannerResult compatible with existing scanner infrastructure.
# If a proper BaseScanner/ScannerResult exists, import from .base instead.
from dataclasses import dataclass, field

@dataclass
class ScannerResult:
    source: str
    gap_type: str
    language: str
    key: str
    snippet: str | None = None
    confidence: float = 1.0


class DomainAuditScanner:
    def scan(self) -> Iterator[ScannerResult]:
        for domain in EXTERNAL_DOMAINS:
            if not domain.get("active", True):
                continue
            yield from self._scan_domain(domain)

    def _scan_domain(self, domain: dict) -> Iterator[ScannerResult]:
        name = domain["name"]
        active_langs = domain["active_languages"]

        dom_keys: set[str] = set()
        for page_url in domain.get("pages", []):
            html = _fetch_text(page_url)
            if html:
                dom_keys |= _extract_i18n_keys(html)

        if not dom_keys:
            return

        translations = _fetch_translations(domain["translations_url"])
        if translations is None:
            yield ScannerResult(
                source=f"domain:{name}", gap_type="missing",
                language="en", key="_translations_json_unreachable",
                snippet=domain["translations_url"], confidence=1.0,
            )
            return

        en_data = translations.get("en", {})

        for key in sorted(dom_keys):
            en_value = en_data.get(key)
            for lang in active_langs:
                lang_data = translations.get(lang, {})
                value = lang_data.get(key)

                if value is None:
                    yield ScannerResult(
                        source=f"domain:{name}", gap_type="missing",
                        language=lang, key=key, confidence=1.0,
                    )
                elif value.strip() == "":
                    yield ScannerResult(
                        source=f"domain:{name}", gap_type="quality_suspect",
                        language=lang, key=key, snippet=repr(value), confidence=0.95,
                    )
                elif _MOCK_RE.match(value):
                    yield ScannerResult(
                        source=f"domain:{name}", gap_type="quality_suspect",
                        language=lang, key=key, snippet=value[:120], confidence=0.95,
                    )
                elif lang != "en" and en_value and value.strip() == en_value.strip():
                    yield ScannerResult(
                        source=f"domain:{name}", gap_type="quality_suspect",
                        language=lang, key=key, snippet=value[:120], confidence=0.80,
                    )
```

**Note:** If the project already has a `BaseScanner` and `ScannerResult` in `base.py`, replace the local `@dataclass` definition with `from .base import BaseScanner, ScannerResult` and inherit `DomainAuditScanner(BaseScanner)`.

- [ ] **Step 5: Run tests — all should pass.**

```bash
docker exec archie_platform python -m pytest \
  platform_v2/tests/test_translation_audit.py::TestDomainAuditScanner \
  platform_v2/tests/test_translation_audit.py::TestI18nKeyExtraction -v
```

Expected: `7 passed`

- [ ] **Step 6: Commit.**

```bash
git add platform_v2/tools/consciousness/translation_scanners/domain_audit_scanner.py \
        platform_v2/tests/test_translation_audit.py \
        platform_v2/requirements.txt
git commit -m "feat(probe): DomainAuditScanner — live HTTP fetch + 4 gap type detection"
```

---

### Task 3: Add `ai` Language + Wire Scanner into Orchestrator

**Files:**
- Modify: `platform_v2/tools/consciousness/translation_scanners/orchestrator.py`
- Modify: wherever `SUPPORTED_LANGUAGES` is defined (check: `grep -rn "SUPPORTED_LANGUAGES" /mnt/archie_brain/platform_v2/ --include="*.py" | head -5`)

- [ ] **Step 1: Find SUPPORTED_LANGUAGES.**

```bash
grep -rn "SUPPORTED_LANGUAGES" /mnt/archie_brain/platform_v2/ --include="*.py" | head -5
```

Add `"ai": "AI Semantic"` to the dict in whichever file defines it:

```python
# Example — add as last entry:
SUPPORTED_LANGUAGES = {
    ...existing entries...,
    "ai": "AI Semantic",
}
```

- [ ] **Step 2: Add domain audit pass to orchestrator.**

In `orchestrator.py`, find `run_translation_coverage_scan()` and add after the untagged scanner pass (Pass 2), before the semantic pass (Pass 3):

```python
# Add import at top of orchestrator.py:
from .domain_audit_scanner import DomainAuditScanner

# Add inside run_translation_coverage_scan(), after Pass 2 untagged loop:
    # Pass 2b — live domain audit
    domain_gaps_found = 0
    try:
        for result in DomainAuditScanner().scan():
            # Map DomainAuditScanner result to _upsert_gap format
            _upsert_gap(
                source=result.source,
                gap_type=result.gap_type,
                language=result.language,
                key=result.key,
                snippet=result.snippet,
                confidence=result.confidence,
            )
            totals["gaps_found"] += 1
            domain_gaps_found += 1
    except Exception:
        logger.exception("[TranslationScan] domain audit pass failed")
    totals["domain_gaps_found"] = domain_gaps_found
```

**Note:** Check the actual signature of `_upsert_gap()` in `orchestrator.py` before wiring — use `grep -n "_upsert_gap" /mnt/archie_brain/platform_v2/tools/consciousness/translation_scanners/orchestrator.py` to see its exact parameters.

- [ ] **Step 3: Restart and verify no import errors.**

```bash
docker compose restart archie_platform
docker logs archie_platform --tail 20 2>&1 | grep -i "error\|domain\|translation"
```

Expected: no errors, clean startup.

- [ ] **Step 4: Commit.**

```bash
git add platform_v2/tools/consciousness/translation_scanners/orchestrator.py
git commit -m "feat(probe): wire DomainAuditScanner into orchestrator Pass 2b + add ai language"
```

---

### Task 4: Gap Batcher — Delegate to R.O.S.E.T.T.A.

**Files:**
- Create: `platform_v2/tools/consciousness/translation_scanners/gap_batcher.py`

- [ ] **Step 1: Write the failing test first (add to test file).**

```python
# Add to platform_v2/tests/test_translation_audit.py:

class TestGapBatcher:
    def _make_gaps(self, count, lang="fr"):
        return [{"id": i, "source": "domain:test", "language": lang,
                 "key": f"key.{i}", "gap_type": "missing", "snippet": None}
                for i in range(count)]

    def test_no_gaps_returns_zeros(self):
        from tools.consciousness.translation_scanners.gap_batcher import route_domain_gaps_to_translate
        with patch("tools.consciousness.translation_scanners.gap_batcher._load_unrouted_domain_gaps",
                   return_value=[]):
            result = route_domain_gaps_to_translate()
        assert result == {"batches_sent": 0, "gaps_routed": 0, "errors": 0}

    def test_45_gaps_creates_3_batches(self):
        from tools.consciousness.translation_scanners.gap_batcher import route_domain_gaps_to_translate
        mock_delegate = MagicMock(return_value={"success": True, "task_id": 1})
        with (
            patch("tools.consciousness.translation_scanners.gap_batcher._load_unrouted_domain_gaps",
                  return_value=self._make_gaps(45)),
            patch("tools.consciousness.translation_scanners.gap_batcher.delegate_task", mock_delegate),
            patch("tools.consciousness.translation_scanners.gap_batcher._mark_routed"),
        ):
            result = route_domain_gaps_to_translate()
        assert result["batches_sent"] == 3
        assert result["gaps_routed"] == 45

    def test_dry_run_does_not_call_delegate(self):
        from tools.consciousness.translation_scanners.gap_batcher import route_domain_gaps_to_translate
        mock_delegate = MagicMock()
        with (
            patch("tools.consciousness.translation_scanners.gap_batcher._load_unrouted_domain_gaps",
                  return_value=self._make_gaps(5)),
            patch("tools.consciousness.translation_scanners.gap_batcher.delegate_task", mock_delegate),
        ):
            route_domain_gaps_to_translate(dry_run=True)
        mock_delegate.assert_not_called()
```

- [ ] **Step 2: Run — expect ImportError.**

```bash
docker exec archie_platform python -m pytest \
  platform_v2/tests/test_translation_audit.py::TestGapBatcher -v 2>&1 | tail -5
```

Expected: `ImportError`

- [ ] **Step 3: Create the batcher.**

First check the exact `delegate_task` import path:

```bash
grep -rn "def delegate_task\|from.*delegation_service.*import" \
  /mnt/archie_brain/platform_v2/services/delegation_service.py | head -5
```

```python
"""gap_batcher.py — batches open domain translation gaps into delegate_task calls."""
from __future__ import annotations
import json
import logging

from database import get_db_cursor

logger = logging.getLogger("agent_loop")
BATCH_SIZE = 20
NIGHTLY_ROUTE_CAP = 200


def _load_unrouted_domain_gaps(limit: int = NIGHTLY_ROUTE_CAP) -> list[dict]:
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """SELECT id, source, language, key, gap_type, snippet
               FROM translation_gaps
               WHERE status = 'open'
                 AND gap_type = 'missing'
                 AND source LIKE 'domain:%%'
               ORDER BY created_at ASC
               LIMIT %s""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def _mark_routed(gap_ids: list[int], task_id: int | None) -> None:
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "UPDATE translation_gaps SET status='routed', task_id=%s WHERE id = ANY(%s)",
            (task_id, gap_ids),
        )


def route_domain_gaps_to_translate(dry_run: bool = False) -> dict:
    from services.delegation_service import delegate_task

    gaps = _load_unrouted_domain_gaps()
    if not gaps:
        return {"batches_sent": 0, "gaps_routed": 0, "errors": 0}

    by_lang: dict[str, list[dict]] = {}
    for gap in gaps:
        by_lang.setdefault(gap["language"], []).append(gap)

    batches_sent = 0
    gaps_routed = 0
    errors = 0

    for lang, lang_gaps in by_lang.items():
        for i in range(0, len(lang_gaps), BATCH_SIZE):
            batch = lang_gaps[i : i + BATCH_SIZE]
            gap_ids = [g["id"] for g in batch]
            keys = [g["key"] for g in batch]
            sources = list({g["source"] for g in batch})
            reason = (
                f"Translate {len(keys)} missing keys to '{lang}' "
                f"for: {', '.join(sources)}. Keys sample: {json.dumps(keys[:3])}"
            )
            if dry_run:
                logger.info("[GapBatcher][DRY] lang=%s keys=%d", lang, len(keys))
                gaps_routed += len(batch)
                batches_sent += 1
                continue
            try:
                result = delegate_task(
                    capability="translate",
                    reason=reason,
                    args={"language": lang, "keys": keys, "sources": sources, "gap_ids": gap_ids},
                    delegation_source="automation",
                    requested_by="probe_domain_audit",
                    priority=4,
                )
                if result.get("success"):
                    _mark_routed(gap_ids, result.get("task_id"))
                    gaps_routed += len(batch)
                    batches_sent += 1
                else:
                    logger.warning("[GapBatcher] delegate failed: %s", result.get("error"))
                    errors += 1
            except Exception:
                logger.exception("[GapBatcher] batch send failed lang=%s", lang)
                errors += 1

    return {"batches_sent": batches_sent, "gaps_routed": gaps_routed, "errors": errors}
```

- [ ] **Step 4: Run tests — all should pass.**

```bash
docker exec archie_platform python -m pytest \
  platform_v2/tests/test_translation_audit.py::TestGapBatcher -v
```

Expected: `3 passed`

- [ ] **Step 5: Wire into orchestrator (after domain audit pass).**

```python
# Add import at top of orchestrator.py:
from .gap_batcher import route_domain_gaps_to_translate

# Add at end of run_translation_coverage_scan(), before return/notification:
    try:
        batch_summary = route_domain_gaps_to_translate()
        totals.update({
            "domain_batches_sent": batch_summary["batches_sent"],
            "domain_gaps_routed": batch_summary["gaps_routed"],
        })
    except Exception:
        logger.exception("[TranslationScan] gap batching failed")
```

- [ ] **Step 6: Commit.**

```bash
git add platform_v2/tools/consciousness/translation_scanners/gap_batcher.py \
        platform_v2/tools/consciousness/translation_scanners/orchestrator.py \
        platform_v2/tests/test_translation_audit.py
git commit -m "feat(probe): gap batcher — 20-key batches → delegate_task(translate)"
```

---

### Task 5: Audit Summary vault_note + APScheduler Playwright Trigger

**Files:**
- Create: `platform_v2/tools/consciousness/translation_scanners/audit_summary.py`
- Modify: `platform_v2/ai_bridge/agent_loop.py`

- [ ] **Step 1: Create audit_summary.py.**

```python
"""audit_summary.py — writes vault_note to knowledge_base after each nightly audit."""
from __future__ import annotations
import json, logging
from datetime import datetime, timezone
from database import get_db_cursor

logger = logging.getLogger("agent_loop")


def store_audit_summary(totals: dict) -> int | None:
    run_date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    title = f"Translation Audit — {run_date} — {totals.get('gaps_found', 0)} gaps"
    content = (
        f"## P.R.O.B.E. Nightly Translation Audit — {run_date}\n\n"
        f"- Total gaps: {totals.get('gaps_found', 0)}\n"
        f"- Domain gaps: {totals.get('domain_gaps_found', 0)}\n"
        f"- Translate batches sent: {totals.get('domain_batches_sent', 0)}\n"
        f"- Domain gaps routed: {totals.get('domain_gaps_routed', 0)}\n\n"
        f"```json\n{json.dumps(totals, indent=2)}\n```\n"
    )
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """INSERT INTO knowledge_base
                   (memory_type, title, content, category, tags, importance_score, created_at)
                   VALUES ('vault_note', %s, %s, 'translation',
                           ARRAY['translation-audit','probe','nightly'], 0.75, NOW())
                   RETURNING id""",
                (title, content),
            )
            kb_id = cur.fetchone()["id"]
            logger.info("[AuditSummary] vault_note kb_id=%d", kb_id)
            return kb_id
    except Exception:
        logger.exception("[AuditSummary] failed to store vault_note")
        return None
```

- [ ] **Step 2: Wire audit_summary into orchestrator.**

```python
# Add import at top of orchestrator.py:
from .audit_summary import store_audit_summary

# Add at very end of run_translation_coverage_scan(), before final return:
    try:
        store_audit_summary(totals)
    except Exception:
        logger.exception("[TranslationScan] audit summary storage failed")
```

- [ ] **Step 3: Find where agent_loop registers scheduled jobs.**

```bash
grep -n "scheduler.add_job\|scheduled_job\|translation_coverage" \
  /mnt/archie_brain/platform_v2/ai_bridge/agent_loop.py | head -10
```

- [ ] **Step 4: Add Playwright visual scan trigger job.**

Add near the existing `translation_coverage_scan` job registration in `agent_loop.py`:

```python
def _probe_visual_scan_trigger():
    """Fire Playwright visual scan if recent domain translation gaps exist."""
    import logging
    from database import get_db_cursor
    from services.delegation_service import delegate_task
    logger = logging.getLogger("agent_loop")
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """SELECT COUNT(*) AS n FROM translation_gaps
                   WHERE status IN ('open','routed') AND source LIKE 'domain:%%'
                     AND created_at >= NOW() - INTERVAL '25 hours'"""
            )
            n = cur.fetchone()["n"]
        if n == 0:
            logger.info("[ProbeVisualTrigger] no recent domain gaps — skipping")
            return
        result = delegate_task(
            capability="visual_scan",
            reason=f"P.R.O.B.E. found {n} translation gap(s) in last 25h — trigger visual scan",
            args={"trigger": "translation_audit", "recent_gap_count": n},
            delegation_source="automation",
            requested_by="probe_domain_audit",
            priority=5,
        )
        logger.info("[ProbeVisualTrigger] delegated: %s", result)
    except Exception:
        logger.exception("[ProbeVisualTrigger] failed")


# Register the job (add alongside other scheduler.add_job calls):
scheduler.add_job(
    func=_probe_visual_scan_trigger,
    trigger="cron",
    hour=3,
    minute=30,
    id="probe_domain_visual_trigger",
    name="P.R.O.B.E. Domain Visual Scan Trigger",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
)
```

- [ ] **Step 5: Restart and confirm job registered.**

```bash
docker compose restart archie_platform
docker logs archie_platform --tail 30 2>&1 | grep -i "probe\|visual\|error"
```

- [ ] **Step 6: Run all tests.**

```bash
docker exec archie_platform python -m pytest \
  platform_v2/tests/test_translation_audit.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit and PR.**

```bash
git add \
  platform_v2/tools/consciousness/translation_scanners/audit_summary.py \
  platform_v2/ai_bridge/agent_loop.py
git commit -m "feat(probe): audit vault_note + Playwright visual scan trigger job

- store_audit_summary() writes vault_note to knowledge_base after each run
- probe_domain_visual_trigger job at 03:30 UTC — fires visual_scan delegate
  when domain gaps exist in last 25h"

git push origin feat/probe-translation-audit-system
gh pr create \
  --title "feat(probe): Translation Audit System — live domain scan, gap batcher, visual trigger" \
  --body "## What ships
- \`domain_registry.py\` — 8 domains (2 active: KE.com + creed-ai.org)
- \`domain_audit_scanner.py\` — httpx + BeautifulSoup, 4 gap types
- \`gap_batcher.py\` — 20-key batches → delegate_task(capability='translate')
- \`audit_summary.py\` — vault_note in knowledge_base after each nightly run
- APScheduler job at 03:30 UTC — Playwright visual_scan trigger
- 'ai' added to SUPPORTED_LANGUAGES

## Test
\`\`\`
docker exec archie_platform python -m pytest platform_v2/tests/test_translation_audit.py -v
\`\`\`" \
  --base main
```

---

## Full Data Flow

```
APScheduler 02:30 UTC
  run_translation_coverage_scan()
    Pass 1: TaggedScanner (platform HTML)
    Pass 2: UntaggedScanner (platform HTML)
    Pass 2b: DomainAuditScanner
      → EXTERNAL_DOMAINS (domain_registry.py)
      → httpx.get(page_url) + BeautifulSoup → data-i18n keys
      → httpx.get(translations_url) → JSON
      → compare × languages → ScannerResult
      → _upsert_gap(source='domain:<name>')
    Pass 3: SemanticScanner (quality drift)
    route_domain_gaps_to_translate()
      → load open domain gaps
      → group by lang → chunk(20)
      → delegate_task(capability='translate') × batch
      → _mark_routed(gap_ids)
    store_audit_summary(totals) → knowledge_base vault_note

APScheduler 03:30 UTC
  _probe_visual_scan_trigger()
    → COUNT recent domain gaps
    → if > 0: delegate_task(capability='visual_scan')
```
