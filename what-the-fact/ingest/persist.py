"""DB writes: upsert articles + bias scores + audit trail + story clustering."""

import json
import logging
import os
import threading
from sqlalchemy import text

try:  # container runs `python -m ingest.run` (package); tests import as a script
    from ingest import content_kind
except ImportError:  # pragma: no cover
    import content_kind

# ── Cross-Watch signal (fire-and-forget, Task #3023) ──────────────────────────
_CW_HUB = os.getenv("CROSS_WATCH_HUB_URL", "")
_CW_TOKEN = os.getenv("CROSS_WATCH_SERVICE_TOKEN", "")


def _send_wtf_signal(article_id: int, title: str, url: str) -> None:
    """POST a news_coverage signal to the hub for entity matching.  Non-fatal."""
    if not _CW_HUB or not _CW_TOKEN:
        return
    try:
        import requests as _req

        _req.post(
            f"{_CW_HUB}/api/cross-watch/signal",
            json={
                "signal_type": "news_coverage",
                "source_product": "wtf",
                "source_item_id": str(article_id),
                "headline": title,
                "url": url,
            },
            headers={"Authorization": f"Bearer {_CW_TOKEN}"},
            timeout=3,
        )
    except Exception:
        pass  # cross-watch failure must never break ingest


logger = logging.getLogger(__name__)

_ALLOWED_SCHEMAS = frozenset({"wtf", "wtf_test"})


def _schema() -> str:
    return os.environ.get("WTF_SCHEMA", "wtf")



# A headline that is only the publisher's own name is not a headline. Google
# News emits exactly this when it has no title for an item — measured 2026-08-18:
# 74 of La Presse's 180 articles were the literal string "- La Presse+", giving
# that source 43.9% title uniqueness while every other source sat above 73%.
# Those rows still got bias-scored and fact-checked, so the pipeline spent real
# work on a string that says nothing (#5775).
#
# Deliberately NARROW. It matches a title that is ONLY punctuation + the source
# name (+ an optional trailing '+' or '|' fragment). A real headline that merely
# CONTAINS the publisher's name is untouched.
_JUNK_TITLE_MAX_LEN = 60


def is_publisher_suffix_title(title, source_name):
    """True when `title` carries no information beyond the publisher's name."""
    if not title or not source_name:
        return False
    def _norm(v):
        # Callers pass a SLUG ("la-presse") while the junk title carries the
        # display name ("La Presse"), so hyphens/underscores normalise to spaces
        # before comparing. Without this the guard silently never matches.
        v = " ".join(str(v).replace("-", " ").replace("_", " ").split())
        return v.strip(" |\u2013\u2014\u00b7+").casefold()

    t = " ".join(str(title).split())
    if len(t) > _JUNK_TITLE_MAX_LEN:
        return False
    # Google leaves separators behind: "- Name+", "| Name". Strip the leading
    # dash here (not in _norm) so a hyphenated slug keeps its internal hyphens
    # converted to spaces rather than being eaten.
    stripped = _norm(t.lstrip(" -|\u2013\u2014\u00b7"))
    name = _norm(source_name)
    return bool(name) and stripped == name


