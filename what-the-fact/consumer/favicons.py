"""Which publisher favicons exist on disk, so /news only asks for icons that are there.

The icons are baked into the image by scripts/fetch_source_favicons.py (the containers are read_only; nothing can be cached at runtime).
That script fetches from each publisher's OWN domain with an honest self-identifying user-agent, and a publisher that refuses it (CBC,
Postmedia, SaltWire) simply has no file: the template shows a two-letter badge for those, which is the documented intended render.

Before this, the template requested /static/favicons/<slug>.png for EVERY source and let `onerror` swap in the badge, so each /news view made
one guaranteed 404 per icon-less source (9 of 46). Same page for the reader, but 9 wasted requests and 9 lines in every access log.
"""

import functools
import os

FAVICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "favicons")


@functools.lru_cache(maxsize=4)
def favicon_slugs(directory=FAVICON_DIR):
    """frozenset of slugs that have a <slug>.png. Cached for the process: the image is read-only, so a new file arrives with a new image."""
    try:
        return frozenset(os.path.splitext(f)[0] for f in os.listdir(directory) if f.endswith(".png"))
    except OSError:
        return frozenset()


def has_favicon(slug, directory=FAVICON_DIR):
    """True only for a non-empty slug that has an icon file. An unreadable directory means NO icons (badges), never an error page."""
    return bool(slug) and slug in favicon_slugs(directory)
