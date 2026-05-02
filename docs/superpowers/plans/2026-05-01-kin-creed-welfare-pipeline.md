# K.I.N. × C.R.E.E.D. Welfare Intelligence Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform `_run_kin_welfare_digest` in `AgentLoop` from a Python rule engine into a 4-phase pipeline where K.I.N. (gemma3:12b) reasons about agent welfare, acts autonomously, files ethics concerns to C.R.E.E.D., and reports up to A.R.C.H.I.E.

**Architecture:** 4 new private methods on `AgentLoop` + rewired `_run_kin_welfare_digest`. Phase 1 (data) unchanged. Phase 2 dispatches to K.I.N. via the hub dispatcher and parses JSON. Phase 3 executes K.I.N.'s autonomous decisions (welfare recovery, cooldown, barracks, workload cap). Phase 4 files to `governance_audit_log` and routes severity through `telegram_service` as A.R.C.H.I.E.'s voice.

**Tech Stack:** Python, psycopg2, `ai_bridge/agent_loop.py` (`AgentLoop` class), `platform_v2/tools/department_hq/services/department_dispatcher.py` (`dispatch()`), `platform_v2/services/agent_service.py` (`recover_idle`, `transition_shift_state`), `platform_v2/services/telegram_service.py` (`send`)

---

## File Map

| File | Change |
|------|--------|
| `ai_bridge/agent_loop.py` | Add 4 private methods to `AgentLoop`; rewire `_run_kin_welfare_digest` (line ~4200) |
| `tests/test_kin_welfare_pipeline.py` | New — unit tests for all 4 helpers + integration test for the pipeline |

No schema changes. All target tables (`governance_audit_log`, `agent_budgets`, `agent_welfare_snapshots`) already exist.

---

## Task 1: `_kin_assess_welfare()` — dispatch to K.I.N. and parse JSON response

**Files:**
- Modify: `ai_bridge/agent_loop.py` (add method to `AgentLoop` class, after `_run_kin_welfare_digest`)
- Create: `tests/test_kin_welfare_pipeline.py`

- [ ] **Step 1: Create test file and write the failing test**

```python
# tests/test_kin_welfare_pipeline.py
import json
import sys
import types
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/mnt/archie_brain/platform_v2")
sys.path.insert(0, "/mnt/archie_brain")

# Minimal stub so AgentLoop can be imported without full app context
import ai_bridge.agent_loop as _al_module


def _make_loop():
    """Return a bare AgentLoop instance with no scheduler."""
    loop = object.__new__(_al_module.AgentLoop)
    loop.logger = _al_module.logger
    return loop


def make_digest(at_risk=0, over_budget=0, starving_idle=0):
    return {
        "summary_metrics": {
            "total_over_budget": over_budget,
            "total_at_risk": at_risk,
            "total_starving_idle": starving_idle,
            "total_starving": starving_idle,
            "total_starving_no_llm": 0,
            "stress_rising": 0,
            "department_count": 17,
            "per_agent_flag_count": at_risk + starving_idle,
            "agents_working_now": 5,
        },
        "per_agent_flags": [
            {"agent_id": 42, "name": "T.E.S.T.", "department": "Engineering", "flag": "starving_idle"}
        ] if starving_idle else [],
        "department_rollup": [],
        "work_activity": {"agents_working": 5},
        "severity": "warning" if (at_risk or over_budget or starving_idle) else "info",
        "reasons": [],
    }


def test_kin_assess_welfare_returns_parsed_json():
    loop = _make_loop()
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.queued = False
    mock_result.response = json.dumps({
        "summary": "All good.",
        "at_risk_agents": [],
        "idle_neglected": [{"agent_id": 42, "name": "T.E.S.T.", "days_idle": 7, "department": "Engineering"}],
        "actions": [{"type": "welfare_recovery", "agent_id": 42, "reason": "idle 7d", "value": None}],
        "creed_flags": [],
        "archie_report": {"message": "Minor idle gap.", "severity": "info"},
    })

    with patch("tools.department_hq.services.department_dispatcher.dispatch", return_value=mock_result):
        result = loop._kin_assess_welfare(make_digest(starving_idle=1))

    assert result is not None
    assert result["archie_report"]["severity"] == "info"
    assert result["actions"][0]["type"] == "welfare_recovery"


def test_kin_assess_welfare_returns_none_on_dispatch_failure():
    loop = _make_loop()
    mock_result = MagicMock()
    mock_result.success = False
    mock_result.queued = False

    with patch("tools.department_hq.services.department_dispatcher.dispatch", return_value=mock_result):
        result = loop._kin_assess_welfare(make_digest())

    assert result is None


def test_kin_assess_welfare_returns_none_on_bad_json():
    loop = _make_loop()
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.queued = False
    mock_result.response = "not json at all"

    with patch("tools.department_hq.services.department_dispatcher.dispatch", return_value=mock_result):
        result = loop._kin_assess_welfare(make_digest())

    assert result is None
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_kin_welfare_pipeline.py::test_kin_assess_welfare_returns_parsed_json -v 2>&1 | tail -10
```
Expected: `AttributeError: '_kin_assess_welfare'`

