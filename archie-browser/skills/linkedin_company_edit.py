"""LinkedIn company page edit — updates tagline, description, website, industry."""
import os
import sys
from datetime import datetime

_SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
# Guard the insert (#5650): skill_runner._discover_skills() re-imports EVERY skill on
# EVERY execute(), so an unguarded insert added a duplicate path per skill per run —
# measured sys.path 6 -> 33 after only 3 discoveries in a long-lived container.
if _SKILLS_DIR not in sys.path:
    sys.path.insert(0, _SKILLS_DIR)
from _linkedin_common import get_company_slug

SKILL_NAME = "linkedin_company_edit"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    # Write to the MOUNTED /profiles volume (host: /mnt/data2/browser-profiles) with
    # a FIXED name so the shot is retrievable from the host; /tmp was never mounted
    # (all prior company_edit screenshots were lost). Viewport-only + short timeout.
    path = f"/profiles/_ce_{name}.png"
    try:
        page.screenshot(path=path, full_page=False, timeout=15000, animations="disabled")
        return path
    except Exception:
        return None


def _dump_modal(page):
    """Read-only structure dump of the open edit modal — section nav-items + field
    labels — so we can locate the real Overview/Description section + field."""
    try:
        return page.evaluate(r"""
        () => {
          function* walk(root){ for (const el of root.querySelectorAll('*')) { yield el; if (el.shadowRoot) yield* walk(el.shadowRoot); } }
          const navs = new Set(), fields = [];
          for (const el of walk(document)) {
            const t = el.tagName;
            if ((t==='BUTTON' || t==='A' || el.getAttribute && el.getAttribute('role')==='tab')) {
              const tx = (el.innerText||'').trim();
              if (tx && tx.length<28) navs.add(tx);
            }
            if (t==='INPUT' || t==='TEXTAREA' || (el.getAttribute && el.getAttribute('contenteditable')==='true')) {
              if (['hidden','checkbox','radio','submit'].includes(el.type)) continue;
              fields.push({tag:t, type:(el.type||''), aria:(el.getAttribute('aria-label')||'').slice(0,40), ph:(el.placeholder||'').slice(0,40), val:(el.value||el.innerText||'').slice(0,40)});
            }
          }
          return { navs: Array.from(navs).slice(0,40), fields: fields.slice(0,25) };
        }
        """)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}"}


