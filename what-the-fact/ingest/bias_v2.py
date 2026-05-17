"""DistilBERT zero-shot bias classifier (v2 signal) — task #2136.

Second independent bias signal alongside the LLM tier-1 score from
`quick_analyzer.py`. NOT a replacement for the heuristic or the LLM —
the audit trail keeps all three so users can see where signals diverge.

Model: valhalla/distilbart-mnli-12-3 (~500MB, CPU-only on outpost-us).
Cached under HF_HOME (/opt/hf-cache) — baked into Dockerfile.ingest so
container restarts don't re-download.
"""

from __future__ import annotations

import logging
import os
import threading

log = logging.getLogger(__name__)

_MODEL_ID = os.getenv("BIAS_V2_MODEL", "valhalla/distilbart-mnli-12-3")
_LABELS = [
    "left-leaning political bias",
    "neutral reporting",
    "right-leaning political bias",
]
_LABEL_TO_SHORT = {
    "left-leaning political bias": "left",
    "neutral reporting": "center",
    "right-leaning political bias": "right",
}
_LABEL_TO_SCORE = {
    "left-leaning political bias": -0.7,
    "neutral reporting": 0.0,
    "right-leaning political bias": +0.7,
}

_pipe = None
_pipe_lock = threading.Lock()


def _ensure_pipe():
    global _pipe
    if _pipe is not None:
        return _pipe
    with _pipe_lock:
        if _pipe is None:
            from transformers import pipeline  # local import — heavy
            log.info("Loading zero-shot pipeline: %s", _MODEL_ID)
            _pipe = pipeline(
                "zero-shot-classification",
                model=_MODEL_ID,
                device=-1,  # CPU
            )
            log.info("Zero-shot pipeline ready: %s", _MODEL_ID)
    return _pipe


def score_v2(title: str, body: str) -> dict:
    """Score one article with the zero-shot classifier.

    Returns dict with keys: label, score, confidence, model.
      - label: 'left' | 'center' | 'right'
      - score: signed [-1.0, +1.0] (label baseline × confidence)
      - confidence: top-label probability [0.0, 1.0]
      - model: HF model id

    Raises on model load failure — callers should catch and skip.
    """
    text = ((title or "") + " " + (body or "")).strip()
    if not text:
        return {"label": "center", "score": 0.0, "confidence": 0.0, "model": _MODEL_ID}

    # Truncate to ~512 tokens worth of chars. The pipeline will tokenize +
    # truncate again internally, but capping early avoids wasted work on
    # long-form articles.
    text = text[:2000]

    pipe = _ensure_pipe()
    out = pipe(text, candidate_labels=_LABELS, multi_label=False)

    top_label = out["labels"][0]
    top_conf = float(out["scores"][0])
    baseline = _LABEL_TO_SCORE[top_label]
    score = round(baseline * top_conf, 3)

    return {
        "label": _LABEL_TO_SHORT[top_label],
        "score": score,
        "confidence": round(top_conf, 3),
        "model": _MODEL_ID,
    }
