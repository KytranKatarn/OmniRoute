"""LinkedIn profile probe — READ-ONLY diagnostic.

Navigates to the logged-in user's own profile (/in/me) and dumps the real DOM
state needed to fix linkedin_profile_edit / linkedin_profile_view:
  - where /in/me actually landed (url, title)
  - whether the page is the authenticated self-profile
  - every edit/add candidate button (tag, aria-label, text)
  - whether the About section (#about) exists
  - best-guess name + headline text

No mutations. Used to gather evidence before changing selectors.
"""

SKILL_NAME = "linkedin_profile_probe"
PLATFORMS = ["linkedin"]

_JS_DUMP = r"""
() => {
  const out = { url: location.href, title: document.title };
  const h1 = document.querySelector('h1');
  out.h1 = h1 ? (h1.innerText || '').trim() : null;
  const hl = document.querySelector('div.text-body-medium.break-words')
          || document.querySelector('.pv-text-details__left-panel div.text-body-medium');
  out.headline_guess = hl ? (hl.innerText || '').trim() : null;
  out.has_about = !!document.getElementById('about');
  out.has_add_section = !!Array.from(document.querySelectorAll('button'))
      .find(b => ((b.getAttribute('aria-label')||'') + (b.innerText||''))
                   .toLowerCase().includes('add profile section'));
  const els = Array.from(document.querySelectorAll('button, a'));
  out.control_count = els.length;
  const cand = [];
  for (const b of els) {
    const lbl = (b.getAttribute('aria-label') || '').trim();
    const txt = (b.innerText || '').trim().slice(0, 50);
    const blob = (lbl + ' ' + txt).toLowerCase();
    if (blob.includes('edit') || blob.includes('add profile') ||
        blob.includes('add section') || blob.includes('intro') ||
        (blob.includes('about') && blob.includes('edit'))) {
      cand.push({ tag: b.tagName, aria: lbl.slice(0, 70), text: txt });
    }
  }
  out.candidates = cand.slice(0, 50);
  const main = document.querySelector('main') || document.body;
  out.top_card_text = (main.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 600);
  return out;
}
"""


def execute(page, params: dict) -> dict:
    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    # Trigger lazy-loaded sections (About lives below the fold).
    try:
        for _ in range(4):
            page.evaluate("() => window.scrollBy(0, document.body.scrollHeight/4)")
            page.wait_for_timeout(600)
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(800)
    except Exception:
        pass

    try:
        dump = page.evaluate(_JS_DUMP)
    except Exception as exc:
        return {"success": False, "result": f"probe failed: {type(exc).__name__}: {exc}"}

    # logged-in heuristic: not on a login/authwall URL and we have an h1
    url = dump.get("url", "")
    logged_in = "/authwall" not in url and "linkedin.com/login" not in url
    dump["logged_in_guess"] = logged_in
    dump["success"] = True
    dump["result"] = (
        f"url={url} | h1={dump.get('h1')!r} | has_about={dump.get('has_about')} | "
        f"candidates={len(dump.get('candidates', []))}"
    )
    return dump