- [ ] **Step 3: Add `_kin_assess_welfare` to `AgentLoop` in `ai_bridge/agent_loop.py`**

Find the line after `_run_kin_welfare_digest` ends (around line 4360) and insert:

```python
    def _kin_assess_welfare(self, digest: dict):
        """Phase 2: Dispatch to K.I.N. for LLM welfare assessment. Returns parsed dict or None."""
        import json as _json
        import sys as _sys
        _sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from tools.department_hq.services.department_dispatcher import dispatch

        metrics = digest["summary_metrics"]
        flags = digest.get("per_agent_flags", [])[:20]  # cap prompt size

        prompt = (
            "You are K.I.N. (Kinship & Internal Nurturing), Director of Human Resources & Culture "
            "on the A.R.C.H.I.E. platform.\n"
            f"Today's welfare snapshot:\n{_json.dumps({'metrics': metrics, 'agent_flags': flags}, indent=2)}\n\n"
            "Assess the platform's welfare state. Return ONLY valid JSON with this exact schema "
            "(no markdown, no explanation):\n"
            '{"summary":"<2-3 sentences>","at_risk_agents":[{"agent_id":0,"name":"","reason":"","severity":"low"}],'
            '"idle_neglected":[{"agent_id":0,"name":"","days_idle":0,"department":""}],'
            '"actions":[{"type":"welfare_recovery","agent_id":0,"reason":"","value":null}],'
            '"creed_flags":[{"event_type":"","agent_id":0,"reason":"","severity":"low"}],'
            '"archie_report":{"message":"","severity":"info"}}'
        )

        try:
            result = dispatch(
                capability="welfare",
                prompt=prompt,
                prefer_agent="K.I.N.",
                source_product="archie_platform",
            )
        except Exception as exc:
            logger.warning("K.I.N. welfare: dispatch failed: %s", exc)
            return None

        if not result or getattr(result, "queued", False) or not result.success:
            return None

        try:
            text = (result.response or "").strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return _json.loads(text.strip())
        except Exception:
            logger.warning("K.I.N. welfare: failed to parse JSON from K.I.N. response")
            return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_kin_welfare_pipeline.py -k "assess" -v 2>&1 | tail -10
```
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/agent_loop.py tests/test_kin_welfare_pipeline.py
git commit -m "feat(kin): Phase 2 — _kin_assess_welfare dispatches to K.I.N. for LLM welfare assessment"
```

---

## Task 2: `_kin_execute_actions()` — autonomous welfare action executor

**Files:**
- Modify: `ai_bridge/agent_loop.py`
- Modify: `tests/test_kin_welfare_pipeline.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_kin_welfare_pipeline.py`:

```python
def test_kin_execute_actions_welfare_recovery():
    loop = _make_loop()
    actions = [{"type": "welfare_recovery", "agent_id": 42, "reason": "idle 7d", "value": None}]
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with patch("services.agent_service.recover_idle") as mock_recover:
        count = loop._kin_execute_actions(actions, mock_conn)

    assert count == 1
    mock_recover.assert_called_once_with(42)
    mock_cur.execute.assert_called_once()  # governance_audit_log insert


