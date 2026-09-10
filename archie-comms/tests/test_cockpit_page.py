"""#6653 Phase 4 — the cockpit page: both layouts from one template; the JS never
renders server text with innerHTML."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "templates" / "cockpit.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "cockpit.css").read_text(encoding="utf-8")

IDS = ["pane-crew", "pane-builder", "pane-approvals", "ck-tabs", "ck-search", "ck-chips", "ck-roster", "ck-more",
       "ck-agent", "ck-agent-close", "ck-hire-open", "ck-hire", "ck-provider", "ck-model", "ck-prompt", "ck-system",
       "ck-run", "ck-jobs", "ck-approvals", "ck-strip", "ck-toast",
       "ck-switch", "pane-work", "ck-work-total", "ck-task-open", "ck-work-search", "ck-work-chips", "ck-work-list",
       "ck-work-more", "ck-task", "ck-task-close", "ck-task-title", "ck-task-body", "ck-task-new",
       "ck-task-new-project", "ck-target"]


def _extract(head):
    """Lift one top-level declaration out of cockpit.js by brace/bracket balance.

    Slicing the real file (rather than restating the logic here) is what makes the truth-table
    test non-vacuous: edit applyPhase and this test runs the EDITED function.
    """
    start = JS.index(head)
    opener = "[" if head.rstrip().endswith("[") else "{"
    closer = "]" if opener == "[" else "}"
    depth, i = 0, start
    while True:
        ch = JS[i]
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                break
        i += 1
    tail = JS[i + 1 : i + 2]
    return JS[start : i + 1] + (";" if tail != ";" else ";")


@pytest.fixture
def js_run():
    """Run an arbitrary snippet of the real cockpit.js in node and return its stdout.

    Same SKIP caveat as js_eval below: absent node means this silently does not run.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")

    def run(script):
        out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()

    return run


