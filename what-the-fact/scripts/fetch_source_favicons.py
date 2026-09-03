#!/usr/bin/env python3
"""Fetch each source's favicon from ITS OWN domain and store it locally.

WHY THIS EXISTS
    /news rendered every source logo via
        https://www.google.com/s2/favicons?domain=<publisher>
    which is a THIRD-PARTY REQUEST PER SOURCE PER PAGE VIEW — up to 46 of them,
    telling Google which outlets each reader browses. On a site whose whole
    position is sovereignty (and one that had just removed CARTO tiles from /map
    for exactly this reason) that is the wrong default.

    ⚠️ tests/test_wtf_map.py::_FORBIDDEN_HOSTS did NOT catch it: the guard lists
    unpkg / jsdelivr / cdnjs / cartocdn / tile.openstreetmap and knows nothing
    about google.com. news.html was never exempt — the guard simply had no
    opinion. google.com is added to that list alongside this change, so the gap
    cannot silently reopen.

WHY BUILD-TIME AND NOT RUNTIME
    The wtf containers run `read_only: true` (verified live:
    ReadonlyRootfs=true, the only bind is /app/data for billing). The app
    therefore CANNOT write into consumer/static/ at runtime, and there is no
    volume for it. Images are baked with `COPY .`, so committing the assets is
    both the simplest and the only workable option: run this script, commit the
    PNGs, and they ship with the image.

WHY THE PUBLISHER'S OWN DOMAIN
    We already fetch these publishers' RSS and article bodies, so their origin is
    not a new party. Routing through Google's favicon service server-side would
    still hand Google the full list of outlets we track. Fetching from the
    publisher adds nobody.

USAGE
    python3 scripts/fetch_source_favicons.py --out consumer/static/favicons
    python3 scripts/fetch_source_favicons.py --out /tmp/favicons --force

    Re-run occasionally; logos change rarely. Existing files are skipped unless
    --force. Sources that yield nothing are simply absent — the template falls
    back to a two-letter monogram, which is also the correct rendering for a
    publisher that has no usable icon.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import sys
import urllib.parse
import urllib.request

SIZE = 32
TIMEOUT = 12
UA = "Mozilla/5.0 (compatible; WhatTheFactBot/1.0; +https://what-the-fact.com)"

# rel values that denote a site icon, in rough order of preference. apple-touch
# icons are usually the largest and cleanest, so they are tried FIRST — a 180px
# PNG downsamples to 32 far better than a 16px .ico upscales.
_ICON_RELS = ("apple-touch-icon", "icon", "shortcut icon")
_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
_REL_RE = re.compile(r'rel\s*=\s*["\']([^"\']+)["\']', re.I)
_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.I)


def _get(url: str, limit: int = 2_000_000) -> bytes | None:
    """Fetch a URL. Returns None on ANY failure — this script must never raise."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            if r.status != 200:
                return None
            return r.read(limit)
    except Exception:
        return None


