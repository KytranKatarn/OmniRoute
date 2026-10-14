"""The auto-merge path allowlist admits the WTF PRESENTATION layer and nothing server-side (owner decision 2026-10-14).

Runs the REAL ``_automerge_paths_allowed`` with a faked changed-file list, in both directions: the allowlist must admit
templates/CSS/tests/docs, and must still refuse server code, migrations, ingest, data, JS and images. A gate that admits
everything is as broken as one that admits nothing, so the refusals are as load-bearing as the admissions.
"""

import pytest

import tools.repair_bay.services.github_service as gs
import tools.repair_bay.services.pr_review_service as prs

W = "what-the-fact/"


def _allowed(monkeypatch, paths):
    monkeypatch.delenv("FORGE_AUTOMERGE_SAFE_PATHS", raising=False)
    monkeypatch.setattr(gs, "_api_get", lambda *_a, **_k: (True, [{"filename": p} for p in paths]))
    return prs._automerge_paths_allowed(1, prs._DEFAULT_REPO)


@pytest.mark.parametrize(
    "path",
    [
        W + "consumer/templates/elections.html",
        W + "consumer/static/style.css",
        W + "consumer/static/history/atlas.css",
        W + "tests/test_x.py",
        W + "docs/history-atlas-release.md",
        W + "design-handoff/PORT-STATUS.md",
    ],
)
def test_presentation_paths_are_admitted(monkeypatch, path):
    ok, blocking = _allowed(monkeypatch, [path])
    assert ok and blocking == []


@pytest.mark.parametrize(
    "path",
    [
        W + "consumer/routes.py",
        W + "consumer/app.py",
        W + "consumer/history_data.py",
        W + "ingest/run.py",
        W + "migrations/104_fix.sql",
        W + "consumer/data/history/events.json",
        W + "consumer/static/history/atlas.js",
        W + "consumer/static/history/nrcan-1867.svg",
        W + "consumer/static/style.css.map",
        W + "deploy.sh",
        W + "Dockerfile",
        W + "consumer/templates-evil/x.html",
        "what-the-fact-site/consumer/templates/x.html",
        "platform_v2/services/anything.py",
    ],
)
def test_server_side_and_asset_paths_still_need_a_human(monkeypatch, path):
    ok, blocking = _allowed(monkeypatch, [path])
    assert not ok and blocking == [path]


def test_one_blocked_file_blocks_the_whole_pr(monkeypatch):
    ok, blocking = _allowed(monkeypatch, [W + "consumer/templates/a.html", W + "consumer/routes.py"])
    assert not ok and blocking == [W + "consumer/routes.py"]


def test_the_real_atlas_and_cost_prs_stay_human(monkeypatch):
    """#3846-style asset PRs and #3843-style platform PRs must not have become auto-mergeable."""
    assert not _allowed(monkeypatch, [W + "consumer/static/history/nrcan-1870.svg"])[0]
    assert not _allowed(monkeypatch, ["platform_v2/services/codex_broker_client.py"])[0]


def test_existing_safe_paths_still_admitted(monkeypatch):
    assert _allowed(monkeypatch, ["docs/x.md", "platform_v2/tests/test_a.py", ".claude/rules/a.md"])[0]