def execute(page, params: dict) -> dict:
    company_slug = get_company_slug(params)
    tagline = params.get("tagline", "").strip()
    description = params.get("description", "").strip()
    website = params.get("website", "").strip()
    industry = params.get("industry", "").strip()

    if not any([tagline, description, website, industry]):
        raise ValueError("At least one field required: tagline, description, website, industry")

    # Navigate to company page — LinkedIn auto-redirects admins to admin view
    company_url = f"https://www.linkedin.com/company/{company_slug}/"
    page.goto(company_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "company_before")

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    # Click "Edit Page" — appears in left sidebar on admin view
    opened = False
    for btn in [
        lambda: page.get_by_role("link", name="Edit Page", exact=True).click(timeout=8000),
        lambda: page.locator('a:has-text("Edit Page")').first.click(timeout=8000),
        lambda: page.get_by_role("link", name="Edit page", exact=False).first.click(timeout=8000),
        lambda: page.locator('nav a:has-text("Edit")').first.click(timeout=6000),
        # Fallback: top-right edit button on public view
        lambda: page.get_by_role("button", name="Edit page", exact=False).first.click(timeout=6000),
        lambda: page.locator('[data-control-name="page_edit"]').first.click(timeout=6000),
    ]:
        try:
            btn()
            opened = True
            break
        except Exception:
            continue

    if not opened:
        _screenshot(page, "company_edit_btn_fail")
        raise RuntimeError("Could not find Edit page button — check admin access")

    page.wait_for_timeout(2000)
    _screenshot(page, "company_edit_open")
    modal_dump = _dump_modal(page)

    updated_fields = []
    errors = []

    # The editor is a SINGLE scrollable form (no per-field tab). Fields have NO
    # aria-label/id — only PLACEHOLDERS (probe-confirmed 2026-07-01). Target by
    # placeholder; NEVER textarea.last (that trailing textarea is not the About field).
    def _fill_ph(placeholders, value, key):
        # Try multiple LOCATORS (get_by_placeholder + CSS placeholder selector) and
        # an explicit CLICK+TYPE interaction. The About/website fields are below the
        # fold in the modal's internal scroll container AND are React-controlled —
        # a native scrollIntoView reaches them, and click+type registers where a
        # programmatic .fill() silently no-ops (verified: fill() failed x3 on CREED).
        cands = []
        for ph in placeholders:
            cands.append(lambda ph=ph: page.get_by_placeholder(ph, exact=False).first)
            key20 = ph[:20].replace('"', '')
            cands.append(lambda k=key20: page.locator(f'textarea[placeholder*="{k}"], input[placeholder*="{k}"]').first)
        for mk in cands:
            try:
                loc = mk()
                loc.evaluate("el => el.scrollIntoView({block:'center'})")
                page.wait_for_timeout(300)
                loc.click(timeout=3000)
                loc.press("Control+a")
                loc.press("Delete")
                loc.type(value, delay=3)
                updated_fields.append(key)
                return True
            except Exception:
                continue
        errors.append(key + "_not_filled")
        return False

    if tagline:
        _fill_ph(["Add your slogan or mission statement", "slogan", "mission statement"], tagline, "tagline")
    if description:
        _fill_ph(["Add an About Us with a brief overview", "brief overview", "About Us"], description, "description")
    if website:
        _fill_ph(["Add your website homepage", "www.example"], website, "website")

    # Industry — placeholder-targeted typeahead; pick the matching option.
    if industry:
        try:
            ind = page.get_by_placeholder("Select an industry", exact=False).first
            ind.fill(industry, timeout=5000)
            page.wait_for_timeout(900)
            try:
                page.get_by_role("option", name=industry, exact=False).first.click(timeout=3000)
            except Exception:
                page.locator('[role="option"]').first.click(timeout=3000)
            updated_fields.append("industry")
        except Exception:
            errors.append("industry_field_not_found")

    page.wait_for_timeout(500)
    _screenshot(page, "company_filled")

    # Save
    for save_btn in [
        lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=8000),
        lambda: page.get_by_role("button", name="Save changes", exact=False).last.click(timeout=6000),
        lambda: page.locator('button[type="submit"]').last.click(timeout=5000),
    ]:
        try:
            save_btn()
            break
        except Exception:
            continue

    page.wait_for_timeout(2500)

    # Dismiss follow-up
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    final = _screenshot(page, "company_after")

    # ── HONEST verify — re-open the editor + confirm the values persisted ─────
    verified = {}
    if updated_fields:
        try:
            page.goto(company_url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            try:
                page.keyboard.press("Escape")  # dismiss the Premium upsell overlay
                page.wait_for_timeout(500)
            except Exception:
                pass
            reopened = False
            for btn in [
                lambda: page.get_by_role("link", name="Edit Page", exact=True).click(timeout=8000),
                lambda: page.locator('a:has-text("Edit Page")').first.click(timeout=6000),
            ]:
                try:
                    btn()
                    reopened = True
                    break
                except Exception:
                    continue
            if reopened:
                page.wait_for_timeout(2500)
                dump2 = _dump_modal(page)
                vals = " ".join([(f.get("val") or "") for f in (dump2.get("fields") or [])]).lower()
                if tagline:
                    verified["tagline"] = tagline[:25].lower() in vals
                if description:
                    verified["description"] = description[:30].lower() in vals
                if website:
                    verified["website"] = website[:15].lower() in vals
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
        except Exception:
            pass

    checkable = [k for k in ("tagline", "description", "website") if params.get(k)]
    all_ok = all(verified.get(k) for k in checkable) if checkable else len(updated_fields) > 0
    return {
        "success": bool(all_ok),
        "result": (f"Verified: {', '.join(k for k in verified if verified[k])}" if all_ok
                   else f"NOT fully verified — filled {updated_fields}, verified {verified}"),
        "updated_fields": updated_fields,
        "verified": verified,
        "errors": errors,
        "screenshot_path": final,
        "modal_dump": modal_dump,
    }
