"""Browser fixture for the actual Repairs detail renderer; no production login."""

import os
from pathlib import Path
import re

import pytest


@pytest.fixture
def detail():
    from playwright.sync_api import sync_playwright

    template = (Path(__file__).parents[1] / "templates/tools/repair_bay.html").read_text()
    script = template[template.index("function showProposalDetail(") : template.index("function closeDetail(")]
    ids = set(re.findall(r"getElementById\('([^']+)'\)", script))
    html = "<body>" + "".join('<div id="' + id + '"></div>' for id in ids) + "</body>"
    state = {
        "status": "fix_requested",
        "id": 12875,
        "title": "DHQ performance helper repair",
        "metadata": {"source": "code_health_audit", "issue_code": "PYFLAKES"},
    }
    posts, dialogs = [], []
    response = {"success": True, "queued": True, "worker_enabled": False}
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1000, "height": 440})

        def route(request):
            if request.request.url.endswith("/proposals/12875"):
                request.fulfill(json={"proposal": state})
            elif "/proposals/12875/" in request.request.url:
                posts.append((request.request.method, request.request.url))
                request.fulfill(json=response)
            else:
                request.fulfill(body=html, content_type="text/html")

        page.route("http://repair.test/**", route)
        page.goto("http://repair.test/")
        page.add_script_tag(
            content="var API='http://repair.test/api'; var _refreshes=0; function loadProposals(){_refreshes++;}"
            + script
        )

        def on_dialog(dialog):
            dialogs.append(dialog.message)
            dialog.accept()

        page.on("dialog", on_dialog)
        yield page, state, posts, dialogs, response
        browser.close()


def test_code_health_retry_uses_validated_queue_and_shows_paused_worker(detail):
    page, _, posts, dialogs, _ = detail
    page.evaluate("showProposalDetail(12875)")
    button = page.get_by_role("button", name="Queue retry", exact=True)
    button.wait_for()
    if os.getenv("REPAIR_UI_ARTIFACTS"):
        page.screenshot(path=str(Path(os.environ["REPAIR_UI_ARTIFACTS"]) / "retry-after.png"))
    button.click()
    page.wait_for_function("_refreshes === 1")
    assert posts == [("POST", "http://repair.test/api/proposals/12875/retry-fix")]
    assert dialogs == ["Repair queued. The repair worker is paused."]


def test_manual_audit_cannot_use_generic_execute(detail):
    page, state, posts, _, _ = detail
    state["status"] = "approved"
    state["metadata"]["issue_code"] = "SQL_INJECTION_RISK"
    page.evaluate("showProposalDetail(12875)")
    page.get_by_text("Security review required", exact=True).wait_for()
    assert page.get_by_role("button", name="Execute", exact=True).count() == 0
    assert posts == []


def test_retry_failure_is_visible_to_user(detail):
    page, _, posts, dialogs, response = detail
    response.clear()
    response.update(success=False, error="Finding requires planned manual review")
    page.evaluate("showProposalDetail(12875)")
    page.get_by_role("button", name="Queue retry", exact=True).click()
    page.wait_for_timeout(100)
    assert len(posts) == 1 and dialogs == ["Finding requires planned manual review"]


def test_non_audit_retry_keeps_existing_workflow(detail):
    page, state, posts, _, response = detail
    state["metadata"]["source"] = "qa_pipeline"
    response.clear()
    response.update(success=True)
    page.evaluate("showProposalDetail(12875)")
    page.get_by_role("button", name="Retry", exact=True).click()
    page.wait_for_function("_refreshes === 1")
    assert posts == [("POST", "http://repair.test/api/proposals/12875/retry")]


def test_pending_audit_requires_approval_before_queueing(detail):
    page, state, posts, _, _ = detail
    state["status"] = "pending"
    page.evaluate("showProposalDetail(12875)")
    page.get_by_role("button", name="Approve", exact=True).wait_for()
    assert page.get_by_role("button", name="Retry", exact=True).count() == 0
    assert page.get_by_role("button", name="Queue retry", exact=True).count() == 0
    assert posts == []