def _icon_candidates(site_url: str) -> list[str]:
    """Icon URLs to try, best first: declared <link rel=icon>, then /favicon.ico."""
    parts = urllib.parse.urlsplit(site_url)
    origin = f"{parts.scheme or 'https'}://{parts.netloc}"
    found: list[tuple[int, str]] = []

    html = _get(site_url)
    if html:
        try:
            text = html.decode("utf-8", "ignore")
        except Exception:
            text = ""
        for tag in _LINK_RE.findall(text):
            rel_m, href_m = _REL_RE.search(tag), _HREF_RE.search(tag)
            if not rel_m or not href_m:
                continue
            rel = rel_m.group(1).strip().lower()
            for rank, want in enumerate(_ICON_RELS):
                if want in rel:
                    found.append((rank, urllib.parse.urljoin(site_url, href_m.group(1))))
                    break

    # Stable: preference rank first, document order preserved within a rank.
    ordered = [u for _, u in sorted(found, key=lambda t: t[0])]
    ordered.append(urllib.parse.urljoin(origin + "/", "favicon.ico"))

    seen, out = set(), []
    for u in ordered:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _to_png(raw: bytes) -> bytes | None:
    """Normalise any icon format to a SIZExSIZE RGBA PNG, or None if unusable.

    Pillow is the validator as well as the converter: bytes it cannot open are
    not an image, whatever the content-type header claimed. Several publishers
    serve an HTML error page with image/x-icon.
    """
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(raw))
        # .ico carries several sizes; Image.open picks one, so ask for the
        # largest available before downsampling.
        if getattr(im, "n_frames", 1) > 1 and im.format == "ICO":
            try:
                im = Image.open(io.BytesIO(raw))
                im.size = max(im.ico.sizes())  # type: ignore[attr-defined]
            except Exception:
                pass
        im = im.convert("RGBA")
        im.thumbnail((SIZE, SIZE), Image.LANCZOS)
        canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        canvas.paste(im, ((SIZE - im.width) // 2, (SIZE - im.height) // 2))
        buf = io.BytesIO()
        canvas.save(buf, "PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        return None


def _sources_from_file(path: str) -> list[tuple[str, str]]:
    """Read `slug<TAB>url` lines. Blank lines and `#` comments ignored.

    The zero-dependency path: no DB driver, no credentials, no app import. Handy
    both for a one-off run from a host that has psql but not the app's secrets,
    and for reproducing a fetch from a checked-in list.

        psql -At -F$'\\t' -c "SELECT slug,url FROM wtf.sources WHERE url IS NOT NULL" > s.tsv
    """
    out: list[tuple[str, str]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t") if "\t" in line else line.split(None, 1)
            if len(parts) == 2 and parts[0] and parts[1]:
                out.append((parts[0].strip(), parts[1].strip()))
    return out


def _sources(dsn: str | None = None) -> list[tuple[str, str]]:
    """(slug, url) for every source with a url.

    ⚠️ `--dsn` exists because this script is a BUILD-TIME tool and is not run
    from inside a wtf container. Falling back to `consumer.routes._db()` requires
    the app's own DB env, which only the wtf containers carry — running it from
    `archie_platform` (the one place with both outbound network AND the repo
    mounted) dies on `Expected string or URL object, got None`. Imports stay
    local so --help works with neither a database nor the app package.
    """
    from sqlalchemy import create_engine, text  # noqa: E402

    if dsn:
        engine, schema = create_engine(dsn), os.getenv("WTF_SCHEMA", "wtf")
    else:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from consumer.routes import _db, _schema  # noqa: E402

        engine, schema = _db(), _schema()

    with engine.begin() as c:
        rows = c.execute(
            text(f"SELECT slug, url FROM {schema}.sources "
                 "WHERE url IS NOT NULL AND slug IS NOT NULL ORDER BY slug")
        ).all()
    return [(r[0], r[1]) for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="output directory for <slug>.png")
    ap.add_argument("--force", action="store_true", help="refetch sources already on disk")
    ap.add_argument("--dsn", default=os.getenv("WTF_DSN"),
                    help="SQLAlchemy DSN for the wtf DB. Defaults to $WTF_DSN; without "
                         "either, falls back to the app's own config (only works inside "
                         "a wtf container).")
    ap.add_argument("--sources-file",
                    help="slug<TAB>url per line, instead of querying the DB. No driver "
                         "and no credentials needed.")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    got = skipped = failed = 0

    sources = (_sources_from_file(args.sources_file) if args.sources_file
               else _sources(args.dsn))
    print(f"{len(sources)} source(s) to consider\n")

    for slug, url in sources:
        dest = os.path.join(args.out, f"{slug}.png")
        if os.path.exists(dest) and not args.force:
            skipped += 1
            continue

        png = None
        for cand in _icon_candidates(url):
            raw = _get(cand)
            if raw:
                png = _to_png(raw)
                if png:
                    break

        if png:
            with open(dest, "wb") as fh:
                fh.write(png)
            got += 1
            print(f"  ok      {slug}")
        else:
            failed += 1
            print(f"  MISSING {slug}  ({url}) — template falls back to monogram")

    print(f"\nfetched={got} skipped={skipped} missing={failed}")
    # A missing icon is NOT an error: the monogram fallback is a correct render.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
