"""LinkedIn OWN comments — the account holder's manually-written comments (read-only).

WHY (#5644 slice 2): the notification bell only ever surfaces comments OTHERS leave on
YOUR posts (that is what `linkedin_comments` holds). The comments the owner writes BY HAND
on other people's posts are invisible to every existing path — and per the owner they are
the single richest untapped voice sample. They live on the profile's
`/recent-activity/comments/` tab.

TWO DESIGN RULES, both learned from prior LinkedIn breakage:

1. NO POSITIONAL ZIPPING. `linkedin_recent_activity` collects activity URNs and comment
   URNs page-wide and pairs them by index, guarded by `len(comment_urns) >= len(urns)`.
   Measured on Terry 2026-08-16: 5 activity URNs vs **6** comment URNs -> that guard
   passes while the pairing is not necessarily true (a second comment on one post shifts
   every later pair). A mis-paired URN is a deep-link to SOMEONE ELSE'S comment, i.e. it
   would file a stranger's words as the owner's voice. Here each item's URN and text are
   read from the SAME container element, so pairing is structural, not inferred.

2. THE SKILL DOES NOT PARSE. It returns each item's raw innerText and lets the platform
   service isolate the comment. The skill is image-baked (every parser tweak = a container
   rebuild); the service is volume-mounted and unit-testable against captured fixtures.
   Keeping the split here is what makes the parser cheap to correct when LinkedIn shifts.

Read-only. No writes, no LLM.
"""
import os
import re
from datetime import datetime
from urllib.parse import quote

SKILL_NAME = "linkedin_own_comments"
PLATFORMS = ["linkedin"]

# Declared here rather than added to the two `_READ_ONLY_SKILLS` allowlists (skill_runner
# + headed_tasks): an explicit module-level flag overrides the allowlist in BOTH runners,
# so this is one source of truth instead of two lists that can drift apart. Without it a
# new skill defaults to MUTATING — safe, but it would make this read-only skill fail fast
# whenever the trusted profile is unavailable.
MUTATING = False

_SHOT_DIR = "/profiles"
_ACTIVITY_RE = re.compile(r"urn:li:activity:\d+")


def _shot(page, name):
    path = f"{_SHOT_DIR}/_own_comments_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, full_page=False, timeout=10000, animations="disabled")
        return path if os.path.exists(path) else "shot_failed: file_not_written"
    except Exception as exc:
        return f"shot_failed: {type(exc).__name__}"


def _comments_url(profile_url: str) -> str:
    base = profile_url.split("?")[0].rstrip("/")
    low = base.lower()
    if "/recent-activity/comments" in low:
        return base + "/"
    if "/recent-activity" in low:  # some other activity tab -> retarget to comments
        return base.rsplit("/recent-activity", 1)[0] + "/recent-activity/comments/"
    return base + "/recent-activity/comments/"


# Per-item extraction. The container is the element carrying data-urn (the activity id);
# the comment URN is read from INSIDE that same container so the two cannot be mismatched.
_JS_ITEMS = r"""
(maxItems) => {
  const out = { items: [], containers_seen: 0, strategy: 'none' };

  // Container candidates, most specific first. data-urn is what the existing
  // recent-activity skill already proved present on this surface.
  let nodes = Array.from(document.querySelectorAll('[data-urn]'));
  if (nodes.length) { out.strategy = 'data_urn'; }
  else {
    // SDUI fallback: feed items carry a componentkey.
    nodes = Array.from(document.querySelectorAll('[componentkey]'))
      .filter(n => /urn:li:activity:/.test(n.innerHTML || ''));
    if (nodes.length) out.strategy = 'componentkey';
  }
  out.containers_seen = nodes.length;

  const seen = new Set();
  for (const n of nodes) {
    if (out.items.length >= maxItems) break;
    const html = n.innerHTML || '';
    // The comment URN must come from INSIDE this container (rule 1).
    const cm = html.match(/urn:li:comment:\(?[^\s"'<>\\]{6,}?\)/) || html.match(/urn:li:comment:\d+/);
    const am = (n.getAttribute('data-urn') || '').match(/urn:li:activity:\d+/)
            || html.match(/urn:li:activity:\d+/);
    if (!cm || !am) continue;
    const key = cm[0];
    if (seen.has(key)) continue;
    seen.add(key);
    out.items.push({
      activity_urn: am[0],
      comment_urn: key,
      // RAW text — parsing happens service-side (rule 2). Capped generously: a long
      // comment is exactly the sample worth keeping.
      raw_text: (n.innerText || '').replace(/ /g, ' ').slice(0, 4000),
    });
  }
  return out;
}
"""


