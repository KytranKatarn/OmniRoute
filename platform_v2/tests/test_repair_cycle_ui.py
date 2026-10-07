"""Browser fixture for the actual Repairs detail renderer; no production login."""

import os
from pathlib import Path
import re

import pytest


@pytest.fixture
def detail():
    from playwright.sync_api import sync_playwright

    template = (Path(__file__).parents[1] / "templates/tools/repair_bay.html").read_text()
    script = template[template.index("function showProposalDetail(") : template.index("function toggleDiffView(")]
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
            elif request.request.url.endswith("/proposals/12875/repair-progress"):
                stage = (
                    (state.get("repair_progress") or {}).get("stage")
                    or (state["metadata"].get("repair_submission") or {}).get("stage")
                    or "generation"
                )
                request.fulfill(json={"success": True, "progress": {"stage": stage}})
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


def test_ready_patch_advances_existing_diff_to_submission(detail):
    page, state, posts, dialogs, response = detail
    state["status"] = "ready_for_review"
    state["code_changes"] = (
        "--- a/platform_v2/tools/faith/routes.py\n+++ b/platform_v2/tools/faith/routes.py\n@@ -1 +1 @@\n-old\n+new\n"
    )
    response.clear()
    response.update(
        success=True, queued=True, message="Saved patch queued for approval, sandbox tests and PR creation."
    )
    page.evaluate("showProposalDetail(12875)")
    button = page.get_by_role("button", name="Test & Submit Patch", exact=True)
    button.wait_for()
    if os.getenv("REPAIR_UI_ARTIFACTS"):
        page.screenshot(path=str(Path(os.environ["REPAIR_UI_ARTIFACTS"]) / "submission-after.png"))
    button.click()
    page.wait_for_function("_refreshes === 1")
    assert posts == [("POST", "http://repair.test/api/proposals/12875/submit-patch")]
    assert dialogs == ["Saved patch queued for approval, sandbox tests and PR creation."]


def test_pending_submission_cannot_regenerate_patch(detail):
    page, state, _, _, _ = detail
    state["status"] = "ready_for_review"
    state["code_changes"] = "saved diff"
    state["metadata"]["repair_submission"] = {"stage": "awaiting_approval"}
    page.evaluate("showProposalDetail(12875)")
    page.get_by_text("Patch stage: awaiting approval", exact=True).wait_for()
    assert page.get_by_role("button", name="Queue retry", exact=True).count() == 0
    assert page.get_by_role("button", name="Test & Submit Patch", exact=True).count() == 0


def test_merged_patch_offers_verification_instead_of_deployment_claim(detail):
    page, state, posts, _, _ = detail
    state["status"] = "pr_open"
    state["metadata"]["repair_submission"] = {"stage": "merged_awaiting_verification"}
    state["repair_progress"] = {"stage": "merged_awaiting_verification"}
    page.evaluate("showProposalDetail(12875)")
    button = page.get_by_role("button", name="Verify Completion", exact=True)
    button.wait_for()
    assert page.get_by_role("button", name="Deploy to Production", exact=True).count() == 0
    button.click()
    page.wait_for_function("_refreshes === 1")
    assert posts == [("POST", "http://repair.test/api/proposals/12875/verify-completion")]


@pytest.mark.parametrize("close_before_response", [False, True])
def test_delayed_progress_cannot_reopen_or_replace_detail(detail, close_before_response):
    page, state, _, _, _ = detail
    state["metadata"]["repair_submission"] = {"stage": "awaiting_review"}
    # Hold the progress promise while a user closes the detail or selects another proposal.
    page.evaluate(
        """() => {
        const nativeFetch = window.fetch;
        window.fetch = (url, options) => url.endsWith('/repair-progress')
            ? new Promise(resolve => { window.finishProgress = () => resolve({json: () => Promise.resolve({success:true,progress:{stage:'pr_open'}})}); })
            : nativeFetch(url, options);
    }"""
    )
    page.evaluate("showProposalDetail(12875)")
    page.wait_for_function("typeof finishProgress === 'function'")
    if close_before_response:
        page.evaluate("closeDetail()")
    else:
        page.route(
            "http://repair.test/api/proposals/12876",
            lambda route: route.fulfill(
                json={"proposal": {"id": 12876, "title": "New detail", "status": "pending", "metadata": {}}}
            ),
        )
        page.evaluate("showProposalDetail(12876)")
        page.get_by_text("New detail", exact=True).wait_for()
    page.evaluate("finishProgress()")
    page.wait_for_timeout(100)
    if close_before_response:
        assert page.locator("#proposalDetail").is_hidden()
    else:
        assert page.locator("#detailTitle").inner_text() == "New detail"
        assert page.get_by_text("Patch stage: pr open", exact=True).count() == 0


def test_close_cancels_progress_request_and_stops_polling(detail):
    page, state, _, _, _ = detail
    state["metadata"]["repair_submission"] = {"stage": "awaiting_review"}
    page.clock.install()
    page.evaluate(
        """() => {
        const nativeFetch = window.fetch;
        window.progressRequests = 0;
        window.progressAborted = false;
        window.fetch = (url, options) => {
            if (!url.endsWith('/repair-progress')) return nativeFetch(url, options);
            window.progressRequests++;
            if (options.signal) options.signal.addEventListener('abort', () => {window.progressAborted = true;});
            return new Promise(resolve => {window.finishProgress = () => resolve({json: () => Promise.resolve({success:true,progress:{stage:'awaiting_review'}})});});
        };
    }"""
    )
    page.evaluate("showProposalDetail(12875)")
    page.wait_for_function("progressRequests === 1")
    page.evaluate("closeDetail(); finishProgress();")
    page.clock.run_for(15000)
    assert page.evaluate("progressAborted") is True
    assert page.evaluate("progressRequests") == 1
    assert page.locator("#proposalDetail").is_hidden()
