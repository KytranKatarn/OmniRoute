"""Rule-based bias heuristic v3. Scores are -1.0 (left) to +1.0 (right).

Key design decisions:
- Canadian media baseline is institutionally center-left. Band thresholds shift
  slightly right to account for this — what v2 called CENTER now correctly shows
  CENTER-LEFT for articles with mild left-leaning language.
- Headline weighted 3x body text.
- Adds loaded language, framing signals, and word-choice pairs from AllSides
  methodology and 2025-2026 media bias research.
"""
import re

_TRIGGERS = {

    # === PARTIES & LEADERS ===
    "ndp":                      -0.6,
    "new democratic":           -0.6,
    "liberal party":            -0.25,
    "liberals":                 -0.2,
    "liberal":                  -0.15,
    "trudeau":                  -0.2,
    "mark carney":              -0.15,
    "conservative":              0.5,
    "conservatives":             0.5,
    "tory":                      0.45,
    "tories":                    0.45,
    "poilievre":                 0.5,
    "bloc québécois":           -0.2,
    "bloc quebecois":           -0.2,
    "green party":              -0.35,
    "people's party":            0.8,
    "peoples party":             0.8,
    "ppc":                       0.8,
    "maxime bernier":            0.8,

    # === ECONOMIC FRAMING ===
    "tax cut":                   0.4,
    "tax cuts":                  0.4,
    "tax relief":                0.4,
    "lower taxes":               0.5,
    "carbon tax":                0.5,
    "carbon price":             -0.2,
    "fiscal responsibility":     0.35,
    "balanced budget":           0.3,
    "deficit spending":         -0.2,
    "government spending":       0.25,
    "social spending":          -0.3,
    "welfare state":             0.4,
    "corporate tax":            -0.25,
    "wealth tax":               -0.45,
    "job creators":              0.4,
    "corporate welfare":        -0.4,
    "red tape":                  0.35,
    "deregulation":              0.4,
    "privatization":             0.45,
    "privatize":                 0.45,
    "minimum wage":             -0.4,
    "living wage":              -0.45,
    "labour rights":            -0.4,
    "union":                    -0.4,
    "unions":                    -0.4,
    "collective bargaining":    -0.5,
    "workers rights":           -0.35,
    "private enterprise":        0.18,
    "small business":            0.2,
    "entrepreneurs":             0.15,
    "private sector":            0.15,
    "property owners":           0.22,
    "property rights":           0.22,
    "economic freedom":          0.28,
    "free market":               0.3,
    "personal responsibility":   0.25,
    "self-reliance":             0.25,
    "social safety net":        -0.25,
    "publicly funded":          -0.15,
    "public sector":            -0.1,
    "income inequality":        -0.2,
    "wealth gap":               -0.2,
    "poverty":                  -0.12,
    "food bank":                -0.15,

    # === ENERGY & ENVIRONMENT ===
    "oil and gas":               0.4,
    "oil industry":              0.4,
    "pipeline":                  0.25,
    "oilsands":                  0.35,
    "oil sands":                 0.35,
    "tar sands":                -0.3,
    "fossil fuel":              -0.3,
    "fossil fuels":             -0.3,
    "net zero":                 -0.2,
    "clean energy":             -0.2,
    "climate emergency":        -0.4,
    "climate crisis":           -0.35,
    "climate change":           -0.15,
    "climate alarmism":          0.5,
    "climate skeptic":           0.4,
    "climate denier":           -0.3,
    "global warming":           -0.15,
    "carbon emissions":         -0.2,
    "emissions target":         -0.2,
    "green new deal":           -0.5,
    "resource development":      0.2,
    "energy security":           0.2,

    # === SOCIAL ISSUES ===
    "reconciliation":           -0.3,
    "indigenous":               -0.25,
    "first nations":            -0.2,
    "residential schools":      -0.3,
    "unmarked graves":          -0.3,
    "lgbtq":                    -0.3,
    "trans rights":             -0.4,
    "gender ideology":           0.6,
    "parental rights":           0.5,
    "faith-based":               0.3,
    "religious freedom":         0.35,
    "woke":                      0.5,
    "woke agenda":               0.6,
    "political correctness":     0.45,
    "cancel culture":            0.5,
    "diversity equity":         -0.3,
    "systemic racism":          -0.4,
    "systemic":                 -0.28,
    "defund":                   -0.5,
    "social housing":           -0.3,
    "affordable housing":       -0.15,
    "pharmacare":               -0.4,
    "dental care":              -0.3,
    "childcare":                -0.25,
    "childcare spaces":         -0.2,
    "universal basic income":   -0.4,
    "universal health":         -0.2,
    "marginalized":             -0.3,
    "vulnerable populations":   -0.25,
    "colonialism":              -0.35,
    "decolonize":               -0.4,
    "lived experience":         -0.3,
    "settler":                  -0.3,
    "privilege":                -0.3,
    "equity":                   -0.15,
    "inclusion":                -0.1,
    "progressive":              -0.18,

    # === LOADED LANGUAGE — RIGHT ===
    "radical left":              0.7,
    "radical agenda":            0.6,
    "socialist":                 0.5,
    "nanny state":               0.5,
    "virtue signaling":          0.5,
    "open borders":              0.6,
    "big government":            0.4,
    "elite":                     0.3,
    "elites":                    0.3,
    "mainstream media":          0.45,
    "legacy media":              0.4,
    "propaganda":                0.35,
    "hardworking canadians":     0.3,
    "taxpayers":                 0.2,
    "ordinary canadians":        0.15,

    # === LOADED LANGUAGE — LEFT ===
    "evidence-based":           -0.12,
    "science-based":            -0.12,
    "accountability":           -0.1,
    "transparency":             -0.08,
    "crown corporation":        -0.12,

    # === IMMIGRATION ===
    "immigration levels":        0.3,
    "reduced immigration":       0.7,
    "immigration targets":       0.2,
    "asylum seekers":           -0.2,
    "refugees":                 -0.15,
    "border security":           0.45,
    "illegal aliens":            0.6,
    "illegal immigrants":        0.5,
    "irregular migrants":        0.2,
    "undocumented workers":     -0.4,
    "undocumented":             -0.3,

    # === LAW & ORDER ===
    "tough on crime":            0.4,
    "law and order":             0.4,
    "mandatory minimum":         0.35,
    "decriminalize":            -0.4,
    "drug decriminalization":   -0.45,
    "safe supply":              -0.4,
    "supervised consumption":   -0.4,
    "freedom convoy":            0.6,
    "truckers convoy":           0.55,

    # === ATTRIBUTION FRAMING (AllSides methodology) ===
    "experts warn":             -0.1,
    "scientists warn":          -0.12,
    "according to experts":     -0.08,
    "critics say":              -0.08,
    "advocates say":            -0.1,
    "activists say":            -0.1,
    "blasted":                   0.2,
    "slammed":                   0.15,
    "outrage":                   0.15,

    # === WORD CHOICE PAIRS (same subject, different framing) ===
    "pro-life":                  0.5,
    "anti-abortion":            -0.3,
    "pro-choice":               -0.4,

    # === NEUTRAL ANCHORS (zero weight) ===
    "statistics canada":         0.0,
    "bank of canada":            0.0,
    "ipcc":                      0.0,
    "scientists":                0.0,
    "researchers":               0.0,
    "study shows":               0.0,
    "report finds":              0.0,
}

