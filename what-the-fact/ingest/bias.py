"""Rule-based bias heuristic v1. Scores are -1.0 (left) to +1.0 (right)."""
import re

# Weighted trigger terms. Tuned against bias_golden.json fixture.
_TRIGGERS = {
    # negative = left-leaning
    "union":                 -0.4,
    "unions":                -0.4,
    "labour":                -0.3,
    "collective bargaining": -0.5,
    "minimum wage":          -0.4,
    "ndp":                   -0.6,
    "new democratic":        -0.6,
    "indigenous":            -0.3,
    "activists":             -0.3,
    # neutral anchors
    "statistics canada":     0.0,
    "bank of canada":        0.0,
    "ipcc":                  0.0,
    "scientists":            0.0,
    # positive = right-leaning
    "conservative":          0.5,
    "tax cut":               0.4,
    "tax cuts":              0.4,
    "oil and gas":           0.4,
    "oil industry":          0.4,
    "pipeline":              0.2,
    "reduced immigration":   0.7,
    "sharp reductions":      0.4,
    # slight center-left
    "liberal":              -0.2,
    "liberals":             -0.2,
    "housing bill":         -0.2,
}

_BANDS = [
    (-0.6, "left"),
    (-0.2, "center-left"),
    (0.2,  "center"),
    (0.6,  "center-right"),
    (1.01, "right"),
]


def _band_for(score: float) -> str:
    for threshold, name in _BANDS:
        if score < threshold:
            return name
    return "right"


def score_bias(title: str, body: str) -> dict:
    text = (title + " " + body).lower()
    hits = []
    total = 0.0
    weight = 0.0
    for term, w in _TRIGGERS.items():
        if re.search(rf"\b{re.escape(term)}\b", text):
            hits.append(f"{term}({w:+.2f})")
            total += w
            weight += abs(w)
    score = total / weight if weight else 0.0
    score = max(-1.0, min(1.0, score))
    return {
        "band": _band_for(score),
        "score": round(score, 3),
        "rationale": "triggers: " + (", ".join(hits) if hits else "none — defaulted center"),
        "heuristic_version": "v1",
    }