@pytest.fixture
def js_eval():
    """Run a snippet of the real cockpit.js in node and return a caller for applyPhase().

    NOTE, stated plainly: this SKIPS where node is absent. The always-running guards for the
    same behaviour are test_js_shows_apply_only_for_completed_targeted_unapplied_jobs and
    test_js_apply_settled_set_excludes_the_states_that_must_not_re_offer_apply — they pin the
    gate expression and the settled set textually. Only this one proves the logic.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed — the textual guards still cover the gate and the set")

    def make(src):
        def run(job):
            script = src + "\nprocess.stdout.write(applyPhase(JSON.parse(process.argv[1])));"
            out = subprocess.run(
                [node, "-e", script, json.dumps(job)], capture_output=True, text=True, timeout=30
            )
            assert out.returncode == 0, out.stderr
            return out.stdout.strip()

        return run

    return make


def test_template_has_every_id_the_js_binds():
    missing = [i for i in IDS if f'id="{i}"' not in HTML]
    assert not missing, missing


def test_template_has_the_work_pane_switch_sheet_form_and_target_field():
    html = HTML
    for needle in (
        'id="ck-switch"', 'data-left="crew"', 'data-left="work"',
        'id="pane-work"', 'aria-label="Work"', 'id="ck-work-total"', 'id="ck-task-open"', 'id="ck-work-search"',
        'id="ck-work-chips"', 'id="ck-work-list"', 'id="ck-work-more"',
        'id="ck-task"', 'aria-label="Task"', 'id="ck-task-close"', 'id="ck-task-title"', 'id="ck-task-body"',
        'id="ck-task-new"', 'id="ck-task-new-project"', 'name="title"', 'name="priority"', 'name="task_type"',
        'id="ck-target"', 'name="target_path"', 'data-pane="work"',
    ):
        assert needle in html, needle
    assert html.count('data-pane="') == 4


def test_css_places_the_work_pane_and_task_sheet_like_crew_and_agent():
    css = CSS
    assert "#pane-crew, #pane-work, #pane-builder { display: flex; }" not in css, "work and crew share a cell — only one shows"
    assert ".ck-switch" in css and ".ck-switch button[aria-pressed=\"true\"]" in css
    assert "#ck-task" in css
    # This rule is only correct INSIDE the desktop block — hoisted to top level it would make
    # the sheet permanently visible on a phone, and a whole-file substring check would still
    # pass. (The refuter placed it at 768px; it is actually in the 1024px block, which is where
    # #ck-task becomes a static column rather than an overlay.)
    desktop = css.split("@media (min-width: 1024px)")[1]
    assert "#ck-agent[hidden], #ck-task[hidden] { display: flex; }" in desktop
    assert "#pane-work.ck-show" in css or ".ck-left-work #pane-work" in css


def test_css_768_block_hides_pane_work_unless_left_work_is_active():
    # structural, not a spelling check: #pane-work must default to hidden in the 768px block,
    # and the ONLY rule allowed to re-show it there is the body.ck-left-work one — a stale
    # .ck-show class left over from the phone tab switch (specificity 0,0,2,0) must never be
    # able to win against the default. A rule added in another @media block must not count.
    tablet = CSS.split("@media (min-width: 768px)")[1].split("@media (min-width: 1024px)")[0]
    assert "#pane-work { display: none; }" in tablet
    rules = re.findall(r'([^{}]+)\{([^{}]*)\}', tablet)
    reshow = [sel.strip() for sel, body in rules if "#pane-work" in sel and re.search(r"display:\s*flex", body)]
    assert reshow == ["body.ck-left-work #pane-work"], reshow


def test_template_loads_cockpit_assets_and_not_the_chat_stylesheet():
    # the chat body rule is overflow:hidden and pins the cockpit at scrollY 0 — must NOT be linked
    assert '/static/css/archie-chat.css' not in HTML
    assert '/static/css/cockpit.css' in HTML and '/static/js/cockpit.js' in HTML
    assert 'name="viewport"' in HTML


def test_css_has_the_three_breakpoints_and_the_desktop_grid():
    assert "grid-template-columns: 320px 1fr 400px" in CSS
    for bp in ("480px", "768px", "1024px"):
        assert f"(max-width: {bp})" in CSS or f"(min-width: {bp})" in CSS, bp


def test_no_phantom_state_classes():
    assert "sc-live" not in HTML + CSS and "sc-static" not in HTML + CSS


JS = (ROOT / "static" / "js" / "cockpit.js").read_text(encoding="utf-8")


def test_js_never_renders_server_text_with_innerhtml():
    assert ".innerHTML" not in JS and "insertAdjacentHTML" not in JS and "outerHTML" not in JS


def test_js_binds_the_cockpit_routes_and_polls_every_5s():
    for route in ("/api/cockpit/agents", "/api/cockpit/agents/create", "/api/cockpit/build/providers", "/api/cockpit/build/run", "/api/cockpit/build/runs", "/api/approvals/pending"):
        assert route in JS, route
    assert "POLL_MS = 5000" in JS


def test_js_requires_the_typed_name_before_decommission():
    assert "decommissioned" in JS
    assert "type the agent's name" in JS.lower()  # the confirm prompt (double-quoted in the JS so the apostrophe is literal)


def test_chat_header_links_to_the_cockpit():
    chat = (ROOT / "templates" / "chat.html").read_text(encoding="utf-8")
    assert "/cockpit" in chat


def test_js_reset_reload_rewinds_the_roster_offset():
    # a reload after an action/decision must start from page 1 — "Load more" left offset at 50
    assert "if (reset) roster.offset = 0;" in JS


def test_js_keeps_polling_after_a_failed_jobs_poll():
    # spec §7: a poll error shows once and polling continues
    assert "jobsErrToasted" in JS and "const ACTIVE = new Set(['pending', 'pending_approval', 'running', 'queued'])" in JS


def test_js_polls_the_roster_while_a_hire_is_pending():
    assert "hirePending" in JS and "if (hirePending) loadRoster(true)" in JS


def test_css_hides_tabs_and_shows_the_strip_from_tablet_up():
    tablet = CSS.split("@media (min-width: 768px)")[1].split("@media (min-width: 1024px)")[0]
    assert ".ck-tabs { display: none; }" in tablet and "#pane-approvals { display: none !important; }" in tablet


def test_js_wires_the_work_pane_and_apply():
    js = JS
    assert "work: 'pane-work'" in js and "const WORK_POLL_MS = 30000" in js
    for needle in ("/api/cockpit/projects", "/api/cockpit/tasks", "'/api/cockpit/tasks/' + id + '/' + action", "/api/cockpit/build/' + id + '/apply'", "target_path", "localStorage"):
        assert needle in js, needle
    # ⚠️ A BARE "target_path" PROVES NOTHING — it also appears in renderJobs' display line and in
    # the Apply gate, so deleting the ONE statement that reads the field and puts it on the
    # request body left this whole test green while "choose a target file" silently stopped
    # working. Pin the read AND the assignment as one statement.
    assert "const target = $('ck-target').value.trim(); if (target) body.target_path = target;" in js
    assert "function loadWork(" in js and "function openTask(" in js and "function taskAct(" in js and "function applyJob(" in js
    assert "window.prompt" not in js.split("// ---- Work")[1].split("// ---- Approvals")[0], "task actions use inline inputs, not prompts"
    assert ".innerHTML" not in JS and "insertAdjacentHTML" not in JS


def test_js_shows_apply_only_for_completed_targeted_unapplied_jobs():
    """The gate moved from a raw `!j.apply_approval_id` to applyPhase(), because that id alone
    could not tell a pending apply from a denied one — see the phase tests below. What must
    still hold: Apply appears ONLY for a completed job with a target that is not already a PR
    and has no LIVE approval, and the phase is what decides it."""
    js = JS
    assert "if (j.status === 'completed' && j.target_path && (phase === 'none' || phase === 'settled')) {" in js
    # …and the phase used by the button is the one computed for THIS job, not a stale outer var.
    assert "const phase = applyPhase(j);" in js
    assert "'PR #' + j.pr_number" in js and "j.apply_error" in js
    # a live approval still suppresses it: 'pending' is absent from the enabling condition
    gate = js.split("if (j.status === 'completed' && j.target_path && ", 1)[1].split(") {", 1)[0]
    assert "pending" not in gate, gate


def test_js_apply_settled_set_excludes_the_states_that_must_not_re_offer_apply():
    """`approved` and `executed` mean the executor is about to run or has run; re-offering
    Apply there risks a second branch and a duplicate PR. `pending` is the original bug's
    opposite — it MUST keep the button hidden."""
    raw = JS.split("const APPLY_SETTLED = [", 1)[1].split("]", 1)[0]
    settled = {x.strip().strip("'\"") for x in raw.split(",") if x.strip()}
    assert settled == {"rejected", "denied", "expired", "failed", "cancelled"}, settled
    # 'rejected' is the one that matters: it is what every deny path writes. Its absence is the
    # defect this set was rewritten to fix, so name it separately from the equality above.
    assert "rejected" in settled


def test_applyPhase_truth_table(js_eval):
    """Behavioural, not textual: runs the real applyPhase() and asserts every case that the
    old `!j.apply_approval_id` gate got wrong."""
    run = js_eval(_extract("const APPLY_SETTLED = [") + "\n" + _extract("function applyPhase(j) {"))
    assert run({}) == "none"
    assert run({"pr_number": 7}) == "pr"
    assert run({"apply_approval_id": 5, "apply_approval_status": "pending"}) == "pending"
    # THE BUG: these used to render "apply waits for approval #N" forever.
    # 'rejected' FIRST and deliberately: it is what EVERY deny path actually writes to
    # autonomy_approval_queue (approvals_routes.py:254, telegram_gateway 1034/1149/1232/2127).
    # The first cut of this fix omitted it — copied from an app.py docstring that said 'denied'
    # — so the common settle path stayed stuck and the fix defeated its own purpose. 'denied'
    # is contractor_approval_requests' word and is kept only because that table does use it.
    for settled in ("rejected", "denied", "expired", "failed", "cancelled"):
        assert run({"apply_approval_id": 5, "apply_approval_status": settled}) == "settled", settled
    # about to run / already ran — must NOT re-offer Apply
    for live in ("approved", "executed"):
        assert run({"apply_approval_id": 5, "apply_approval_status": live}) == "pending"
    # an older hub sends no key at all, and a purged queue row resolves to null: neither is
    # evidence the apply is over, so both stay "pending" (today's wording, button hidden).
    assert run({"apply_approval_id": 5}) == "pending"
    assert run({"apply_approval_id": 5, "apply_approval_status": None}) == "pending"
    # a PR wins over any approval state
    assert run({"pr_number": 7, "apply_approval_id": 5, "apply_approval_status": "denied"}) == "pr"


def test_js_apply_success_message_never_claims_applied_or_merged():
    # the real flow only raises a Tier-2 approval that a human merges — the success toast must
    # say so, and must never claim the change was already applied or merged
    fn = JS.split("async function applyJob(", 1)[1].split("\n  }\n", 1)[0]
    success = fn.split("return; }", 1)[1]
    assert "approval" in success.lower()
    assert "applied" not in success.lower()
    assert "merged" not in success.lower()


def test_js_clears_a_note_only_after_the_write_landed():
    """It used to clear on BOTH paths. On success the sheet had already been rebuilt, so the
    clear was a no-op — meaning the only text it ever really destroyed was the owner's
    unsaved note after a FAILED save."""
    act = JS.split("async function taskAct(", 1)[1].split("\n  }\n", 1)[0]
    assert "return false;" in act and "return true;" in act, act
    assert "taskAct(t.id, 'note', { text }, 'Note added').then((ok) => { if (ok) noteBox.value = ''; });" in JS
    # non-vacuity: the unconditional form must be gone
    assert ".then(() => { noteBox.value = ''; })" not in JS


def test_js_never_rebuilds_the_task_sheet_while_the_owner_is_using_it():
    """renderTask() does body.textContent = '' — a 10 s poll running that destroyed a
    half-typed note and any status/priority chosen but not yet applied."""
    assert "taskWatch = setInterval(() => { if (!taskSheetBusy()) openTask(id); }, 10000);" in JS
    busy = JS.split("function taskSheetBusy() {", 1)[1].split("\n  }\n", 1)[0]
    # all three losses the poll could cause must be covered
    assert "document.activeElement" in busy, busy          # typing / mid-selection
    assert "taskEls.note" in busy, busy                    # an unsent note
    # The exact comparison, not just the names: both node-backed tests SKIP where node is
    # absent, and everything else here proves the render-time capture EXISTS rather than that it
    # is what gets compared. This is the only always-running assertion that pins the fix itself.
    assert "taskEls.status.value !== taskEls.statusAtRender" in busy, busy
    assert "taskEls.prio.value !== taskEls.prioAtRender" in busy, busy
    # …and the comparison against the task's own field — which a NULL priority wedges — is gone
    assert "String(currentTask.priority)" not in busy, busy
    # …and the refs are actually populated on every render, or the checks read null forever.
    # The *AtRender captures are part of the wiring, not decoration: without them the busy
    # check compares against undefined and the guard silently stops guarding. (This assertion
    # used to stop at the ref, and a mutation that deleted the capture went undetected.)
    for wiring in ("taskEls.status = stSel; taskEls.statusAtRender = stSel.value;",
                   "taskEls.prio = prSel; taskEls.prioAtRender = prSel.value;",
                   "taskEls.note = noteBox;"):
        assert wiring in JS, wiring


def test_js_loads_the_work_pane_when_the_desktop_column_is_what_reveals_it():
    """From 768px up the Work column's visibility comes from body.ck-left-work, not from a pane
    tab — so showPane('work') cannot be the only loader, or a saved 'work' preference with the
    hash on #builder renders a permanently blank column."""
    left = JS.split("function setLeft(name, persist) {", 1)[1].split("\n  }\n", 1)[0]
    assert "if (booted && leftChoice === 'work' && !workLoaded) loadWork(true);" in left, left
    # the boot path too: setLeft() runs before `work`/`workLoaded` exist, so it is deliberately
    # inert until `booted`, and boot has to do the first load itself.
    assert "booted = true;" in JS
    assert "if (leftChoice === 'work' && !workLoaded) loadWork(true);" in JS.split("booted = true;", 1)[1]


