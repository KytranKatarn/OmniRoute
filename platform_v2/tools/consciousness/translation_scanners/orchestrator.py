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
from .generator import NIGHTLY_CAP, process_missing_gap_status

logger = logging.getLogger("agent_loop")

# Maps EXTERNAL_SCAN_SOURCES labels to their deploy context.
# After a successful bundle export, deploy_static is dispatched automatically.
_DEPLOY_CONTEXT_BY_LABEL: dict[str, dict] = {
    "website_kytranempowerment": {
        "domain": "kytranempowerment.com",
        "source_path": "/mnt/archie_brain/website/kytranempowerment.com",
        "changed_files": ["data/translations.json"],
        "verify_url": "https://kytranempowerment.com/data/translations.json",
        "is_translation": True,
    },
    "website_creed": {
        "domain": "creed-ai.org",
        "source_path": "/mnt/standalone/websites/creed-ai.org",
        "changed_files": ["data/translations.json"],
        "verify_url": "https://creed-ai.org/data/translations.json",
        "is_translation": True,
    },
    # WTF consumer — Flask app on Citadel, image-baked (NOT bind-mounted).
    # Corrected 2026-08-18 (#5792). This entry previously carried:
    #   source_path    /mnt/standalone/websites/what-the-fact.com  <- static site
    #                  frozen 2026-04-14, from before WTF became a Flask app
    #   container_name "wtf_consumer"                              <- NO SUCH
    #                  CONTAINER; the real one is compose-prefixed (verified by
    #                  docker ps on 100.64.0.10)
    #   changed_files  ["data/translations.json"]                  <- the dead
    #                  site's path shape; the app serves /static/data/
    # A deploy step targeting a container name that matches nothing cannot succeed
    # and reports nothing — the same silent-no-op class as #5750.
    #
    # Nothing exports here today: #5750 set the WTF bundle to None in
    # EXTERNAL_SCAN_SOURCES because the DB set and the hand-maintained repo file
    # are not supersets of one another. These fields are therefore unreachable —
    # corrected so the next person to re-enable a bundle does not inherit four
    # wrong values at once.
    "website_what_the_fact": {
        "domain": "what-the-fact.com",
        "source_path": "/mnt/archie_brain/what-the-fact",
        "changed_files": ["consumer/static/data/translations.json"],
        "verify_url": "https://what-the-fact.com/static/data/translations.json",
        "is_translation": True,
        "container_name": "what-the-fact-wtf-consumer-1",
        "_capability": "deploy_vps",
    },
    # Watch products — VPS containers, serve static/data/ path
    "product_civic_watch": {
        "domain": "civic.kytranempowerment.com",
        "source_path": "/mnt/standalone/kytran-civic-watch",
        "changed_files": ["static/data/translations.json"],
        "verify_url": "https://civic.kytranempowerment.com/data/translations.json",
        "is_translation": True,
        "container_name": "kytran_watch_api",
        "_capability": "deploy_vps",
    },
    "product_gov_watch": {
        "domain": "gov.kytranempowerment.com",
        "source_path": "/mnt/standalone/kytran-gov-watch",
        "changed_files": ["static/data/translations.json"],
        "verify_url": "https://gov.kytranempowerment.com/static/data/translations.json",
        "is_translation": True,
        "container_name": "kytran_gov_watch",
        "_capability": "deploy_vps",
    },
    "product_legal_watch": {
        "domain": "legal.kytranempowerment.com",
        "source_path": "/mnt/standalone/kytran-legal-watch",
        "changed_files": ["static/data/translations.json"],
        "verify_url": "https://legal.kytranempowerment.com/data/translations.json",
        "is_translation": True,
        "container_name": "kytran_legal_api",
        "_capability": "deploy_vps",
    },
    "product_market_watch": {
        "domain": "market.kytranempowerment.com",
        "source_path": "/mnt/standalone/kytran-market-watch",
        "changed_files": ["static/data/translations.json"],
        "verify_url": "https://market.kytranempowerment.com/static/data/translations.json",
        "is_translation": True,
        "container_name": "kytran_market_api",
        "_capability": "deploy_vps",
    },
}


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


