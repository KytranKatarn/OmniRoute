"""Parse an LLM bias reading — ONE definition, and it distinguishes ABSENCE from ZERO.

THE BUG THIS EXISTS TO KILL
Both llm_v1 writers did:

    score = float(bias.get("score") or 0.0)

`or 0.0` collapses four different things into one number:
    missing key        -> 0.0   (absence)
    JSON null          -> 0.0   (absence, stated explicitly by the model)
    the string ""      -> 0.0   (absence)
    a real 0.0         -> 0.0   (a MEASUREMENT — "dead centre")

The band was taken from the model and kept, so an article came out as
`band='right', score=0.0, rationale=''` — the band asserting a lean while the
score says none. 3,629 articles were publicly labelled `right` that way, and
34,275 rows in total carried the fabricated zero (most invisibly, because an
absent band also defaults to 'center').

Measured across 745 sampled rows: score null-or-absent in 745 (100%), a literal
`0` returned by the model in **0**. In 400 the model explicitly emitted
`"score": null` — stating it had no reading — and the code overwrote that
statement with a measurement.

Same family as the A.U.R.O.R.A. weather parser, where `<gust>00</gust>` means NO
GUST but parses cleanly as `0`, so `int(x or 0)` fabricated a measurement on 94%
of forecast periods. `or <default>` is never safe on a field where zero is a
legal value.

RETURNING None IS THE POINT
None means "the model gave no usable reading — do not overwrite the heuristic".
The heuristic row it would clobber is a real, inspectable, deterministic
measurement (ingest/bias.py:score_bias). Replacing it with a partial parse is
strictly worse than leaving it alone.
"""

from typing import Optional

VALID_BANDS = frozenset({"left", "center-left", "center", "center-right", "right"})


def _score_or_none(raw) -> Optional[float]:
    """Coerce a model score to float, or None when it is ABSENT.

    Deliberately does NOT use `or` / truthiness anywhere: 0.0 and "0" are real
    measurements and must survive. Only genuine absence — missing, JSON null,
    empty/whitespace string, or unparseable — yields None.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):  # bool is an int subclass; a bool is not a score
        return None
    if isinstance(raw, (int, float)):
        return max(-1.0, min(1.0, float(raw)))
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            return max(-1.0, min(1.0, float(text)))
        except ValueError:
            return None
    return None


def parse_llm_bias(bias) -> Optional[dict]:
    """LLM bias section -> a usable reading, or None to leave the heuristic alone.

    Returns None when the model supplied no score. A band without a score is not
    a measurement — it is a partial parse, and every such row measured carried an
    empty rationale too.

    On success returns {band, score, rationale, confidence, trigger_phrases}
    with the band validated against VALID_BANDS (falling back to 'center' only
    when a real score IS present, so the row stays internally consistent).
    """
    if not isinstance(bias, dict):
        return None

    score = _score_or_none(bias.get("score"))
    if score is None:
        return None  # the whole point: no score => no overwrite

    band = str(bias.get("band") or "").strip().lower()
    if band not in VALID_BANDS:
        band = "center"

    confidence = bias.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = None

    triggers = bias.get("trigger_phrases")
    if not isinstance(triggers, list):
        triggers = []

    return {
        "band": band,
        "score": score,
        "rationale": (bias.get("rationale") or "").strip(),
        "confidence": confidence,
        "trigger_phrases": triggers,
    }