def test_js_polls_work_on_real_visibility_not_only_the_phone_tab_class():
    vis = JS.split("function workVisible() {", 1)[1].split("}", 1)[0]
    assert "getClientRects" in vis, vis
    assert "setInterval(() => { if (workLoaded && workVisible()) refreshWork(); }, WORK_POLL_MS);" in JS
    # non-vacuity: the .ck-show-only gate is gone
    assert "$('pane-work').classList.contains('ck-show')) loadWork(true)" not in JS


def test_js_refresh_does_not_discard_pages_the_owner_loaded():
    """loadWork(true) reset offset to 0, so every 30 s poll threw away "Load more" pages."""
    ref = JS.split("function refreshWork() {", 1)[1].split("\n  }\n", 1)[0]
    assert "work.offset + TASK_PAGE" in ref and "WORK_MAX_REFRESH" in ref, ref
    # past the server's clamp we skip rather than silently truncate
    assert "if (loaded > WORK_MAX_REFRESH) return;" in ref
    assert "loadWork(false, loaded);" in ref
    # the span request must start at 0 and rebuild, or a refresh would append duplicates.
    # The request is shaped in loadWork; the rebuild happens in _loadWork (split for the
    # re-entry guard's finally) — assert each in the function that owns it.
    lw = JS.split("async function loadWork(reset, spanLimit) {", 1)[1].split("\n  }\n", 1)[0]
    assert "const from = spanLimit ? 0 : work.offset;" in lw and "const size = spanLimit || TASK_PAGE;" in lw, lw
    inner = JS.split("async function _loadWork(qs, reset, spanLimit) {", 1)[1].split("\n  }\n", 1)[0]
    assert "if (reset || spanLimit) list.textContent = '';" in inner, inner


