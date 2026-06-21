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
    except Exception:  # noqa: BLE001 — best-effort warmup, embedding_service still tries
        pass

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
