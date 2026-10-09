"""Exercise the real proposal-detail JavaScript in an isolated Chromium fixture."""

from pathlib import Path

from playwright.sync_api import sync_playwright


def test_planned_repair_controls_and_progress(tmp_path):
    template = (Path(__file__).parents[1] / "templates/tools/repair_bay.html").read_text()
    detail = template.split("function showProposalDetail(id) {", 1)[1].split("function closeDetail()", 1)[0]
    script = "function showProposalDetail(id) {" + detail
    # Real component script, local DOM fixture and mocked HTTP; no platform mutation.
    markup = template.split("<!-- Detail panel (hidden by default) -->", 1)[1].split(
        '\n          </div>\n          <div style="height:6px', 1
    )[0]
    static = Path(__file__).parents[1] / "static/css"
    css = (static / "lcars-tokens.css").read_text() + (static / "repair-bay.css").read_text()
    html = "<style>" + css + '</style><body style="background:#080d18;color:white">' + markup + "</body>"
    proposal = {
        "id": 19,
        "title": "Department HQ planned refactor",
        "status": "approved",
        "metadata": {"source": "code_health_audit", "issue_code": "LARGE_FILE"},
        "repair_progress": {
            "stage": "generation",
            "planned_work": {
                "kind": "planned_refactor",
                "eligible": True,
                "enabled": False,
                "reason": "Explicit request required",
            },
        },
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1000, "height": 700})
        page.set_content(html)
        page.evaluate(
            """proposal => {
                window.proposal = proposal; window.API = '/fixture'; window.postCount = 0;
                window.alert = () => {}; window.loadProposals = () => {};
                window.fetch = async (url, options) => ({json: async () => {
                    if (options && options.method === 'POST') {
                        window.postCount++;
                        proposal.repair_progress = {stage:'planned_queued', planned_work:{
                            task_id:77, task_status:'deferred', kind:'planned_refactor', enabled:true
                        }};
                        return {success:true, queued:true};
                    }
                    return url.endsWith('repair-progress')
                        ? {success:true, progress:proposal.repair_progress} : {success:true, proposal};
                }});
            }""",
            proposal,
        )
        page.add_script_tag(content=script)
        page.evaluate("showProposalDetail(19)")
        disabled = page.get_by_role("button", name="Planned repairs disabled")
        disabled.wait_for()
        assert disabled.is_disabled()
        page.screenshot(path=str(tmp_path / "planned-disabled.png"))
        page.evaluate("proposal.repair_progress.planned_work.enabled = true; showProposalDetail(19)")
        page.get_by_role("button", name="Queue planned refactor").click()
        page.get_by_text("Coding task #77 · deferred", exact=True).wait_for()
        assert page.evaluate("postCount") == 1
        assert page.get_by_role("button", name="Queue planned refactor").count() == 0
        page.screenshot(path=str(tmp_path / "planned-queued.png"))
        page.evaluate(
            "proposal.repair_progress.stage = 'planned_blocked'; proposal.repair_progress.planned_work.task_status = 'blocked'; showProposalDetail(19)"
        )
        page.get_by_text("Coding task #77 · blocked", exact=True).wait_for()
        assert "verified complete" not in page.locator("#detailActions").inner_text()
        page.screenshot(path=str(tmp_path / "planned-blocked.png"))
        browser.close()
