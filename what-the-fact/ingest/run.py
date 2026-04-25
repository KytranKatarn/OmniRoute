"""Entry point for wtf-ingest. Polls each source hourly, normalizes, scores, persists."""
import logging
import os
import time
from sqlalchemy import create_engine, text

from ingest.sources.cbc_english import fetch_articles as cbc_fetch, SOURCE_SLUG as CBC_SLUG, CBC_URL
from ingest.sources.global_news import fetch_articles as global_news_fetch, SOURCE_SLUG as GLOBAL_NEWS_SLUG, GLOBAL_NEWS_URL
from ingest.sources.ctv_news import fetch_articles as ctv_fetch, SOURCE_SLUG as CTV_SLUG, SOURCE_NAME as CTV_NAME, SOURCE_URL as CTV_URL, RSS_URL as CTV_RSS, BIAS_LEAN as CTV_BIAS
from ingest.sources.toronto_star import fetch_articles as star_fetch, SOURCE_SLUG as STAR_SLUG, SOURCE_NAME as STAR_NAME, SOURCE_URL as STAR_URL, RSS_URL as STAR_RSS, BIAS_LEAN as STAR_BIAS
from ingest.sources.national_post import fetch_articles as np_fetch, SOURCE_SLUG as NP_SLUG, SOURCE_NAME as NP_NAME, SOURCE_URL as NP_URL, RSS_URL as NP_RSS, BIAS_LEAN as NP_BIAS
from ingest.sources.globe_mail import fetch_articles as gm_fetch, SOURCE_SLUG as GM_SLUG, SOURCE_NAME as GM_NAME, SOURCE_URL as GM_URL, RSS_URL as GM_RSS, BIAS_LEAN as GM_BIAS
from ingest.sources.ipolitics import fetch_articles as ipo_fetch, SOURCE_SLUG as IPO_SLUG, SOURCE_NAME as IPO_NAME, SOURCE_URL as IPO_URL, RSS_URL as IPO_RSS, BIAS_LEAN as IPO_BIAS
from ingest.sources.the_narwhal import fetch_articles as narwhal_fetch, SOURCE_SLUG as NARWHAL_SLUG, SOURCE_NAME as NARWHAL_NAME, SOURCE_URL as NARWHAL_URL, RSS_URL as NARWHAL_RSS, BIAS_LEAN as NARWHAL_BIAS
from ingest.sources.la_presse import fetch_articles as lp_fetch, SOURCE_SLUG as LP_SLUG, SOURCE_NAME as LP_NAME, SOURCE_URL as LP_URL, RSS_URL as LP_RSS, BIAS_LEAN as LP_BIAS
from ingest.sources.canadaland import fetch_articles as cl_fetch, SOURCE_SLUG as CL_SLUG, SOURCE_NAME as CL_NAME, SOURCE_URL as CL_URL, RSS_URL as CL_RSS, BIAS_LEAN as CL_BIAS
from ingest.normalizer import canonicalize
from ingest.bias import score_bias
from ingest.persist import upsert_article, record_failure
from shared.creed_events import emit as creed_emit

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wtf-ingest")
POLL_SECS = int(os.environ.get("WTF_POLL_SECS", "1800"))  # 30-min default for breaking news

# Source registry — (slug, name, site_url, rss_url, bias_lean, fetch_fn)
# Bias leans seeded from AllSides / Media Bias Fact Check, 2024 ratings.
SOURCES = [
    (CBC_SLUG,       "CBC English Top Stories",  "https://www.cbc.ca",              CBC_URL,        "center-left",  cbc_fetch),
    (GLOBAL_NEWS_SLUG, "Global News",             "https://globalnews.ca",           GLOBAL_NEWS_URL, "center",      global_news_fetch),
    (CTV_SLUG,       CTV_NAME,                   CTV_URL,                            CTV_RSS,        CTV_BIAS,       ctv_fetch),
    (STAR_SLUG,      STAR_NAME,                  STAR_URL,                           STAR_RSS,       STAR_BIAS,      star_fetch),
    (NP_SLUG,        NP_NAME,                    NP_URL,                             NP_RSS,         NP_BIAS,        np_fetch),
    (GM_SLUG,        GM_NAME,                    GM_URL,                             GM_RSS,         GM_BIAS,        gm_fetch),
    (IPO_SLUG,       IPO_NAME,                   IPO_URL,                            IPO_RSS,        IPO_BIAS,       ipo_fetch),
    (NARWHAL_SLUG,   NARWHAL_NAME,               NARWHAL_URL,                        NARWHAL_RSS,    NARWHAL_BIAS,   narwhal_fetch),
    (LP_SLUG,        LP_NAME,                    LP_URL,                             LP_RSS,         LP_BIAS,        lp_fetch),
    (CL_SLUG,        CL_NAME,                    CL_URL,                             CL_RSS,         CL_BIAS,        cl_fetch),
]


def _ensure_source(engine, slug, name, url, rss_url=None, bias_lean=None) -> int:
    with engine.begin() as c:
        c.execute(
            text("""
                INSERT INTO wtf.sources (slug, name, url, rss_feed, bias_lean)
                VALUES (:s, :n, :u, :r, :b)
                ON CONFLICT (slug) DO UPDATE SET
                    name=EXCLUDED.name,
                    url=EXCLUDED.url,
                    rss_feed=COALESCE(EXCLUDED.rss_feed, wtf.sources.rss_feed),
                    bias_lean=COALESCE(EXCLUDED.bias_lean, wtf.sources.bias_lean)
            """),
            {"s": slug, "n": name, "u": url, "r": rss_url, "b": bias_lean},
        )
        return c.execute(text("SELECT id FROM wtf.sources WHERE slug=:s"), {"s": slug}).scalar()


def _process_source(engine, slug, name, url, rss_url, bias_lean, fetch_fn, stats):
    """Fetch + normalize + score + persist one source. Mutates stats in place."""
    sid = _ensure_source(engine, slug, name, url, rss_url, bias_lean)
    try:
        raw_articles = fetch_fn()
    except Exception as exc:
        log.exception("%s fetch failed", slug)
        record_failure(engine, slug, {}, f"fetch: {exc}")
        stats["failed"] += 1
        return
    for raw in raw_articles:
        try:
            article = canonicalize(raw)
            bias = score_bias(article["title"], article["body"])
            inserted = upsert_article(engine, sid, article, bias, source_slug=slug)
            if inserted:
                stats["inserted"] += 1
                creed_emit("wtf.article.ingested", {
                    "source": slug, "url": article["url"], "bias": bias["band"],
                })
            else:
                stats["skipped"] += 1
        except Exception as exc:
            log.exception("article failed: %s", raw.get("url"))
            record_failure(engine, slug, raw, str(exc))
            stats["failed"] += 1


def run_once(engine) -> dict:
    """Run one ingestion pass across all registered sources. Returns stats dict."""
    stats = {"inserted": 0, "skipped": 0, "failed": 0}
    for slug, name, url, rss_url, bias_lean, fetch_fn in SOURCES:
        _process_source(engine, slug, name, url, rss_url, bias_lean, fetch_fn, stats)
    log.info("run_once: %s", stats)

    # Recompute rolling outlet bias scores after each pass
    try:
        from ingest.outlet_bias import recompute_outlet_bias
        recompute_outlet_bias(engine)
    except Exception as exc:
        log.warning("outlet_bias recompute failed: %s", exc)

    return stats


def main():
    engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    while True:
        try:
            run_once(engine)
        except Exception:
            log.exception("run_once crashed — sleeping and retrying")
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
