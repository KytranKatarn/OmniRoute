"""Generic sitemap-index fetcher — for sources that removed RSS (#4909).

Postmedia (montrealgazette / leaderpost / thestarphoenix) dropped their
WordPress /feed endpoints in mid-2026; their sitemap.xml remains open: an
index of date-parameterized day-sitemaps (sitemap.xml?yyyy=&mm=&dd=) whose
<url> entries carry only <loc> + <lastmod> — no titles. This fetcher reads
the newest N day-sitemaps and fetches each NEW article page (bounded) to
extract the real title (og:title, falling back to <title>, then a
slug-derived string). Bodies stay empty — the scout body backlog worker
fills them later, same as thin RSS entries.

Activated per source by prefixing wtf.sources.rss_feed with 'sitemap:'
(migration 048); the run.py generic loop routes on that prefix and passes
the source's recently-known URLs so title lookups only hit NEW articles.
"""

from datetime import datetime, timezone
import html as _html
import logging
import re

import requests

logger = logging.getLogger(__name__)

_UA = {"User-Agent": "WTF-Ingest/1.0 (+https://what-the-fact.com)"}
_DAY_SITEMAPS = 2        # newest N day-sitemaps from the index
_MAX_NEW_PER_RUN = 40    # page-title fetches per source per run (new URLs only)

_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
_URL_BLOCK_RE = re.compile(r"<url>(.*?)</url>", re.S)
_LASTMOD_RE = re.compile(r"<lastmod>([^<]+)</lastmod>")
_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', re.I
)
_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.I)


def _get_text(url: str, timeout: int = 15) -> str:
    resp = requests.get(url, timeout=timeout, headers=_UA)
    resp.raise_for_status()
    return resp.text


def _page_title(url: str) -> str | None:
    """Fetch just the head of an article page and pull og:title / <title>."""
    try:
        resp = requests.get(url, timeout=12, headers=_UA, stream=True)
        resp.raise_for_status()
        chunk = next(resp.iter_content(65536)).decode("utf-8", "ignore")
        resp.close()
        m = _OG_TITLE_RE.search(chunk) or _TITLE_RE.search(chunk)
        if m:
            return _html.unescape(m.group(1)).strip() or None
    except Exception:
        pass
    return None


def _slug_title(url: str) -> str:
    seg = url.rstrip("/").rsplit("/", 1)[-1]
    seg = seg.split("?")[0]
    return (seg.replace("-", " ").strip() or url).capitalize()


def _parse_lastmod(raw: str | None) -> datetime:
    """ISO lastmod (usually offset-aware) → naive UTC, matching the RSS path."""
    if raw:
        try:
            dt = datetime.fromisoformat(raw.strip())
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            pass
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fetch_sitemap(index_url: str, source_slug: str,
                  known_urls: set[str] | None = None) -> list[dict]:
    """Fetch newest day-sitemaps from a sitemap index; return raw article dicts
    in the same shape as rss_generic.fetch_rss. Only NEW urls (not in
    known_urls) get a page-title fetch, capped at _MAX_NEW_PER_RUN."""
    known = known_urls or set()

    index_xml = _get_text(index_url)
    day_maps = _LOC_RE.findall(index_xml)[:_DAY_SITEMAPS]
    if not day_maps:
        logger.warning("%s: sitemap index at %s had no <loc> entries",
                       source_slug, index_url)
        return []

    out: list[dict] = []
    fetched_titles = 0
    for day_url in day_maps:
        try:
            day_xml = _get_text(_html.unescape(day_url))
        except Exception as exc:
            logger.warning("%s: day sitemap %s failed: %s",
                           source_slug, day_url, exc)
            continue
        for block in _URL_BLOCK_RE.findall(day_xml):
            loc_m = _LOC_RE.search(block)
            if not loc_m:
                continue
            url = _html.unescape(loc_m.group(1)).strip()
            if not url or url in known:
                continue
            if fetched_titles >= _MAX_NEW_PER_RUN:
                break
            lastmod_m = _LASTMOD_RE.search(block)
            title = _page_title(url) or _slug_title(url)
            fetched_titles += 1
            out.append({
                "external_id": url,
                "title": title,
                "body": "",  # scout body backlog fills this later
                "url": url,
                "published_at": _parse_lastmod(
                    lastmod_m.group(1) if lastmod_m else None),
                "author": None,
            })
        if fetched_titles >= _MAX_NEW_PER_RUN:
            break

    logger.info("%s: sitemap fetched %d new articles (%d day-maps)",
                source_slug, len(out), len(day_maps))
    return out
