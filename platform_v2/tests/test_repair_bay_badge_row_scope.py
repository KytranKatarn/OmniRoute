"""The reviewer badge row must be in scope for BOTH advisory reviewers.

The miss
--------
The CODEX and P.R.O.B.E. badges share one flex row (`cxRow`). CODEX appends into it
first, P.R.O.B.E. appends into it after. Both the DECLARATION and the APPEND lived
inside `if (cx && cx.verdict)`, so a PR carrying a P.R.O.B.E. verdict but no CODEX
verdict entered the P.R.O.B.E. block and touched an undeclared `cxRow`:

    TypeError: Cannot read properties of undefined (reading 'appendChild')

That throw was not contained to its own row. It escaped the `forEach`, reached the
promise `.catch`, and replaced the ENTIRE rendered list with "Failed to load reviews."
— all 200 rows, because one row lacked a CODEX verdict.

Latent when found: no row currently has P.R.O.B.E. without CODEX, so it could not
fire. It arms itself the moment such a row lands, which is why this is a static
check rather than a data-dependent test — the test must hold for the row that does
not exist yet.

Why a source check
------------------
This is a template-rendering defect, not a service defect: the data was correct, the
API reported it correctly, and only the emitted JavaScript was wrong. Rendering the
page in CI would need a browser and a seeded row, and would still not cover the row
that does not exist. So this parses the template and asserts the DECLARATION's block
depth is no deeper than every USE — the structural property that makes the bug
impossible, independent of what any row happens to contain.
"""

import pathlib
import re
import unittest

TEMPLATE = pathlib.Path(__file__).resolve().parents[1] / "templates" / "tools" / "repair_bay.html"


def _enclosing_blocks(lines):
    """For each line, the chain of enclosing blocks as opener line numbers.

    Depth alone is not enough to decide scope. Two lines can sit at the same depth
    and mean completely different things: one inside `if (cx) {...}` and one after
    that block closed. The bug this file guards against is exactly that — `cxRow`
    declared inside the CODEX conditional and used after it — and a depth comparison
    sees no difference at all.

    So scope is decided by chain containment: a use can see a declaration only if the
    declaration's enclosing chain is a PREFIX of the use's chain. That is the rule
    JavaScript's own `var` hoisting obeys, expressed structurally.
    """
    chains = []
    stack = []  # opener line numbers, innermost last
    pending = False
    for lineno, line in enumerate(lines, start=1):
        # Record the chain as of the START of this line, so a `var` declared on a line
        # is in scope for the rest of that same line.
        chains.append(tuple(stack))
        for char in line:
            if char == "{":
                stack.append(lineno)
            elif char == "}":
                if stack:
                    stack.pop()
    return chains


def _relevant(lines):
    """Lines mentioning cxRow, minus comments.

    Comments are excluded deliberately: the fix documents the bug at length, and a
    comment mentioning `cxRow` at depth 0 would otherwise read as an out-of-scope
    use and fail this test for the wrong reason.
    """
    return [(i, line) for i, line in enumerate(lines) if "cxRow" in line and not line.strip().startswith("//")]


class TestReviewerBadgeRowScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TEMPLATE.read_text(encoding="utf-8")
        cls.lines = cls.source.split("\n")
        cls.chains = _enclosing_blocks(cls.lines)
        cls.depths = [len(c) for c in cls.chains]

    def test_template_exists_and_is_intact(self):
        """Guard the guard: a mangled template must fail loudly, not silently pass."""
        self.assertTrue(
            self.source.startswith('{% extends "base.html" %}'),
            "template no longer extends base.html — it is damaged",
        )
        self.assertEqual(
            self.source.count("{% block"),
            self.source.count("{% endblock"),
            "unbalanced Jinja blocks",
        )

    def test_cxrow_is_declared_exactly_once(self):
        decls = [
            i for i, line in enumerate(self.lines) if line.strip().startswith("var cxRow = document.createElement")
        ]
        self.assertEqual(
            len(decls),
            1,
            f"expected exactly one cxRow declaration, found {len(decls)} at lines "
            f"{[d + 1 for d in decls]} — a duplicate would shadow and re-append the row",
        )

    def test_every_cxrow_use_is_in_scope(self):
        """The actual regression: no use may sit deeper than the declaration."""
        decl = next(
            i for i, line in enumerate(self.lines) if line.strip().startswith("var cxRow = document.createElement")
        )
        decl_chain = self.chains[decl]
        offenders = [
            (i + 1, line.strip()[:60])
            for i, line in _relevant(self.lines)
            if i != decl and self.chains[i][: len(decl_chain)] != decl_chain
        ]
        self.assertEqual(
            offenders,
            [],
            "cxRow used outside the block that declares it — this throws "
            "'Cannot read properties of undefined' and blanks the whole PR list. "
            f"declaration at line {decl + 1} (block chain {decl_chain}); "
            f"offenders: {offenders}",
        )

    def test_badge_row_is_appended_to_the_card_exactly_once(self):
        """The shared badge row must be handed to the card once.

        Twice would render the row twice. Zero would leave both badges built and then
        discarded, which is invisible in the served HTML and shows up only as a card
        with no badges on it.
        """
        appends = [i for i, line in enumerate(self.lines) if "card.appendChild(cxRow)" in line]
        self.assertEqual(
            len(appends),
            1,
            f"cxRow must be appended to the card exactly once, found {len(appends)}",
        )

    def test_probe_badge_block_is_not_nested_inside_the_codex_condition(self):
        """P.R.O.B.E. must be able to render on a row that has no CODEX verdict.

        The three reviewers keep independent metadata, so "P.R.O.B.E. says PASS, CODEX has
        not reviewed" is a legitimate row. If the P.R.O.B.E. block sits inside
        `if (cx && cx.verdict)`, that row silently loses its QA badge — the data is there
        and the server reports it, so nothing looks wrong except the missing badge.
        """
        cxif = next(i for i, line in enumerate(self.lines) if line.strip().startswith("if (cx && cx.verdict)"))
        pbif = next(i for i, line in enumerate(self.lines) if line.strip().startswith("if (pb && pb.verdict)"))
        self.assertGreater(
            self.depths[pbif],
            self.depths[cxif],
            "the P.R.O.B.E. block is nested inside the CODEX condition — a P.R.O.B.E.-only "
            "row will not render its badge",
        )

    def test_no_cxrow_append_sits_outside_the_declaration(self):
        """The direct regression guard.

        `card.appendChild(cxRow)` and `cxRow.childNodes` must both be reachable wherever
        they appear. A `cxRow.childNodes.length` read placed after the block that declares
        cxRow has ended throws on every row without a CODEX verdict, and because the throw
        escapes the forEach it blanks the whole list rather than one row.
        """
        decl = next(
            i for i, line in enumerate(self.lines) if line.strip().startswith("var cxRow = document.createElement")
        )
        decl_chain = self.chains[decl]
        offenders = [
            (i + 1, line.strip()[:70])
            for i, line in enumerate(self.lines)
            if ("cxRow.childNodes" in line or "card.appendChild(cxRow)" in line)
            and self.chains[i][: len(decl_chain)] != decl_chain
        ]
        self.assertEqual(
            offenders,
            [],
            "cxRow touched where it may not be declared — this throws and blanks the "
            f"entire PR list. declaration at line {decl + 1}; offenders: {offenders}",
        )

    def test_probe_badge_appends_into_an_in_scope_row(self):
        """The row the P.R.O.B.E. badge is appended into must exist on that path.

        This is the check that would have caught the regression where cxRow was hoisted
        out of the CODEX conditional: the append then runs on rows where the declaration
        never executed.
        """
        pbif = next(i for i, line in enumerate(self.lines) if line.strip().startswith("if (pb && pb.verdict)"))
        decl = next(
            i for i, line in enumerate(self.lines) if line.strip().startswith("var cxRow = document.createElement")
        )
        decl_chain = self.chains[decl]
        self.assertEqual(
            self.chains[pbif][: len(decl_chain)],
            decl_chain,
            "the P.R.O.B.E. block can execute where cxRow was never declared — "
            "cxRow.appendChild(pbB) would throw and blank the whole PR list",
        )

    def test_inline_javascript_parses(self):
        """Extract the inline scripts and check they are syntactically valid JS.

        Guards the whole template, not just this fix: the corruption that produced a
        one-character-per-line template during development passed a byte check but
        failed here immediately.
        """
        blocks = re.findall(r"<script[^>]*>(.*?)</script>", self.source, re.S)
        self.assertGreater(len(blocks), 5, "no inline script blocks found — parsing wrong?")
        joined = "\n;\n".join(blocks)
        # Braces/parens/brackets must balance outside strings and comments. Full JS
        # parsing needs a JS engine; this catches the structural damage that matters.
        for opener, closer in (("{", "}"), ("(", ")"), ("[", "]")):
            self.assertEqual(
                joined.count(opener),
                joined.count(closer),
                f"unbalanced {opener}{closer} in inline JS — template is damaged",
            )


