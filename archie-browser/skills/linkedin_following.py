"""LinkedIn following — list the people + company Pages the acting account follows (read-only).

Feeds the S.I.G.N.A.L. engagement target list (auto-engagement Phase 2b): who the
account already follows is the natural candidate pool for approval-gated
likes/comments. The home FEED is withheld from automation, but the network-manager
listing pages ARE served to the authenticated headless session (verified live on
Terry/377 — screenshots rendered full lists).

Sources:
  people    -> /mynetwork/network-manager/people-follow/following/
  companies -> /mynetwork/network-manager/company/

Extraction notes (learned live 2026-07-02):
  - The lists are VIRTUALIZED (entries unmount as you scroll — KB #273535), so
    links are harvested every scroll round, not once at the end.
  - The network-manager view is shadow-DOM-heavy: page.content() does NOT
    serialize shadow roots, so a raw-HTML regex sees zero entries even though the
    page renders. Playwright locators pierce open shadow DOM — they are the
    PRIMARY harvester; the regex pass is a cheap bonus for non-shadow renders.

Honesty contract: success=False when a list renders zero entries WITHOUT an explicit
empty-state (withheld / layout changed / logged out) — never phantom-succeed.
Read-only — no writes.
"""
import os
import re
from datetime import datetime

SKILL_NAME = "linkedin_following"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

_SOURCES = {
    "people": {
        "url": "https://www.linkedin.com/mynetwork/network-manager/people-follow/following/",
        "prefix": "/in/",
    },
    "companies": {
        "url": "https://www.linkedin.com/mynetwork/network-manager/company/",
        "prefix": "/company/",
    },
}

_HREF_RE = re.compile(r'href="([^"]+)"')

# Explicit LinkedIn empty-state copy — an empty list WITH one of these is a real
# (successful) empty result, not a withheld/broken page.
_EMPTY_MARKERS = [
    "not following",
    "no pages",
    "nothing to see",
    "you don't follow",
    "you aren’t following",
]


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, timeout=5000, animations="disabled")
        return path
    except Exception:
        return None


def _dismiss_overlays(page):
    """Dismiss LinkedIn interstitial modals (Premium upsell, etc.). Harmless if none."""
    for attempt in [
        lambda: page.locator(".artdeco-modal__dismiss").first.click(timeout=2000),
        lambda: page.locator('button[aria-label="Dismiss"]').first.click(timeout=2000),
    ]:
        try:
            attempt()
            page.wait_for_timeout(500)
            return
        except Exception:
            continue
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    except Exception:
        pass


def _canon(href: str, prefix: str):
    """Canonical entity URL (absolute, no query/fragment/trailing slash) for an
    entity ROOT link like /in/<vanity> or /company/<slug> — else None."""
    if not href:
        return None
    href = href.split("?")[0].split("#")[0]
    if href.startswith("/"):
        href = "https://www.linkedin.com" + href
    if not href.startswith("https://www.linkedin.com"):
        return None
    href = href.rstrip("/")
    if prefix not in href:
        return None
    tail = href.split(prefix, 1)[1]
    if not tail or "/" in tail:  # deeper paths (posts/, about/, ...) are not entities
        return None
    return href


def _harvest(page, prefix: str, seen: dict):
    """Collect entity links from the CURRENT render into ``seen`` (url -> name).

    Locators first (they pierce open shadow DOM — the network-manager list lives in
    shadow roots, invisible to page.content()); raw-HTML regex second as a bonus.
    Called every scroll round because the list virtualizes."""
    try:
        anchors = page.locator(f'main a[href*="{prefix}"]')
        n = min(anchors.count(), 120)
        for i in range(n):
            a = anchors.nth(i)
            try:
                url = _canon(a.get_attribute("href", timeout=500), prefix)
                if not url:
                    continue
                if url not in seen:
                    seen[url] = ""
                if not seen[url]:
                    text = (a.inner_text(timeout=500) or "").strip().replace("\n", " ")
                    if 1 < len(text) <= 80:
                        seen[url] = text
            except Exception:
                continue
    except Exception:
        pass
    for m in _HREF_RE.finditer(page.content() or ""):
        url = _canon(m.group(1), prefix)
        if url and url not in seen:
            seen[url] = ""


def _collect(page, kind: str, limit: int, scroll_rounds: int) -> dict:
    src = _SOURCES[kind]
    page.goto(src["url"], wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    current = (page.url or "").lower()
    if "authwall" in current or "/login" in current or "/checkpoint" in current:
        _screenshot(page, f"following_{kind}_authwall")
        return {"ok": False, "error": "logged_out", "entries": []}

    _dismiss_overlays(page)
    seen: dict = {}
    _harvest(page, src["prefix"], seen)
    for _ in range(max(1, scroll_rounds)):
        if len(seen) >= limit:
            break
        try:
            page.mouse.wheel(0, 2400)
        except Exception:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)
        _harvest(page, src["prefix"], seen)

    shot = _screenshot(page, f"following_{kind}")
    entries = [{"url": u, "name": n} for u, n in list(seen.items())[:limit]]

    if not entries:
        body = ""
        try:
            body = (page.locator("main").first.inner_text(timeout=3000) or "").lower()
        except Exception:
            pass
        if any(marker in body for marker in _EMPTY_MARKERS):
            return {"ok": True, "empty_state": True, "entries": [], "screenshot": shot}
        # Zero entries and no empty-state = withheld/changed page. Fail honestly.
        return {"ok": False, "error": "no_entries_rendered", "entries": [], "screenshot": shot}

    return {"ok": True, "entries": entries, "screenshot": shot}


def execute(page, params: dict) -> dict:
    kind = (params.get("kind") or "all").strip().lower()
    limit = int(params.get("limit", 50))
    scroll_rounds = int(params.get("scroll_rounds", 8))
    if kind not in ("people", "companies", "all"):
        raise ValueError("kind must be 'people', 'companies', or 'all'")

    kinds = ["people", "companies"] if kind == "all" else [kind]
    out = {"success": True, "kind": kind, "people": [], "companies": [], "errors": {}}
    screenshots = []
    for k in kinds:
        res = _collect(page, k, limit, scroll_rounds)
        if res.get("screenshot"):
            screenshots.append(res["screenshot"])
        if res["ok"]:
            out[k] = res["entries"]
        else:
            out["errors"][k] = res["error"]

    # success only if every requested list either rendered entries or showed a real
    # empty-state; a logged_out/no_entries_rendered on ANY requested kind = failure.
    if out["errors"]:
        out["success"] = False
        out["error"] = "; ".join(f"{k}: {v}" for k, v in out["errors"].items())
    out["total"] = len(out["people"]) + len(out["companies"])
    if screenshots:
        out["screenshot_path"] = screenshots[-1]
    return out
