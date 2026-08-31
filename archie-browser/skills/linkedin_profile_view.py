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

SKILLS + EXPERIENCE (#5644): added as voice-grounding material for S.I.G.N.A.L.
Two deliberate constraints, both learned the hard way:
  - `experience` is returned as ORDERED RAW LINES, not parsed {title, company,
    dates} entries. On the SDUI profile the visual order IS the only schema, and
    a mis-parsed entry that swaps a company into a title is worse than no entry
    at all (KB #288935 — the search-card `<p>`-order bug shipped exactly that).
    Voice grounding needs faithful text, not a pretty shape.
  - every section reports HOW it was found via `strategy` (anchor_id /
    heading_walk / none). A selector break and a genuinely empty section used to
    be byte-identical; `strategy: "none"` now distinguishes them.
These sections mount LAZILY well below the fold, so the pre-extract scroll is
load-bearing, not cosmetic — without it they are reliably absent.
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
  const out = { name:'', headline:'', location:'', connections:'', about:'',
                skills:[], experience:[], _strategy:{} };

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
    // 2600 = LinkedIn's own About limit. Was 800, which silently truncated Terry's
    // About mid-sentence (measured 2026-08-16: returned exactly 800 chars). A clipped
    // About is a degraded VOICE sample, and the clipping was invisible downstream.
    out.about = t.slice(0, 2600);
  }
  out._strategy.about = sec ? (anchor ? 'anchor_id' : 'heading_walk') : 'none';

  // ---- skills + experience (#5644) ----
  // Anchor on the section id LinkedIn still emits (#skills / #experience); fall
  // back to a shadow-piercing heading walk. Both sections render each entry
  // TWICE (visible + an a11y duplicate), so consecutive repeats are collapsed.
  function sectionFor(id, headingText){
    const a = document.getElementById(id);
    if (a) return [a.closest('section') || a.parentElement, 'anchor_id'];
    for (const el of walk(document)) {
      const tn = el.tagName;
      if ((tn==='H2'||tn==='SPAN'||tn==='DIV') && (el.innerText||'').trim()===headingText) {
        return [el.closest('section') || el.parentElement, 'heading_walk'];
      }
    }
    return [null, 'none'];
  }
  // Chrome/affordance lines that are page furniture, never content.
  const CHROME = /^(show all|see more|…see more|see less|endorse|add|edit|skills|experience|show credential|·|\d+ endorsement)/i;
  function sectionLines(sec, headingText){
    const raw = ((sec && sec.innerText) || '').split('\n').map(s => s.trim()).filter(Boolean);
    const out = [];
    for (const l of raw) {
      if (l === headingText) continue;
      if (CHROME.test(l)) continue;
      // collapse the a11y duplicate (same line repeated back-to-back)
      if (out.length && out[out.length-1].toLowerCase() === l.toLowerCase()) continue;
      out.push(l.slice(0, 200));
    }
    return out;
  }

  const [skillSec, skillHow] = sectionFor('skills', 'Skills');
  out.skills = sectionLines(skillSec, 'Skills').slice(0, 50);
  out._strategy.skills = skillHow;

  const [expSec, expHow] = sectionFor('experience', 'Experience');
  out.experience = sectionLines(expSec, 'Experience').slice(0, 120);
  out._strategy.experience = expHow;

  // DIAGNOSTIC (kept, not scaffolding): when a section comes back 'none', this is the
  // difference between "the profile has no Experience" and "LinkedIn renamed the hook".
  // Without it those two are byte-identical and a selector break reads as a sparse profile.
  const ids = [];
  for (const el of document.querySelectorAll('[id]')) {
    const v = el.id;
    if (/^(about|skills|experience|education|licenses|projects|volunteer|honors|recommendations|interests)/i.test(v)) ids.push(v);
  }
  const heads = [];
  for (const el of walk(document)) {
    if (el.tagName === 'H2') {
      const t = (el.innerText || '').trim().split('\n')[0].slice(0, 40);
      if (t && !heads.includes(t)) heads.push(t);
    }
  }
  out._diag = { anchor_ids: ids.slice(0, 20), h2_headings: heads.slice(0, 25) };

  return out;
}
"""


def _scroll_for_lazy_sections(page):
    """Skills/Experience mount lazily far below the fold — extract before this and
    they are reliably absent (which would read as 'this profile has no skills').
    Stepped scroll, then back to top so the top-card screenshot is unaffected."""
    try:
        for _ in range(6):
            page.evaluate("window.scrollBy(0, Math.round(window.innerHeight * 0.9))")
            page.wait_for_timeout(600)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(800)
        return True
    except Exception:
        return False


# ── details-page fallback (#6236) ─────────────────────────────────────────────
# MEASURED 2026-08-31 on Terry/377: Skills and Experience are NO LONGER RENDERED
# ON THE PROFILE AT ALL. The page's h2 set is
#   Terry Caetano · Suggested for you · Analytics · About · Featured · Activity ·
#   Profile language · Public profile & URL
# with anchor_ids EMPTY — so #skills/#experience and the 'Skills'/'Experience'
# heading walk both correctly returned strategy 'none'. Scrolling was not the
# problem (scrolled=True); the sections have moved to their own pages:
#   /in/<slug>/details/skills/      /in/<slug>/details/experience/
# Same failure family as the comment deep-link (#6035): the content is not on the
# page you are standing on, so navigate to the page that renders it.
#
# WHY LINE-BASED AND NOT A SELECTOR — this was probed, not assumed. On the details
# pages: [data-view-name] = 0, span[aria-hidden="true"] = 0, no /search/results/
# links, and every class is hashed (`_02484ad3 c2d1c236 …`) so it changes each
# LinkedIn deploy. The only <li> elements on the skills page are the five FILTER
# TABS, not the entries. There is no stable hook to bind to; visual line order is
# the whole schema, which is the same constraint the module docstring already
# records for experience.
_JS_DETAILS = r"""
() => {
  const main = document.querySelector('main') || document.body;
  // The 5 <li> on the skills page are the filter tabs (All / Industry Knowledge /
  // Tools & Technologies / Interpersonal Skills / Other Skills). Read them from the
  // DOM instead of hardcoding, so a renamed or localised tab is still excluded.
  const tabs = new Set();
  main.querySelectorAll('li').forEach(li => {
    const t = (li.innerText || '').trim();
    if (t && t.split('\n').length === 1 && t.length < 40) tabs.add(t.toLowerCase());
  });

  // `main` ALSO contains the right rail ("Who your viewers also viewed", suggested
  // profiles) and the global footer (Accessibility / Talent Solutions / LinkedIn
  // Corporation ©). Measured: reading main.innerText straight swept 20+ furniture
  // lines in behind 10 real skills. Strip them by SEMANTIC TAG — aside/footer/nav
  // survive LinkedIn's class hashing where a phrase blacklist would not.
  //
  // ⚠️ HIDE IN THE LIVE DOM, DO NOT CLONE. innerText is LAYOUT-DEPENDENT and a
  // detached cloneNode has no layout, so clone.innerText degrades to textContent
  // with NO line breaks — measured: the entire skills page collapsed to a single
  // 98-entry run-on string ("SkillsYou've added...Change ManagementProject Devel").
  // Hiding is reversible and restored in the finally below; the page is navigated
  // away from immediately after, and the screenshot is taken back on the profile.
  const hidden = [];
  main.querySelectorAll('aside, footer, nav, [role="complementary"], [role="navigation"], [role="contentinfo"]')
      .forEach(el => { hidden.push([el, el.style.display]); el.style.display = 'none'; });

  let all;
  try {
    all = (main.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
  } finally {
    for (const [el, prev] of hidden) el.style.display = prev;
  }

  // Belt-and-braces: if the rail/footer is NOT wrapped in a semantic tag on some
  // render, cut at the first furniture sentinel. Truncating is safe — every real
  // entry precedes the rail.
  const STOP = /^(who your viewers also viewed|people you may know|more profiles for you|linkedin corporation ©|you might like|suggested for you)/i;
  const cut = all.findIndex(l => STOP.test(l));
  const lines = cut >= 0 ? all.slice(0, cut) : all;
  return { lines, tabs: [...tabs], truncated_at: cut >= 0 ? cut : null,
           total_seen: all.length, furniture_hidden: hidden.length };
}
"""

# Sub-lines that belong to an entry rather than being one. Endorsement forms are
# stable, user-visible copy; the counts are matched numerically.
_ENDORSE = ("endorsed by",)
_CHROME_EXACT = {
    "skills", "experience", "all", "show all", "see more", "see less",
    "show credential", "add", "edit", "back",
}


def _clean_details_lines(lines, tabs, heading):
    """Entry titles from a details page's flattened text.

    Returns (entries, dropped) — `dropped` is kept so a future markup change shows
    up as a shift in what was discarded rather than as a silently shorter list.
    """
    import re

    tabset = {t.lower() for t in (tabs or [])}
    kept, dropped = [], []
    for raw in lines:
        low = raw.lower()
        if low == (heading or "").lower() or low in _CHROME_EXACT or low in tabset:
            dropped.append(raw)
            continue
        if any(low.startswith(p) for p in _ENDORSE) or re.match(r"^\d+\s+endorsements?$", low):
            dropped.append(raw)
            continue
        if low.startswith("you") and "maximum number of skills" in low:
            dropped.append(raw)
            continue
        kept.append(raw[:200])
    return kept, dropped


def _dedupe_context_lines(kept):
    """On the skills page each skill is followed by the POSITION it is attached to,
    and that position line repeats once per skill (measured: one position line
    appeared against 8+ skills). A line occurring more than once is therefore
    context, not a skill — skill names are unique within the list.

    Deliberately conservative: a line seen exactly once is KEPT even if it looks
    like a position, because dropping a real skill is worse than keeping one extra
    line, and the caller can see both counts.
    """
    from collections import Counter

    freq = Counter(kept)
    return [l for l in kept if freq[l] == 1], [l for l in dict.fromkeys(kept) if freq[l] > 1]


def _extract_details_section(page, base_url, section, heading):
    """Navigate to a details page and pull its entry lines. NEVER raises."""
    url = f"{base_url}/details/{section}/"
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3500)
        # Scroll until the list STOPS GROWING, not a fixed count. These pages paginate
        # lazily, and a fixed scroll silently truncates a long list into a plausible
        # short one — the failure mode this whole fix exists to remove. Bounded at 15
        # passes; two consecutive no-growth reads end it.
        prev, stable = -1, 0
        for _ in range(15):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(900)
            try:
                n = page.evaluate("() => ((document.querySelector('main')||document.body).innerText||'').split('\\n').length")
            except Exception:
                break
            if n <= prev:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
            prev = n
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(600)
        raw = page.evaluate(_JS_DETAILS) or {}
        lines = raw.get("lines") or []
        if not lines:
            return [], {"strategy": "none", "reason": "no_lines", "url": url}
        kept, dropped = _clean_details_lines(lines, raw.get("tabs"), heading)
        meta = {
            "strategy": "details_page",
            "url": url,
            "raw_lines": len(lines),
            "dropped": len(dropped),
            "furniture_cut_at": raw.get("truncated_at"),
            "total_seen": raw.get("total_seen"),
        }
        if section == "skills":
            uniq, repeated = _dedupe_context_lines(kept)
            meta["context_lines_dropped"] = len(repeated)
            return uniq[:50], meta
        return kept[:120], meta
    except Exception as exc:
        return [], {"strategy": "none", "reason": f"{type(exc).__name__}", "url": url}


def execute(page, params: dict) -> dict:
    profile_url = params.get("profile_url", "").strip()
    if not profile_url:
        raise ValueError("profile_url is required for linkedin_profile_view")

    # Strip tracking params — navigate to clean profile URL
    clean_url = profile_url.split("?")[0].rstrip("/")

    page.goto(clean_url, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    scrolled = _scroll_for_lazy_sections(page)

    fields = {
        "name": "",
        "headline": "",
        "location": "",
        "connections": "",
        "about": "",
        "skills": [],
        "experience": [],
    }
    strategy = {"about": "none", "skills": "none", "experience": "none"}
    diag = {}
    extract_error = ""
    try:
        raw = page.evaluate(_JS_EXTRACT) or {}
        strategy.update(raw.pop("_strategy", None) or {})
        diag = raw.pop("_diag", None) or {}
        fields.update({k: v for k, v in raw.items() if v})
    except Exception as exc:
        extract_error = f"{type(exc).__name__}: {exc}"

    # Details-page fallback (#6236) — ONLY when the inline section came back empty,
    # so if LinkedIn ever restores the on-profile sections this costs no extra
    # navigation. Each is independent: skills can fall back while experience does not.
    details_meta = {}
    for section, heading in (("skills", "Skills"), ("experience", "Experience")):
        if fields[section]:
            continue
        entries, meta = _extract_details_section(page, clean_url, section, heading)
        details_meta[section] = meta
        if entries:
            fields[section] = entries
            strategy[section] = meta["strategy"]

    # Return to the profile — the fallback navigated away and the top-card
    # screenshot below must not silently become a screenshot of /details/experience/.
    if details_meta:
        try:
            page.goto(clean_url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
        except Exception:
            pass

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
    # Deliberately NOT gated on skills/experience: a real profile may legitimately
    # have neither, and failing there would turn a sparse profile into a "broken read".
    # `strategy` is what separates "section absent" from "selector broke".
    got_content = bool(fields["name"] or fields["headline"] or fields["about"])
    result = {
        "success": got_content,
        "profile_url": clean_url,
        "final_url": page.url,
        **fields,
        "skills_count": len(fields["skills"]),
        "experience_count": len(fields["experience"]),
        "strategy": strategy,
        "sections_seen": diag,
        # What the fallback did per section (url / raw_lines / dropped counts). A
        # future markup change shows here as a shift in the drop counts instead of
        # just a shorter list — the same reason `strategy` exists.
        "details_fallback": details_meta,
        "scrolled": scrolled,
        "screenshot": screenshot,
        "screenshot_dir": "/mnt/data2/browser-profiles/ (host)",
    }
    if not got_content:
        result["result"] = "extraction_empty — page may be an auth wall, a 404, or a renderer change"
        if extract_error:
            result["extract_error"] = extract_error
    return result
