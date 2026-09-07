"""Semantic scanner — back-translate + cosine + residue regex."""

from __future__ import annotations

import logging
import re
from typing import Iterator, List, Dict

from .base import BaseScanner, ScannerResult

logger = logging.getLogger("agent_loop")

# #6648: one warm-up warning per process. cosine_similarity runs ~1,081 times a
# night; a per-call WARNING would replace a silent bug with an unreadable log.
_warmup_warned = False


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
    """Dispatch Bridge back-translation. Out-of-module so tests can mock.

    Uses the same per-language specialist as the forward translation so the QA
    signal is as strong as the model that produced the text (gemma3 for ar/he/de,
    mistral otherwise). gemma3 uses raw-text mode (no JSON envelope).
    """
    from tools.department_hq.services.department_dispatcher import dispatch, dispatch_json

    from .generator import _RAW_OUTPUT_MODELS, get_translate_routing

    model, agent = get_translate_routing(source_lang)

    if model in _RAW_OUTPUT_MODELS:
        prompt = (
            f"Translate the following {source_lang} text literally to English. "
            f"Output ONLY the English translation, nothing else.\n\nTEXT: {non_en_text}"
        )
        try:
            r = dispatch(
                capability="translate",
                prompt=prompt,
                module_id="coverage_scan",
                prefer_agent=agent,
                model_override=model,
                local_only=True,
            )
            raw = (getattr(r, "response", "") or "").strip().strip('"').strip()
            return raw.splitlines()[0].strip() if raw else ""
        except Exception:
            return ""

    prompt = (
        f"Translate the following {source_lang} text literally to English. "
        f'Respond ONLY with JSON: {{"en": "..."}}.\n\n'
        f"TEXT: {non_en_text}"
    )
    result = dispatch_json(
        capability="translate",
        prompt=prompt,
        module_id="coverage_scan",
        prefer_agent=agent,
        model_override=model,
        local_only=True,
    )
    if isinstance(result, dict):
        return result.get("en") or ""
    return ""


def cosine_similarity(a: str, b: str) -> float:
    """Via existing embedding service. Out-of-module so tests can mock.

    Routes model warm-up through Dept HQ's model_service (same path the
    dispatcher uses) so the embedding model is prepared before inference.
    """
    from ai_bridge.embedding_service import generate_embedding

    try:
        from services.model_service import get_model_service
        import os

        embed_model = os.getenv("OLLAMA_EMBEDDING_MODEL", "arctic-embed-cpu")
        get_model_service().ensure_model_ready("coverage_scan", embed_model)
    except Exception as _warm_exc:  # noqa: BLE001 — best-effort warmup, embedding_service still tries
        # #6648: this used to be a bare `pass`, which is why a warm-up that failed
        # on EVERY call went unnoticed for months — the only trace was a wall of
        # ERROR lines from model_service itself.
        #
        # Deliberately ONE warning per process, not per call: this runs ~1,081
        # times a night, and a per-call WARNING would simply replace a silent bug
        # with an unreadable log. Best-effort stays best-effort — the embedding
        # call below still works whether or not the warm-up did.
        global _warmup_warned
        if not _warmup_warned:
            _warmup_warned = True
            logger.warning(
                "cosine_similarity: embedding warm-up failed (%s) — continuing without it. "
                "This is logged ONCE per process; see #6648.",
                _warm_exc,
            )
        else:
            logger.debug("cosine_similarity: embedding warm-up failed again: %s", _warm_exc)

    va = generate_embedding(a)
    vb = generate_embedding(b)
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
        # Row ids this scan ACTUALLY evaluated (got a real back-translation for).
        # The caller stamps translations.last_semantic_review_at on these.
        #
        # WHY THIS EXISTS (#6648, measured 2026-09-07): orchestrator.py:148-149
        # SELECTS candidates on `last_semantic_review_at IS NULL OR < NOW() - 30 days`,
        # but nothing in the QA path ever WROTE that column — the only writers are
        # generator.py:282/289, which fire when a NEW translation is created. So this
        # sweep re-attempted the same rows on every run, forever: 34,343 never-reviewed
        # vs 4,018 reviewed, and every one of the 4,018 was stamped by the generator,
        # not by this scanner.
        #
        # That non-convergence is what pushed ~13,000 translate dispatches/30d at the
        # hub and produced 6,309 admission-cap sheds — against a translation corpus that
        # is COMPLETE (every language 4,468-4,579 approved, 9 rows pending, zero open
        # `missing` gaps). The work was re-verification of finished work, on a loop.
        #
        # ⚠️ ONLY genuinely-evaluated rows belong here. A short-skip never reached the
        # model, and an empty back-translation means the dispatch was shed or failed —
        # neither was reviewed, so neither may be stamped. Stamping an unevaluated row
        # buys silence for 30 days and is exactly the "unmonitored while appearing
        # monitored" shape (#5851 applies the same rule in generator.py:183).
        self.reviewed_ids: List[int] = []

    def scan(self) -> Iterator[ScannerResult]:
        for row in self.rows:
            text = row.get("text") or ""
            if _should_skip_short(text):
                continue
            back = back_translate_to_en(text, row.get("language", ""))
            if not (back or "").strip():
                # Failed/empty back-translation: the QA dispatch couldn't
                # evaluate this translation. Skip rather than flag — an empty
                # back-translation yields cosine 0.0 and produced ~900
                # false-positive 'quality_suspect' gaps during the 2026-05
                # hub-starvation window (#3676 follow-up). The next scan
                # re-evaluates once the dispatcher is healthy.
                continue
            # Past the empty-check: this row got a REAL back-translation, so it was
            # genuinely reviewed. Record it whether or not a gap is yielded below —
            # a row evaluated and found GOOD is precisely the one that must stop
            # coming back, and it is the majority case on a healthy corpus.
            if row.get("id") is not None:
                self.reviewed_ids.append(row["id"])
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
