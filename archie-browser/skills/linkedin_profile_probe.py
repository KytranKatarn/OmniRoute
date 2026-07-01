"""LinkedIn profile probe — READ-ONLY diagnostic.

Key facts discovered live 2026-06-30 (Terry/377):
  - "Edit profile" NAVIGATES to the route /in/<vanity>/edit/intro/ (NOT a modal).
  - "Add background image" opens an iframe-based uploader (main frame has no input).

Params:
  open: ""              -> profile PAGE dump (all_aria, candidates, top_card_text)
        "intro_route"   -> goto /in/me/edit/intro/ directly, dump ALL forms
        "banner"        -> click "Add background image", dump iframe srcs
        "about_route"   -> goto /in/me/edit/about/ (or detail/about), dump forms
"""

SKILL_NAME = "linkedin_profile_probe"
PLATFORMS = ["linkedin"]

_JS_PAGE = r"""
() => {
  const out = { url: location.href, title: document.title };
  out.has_about = !!document.getElementById('about');
  const els = Array.from(document.querySelectorAll('button, a, [role="button"]'));
  const cand = [], all_aria = [], seen = new Set();
  for (const b of els) {
    const lbl = (b.getAttribute('aria-label') || '').trim();
    const txt = (b.innerText || '').trim().slice(0, 50);
    if (lbl && !seen.has(lbl)) { seen.add(lbl); all_aria.push({ tag: b.tagName, aria: lbl.slice(0, 70) }); }
    const blob = (lbl + ' ' + txt).toLowerCase();
    if (blob.includes('edit') || blob.includes('add section') || blob.includes('background') || blob.includes('cover')) {
      cand.push({ tag: b.tagName, aria: lbl.slice(0, 70), text: txt });
    }
  }
  out.candidates = cand.slice(0, 40);
  out.all_aria = all_aria.slice(0, 90);
  const main = document.querySelector('main') || document.body;
  out.top_card_text = (main.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 500);
  return out;
}
"""

_JS_FORMS = r"""
() => {
  function accName(el){
    let n = el.getAttribute('aria-label'); if (n) return n.trim();
    const lb = el.getAttribute('aria-labelledby');
    if (lb){ const t = lb.split(/\s+/).map(id => { const e = document.getElementById(id); return e ? (e.innerText || e.textContent || '') : ''; }).join(' ').trim(); if (t) return t; }
    if (el.id){ try { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) return (l.innerText || '').trim(); } catch(e){} }
    let p = el.parentElement, tries = 0;
    while (p && tries < 5){ const lab = p.querySelector('label'); if (lab && (lab.innerText || '').trim()) return (lab.innerText || '').trim(); p = p.parentElement; tries++; }
    return '';
  }
  const forms = Array.from(document.querySelectorAll('form'));
  const out = forms.map(f => ({
    text: (f.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 120),
    fields: Array.from(f.querySelectorAll('input, textarea, [contenteditable="true"]'))
      .filter(x => !['checkbox', 'radio', 'hidden'].includes(x.type))
      .map(x => ({ tag: x.tagName, type: (x.type || ''), acc: accName(x).slice(0, 40), id: (x.id || '').slice(0, 18) }))
      .slice(0, 18),
  }));
  return { url: location.href, form_count: forms.length, textareas: document.querySelectorAll('textarea').length, forms: out.slice(0, 6) };
}
"""

_JS_BANNER = r"""
() => {
  const frames = Array.from(document.querySelectorAll('iframe')).map(f => ({
    name: (f.name || '').slice(0, 40), id: (f.id || '').slice(0, 40),
    src: (f.src || '').slice(0, 90), title: (f.title || '').slice(0, 40),
  }));
  return {
    url: location.href, iframe_count: frames.length, frames: frames.slice(0, 8),
    file_inputs: document.querySelectorAll('input[type="file"]').length,
    dialog_count: document.querySelectorAll('[role="dialog"], .artdeco-modal').length,
  };
}
"""


def _click_first(page, attempts):
    for fn in attempts:
        try:
            fn()
            return True
        except Exception:
            continue
    return False


def _shot(page, name):
    """Full-page screenshot to the MOUNTED /profiles volume (readable from host
    at /mnt/data2/browser-profiles/). Long timeout — the profile page animates."""
    path = f"/profiles/_probe_{name}.png"
    try:
        page.screenshot(path=path, full_page=False, timeout=15000, animations="disabled")
        return path
    except Exception as exc:
        return f"shot_failed: {type(exc).__name__}"