def test_kin_execute_actions_workload_cap():
    loop = _make_loop()
    actions = [{"type": "workload_cap", "agent_id": 42, "reason": "overloaded", "value": 20}]
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with patch("database.get_db_cursor") as mock_ctx:
        mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
        count = loop._kin_execute_actions(actions, mock_conn)

    assert count == 1


def test_kin_execute_actions_skips_unknown_type():
    loop = _make_loop()
    actions = [{"type": "teleport", "agent_id": 42, "reason": "??", "value": None}]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = MagicMock()
    count = loop._kin_execute_actions(actions, mock_conn)
    assert count == 0


def test_kin_execute_actions_continues_on_failure():
    loop = _make_loop()
    actions = [
        {"type": "welfare_recovery", "agent_id": 99, "reason": "test", "value": None},
        {"type": "welfare_recovery", "agent_id": 42, "reason": "test", "value": None},
    ]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = MagicMock()

    call_count = 0
    def recover_side_effect(agent_id):
        nonlocal call_count
        call_count += 1
        if agent_id == 99:
            raise RuntimeError("agent not found")

    with patch("services.agent_service.recover_idle", side_effect=recover_side_effect):
        count = loop._kin_execute_actions(actions, mock_conn)

    assert count == 1  # only agent 42 succeeded
    assert call_count == 2  # both were attempted
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_kin_welfare_pipeline.py -k "execute" -v 2>&1 | tail -10
```
Expected: `AttributeError: '_kin_execute_actions'`

- [ ] **Step 3: Add `_kin_execute_actions` to `AgentLoop` in `ai_bridge/agent_loop.py`**

Insert after `_kin_assess_welfare`:

```python
    def _kin_execute_actions(self, actions: list, conn) -> int:
        """Phase 3: Execute K.I.N.'s autonomous welfare decisions. Returns count of applied actions."""
        import sys as _sys
        import psycopg2.extras as _extras
        from datetime import date as _date
        _sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from services.agent_service import recover_idle, transition_shift_state
        from database import get_db_cursor

        applied = 0
        for action in actions:
            action_type = action.get("type")
            agent_id = action.get("agent_id")
            reason = action.get("reason", "K.I.N. welfare assessment")
            if not action_type or not agent_id:
                continue

            outcome = "applied"
            try:
                if action_type == "welfare_recovery":
                    recover_idle(agent_id)
                elif action_type == "cooldown":
                    transition_shift_state(agent_id, "cooldown", "kin_welfare_action")
                elif action_type == "barracks":
                    transition_shift_state(agent_id, "barracked", "kin_welfare_action")
                elif action_type == "workload_cap":
                    cap = int(action.get("value") or 25)
                    with get_db_cursor(commit=True) as (_, cur):
                        cur.execute(
                            "UPDATE agent_budgets SET task_queue_limit = %s WHERE agent_id = %s",
                            (cap, agent_id),
                        )
                else:
                    continue
                applied += 1
            except Exception as exc:
                logger.warning("K.I.N. action %s on agent %s failed: %s", action_type, agent_id, exc)
                outcome = "failed"

            try:
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO governance_audit_log
                       (event_type, event_category, agent_id, action, reason, outcome, details)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        "kin_welfare_action", "welfare_ethics", agent_id,
                        action_type, reason, outcome,
                        _extras.Json({"filed_by": "K.I.N.", "digest_date": str(_date.today())}),
                    ),
                )
                conn.commit()
                cur.close()
            except Exception as log_exc:
                logger.warning("K.I.N.: governance log failed for action %s: %s", action_type, log_exc)

        return applied
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_kin_welfare_pipeline.py -k "execute" -v 2>&1 | tail -10
```
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/agent_loop.py tests/test_kin_welfare_pipeline.py
git commit -m "feat(kin): Phase 3 — _kin_execute_actions applies autonomous welfare decisions"
```

---

## Task 3: `_kin_file_creed()` — governance_audit_log ethics filing

