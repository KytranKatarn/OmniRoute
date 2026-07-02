"""LinkedIn profile view — navigate to any profile, screenshot, extract key info.

HONEST-READ rewrite (#4612, KB #276950): the original phantom-succeeded — it
returned success:True with every field empty (stale class selectors + a
non-shadow-piercing About extract) and a screenshot_path it never wrote
(silent try/except). Now:
  - top-card fields extracted via a shadow-DOM-piercing walk (KB #277237:
    locators pierce, document.querySelectorAll does NOT cross shadow roots)
    with locator fallbacks;
  - success requires at least name OR headline OR about to be non-empty;
  - screenshots go to the mounted /profiles volume (retrievable from the host
    at /mnt/data2/browser-profiles/) and failures are reported, not hidden.
"""
import os
from datetime import datetime

SKILL_NAME = "linkedin_profile_view"
PLATFORMS = ["linkedin"]

_SHOT_DIR = "/profiles"


def _shot(page, name):
    """Screenshot to the MOUNTED /profiles volume. Honest: returns the path on
    success, or 'shot_failed: <why>' — never a path that was not written."""
    path = f"{_SHOT_DIR}/_profile_view_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, full_page=False, timeout=15000, animations="disabled")
        return path if os.path.exists(path) else "shot_failed: file_not_written"
    except Exception as exc:
        return f"shot_failed: {type(exc).__name__}"


# Top-card extract by LINE-PARSING main.innerText — probe-verified on Terry/377
# (2026-07-02): the self-profile renderer has NO H1; main.innerText opens with
# "name / pronouns / headline / <location> · Contact info / N followers · N
# connections" as separate block lines. About anchors on id="about" (walk
# fallback pierces shadow roots, KB #277237).
_JS_EXTRACT = r"""
() => {
  function* walk(root){ for (const el of root.querySelectorAll('*')) { yield el; if (el.shadowRoot) yield* walk(el.shadowRoot); } }
  const out = { name:'', headline:'', location:'', connections:'', about:'' };

  const main = document.querySelector('main');
  const lines = ((main ? main.innerText : document.body.innerText) || '')
    .split('\n').map(s => s.trim()).filter(Boolean);
  const noise = /^(he\/him|she\/her|they\/them|·|(1st|2nd|3rd)\b|degree connection|verified|open to)/i;
  let i = 0;
  while (i < lines.length && noise.test(lines[i])) i++;
  if (i < lines.length) { out.name = lines[i].slice(0, 120); i++; }
  while (i < lines.length && noise.test(lines[i])) i++;
  if (i < lines.length && !/contact info/i.test(lines[i])) out.headline = lines[i].slice(0, 220);
  // location: joined "<loc> · Contact info" OR the line just above a bare
  // "Contact info" line (the link renders as its own innerText line on some loads)
  const locLine = lines.find(l => /· contact info/i.test(l));
  if (locLine) out.location = locLine.split('·')[0].trim().slice(0, 120);
  else {
    const ci = lines.findIndex(l => /^contact info$/i.test(l));
    if (ci > 0) out.location = lines[ci - 1].replace(/·\s*$/, '').trim().slice(0, 120);
  }
  const connLine = lines.find(l => /(followers|connections)/i.test(l));
  if (connLine) out.connections = connLine.slice(0, 60);

  // about: section anchored on #about (fallback: heading text 'About')
  const anchor = document.getElementById('about');
  let sec = anchor ? (anchor.closest('section') || anchor.parentElement) : null;
  if (!sec) {
    for (const el of walk(document)) {
      if ((el.tagName==='H2'||el.tagName==='SPAN'||el.tagName==='DIV') && (el.innerText||'').trim()==='About') { sec = el.closest('section') || el.parentElement; break; }
    }
  }
  if (sec) {
    let t = (sec.innerText||'').replace(/\s+/g,' ').trim();
    t = t.replace(/^About\s*/i,'').replace(/\s*…see more\s*$/i,'').replace(/\s*see more\s*$/i,'');
    out.about = t.slice(0, 800);
  }
  return out;
}
"""


def execute(page, params: dict) -> dict:
    profile_url = params.get("profile_url", "").strip()
    if not profile_url:
        raise ValueError("profile_url is required for linkedin_profile_view")

    # Strip tracking params — navigate to clean profile URL
    clean_url = profile_url.split("?")[0].rstrip("/")

    page.goto(clean_url, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    fields = {"name": "", "headline": "", "location": "", "connections": "", "about": ""}
    extract_error = ""
    try:
        fields.update({k: v for k, v in (page.evaluate(_JS_EXTRACT) or {}).items() if v})
    except Exception as exc:
        extract_error = f"{type(exc).__name__}: {exc}"

    # Locator fallbacks (Playwright locators pierce shadow DOM natively)
    if not fields["name"]:
        try:
            fields["name"] = page.locator("h1").first.inner_text(timeout=4000).strip()[:120]
        except Exception:
            pass
    if not fields["connections"]:
        try:
            fields["connections"] = (
                page.locator("span, a").filter(has_text="connections").first.inner_text(timeout=3000).strip()[:60]
            )
        except Exception:
            pass

    # Scroll to top + settle before the shot — the profile page animates and an
    # immediate screenshot times out (probe's about_view shot works with this).
    try:
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass
    page.wait_for_timeout(1500)
    screenshot = _shot(page, "top")

    # HONEST verdict — an all-empty extract is a failed read, not a success.
    got_content = bool(fields["name"] or fields["headline"] or fields["about"])
    result = {
        "success": got_content,
        "profile_url": clean_url,
        "final_url": page.url,
        **fields,
        "screenshot": screenshot,
        "screenshot_dir": "/mnt/data2/browser-profiles/ (host)",
    }
    if not got_content:
        result["result"] = "extraction_empty — page may be an auth wall, a 404, or a renderer change"
        if extract_error:
            result["extract_error"] = extract_error
    return result
