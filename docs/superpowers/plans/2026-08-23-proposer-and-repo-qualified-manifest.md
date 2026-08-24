# Proposer & Repo-Qualified Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the proposer — the component that reads the four work sources, classifies each item to a lane, and assembles a right-sized manifest the owner can approve — and first close the cross-repo hole in the manifest that would otherwise make per-repo authority a fiction.

**Architecture:** Five tasks, in dependency order. Task 1 makes a manifest entry a real `(repo, PR)` pair, because `_pr_on_open_window` currently matches on PR number alone and cannot tell archie-platform #48 from archie-code #48. Tasks 2–3 are pure logic (classification) and bounded gathering (per-source caps), kept separate so the brain is testable without a DB. Task 4 assembles a capped manifest. Task 5 schedules it and exposes it to the cockpit. The proposer only ever *proposes*: it writes `planned` windows, never opens one.

**Tech Stack:** Python 3, psycopg2 (`RealDictCursor`), APScheduler (`archie_scheduler` sidecar), Flask, pytest. Postgres migration under `database/migrations/`.

**Spec:** `docs/superpowers/specs/2026-08-23-three-lane-coder-architecture-design.md`

## Global Constraints

- **Safety properties are universal; authority limits are per-actor** (decision #953). Nothing here relaxes a safety gate.
- **The proposer never opens a window and never merges.** It writes `status='planned'` windows only. Opening is the owner's act in the cockpit (Plan 3).
- **Fail closed.** Any lookup error, missing config, or unavailable service yields *fewer* proposed items, never more.
- **Never duplicate a scope list in the platform.** `PLATFORM_SCOPE` lives in archie-code (`archie_engine/scope_guard.py`); the platform has no copy and must not grow one. Callers pass their own prefixes — the `#5002` precedent, whose docstring warns that duplicating the list "would drift, exactly as `.claude/rules/codex-agent.md` drifted from `config/agents/codex.yaml`".
- **Server-side filtering only NARROWS.** It can never grant access. Writes stay gated by `scope_guard` on the engine side.
- **All times UTC in storage** via `services.time_utils.now_utc()`; never `datetime.utcnow()` (`.claude/rules/timezone.md`).
- **Every `CronTrigger` carries `timezone="America/Toronto"`.**
- **No LLM in a gate or alert path.** Classification is deterministic; an LLM may later *rank*, never *authorise*.

## Measured baseline (2026-08-23 — re-measure before trusting)

| Fact | Value | Why it matters |
|---|---|---|
| `unified_tasks` pending | **339** | source volume |
| `improvement_proposals` `status='approved'` | **1,361** (non-archived total 3,045; `archived` 8,378) | a naive proposer would emit thousands |
| `maintenance_windows` rows, ever | **0** | the machinery has never once run |
| `maintenance_window_items` rows, ever | **0** | **no legacy `ref` format — Task 1 needs no backfill** |
| `GITHUB_TOKEN` reach | archie-platform, archie-code, KSO, creed (push+admin); 4 watch repos + KBS **404** | per-repo authority cannot come from token scoping |

⚠️ **The #5002 lesson, which this plan exists to not repeat:** the engine's first in-scope Code Health issue ranked **744** against a fetch limit of **200**, so every cycle no-opped while looking healthy. Rank-then-truncate across a 3,045-row pool reproduces exactly that. Gather **per source, per lane, already filtered**, then cap.

## File Structure

| File | Responsibility |
|---|---|
| `database/migrations/478_manifest_repo.sql` | add `repo` to `maintenance_window_items` |
| `platform_v2/services/maintenance_schedule_service.py` *(modify)* | `add_item(..., repo=)`; `get_manifest` returns it |
| `platform_v2/tools/repair_bay/services/github_service.py` *(modify)* | `_pr_on_open_window(pr_number, repo=)` matches on both |
| `platform_v2/services/lane_classifier.py` **(new)** | PURE: item → lane, tier, reason. No DB, no Flask. |
| `platform_v2/services/proposer_service.py` **(new)** | gather (bounded, per source) → classify → assemble a capped `planned` window |
| `platform_v2/tools/department_hq/jobs.py` *(modify)* | schedule `proposer_draft` |
| `platform_v2/app.py` *(modify)* | `GET /api/internal/proposed-manifest` |
| `platform_v2/tests/test_lane_classifier.py` **(new)** | classifier truth table |
| `platform_v2/tests/test_manifest_repo_scoping.py` **(new)** | the cross-repo hole stays shut |
| `platform_v2/tests/test_proposer_service.py` **(new)** | caps, ordering, fail-closed |

---

### Task 1: A manifest entry is a `(repo, PR)` pair

**Why first:** the spec states "a window opened for one repo grants nothing in another." That is currently **false**. `_pr_on_open_window(pr_number)` matches `str(item["ref"]) == str(pr_number)` and `maintenance_window_items` has no `repo` column, so a window listing archie-platform #48 authorises merging archie-code #48. Same PR-number collision that makes `get_review(46)` return the wrong repo's review. Live severity today is **zero** (0 windows, 0 `coo_window` callers) — which is exactly why it must land *before* Plan 3 wires anything.

**Files:**
- Create: `database/migrations/478_manifest_repo.sql`
- Modify: `platform_v2/services/maintenance_schedule_service.py:107-145`
- Modify: `platform_v2/tools/repair_bay/services/github_service.py:570-603`
- Test: `platform_v2/tests/test_manifest_repo_scoping.py`

**Interfaces:**
- Produces: `add_item(window_id, title, item_type="other", ref=None, added_by="repair_bay", repo=None) -> dict`
- Produces: `_pr_on_open_window(pr_number: int, repo: str = None) -> tuple[bool, str]`
- Produces: `get_manifest(window_id)` rows gain a `repo` key.

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_manifest_repo_scoping.py
"""A manifest entry is a (repo, PR) pair.

Before this, _pr_on_open_window matched on PR number alone, so a window listing
archie-platform #48 also authorised archie-code #48. PR numbers collide across
repos; an authority check keyed on the number alone crosses repo boundaries.
"""
import pytest
from tools.repair_bay.services import github_service as gs

_WINDOW = [{"id": 7}]


def _manifest(rows):
    return lambda window_id: rows


def _patch(monkeypatch, manifest_rows):
    import services.maintenance_schedule_service as mss
    monkeypatch.setattr(mss, "list_windows", lambda status=None, limit=5: _WINDOW)
    monkeypatch.setattr(mss, "get_manifest", _manifest(manifest_rows))


def test_a_window_for_one_repo_does_not_authorise_another(monkeypatch):
    _patch(monkeypatch, [{"ref": "48", "repo": "KytranKatarn/archie-platform", "status": "planned"}])
    ok, why = gs._pr_on_open_window(48, repo="KytranKatarn/archie-code")
    assert ok is False
    assert "archie-code" in why or "not on any open window" in why


def test_the_matching_repo_is_authorised(monkeypatch):
    _patch(monkeypatch, [{"ref": "48", "repo": "KytranKatarn/archie-platform", "status": "planned"}])
    ok, _ = gs._pr_on_open_window(48, repo="KytranKatarn/archie-platform")
    assert ok is True


def test_a_legacy_item_with_no_repo_is_refused_not_assumed(monkeypatch):
    """FAIL CLOSED. An entry that predates repo qualification names no repo, so it
    authorises nothing. Treating a NULL repo as 'the default repo' would silently
    re-open the very hole this closes."""
    _patch(monkeypatch, [{"ref": "48", "repo": None, "status": "planned"}])
    ok, _ = gs._pr_on_open_window(48, repo="KytranKatarn/archie-platform")
    assert ok is False


def test_an_already_deployed_item_is_still_refused(monkeypatch):
    _patch(monkeypatch, [{"ref": "48", "repo": "KytranKatarn/archie-platform", "status": "deployed"}])
    ok, why = gs._pr_on_open_window(48, repo="KytranKatarn/archie-platform")
    assert ok is False and "deployed" in why
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_manifest_repo_scoping.py -v`
Expected: FAIL — `_pr_on_open_window() got an unexpected keyword argument 'repo'`.

- [ ] **Step 3: Write the migration**

```sql
-- database/migrations/478_manifest_repo.sql
-- A manifest entry is a (repo, PR) pair. Without this, _pr_on_open_window
-- matches on PR number alone and a window for one repo authorises another.
-- No backfill: maintenance_window_items has 0 rows (measured 2026-08-23), so
-- there is no legacy ref format to preserve. NULL stays meaningful — it means
-- "names no repo", and the matcher refuses it rather than assuming a default.
ALTER TABLE maintenance_window_items
    ADD COLUMN IF NOT EXISTS repo VARCHAR(200);

COMMENT ON COLUMN maintenance_window_items.repo IS
    'owner/name of the repo this manifest entry authorises. NULL authorises nothing.';

CREATE INDEX IF NOT EXISTS idx_mwi_window_repo_ref
    ON maintenance_window_items (window_id, repo, ref);
```

- [ ] **Step 4: Apply the migration**

Run: `docker exec -i archie_database psql -U archie -d archie < database/migrations/478_manifest_repo.sql`
Expected: `ALTER TABLE`, `COMMENT`, `CREATE INDEX`.

- [ ] **Step 5: Thread `repo` through `add_item` and `get_manifest`**

```python
# platform_v2/services/maintenance_schedule_service.py
def add_item(
    window_id: int,
    title: str,
    item_type: str = "other",
    ref: str = None,
    added_by: str = "repair_bay",
    repo: str = None,
) -> dict:
    """Append a fix to a window's manifest.

    Refuses once a window has opened — the owner approved a SPECIFIC list, and
    silently extending it after the fact would make that approval meaningless.

    ``repo`` qualifies ``ref``: PR numbers collide across repos, so an entry
    that names no repo authorises nothing (see _pr_on_open_window).
    """
    with _cursor() as (conn, cur):
        cur.execute("SELECT status FROM maintenance_windows WHERE id = %s", (window_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": f"no such window {window_id}"}
        if row["status"] not in ("planned", "announced"):
            return {
                "ok": False,
                "error": f"window {window_id} is '{row['status']}' — the approved list is frozen",
            }
        cur.execute(
            """INSERT INTO maintenance_window_items
                   (window_id, item_type, ref, title, added_by, repo)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (window_id, item_type, ref, title, added_by, repo),
        )
        item_id = cur.fetchone()["id"]
        if row["status"] == "announced":
            cur.execute(
                "UPDATE maintenance_windows SET status='planned', announced_at=NULL,"
                " updated_at=NOW() WHERE id=%s",
                (window_id,),
            )
    return {"ok": True, "item_id": item_id, "reannounce_required": row["status"] == "announced"}
```

In `get_manifest`, add `repo` to the SELECT column list:

```python
            """SELECT id, item_type, ref, title, added_by, status, notes, repo
                 FROM maintenance_window_items WHERE window_id = %s ORDER BY id""",
```

- [ ] **Step 6: Make the matcher repo-aware**

```python
# platform_v2/tools/repair_bay/services/github_service.py
def _pr_on_open_window(pr_number: int, repo: str = None) -> tuple:
    """Is there an OPEN maintenance window whose manifest contains this (repo, PR)?

    ... (existing docstring preserved) ...

    REPO QUALIFICATION: PR numbers collide across repos. Matching on the number
    alone let a window listing archie-platform #48 authorise archie-code #48.
    An item naming no repo authorises NOTHING — fail closed, never assume the
    default repo, or the hole silently reopens.
    """
    try:
        from services.maintenance_schedule_service import get_manifest, list_windows

        want_repo = (repo or _DEFAULT_REPO or "").strip()
        open_windows = list_windows(status="open", limit=5) or []
        if not open_windows:
            return False, "no maintenance window is open"
        for w in open_windows:
            for item in get_manifest(w["id"]) or []:
                if str(item.get("ref") or "") != str(pr_number):
                    continue
                item_repo = (item.get("repo") or "").strip()
                if not item_repo:
                    return False, (
                        f"PR #{pr_number} is on window {w['id']} but the entry names no repo "
                        f"— refusing (a repo-less entry authorises nothing)"
                    )
                if item_repo != want_repo:
                    return False, (
                        f"PR #{pr_number} on window {w['id']} is for {item_repo}, "
                        f"not {want_repo} — a window for one repo grants nothing in another"
                    )
                if (item.get("status") or "planned") != "planned":
                    return False, f"PR #{pr_number} already '{item.get('status')}' on window {w['id']}"
                return True, f"on the manifest of open window {w['id']} for {item_repo}"
        return False, f"PR #{pr_number} is not on any open window's approved manifest"
    except Exception as exc:  # noqa: BLE001 - fail closed, always
        return False, f"window check failed ({type(exc).__name__}) — refusing"
```

Then update its call site in `_automerge_governance_ok` to pass the repo it already has in scope.

- [ ] **Step 7: Run tests to verify they pass**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_manifest_repo_scoping.py /app/tests/test_window_scoped_merge.py /app/tests/test_repair_bay_window_manifest.py /app/tests/test_maintenance_window_driver.py -v`
Expected: all PASS. The three pre-existing window suites must stay green — if one fails, a caller still passes positionally where `repo` now sits.

- [ ] **Step 8: Commit**

```bash
git add database/migrations/478_manifest_repo.sql \
        platform_v2/services/maintenance_schedule_service.py \
        platform_v2/tools/repair_bay/services/github_service.py \
        platform_v2/tests/test_manifest_repo_scoping.py
git commit -m "fix(governance): a manifest entry is a (repo, PR) pair (#380)"
```

---

### Task 2: The lane classifier (pure logic)

**Why pure:** this is the decision the whole design rests on, and it must be testable without a DB, GitHub, or a Flask app — the same reason `welfare_load` and `verdict_refusal` are pure.

**Files:**
- Create: `platform_v2/services/lane_classifier.py`
- Test: `platform_v2/tests/test_lane_classifier.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `classify(item: dict, lane_prefixes: dict) -> dict` returning
  `{"lane": "claude"|"codex"|"engine"|None, "tier": int, "reason": str}`.
  `lane == None` means *no lane may take this* — the caller drops it.
- Produces: `KERNEL_PATTERNS: tuple[str, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_lane_classifier.py
"""Which lane may take an item, and at what tier.

Deterministic on purpose: this feeds an authority decision, and no LLM belongs
in a gate path. An LLM may later RANK candidates; it must never AUTHORISE one.
"""
from services.lane_classifier import classify, KERNEL_PATTERNS

# The caller passes its own prefixes — the platform must never hold a second
# copy of PLATFORM_SCOPE (#5002: duplicating a scope list is how it drifts).
LANES = {
    "codex": ("platform_v2/tools/fitness/", "platform_v2/tools/therapy/"),
    "engine": ("platform_v2/", "ai_bridge/", "scripts/", "docs/"),
}


def test_kernel_paths_go_to_no_autonomous_lane():
    """An actor that can rewrite the rules binding it is not governed (#953)."""
    for path in ("platform_v2/services/agent_service.py",
                 "platform_v2/tools/department_hq/services/department_dispatcher.py",
                 "platform_v2/tools/repair_bay/services/github_service.py"):
        out = classify({"file_path": path, "title": "x"}, LANES)
        assert out["lane"] is None, path
        assert "kernel" in out["reason"].lower()


def test_a_narrow_module_prefers_codex():
    out = classify({"file_path": "platform_v2/tools/fitness/routes.py", "title": "x"}, LANES)
    assert out["lane"] == "codex"


def test_platform_wide_work_goes_to_the_engine():
    out = classify({"file_path": "ai_bridge/agent_loop.py", "title": "x"}, LANES)
    assert out["lane"] == "engine"


def test_an_item_with_no_path_is_unassigned_not_guessed():
    """No path means we cannot prove it is in scope. Fail closed."""
    out = classify({"file_path": None, "title": "something vague"}, LANES)
    assert out["lane"] is None
    assert "no path" in out["reason"].lower()


def test_a_path_outside_every_lane_is_unassigned():
    out = classify({"file_path": "standalone/media_hub/app.py", "title": "x"}, LANES)
    assert out["lane"] is None


def test_tier_never_exceeds_two_for_an_autonomous_lane():
    """Tier 3 is the owner's and is auto-merged by nobody."""
    for path in ("platform_v2/tools/fitness/routes.py", "ai_bridge/agent_loop.py"):
        assert classify({"file_path": path, "title": "x"}, LANES)["tier"] <= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_lane_classifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.lane_classifier'`.

- [ ] **Step 3: Write the implementation**

```python
# platform_v2/services/lane_classifier.py
"""Which lane may take a work item — pure, deterministic, no I/O.

Deliberately not an LLM. This feeds an authority decision, and decision #953
makes safety properties universal: a gate must be reproducible and auditable.
An LLM may later rank candidates for usefulness; it must never authorise one.

The caller passes lane prefixes. This module holds NO copy of PLATFORM_SCOPE —
that lives in archie-code (archie_engine/scope_guard.py) and duplicating it
here is precisely the drift #5002 warns about.
"""

# Blocked for EVERY autonomous lane, including A.R.C.H.I.E.'s. This code
# enforces every other rule — including which lane runs and what gets approved.
KERNEL_PATTERNS: tuple = (
    "agent_service.py",
    "department_dispatcher.py",
    "repair_bay/services/github_service.py",
    "repair_bay/services/pr_review_service.py",
    "scripts/check_agent_single_writer.py",
    "scripts/agents/",
    "scripts/backup/",
    "scripts/dr/",
    "database/migrations/",
    ".github/",
    ".git/",
    "secrets/",
    "docker-compose",
    "Dockerfile",
)

_MAX_AUTONOMOUS_TIER = 2


def _is_kernel(path: str) -> bool:
    return any(pat in path for pat in KERNEL_PATTERNS)


def classify(item: dict, lane_prefixes: dict) -> dict:
    """Return {"lane", "tier", "reason"} for one work item.

    lane is None when no autonomous lane may take it — the caller drops it
    rather than escalating, because escalation is the owner's decision.
    """
    path = (item.get("file_path") or "").strip()
    if not path:
        return {"lane": None, "tier": 0,
                "reason": "no path — cannot prove it is in scope, so no lane may take it"}

    if _is_kernel(path):
        return {"lane": None, "tier": 0,
                "reason": f"governance kernel ({path}) — blocked for every autonomous lane (#953)"}

    # Narrowest lane first: prefer the most constrained actor that can do the job.
    for lane in ("codex", "engine"):
        for prefix in lane_prefixes.get(lane, ()):
            if path.startswith(prefix):
                return {"lane": lane, "tier": min(2, _MAX_AUTONOMOUS_TIER),
                        "reason": f"{path} is under {lane} prefix {prefix}"}

    return {"lane": None, "tier": 0,
            "reason": f"{path} is outside every configured lane prefix"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_lane_classifier.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/lane_classifier.py platform_v2/tests/test_lane_classifier.py
git commit -m "feat(proposer): deterministic lane classifier (#380)"
```

---

### Task 3: Bounded, per-source candidate gathering

**Why bounded per source:** measured pools are 339 pending tasks and 3,045 live proposals. `#5002` records what a global rank-then-truncate does: the engine's first in-scope issue ranked **744** against a fetch limit of **200**, so every cycle no-opped while appearing healthy. Gather per source with its own cap.

**Files:**
- Create: `platform_v2/services/proposer_service.py` (gathering half)
- Test: `platform_v2/tests/test_proposer_service.py`

**Interfaces:**
- Consumes: `lane_classifier.classify`.
- Produces: `gather_candidates(lane_prefixes: dict, per_source_cap: int = 25) -> list[dict]`, each candidate `{"source", "ref", "title", "file_path", "lane", "tier", "reason"}`.

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_proposer_service.py
"""Gathering is bounded PER SOURCE, and unassignable items never survive."""
import services.proposer_service as ps

LANES = {"codex": ("platform_v2/tools/fitness/",), "engine": ("platform_v2/", "ai_bridge/")}


def test_each_source_is_capped_independently(monkeypatch):
    """A global cap lets one noisy source crowd out every other (#5002)."""
    many = [{"id": i, "title": f"t{i}", "file_path": "ai_bridge/x.py"} for i in range(500)]
    monkeypatch.setattr(ps, "_fetch_tasks", lambda limit: many[:limit])
    monkeypatch.setattr(ps, "_fetch_proposals", lambda limit: many[:limit])
    monkeypatch.setattr(ps, "_fetch_code_issues", lambda limit, prefixes: many[:limit])
    out = ps.gather_candidates(LANES, per_source_cap=10)
    for src in ("unified_task", "proposal", "code_issue"):
        assert len([c for c in out if c["source"] == src]) <= 10


def test_kernel_items_are_dropped_before_the_manifest(monkeypatch):
    monkeypatch.setattr(ps, "_fetch_tasks",
                        lambda limit: [{"id": 1, "title": "k",
                                        "file_path": "platform_v2/services/agent_service.py"}])
    monkeypatch.setattr(ps, "_fetch_proposals", lambda limit: [])
    monkeypatch.setattr(ps, "_fetch_code_issues", lambda limit, prefixes: [])
    assert ps.gather_candidates(LANES) == []


def test_a_failing_source_yields_fewer_items_never_an_exception(monkeypatch):
    """Fail closed: one broken source must not take the whole proposer down."""
    def boom(limit):
        raise RuntimeError("db down")
    monkeypatch.setattr(ps, "_fetch_tasks", boom)
    monkeypatch.setattr(ps, "_fetch_proposals",
                        lambda limit: [{"id": 2, "title": "ok", "file_path": "ai_bridge/y.py"}])
    monkeypatch.setattr(ps, "_fetch_code_issues", lambda limit, prefixes: [])
    out = ps.gather_candidates(LANES)
    assert [c["source"] for c in out] == ["proposal"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_proposer_service.py -v`
Expected: FAIL — `No module named 'services.proposer_service'`.

- [ ] **Step 3: Write the gathering half**

```python
# platform_v2/services/proposer_service.py
"""Assemble a PROPOSED manifest of work for the owner to approve.

Never opens a window and never merges. It writes 'planned' windows only;
opening one is the owner's act in the cockpit.

Gathering is bounded PER SOURCE. #5002: the engine once ranked its first
in-scope issue at 744 against a fetch limit of 200, so every cycle no-opped
while looking healthy. A global cap across a 3,045-row pool repeats that.
"""
import logging

from database import get_db_cursor
from services.lane_classifier import classify

log = logging.getLogger(__name__)

DEFAULT_PER_SOURCE_CAP = 25


def _fetch_tasks(limit: int) -> list:
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, title, description FROM unified_tasks
                WHERE status = 'pending' ORDER BY priority DESC NULLS LAST, id LIMIT %s""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def _fetch_proposals(limit: int) -> list:
    """⚠️ improvement_proposals has NO file_path column — verified 2026-08-23.

    It carries `module_name`. Selecting a `file_path` here raises UndefinedColumn,
    which _safe() swallows, leaving this source permanently and silently empty —
    the same "unmonitored while appearing monitored" shape as the phantom
    `backups` table (#2366). Synthesize the path from module_name instead; a row
    with no module_name gets None and the classifier drops it (fail closed).
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, title, module_name FROM improvement_proposals
                WHERE status = 'approved' ORDER BY id DESC LIMIT %s""",
            (limit,),
        )
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            mod = (d.get("module_name") or "").strip()
            d["file_path"] = f"platform_v2/tools/{mod}/" if mod else None
            rows.append(d)
        return rows


def _fetch_code_issues(limit: int, prefixes: tuple) -> list:
    """Delegates to the existing server-side scope filter (#5002) — it only ever
    NARROWS, and the caller supplies its own prefixes so there is one source of
    truth for scope."""
    from services import scan_service

    return scan_service.get_issues(
        status="open", limit=limit, auto_fixable=True, path_prefixes=list(prefixes) or None
    )


def _safe(fn, *args) -> list:
    """One broken source must not take the whole proposer down. Fewer items, never an error."""
    try:
        return fn(*args) or []
    except Exception as exc:  # noqa: BLE001 - fail closed
        log.warning("proposer: source %s failed (%s) — skipping", getattr(fn, "__name__", fn), exc)
        return []


def gather_candidates(lane_prefixes: dict, per_source_cap: int = DEFAULT_PER_SOURCE_CAP) -> list:
    all_prefixes = tuple(p for prefixes in lane_prefixes.values() for p in prefixes)
    sources = (
        ("unified_task", _safe(_fetch_tasks, per_source_cap)),
        ("proposal", _safe(_fetch_proposals, per_source_cap)),
        ("code_issue", _safe(_fetch_code_issues, per_source_cap, all_prefixes)),
    )

    out = []
    for source, rows in sources:
        for row in rows[:per_source_cap]:
            verdict = classify(row, lane_prefixes)
            if not verdict["lane"]:
                continue
            out.append({
                "source": source,
                "ref": str(row.get("id")),
                "title": (row.get("title") or "")[:200],
                "file_path": row.get("file_path"),
                "lane": verdict["lane"],
                "tier": verdict["tier"],
                "reason": verdict["reason"],
            })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_proposer_service.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/proposer_service.py platform_v2/tests/test_proposer_service.py
git commit -m "feat(proposer): bounded per-source candidate gathering (#380)"
```

---

### Task 4: Assemble a capped `planned` manifest

**Files:**
- Modify: `platform_v2/services/proposer_service.py`
- Test: `platform_v2/tests/test_proposer_service.py` (append)

**Interfaces:**
- Consumes: `gather_candidates`, `maintenance_schedule_service.schedule_window` / `add_item` (now repo-aware from Task 1).
- Produces: `propose_manifest(lane_prefixes, repo, max_items=15, dry_run=False) -> dict`
  returning `{"ok", "window_id"|None, "items": [...], "dropped": int, "dry_run": bool}`.

- [ ] **Step 1: Write the failing test**

```python
# append to platform_v2/tests/test_proposer_service.py
def test_manifest_is_capped_and_reports_what_it_dropped(monkeypatch):
    """Silent truncation reads as 'covered everything'. Always report the drop."""
    cands = [{"source": "proposal", "ref": str(i), "title": f"t{i}",
              "file_path": "ai_bridge/x.py", "lane": "engine", "tier": 1,
              "reason": "r"} for i in range(40)]
    monkeypatch.setattr(ps, "gather_candidates", lambda p, per_source_cap=25: cands)
    out = ps.propose_manifest(LANES, repo="KytranKatarn/archie-platform", max_items=15, dry_run=True)
    assert len(out["items"]) == 15
    assert out["dropped"] == 25
    assert out["window_id"] is None and out["dry_run"] is True


def test_every_manifest_item_carries_its_repo(monkeypatch):
    """Task 1 made repo mandatory for authority; an entry without one authorises nothing."""
    cands = [{"source": "proposal", "ref": "1", "title": "t", "file_path": "ai_bridge/x.py",
              "lane": "engine", "tier": 1, "reason": "r"}]
    monkeypatch.setattr(ps, "gather_candidates", lambda p, per_source_cap=25: cands)
    out = ps.propose_manifest(LANES, repo="KytranKatarn/archie-platform", dry_run=True)
    assert all(i["repo"] == "KytranKatarn/archie-platform" for i in out["items"])


def test_an_empty_candidate_set_creates_no_window(monkeypatch):
    """A window with nothing on it is noise the owner has to dismiss."""
    monkeypatch.setattr(ps, "gather_candidates", lambda p, per_source_cap=25: [])
    out = ps.propose_manifest(LANES, repo="KytranKatarn/archie-platform")
    assert out["ok"] is True and out["window_id"] is None and out["items"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_proposer_service.py -k manifest -v`
Expected: FAIL — `module 'services.proposer_service' has no attribute 'propose_manifest'`.

- [ ] **Step 3: Write the implementation**

```python
# append to platform_v2/services/proposer_service.py
DEFAULT_MAX_ITEMS = 15


def propose_manifest(lane_prefixes: dict, repo: str, max_items: int = DEFAULT_MAX_ITEMS,
                     dry_run: bool = False) -> dict:
    """Draft a PLANNED window the owner can review, trim and approve.

    Never opens the window. add_item() refuses to extend a manifest once open,
    so the list must be right-sized BEFORE approval — hence the cap, and hence
    reporting what was dropped instead of truncating silently.
    """
    candidates = gather_candidates(lane_prefixes)
    chosen = candidates[:max_items]
    dropped = len(candidates) - len(chosen)
    items = [dict(c, repo=repo) for c in chosen]

    if dropped:
        log.info("proposer: proposing %d item(s), %d dropped by the cap", len(items), dropped)

    if not items:
        return {"ok": True, "window_id": None, "items": [], "dropped": dropped, "dry_run": dry_run}
    if dry_run:
        return {"ok": True, "window_id": None, "items": items, "dropped": dropped, "dry_run": True}

    from services.maintenance_schedule_service import add_item, schedule_window
    from services.time_utils import now_utc

    win = schedule_window(
        now_utc(),
        reason=f"Proposed by A.R.C.H.I.E. — {len(items)} item(s) for {repo}",
        created_by="proposer",
    )
    window_id = win["id"] if isinstance(win, dict) else win
    for it in items:
        add_item(window_id, title=it["title"], item_type=it["source"],
                 ref=it["ref"], added_by="proposer", repo=it["repo"])
    return {"ok": True, "window_id": window_id, "items": items, "dropped": dropped, "dry_run": False}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_proposer_service.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/proposer_service.py platform_v2/tests/test_proposer_service.py
git commit -m "feat(proposer): assemble a capped planned manifest (#380)"
```

---

### Task 5: Schedule it, and expose it to the cockpit

**Why scheduled:** the spec's non-negotiable is that dormancy is what killed both other lanes. A proposer that only runs when the owner opens the cockpit is dormant by construction whenever he does not.

**Files:**
- Modify: `platform_v2/tools/department_hq/jobs.py`
- Modify: `platform_v2/app.py` (beside `/api/internal/lane-liveness`)
- Test: `platform_v2/tests/test_proposer_service.py` (append)

**Interfaces:**
- Consumes: `propose_manifest`.
- Produces: job `proposer_draft`; `GET /api/internal/proposed-manifest`.

- [ ] **Step 1: Write the failing test**

```python
# append to platform_v2/tests/test_proposer_service.py
def test_the_proposer_is_registered_as_a_scheduled_job():
    """A proposer nobody schedules is exactly the dormancy this design exists to fix."""
    import pathlib
    text = pathlib.Path("/app/tools/department_hq/jobs.py").read_text()
    assert "proposer_draft" in text, "proposer is never scheduled"
    assert "propose_manifest" in text, "scheduled job does not call the proposer"


def test_the_proposed_manifest_endpoint_is_on_the_internal_key_surface():
    """The cockpit is a separate container: it carries the internal key, not a session.
    #2781 shipped exactly this bug — a registry gated so its only consumer 401'd."""
    import pathlib
    text = pathlib.Path("/app/app.py").read_text()
    assert "/api/internal/proposed-manifest" in text
    idx = text.index("/api/internal/proposed-manifest")
    window = text[idx: idx + 1200]
    assert "login_required" not in window, "internal route must not be session-gated"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_proposer_service.py -k "scheduled or endpoint" -v`
Expected: FAIL — `proposer is never scheduled`.

- [ ] **Step 3: Register the job**

⚠️ **jobs.py has NO module-level scheduler** (verified 2026-08-23). Registration happens INSIDE
`register_department_hq_jobs(scheduler, flask_app)` at line 1069, and `scheduler.add_job` takes
`trigger=` as a **keyword** (see line 1259). A module-level `scheduler.add_job(...)` raises
`NameError`; a positional trigger is a `TypeError`. Either way the job never registers and the
proposer is dormant while looking healthy — the exact failure this design exists to prevent.

```python
# platform_v2/tools/department_hq/jobs.py — INSIDE register_department_hq_jobs()
def proposer_draft():
    """Draft a proposed manifest for the owner. Never opens a window."""
    from services.proposer_service import propose_manifest

    lane_prefixes = {
        "codex": ("platform_v2/tools/fitness/", "platform_v2/tools/therapy/",
                  "platform_v2/tools/faith/", "platform_v2/tools/brainstorm/",
                  "platform_v2/tools/doc/", "platform_v2/tools/family_tree/"),
        "engine": ("platform_v2/", "ai_bridge/", "scripts/", "docs/"),
    }
    return propose_manifest(lane_prefixes, repo="KytranKatarn/archie-platform", dry_run=True)


    scheduler.add_job(
        proposer_draft,
        trigger=CronTrigger(hour=7, minute=0, timezone="America/Toronto"),
        id="proposer_draft",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
```

⚠️ `dry_run=True` deliberately: until Plan 3's cockpit surface exists there is nowhere to review a real window, and creating unreviewable windows is how `maintenance_windows` fills with noise. Flip to `dry_run=False` in Plan 3, in the same PR that adds the review screen.

- [ ] **Step 4: Add the read endpoint**

```python
# platform_v2/app.py — beside /api/internal/lane-liveness
@app.route("/api/internal/proposed-manifest", methods=["GET"])
@_require_internal_key
def internal_proposed_manifest():
    """What the proposer would put in front of the owner right now.

    Internal-key surface, not session-gated: the cockpit is a separate container
    and carries the key, not a session (#2781).
    """
    from services.proposer_service import propose_manifest

    lane_prefixes = {
        "codex": ("platform_v2/tools/fitness/", "platform_v2/tools/therapy/",
                  "platform_v2/tools/faith/", "platform_v2/tools/brainstorm/",
                  "platform_v2/tools/doc/", "platform_v2/tools/family_tree/"),
        "engine": ("platform_v2/", "ai_bridge/", "scripts/", "docs/"),
    }
    repo = request.args.get("repo", "KytranKatarn/archie-platform")
    try:
        return jsonify(propose_manifest(lane_prefixes, repo=repo, dry_run=True))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(type(exc).__name__), "items": []}), 200
```

- [ ] **Step 5: Restart and verify through the running process**

```bash
docker compose restart archie_platform archie_scheduler
docker exec archie_platform python3 -c "
import sys, json; sys.path.insert(0,'/app')
from services.proposer_service import propose_manifest
print(json.dumps(propose_manifest({'engine': ('ai_bridge/',)}, repo='KytranKatarn/archie-platform', dry_run=True))[:400])"
```
Expected: a JSON object with `items` and `dropped`. A merge deploys nothing for volume-mounted hub code — the restart is the deploy step (`.claude/rules/deploy-provenance.md`).

- [ ] **Step 6: Run the full suite**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_proposer_service.py /app/tests/test_lane_classifier.py /app/tests/test_manifest_repo_scoping.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/department_hq/jobs.py platform_v2/app.py \
        platform_v2/tests/test_proposer_service.py
git commit -m "feat(proposer): schedule the draft + internal read endpoint (#380)"
```

---

## After all five tasks

The platform can propose. It cannot yet approve — that is Plan 3 (cockpit manifest surface + flipping `dry_run` to False + wiring `authority='coo_window'`).

Verify end to end:

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_lane_classifier.py \
  /app/tests/test_proposer_service.py /app/tests/test_manifest_repo_scoping.py \
  /app/tests/test_window_scoped_merge.py /app/tests/test_repair_bay_window_manifest.py \
  /app/tests/test_maintenance_window_driver.py -v
```

## Self-review notes

**Spec coverage.** This plan implements spec item 1 ("the proposer — the actual missing brain"). Item 4 (widen `PLATFORM_SCOPE`) is **already done** — archie-code #46 and #48. Items 2, 3 and 5 (cockpit surface, wire `coo_window`, per-repo scopes) are Plans 3 and 4.

**Spec gap found and closed here.** The spec asserts "a window opened for one repo grants nothing in another." That is not true of the code: `_pr_on_open_window` matches on PR number alone and `maintenance_window_items` has no `repo` column. Task 1 makes the assertion true. It is placed first because Plan 3 wires `coo_window` to real merges, and shipping that on a repo-blind manifest would turn a latent bug into a live cross-repo authority leak. Live severity today is zero — 0 windows have ever existed and `coo_window` has 0 production callers.

**Open questions the owner still needs to answer** (spec §Open questions):
1. *Schedule vs on-demand?* Answered here as **both** — daily draft at 07:00 ET plus an on-demand endpoint — because dormancy is the failure this design exists to prevent.
2. *Manifest granularity?* Answered here as **one window per (repo, batch)**, following from Task 1 and from `add_item()` refusing to extend an open window.
3. *Should Lane 2's ceiling stay Tier 1?* **Unanswered — still the owner's.** Nothing here depends on it.
4. *Do the watch repos carry admin on the write token?* **Answered 2026-08-23: no.** Measured with the container's `GITHUB_TOKEN`: push+admin on archie-platform, archie-code, KSO and creed; HTTP 404 on all four watch repos and KBS. ⚠️ Probing this from a host shell measures the *owner's* `gh` credential, which does have admin everywhere — a different identity. See KB #294553.

**Deliberately not built here:** any LLM in the classification path (it feeds an authority decision), any auto-opening of windows, and any deploy step (a merge is not a deploy — every product but the platform is image-baked).