def _stamp_semantic_reviewed(row_ids: list) -> int:
    """Mark rows as semantically reviewed NOW. Returns how many were stamped.

    This is the write half of the read at ``_semantic_candidate_rows`` (the
    ``last_semantic_review_at IS NULL OR < NOW() - 30 days`` predicate). Without it
    that predicate can never become false for a row the scanner checked, so the
    sweep re-attempts the same set on every run — measured 2026-09-07 as 34,343
    never-reviewed vs 4,018 reviewed, where all 4,018 were stamped by
    ``generator.py`` writing NEW translations, never by the scanner.

    Fail-SOFT: any error is logged and swallowed. A missed stamp costs a repeated
    review next run; an exception escaping here would abort the whole scan pass.
    """
    ids = [i for i in (row_ids or []) if i is not None]
    if not ids:
        return 0
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "UPDATE translations SET last_semantic_review_at = NOW() WHERE id = ANY(%s)",
                (ids,),
            )
            stamped = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        logger.info("[TranslationScan] semantic review stamped on %s row(s)", stamped)
        return stamped
    except Exception:  # noqa: BLE001
        logger.warning(
            "[TranslationScan] failed to stamp last_semantic_review_at on %s row(s); "
            "they stay eligible and will be re-reviewed next run",
            len(ids),
            exc_info=True,
        )
        return 0


