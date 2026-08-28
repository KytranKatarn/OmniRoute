"""Repair Bay's advisory maintenance-window manifest (#5247a).

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT.

Repair Bay's self-heal pipeline ENDS AT PR CREATION — there is no automated
deploy step (verified: no merge_pr/auto_merge anywhere in forge_self_heal.py or
audit_pipeline.py). So the manifest is a list of fixes AWAITING A HUMAN MERGE,
shown to the owner ahead of the window. It never merges anything.

THE PROPERTY THAT MATTERS MOST: it must never CREATE a window.
`next_window(create_if_missing=True)` would schedule one whenever a self-heal PR
appears, and maintenance_window_driver eventually OPENS scheduled windows — and
opening one ARMS DR SUPPRESSION. A reporting feature that silently disarms DR
because a code fix got a PR is a safety regression, not a nicety.

Second property: bookkeeping must never fail a PR that already exists.
"""

import pytest

pytest.importorskip("psycopg2")

from tests.dbguard import import_or_skip  # noqa: E402
from tests.modstub import install_module_stub  # noqa: E402

try:
    from tools.repair_bay.services import forge_pipeline as fp
except Exception as exc:  # pragma: no cover
    import_or_skip(exc, "forge_pipeline")


class _FakeSchedule:
    def __init__(self, window=None, add_result=None, raise_on_add=False):
        self.window = window
        self.add_result = add_result or {"ok": True, "id": 1}
        self.raise_on_add = raise_on_add
        self.next_window_kwargs = []
        self.added = []

    def next_window(self, **kw):
        self.next_window_kwargs.append(kw)
        return self.window

    def add_item(self, window_id, **kw):
        if self.raise_on_add:
            raise RuntimeError("db exploded")
        self.added.append((window_id, kw))
        return self.add_result


def _install(monkeypatch, fake):
    install_module_stub(
        monkeypatch,
        "services.maintenance_schedule_service",
        next_window=fake.next_window,
        add_item=fake.add_item,
    )
    return fake


_PROPOSAL = {"id": 42, "title": "Fix unbounded retry in dispatcher"}
_PR = {"pr_number": 2499, "pr_url": "https://github.com/x/y/pull/2499"}


# ------------------------------------------------------- never creates one ---
def test_never_creates_a_window(monkeypatch):
    """THE ONE THAT MATTERS. Opening a window arms DR suppression, so a PR must
    never cause one to be scheduled."""
    fake = _install(monkeypatch, _FakeSchedule(window={"id": 7}))
    fp._record_on_next_window(_PROPOSAL, _PR)
    assert fake.next_window_kwargs, "next_window was never called"
    for kw in fake.next_window_kwargs:
        assert kw.get("create_if_missing") is False, (
            "create_if_missing=True would schedule a window per self-heal PR, and the "
            "driver opens scheduled windows — which ARMS DR SUPPRESSION (#5247a)"
        )


def test_no_window_scheduled_is_a_quiet_noop(monkeypatch):
    fake = _install(monkeypatch, _FakeSchedule(window=None))
    fp._record_on_next_window(_PROPOSAL, _PR)
    assert fake.added == [], "queued an item with no window scheduled"


# --------------------------------------------------------------- happy path ---
def test_queues_the_pr_on_the_next_window(monkeypatch):
    fake = _install(monkeypatch, _FakeSchedule(window={"id": 7}))
    fp._record_on_next_window(_PROPOSAL, _PR)
    assert len(fake.added) == 1
    wid, kw = fake.added[0]
    assert wid == 7
    assert "2499" in kw["title"], "the PR number must be visible in the manifest line"
    assert kw["ref"] == "2499"
    assert kw["item_type"] == "repair_bay_pr"
    assert kw["added_by"] == "repair_bay"


def test_title_is_bounded(monkeypatch):
    """A runaway proposal title must not blow up the manifest line."""
    fake = _install(monkeypatch, _FakeSchedule(window={"id": 7}))
    fp._record_on_next_window({"id": 1, "title": "x" * 5000}, _PR)
    assert len(fake.added[0][1]["title"]) < 200


def test_falls_back_to_issue_type_then_a_default(monkeypatch):
    fake = _install(monkeypatch, _FakeSchedule(window={"id": 7}))
    fp._record_on_next_window({"id": 1, "issue_type": "SQL_INJECTION_RISK"}, _PR)
    assert "SQL_INJECTION_RISK" in fake.added[0][1]["title"]
    fake.added.clear()
    fp._record_on_next_window({"id": 1}, _PR)
    assert "self-heal fix" in fake.added[0][1]["title"]


# ----------------------------------------------------- never breaks the PR ---
def test_add_item_refusal_is_logged_not_raised(monkeypatch):
    """add_item refuses once a window has OPENED — the owner approved a specific
    list. That refusal is expected, not an error."""
    _install(monkeypatch, _FakeSchedule(window={"id": 7}, add_result={"ok": False, "error": "window is 'open'"}))
    fp._record_on_next_window(_PROPOSAL, _PR)  # must not raise


def test_exception_never_propagates(monkeypatch):
    """The PR already exists. Bookkeeping must never turn that into a failure."""
    _install(monkeypatch, _FakeSchedule(window={"id": 7}, raise_on_add=True))
    fp._record_on_next_window(_PROPOSAL, _PR)  # must not raise


def test_missing_service_never_propagates(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "services.maintenance_schedule_service", None)
    fp._record_on_next_window(_PROPOSAL, _PR)  # must not raise


# ------------------------------------------------------------ wiring check ---
def test_hook_is_called_after_pr_creation_not_before():
    """Guard the call site: it must sit AFTER create_pr succeeds, so a failed PR
    never lands on the manifest."""
    import inspect

    src = inspect.getsource(fp.deploy_via_forge)
    assert "_record_on_next_window" in src, "hook is not wired into deploy_via_forge"
    assert src.index("create_pr(") < src.index(
        "_record_on_next_window"
    ), "manifest hook must run only after the PR is created"


def test_hook_never_merges():
    """This is advisory. If merging ever appears here, the design changed.

    Checks the CODE with the docstring stripped. The first version of this test
    scanned the whole source and failed on its own docstring, which explains WHY
    create_if_missing=True and open_scheduled are dangerous — a guard that matches
    the prose describing the danger, rather than the danger.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(fp._record_on_next_window)))
    fn = tree.body[0]
    if (
        fn.body
        and isinstance(fn.body[0], ast.Expr)
        and isinstance(getattr(fn.body[0], "value", None), ast.Constant)
        and isinstance(fn.body[0].value.value, str)
    ):
        fn.body = fn.body[1:]  # drop the docstring
    code = ast.unparse(fn)

    for forbidden in ("merge_pr", "open_scheduled", "start_window"):
        assert forbidden not in code, f"advisory manifest must not call {forbidden}"
    assert "create_if_missing=False" in code, "must explicitly pass create_if_missing=False"
    assert (
        "create_if_missing=True" not in code
    ), "create_if_missing=True would schedule a window per PR, and opening one arms DR suppression"