def _expand_more(page) -> int:
    """Click every "…more" affordance so comments are captured in FULL.

    WHY: LinkedIn collapses a long comment in the feed view at a fixed visible budget —
    measured 2026-08-16, ALL 6 of Terry's captured comments came back truncated, two of
    them at exactly 1245 chars (the cap, not a coincidence). A clipped comment is a
    degraded voice sample, and the clipping is invisible once the text is stored.

    Clicking a disclosure control is not a mutation: nothing is published, liked or sent.
    Locators are RE-RESOLVED on every pass — SDUI re-renders the list after each expand,
    so a handle cached across passes goes stale and silently stops clicking.
    """
    clicked = 0
    for _ in range(4):
        progressed = False
        try:
            btns = page.locator(
                "button:has-text('…more'), button:has-text('...more'), "
                "button:has-text('see more'), button:has-text('See more')"
            )
            count = min(btns.count(), 40)
        except Exception:
            break
        for i in range(count):
            try:
                b = btns.nth(i)
                if b.is_visible():
                    b.click(timeout=1500)
                    clicked += 1
                    progressed = True
                    page.wait_for_timeout(120)
            except Exception:
                continue  # one stale/covered control must not abort the pass
        if not progressed:
            break
    if clicked:
        page.wait_for_timeout(600)
    return clicked


def execute(page, params: dict) -> dict:
    profile_url = (params.get("profile_url") or "").strip()
    limit = int(params.get("limit", 20))
    if not profile_url:
        raise ValueError("profile_url is required for linkedin_own_comments")

    url = _comments_url(profile_url)
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    # SDUI mounts lazily — without the scroll only the first screenful exists, so a quiet
    # profile and a short scroll are indistinguishable. Scroll until the container count
    # stops growing (bounded), which is also how we page past the initial batch.
    scrolls = 0
    last_count = -1
    for _ in range(12):
        try:
            count = page.evaluate("document.querySelectorAll('[data-urn]').length")
        except Exception:
            break
        if count == last_count and count > 0:
            break
        last_count = count
        try:
            page.evaluate("window.scrollBy(0, Math.round(window.innerHeight * 0.9))")
        except Exception:
            break
        page.wait_for_timeout(900)
        scrolls += 1

    expanded = _expand_more(page)

    extract_error = ""
    data = {}
    try:
        data = page.evaluate(_JS_ITEMS, limit) or {}
    except Exception as exc:
        extract_error = f"{type(exc).__name__}: {exc}"

    items = []
    for it in data.get("items") or []:
        activity = it.get("activity_urn") or ""
        curn = it.get("comment_urn") or ""
        post_url = f"https://www.linkedin.com/feed/update/{activity}/" if activity else None
        items.append(
            {
                "activity_urn": activity,
                "comment_urn": curn,
                "post_url": post_url,
                # The ?commentUrn= deep-link is the ONLY form that renders the thread to
                # automation (KB #274178/#274179) — carried so a later pass can open it.
                "comment_url": (
                    f"{post_url}?commentUrn={quote(curn, safe='')}" if post_url and curn else None
                ),
                "raw_text": it.get("raw_text") or "",
            }
        )

    html_low = (page.content() or "").lower()
    walled = ("authwall" in html_low) or ("sign in to view" in html_low) or ("join linkedin" in html_low)

    # HONEST verdict: an empty list is a legitimate answer (the owner may simply not have
    # commented), so success only goes False on a positive auth wall or a failed extract.
    # `strategy` + `containers_seen` are what separate "no comments" from "selector broke".
    result = {
        "success": (not walled) and not extract_error,
        "profile_url": profile_url,
        "comments_url": url,
        "total": len(items),
        "items": items,
        "strategy": data.get("strategy", "none"),
        "containers_seen": data.get("containers_seen", 0),
        "scrolls": scrolls,
        # If this is 0 while comments come back truncated, the disclosure control moved —
        # the samples are being silently clipped and the parser cannot tell.
        "expanded": expanded,
        "screenshot": _shot(page, "tab"),
    }
    if walled:
        result["result"] = "auth_wall — the session is not logged in for this profile"
    elif extract_error:
        result["result"] = f"extract_failed — {extract_error}"
    elif not items:
        result["result"] = (
            "no comment items found "
            f"(containers_seen={result['containers_seen']}, strategy={result['strategy']}) — "
            "empty tab, or a LinkedIn layout change"
        )
    return result