# v3: thresholds shifted slightly right to account for Canadian media's
# institutional center-left baseline. Articles that previously read CENTER
# with mild left-leaning language will now correctly score CENTER-LEFT.
_BANDS = [
    (-0.55, "left"),
    (-0.15, "center-left"),
    (0.25,  "center"),
    (0.65,  "center-right"),
    (1.01,  "right"),
]


def _band_for(score: float) -> str:
    for threshold, name in _BANDS:
        if score < threshold:
            return name
    return "right"


def score_bias(title: str, body: str) -> dict:
    # Headline weighted 3x — editorial framing in titles is a stronger signal
    title_text = (title or "").lower()
    body_text = (body or "").lower()

    hits = []
    total = 0.0
    weight = 0.0

    for term, w in _TRIGGERS.items():
        pattern = rf"\b{re.escape(term)}\b"
        in_title = bool(re.search(pattern, title_text))
        in_body = bool(re.search(pattern, body_text))

        if in_title or in_body:
            multiplier = 3.0 if in_title else 1.0
            contribution = w * multiplier
            hits.append(f"{term}({w:+.2f}×{multiplier:.0f})")
            total += contribution
            weight += abs(contribution)

    # ⚠️ `weight == 0` means NO trigger term matched — the detector found NOTHING,
    # which is NOT the same as measuring a lean of zero. The old
    # `total / weight if weight else 0.0` collapsed those two, and _band_for(0.0)
    # then returned 'center', so "we detected no loaded vocabulary" was published
    # as "this article is politically centrist". 41,369 rows say exactly that in
    # their own rationale: "triggers: none — defaulted center".
    #
    # Same absent-vs-measured collapse as `float(x or 0.0)` in the LLM bias
    # writers and `or "unverifiable"` in the fact-check writers — this one is in
    # the detector itself.
    #
    # score/band still carry the schema-required values (score is NOT NULL, band
    # is CHECK-constrained to five POLITICAL values with no "undetermined"
    # member), but `signal_detected` now says whether they mean anything. The
    # outlet rollup averages only signal-bearing rows — see ingest/outlet_bias.py.
    signal_detected = weight > 0
    score = total / weight if weight else 0.0
    score = max(-1.0, min(1.0, score))
    return {
        "band": _band_for(score),
        "score": round(score, 3),
        "signal_detected": signal_detected,
        "rationale": "triggers: " + (", ".join(hits) if hits else "none — NO SIGNAL DETECTED (not a centrist finding)"),
        "heuristic_version": "v3",
    }