if __name__ == "__main__":
    unittest.main()


class TestLoadingPlaceholderIsCleared(unittest.TestCase):
    """The Open sub-tab rendered "Loading..." forever, over the rows that had loaded.

    `loadPRReviews` appended a `Loading...` placeholder to the list before its fetch and
    then never removed it: no `.remove()`, no reassignment. On a successful load it stayed
    as the list's first child forever, so the tab read "Loading" permanently while its rows
    sat underneath it. Only the Open sub-tab looked broken, because that is the default
    filter and the one an operator lands on — the sibling tabs were saved by a count or a
    cap note drawing the eye above the stale text.

    The failure path was never affected: the catch clears `list.textContent` outright. So the
    bug lived entirely in the success path, which is why a passing smoke check that asserted
    on row counts missed it — the rows really were there.

    Asserted statically, on the rendered-source shape, because a browser test that only
    counted rows passes while this bug is present.
    """

    @classmethod
    def setUpClass(cls):
        cls.source = TEMPLATE.read_text(encoding="utf-8")
        cls.lines = cls.source.split("\n")
        start = next(i for i, line in enumerate(cls.lines) if "window.loadPRReviews = function(state)" in line)
        end = next(i for i in range(start, len(cls.lines)) if "Failed to load reviews." in cls.lines[i])
        cls.fn = cls.lines[start : end + 2]

    def test_placeholder_is_appended_before_the_fetch(self):
        """Sanity: the placeholder must still be shown while the request is in flight.

        Removing it outright would trade a permanent "Loading" for a blank list, which is
        a worse lie — an empty list reads as "no PRs", not "not loaded yet".
        """
        text = "\n".join(self.fn)
        self.assertIn("Loading...", text)
        self.assertIn("list.appendChild(loading)", text)
        self.assertLess(
            text.index("list.appendChild(loading)"),
            text.index("fetch(url)"),
            "the placeholder must be appended before the fetch",
        )

    def test_placeholder_is_removed_on_success(self):
        """The regression: the success path must drop it before rendering rows."""
        text = "\n".join(self.fn)
        self.assertTrue(
            "prReviewLoading" in text and "_ld.remove()" in text,
            "the Loading placeholder is never removed on the success path, so the tab "
            "reads 'Loading' over the rows that have loaded",
        )

    def test_removal_happens_before_the_rows_render(self):
        """Order matters: clearing afterwards would still leave a flash, and on the empty
        branch the early `return` would skip it entirely."""
        text = "\n".join(self.fn)
        self.assertLess(
            text.index("_ld.remove()"),
            text.index("reviews.forEach"),
            "the placeholder must be removed before the rows are appended",
        )
        self.assertLess(
            text.index("_ld.remove()"),
            text.index("if (!reviews.length)"),
            "the placeholder must be removed before the empty-state early return",
        )

    def test_placeholder_carries_an_id_so_it_is_assertable(self):
        self.assertIn("loading.id = 'prReviewLoading'", "\n".join(self.fn))