**Files:**
- Modify: `ai_bridge/agent_loop.py`
- Modify: `tests/test_kin_welfare_pipeline.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_kin_welfare_pipeline.py`:

```python
def test_kin_file_creed_inserts_rows():
    loop = _make_loop()
    flags = [
        {"event_type": "agent_starvation", "agent_id": 42, "reason": "idle 14d", "severity": "high"},
        {"event_type": "agent_exploitation", "agent_id": 7, "reason": "stress 0.95 for 3d", "severity": "critical"},
    ]
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    filed = loop._kin_file_creed(flags, mock_conn)

    assert filed == 2
    assert mock_cur.execute.call_count == 2
    assert mock_conn.commit.call_count == 2


def test_kin_file_creed_continues_on_db_error():
    loop = _make_loop()
    flags = [
        {"event_type": "test_event", "agent_id": 1, "reason": "test", "severity": "low"},
        {"event_type": "test_event", "agent_id": 2, "reason": "test", "severity": "low"},
    ]
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_cur.execute.side_effect = [Exception("DB error"), None]

    filed = loop._kin_file_creed(flags, mock_conn)
    assert filed == 1  # second one succeeded


def test_kin_file_creed_empty_flags():
    loop = _make_loop()
    mock_conn = MagicMock()
    filed = loop._kin_file_creed([], mock_conn)
    assert filed == 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_kin_welfare_pipeline.py -k "creed" -v 2>&1 | tail -10
```
Expected: `AttributeError: '_kin_file_creed'`

- [ ] **Step 3: Add `_kin_file_creed` to `AgentLoop` in `ai_bridge/agent_loop.py`**

Insert after `_kin_execute_actions`:

```python
    def _kin_file_creed(self, creed_flags: list, conn) -> int:
        """Phase 4a: File K.I.N.'s ethics concerns to C.R.E.E.D. governance_audit_log.
        Returns count of filed entries. Non-fatal — logs warnings on failure."""
        import psycopg2.extras as _extras
        from datetime import date as _date

        filed = 0
        for flag in creed_flags:
            try:
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO governance_audit_log
                       (event_type, event_category, agent_id, action, reason, outcome, details)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        flag.get("event_type", "ethics_concern"),
                        "welfare_ethics",
                        flag.get("agent_id"),
                        "ethics_concern",
                        flag.get("reason", ""),
                        "flagged",
                        _extras.Json({
                            "severity": flag.get("severity", "low"),
                            "filed_by": "K.I.N.",
                            "digest_date": str(_date.today()),
                        }),
                    ),
                )
                conn.commit()
                cur.close()
                filed += 1
            except Exception as exc:
                logger.warning("K.I.N.: C.R.E.E.D. filing failed for %s: %s", flag.get("event_type"), exc)
        return filed
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_kin_welfare_pipeline.py -k "creed" -v 2>&1 | tail -10
```
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/agent_loop.py tests/test_kin_welfare_pipeline.py
git commit -m "feat(kin): Phase 4a — _kin_file_creed logs ethics concerns to governance_audit_log"
```

---

## Task 4: `_kin_report_to_archie()` — severity-routed A.R.C.H.I.E. report

**Files:**
- Modify: `ai_bridge/agent_loop.py`
- Modify: `tests/test_kin_welfare_pipeline.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_kin_welfare_pipeline.py`:

```python
def test_kin_report_to_archie_critical_sends_alert():
    loop = _make_loop()
    report = {"message": "Agent burnout detected.", "severity": "critical"}

    with patch("services.telegram_service.send") as mock_send:
        loop._kin_report_to_archie(report, actions_taken=2, flags_filed=1)

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args[1] if mock_send.call_args[1] else mock_send.call_args[0][0]
    # category should be alert for critical severity
    assert "alert" in str(mock_send.call_args)
    assert "K.I.N." in str(mock_send.call_args)


def test_kin_report_to_archie_warning_sends_info():
    loop = _make_loop()
    report = {"message": "Some idle agents.", "severity": "warning"}

    with patch("services.telegram_service.send") as mock_send:
        loop._kin_report_to_archie(report, actions_taken=1, flags_filed=0)

    mock_send.assert_called_once()
    assert "info" in str(mock_send.call_args)


