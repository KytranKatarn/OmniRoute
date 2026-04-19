"""Entry point for wtf-ingest. Polls each source hourly, normalizes, scores, persists."""
import logging
import os
import time
from sqlalchemy import create_engine, text

from ingest.sources.cbc_english import (
    fetch_articles as cbc_fetch,
    SOURCE_SLUG as CBC_SLUG,
    CBC_URL,
)
from ingest.sources.global_news import (
    fetch_articles as global_news_fetch,
    SOURCE_SLUG as GLOBAL_NEWS_SLUG,
    GLOBAL_NEWS_URL,
)
from ingest.normalizer import canonicalize
from ingest.bias import score_bias
from ingest.persist import upsert_article, record_failure
from shared.creed_events import emit as creed_emit

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wtf-ingest")
POLL_SECS = int(os.environ.get("WTF_POLL_SECS", "3600"))

# Source registry — add a new Canadian feed by appending one tuple here.
SOURCES = [
    (CBC_SLUG, "CBC English Top Stories", CBC_URL, cbc_fetch),
    (GLOBAL_NEWS_SLUG, "Global News", GLOBAL_NEWS_URL, global_news_fetch),
]


def _ensure_source(engine, slug, name, url) -> int:
    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO wtf.sources (slug, name, url) VALUES (:s, :n, :u)
            ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name, url=EXCLUDED.url
        """), {"s": slug, "n": name, "u": url})
        return c.execute(text("SELECT id FROM wtf.sources WHERE slug=:s"), {"s": slug}).scalar()


def _process_source(engine, slug: str, name: str, url: str, fetch_fn, stats: dict) -> None:
    """Fetch + normalize + score + persist one source. Mutates stats in place."""
    sid = _ensure_source(engine, slug, name, url)
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
            inserted = upsert_article(engine, sid, article, bias)
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
    for slug, name, url, fetch_fn in SOURCES:
        _process_source(engine, slug, name, url, fetch_fn, stats)
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