def test_js_saves_the_left_preference_only_on_a_deliberate_switch():
    """showPane('crew') also runs when the owner merely arrives from Chat at /cockpit#crew —
    writing localStorage there silently reset a saved Work preference."""
    left = JS.split("function setLeft(name, persist) {", 1)[1].split("\n  }\n", 1)[0]
    assert "if (persist) { try { localStorage.setItem('ck-left', leftChoice); }" in left, left
    # non-vacuity: the unconditional write is gone, and the two callers disagree on purpose
    assert "\n    try { localStorage.setItem('ck-left', leftChoice); } catch (e) { /* ignore */ }\n" not in JS
    assert "if (name === 'crew' || name === 'work') setLeft(name, false);" in JS       # navigation
    assert "setLeft(b.dataset.left, true); location.hash = b.dataset.left;" in JS      # the switch


def test_js_refuses_a_re_entrant_identical_work_load():
    """`workLoaded` is only set AFTER the awaits, so it cannot dedupe in flight: one Work-switch
    click ran loadWork up to 5x and boot with #work ran it 2x — same DOM, ~10 redundant requests
    and visible flicker."""
    lw = JS.split("async function loadWork(reset, spanLimit) {", 1)[1].split("\n  }\n", 1)[0]
    assert "if (workLoading === sig) return;" in lw, lw
    assert "workLoading = sig;" in lw, lw
    # cleared in a finally, or a failed fetch's early return strands it and wedges Work forever
    assert "finally { if (workLoading === sig) workLoading = null; }" in lw, lw
    # the guard is SYNCHRONOUS — it must precede every await in the function
    assert lw.index("workLoading = sig;") < lw.index("await"), "guard must run before any await"
    # keyed on the request, so a changed filter is never dropped: the signature carries the query
    assert "const sig = qs.toString()" in lw, lw


