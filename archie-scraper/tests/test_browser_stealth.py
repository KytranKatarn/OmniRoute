"""Regression: browser_pool gives every context a realistic anti-bot fingerprint (#5152 slice 1).

Before this, pages loaded with Playwright's default HeadlessChrome UA +
navigator.webdriver=true, which bot walls (Amazon / Cloudflare) flag instantly —
S.C.O.U.T. scrapes of Amazon.ca and Canada Computers came back empty. Verified
live in the archie_scraper container that the config now produces a Chrome/125 UA
with webdriver hidden and real plugins/languages. This source-assertion keeps the
hardening from silently regressing (browser_pool is a threaded Playwright wrapper,
so a live launch is impractical in unit tests — the container proof + this guard).
"""

import os

_BP = os.path.join(os.path.dirname(__file__), "..", "browser_pool.py")


def test_browser_pool_has_realistic_fingerprint():
    with open(_BP, encoding="utf-8") as fh:
        src = fh.read()

    # A realistic desktop-Chrome UA (not HeadlessChrome), overridable via env.
    assert "_REALISTIC_UA" in src and "Chrome/125" in src, "missing realistic user-agent"
    assert 'os.getenv("SCOUT_USER_AGENT")' in src, "UA should be overridable via SCOUT_USER_AGENT"

    # Stealth init script hiding the remaining automation tells, applied to context.
    assert "navigator,'webdriver'" in src, "missing webdriver stealth in init script"
    assert "add_init_script(_STEALTH_INIT_JS)" in src, "stealth init script not applied to the context"

    # Context must carry the realistic UA + locale + timezone.
    assert '"user_agent": _REALISTIC_UA' in src, "context must set the realistic UA"
    assert '"locale": "en-US"' in src, "context must set a locale"
    assert '"timezone_id": "America/Toronto"' in src, "context must set a timezone"

    # Launch must drop the CDP automation flag.
    assert "--disable-blink-features=AutomationControlled" in src, "missing AutomationControlled launch flag"


def test_scrape_skills_use_bounded_render_settle():
    """SPAs render AFTER domcontentloaded, so skills must settle (bounded, non-fatal)
    before extracting — and price_monitor must drop the fragile networkidle goto that
    fails on ad-heavy retail pages (#5152 slice 1b)."""
    here = os.path.dirname(__file__)
    with open(os.path.join(here, "..", "browser_pool.py"), encoding="utf-8") as fh:
        bp_src = fh.read()
    assert "def wait_for_render(" in bp_src, "browser_pool must expose wait_for_render"
    assert 'os.getenv("SCOUT_SETTLE_MS"' in bp_src, "settle must be tunable via SCOUT_SETTLE_MS"

    skills_dir = os.path.join(here, "..", "skills")
    for skill in ("web_scrape.py", "price_monitor.py"):
        with open(os.path.join(skills_dir, skill), encoding="utf-8") as fh:
            s = fh.read()
        assert "from browser_pool import wait_for_render" in s, f"{skill} must import wait_for_render"
        assert "wait_for_render(page)" in s, f"{skill} must call wait_for_render after navigation"

    with open(os.path.join(skills_dir, "price_monitor.py"), encoding="utf-8") as fh:
        pm = fh.read()
    assert 'wait_until="networkidle"' not in pm, "price_monitor must not hard-wait on networkidle"
    assert 'wait_until="domcontentloaded"' in pm, "price_monitor must use domcontentloaded + settle"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