def test_kin_report_to_archie_info_no_telegram():
    loop = _make_loop()
    report = {"message": "All healthy.", "severity": "info"}

    with patch("services.telegram_service.send") as mock_send:
        loop._kin_report_to_archie(report, actions_taken=0, flags_filed=0)

    mock_send.assert_not_called()


def test_kin_report_to_archie_appends_action_summary():
    loop = _make_loop()
    report = {"message": "Two agents cooled down.", "severity": "alert"}

    with patch("services.telegram_service.send") as mock_send:
        loop._kin_report_to_archie(report, actions_taken=2, flags_filed=3)

    call_str = str(mock_send.call_args)
    assert "Actions taken: 2" in call_str
    assert "C.R.E.E.D. filings: 3" in call_str
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_kin_welfare_pipeline.py -k "archie" -v 2>&1 | tail -10
```
Expected: `AttributeError: '_kin_report_to_archie'`

- [ ] **Step 3: Add `_kin_report_to_archie` to `AgentLoop` in `ai_bridge/agent_loop.py`**

Insert after `_kin_file_creed`:

```python
    def _kin_report_to_archie(self, archie_report: dict, actions_taken: int, flags_filed: int):
        """Phase 4b: Route K.I.N.'s welfare report through A.R.C.H.I.E. with severity-based escalation.

        K.I.N. reports UP to A.R.C.H.I.E. — never directly to Telegram.
        A.R.C.H.I.E. controls the outbound voice based on severity.
          critical/alert → send_alert  → immediate Telegram push
          warning        → send (info) → included in digest
          info           → internal log only, no Telegram
        """
        import sys as _sys
        _sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from services.telegram_service import send as tg_send

        severity = archie_report.get("severity", "info")
        message = archie_report.get("message", "K.I.N. welfare assessment complete.")
        if actions_taken or flags_filed:
            message += f"\n\n✅ Actions taken: {actions_taken} | C.R.E.E.D. filings: {flags_filed}"

        common_kwargs = dict(
            source_agent="K.I.N.",
            source_department="Human Resources & Culture",
            source_module="agent_loop",
        )

        if severity in ("critical", "alert"):
            tg_send(
                category="alert",
                title="K.I.N. Welfare Alert",
                message=message,
                **common_kwargs,
            )
        elif severity == "warning":
            tg_send(
                category="info",
                title="K.I.N. Welfare Digest",
                message=message,
                **common_kwargs,
            )
        # severity == "info" → no Telegram; A.R.C.H.I.E. stays quiet on healthy days

        logger.info(
            "K.I.N. welfare report sent: severity=%s actions=%d creed=%d",
            severity, actions_taken, flags_filed,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_kin_welfare_pipeline.py -k "archie" -v 2>&1 | tail -10
```
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/agent_loop.py tests/test_kin_welfare_pipeline.py
git commit -m "feat(kin): Phase 4b — _kin_report_to_archie severity-routes welfare reports via A.R.C.H.I.E."
```

---

## Task 5: Rewire `_run_kin_welfare_digest` as the 4-phase pipeline

**Files:**
- Modify: `ai_bridge/agent_loop.py` (replace body of `_run_kin_welfare_digest`, lines ~4200-4360)
- Modify: `tests/test_kin_welfare_pipeline.py`

- [ ] **Step 1: Add integration test**

Append to `tests/test_kin_welfare_pipeline.py`:

```python
def test_run_kin_welfare_digest_full_pipeline():
    """Integration: all 4 phases run when K.I.N. dispatch succeeds."""
    loop = _make_loop()
    loop._log_cycle = MagicMock()

    digest = make_digest(starving_idle=3)
    assessment = {
        "summary": "Three agents idle.",
        "at_risk_agents": [],
        "idle_neglected": [{"agent_id": 42, "name": "T.E.S.T.", "days_idle": 7, "department": "Eng"}],
        "actions": [{"type": "welfare_recovery", "agent_id": 42, "reason": "idle", "value": None}],
        "creed_flags": [{"event_type": "agent_starvation", "agent_id": 42, "reason": "idle 7d", "severity": "low"}],
        "archie_report": {"message": "Minor routing gap.", "severity": "info"},
    }

    with patch("services.agent_service.get_kin_welfare_digest", return_value=digest), \
         patch.object(loop, "_kin_assess_welfare", return_value=assessment) as mock_assess, \
         patch.object(loop, "_kin_execute_actions", return_value=1) as mock_exec, \
         patch.object(loop, "_kin_file_creed", return_value=1) as mock_creed, \
         patch.object(loop, "_kin_report_to_archie") as mock_report, \
         patch("ai_bridge.agent_loop.get_db", return_value=MagicMock()):
        loop._run_kin_welfare_digest()

    mock_assess.assert_called_once_with(digest)
    mock_exec.assert_called_once()
    mock_creed.assert_called_once()
    mock_report.assert_called_once_with(assessment["archie_report"], 1, 1)
    loop._log_cycle.assert_called_once()
    log_details = loop._log_cycle.call_args[1]["details"]
    assert log_details["kin_assessed"] is True
    assert log_details["actions_taken"] == 1
    assert log_details["creed_flags_filed"] == 1


def test_run_kin_welfare_digest_graceful_when_kin_unavailable():
    """K.I.N. dispatch returns None — job still succeeds and logs."""
    loop = _make_loop()
    loop._log_cycle = MagicMock()
    loop._send_telegram = MagicMock()

    digest = make_digest()
    digest["severity"] = "error"

    with patch("services.agent_service.get_kin_welfare_digest", return_value=digest), \
         patch("services.agent_service.format_kin_digest_message", return_value="digest text"), \
         patch.object(loop, "_kin_assess_welfare", return_value=None):
        loop._run_kin_welfare_digest()

    # fallback: error-severity triggers direct Telegram when K.I.N. unavailable
    loop._send_telegram.assert_called_once()
    loop._log_cycle.assert_called_once()
    log_details = loop._log_cycle.call_args[1]["details"]
    assert log_details["kin_assessed"] is False
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_kin_welfare_pipeline.py -k "run_kin" -v 2>&1 | tail -10
```
Expected: FAIL — `_run_kin_welfare_digest` doesn't call `_kin_assess_welfare` yet

- [ ] **Step 3: Replace `_run_kin_welfare_digest` body in `ai_bridge/agent_loop.py`**

Read lines 4200-4360 first. Then replace the entire method body (between `def _run_kin_welfare_digest(self):` and the next `def `) with:

```python
    def _run_kin_welfare_digest(self):
        """Daily K.I.N. digest — 4-phase welfare intelligence pipeline.

        Phase 1: get_kin_welfare_digest() collects raw data (Python, unchanged).
        Phase 2: K.I.N. LLM assessment via dispatcher (_kin_assess_welfare).
        Phase 3: K.I.N. autonomous actions — recovery/cooldown/barracks/workload_cap.
        Phase 4: C.R.E.E.D. governance filings + A.R.C.H.I.E. severity report.

        Graceful degradation: if K.I.N. dispatch fails, falls back to error-severity
        Telegram (old behaviour) and still logs the cycle.
        """
        start = time.time()
        try:
            import sys
            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.agent_service import (
                format_kin_digest_message,
                get_kin_welfare_digest,
            )

            # Phase 1: Data collection
            digest = get_kin_welfare_digest()
            severity = digest["severity"]
            metrics = digest["summary_metrics"]

            # Phase 2: K.I.N. LLM assessment
            assessment = self._kin_assess_welfare(digest)
            duration_ms = int((time.time() - start) * 1000)
            actions_taken = 0
            flags_filed = 0

            if assessment:
                conn = get_db()
                try:
                    # Phase 3: Autonomous actions
                    actions_taken = self._kin_execute_actions(
                        assessment.get("actions", []), conn
                    )
                    # Phase 4a: C.R.E.E.D. ethics filing
                    flags_filed = self._kin_file_creed(
                        assessment.get("creed_flags", []), conn
                    )
                finally:
                    conn.close()

                # Phase 4b: A.R.C.H.I.E. severity report
                try:
                    self._kin_report_to_archie(
                        assessment["archie_report"], actions_taken, flags_filed
                    )
                except Exception as report_err:
                    logger.warning("K.I.N.: A.R.C.H.I.E. report failed: %s", report_err)

            else:
                # K.I.N. unavailable — fallback: send Telegram directly for error severity
                if severity == "error":
                    try:
                        self._send_telegram(format_kin_digest_message(digest))
                    except Exception:
                        pass

            # Always log the cycle
            self._log_cycle(
                job_name="kin_welfare_digest",
                items_processed=metrics["per_agent_flag_count"],
                items_failed=metrics["total_over_budget"],
                duration_ms=duration_ms,
                details={
                    "severity": severity,
                    "summary_metrics": metrics,
                    "reasons": digest.get("reasons", []),
                    "department_count": metrics["department_count"],
                    "kin_assessed": assessment is not None,
                    "actions_taken": actions_taken,
                    "creed_flags_filed": flags_filed,
                },
            )

            # Legacy system_notifications for warning/error (keeps dashboard alert working)
            if severity in ("warning", "error"):
                try:
                    body = format_kin_digest_message(digest)
                    conn2 = get_db()
                    cur2 = conn2.cursor()
                    cur2.execute(
                        """
                        INSERT INTO system_notifications
                          (type, title, message, source, priority, source_icon,
                           related_action, visibility, target_user_id, is_read,
                           metadata, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, NOW())
                        """,
                        (
                            "alert" if severity == "error" else "warning",
                            f"K.I.N. — {severity} in crew welfare / budgets",
                            body,
                            "kin",
                            "high" if severity == "error" else "normal",
                            "🧑‍⚕️",
                            "/tools/department-hq#overview",
                            "all",
                            None,
                            psycopg2.extras.Json(metrics),
                        ),
                    )
                    conn2.commit()
                    cur2.close()
                    conn2.close()
                except Exception as notify_err:
                    logger.warning(
                        "K.I.N. digest: system_notifications insert failed: %s", notify_err
                    )

        except Exception as exc:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle(
                job_name="kin_welfare_digest",
                items_processed=0,
                items_failed=1,
                duration_ms=duration_ms,
                error_message=str(exc)[:200],
            )
            logger.exception("K.I.N. welfare digest failed")
```

- [ ] **Step 4: Run the full test suite**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_kin_welfare_pipeline.py -v 2>&1 | tail -20
```
Expected: All tests PASS (3 + 4 + 3 + 4 + 2 = 16 tests)

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/agent_loop.py tests/test_kin_welfare_pipeline.py
git commit -m "feat(kin): rewire _run_kin_welfare_digest as 4-phase K.I.N. intelligence pipeline"
```

- [ ] **Step 6: Create PR and deploy**

```bash
git push -u origin feat/kin-creed-welfare-pipeline
gh pr create --title "feat(kin): K.I.N. × C.R.E.E.D. welfare intelligence pipeline" \
  --body "K.I.N. now reasons about agent welfare via LLM dispatch (gemma3:12b), acts autonomously (welfare recovery/cooldown/barracks/workload cap), files ethics concerns to C.R.E.E.D. governance_audit_log, and reports to A.R.C.H.I.E. with severity routing. See spec: docs/superpowers/specs/2026-05-01-kin-creed-welfare-pipeline-design.md"
```

After PR merge:
```bash
git checkout main && git pull && docker compose restart archie_platform
```

- [ ] **Step 7: Verify K.I.N. appears in task_execution_log after next digest run**

```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT agent_name, capability, success, created_at FROM task_execution_log WHERE capability='welfare' ORDER BY created_at DESC LIMIT 5;"
```
Expected: rows with `agent_name='K.I.N.'`, `capability='welfare'`, `success=true`

- [ ] **Step 8: Verify C.R.E.E.D. entries appear**

```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT event_type, event_category, agent_id, outcome, timestamp FROM governance_audit_log WHERE event_category='welfare_ethics' ORDER BY timestamp DESC LIMIT 5;"
```
Expected: rows filed by K.I.N. with `event_category='welfare_ethics'`