def test_taskSheetBusy_is_not_wedged_by_a_task_with_no_selected_priority(js_run):
    """A <select> with no matching option is not empty — the browser auto-selects the first —
    so comparing against the task's own NULL priority read '1' !== 'null' and left the sheet
    permanently "busy" with the 10 s poll dead for that task."""
    src = _extract("function taskSheetBusy() {")
    # The stub is ID-AWARE on purpose: a `$ = () => sheet` that ignores its argument makes the
    # focus branch unreachable, so changing $('ck-task') to any other id — or deleting the
    # branch — would leave both this test and the textual guard green while, in the browser,
    # the poll rebuilt the sheet under the owner's hands.
    harness = (
        "const FOCUSED = { tag: 'textarea' };\n"
        "let sheetHasFocus = false;\n"
        "const $ = (id) => (id === 'ck-task' ? { contains: (el) => sheetHasFocus && el === FOCUSED } : null);\n"
        "const document = { activeElement: null };\n"
        "let taskEls = { note: null, status: null, prio: null, statusAtRender: null, prioAtRender: null };\n"
        + src
        + "\nconst out = [];\n"
        # a NULL-priority task: the select reports '1' but nothing was changed
        "taskEls = { note: { value: '' }, status: { value: 'pending' }, statusAtRender: 'pending',"
        " prio: { value: '1' }, prioAtRender: '1' };\n"
        "out.push('null_priority=' + taskSheetBusy());\n"
        # the owner actually changes the priority — still detected
        "taskEls.prio = { value: '7' };\n"
        "out.push('changed_priority=' + taskSheetBusy());\n"
        # …and the status, on the same mechanism
        "taskEls.prio = { value: '1' }; taskEls.status = { value: 'blocked' };\n"
        "out.push('changed_status=' + taskSheetBusy());\n"
        # an unsent note still counts as busy
        "taskEls.status = { value: 'pending' }; taskEls.note = { value: ' hi ' };\n"
        "out.push('unsent_note=' + taskSheetBusy());\n"
        # focus INSIDE the sheet is busy; the identical state with focus elsewhere is not —
        # only an id-aware $ can tell those two apart
        "taskEls.note = { value: '' };\n"
        "document.activeElement = FOCUSED; sheetHasFocus = true;\n"
        "out.push('focus_in_sheet=' + taskSheetBusy());\n"
        "sheetHasFocus = false;\n"
        "out.push('focus_elsewhere=' + taskSheetBusy());\n"
        "process.stdout.write(out.join(','));"
    )
    assert js_run(harness) == (
        "null_priority=false,changed_priority=true,changed_status=true,unsent_note=true,"
        "focus_in_sheet=true,focus_elsewhere=false"
    )


