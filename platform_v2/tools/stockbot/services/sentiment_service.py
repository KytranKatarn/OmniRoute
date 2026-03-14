"""
Sentiment Service — StockBot Phase 4
Fetch news from multiple sources, analyze with AI Bridge, cache results.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/mnt/archie_brain/platform_v2")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

from database import get_db_cursor

try:
    from archie_bridge import archie_bridge

    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False

logger = logging.getLogger(__name__)

NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")
SENTIMENT_TTL = 3600  # 1 hour


def _now_utc():
    return datetime.now(timezone.utc)


# ── News fetching ──────────────────────────────────────────────────────────────


def fetch_news(ticker: str) -> list:
    """
    Fetch news headlines for ticker from RSS (Yahoo Finance),
    Reddit JSON API, and NewsAPI (if key set).
    Returns list of {source, headline, url, published_at}.
    """
    ticker = ticker.upper().strip()
    articles = []

    # Yahoo Finance RSS
    try:
        import urllib.request
        import xml.etree.ElementTree as ET

        rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            tree = ET.parse(resp)
        root = tree.getroot()
        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item")[:10]:
                title = item.findtext("title", "").strip()
                link = item.findtext("link", "").strip()
                pub = item.findtext("pubDate", "")
                if title:
                    articles.append({"source": "yahoo", "headline": title, "url": link, "published_at": pub})
    except Exception as e:
        logger.warning(f"fetch_news yahoo rss ({ticker}): {e}")

    # Reddit /r/stocks search
    try:
        import urllib.request

        reddit_url = f"https://www.reddit.com/r/stocks/search.json?q={ticker}&restrict_sr=1&sort=new&limit=10"
        req = urllib.request.Request(reddit_url, headers={"User-Agent": "archie-stockbot/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        for post in data.get("data", {}).get("children", []):
            d = post.get("data", {})
            title = d.get("title", "").strip()
            url = d.get("url", "")
            created = d.get("created_utc")
            if title and ticker.lower() in title.lower():
                pub = datetime.fromtimestamp(created, tz=timezone.utc).isoformat() if created else ""
                articles.append({"source": "reddit", "headline": title, "url": url, "published_at": pub})
    except Exception as e:
        logger.warning(f"fetch_news reddit ({ticker}): {e}")

    # NewsAPI (optional)
    if NEWSAPI_KEY:
        try:
            import urllib.request
            import urllib.parse

            params = urllib.parse.urlencode({"q": ticker, "apiKey": NEWSAPI_KEY, "pageSize": 10, "language": "en"})
            url = f"https://newsapi.org/v2/everything?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "archie-stockbot/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
            for art in data.get("articles", []):
                title = art.get("title", "").strip()
                link = art.get("url", "")
                pub = art.get("publishedAt", "")
                if title and title != "[Removed]":
                    articles.append({"source": "newsapi", "headline": title, "url": link, "published_at": pub})
        except Exception as e:
            logger.warning(f"fetch_news newsapi ({ticker}): {e}")

    logger.info(f"fetch_news({ticker}): found {len(articles)} articles")
    return articles


# ── Sentiment analysis ─────────────────────────────────────────────────────────


def analyze_sentiment(ticker: str) -> dict:
    """
    Fetch news, run AI sentiment analysis, cache results.
    Returns {ticker, overall_score, headlines, summary, cached_at}.
    """
    ticker = ticker.upper().strip()

    # Check cache (< 1h old)
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT sentiment_score, headline, analyzed_at
                FROM stock_news_cache
                WHERE ticker = %s
                  AND analyzed_at > NOW() - INTERVAL '1 hour'
                ORDER BY analyzed_at DESC
                LIMIT 15
                """,
                (ticker,),
            )
            rows = cur.fetchall()
        if rows:
            scores = [float(r[0]) for r in rows if r[0] is not None]
            overall = round(sum(scores) / len(scores), 3) if scores else 0.0
            headlines = [{"text": r[1], "score": float(r[0]) if r[0] else 0.0} for r in rows]
            return {
                "ticker": ticker,
                "overall_score": overall,
                "headlines": headlines,
                "summary": f"Cached sentiment for {ticker}: {overall:+.2f}",
                "cached": True,
            }
    except Exception as e:
        logger.warning(f"analyze_sentiment cache read ({ticker}): {e}")

    articles = fetch_news(ticker)
    if not articles:
        return {"ticker": ticker, "overall_score": 0.0, "headlines": [], "summary": "No news found.", "cached": False}

    headline_texts = "\n".join(f"- {a['headline']}" for a in articles[:15])
    prompt = (
        f"Analyze market sentiment for stock ticker {ticker}.\n"
        f"Headlines:\n{headline_texts}\n\n"
        f"Return JSON only (no markdown): "
        f'{{ "overall_score": <float -1 to 1>, "headlines": [{{"text": "...", "score": <float>, "impact": "high|medium|low"}}], '
        f'"summary": "<1-2 sentence summary>" }}'
    )

    analysis = {"overall_score": 0.0, "headlines": [], "summary": "Analysis unavailable."}

    if BRIDGE_AVAILABLE:
        try:
            result = archie_bridge(
                prompt=prompt,
                user_id=1,
                agent_id=None,
                task_type="stock_analysis",
                try_local_first=True,
                enable_memory=False,
            )
            raw = result.get("response", "")
            # Extract JSON from response
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(raw[start:end])
                analysis.update(parsed)
        except Exception as e:
            logger.warning(f"analyze_sentiment bridge ({ticker}): {e}")

    # Cache results
    try:
        import psycopg2.extras

        now = _now_utc()
        analyzed_headlines = {h["text"]: h.get("score", 0.0) for h in analysis.get("headlines", [])}

        with get_db_cursor(commit=True) as (conn, cur):
            for art in articles[:15]:
                score = analyzed_headlines.get(art["headline"])
                cur.execute(
                    """
                    INSERT INTO stock_news_cache (ticker, source, headline, url, sentiment_score, published_at, analyzed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        ticker,
                        art["source"],
                        art["headline"],
                        art.get("url"),
                        score,
                        art.get("published_at") or None,
                        now,
                    ),
                )
    except Exception as e:
        logger.error(f"analyze_sentiment cache write ({ticker}): {e}")

    return {
        "ticker": ticker,
        "overall_score": analysis.get("overall_score", 0.0),
        "headlines": analysis.get("headlines", []),
        "summary": analysis.get("summary", ""),
        "cached": False,
    }


def get_sentiment_history(ticker: str, limit: int = 20) -> list:
    """Return recent cached sentiment rows for ticker."""
    ticker = ticker.upper().strip()
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT source, headline, url, sentiment_score, published_at, analyzed_at
                FROM stock_news_cache
                WHERE ticker = %s
                ORDER BY analyzed_at DESC
                LIMIT %s
                """,
                (ticker, limit),
            )
            rows = cur.fetchall()
        return [
            {
                "source": r[0],
                "headline": r[1],
                "url": r[2],
                "sentiment_score": float(r[3]) if r[3] is not None else None,
                "published_at": r[4].isoformat() if r[4] else None,
                "analyzed_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_sentiment_history({ticker}): {e}")
        return []
