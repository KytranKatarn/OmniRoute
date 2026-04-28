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
               ON CONFLICT ON CONSTRAINT translation_gaps_unique_key
               DO UPDATE SET
                    snippet        = EXCLUDED.snippet,
                    confidence     = EXCLUDED.confidence,
                    status         = CASE WHEN translation_gaps.status = 'resolved'
                                          THEN 'open'
                                          ELSE translation_gaps.status END""",
            (
                result.source,
                result.gap_type,
                result.language,
                result.key,
                result.file_path,
                result.line_number,
                result.snippet,
                result.suggested_key,
                result.confidence,
            ),
        )


def _semantic_candidate_rows(source: str) -> list:
    """Load rows needing semantic review for a given product/site.

    Returns list of dicts with keys: id, language, key, text, source_en_text.
    """
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """SELECT t.id, t.language, t.key, t.text,
                      en.text AS source_en_text
               FROM translations t
               LEFT JOIN translations en
                   ON en.source_label = t.source_label
                  AND en.key = t.key
                  AND en.language = 'en'
               WHERE t.source_label = %s
                 AND t.language <> 'en'
                 AND (t.last_semantic_review_at IS NULL
                      OR t.last_semantic_review_at < NOW() - INTERVAL '30 days')
               LIMIT 500""",
            (source,),
        )
        return [dict(r) for r in cur.fetchall()]


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
        return [dict(r) for r in cur.fetchall()]


def _export_bundle(source: str, bundle_path: str) -> Optional[int]:
    """Write translations.json for this product/site. Return count written."""
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """SELECT language, key, text FROM translations
               WHERE source_label=%s AND status='approved'""",
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
    """Full nightly sequence. Returns summary dict."""
    from tools.consciousness.language_routes import EXTERNAL_SCAN_SOURCES

    start = time.time()
    sources = sources or EXTERNAL_SCAN_SOURCES
    totals = {"gaps_found": 0, "auto_fixed": 0, "routed": 0, "bundles_written": 0}

    # Pass 1 + Pass 2: tagged + untagged per source
    for entry in sources:
        label, directory, _bundle_path = entry
        if not os.path.isdir(directory):
            logger.warning("[TranslationScan] skip missing source %s", directory)
            continue
        for result in TaggedScanner(source=label).scan():
            _upsert_gap(result)
            totals["gaps_found"] += 1
        for result in UntaggedScanner(source=label, directory=directory).scan():
            _upsert_gap(result)
            totals["gaps_found"] += 1

    # Pass 2b: live domain audit (HTTP fetch + data-i18n key extraction)
    # Runs against all active EXTERNAL_DOMAINS. Isolated so a network failure
    # on one domain does not abort the rest of the scan.
    try:
        from .domain_audit_scanner import DomainAuditScanner

        domain_gaps = 0
        for result in DomainAuditScanner().scan():
            _upsert_gap(result)
            totals["gaps_found"] += 1
            domain_gaps += 1
        totals["domain_gaps_found"] = domain_gaps
        logger.info("[TranslationScan] domain audit: %d gaps found", domain_gaps)
    except Exception:  # noqa: BLE001
        logger.exception("[TranslationScan] domain audit pass failed")

    # Gap routing — batch domain gaps to R.O.S.E.T.T.A. via delegate_task
    try:
        from .gap_batcher import route_domain_gaps_to_translate

        batch_summary = route_domain_gaps_to_translate()
        totals["domain_batches_sent"] = batch_summary["batches_sent"]
        totals["domain_gaps_routed"] = batch_summary["gaps_routed"]
        logger.info("[TranslationScan] gap batcher: %s", batch_summary)
    except Exception:  # noqa: BLE001
        logger.exception("[TranslationScan] gap batching failed")

    # Pass 3: semantic quality on stale rows. Semantic scan depends on the
    # embedding model and the back-translation dispatcher — both can fail
    # transiently. Isolate per-source so one bad source doesn't abort the
    # whole pass.
    for entry in sources:
        label = entry[0]
        try:
            rows = _semantic_candidate_rows(label)
            for result in SemanticScanner(source=label, rows=rows).scan():
                _upsert_gap(result)
                totals["gaps_found"] += 1
        except Exception:  # noqa: BLE001
            logger.exception("[TranslationScan] semantic pass failed for %s", label)

    # Generation pass — cap at NIGHTLY_CAP.
    # Each gap is isolated: one translation failure must not abort the whole
    # scan (e.g. if the bridge dispatcher is unavailable for a single call).
    for gap in _load_open_missing_gaps(NIGHTLY_CAP):
        try:
            if process_missing_gap(gap):
                totals["auto_fixed"] += 1
        except Exception:  # noqa: BLE001
            logger.exception(
                "[TranslationScan] process_missing_gap failed for gap_id=%s",
                gap.get("id"),
            )

    # Routed count (after generation writes)
    with get_db_cursor() as (_conn, cur):
        cur.execute("SELECT COUNT(*) AS n FROM translation_gaps WHERE status='routed' AND resolved_at IS NULL")
        totals["routed"] = cur.fetchone()["n"]

    # Bundle export — only for sources with a bundle path
    for entry in sources:
        label, _directory, bundle_path = entry
        if not bundle_path:
            continue
        try:
            count = _export_bundle(label, bundle_path)
            if count is not None:
                totals["bundles_written"] += 1
        except Exception as e:  # noqa: BLE001 — per-source export must not abort the scan
            logger.warning("[TranslationScan] bundle export failed for %s: %s", label, e)

    totals["duration_ms"] = int((time.time() - start) * 1000)
    logger.info("[TranslationScan] complete %s", totals)

    # Store audit vault_note in knowledge_base
    try:
        from .audit_summary import store_audit_summary

        store_audit_summary(totals)
    except Exception:  # noqa: BLE001
        logger.exception("[TranslationScan] audit summary storage failed")

    # Admin Telegram summary — best-effort
    try:
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

    return totals
