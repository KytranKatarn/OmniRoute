"""Rule-based fact-check claim extraction — MVP heuristic v1.

Extracts factual claims from article bodies and assigns verdicts based on
claim type and source credibility. No external API calls.

Verdicts (must match wtf.fact_checks.verdict CHECK constraint:
true | mostly_true | mixed | false | unverified):
  true           — statistical claim from a credible source slug (CBC, Reuters, StatsCan)
  mostly_true    — numerical claim with hedging language
  mixed          — claim with contradicting keywords present in same article
  false          — contains known correction markers ("correction:", "retraction:")
  unverified     — everything else (default)

LLM upgrade: replace _extract_claims() + _assign_verdict() with Bridge dispatch.
"""
import re
import logging
import os
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Source slugs considered credible for statistical claims
_CREDIBLE_SLUGS = frozenset(
    ["cbc_english", "globe_mail", "global_news", "la_presse", "the_narwhal", "ctv_news"]
)

_CLAIM_RE = re.compile(
    r"(?:^|(?<=\. ))"  # sentence boundary
    r"([A-Z][^.!?]{20,200})"  # sentence 20-200 chars
    r"(?=[.!?])",
    re.MULTILINE,
)

_STAT_RE = re.compile(r"\d[\d,.%]+|\bone in \w+\b|\bper cent\b|\bpercent\b", re.I)
_HEDGE_RE = re.compile(r"\baccording to\b|\bsaid\b|\breported\b|\bclaims\b", re.I)
_CONTRADICT_RE = re.compile(r"\bbut\b|\bhowever\b|\bdenied\b|\bdisputed\b", re.I)
_CORRECTION_RE = re.compile(r"\bcorrection:\b|\bretraction:\b|\bupdated:\b", re.I)


def _extract_claims(body: str) -> list[str]:
    """Return up to 3 factual-claim sentences from body."""
    sentences = [s.strip() for s in re.split(r"[.!?]\s+", body) if len(s.strip()) > 30]
    claims = []
    for s in sentences:
        if _STAT_RE.search(s) or _HEDGE_RE.search(s):
            claims.append(s[:500])
        if len(claims) >= 3:
            break
    return claims


def _assign_verdict(claim: str, body: str, source_slug: str) -> str:
    if _CORRECTION_RE.search(body):
        return "false"
    if _CONTRADICT_RE.search(claim):
        return "mixed"
    if source_slug in _CREDIBLE_SLUGS and _STAT_RE.search(claim):
        return "mostly_true" if _HEDGE_RE.search(claim) else "true"
    return "unverified"


def factcheck_article(engine, article_id: int, body: str, source_slug: str) -> None:
    """Extract claims and upsert fact_check rows. Non-fatal on error."""
    S = os.environ.get("WTF_SCHEMA", "wtf")
    claims = _extract_claims(body)
    if not claims:
        return
    try:
        with engine.begin() as c:
            for claim in claims:
                verdict = _assign_verdict(claim, body, source_slug)
                c.execute(
                    text(f"""
                        INSERT INTO {S}.fact_checks
                            (article_id, claim, verdict, evidence, checker)
                        VALUES (:aid, :claim, :verdict, :evidence, 'heuristic-v1')
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "aid": article_id,
                        "claim": claim,
                        "verdict": verdict,
                        "evidence": (
                            f"Rule-based: source_credibility={source_slug in _CREDIBLE_SLUGS}, "
                            f"has_stat={bool(_STAT_RE.search(claim))}, "
                            f"hedged={bool(_HEDGE_RE.search(claim))}"
                        ),
                    },
                )
        logger.debug("factcheck: article %d — %d claims extracted", article_id, len(claims))
    except Exception as exc:
        logger.warning("factcheck failed for article %d: %s", article_id, exc)
