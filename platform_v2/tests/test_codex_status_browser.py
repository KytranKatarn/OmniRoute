"""Render the actual PR row and merge affordance with synthetic data in Chromium."""

import json
import os
from pathlib import Path
import shutil

import pytest

from tools.repair_bay.services.pr_review_service import merge_state

playwright = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]


def test_codex_changes_are_visible_before_forge_finishes():
    template = (ROOT / "templates/tools/repair_bay.html").read_text()
    render = template.split("window.loadPRReviews = function(state) {", 1)[1].split(
        "\nfunction _reviewFileProgress(", 1
    )[0]
    render = "window.loadPRReviews = function(state) {" + render
    source = (ROOT / "static/js/repair-bay-main.js").read_text()
    helpers = []
    for name in ["_prMergeAffordance", "_prStyleMergeBtn"]:
        start = source.index("function " + name + "(")
        helpers.append(source[start : source.index("\n}", start) + 2])
    rows = []
    for number, status, stale in [(3986, "pending", False), (3990, "in_progress", False), (3991, "pending", True)]:
        codex = {"verdict": "REQUEST_CHANGES", "finding_count": 2, "stale": stale}
        rows.append(
            dict(
                pr_number=number,
                title="Role boundary review",
                state="open",
                review_status=status,
                repo="KytranKatarn/archie-platform",
                codex=codex,
                merge_state=merge_state(status, "", codex=codex),
            )
        )
    html = (
        """<!doctype html><html><head><meta charset="utf-8"></head>
<body style="margin:16px;background:#0b1020;color:white;font-family:monospace">
<h2>Repair Bay · isolated status fixture</h2><p>Synthetic API; no production access.</p>
<span id="prReviewCount"></span><div id="prReviewList"></div><script>
var API='/api', _prStateFilter='open', _prScopeDefaults=undefined;
function _prInitReviewerPick() {}
const rows=ROWS;
window.fetch=async()=>({json:async()=>({reviews:rows,total:rows.length})});
HELPERS
RENDER
window.loadPRReviews();</script></body></html>""".replace(
            "ROWS", json.dumps(rows)
        )
        .replace("HELPERS", "\n".join(helpers))
        .replace("RENDER", render)
    )
    with playwright.sync_playwright() as manager:
        browser = manager.chromium.launch(
            headless=True,
            executable_path=shutil.which("chromium") or shutil.which("google-chrome"),
            args=["--no-sandbox"],
        )
        try:
            page = browser.new_page(viewport={"width": 1100, "height": 650})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.set_content(html)
            page.wait_for_selector("[data-pr-row]")
            cards = page.locator("[data-pr-row]")
            assert cards.count() == 3
            for index in [0, 1]:
                card = cards.nth(index)
                assert "CHANGES REQUESTED · CODEX" in card.inner_text()
                button = card.get_by_role("button", name="Blocked — re-review", exact=True)
                assert button.is_disabled()
                assert "Awaiting human read" not in card.inner_text()
            assert "WAITING FOR REVIEW" in cards.nth(2).inner_text()
            assert not errors
            evidence = os.getenv("CODEX_STATUS_SCREENSHOTS")
            if evidence:
                directory = Path(evidence)
                directory.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(directory / "codex-status-desktop.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                page.screenshot(path=str(directory / "codex-status-mobile.png"), full_page=True)
        finally:
            browser.close()
