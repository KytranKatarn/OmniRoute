"""Repair Bay — PR Review pane smoke check.

Every defect in this pane during the CODEX review work (2026-10-04) was invisible to the
string-assertion unit tests and obvious the moment a browser clicked the thing:

  - the CODEX pane read /issues/N/comments while CODEX posts to /pulls/N/reviews, so a
    real review was never displayed
  - the "==== CODEX REVIEW ====" marker is never posted, so matching it found nothing
  - tag-stripping silently mangled code spans inside findings
  - a 502 rendered as "(No CodeRabbit review)" — a failure displayed as absence
  - showPRDetail() threw on an unbound name and blanked the whole report pane
  - and the CodeRabbit endpoint itself 502'd on every PR, unnoticed for the same reason

A file can contain every string a grep-based test looks for and still throw at runtime,
so the only honest check drives the page. ``scripts/test_repair_bay_pr_pane.cjs`` is the
Node version for interactive use; this module is the same assertions in Python so the
agent loop can run them unattended from inside the platform container.

The judgement is split out as `judge_pane()` — a pure function over a DOM snapshot — so
the part that decides pass/fail is unit-testable without a browser. Everything expensive
lives in `check_pr_review_pane()`.

Contracts this module keeps:

  * NEVER returns "ok" when it did not run. A missing credential or a missing browser is
    reported as skipped/incomplete, so an unrunnable check can never read as a pass.
  * NEVER logs or returns the credential.
  * `localhost` by default, NOT 127.0.0.1 — the platform's own security layer serves
    "ACCESS DENIED / BLOCKED DOMAIN" for the loopback literal.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

#: Tried in order; the first that answers wins. The job runs in `archie_scheduler`,
#: where the platform is `archie_platform:3000` and `localhost:3000` is refused —
#: measured, and it produced a hard failure on the first live run. `localhost` is kept
#: for interactive runs (the Node script, a shell in the platform container), where
#: `archie_platform` does not resolve. Guessing one host is how this check reported a
#: false outage on its first execution.
CANDIDATE_BASE_URLS = ("http://archie_platform:3000", "http://localhost:3000")
DEFAULT_BASE_URL = CANDIDATE_BASE_URLS[0]
REPAIR_BAY_PATH = "/tools/repair-bay/"
LOGIN_PATH = "/login"
USERNAME = "claude"
PASSWORD_ENV = "ARCHIE_CLAUDE_PASSWORD"
#: Canonical credential store (written by the Tier-2-approved rotation). Preferred over
#: the environment because compose sources ARCHIE_CLAUDE_PASSWORD from the root `.env`,
#: which the rotation does NOT update — measured 2026-10-04, the two disagreed and the
#: env copy was stale, so a check reading env alone fails to log in and would have
#: reported a credential problem that did not exist. Mirrors .claude/skills/
#: archie-platform-login, which documents the same precedence.
CREDS_FILE_ENV = "ARCHIE_CRED_FILE"
DEFAULT_CREDS_FILES = (
    "/app/credentials/agent_passwords.env",
    "/mnt/archie_brain/credentials/agent_passwords.env",
)

#: Filters exercised. `open` is the tab default; `merged` is where history lives and
#: where the capped-list banner shows up.
DEFAULT_FILTERS = ("open", "merged")

#: Below this the pane rendered nothing useful. The placeholder is ~70 bytes and a real
#: report is multiple kilobytes, so the gap is wide enough that the exact number is not
#: load-bearing — it only has to separate "rendered" from "blank".
MIN_PANE_BYTES = 500

#: Endpoints each pane fetches. These are asserted DIRECTLY — status plus the absence of
#: an `error` key — rather than by scraping the pane's text for a phrase.
#:
#: Text-scraping was the first attempt and it is wrong: the pane renders the review body,
#: so a CODEX review whose FINDINGS happen to contain the words looks like a failure. That
#: is a check that cries wolf on real content. The endpoint contract is unambiguous, and
#: asserting it catches what the text match was meant to catch — the #3620 CodeRabbit
#: NameError, which 502'd every fetch — without ever reading prose.
PANE_ENDPOINTS = ("coderabbit", "codex")

#: Per-endpoint budget. See the AbortController note at the probe: page.evaluate() does
#: not inherit the page timeout, so this has to be enforced in-page.
ENDPOINT_TIMEOUT_MS = 8000


def judge_pane(snapshot: dict[str, Any]) -> list[str]:
    """Decide whether one clicked PR's detail pane is healthy.

    Pure: takes a DOM snapshot, returns failure reasons (empty list == healthy). Kept free
    of Playwright so the decision logic is unit-testable.

    `snapshot` keys:
        missing      -- the #prReviewDetail element was not in the DOM at all
        still_empty  -- the pane still carries the --empty placeholder class
        bytes        -- rendered innerHTML length
        text         -- the pane's visible text
        page_errors  -- JS errors seen since the click
    """
    reasons: list[str] = []
    if snapshot.get("missing"):
        return ["#prReviewDetail is missing from the DOM"]

    if snapshot.get("still_empty"):
        # The fingerprint of a showPRDetail() crash: the handler clears --empty and THEN
        # throws, so the pane is blank rather than showing its placeholder.
        reasons.append("pane still flagged empty after clicking a row")

    nbytes = int(snapshot.get("bytes") or 0)
    if nbytes < MIN_PANE_BYTES:
        reasons.append(f"pane rendered only {nbytes} bytes (below {MIN_PANE_BYTES})")

    for name, err in (snapshot.get("endpoint_errors") or {}).items():
        reasons.append(f"pane endpoint /{name} failed -> {str(err)[:110]}")

    for err in snapshot.get("page_errors") or []:
        reasons.append(f"JS error after click: {str(err)[:110]}")

    return reasons


def resolve_password() -> str | None:
    """Return the agent password, or None. Never logs or returns it in a message.

    Credentials file first, environment second — see DEFAULT_CREDS_FILES for why.
    """
    import re

    paths = []
    override = os.getenv(CREDS_FILE_ENV)
    if override:
        paths.append(override)
    paths.extend(DEFAULT_CREDS_FILES)
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                m = re.search(r"^ARCHIE_CLAUDE_PASSWORD=(.*)$", fh.read(), re.M)
        except OSError:
            continue
        if m:
            val = m.group(1).strip().strip("\"'")
            if val:
                return val
    val = os.getenv(PASSWORD_ENV)
    return val or None


#: Substrings that identify the platform's login page. Used to reject a 200 that is NOT
#: the login page.
_LOGIN_MARKERS = ('name="username"', 'id="username"', 'type="password"')


def _reachable_base(candidates):
    """First candidate that actually serves the login form, else None.

    Status alone is not enough. The platform's security layer answers **HTTP 200** with an
    "ACCESS DENIED / BLOCKED DOMAIN" page for hosts it does not like — that is a 200, so a
    status-only probe accepts it and stops, and the check then fails against a blocked host
    while a perfectly good candidate sits second in the list. This was measured on
    127.0.0.1 on 2026-10-04.

    So the body must look like the login page. Probed over plain HTTP rather than by
    driving the browser: a wrong host should cost one cheap request, not a launch.
    """
    import urllib.error
    import urllib.request

    for base in candidates:
        try:
            with urllib.request.urlopen(f"{base}{LOGIN_PATH}", timeout=8) as resp:
                # Read enough of the page. A 4 KB cap was wrong: the login form sits
                # past that in the real 10.8 KB page, so the marker never matched and the
                # probe rejected the ONE working host. Found by running it, not by reading
                # it — the unit test used a synthetic body short enough to fit.
                body = resp.read(65536).decode("utf-8", "replace")
                if resp.status < 500 and any(m in body for m in _LOGIN_MARKERS):
                    return base
        except urllib.error.HTTPError:
            continue
        except Exception:  # noqa: BLE001 - refused, DNS, timeout
            continue
    return None


def _classify(failures: list[str], checked: int, skipped_reason: str | None) -> dict[str, Any]:
    """Severity + shape shared by the live path and the tests."""
    if skipped_reason:
        return {
            "severity": "info",
            "failures": [],
            "summary_metrics": {"checked": checked, "failed": 0, "skipped": 1},
            "skipped_reason": skipped_reason,
            "reasons": [skipped_reason],
        }
    if failures:
        return {
            "severity": "error",
            "failures": failures,
            "summary_metrics": {"checked": checked, "failed": len(failures), "skipped": 0},
            "reasons": failures,
        }
    return {
        "severity": "info",
        "failures": [],
        "summary_metrics": {"checked": checked, "failed": 0, "skipped": 0},
        "reasons": [],
    }


def check_pr_review_pane(
    base_url: str | None = None,
    filters: tuple[str, ...] = DEFAULT_FILTERS,
    nav_timeout_ms: int = 20000,
    settle_ms: int = 2500,
) -> dict[str, Any]:
    """Drive Repair Bay -> PR Review and click a row in each filter.

    Returns the dict shape used by the other agent-loop checks (severity /
    summary_metrics / reasons) so callers need no special case.
    """
    override = base_url or os.getenv("ARCHIE_BASE_URL")
    candidates = [override.rstrip("/")] if override else list(CANDIDATE_BASE_URLS)
    password = resolve_password()
    if not password:
        # Explicitly not a pass. A check that cannot run must never be reported green.
        return _classify([], 0, f"skipped: no agent credential (no {CREDS_FILE_ENV} file and no {PASSWORD_ENV})")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001 - absence must be reported, not raised
        return _classify([], 0, f"skipped: playwright unavailable ({exc.__class__.__name__})")

    failures: list[str] = []
    checked = 0
    console: list[str] = []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox"])
            try:
                base = _reachable_base(candidates)
                if base is None:
                    return _classify([], 0, f"skipped: no reachable platform at {', '.join(candidates)}")
                page = browser.new_page()
                page.on("pageerror", lambda e: console.append(str(e)))
                page.set_default_timeout(nav_timeout_ms)

                page.goto(f"{base}{LOGIN_PATH}", wait_until="domcontentloaded")
                page.fill("input[name='username'], #username", USERNAME)
                page.fill("input[type='password'], #password", password)
                page.click("button[type='submit'], button:has-text('ACCESS SYSTEM')")
                page.wait_for_load_state("networkidle")
                if LOGIN_PATH in page.url:
                    return _classify([], 0, f"skipped: {USERNAME} login rejected (agent credential stale?)")

                # A cache-busting query so the browser cannot answer from a copy cached
                # before a deploy — a stale page makes a good fix look broken and a real
                # break look fixed.
                page.goto(f"{base}{REPAIR_BAY_PATH}?pane_smoke=1", wait_until="networkidle")
                if not page.evaluate("() => !!document.getElementById('tab-pr-review')"):
                    # Authenticated and the platform answered, so an absent tab is a
                    # REGRESSION, not an environment problem. Reporting it as a skip made a
                    # deployment that removed the pane look healthy — the exact failure
                    # this check exists to catch.
                    failures.append(
                        "[all] PR Review tab markup absent while authenticated " "(Repair Bay module failed to load?)"
                    )
                    return _classify(failures, 0, None)
                page.evaluate("() => window.switchTab && window.switchTab('pr-review')")
                page.wait_for_timeout(settle_ms)

                for filt in filters:
                    console.clear()
                    rows = page.evaluate(
                        """(f) => {
                            document.getElementById('prFilter-' + f).click();
                            return new Promise(r => setTimeout(() => r(
                                document.querySelectorAll(
                                    '#prReviewList > div[data-pr-row]').length), 2500));
                        }""",
                        filt,
                    )
                    if not rows:
                        # Nothing tracked in this filter is legitimate — but only if the
                        # list actually loaded. If JS threw while fetching it, an empty
                        # list and a real error look identical, and a healthy second filter
                        # would make the whole run pass.
                        if console:
                            failures.append(
                                f"[{filt}] list rendered empty while JS reported: "
                                + "; ".join(str(e)[:90] for e in console[:2])
                            )
                        continue
                    checked += 1

                    # Raw string: the JS regex below contains \d, which is an invalid
                    # escape in a normal Python string literal (SyntaxWarning).
                    pr_number = page.evaluate(
                        r"""() => {
                            const r = document.querySelector('#prReviewList > div[data-pr-row]');
                            if (!r) return null;
                            const m = (r.innerText || '').match(/#(\d+)/);
                            r.click();
                            return m ? m[1] : null;
                        }"""
                    )
                    page.wait_for_timeout(settle_ms)
                    # Direct endpoint contract: HTTP ok and no `error` key. This is what catches a
                    # backend failure that the pane renders as "no review" — the reason the
                    # CodeRabbit NameError shipped unnoticed. Probed after the click so the pane has
                    # rendered; both run in-page and carry the session cookie.
                    endpoint_errors = {}
                    if pr_number:
                        endpoint_errors = page.evaluate(
                            """async (args) => {
                                const [num, kinds, budgetMs] = args;
                                const bad = {};
                                for (const kind of kinds) {
                                  // AbortController is REQUIRED here. page.evaluate() has no timeout of its
                                  // own — it does NOT inherit page.set_default_timeout — so a server that
                                  // accepts the connection and never finishes the response hangs the
                                  // evaluate, hangs the job, and because max_instances=1 the check never runs
                                  // again. A monitoring job that can hang forever is not a monitoring job.
                                  const ctl = new AbortController();
                                  const timer = setTimeout(() => ctl.abort(), budgetMs);
                                  try {
                                    const r = await fetch(
                                      `/tools/repair-bay/api/forge/pr-reviews/${num}/${kind}`,
                                      {credentials: 'include', signal: ctl.signal});
                                    if (!r.ok) { bad[kind] = `HTTP ${r.status}`; continue; }
                                    const j = await r.json();
                                    if (j && j.error) bad[kind] = String(j.error).slice(0, 100);
                                  } catch (e) {
                                    bad[kind] = (e && e.name === 'AbortError')
                                      ? `no response in ${budgetMs}ms`
                                      : String(e).slice(0, 100);
                                  } finally {
                                    clearTimeout(timer);
                                  }
                                }
                                return bad;
                            }""",
                            [pr_number, list(PANE_ENDPOINTS), ENDPOINT_TIMEOUT_MS],
                        )
                    snapshot = page.evaluate(
                        """() => {
                            const el = document.getElementById('prReviewDetail');
                            if (!el) return {missing: true};
                            return {
                                still_empty: el.className.includes('--empty'),
                                bytes: el.innerHTML.length,
                                text: (el.innerText || '').replace(/\\s+/g, ' '),
                            };
                        }"""
                    )
                    snapshot["page_errors"] = list(console)
                    snapshot["endpoint_errors"] = endpoint_errors or {}
                    for reason in judge_pane(snapshot):
                        failures.append(f"[{filt}] {reason}")
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - a harness failure IS a check failure
        failures.append(f"harness error: {exc.__class__.__name__}: {str(exc)[:160]}")

    if checked == 0 and not failures:
        return _classify([], 0, "skipped: no tracked PRs in any filter to click")
    return _classify(failures, checked, None)


def format_alert_message(result: dict[str, Any]) -> str:
    """One-line-ish body for a system notification."""
    metrics = result.get("summary_metrics") or {}
    head = (
        f"Repair Bay PR Review pane: {metrics.get('failed', 0)} failure(s) "
        f"across {metrics.get('checked', 0)} filter(s) checked."
    )
    reasons = result.get("reasons") or []
    if not reasons:
        return head
    return head + "\n\n" + "\n".join(f"  - {r}" for r in reasons[:10])