def upsert_article(
    engine, source_id: int, article: dict, bias: dict, source_slug: str = ""
) -> bool:
    """Insert article + bias_score + audit entry, then cluster + fact-check. Returns article_id (int) on insert, None on dedupe/failure."""
    S = _schema()
    aid = None

    # Reject a title that is only the publisher's name BEFORE it costs a bias
    # score and a fact-check. Treated as a dedupe (return None), not an error:
    # the feed is working, this one item simply carries no headline.
    if is_publisher_suffix_title(article.get("title"), source_slug or article.get("source_name")):
        logger.warning(
            "persist: dropping publisher-suffix title from source %s: %r",
            source_id, (article.get("title") or "")[:80],
        )
        return None

    with engine.begin() as c:
        r = c.execute(
            text(f"""
                INSERT INTO {S}.articles (source_id, external_id, title, body, url,
                                          content_type, published_at)
                SELECT :sid, :eid, :t, :b, :u, :ctype,
                        -- Clamp a wildly-future published_at (source date-parse error) so a
                        -- bogus date can't pin the article atop every feed (front page,
                        -- clusters, digests all sort by it). NULL / normal dates pass through
                        -- unchanged. (WTF front-page freeze, 2026-07-14)
                        CASE WHEN :p IS NOT NULL AND :p > NOW() + INTERVAL '2 hours'
                             THEN NOW() + INTERVAL '2 hours' ELSE :p END
                -- ⚠️ RE-FETCH DEDUPE. Neither unique key catches this class.
                --
                -- 10 of 46 sources are ingested through a GOOGLE NEWS PROXY, which
                -- re-encodes the same story under a NEW opaque token on a later
                -- poll — so external_id AND url both change while the article is
                -- identical. Measured over 14 days: 796 same-source same-title
                -- groups, 953 redundant rows (6.3% of all articles), and 792 of
                -- those 796 had DIFFERENT urls. CTV News alone was 571.
                --
                -- Example: the same CTV story arrived twice with identical
                -- published_at and two different news.google.com/rss/articles/CBMi…
                -- tokens. `ON CONFLICT (source_id, external_id)` cannot see it, and
                -- neither could a URL constraint.
                --
                -- ⚠️ THE 6-HOUR WINDOW IS LOAD-BEARING, NOT A ROUND NUMBER.
                -- Spread within duplicate groups, 14d:
                --      < 1h   623 groups   ← the re-fetch signature
                --      1-6h    79
                --      6-24h   28
                --      24-72h   8
                --      > 72h   58   ← NOT duplicates
                -- The >72h bucket is RECURRING CONTENT that legitimately reuses a
                -- headline: "Today's horoscope" x8, "Before the Bell…" x10 (a daily
                -- column), "Transaction in Own Shares" x8. Deduping on title alone,
                -- or with a window of a day or more, would silently delete a
                -- publisher's daily column down to a single copy. 6h sits above the
                -- entire re-fetch population and far below any daily recurrence.
                --
                -- Done as WHERE NOT EXISTS inside the INSERT, not a read-then-write,
                -- so two ingest passes cannot interleave past it.
                --
                -- NOT filtered on suppressed_reason: a copy already suppressed as a
                -- duplicate must still block a THIRD copy.
                 WHERE NOT EXISTS (
                     SELECT 1 FROM {S}.articles d
                      WHERE d.source_id = :sid
                        AND d.title = :t
                        AND d.published_at
                            BETWEEN COALESCE(CAST(:p AS timestamptz), NOW()) - INTERVAL '6 hours'
                                AND COALESCE(CAST(:p AS timestamptz), NOW()) + INTERVAL '6 hours'
                 )
                ON CONFLICT (source_id, external_id) DO NOTHING
                RETURNING id
            """),
            {
                "sid": source_id,
                "eid": article["external_id"],
                "t": article["title"],
                "b": article["body"],
                "u": article["url"],
                # Classify at ingest so the bias rollup never averages a press
                # release into an outlet's partisan lean (migration 065).
                # Fail-safe: content_kind.classify never raises and defaults to
                # 'journalism', so a detector problem can only ever UNDER-flag —
                # a false positive would silently delete a real signal from a
                # public statistic, which is the worse direction.
                "ctype": content_kind.classify(article.get("title"), article.get("body")),
                "p": article["published_at"],
            },
        )
        row = r.fetchone()
        if not row:
            # Both no-row paths return None, so without this the re-fetch dedupe
            # would be INVISIBLE — indistinguishable from the ordinary
            # already-seen-this-guid case, and nobody could tell whether the new
            # guard was firing, over-firing, or dead. One extra cheap query on
            # the ~6% of items that dedupe.
            try:
                dup = c.execute(
                    text(f"""
                        SELECT id FROM {S}.articles
                         WHERE source_id = :sid AND title = :t
                           AND external_id IS DISTINCT FROM :eid
                           AND published_at
                               BETWEEN COALESCE(CAST(:p AS timestamptz), NOW()) - INTERVAL '6 hours'
                                   AND COALESCE(CAST(:p AS timestamptz), NOW()) + INTERVAL '6 hours'
                         LIMIT 1
                    """),
                    {"sid": source_id, "t": article["title"],
                     "eid": article["external_id"], "p": article["published_at"]},
                ).fetchone()
                if dup:
                    logger.info(
                        "persist: re-fetch duplicate skipped — source=%s keeps id=%s, "
                        "new guid=%r title=%r",
                        source_id, dup[0], str(article["external_id"])[:40],
                        (article["title"] or "")[:70],
                    )
            except Exception:
                pass  # observability must never break ingestion
            return None
        aid = row[0]
        c.execute(
            text(f"""
                INSERT INTO {S}.bias_scores (article_id, band, score, heuristic_version, rationale,
                                             signal_detected)
                VALUES (:aid, :band, :score, :v, :rat, :sig)
            """),
            {
                "aid": aid,
                "band": bias["band"],
                "score": bias["score"],
                "v": bias["heuristic_version"],
                "rat": bias["rationale"],
                # False = the detector matched NO trigger term. score/band carry
                # schema-required values but assert nothing; the outlet rollup
                # excludes these rows. Default True keeps any caller that predates
                # score_bias returning the key from silently marking rows no-signal.
                "sig": bias.get("signal_detected", True),
            },
        )
        c.execute(
            text(
                f"INSERT INTO {S}.audit_trail (article_id, event_type, payload) VALUES (:aid, 'ingested', :p)"
            ),
            {"aid": aid, "p": json.dumps({"source_id": source_id, "bias": bias})},
        )

    # Tag journalist bylines into the shared entity graph (Milestone B / B2).
    # Separate txn + non-fatal: a byline-resolution error must never drop the article.
    if aid and article.get("author"):
        try:
            try:
                from shared.author_resolver import resolve_byline, tag_article_author
            except ImportError:
                from author_resolver import resolve_byline, tag_article_author
            with engine.begin() as ac:
                for eid in resolve_byline(ac, article["author"], source_slug):
                    tag_article_author(ac, aid, eid, source_slug)
        except Exception as exc:
            logger.warning("author tagging failed for article %s: %s", aid, exc)

    # Cluster in a separate transaction (article must be committed first)
    try:
        from ingest.cluster import find_or_create_cluster

        find_or_create_cluster(engine, aid, article["title"], article["published_at"])
    except Exception as exc:
        logger.warning("clustering failed for article %d: %s", aid, exc)

    # Fact-check claims (non-fatal)
    try:
        from ingest.factcheck import factcheck_article

        factcheck_article(engine, aid, article.get("body", ""), source_slug)
    except Exception as exc:
        logger.warning("factcheck failed for article %d: %s", aid, exc)

    # Geo extraction for every article
    try:
        from ingest.geocoder import extract_geo

        geo = extract_geo(
            aid,
            article.get("title", ""),
            article.get("body", ""),
            source_slug=source_slug,
        )
        save_geo(engine, aid, S, geo)
    except Exception:
        pass  # geo is non-fatal

    # Fire-and-forget cross-watch signal (daemon thread — never blocks ingest)
    if aid:
        threading.Thread(
            target=_send_wtf_signal,
            args=(aid, article.get("title", ""), article.get("url", "")),
            daemon=True,
        ).start()

    return aid


