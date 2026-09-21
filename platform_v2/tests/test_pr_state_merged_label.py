"""A merged PR must be labelled 'merged', and the UI must only offer states we write.

Measured 2026-09-21. `pr_reviews.state` held 2,573 `closed` / 575 `merged` / 4 `open`,
and the newest `merged` row was 2026-08-18 — a value NOTHING in the codebase still
wrote. `sync_closed_prs` writes `'closed'` for everything that leaves GitHub's open
set, merges included, while the Repair Bay filter still offered a MERGED button. So
that button was a frozen archive: populated enough to look healthy, blind to every
merge for a month. The owner merged four PRs, clicked MERGED, saw none of them, and
concluded the GitHub sync was broken. The sync was fine; the vocabulary was not.

The second test here is the one that would have caught it: it compares what the UI
OFFERS against what the writer can PRODUCE. Neither side is wrong on its own — the
defect only exists in the gap between them, which is invisible to any test that
exercises one side.
"""

from __future__ import annotations

import os
import re

import pytest

from tools.repair_bay.services import github_service as gh

TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates",
    "tools",
    "repair_bay.html",
)
SERVICE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools",
    "repair_bay",
    "services",
    "pr_review_service.py",
)


class TestPrWasMerged:
    """One API call, and `None` must never be mistaken for an answer."""

    def _patch(self, monkeypatch, ok, data):
        calls = []

        def fake(path, params=None, timeout=15):
            calls.append(path)
            return ok, data

        monkeypatch.setattr(gh, "_api_get", fake)
        return calls

    def test_merged_true_flag(self, monkeypatch):
        self._patch(monkeypatch, True, {"state": "closed", "merged": True})
        assert gh.pr_was_merged(1, repo="o/r") is True

    def test_merged_at_timestamp_alone_counts(self, monkeypatch):
        # Some cached/list payloads carry only the timestamp, not the boolean.
        self._patch(monkeypatch, True, {"state": "closed", "merged_at": "2026-09-21T11:34:40Z"})
        assert gh.pr_was_merged(1, repo="o/r") is True

    def test_closed_unmerged_is_false(self, monkeypatch):
        self._patch(monkeypatch, True, {"state": "closed", "merged": False, "merged_at": None})
        assert gh.pr_was_merged(1, repo="o/r") is False

    def test_open_pr_is_false(self, monkeypatch):
        self._patch(monkeypatch, True, {"state": "open"})
        assert gh.pr_was_merged(1, repo="o/r") is False

    def test_unreadable_is_None_not_False(self, monkeypatch):
        # Load-bearing: the caller keeps 'closed' on None. Returning False would be
        # the same outcome today, but it would be an ASSERTION where we have none.
        self._patch(monkeypatch, False, {})
        assert gh.pr_was_merged(1, repo="o/r") is None

    def test_missing_state_is_None(self, monkeypatch):
        self._patch(monkeypatch, True, {"title": "no state field"})
        assert gh.pr_was_merged(1, repo="o/r") is None

    def test_exactly_one_api_call(self, monkeypatch):
        calls = self._patch(monkeypatch, True, {"state": "closed", "merged": True})
        gh.pr_was_merged(7, repo="own/repo")
        assert calls == ["/repos/own/repo/pulls/7"], calls

    def test_repo_aware(self, monkeypatch):
        # A hardcoded REPO_FULL is wrong for the non-default repos F.O.R.G.E. reviews.
        calls = self._patch(monkeypatch, True, {"state": "open"})
        gh.pr_was_merged(3, repo="KytranKatarn/archie-code")
        assert "KytranKatarn/archie-code" in calls[0]


def _source(path):
    with open(path, "r") as fh:
        return fh.read()


class TestFilterVocabularyMatchesWriter:
    """THE guard. What the UI offers must be something the writer can produce."""

    def test_ui_filter_states_are_all_writable(self):
        html = _source(TEMPLATE)
        # Anchor INSIDE setPRFilter — a bare `[...].forEach` search matches several
        # unrelated lists in this template (the first hit was a 'pending' one).
        fn = re.search(r"window\.setPRFilter\s*=\s*function.*?\n\};", html, re.S)
        assert fn, "could not locate window.setPRFilter in repair_bay.html"
        m = re.search(r"\[((?:'[a-z]+',?\s*)+)\]\.forEach", fn.group(0))
        assert m, "could not locate the state-filter list inside setPRFilter"
        offered = {v for v in re.findall(r"'([a-z]+)'", m.group(1))}
        # 'all' is a UI-only sentinel — loadPRReviews omits the param for it.
        offered.discard("all")
        assert offered == {"open", "merged", "closed"}, offered

        svc = _source(SERVICE)
        # 'closed' and 'merged' must be written as literals by sync_closed_prs.
        for value in ("closed", "merged"):
            assert re.search(rf"state\s*=\s*'{value}'", svc), (
                f"the UI offers a '{value}' filter but nothing in pr_review_service "
                f"writes state = '{value}' — that filter can only ever show history"
            )

    def test_open_is_reachable_via_the_github_passthrough(self):
        # 'open' is not a literal: the poll upsert copies GitHub's own state.
        svc = _source(SERVICE)
        assert (
            "state          = EXCLUDED.state" in svc
        ), "the upsert no longer passes GitHub's state through, so 'open' may be unreachable"

    def test_sync_closed_prs_probes_before_labelling(self):
        svc = _source(SERVICE)
        assert "pr_was_merged" in svc, "sync_closed_prs must classify merged-vs-closed"
        assert "_MAX_MERGE_PROBES" in svc, "the probe must be bounded (#5707 mass-departure)"
        # The departed set must be captured BEFORE the close UPDATE, or the rows
        # become indistinguishable from historical closed rows.
        i_select = svc.index("SELECT pr_number FROM pr_reviews")
        i_update = svc.index("UPDATE pr_reviews\n                SET state = 'closed'")
        assert i_select < i_update, "the departed-set SELECT must precede the close UPDATE"

    def test_merged_upgrade_only_touches_rows_it_just_closed(self):
        svc = _source(SERVICE)
        m = re.search(r"UPDATE pr_reviews SET state = 'merged'.*?\"\"\"", svc, re.S)
        assert m, "merged upgrade not found"
        block = m.group(0)
        # Without `state = 'closed'` this would rewrite historical rows too.
        assert "state = 'closed'" in block, "the upgrade must be scoped to just-closed rows"
        assert "pr_number = ANY" in block, "the upgrade must be scoped to the probed set"
