"""Entry point for wtf-ingest. Polls each source hourly, normalizes, scores, persists."""
import logging
import os
import time
from sqlalchemy import create_engine, text

from ingest.sources.cbc_english import fetch_articles as cbc_fetch, SOURCE_SLUG as CBC_SLUG
from ingest.normalizer import canonicalize
from ingest.bias import score_bias
from ingest.persist import upsert_article, record_failure
from shared.creed_events import emit as creed_emit

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wtf-ingest")
POLL_SECS = int(os.environ.get("WTF_POLL_SECS", "3600"))


def _ensure_source(engine, slug, name, url) -> int:
    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO wtf.sources (slug, name, url) VALUES (:s, :n, :u)
            ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name, url=EXCLUDED.url
        """), {"s": slug, "n": name, "u": url})
        return c.execute(text("SELECT id FROM wtf.sources WHERE slug=:s"), {"s": slug}).scalar()


def run_once(engine) -> dict:
    """Run one ingestion pass across all sources. Returns stats dict."""
    stats = {"inserted": 0, "skipped": 0, "failed": 0}
    sid = _ensure_source(engine, CBC_SLUG, "CBC English Top Stories",
                          "https://www.cbc.ca/cmlink/rss-topstories")
    try:
        raw_articles = cbc_fetch()
    except Exception as exc:
        log.exception("cbc fetch failed")
        record_failure(engine, CBC_SLUG, {}, f"fetch: {exc}")
        stats["failed"] += 1
        return stats
    for raw in raw_articles:
        try:
            article = canonicalize(raw)
            bias = score_bias(article["title"], article["body"])
            inserted = upsert_article(engine, sid, article, bias)
            if inserted:
                stats["inserted"] += 1
                creed_emit("wtf.article.ingested", {
                    "source": CBC_SLUG, "url": article["url"], "bias": bias["band"],
                })
            else:
                stats["skipped"] += 1
        except Exception as exc:
            log.exception("article failed: %s", raw.get("url"))
            record_failure(engine, CBC_SLUG, raw, str(exc))
            stats["failed"] += 1
    log.info("run_once: %s", stats)
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