def _load_open_missing_gaps(limit: int, source_labels: list) -> list:
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """SELECT id, source, language, key, gap_type
               FROM translation_gaps
               WHERE status='open' AND gap_type='missing'
                 AND source = ANY(%s)
               ORDER BY created_at ASC
               LIMIT %s""",
            (source_labels, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def _load_open_quality_gaps(limit: int, source_labels: list) -> list:
    """Open quality_suspect gaps that CAN be re-translated.

    Only those with a key + a live English source row — process_missing_gap
    regenerates the translation and re-gates it. Worst (lowest cosine) first.
    Scoped to the sources being scanned so a scoped/test run never touches
    gaps belonging to other sources.
    """
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """SELECT id, source, language, key, gap_type
               FROM translation_gaps tg
               WHERE status='open' AND gap_type='quality_suspect'
                 AND source = ANY(%s)
                 AND key IS NOT NULL AND key <> ''
                 AND EXISTS (SELECT 1 FROM translations en
                             WHERE en.source_label=tg.source
                               AND en.language='en' AND en.key=tg.key)
               ORDER BY confidence ASC, created_at ASC
               LIMIT %s""",
            (source_labels, limit),
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


def run_translation_coverage_scan(
    sources: Optional[list] = None,
    *,
    generate: bool = True,
    domain_audit: bool = True,
    deploy: bool = True,
) -> dict:
    """Full nightly sequence. Returns summary dict.

    The three keyword flags let a lightweight caller (e.g. the git-hook
    delegate) run a SCOPED, fast scan: pass a single-source ``sources`` list
    plus ``generate=False, domain_audit=False, deploy=False`` to detect+route
    gaps for the changed source only, skipping the global LLM generation pass
    (the multi-minute cost), the live domain audit (HTTP to every domain), and
    the bundle-export→deploy step. Defaults preserve the original full nightly
    behaviour byte-for-byte.
    """
    from tools.consciousness.language_routes import EXTERNAL_SCAN_SOURCES

    start = time.time()
    sources = sources or EXTERNAL_SCAN_SOURCES
    source_labels = [entry[0] for entry in sources]
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
        for result in DomainAuditScanner().scan() if domain_audit else []:
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

        batch_summary = route_domain_gaps_to_translate() if domain_audit else {"batches_sent": 0, "gaps_routed": 0}
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
            # Semantic quality pass back-translates via the LLM dispatcher —
            # the expensive bit. Skip it when generate=False (scoped git-hook
            # detection scan wants no LLM calls).
            rows = _semantic_candidate_rows(label) if generate else []
            scanner = SemanticScanner(source=label, rows=rows)
            try:
                for result in scanner.scan():
                    _upsert_gap(result)
                    totals["gaps_found"] += 1
            finally:
                # Stamp in a `finally`: those back-translations were DISPATCHED and
                # PAID FOR. If the loop dies partway, the rows it did evaluate were
                # still evaluated, and discarding the stamp only guarantees we spend
                # the same dispatches again on the next run — which is the exact
                # failure this fix exists to end.
                stamped = _stamp_semantic_reviewed(scanner.reviewed_ids)
                totals["semantic_reviewed"] = totals.get("semantic_reviewed", 0) + stamped
        except Exception:  # noqa: BLE001
            logger.exception("[TranslationScan] semantic pass failed for %s", label)

    # #5851 — BRAKES. This pass fired 2,152 translate dispatches in 48h with no
    # backpressure gate; the hub shed 1,117 of them at the 7B in-flight admission cap and
    # they were recorded as failures. The WTF producers got this same gate in #4536; this
    # one never did. Fail-OPEN (any error -> proceed), tunable via platform_settings with
    # no deploy, exactly as wtf_hub/routes.py uses it.
    totals["generation_deferred"] = 0
    if generate:
        try:
            from services.welfare_governance_service import in_flight_over_cap

            if in_flight_over_cap("translate"):
                logger.info("[TranslationScan] translate lane already saturated — skipping generation pass")
                generate = False
                totals["generation_deferred"] = -1  # -1 = never started
        except Exception:  # noqa: BLE001
            logger.warning("[TranslationScan] in-flight check failed; proceeding", exc_info=True)

    # Generation pass — cap at NIGHTLY_CAP.
    # Each gap is isolated: one translation failure must not abort the whole
    # scan (e.g. if the bridge dispatcher is unavailable for a single call).
    for gap in _load_open_missing_gaps(NIGHTLY_CAP, source_labels) if generate else []:
        try:
            status = process_missing_gap_status(gap)
            if status == "written":
                totals["auto_fixed"] += 1
            elif status == "deferred":
                # The hub shed this one. Continuing to fire into a saturated hub is what
                # produced 1,117 shed dispatches — stop the batch and leave the remaining
                # gaps OPEN for the next pass rather than converting them all into
                # "failures" that never get retried (#5851).
                totals["generation_deferred"] += 1
                logger.info(
                    "[TranslationScan] dispatch deferred (hub backpressure) at gap_id=%s — stopping generation pass",
                    gap.get("id"),
                )
                break
        except Exception:  # noqa: BLE001
            logger.exception(
                "[TranslationScan] process_missing_gap failed for gap_id=%s",
                gap.get("id"),
            )

    # Re-translation pass for genuine quality_suspect gaps (existing
    # low-quality translations). Same generate→gate→write→resolve path:
    # process_missing_gap overwrites the suspect text and marks the gap
    # resolved. Only runs on the full nightly (generate=True).
    totals["quality_retranslated"] = 0
    for gap in _load_open_quality_gaps(NIGHTLY_CAP, source_labels) if generate else []:
        try:
            if process_missing_gap_status(gap) == "written":
                totals["quality_retranslated"] += 1
                totals["auto_fixed"] += 1
        except Exception:  # noqa: BLE001
            logger.exception(
                "[TranslationScan] quality re-translate failed for gap_id=%s",
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
                if deploy and label in _DEPLOY_CONTEXT_BY_LABEL:
                    try:
                        from services.deploy_service import run_deploy_pipeline

                        deploy_ctx = dict(_DEPLOY_CONTEXT_BY_LABEL[label])
                        capability = deploy_ctx.pop("_capability", "deploy_static")
                        deploy_result = run_deploy_pipeline(capability, deploy_ctx)
                        if deploy_result.success:
                            logger.info("[TranslationScan] deploy_static succeeded for %s", label)
                        else:
                            logger.warning(
                                "[TranslationScan] deploy_static failed for %s: %s",
                                label,
                                deploy_result.error,
                            )
                    except Exception:  # noqa: BLE001 — deploy failure must not abort the scan
                        logger.exception("[TranslationScan] deploy failed for %s", label)
        except Exception as e:  # noqa: BLE001 — per-source export must not abort the scan
            logger.warning("[TranslationScan] bundle export failed for %s: %s", label, e)

    totals["duration_ms"] = int((time.time() - start) * 1000)
    logger.info("[TranslationScan] complete %s", totals)

    # The audit vault_note + admin notification summarise a FULL scan. A scoped
    # git-hook scan (generate=False) skips both: the audit title is date-only so
    # repeated same-day scoped scans collide on the unique index, and a "scan
    # complete" notice on every website commit would spam the admin feed.
    if generate:
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
