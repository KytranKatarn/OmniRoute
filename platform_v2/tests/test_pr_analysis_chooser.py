"""Real Chromium, actual chooser/controller JS, synthetic API: never starts a review.

Run with --noconftest: no application, production DB, login or inference required.
PR_ANALYSIS_SCREENSHOTS optionally selects an evidence directory outside the repo.
"""

import json
import os
from pathlib import Path
import shutil

import pytest

playwright = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "templates/tools/repair_bay.html").read_text()


def function_source(start, end):
    return TEMPLATE[TEMPLATE.index(start) : TEMPLATE.index(end)].strip()


def fixture_html():
    css = "\n".join(
        (ROOT / "static/css" / name).read_text()
        for name in ["lcars-tokens.css", "light-mode.css", "lcars-modals.css", "repair-bay-pr-analysis.css"]
    )
    js = (ROOT / "static/js/repair-bay-pr-analysis.js").read_text()
    functions = "\n".join(
        function_source(start, end)
        for start, end in [
            ("function _prScopeBody(", "function _prScopeLabel("),
            ("function _prSelectedReviewer(", "function _prInitReviewerPick("),
            ("function triggerPRReReview(", "function prFileUrl("),
            ("function triggerPRAnalysis(", "function confirmMergePR("),
            ("async function triggerForgeReview(", "async function createPrFromPush("),
        ]
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{css}
        body {{margin:24px;background:var(--archie-bg-primary);color:var(--archie-text-secondary);font-family:sans-serif}}
        #analyze {{background:var(--archie-purple);color:white;padding:12px;border:0}}
        </style></head><body><h1>Repair Bay · isolated dialog fixture</h1>
        <p>Synthetic PR and API. No real review can be dispatched.</p>
        <select id="prScopePlan"><option value="">Server default</option><option value="per_file">Per file</option><option value="packed">Packed</option></select>
        <input id="prScopeMaxFiles" type="number">
        <select id="prReviewerPick"><option>F.O.R.G.E.</option><option>P.R.O.B.E.</option></select>
        <button id="analyze" onclick="triggerPRAnalysis(3912,'KytranKatarn/archie-platform',20)">Analyze</button>
        <button id="rereview" onclick="triggerPRReReview(3912,'KytranKatarn/archie-platform',null)">Re-review</button>
        <input id="forgeReviewPrNum" value="3912"><span id="forgeReviewStatus"></span>
        <button id="manual" onclick="triggerForgeReview()">Analyze entered PR</button>
        <script>var API='/tools/repair-bay/api';var _prStateFilter='open';window.refreshes=0;window.loadPRReviews=function(){{window.refreshes++;}};</script>
        <script>{js}</script><script>{functions}</script></body></html>"""


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as manager:
        executable = shutil.which("google-chrome") or shutil.which("chromium")
        instance = manager.chromium.launch(headless=True, executable_path=executable, args=["--no-sandbox"])
        yield instance
        instance.close()


@pytest.fixture
def ui(browser):
    context = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    page = context.new_page()
    state = {
        "posts": [],
        "scope_status": 200,
        "scope": {"success": True, "plan": "per_file", "max_files": 10, "max_files_ceiling": 25},
        "status": 202,
        "response": {"success": True, "status": "analyzing"},
        "non_json": False,
    }
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route(request):
        url = request.request.url
        if url == "http://repair-bay.test/":
            request.fulfill(content_type="text/html", body=fixture_html())
        elif url.endswith("/forge/review-scope"):
            request.fulfill(status=state["scope_status"], json=state["scope"])
        elif url.endswith("/forge/pr-reviews/3912/analyze"):
            state["posts"].append(request.request.post_data_json)
            if state["status"] == "abort":
                request.abort()
            elif state["non_json"]:
                request.fulfill(status=state["status"], content_type="text/html", body="Unavailable")
            else:
                request.fulfill(status=state["status"], json=state["response"])
        else:
            request.abort()  # All external resources and real HTTP are forbidden.

    page.route("**/*", route)
    page.goto("http://repair-bay.test/", wait_until="networkidle")
    yield page, state
    assert not errors, errors
    context.close()


def open_dialog(page, button="#analyze"):
    page.locator(button).click()
    playwright.expect(page.get_by_role("dialog", name="Choose PR analysis")).to_be_visible()
    playwright.expect(page.get_by_role("button", name="Run analysis", exact=True)).to_be_enabled()


def submit(page):
    # Two immediate clicks must never start two requests.
    page.get_by_role("button", name="Run analysis", exact=True).evaluate("b => { b.click(); b.click(); }")


def evidence(page, name):
    directory = os.environ.get("PR_ANALYSIS_SCREENSHOTS")
    if directory:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path / name), full_page=True)


@pytest.mark.parametrize("entry", ["#analyze", "#rereview", "#manual"])
def test_all_analysis_entrypoints_open_choices_without_dispatch(ui, entry):
    page, state = ui
    open_dialog(page, entry)
    assert state["posts"] == []
    playwright.expect(page.locator("#rb-pr-analysis-mode")).to_have_value("full")
    playwright.expect(page.locator("#rb-pr-analysis-summary")).to_contain_text("up to 25 files")
    page.get_by_role("button", name="Cancel", exact=True).click()
    assert state["posts"] == []


@pytest.mark.parametrize("dismiss", ["cancel", "escape", "close", "backdrop"])
def test_dismissal_does_not_dispatch_and_restores_focus(ui, dismiss):
    page, state = ui
    open_dialog(page)
    if dismiss == "cancel":
        page.get_by_role("button", name="Cancel", exact=True).click()
    elif dismiss == "escape":
        page.keyboard.press("Escape")
    elif dismiss == "close":
        page.get_by_role("button", name="Close analysis choices").click()
    else:
        page.mouse.click(2, 2)
    playwright.expect(page.get_by_role("dialog")).to_have_count(0)
    playwright.expect(page.locator("#analyze")).to_be_focused()
    assert state["posts"] == []


@pytest.mark.parametrize(
    "entry,repo",
    [("#analyze", "KytranKatarn/archie-platform"), ("#rereview", "KytranKatarn/archie-platform"), ("#manual", None)],
)
def test_full_diff_sends_one_explicit_request(ui, entry, repo):
    page, state = ui
    open_dialog(page, entry)
    submit(page)
    playwright.expect(page.get_by_role("button", name="Request accepted", exact=True)).to_be_disabled()
    assert state["posts"] == [
        {"repo": repo, "reviewer": "F.O.R.G.E.", "wide": True, "plan": "per_file", "max_files": 25}
    ]
    assert page.evaluate("window.refreshes") == 1
    playwright.expect(page.get_by_role("status")).to_contain_text("does not mean the review has finished")


def test_scoped_choice_honors_toolbar_then_dialog_overrides(ui):
    page, state = ui
    page.locator("#prScopePlan").select_option("packed")
    page.locator("#prScopeMaxFiles").fill("7")
    page.locator("#prReviewerPick").select_option("P.R.O.B.E.")
    open_dialog(page)
    page.locator("#rb-pr-analysis-mode").select_option("scoped")
    playwright.expect(page.locator("#rb-pr-analysis-plan")).to_have_value("packed")
    playwright.expect(page.locator("#rb-pr-analysis-max-files")).to_have_value("7")
    playwright.expect(page.get_by_role("dialog")).to_contain_text("Advisory QA opinion only")
    playwright.expect(page.locator("#rb-pr-analysis-summary")).to_contain_text("cannot cover all")
    page.locator("#rb-pr-analysis-max-files").fill("6")
    submit(page)
    playwright.expect(page.get_by_role("button", name="Request accepted", exact=True)).to_be_disabled()
    assert state["posts"] == [
        {
            "repo": "KytranKatarn/archie-platform",
            "reviewer": "P.R.O.B.E.",
            "wide": False,
            "plan": "packed",
            "max_files": 6,
        }
    ]


@pytest.mark.parametrize("invalid", ["0", "26", "1.5", ""])
def test_invalid_scoped_limit_cannot_launch(ui, invalid):
    page, state = ui
    open_dialog(page)
    page.locator("#rb-pr-analysis-mode").select_option("scoped")
    page.locator("#rb-pr-analysis-max-files").fill(invalid)
    playwright.expect(page.get_by_role("button", name="Run analysis", exact=True)).to_be_disabled()
    assert state["posts"] == []


@pytest.mark.parametrize("kind", ["busy", "non_json", "network"])
def test_failure_is_visible_without_success_refresh_or_auto_retry(ui, kind):
    page, state = ui
    if kind == "busy":
        state.update(status=409, response={"status": "in_progress", "message": "Review already running"})
    elif kind == "non_json":
        state.update(status=502, non_json=True)
    else:
        state["status"] = "abort"
    open_dialog(page)
    submit(page)
    playwright.expect(page.get_by_role("button", name="Request not confirmed", exact=True)).to_be_disabled()
    playwright.expect(page.get_by_role("status")).to_contain_text("Nothing will be retried automatically")
    if kind == "busy":
        playwright.expect(page.get_by_role("status")).to_contain_text("already running")
    assert len(state["posts"]) == 1
    assert page.evaluate("window.refreshes") == 0


def test_settings_failure_does_not_guess_scope_or_launch(ui):
    page, state = ui
    state.update(scope_status=500, scope={"success": False, "error": "Settings unavailable"})
    page.locator("#analyze").click()
    playwright.expect(page.get_by_role("status")).to_contain_text("Cannot load effective review limits")
    playwright.expect(page.get_by_role("button", name="Run analysis", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Cancel", exact=True).click()
    assert state["posts"] == []


def test_focus_trap_and_duplicate_open(ui):
    page, state = ui
    open_dialog(page)
    page.evaluate("triggerPRAnalysis(3913,'different/repo',1)")
    playwright.expect(page.get_by_role("dialog")).to_have_count(1)
    playwright.expect(page.get_by_role("dialog")).to_contain_text("PR #3912")
    page.get_by_role("button", name="Run analysis", exact=True).focus()
    page.keyboard.press("Tab")
    playwright.expect(page.get_by_role("button", name="Close analysis choices")).to_be_focused()
    page.keyboard.press("Shift+Tab")
    playwright.expect(page.get_by_role("button", name="Run analysis", exact=True)).to_be_focused()
    page.keyboard.press("Escape")
    assert state["posts"] == []


@pytest.mark.parametrize("width,height", [(374, 812), (717, 812), (1280, 900)])
def test_responsive_dialog_and_screenshot(ui, width, height):
    page, state = ui
    page.set_viewport_size({"width": width, "height": height})
    evidence(page, f"analysis-{width}-before.png")
    open_dialog(page)
    evidence(page, f"analysis-{width}-full.png")
    page.locator("#rb-pr-analysis-mode").select_option("scoped")
    evidence(page, f"analysis-{width}-choices.png")
    bounds = page.get_by_role("dialog").bounding_box()
    assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
    assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= height
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for name in ["Cancel", "Run analysis"]:
        assert page.get_by_role("button", name=name, exact=True).bounding_box()["height"] >= 44
    assert state["posts"] == []


@pytest.mark.parametrize("width", [374, 1280])
def test_light_theme_dialog_keeps_controls_visible(ui, width):
    page, state = ui
    page.set_viewport_size({"width": width, "height": 900})
    page.evaluate("document.body.classList.add('light-mode')")
    open_dialog(page)
    evidence(page, f"analysis-{width}-light.png")
    playwright.expect(page.get_by_role("button", name="Run analysis", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert state["posts"] == []


def test_template_loads_component_and_no_entrypoint_posts_directly():
    assert "css/repair-bay-pr-analysis.css" in TEMPLATE
    assert "js/repair-bay-pr-analysis.js" in TEMPLATE
    for start, end in [
        ("function triggerPRAnalysis(", "function confirmMergePR("),
        ("async function triggerForgeReview(", "async function createPrFromPush("),
        ("function triggerPRReReview(", "function prFileUrl("),
    ]:
        assert "fetch(" not in function_source(start, end)
