"""LinkedIn account registration — SEMI-automated signup for a NEW agent account.

Part of the S.I.G.N.A.L. scale phase: each supporting agent gets its OWN LinkedIn
account on its own business email, REGISTERED + accessed from a fixed regional egress
so it reads as a distinct real person in a region (global footprint, not all-from-one-IP).

⚠️ HONEST SCOPE — read before wiring a live run:
  • LinkedIn aggressively fights automated signup. This skill automates the parts that
    CAN be automated (the form fill, and entering an email code we already hold) and
    DETECTS — but never fakes — the parts that cannot:
      - phone / SMS verification  → needs='phone'   (human, or a regional number entered by hand)
      - CAPTCHA / "security check" → needs='human'   (solve via the noVNC headed session)
  • It NEVER claims success it didn't verify (returns stage='registered' only when the
    authenticated home/feed actually renders).
  • EMAIL verification is automatable OUTSIDE this skill: the platform owns the agent's
    mailbox (Stalwart), so an orchestrator reads LinkedIn's code and re-invokes this skill
    with params['verification_code'].

Integration still required before a live run (do at pilot time, with the owner):
  1. skill_runner must launch a PERSISTENT context on the NEW profile dir
     /profiles/<agent_id>-linkedin WITH --proxy-server=socks5://<egress node>:1080 so the
     account is born from its assigned region (registry egress_pref). See node_socks fabric.
  2. orchestrator (ARCHIE) reads the email code from Stalwart + drives the noVNC handoff
     for phone/CAPTCHA, then flips agent_platform_accounts.profile_established/can_post.

This module builds the capability; it is NOT wired to run autonomously.
"""
import os
import re
from datetime import datetime

SKILL_NAME = "linkedin_register"
PLATFORMS = ["linkedin"]
MUTATING = True  # creates an account — never run on an unauthed storage_state fallback

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

_SIGNUP_URL = "https://www.linkedin.com/signup"


def _shot(page, name):
    path = f"{_SCREENSHOTS_DIR}/register_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, timeout=5000)
        return path
    except Exception:
        return None


def _first_visible(page, selectors, timeout=4000):
    """Return the first selector that resolves to a visible element, else None."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout)
            return loc
        except Exception:
            continue
    return None


def _result(stage, needs, message, page=None, shot=None, success=False):
    return {
        "success": success,
        "stage": stage,        # form | name | email_verification | phone_verification | captcha | registered | failed
        "needs": needs,        # none | email_code | phone | human
        "message": message,
        "screenshot_path": shot or (_shot(page, stage) if page else None),
    }


def _detect_stage(page):
    """Classify the page LinkedIn is currently showing during signup."""
    url = (page.url or "").lower()
    try:
        body = (page.inner_text("body") or "").lower()
    except Exception:
        body = ""
    if any(x in url for x in ("/feed", "/checkpoint/lg/login-submit")) or "start a post" in body:
        return "registered"
    if "/checkpoint/challenge" in url or "security check" in body or "let's do a quick" in body or "puzzle" in body:
        return "captcha"
    if "phone" in body and ("verify" in body or "add your phone" in body or "enter the code" in body and "phone" in body):
        return "phone_verification"
    if ("enter the code" in body or "verify your email" in body or "we sent" in body) and "email" in body:
        return "email_verification"
    if "/checkpoint/" in url:
        return "captcha"
    return "form"


def execute(page, params: dict) -> dict:
    email = (params.get("email") or "").strip()
    password = (params.get("password") or "").strip()
    first = (params.get("first_name") or "").strip()
    last = (params.get("last_name") or "").strip()
    code = (params.get("verification_code") or "").strip()

    if not email or not password:
        raise ValueError("email and password are required for linkedin_register")

    page.goto(_SIGNUP_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    # If we already hold an email code (orchestrator read it from Stalwart), the page may be
    # the verification step from a prior call on this same profile — handle it first.
    stage = _detect_stage(page)
    if stage == "email_verification" and code:
        box = _first_visible(page, [
            "input[name='pin']", "input#input__email_verification_pin",
            "input[autocomplete='one-time-code']", "input[type='tel']",
        ])
        if box:
            box.fill(code, timeout=8000)
            for btn in ["button:has-text('Verify')", "button:has-text('Submit')", "button[type='submit']"]:
                try:
                    page.locator(btn).first.click(timeout=4000)
                    break
                except Exception:
                    continue
            page.wait_for_timeout(3500)

    # Fresh form: email + password (+ name on some variants).
    email_box = _first_visible(page, ["input#email-address", "input#email", "input[name='email-address']",
                                      "input[autocomplete='username']"], timeout=6000)
    if email_box:
        try:
            email_box.fill(email, timeout=6000)
            pw = _first_visible(page, ["input#password", "input[name='password']",
                                       "input[autocomplete='new-password']"])
            if pw:
                pw.fill(password, timeout=6000)
            # some variants ask first/last on the same screen
            for sel, val in [("input#first-name", first), ("input#last-name", last)]:
                if val:
                    el = _first_visible(page, [sel], timeout=1500)
                    if el:
                        el.fill(val, timeout=3000)
            for btn in ["button#join-form-submit", "button[type='submit']",
                        "button:has-text('Agree & Join')", "button:has-text('Continue')",
                        "button:has-text('Join')"]:
                try:
                    page.locator(btn).first.click(timeout=4000)
                    break
                except Exception:
                    continue
            page.wait_for_timeout(4000)
        except Exception as exc:
            return _result("failed", "human", f"form fill failed: {str(exc)[:160]}", page=page)

    # Secondary name screen (variant flow).
    if first and last:
        fn = _first_visible(page, ["input#first-name", "input[name='first-name']"], timeout=2500)
        if fn:
            try:
                fn.fill(first, timeout=3000)
                ln = _first_visible(page, ["input#last-name", "input[name='last-name']"])
                if ln:
                    ln.fill(last, timeout=3000)
                for btn in ["button[type='submit']", "button:has-text('Continue')", "button:has-text('Agree')"]:
                    try:
                        page.locator(btn).first.click(timeout=4000)
                        break
                    except Exception:
                        continue
                page.wait_for_timeout(3500)
            except Exception:
                pass

    # Where did we land?
    stage = _detect_stage(page)
    shot = _shot(page, stage)
    if stage == "registered":
        return _result("registered", "none", "Account created and authenticated.", shot=shot, success=True)
    if stage == "email_verification":
        return _result("email_verification", "email_code",
                       "Awaiting the email code — orchestrator reads it from Stalwart and re-invokes "
                       "with params['verification_code'].", shot=shot)
    if stage == "phone_verification":
        return _result("phone_verification", "phone",
                       "LinkedIn requires phone/SMS verification — needs a regional number entered "
                       "via the noVNC headed session.", shot=shot)
    if stage == "captcha":
        return _result("captcha", "human",
                       "LinkedIn is showing a CAPTCHA / security challenge — solve it in the noVNC "
                       "headed session, then re-probe.", shot=shot)
    return _result("form", "human",
                   "Could not advance the signup flow automatically (DOM variant / step-up). "
                   "Continue in the noVNC headed session.", shot=shot)