def execute(page, params: dict) -> dict:
    open_target = (params.get("open") or "").strip().lower()

    if open_target == "route":
        url = (params.get("url") or "").strip()
        if not url:
            return {"success": False, "result": "url param required"}
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        shot = _shot(page, "route")
        pierce = r"""
        () => {
          function* walk(root){ for (const el of root.querySelectorAll('*')) { yield el; if (el.shadowRoot) yield* walk(el.shadowRoot); } }
          let ce = 0, saves = 0; const inputs = [];
          for (const el of walk(document)) {
            if (el.getAttribute && el.getAttribute('contenteditable') === 'true') ce++;
            const t = el.tagName;
            if (t === 'INPUT' || t === 'TEXTAREA') { if (['hidden','checkbox','radio'].includes(el.type)) continue; inputs.push({ tag: t, type: el.type || '', aria: (el.getAttribute('aria-label') || '').slice(0,32), ph: (el.placeholder || '').slice(0,25) }); }
            if (t === 'BUTTON' && (el.innerText || '').trim() === 'Save') saves++;
          }
          const body = (document.body.innerText || '');
          return { contenteditables: ce, save_buttons: saves, inputs: inputs.slice(0,16), is_404: /doesn.t exist|page not found/i.test(body), title: document.title.slice(0,50) };
        }
        """
        try:
            dump = page.evaluate(pierce)
        except Exception as exc:
            dump = {"result": f"pierce failed: {type(exc).__name__}"}
        try:
            dump["pw_save"] = page.get_by_role("button", name="Save", exact=True).count()
            dump["pw_title"] = page.get_by_label("Title", exact=False).count()
        except Exception:
            pass
        dump.update({"mode": "route", "success": True, "shot": shot, "final_url": page.url})
        return dump

    if open_target == "exp_diag":
        page.goto("https://www.linkedin.com/in/me/add-edit/POSITION/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        try:
            page.get_by_label("Job title", exact=False).first.fill("Founder", timeout=6000)
        except Exception:
            pass
        try:
            page.get_by_label("Organization", exact=False).first.fill("Kytran Empowerment Inc.", timeout=6000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        try:
            page.locator('[role="option"]').filter(has_text="Kytran").first.click(timeout=2500)
        except Exception:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
        try:
            page.get_by_label("currently work", exact=False).first.check(timeout=3000)
        except Exception:
            pass
        try:
            page.get_by_label("Start month", exact=False).first.select_option(label="January", timeout=4000)
        except Exception:
            pass
        try:
            page.get_by_label("Start year", exact=False).first.select_option(label="2026", timeout=4000)
        except Exception:
            pass
        page.wait_for_timeout(1000)
        shot = _shot(page, "exp_diag")
        diag = page.evaluate(r"""() => {
          function* walk(root){ for (const el of root.querySelectorAll('*')) { yield el; if (el.shadowRoot) yield* walk(el.shadowRoot); } }
          const buttons=[]; let errText='';
          for (const el of walk(document)) {
            if (el.tagName==='BUTTON') { const t=(el.innerText||'').trim(); if (t) buttons.push({t:t.slice(0,16), disabled: !!(el.disabled || el.getAttribute('aria-disabled')==='true')}); }
            const cls=((el.className||'')+'').toString();
            if (/error|invalid|field__error|fb-/i.test(cls)) { const tx=(el.innerText||'').trim(); if (tx && tx.length<70) errText += tx+' | '; }
          }
          const vals={};
          for (const el of walk(document)) { if (el.tagName==='INPUT' && el.value) vals[((el.getAttribute('aria-label')||el.placeholder||'')+'').slice(0,18)] = (el.value+'').slice(0,28); }
          return { buttons: buttons.slice(0,14), errText: errText.slice(0,250), vals };
        }""")
        diag.update({"mode": "exp_diag", "success": True, "shot": shot})
        return diag

    if open_target == "intro_route":
        page.goto("https://www.linkedin.com/in/me/edit/intro/", wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        shot = _shot(page, "intro")
        # Shadow-DOM-piercing field walk — querySelectorAll does NOT cross shadow
        # roots; this recurses into them to find the real editable fields.
        pierce_js = r"""
        () => {
          function* walk(root){
            for (const el of root.querySelectorAll('*')) {
              yield el;
              if (el.shadowRoot) yield* walk(el.shadowRoot);
            }
          }
          const out = [];
          for (const el of walk(document)) {
            const t = el.tagName;
            const ce = el.getAttribute && el.getAttribute('contenteditable') === 'true';
            if (t === 'INPUT' || t === 'TEXTAREA' || ce) {
              if (['checkbox','radio','hidden'].includes(el.type)) continue;
              const val = (el.value || el.innerText || el.textContent || '').trim().slice(0, 45);
              out.push({ tag: t, ce: !!ce, type: el.type || '', role: el.getAttribute('role') || '',
                         aria: (el.getAttribute('aria-label') || '').slice(0, 40),
                         alby: (el.getAttribute('aria-labelledby') || '').slice(0, 25),
                         id: (el.id || '').slice(0, 25), val: val });
            }
          }
          return { count: out.length, fields: out.slice(0, 25) };
        }
        """
        try:
            dump = page.evaluate(pierce_js)
        except Exception as exc:
            dump = {"result": f"pierce failed: {type(exc).__name__}: {exc}"}
        # Also probe Playwright high-level locator counts (these DO pierce shadow DOM).
        try:
            dump["pw_label_headline"] = page.get_by_label("Headline", exact=False).count()
            dump["pw_role_textbox"] = page.get_by_role("textbox").count()
        except Exception:
            pass
        dump.update({"mode": open_target, "success": True, "shot": shot})
        return dump

    if open_target == "about_route":
        page.goto("https://www.linkedin.com/in/me/edit/about/", wait_until="domcontentloaded")
        page.wait_for_timeout(3500)
        try:
            dump = page.evaluate(_JS_FORMS)
        except Exception as exc:
            dump = {"result": f"dump failed: {type(exc).__name__}: {exc}"}
        dump.update({"mode": open_target, "success": True})
        return dump

    if open_target == "about_view":
        # READ + SHOW the LIVE About section on the profile page (profile_view's
        # extractor is broken; nothing else scroll-captures the About). Scroll the
        # #about section into view, extract its text via a shadow-safe walk, shoot.
        page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        about_text = ""
        try:
            about_text = page.evaluate(r"""
            () => {
              function* walk(root){ for (const el of root.querySelectorAll('*')) { yield el; if (el.shadowRoot) yield* walk(el.shadowRoot); } }
              const anchor = document.getElementById('about');
              let sec = anchor ? (anchor.closest('section') || anchor.parentElement) : null;
              if (!sec) {
                for (const el of walk(document)) {
                  if ((el.tagName==='H2'||el.tagName==='SPAN'||el.tagName==='DIV') && (el.innerText||'').trim()==='About') { sec = el.closest('section') || el.parentElement; break; }
                }
              }
              if (!sec) return '';
              sec.scrollIntoView({block:'center'});
              let t = (sec.innerText||'').replace(/\s+/g,' ').trim();
              t = t.replace(/^About\s*/i,'').replace(/\s*…see more\s*$/i,'').replace(/\s*see more\s*$/i,'');
              return t.slice(0,700);
            }
            """) or ""
        except Exception as exc:
            about_text = f"extract_failed: {type(exc).__name__}"
        page.wait_for_timeout(1500)
        shot = _shot(page, "about_view")
        return {"mode": "about_view", "success": True, "about_text": about_text, "shot": shot}

    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(3500)

    if not open_target:
        try:
            dump = page.evaluate(_JS_PAGE)
        except Exception as exc:
            return {"success": False, "result": f"probe failed: {type(exc).__name__}: {exc}"}
        dump.update({"mode": "page", "success": True})
        return dump

    if open_target == "banner":
        opened = _click_first(page, [
            lambda: page.locator('button[aria-label="Add background image"]').first.click(timeout=8000),
            lambda: page.locator('[aria-label*="background image"]').first.click(timeout=8000),
        ])
        page.wait_for_timeout(4000)
        shot = _shot(page, "banner")
        try:
            dump = page.evaluate(_JS_BANNER)
        except Exception as exc:
            dump = {"result": f"dump failed: {type(exc).__name__}: {exc}"}
        dump.update({"mode": "banner", "opened_click": opened, "success": True, "shot": shot})
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return dump

    return {"success": False, "result": f"unknown open target: {open_target}"}