def _decomment(css):
    """Strip /* … */ so a rule's captured selector is a selector, not the prose above it."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_css_1024_takes_both_entry_forms_out_of_the_fixed_overlay_layer():
    """#ck-hire and #ck-task-new both ship as .ck-sheet — position: fixed; inset: 0; z-index: 6.

    At desktop #ck-task is a GRID ITEM carrying that same z-index (a non-auto z-index makes a
    grid or flex item paint as if positioned, even at position: static) and is LATER in DOM
    order, so it won the tie and painted over the form: 4 of 10 points sampled across the
    full-width "Create task" button returned #ck-task from elementFromPoint — the centre among
    them — and Playwright reported #ck-task intercepting the click. #ck-hire shipped in Phase 4a
    with the identical latent bug, so the fix has to reach both, not just the new one.
    """
    top, desktop = CSS.split("@media (min-width: 1024px)")
    # the phone pattern must survive byte-for-byte: there the full-screen sheet is correct
    assert ".ck-sheet { position: fixed; inset: 0; z-index: 6;" in top
    rules = re.findall(r"([^{}]+)\{([^{}]*)\}", _decomment(desktop))
    hits = [(sel.strip(), body) for sel, body in rules
            if ".ck-form" in sel or "#ck-hire" in sel or "#ck-task-new" in sel]
    assert hits, "no desktop treatment for the entry forms — they are still inset:0 overlays"
    # both forms covered, by the class they share or by name — patching only #ck-task-new leaves
    # the Phase 4a form eating clicks in exactly the same way
    covered = any(".ck-form" in sel for sel, _ in hits) or (
        any("#ck-hire" in sel for sel, _ in hits) and any("#ck-task-new" in sel for sel, _ in hits))
    assert covered, hits
    decls = " ".join(b for _, b in hits)
    assert re.search(r"position:\s*static", decls), hits
    # z-index has to be surrendered too, not just position: a flex item (which each form is,
    # inside its .ck-pane) keeps its stacking context at position: static if z-index stays 6.
    assert re.search(r"z-index:\s*auto", decls), hits
    # …and nothing in the block puts them back on the overlay layer
    assert not re.search(r"position:\s*fixed", decls), hits


def test_js_scrolls_a_desktop_form_into_view_when_it_opens():
    """In flow the panel sits after the list in its pane column, so on a 1280x800 desktop it can
    open below the fold — "+ Task" would read as doing nothing. No-op for the phone's fixed
    inset:0 sheet, which already fills the viewport, so <1024 behaviour is unchanged."""
    assert "function revealForm(el) { if (el.scrollIntoView) el.scrollIntoView({ block: 'nearest' }); }" in JS
    for opener, form in (("ck-hire-open", "ck-hire"), ("ck-task-open", "ck-task-new")):
        needle = "$('%s').addEventListener('click'" % opener
        line = next((l for l in JS.splitlines() if needle in l), None)
        assert line, opener
        # on the OPEN handler itself, not merely present somewhere in the file
        assert "revealForm($('%s'))" % form in line, line


def test_js_never_refills_a_dropdown_the_owner_is_choosing_from():
    """The 30 s Work poll rebuilt #ck-task-new-project with textContent='' + re-append, which
    DISCARDS the selection while leaving the typed title intact — the form still looks complete
    and submits under the first option. Measured: pick project 343, wait 35 s, the select reads
    270; that is how task #6682 was filed against a project the owner never chose. The roster
    poll does the same to #ck-hire-dept. Both refills must now sit behind keepChoice().
    """
    guard_body = JS.split("function keepChoice(id, sel) {", 1)[1].split("\n", 1)[0]
    assert "formOnScreen(id)" in guard_body and "sel.options.length" in guard_body, guard_body
    # on-screen is asked of the LAYOUT — `hidden` alone is not it, since showPane() sets
    # hidden=true without removing .ck-show and the .ck-show display rule beats [hidden]
    on_screen = JS.split("function formOnScreen(id) {", 1)[1].split("\n", 1)[0]
    assert "getClientRects" in on_screen, on_screen
    for form_id, wipe in (("ck-task-new", "sel.textContent = '';"), ("ck-hire", "dept.textContent = '';")):
        needle = "if (!keepChoice('%s', " % form_id
        line = next((l for l in JS.splitlines() if needle in l), None)
        assert line, form_id
        # the wipe must be INSIDE the guard, not merely somewhere after it
        assert wipe in line, line
    # …and no bare, unguarded refill survives — including the original one-liner form
    assert not re.search(r"^\s*(?:const \w+ = \$\('[\w-]+'\); )?(?:sel|dept)\.textContent = '';",
                         JS, re.M), "an unguarded dropdown refill is back"