def save_geo(engine, article_id: int, schema: str, geo: dict) -> None:
    """Save geocoder result to article geo columns.

    ⚠️ This is the INGEST-TIME geo write — it runs for every article, so it is
    the path that decides what the map sees. It must persist EVERY field
    extract_geo() produces.

    country_code was missing from this UPDATE entirely (#6210). The geocoder
    computed it correctly and this function silently dropped it on the floor,
    which is why /map coloured every pin the same "unknown" grey. The two other
    writers (run.py's orchestrator UPDATE, geo_backlog_worker) always included
    the column, but run.py's is scoped `WHERE geo_scope IN ('national')` and the
    backlog worker only sees rows this path failed to fill — so neither covered
    the ordinary article.

    ⚠️ Adding a field to extract_geo() means adding it HERE too. A value that is
    computed but never written is indistinguishable, in the database, from one
    that was never computed at all.
    """
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"save_geo: disallowed schema {schema!r}")
    if not geo or not article_id:
        return
    try:
        with engine.begin() as c:
            c.execute(
                text(
                    f"UPDATE {schema}.articles SET province_code = :pc, city = :city, "
                    f"lat = :lat, lng = :lng, country_code = :country, geo_scope = :scope "
                    f"WHERE id = :aid"
                ),
                {
                    "pc": geo.get("province_code"),
                    "city": geo.get("city"),
                    "lat": geo.get("lat"),
                    "lng": geo.get("lng"),
                    "country": geo.get("country_code"),
                    "scope": geo.get("geo_scope", "national"),
                    "aid": article_id,
                },
            )
    except Exception as exc:
        logger.debug("save_geo: failed for article_id=%s: %s", article_id, exc)


def mark_ai_analyzed(engine, article_id: int, schema: str) -> None:
    """Mark article as AI-analyzed."""
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"mark_ai_analyzed: disallowed schema {schema!r}")
    try:
        with engine.begin() as c:
            c.execute(
                text(
                    f"UPDATE {schema}.articles SET ai_analyzed = TRUE, ai_analyzed_at = NOW() WHERE id = :aid"
                ),
                {"aid": article_id},
            )
    except Exception as exc:
        logger.debug("mark_ai_analyzed: failed for article_id=%s: %s", article_id, exc)


def record_failure(engine, source_slug: str, raw: dict, error: str) -> None:
    S = _schema()
    with engine.begin() as c:
        c.execute(
            text(f"""
            INSERT INTO {S}.failed_ingest (source_slug, raw_payload, error)
            VALUES (:s, :r, :e)
        """),
            {"s": source_slug, "r": json.dumps(raw, default=str), "e": error},
        )
    logger.warning("dead-letter: %s - %s", source_slug, error[:100])
