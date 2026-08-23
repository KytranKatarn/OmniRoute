# Lane Safety & Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the three coder lanes observable when they go quiet, and bring A.R.C.H.I.E.'s scope and merge authority in line with the approved design — before any new autonomy is built on top.

**Architecture:** Three additions to `archie-platform` (a deterministic liveness observer, its scheduled job, and a read endpoint) and two to `archie-code` (wire the `coo_window` merge authority, widen `PLATFORM_SCOPE` to platform-minus-kernel). Task 4 deliberately RAISES the unattended merge ceiling from Tier 1 to Tier 2, bounded by an owner-approved window (premise corrected during execution — see Task 4); Task 5 widens scope but keeps the governance kernel blocked. Both were explicitly approved by the owner.

**Tech Stack:** Python 3.12, psycopg2 (`database.get_db_cursor`), APScheduler (`ai_bridge/agent_loop.py`), pytest, Flask.

**Spec:** `docs/superpowers/specs/2026-08-23-three-lane-coder-architecture-design.md`

## Global Constraints

- **Two repos, two deploy paths.** Tasks 1–3 are `archie-platform` (`/mnt/archie_brain`), bind-mounted → deploy = `git checkout main && git pull --ff-only` + `docker compose restart archie_platform archie_scheduler`. Tasks 4–5 are `archie-code` (`/mnt/standalone/archie-code`), whose engine runs a `/workspace` git clone that hard-resets to `origin/main` on start → **deploy = merge to archie-code main + `docker compose restart archie_engine`. Editing source or `--build` deploys NOTHING** (KB #293029).
- **Platform tests must run inside the container**: `docker exec -w /app archie_platform python3 -m pytest ...`. On the host they all error at setup on a localhost DB (#5922/#5406).
- **PR size**: keep each task's diff under **9,000 chars** (`git diff main..HEAD | wc -c`) or F.O.R.G.E. silently drops files from review — always the test file first.
- **Never stack PRs.** Each task's branch targets `main` (KB #293018).
- **No LLM in any alert path.** The observer is deterministic, like `backup_posture_monitor`.
- **A lane that has never run reports `unknown` and does NOT alert.** A fresh deploy must not page.
- Timezone: store UTC via `services.time_utils.now_utc()`; never `datetime.utcnow()`.

---

### Task 1: Lane liveness observer (pure logic + tests)

Deterministic checker: how long since each lane last dispatched, and is that stale?

**Files:**
- Create: `platform_v2/services/lane_liveness_monitor.py`
- Test: `platform_v2/tests/test_lane_liveness_monitor.py`

**Interfaces:**
- Consumes: `database.get_db_cursor`, `services.telegram_service.send_system`
- Produces:
  - `LANES: dict[str, dict]` — lane key → `{"label": str, "module_sources": tuple[str, ...]}`
  - `STALE_HOURS: dict[str, float]` — lane key → staleness threshold
  - `lane_status(rows: list[dict], now) -> list[dict]` — PURE; returns one dict per lane with keys `lane, label, last_dispatch, age_hours, status` where `status ∈ {"ok","stale","unknown"}`
  - `check_lane_liveness(alert: bool = True) -> dict` — DB + alert wrapper; returns `{"checked_at": str, "lanes": list[dict], "stale": list[str]}`

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_lane_liveness_monitor.py
"""Lane dormancy observer (project #380).

Codex ran last on 2026-06-28 and the engine on 2026-07-20; nobody noticed,
because nothing reported a quiet lane. These tests pin the three rules that
make this observer trustworthy: never-run is UNKNOWN not an alert, a fresh
lane is OK, and a lane past its threshold is STALE.
"""
from datetime import datetime, timedelta, timezone

from services.lane_liveness_monitor import LANES, lane_status

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def _row(source, hours_ago):
    return {"module_source": source, "last_dispatch": NOW - timedelta(hours=hours_ago)}


def test_all_three_lanes_are_reported_even_with_no_rows():
    out = lane_status([], NOW)
    assert {d["lane"] for d in out} == set(LANES)


def test_a_lane_that_never_ran_is_unknown_not_stale():
    out = {d["lane"]: d for d in lane_status([], NOW)}
    assert out["codex"]["status"] == "unknown"
    assert out["codex"]["age_hours"] is None


def test_a_recent_lane_is_ok():
    out = {d["lane"]: d for d in lane_status([_row("claude_cli", 1)], NOW)}
    assert out["claude"]["status"] == "ok"
    assert out["claude"]["age_hours"] == 1.0


def test_a_lane_past_its_threshold_is_stale():
    out = {d["lane"]: d for d in lane_status([_row("codex_cli", 24 * 40)], NOW)}
    assert out["codex"]["status"] == "stale"


def test_engine_matches_either_of_its_two_module_sources():
    out = {d["lane"]: d for d in lane_status([_row("archie_code_engine", 2)], NOW)}
    assert out["engine"]["status"] == "ok"


def test_newest_row_wins_when_a_lane_has_several_sources():
    rows = [_row("archie_engine", 500), _row("archie_code_engine", 3)]
    out = {d["lane"]: d for d in lane_status(rows, NOW)}
    assert out["engine"]["age_hours"] == 3.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_lane_liveness_monitor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.lane_liveness_monitor'`

- [ ] **Step 3: Write minimal implementation**

```python
# platform_v2/services/lane_liveness_monitor.py
"""Per-lane dormancy observer (project #380).

WHY THIS EXISTS: every autonomous coder on this platform was built, merged, and
then quietly stopped. Codex last dispatched 2026-06-28; the archie_engine build
loop 2026-07-20. Neither was broken -- nothing queued work, and nothing reported
the silence. The three-lane design therefore treats a liveness signal as part of
the architecture, not a follow-up.

Same shape as ``backup_posture_monitor``: deterministic, NO LLM in the alert
path, send_system cooldowns, and a lane that has NEVER run reports 'unknown'
rather than alerting -- a fresh deploy must not page.
"""

from services.time_utils import now_utc

# Lane -> the module_source values its dispatches carry in task_execution_log.
# Measured 2026-08-23: claude_cli / codex_cli / archie_engine+archie_code_engine.
LANES: dict = {
    "claude": {"label": "Claude CLI", "module_sources": ("claude_cli",)},
    "codex": {"label": "Codex CLI", "module_sources": ("codex_cli",)},
    "engine": {
        "label": "A.R.C.H.I.E. local",
        "module_sources": ("archie_engine", "archie_code_engine"),
    },
}

# Generous on purpose. These lanes are meant to be busy; the alarm is for
# "has fallen silent", not "is briefly idle".
STALE_HOURS: dict = {"claude": 72.0, "codex": 168.0, "engine": 168.0}


def lane_status(rows: list, now=None) -> list:
    """PURE. rows = [{module_source, last_dispatch}] -> one status dict per lane."""
    now = now or now_utc()
    newest: dict = {}
    for r in rows or []:
        src = r.get("module_source")
        ts = r.get("last_dispatch")
        if not src or not ts:
            continue
        for lane, cfg in LANES.items():
            if src in cfg["module_sources"]:
                if lane not in newest or ts > newest[lane]:
                    newest[lane] = ts

    out = []
    for lane, cfg in LANES.items():
        ts = newest.get(lane)
        if ts is None:
            out.append({
                "lane": lane, "label": cfg["label"], "last_dispatch": None,
                "age_hours": None, "status": "unknown",
            })
            continue
        age = round((now - ts).total_seconds() / 3600.0, 1)
        out.append({
            "lane": lane, "label": cfg["label"], "last_dispatch": ts.isoformat(),
            "age_hours": age,
            "status": "stale" if age > STALE_HOURS[lane] else "ok",
        })
    return out


def check_lane_liveness(alert: bool = True) -> dict:
    """Measure every lane; alert on newly-stale ones. Never raises into a caller."""
    from database import get_db_cursor

    sources = [s for cfg in LANES.values() for s in cfg["module_sources"]]
    rows = []
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT module_source, MAX(created_at) AS last_dispatch "
                "FROM task_execution_log WHERE module_source = ANY(%s) "
                "GROUP BY module_source",
                (sources,),
            )
            rows = [dict(r) for r in cur.fetchall()]
    except Exception as exc:  # observability must never break its caller
        return {"checked_at": now_utc().isoformat(), "lanes": [],
                "stale": [], "error": f"{type(exc).__name__}: {exc}"}

    lanes = lane_status(rows)
    stale = [d["lane"] for d in lanes if d["status"] == "stale"]

    if alert and stale:
        try:
            from services.telegram_service import send_system
            for d in lanes:
                if d["status"] != "stale":
                    continue
                # Lane name in the TITLE: send_system dedups on (title, source),
                # so a shared title would mute every other lane.
                send_system(
                    f"Coder lane dormant: {d['label']}",
                    f"No dispatch for {d['age_hours']}h "
                    f"(threshold {STALE_HOURS[d['lane']]}h). "
                    f"Last seen {d['last_dispatch']}.",
                    cooldown_hours=24.0,
                )
        except Exception:
            pass

    return {"checked_at": now_utc().isoformat(), "lanes": lanes, "stale": stale}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_lane_liveness_monitor.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Sanity-check it against live data**

Run:
```bash
docker exec -w /app archie_platform python3 -c "
from services.lane_liveness_monitor import check_lane_liveness
import json; print(json.dumps(check_lane_liveness(alert=False), indent=2))"
```
Expected: `claude` → `ok`; `codex` and `engine` → `stale` with ages of roughly 1,300h and 800h. If either reads `unknown`, the `module_source` values have drifted — fix `LANES`, do not relax the test.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/lane_liveness_monitor.py platform_v2/tests/test_lane_liveness_monitor.py
git commit -m "feat(observability): per-lane dormancy observer (#380)"
```

---

### Task 2: Schedule the observer

**Files:**
- Modify: `ai_bridge/agent_loop.py` (beside the `backup_posture_monitor` registration, ~line 1157)
- Test: `platform_v2/tests/test_lane_liveness_monitor.py` (append)

**Interfaces:**
- Consumes: `check_lane_liveness` from Task 1
- Produces: an APScheduler job with `id="lane_liveness_monitor"`

- [ ] **Step 1: Write the failing test**

```python
def test_observer_is_registered_as_a_scheduled_job():
    """A monitor nobody schedules is exactly the dormancy this fixes."""
    import pathlib
    src = pathlib.Path("/app/../ai_bridge/agent_loop.py").resolve()
    if not src.exists():
        src = pathlib.Path("/mnt/archie_brain/ai_bridge/agent_loop.py")
    text = src.read_text()
    assert "lane_liveness_monitor" in text, "observer is never scheduled"
    assert "check_lane_liveness" in text, "scheduled job does not call the checker"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_lane_liveness_monitor.py::test_observer_is_registered_as_a_scheduled_job -v`
Expected: FAIL — `AssertionError: observer is never scheduled`

- [ ] **Step 3: Register the job**

Find the `backup_posture_monitor` registration in `ai_bridge/agent_loop.py` (~line 1157) and add immediately after it, matching the surrounding style:

```python
            # Per-lane coder dormancy (#380). Deterministic, no LLM. Hourly is
            # ample for thresholds measured in days.
            from services.lane_liveness_monitor import check_lane_liveness

            scheduler.add_job(
                check_lane_liveness,
                "interval",
                hours=1,
                id="lane_liveness_monitor",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_lane_liveness_monitor.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Deploy and confirm the job is live**

```bash
docker compose restart archie_scheduler
sleep 45
docker logs --since 2m archie_scheduler 2>&1 | grep -i "lane_liveness" | head -3
```
Expected: a registration or execution line. **`is-active` is not proof** — confirm the job id appears.

- [ ] **Step 6: Commit**

```bash
git add ai_bridge/agent_loop.py platform_v2/tests/test_lane_liveness_monitor.py
git commit -m "feat(observability): schedule the lane dormancy observer hourly (#380)"
```

---

### Task 3: Read endpoint for the cockpit badge

**Files:**
- Modify: `platform_v2/app.py` (beside the other `/api/internal/*` routes, near `api_internal_invokable_skills` ~line 5540)
- Test: `platform_v2/tests/test_lane_liveness_monitor.py` (append)

**Interfaces:**
- Consumes: `check_lane_liveness` from Task 1
- Produces: `GET /api/internal/lane-liveness` → `{"ok": true, "checked_at": str, "lanes": [...], "stale": [...]}`, Bearer `INTERNAL_API_KEY`

- [ ] **Step 1: Write the failing test**

```python
def test_liveness_endpoint_is_on_the_internal_key_surface():
    """The cockpit is a separate container: it has the internal key, not a session.
    #2781 shipped exactly this bug -- a registry gated so its only consumer 401'd."""
    import pathlib
    src = pathlib.Path("/app/app.py")
    if not src.exists():
        src = pathlib.Path("/mnt/archie_brain/platform_v2/app.py")
    text = src.read_text()
    assert "/api/internal/lane-liveness" in text, "endpoint missing"
    idx = text.index("/api/internal/lane-liveness")
    window = text[idx: idx + 1200]
    assert "check_lane_liveness" in window, "route does not call the checker"
    assert "login_required" not in window, "internal route must not be session-gated"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_lane_liveness_monitor.py::test_liveness_endpoint_is_on_the_internal_key_surface -v`
Expected: FAIL — `AssertionError: endpoint missing`

- [ ] **Step 3: Add the route**

In `platform_v2/app.py`, beside the other `/api/internal/delegation/*` routes, copying their existing auth decorator/helper exactly as those routes do it:

```python
@app.route("/api/internal/lane-liveness", methods=["GET"])
@require_internal_key  # same guard the sibling /api/internal/delegation routes use
def api_internal_lane_liveness():
    """Per-lane dormancy for the cockpit badge (#380).

    Internal-key surface, NOT session-gated: the cockpit is a separate
    container holding the internal key and no session cookie.
    """
    from services.lane_liveness_monitor import check_lane_liveness

    # alert=False: the hourly job owns alerting. A page refresh must never page.
    data = check_lane_liveness(alert=False)
    return jsonify({"ok": True, **data})
```

> If the sibling routes use a different guard name, use theirs verbatim — do not invent one.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_lane_liveness_monitor.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Verify live through the running process**

```bash
docker compose restart archie_platform && sleep 40
docker exec -i archie_platform python3 - <<'PY'
import os, json, urllib.request
k = os.environ.get("INTERNAL_API_KEY", "")
r = urllib.request.Request("http://127.0.0.1:3000/api/internal/lane-liveness",
                           headers={"Authorization": "Bearer " + k})
print(json.dumps(json.loads(urllib.request.urlopen(r, timeout=20).read()), indent=2))
PY
```
Expected: HTTP 200, three lanes, `claude` ok, `codex`/`engine` stale.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/app.py platform_v2/tests/test_lane_liveness_monitor.py
git commit -m "feat(api): internal lane-liveness endpoint for the cockpit badge (#380)"
```

---

### Task 4: Wire `authority='coo_window'` into the engine merge path

⚠️ **Premise corrected 2026-08-23 during execution.** The original text here claimed she auto-merges Tier 2 today and that this task reduces authority. **Both were wrong.** Measured: `merge_pr(..., authority=_DEFAULT_AUTHORITY)` with `_DEFAULT_AUTHORITY = "forge"`, and the two unattended callers (`forge_pipeline.py:359`, `pr_review_service.py:769`) pass no authority — so they already run at the most restrictive **Tier 1** ceiling. No production code passes `authority='coo'`; only tests do.

This task therefore **RAISES** the unattended ceiling from Tier 1 to Tier 2, bounded by an owner-approved open window that lists the PR on its manifest. The owner was shown the correction and explicitly accepted the increase.

**Files:**
- Modify: `platform_v2/tools/repair_bay/services/github_service.py` — the engine/COO merge call site
- Test: `platform_v2/tests/test_window_scoped_merge.py` (append)

**Interfaces:**
- Consumes: `_automerge_governance_ok(pr_number, repo, authority)`, `_pr_on_open_window(pr_number)`
- Produces: unattended COO merges pass `authority="coo_window"`

- [ ] **Step 1: Write the failing test**

```python
def test_unattended_coo_merges_use_the_window_authority():
    """'coo' alone lets her merge Tier 2 unattended; 'coo_window' additionally
    requires an OPEN window whose manifest names the PR. Zero production callers
    passed 'coo_window' before #380."""
    import pathlib
    p = pathlib.Path("/app/tools/repair_bay/services/github_service.py")
    if not p.exists():
        p = pathlib.Path(
            "/mnt/archie_brain/platform_v2/tools/repair_bay/services/github_service.py")
    src = p.read_text()
    assert 'authority="coo_window"' in src or "authority='coo_window'" in src, \
        "no production caller passes coo_window"


def test_no_unattended_path_still_passes_bare_coo():
    """A leftover bare-'coo' unattended caller would silently keep the old power."""
    import pathlib, re
    p = pathlib.Path("/app/tools/repair_bay/services/github_service.py")
    if not p.exists():
        p = pathlib.Path(
            "/mnt/archie_brain/platform_v2/tools/repair_bay/services/github_service.py")
    src = p.read_text()
    bare = re.findall(r'authority\s*=\s*["\']coo["\']', src)
    assert not bare, f"unattended caller still uses bare 'coo': {bare}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_window_scoped_merge.py -v -k authority`
Expected: FAIL — `AssertionError: no production caller passes coo_window`

- [ ] **Step 3: Change the call site**

In `github_service.py`, locate where an unattended engine/COO merge resolves its authority and pass `"coo_window"` instead of `"coo"`. Do **not** touch `_AUTHORITY_CEILING`, `human_override`, or the two `@admin_required` routes — an authenticated human clicking Merge is the authority those exist to require (decision #953).

```python
    # #380: unattended COO merges are window-scoped. 'coo_window' is strictly
    # narrower than 'coo' -- same Tier-2 ceiling PLUS a third condition: an
    # announced window must be OPEN and this PR must be on its approved
    # manifest. Interactive human merges are unaffected.
    authority = "coo_window"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_window_scoped_merge.py tests/test_merge_governance_gate.py -v`
Expected: PASS — all, including the 20 pre-existing governance tests

- [ ] **Step 5: Verify the refusal is real, not assumed**

```bash
docker exec -w /app archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services import github_service as gs
print(gs._pr_on_open_window(999999))"
```
Expected: `(False, 'no maintenance window is open')` — fails closed with no window, which is the state today.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/repair_bay/services/github_service.py platform_v2/tests/test_window_scoped_merge.py
git commit -m "fix(governance): unattended COO merges are window-scoped (#380)"
```

---

### Task 5: Widen `PLATFORM_SCOPE` to platform-minus-kernel

**Repo: `archie-code`** (`/mnt/standalone/archie-code`). Deploy = merge to main + restart `archie_engine`.

Today `PLATFORM_SCOPE` is a 19-path allowlist mirroring Codex's — it scopes the COO as if she were a third-party agent. The design inverts this for her lane: platform-wide reach, bounded by a never-touch kernel and by process (approval + PR + window from Task 4).

**Files:**
- Modify: `archie_engine/scope_guard.py` — `PLATFORM_SCOPE`
- Test: `archie_engine/tests/test_scope_guard.py` (append; create if absent)

**Interfaces:**
- Consumes: `is_in_scope(path, cfg)` (existing)
- Produces: `PLATFORM_SCOPE` with broad `allowed_paths` and the kernel in `blocked_globs`

- [ ] **Step 1: Write the failing test**

```python
from archie_engine.scope_guard import PLATFORM_SCOPE, is_in_scope

def test_she_can_reach_the_platform_she_runs():
    for p in ("platform_v2/services/agent_jobs.py",
              "platform_v2/tools/department_hq/jobs.py",
              "ai_bridge/agent_loop.py",
              "platform_v2/templates/tools/wtf_hub.html"):
        assert is_in_scope(p, PLATFORM_SCOPE), p

def test_the_governance_kernel_stays_blocked():
    """An actor that can rewrite the rules binding it is not governed.
    Safety property -> universal, per decision #953."""
    for p in ("platform_v2/services/agent_service.py",
              "platform_v2/tools/department_hq/services/department_dispatcher.py"):
        assert not is_in_scope(p, PLATFORM_SCOPE), p

def test_secrets_infra_and_ci_stay_blocked():
    for p in (".env", "platform_v2/.env", "secrets/database/password.txt",
              "docker-compose.yml", "Dockerfile", "scripts/dr/failover.sh",
              ".github/workflows/ci.yml"):
        assert not is_in_scope(p, PLATFORM_SCOPE), p

def test_traversal_and_absolute_paths_still_refused():
    for p in ("../etc/passwd", "/etc/passwd", "platform_v2/../../x"):
        assert not is_in_scope(p, PLATFORM_SCOPE), p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/standalone/archie-code && python3 -m pytest archie_engine/tests/test_scope_guard.py -v -k platform`
Expected: FAIL on `test_she_can_reach_the_platform_she_runs` — `platform_v2/services/agent_jobs.py` is not in the 19-path allowlist.

- [ ] **Step 3: Widen the scope**

Replace `PLATFORM_SCOPE["allowed_paths"]` with the broad set and **extend** `blocked_globs`. Keep every existing blocked glob.

```python
PLATFORM_SCOPE: dict = {
    # #380: inverted for Lane 3. A.R.C.H.I.E. is COO and the platform is hers,
    # so she is bounded by PROCESS (owner-approved manifest + PR + F.O.R.G.E. +
    # window-scoped merge), not by a path allowlist. Codex keeps the narrow
    # allowlist because it is a third-party agent.
    "allowed_paths": [
        "platform_v2/",
        "ai_bridge/",
        "scripts/",
        "docs/",
        "database/migrations/",
    ],
    "blocked_globs": [
        "*.env", ".env*", "*.key", "*.pem", "*.pfx", "secrets/*",
        "docker-compose*", "Dockerfile*", "scripts/dr/*",
        ".git/*", ".github/*",
        # THE GOVERNANCE KERNEL -- universal, blocked for every lane including
        # hers. This code enforces every other rule, including which lane runs
        # and what gets approved.
        "*agent_service.py",
        "*department_dispatcher.py",
        # Real production data; excluded until they have DB isolation.
        "platform_v2/tools/media_studio/*",
        "platform_v2/tools/game_studio/*",
        "platform_v2/tools/media_hub/*",
    ],
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/standalone/archie-code && python3 -m pytest archie_engine/tests/ -v`
Expected: PASS — the new tests plus every pre-existing scope-guard test.

- [ ] **Step 5: Confirm no regression against the baseline**

```bash
cd /mnt/standalone/archie-code
git worktree add -q /tmp/sg-base main && (cd /tmp/sg-base && python3 -m pytest archie_engine/tests/ -q 2>&1 | tail -3)
python3 -m pytest archie_engine/tests/ -q 2>&1 | tail -3
git worktree remove /tmp/sg-base --force
```
Expected: failure counts identical apart from the new passing tests. Compare the failing test **names**, not just the counts — a matching count can hide a swap.

- [ ] **Step 6: Commit**

```bash
git add archie_engine/scope_guard.py archie_engine/tests/test_scope_guard.py
git commit -m "feat(scope): PLATFORM_SCOPE is platform-minus-kernel for Lane 3 (#380)"
```

---

## After all five tasks

1. Open one PR per repo, each based on `main`, each under 9,000 diff chars.
2. Review: `review_pr(<n>)` for platform; `review_pr(<n>, repo="KytranKatarn/archie-code")` for archie-code — **archie-code is not in `GITHUB_REPOS`, so it is never auto-polled.**
3. Merge only on an APPROVE verdict.
4. Deploy: platform → `git checkout main && git pull --ff-only` + restart `archie_platform archie_scheduler`. archie-code → restart `archie_engine` (it re-clones `origin/main`).
5. **Verify through the running process, never from git**: re-run the Task 3 endpoint check and confirm `codex`/`engine` still report `stale`. That stale reading is the point — it is the first time the platform has ever said so.

## Self-review notes

- **Spec coverage:** this plan implements spec items 3 (coo_window wiring), 4 (PLATFORM_SCOPE), and the non-negotiable dormancy alarm. Spec items 1 (proposer), 2 (cockpit surface) and 5 (per-repo scopes) are deliberately **out of scope** — they are Plans 2, 3 and 4.
- **Deferred by design:** the cockpit *rendering* of the badge belongs to Plan 3, since `archie_comms` is a separate image-baked service; Task 3 ships the endpoint it will consume.
- **Type consistency:** `check_lane_liveness` / `lane_status` / `LANES` / `STALE_HOURS` are used with identical names and shapes in Tasks 1, 2 and 3.
