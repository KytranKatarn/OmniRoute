"""Guard: no NEW unsafe inline event-handler interpolation (#5874).

Stored-XSS shipped in commit 0ebcd5717 (Department HQ "Create from this" hiring-candidate
button), fixed in e286cfa0e. The vulnerable line looked like:

    var payload = JSON.stringify({capability: c.capability, narrative: c.narrative || '',
                                  hire_id: c.id}).replace(/'/g, '&apos;');
    ... "<button onclick='openAgentCreate(" + payload + ")'>...";

WHY A QUOTE-ESCAPING replace() DOES NOT FIX THIS (the mechanism, not just the symptom):
an HTML attribute value is entity-decoded by the browser's HTML parser BEFORE the
handler's contents are compiled as JavaScript -- two separate decode stages.
JSON.stringify() correctly escapes a REAL quote character (`"` -> `\"`), but it has no
reason to touch the six ordinary letters `&quot;` sitting inside a string -- to
JSON.stringify that is just text. So a candidate `narrative` containing any of:

    &quot;});alert(1);//
    &#39;});alert(2);//
    &#x27;});alert(3);//

survives JSON.stringify unchanged, gets decoded to a real quote by the HTML attribute
parser, and ONLY THEN is parsed as JavaScript -- where it terminates the JSON string and
turns everything after it into executable code. This text is LLM-authored (K.I.N.'s auto
hire proposals, also writable via the `propose_hire` MCP tool) -- no attacker intent is
needed to trigger it. Verified live (see task-9-report.md): all three payloads produced a
button with `hasAttribute('onclick') === false` and the payload passed through as an inert
JS string, once the fix below was applied.

THE FIX (in department-hq.js, `renderHiringStrip`/`_hiringStripClickHandler`): remove the
inline handler entirely. Buttons carry only `data-hire-id="<numeric id>"`; a single
delegated click handler looks the real candidate object up (by id, from the array already
fetched from the API) and passes it straight to `openAgentCreate()`. No candidate text
ever passes through an HTML attribute or gets parsed as JS again.

WHY A BARE COUNT IS NOT ENOUGH (2nd review pass): this file already has 31 pre-existing
inline `onclick` handlers built by string interpolation, e.g. `onclick="fn(' + a.id + ')"`.
A ratchet that only checks "total count did not increase" is defeated by a SWAP: delete
one of those 31 safe lines and add one new line interpolating free text (e.g.
`c.narrative`) and the count stays at 31 while the guard falsely passes. That is the same
"unmonitored while appearing monitored" shape this codebase keeps rediscovering elsewhere
(W.A.R.D.E.N. querying a table that never existed, silently swallowing the error every
run; backup freshness measured on the newest ROW instead of the newest SUCCESS).

THE FIX FOR THE GUARD ITSELF: gate on SHAPE, not count.
  1. `_BASELINE_LINES` is the exact, literal text of all 31 pre-existing matches, audited
     by hand (2026-08-21): every one interpolates a bare numeric DB id (`a.id`, `d.id`,
     `agentId`, `aid`, `post.id`, `p.id`) or that id wrapped in `esc()`/a ternary/an `||`
     default. These are grandfathered by EXACT TEXT, not by pattern -- editing any one of
     them even slightly removes it from the grandfather list and re-subjects it to rule 2.
  2. Anything NOT in that exact set -- a brand new match, or an edited baseline line -- is
     only allowed if every value it interpolates matches `ID_SHAPED_RE`: a bare
     identifier/property chain ending in `id`/`Id`/`ID`, optionally wrapped in
     `Number(...)` or `parseInt(...)`. WHY THIS IS SAFE: a number cannot carry an HTML
     entity -- there is no digit sequence that decodes to a quote character, so neither
     the attribute-decode stage nor the JS-parse stage can ever produce a break-out from
     an id-shaped value. This is the actual security property, not merely convention;
     do not widen this allowlist to silence a false positive without re-deriving that
     property for whatever you are adding.
  3. `agent_profile_modal.js` has zero pre-existing matches (Task 10 is actively editing
     it; scanned read-only) -- anything appearing there must pass rule 2 outright.

This scheme catches the SWAP case: deleting a baseline line and adding a same-shaped-count
replacement interpolating `c.narrative` leaves the new line outside `_BASELINE_LINES` AND
failing `ID_SHAPED_RE` -- flagged regardless of the total count. Proven below in
`TestGuardCatchesTheSwap`, per the review that requested this rewrite.

⚠️ Known imprecision, inherited from the review's own suggested pattern: `ID_SHAPED_RE` is
a naming heuristic, not a type system -- an identifier that merely ends in the letters
"id" (e.g. a hypothetical `void`/`avoid`) would pass even though it is not actually an id.
This is an accepted, disclosed limitation of a lightweight source guard, not a claim of
formal soundness.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]

# Locates the START of an inline handler built by interpolation: on(click|change|input|
# submit)=<quote>ident(<opposite-quote> -- the break-out shape common to every vulnerable
# and every pre-existing safe line alike. A static call like onclick="openAgentCreate(null)"
# never matches: there is no quote character immediately after the "(".
_HANDLER_START_RE = re.compile(r"""on(?:click|change|input|submit)=(?P<q>['"])[\w.$]*\s*\((?P<opp>['"])""")

# A bare identifier/property chain ending in id/Id/ID (e.g. a.id, agentId, aid, post.id),
# optionally wrapped in Number(...) or parseInt(..., 10). See the module docstring for WHY
# this is the safety boundary: a number cannot carry an HTML entity.
_BARE_ID = r"[A-Za-z_$][\w.$]*(?:[Ii]d|ID)"
ID_SHAPED_RE = re.compile(
    r"\A(?:%s|Number\(\s*%s\s*\)|parseInt\(\s*%s\s*(?:,\s*10\s*)?\))\Z" % (_BARE_ID, _BARE_ID, _BARE_ID)
)

# Exact, audited text of every pre-existing interpolated inline handler in department-hq.js
# as of 2026-08-21 -- grandfathered by CONTENT, not by count. agent_profile_modal.js has no
# baseline: it is held to rule 2 (ID_SHAPED_RE) outright for every match.
_BASELINE_LINES = {
    "tools/department_hq/static/js/department-hq.js": {
        "html += '<div class=\"dhq-org-director dhq-clickable\" onclick=\"openAgentSummary(' + d.id + ')\">'",
        "html += '<div class=\"dhq-org-agent dhq-clickable\" onclick=\"openAgentSummary(' + a.id + ')\">'",
        "+ (rosterSelection.has(a.id) ? ' checked' : '') + ' onchange=\"toggleRosterSel(' + a.id + ',this.checked)\"></td>'",
        "html += '<span onclick=\"openAgentDetail(' + oa.id + ')\" style=\"cursor:pointer;text-decoration:underline\">'",
        "+ '<button class=\"dhq-btn-sm dhq-btn-edit\" onclick=\"toggleIdentityEdit(' + a.id + ')\">Edit</button>'",
        "+ '<button class=\"dhq-action-btn dhq-action-save\" onclick=\"saveIdentity(' + a.id + ')\">Save Identity</button>'",
        "+ '<button class=\"dhq-action-btn\" onclick=\"toggleIdentityEdit(' + a.id + ')\">Cancel</button>'",
        "+ '<button class=\"dhq-btn-sm\" onclick=\"generatePortraitPrompt(' + a.id + ')\">Auto-Generate</button>'",
        "+ '<button class=\"dhq-btn-sm dhq-btn-edit\" onclick=\"toggleSocialEdit(' + a.id + ')\">Edit</button>'",
        "+ '<button class=\"dhq-action-btn dhq-action-save\" onclick=\"saveWritingVoice(' + a.id + ')\">Save Voice</button>'",
        "+ '<button class=\"dhq-action-btn\" onclick=\"toggleSocialEdit(' + a.id + ')\">Cancel</button>'",
        "+ '<button class=\"dhq-action-btn\" onclick=\"addSocialProfile(' + a.id + ')\">Add</button>'",
        '+ \'<button class="dhq-action-btn" onclick="generateSocialPost(\' + a.id + \')" id="btnGenPost">Generate</button>\'',
        "+ '<button class=\"dhq-action-btn dhq-action-save\" onclick=\"saveSocialPost(' + a.id + ')\">Save as Draft</button>'",
        "+ '<button class=\"dhq-btn-sm\" onclick=\"addAgentFact(' + a.id + ')\">Add</button>'",
        "+ '<button class=\"dhq-action-btn dhq-action-shift\" onclick=\"changeAgentShift(' + a.id + ',\\'' + esc(a.shift_state) + '\\')\">Cycle Shift</button>'",
        "gHtml += '<button class=\"dhq-btn-sm\" onclick=\"setPrimaryPortrait(' + agentId + ',' + p.id + ')\">Set Primary</button>';",
        "+ (post.status === 'draft' ? ' &middot; <button class=\"dhq-btn-sm\" onclick=\"publishPost(' + post.id + ',' + agentId + ')\">Publish</button>' : '')",
        ": '<button class=\"dhq-btn dhq-btn-primary\" onclick=\"signalSessionLoginStart(' + aid + ', \\'' + plat + '\\')\">Start one-time login</button>')",
        "+ '<button class=\"dhq-btn\" onclick=\"signalSaveLinkedInCreds(' + aid + ', \\'' + plat + '\\')\">Save encrypted</button>'",
        "+   '<button class=\"dhq-action-btn dhq-action-primary\" onclick=\"approveSignalPost(' + a.id + ')\">\u2713 Approve &amp; Post</button>'",
        "+   '<button class=\"dhq-action-btn dhq-action-danger\" onclick=\"denySignalPost(' + a.id + ')\">\u2717 Deny</button>'",
        "+ ' onclick=\"_onSignalChipClick(' + (post.approval_id || 0) + ',\\'' + post.status + '\\')\"'",
        '+ \'<td><button class="dhq-btn" style="font-size:0.6rem" onclick="signalCalendarCancel(\' + p.id + \')">\u2715 Cancel</button></td>\'',
        "+    'onclick=\"_signalApprovePost(' + aid + ')\">'",
        "+    'onclick=\"_signalRejectPost(' + aid + ')\">'",
        "+    'onclick=\"_signalRetryPost(' + aid + ')\">Retry</button>';",
        "+    'onclick=\"_signalAbandonPost(' + aid + ')\">Mark Won\\'t Fix</button>';",
        "+ '<button onclick=\"approvalAction(' + a.id + ',\\'approve\\')\" style=\"background:#10B981;color:#fff;border:none;padding:4px 10px;border-radius:4px;font-size:0.7rem;cursor:pointer\">Approve</button>'",
        "+ '<button onclick=\"approvalAction(' + a.id + ',\\'reject\\')\" style=\"background:#ef4444;color:#fff;border:none;padding:4px 10px;border-radius:4px;font-size:0.7rem;cursor:pointer\">Reject</button>'",
        ": '<button style=\"font-size:0.7rem;padding:3px 12px;cursor:pointer;background:var(--cat-accent,#00ffff);color:#010409;border:none;border-radius:10px;font-family:\\'Antonio\\',sans-serif;letter-spacing:1px;\" onclick=\"replayInterruptedJob(' + esc(j.id) + ', this)\">REPLAY</button>';",
    },
    "static/js/agent_profile_modal.js": set(),
}


def _segments_for_line(line):
    """Return the list of interpolated `+ ... +` segments in the FIRST inline handler on
    this line, or None if the handler's closing `)<quote>` cannot be located (fail-closed:
    callers must treat None as offending, never as safe)."""
    m = _HANDLER_START_RE.search(line)
    if not m:
        return None
    q = m.group("q")
    start = m.end()
    term = line.find(")" + q, start)
    if term == -1:
        return None
    inner = line[start : term + 1]
    return re.findall(r"\+\s*([^+'\"]+?)\s*\+", inner)


def find_offending(text, baseline_lines):
    """Every interpolated-inline-handler line in `text` that is neither an exact member of
    `baseline_lines` NOR entirely id-shaped. Returns [(1-based line no, reason, line)]."""
    out = []
    for i, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not _HANDLER_START_RE.search(line):
            continue
        if line in baseline_lines:
            continue
        segments = _segments_for_line(line)
        if segments is None:
            out.append((i + 1, "handler close could not be located (fail-closed)", line))
            continue
        bad = [s.strip() for s in segments if not ID_SHAPED_RE.match(s.strip())]
        if bad:
            out.append((i + 1, f"non-id-shaped interpolation: {bad}", line))
    return out


class TestIdShapedRegex(unittest.TestCase):
    def test_accepts_known_safe_shapes(self):
        for s in ("d.id", "a.id", "oa.id", "p.id", "post.id", "agentId", "aid", "Number(x.id)", "parseInt(a.id, 10)"):
            self.assertTrue(ID_SHAPED_RE.match(s), f"{s!r} should be id-shaped")

    def test_rejects_known_unsafe_shapes(self):
        for s in (
            "payload",
            "c.narrative",
            "c.capability",
            "esc(a.shift_state)",
            "plat",
            "post.status",
            "(post.approval_id || 0)",
        ):
            self.assertFalse(ID_SHAPED_RE.match(s), f"{s!r} must NOT be treated as id-shaped")


class TestNoOffendingInlineHandlerInterpolation(unittest.TestCase):
    """The real guard: these files must never gain an inline handler interpolating
    anything other than a bare numeric-id-shaped value (or a grandfathered exact line)."""

    def test_scanned_files_exist(self):
        for rel in _BASELINE_LINES:
            self.assertTrue((_PLATFORM_ROOT / rel).is_file(), f"expected file missing: {rel}")

    def test_no_offending_matches_in_real_tree(self):
        for rel, baseline in _BASELINE_LINES.items():
            offending = find_offending((_PLATFORM_ROOT / rel).read_text(), baseline)
            self.assertEqual(
                offending,
                [],
                f"{rel}: found inline handler(s) built by unsafe interpolation -- "
                f"candidate/agent TEXT must never be assembled into an HTML attribute; "
                f"use a data-* attribute + a delegated listener instead (see "
                f"_hiringStripClickHandler in department-hq.js). Offending: {offending}",
            )

    def test_baseline_lines_are_still_present_verbatim(self):
        """A baseline that silently stops matching anything is not protecting anything."""
        rel = "tools/department_hq/static/js/department-hq.js"
        text = (_PLATFORM_ROOT / rel).read_text()
        stripped_lines = {ln.strip() for ln in text.splitlines()}
        missing = _BASELINE_LINES[rel] - stripped_lines
        self.assertEqual(missing, set(), f"baseline lines no longer found verbatim in {rel}: {missing}")

    def test_openAgentCreate_null_is_never_flagged(self):
        """The one static, argument-free call in the template must stay clean forever."""
        template = _PLATFORM_ROOT / "tools" / "department_hq" / "templates" / "department_hq.html"
        src = template.read_text()
        self.assertIn('onclick="openAgentCreate(null)"', src, "the roster button's static call moved or changed")
        self.assertEqual(find_offending(src, set()), [], "a static, argument-free handler must never be flagged")


class TestGuardCatchesTheOriginalBug(unittest.TestCase):
    """Proof the guard is not vacuous. Per repair-bay.md: reintroduce the exact defect in
    a COPY (never mutate the live file), show the check FAIL, then show the real tree PASS."""

    def test_guard_trips_when_the_exact_shipped_bug_is_reintroduced(self):
        rel = "tools/department_hq/static/js/department-hq.js"
        real_text = (_PLATFORM_ROOT / rel).read_text()
        baseline = _BASELINE_LINES[rel]

        self.assertEqual(find_offending(real_text, baseline), [], "real tree should be clean before the self-test")

        # The EXACT line that shipped in 0ebcd5717 and was removed in e286cfa0e, appended
        # to an in-memory COPY of the real file's text -- the live file is never touched.
        reintroduced_line = (
            "             + \" <button class='dhq-btn-sm' onclick='openAgentCreate(\" "
            '+ payload + ")\'>Create from this</button></li>";\n'
        )
        vulnerable_copy_text = (
            real_text + "\n// --- reintroduced defect, guard self-test only ---\n" + reintroduced_line
        )

        offending = find_offending(vulnerable_copy_text, baseline)
        self.assertEqual(len(offending), 1, f"expected exactly one offending match, got: {offending}")
        self.assertIn("payload", offending[0][1], "the reintroduced bug's interpolated variable was not flagged")


class TestGuardCatchesTheSwap(unittest.TestCase):
    """THE case a bare count ratchet misses, per the review that required this rewrite:
    delete one existing SAFE handler and add one NEW handler interpolating free text, so
    the total COUNT of matches is unchanged. A count-only check would pass this silently;
    the shape-based check must not."""

    def test_swap_same_count_different_shape_is_caught(self):
        rel = "tools/department_hq/static/js/department-hq.js"
        real_text = (_PLATFORM_ROOT / rel).read_text()
        baseline = _BASELINE_LINES[rel]

        victim = sorted(baseline)[0]  # any one grandfathered safe line
        self.assertIn(victim, real_text, "the chosen victim line is not actually present")

        swapped_text = real_text.replace(victim, "", 1)
        new_dangerous_line = (
            "             + \" <button class='dhq-btn-sm' onclick='openAgentCreate(\" "
            '+ narrativeLikeValue + ")\'>Swapped in</button></li>";\n'
        )
        swapped_text += "\n// --- swap self-test: -1 safe, +1 unsafe, count unchanged ---\n" + new_dangerous_line

        before_count = len([ln for ln in real_text.splitlines() if _HANDLER_START_RE.search(ln.strip())])
        after_count = len([ln for ln in swapped_text.splitlines() if _HANDLER_START_RE.search(ln.strip())])
        self.assertEqual(after_count, before_count, "the swap must keep the total match COUNT unchanged")

        offending = find_offending(swapped_text, baseline)
        self.assertEqual(len(offending), 1, f"the swap-in should be the only offending match, got: {offending}")
        self.assertIn("narrativeLikeValue", offending[0][1])

    def test_guard_catches_the_opposite_quote_direction_when_unsafe(self):
        """onchange="fn(' + x + ')" -- double-quoted attribute, single-quote break."""
        offending = find_offending("onchange=\"updateThing(' + freeTextVar + ')\"\n", set())
        self.assertEqual(len(offending), 1)

    def test_guard_does_not_flag_the_opposite_quote_direction_when_id_shaped(self):
        offending = find_offending("onchange=\"updateThing(' + rowId + ')\"\n", set())
        self.assertEqual(offending, [])

    def test_guard_does_not_flag_a_static_argument_free_handler(self):
        offending = find_offending('<button onclick="openAgentCreate(null)">+ New Agent</button>\n', set())
        self.assertEqual(offending, [], "false positive on a static, argument-free handler")


if __name__ == "__main__":
    unittest.main()
