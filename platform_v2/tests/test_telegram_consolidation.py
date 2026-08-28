"""Tests for unified telegram_service consolidation (#1935).

Verifies:
  1. send_dispatch_advisory produces exactly one telegram_message_log row
     with category='info' via telegram_service.send().
  2. send_escalation_notification produces exactly one telegram_message_log
     row (not two) — the old inline INSERT is gone, only _log_message fires.
  3. send_escalation_notification still dual-writes to unified_messages +
     chat_messages (Project #265 alignment preserved).

Strategy: patch the real DB writes and the outbound Telegram calls so tests
run without a live bot token or Telegram network access.
"""

import os
import sys
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

# Ensure platform_v2 is importable (mirrors agent_loop bootstrap).
#
# The guard here was `if ARCHIE_PLATFORM_PATH != "":`. os.getenv returns **None** when the
# variable is unset - and `None != ""` is TRUE - so this inserted **None into sys.path**.
# That one line was the largest single source of failure in the whole suite: importlib
# .metadata walks sys.path, so every later flask.testing.FlaskClient() (which probes the
# Werkzeug version on construction) died with
#     TypeError: stat: path should be string, bytes, os.PathLike or integer, not NoneType
# - 296 errors across 379 test files, about two-thirds of the suite's red, from ONE
# module-level line in ONE test file. Use truthiness, never `!= ""`, on an env lookup.
ARCHIE_PLATFORM_PATH = os.getenv("ARCHIE_PLATFORM_PATH")
if ARCHIE_PLATFORM_PATH and ARCHIE_PLATFORM_PATH not in sys.path:
    sys.path.insert(0, ARCHIE_PLATFORM_PATH)

# This was `if "$ARCHIE_AI_BRIDGE_PATH" not in sys.path:` - a literal shell-style string
# that is never in sys.path, so the condition was always true and the guard did nothing.
_AI_BRIDGE_PATH = os.getenv("ARCHIE_AI_BRIDGE_PATH") or "/mnt/archie_brain/ai_bridge"
if _AI_BRIDGE_PATH not in sys.path:
    sys.path.insert(0, _AI_BRIDGE_PATH)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gateway(bot_token=os.getenv("ARCHIE_TELEGRAM_BOT_TOKEN")):
    """Instantiate TelegramGateway without starting the async bot."""
    from ai_bridge.telegram_gateway import TelegramGateway

    gw = object.__new__(TelegramGateway)
    gw.bot_token = bot_token
    gw._running = True
    gw._loop = asyncio.new_event_loop()
    gw._application = MagicMock()
    return gw


# ---------------------------------------------------------------------------
# 1. send_dispatch_advisory → telegram_service.send()
# ---------------------------------------------------------------------------


class TestSendDispatchAdvisory:
    def test_calls_telegram_service_send(self):
        """Advisory must delegate to telegram_service.send(), not raw requests."""
        gw = _make_gateway()

        with patch("services.telegram_service.send") as mock_send:
            # Inject the mock into the module's import namespace for the lazy import
            import services.telegram_service as ts_mod

            original_send = ts_mod.send
            ts_mod.send = mock_send
            try:
                gw.send_dispatch_advisory("Test Title", "Test body message")
            finally:
                ts_mod.send = original_send

        mock_send.assert_called_once()
        kwargs = mock_send.call_args
        # Accept positional or keyword arguments
        bound = kwargs[1] if kwargs[1] else {}
        positional = kwargs[0] if kwargs[0] else ()
        # category must be 'info'
        assert bound.get("category") == "info" or (len(positional) > 0 and positional[0] == "info")

    def test_does_not_use_raw_requests(self):
        """Confirm requests.post is never called for advisory sends."""
        gw = _make_gateway()

        with patch("requests.post") as mock_post, patch("services.telegram_service.send", return_value={"sent": True}):
            import services.telegram_service as ts_mod

            original_send = ts_mod.send
            ts_mod.send = MagicMock(return_value={"sent": True})
            try:
                gw.send_dispatch_advisory("Title", "Message")
            finally:
                ts_mod.send = original_send

        mock_post.assert_not_called()

    def test_no_bot_token_still_delegates(self):
        """Even with empty token, should try telegram_service (which handles token check)."""
        gw = _make_gateway(bot_token="")

        call_count = []

        import services.telegram_service as ts_mod

        original_send = ts_mod.send

        def counting_send(*args, **kwargs):
            call_count.append(1)
            return {"sent": False, "reason": "no bot token configured"}

        ts_mod.send = counting_send
        try:
            gw.send_dispatch_advisory("Title", "Body")
        finally:
            ts_mod.send = original_send

        # Should still call send() once (it may return early, but the call happens)
        assert len(call_count) == 1


# ---------------------------------------------------------------------------
# 2 & 3. send_escalation_notification — exactly one log row, dual-write preserved
# ---------------------------------------------------------------------------


class TestSendEscalationNotification:
    """
    We don't run the real asyncio coroutine; instead we extract the inner
    _send() coroutine and drive it directly, patching the DB + bot calls.
    """

    def _run_send_coroutine(self, approval_id, context, mock_bot_msg=None):
        """
        Invoke send_escalation_notification and capture all _log_message +
        get_db_cursor calls that happen inside the inner _send() coroutine.
        """
        from ai_bridge.telegram_gateway import TelegramGateway
        import services.telegram_service as ts_mod

        # Capture _log_message calls
        log_calls = []
        original_log = ts_mod._log_message

        def fake_log(*args, **kwargs):
            log_calls.append(kwargs if not args else {"_positional": args, **kwargs})
            return 999  # fake log_id

        ts_mod._log_message = fake_log

        # Capture unified_messages + chat_messages writes
        db_writes = []

        # Mock get_db for the user-list SELECT
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [(12345,)]  # one authorized user
        mock_conn.cursor.return_value = mock_cur

        # Mock get_db_cursor for unified + chat writes
        from contextlib import contextmanager

        @contextmanager
        def fake_db_cursor(commit=False):
            c = MagicMock()
            c2 = MagicMock()

            def capturing_execute(sql, params=None):
                db_writes.append((sql.strip()[:60], params))

            c2.execute = capturing_execute
            # Each context manager block: first fetchone = user_id row,
            # second fetchone = conversation lookup (None → triggers INSERT).
            responses = iter([{"user_id": 1}, None, {"id": 10}])
            c2.fetchone = lambda: next(responses, None)
            yield c, c2

        # Mock bot.send_message to return a message object with message_id
        msg_mock = MagicMock()
        msg_mock.message_id = 42
        if mock_bot_msg is None:
            mock_bot_msg = msg_mock

        gw = object.__new__(TelegramGateway)
        gw.bot_token = "$TELEGRAM_BOT_TOKEN"
        gw._running = True
        loop = asyncio.new_event_loop()
        gw._loop = loop
        gw._application = MagicMock()
        gw._application.bot.send_message = AsyncMock(return_value=mock_bot_msg)

        # We schedule the coroutine but need to drive the loop ourselves.
        # Extract _send by running the outer sync method and capturing the future.
        future_holder = []

        def capturing_run_coroutine(coro, lp):
            future_holder.append(coro)
            # Return a dummy future so the outer function doesn't block
            f = loop.create_future()
            f.set_result(None)
            return f

        import database as db_mod

        original_gdc = db_mod.get_db_cursor

        # Patch database.get_db_cursor on the real module object so the coroutine's lazy
        # `from database import get_db_cursor` resolves it. Set BEFORE the block below,
        # because the coroutine is now driven inside it.
        db_mod.get_db_cursor = fake_db_cursor

        try:
            with patch("ai_bridge.telegram_gateway.get_db", return_value=mock_conn), patch(
                "asyncio.run_coroutine_threadsafe", capturing_run_coroutine
            ):
                gw.send_escalation_notification(approval_id, context)

                # ⚠️ DRIVE THE COROUTINE INSIDE THE PATCH CONTEXT.
                #
                # `send_escalation_notification` only SCHEDULES `_send()`; the captured
                # coroutine body does not execute until awaited. Running it after the
                # `with` block meant the patches were already undone, so `_send` called the
                # REAL get_db and the mock was never touched — measured: get_db called
                # False, cursor() 0, bot.send_message 0, and its `except` swallowed the
                # fallout silently.
                #
                # It passed historically only because the real DB had telegram_users rows,
                # so the loop iterated and logged for real. Against archie_test — which has
                # never held a row — it iterates zero times and logs nothing, so all three
                # tests failed with "Calls: []" while looking like a production defect.
                #
                # A capture-then-run helper must run INSIDE every patch the coroutine needs.
                if future_holder:
                    loop.run_until_complete(future_holder[0])
        finally:
            db_mod.get_db_cursor = original_gdc
            ts_mod._log_message = original_log
            loop.close()

        return log_calls, db_writes

    def test_exactly_one_log_row_per_send(self):
        """send_escalation_notification must produce exactly ONE telegram_message_log row."""
        context = {
            "agent_name": "V.I.G.I.L.",
            "department": "Security & Compliance",
            "module_id": "security_network",
            "capability": "compliance_scan",
            "failure_count": 2,
            "original_model": "mistral:7b",
            "escalated_model": "claude-3-haiku",
            "est_cost": 0.0012,
            "recommendation": "Approve",
        }
        log_calls, _ = self._run_send_coroutine(approval_id=101, context=context)
        assert len(log_calls) == 1, (
            f"Expected exactly 1 telegram_message_log row, got {len(log_calls)}. " f"Calls: {log_calls}"
        )

    def test_log_row_has_escalation_category(self):
        """The single log row must use category='escalation'."""
        context = {
            "agent_name": "P.R.O.B.E.",
            "department": "Engineering & Technology",
            "module_id": "repair_bay",
            "capability": "code_repair",
            "failure_count": 1,
            "original_model": "phi3.5",
            "escalated_model": "claude-3-sonnet",
            "est_cost": 0.005,
            "recommendation": "Approve",
        }
        log_calls, _ = self._run_send_coroutine(approval_id=202, context=context)
        assert log_calls, "No log calls recorded"
        first = log_calls[0]
        category = first.get("category") or (first.get("_positional", [None])[0])
        assert category == "escalation"

    def test_writes_to_unified_tables_only(self):
        """After Phase 3 (#2175), escalations write to unified_* only — no chat_* writes."""
        context = {
            "agent_name": "K.I.N.",
            "department": "Human Resources & Culture",
            "module_id": "department_hq",
            "capability": "hr_review",
            "failure_count": 3,
            "original_model": "llama3.2:3b",
            "escalated_model": "gpt-4o-mini",
            "est_cost": 0.002,
            "recommendation": "Approve",
        }
        _, db_writes = self._run_send_coroutine(approval_id=303, context=context)
        sqls = [w[0].upper() for w in db_writes]
        has_unified = any("UNIFIED_MESSAGES" in s or "UNIFIED_CONVERSATIONS" in s for s in sqls)
        has_chat = any("CHAT_MESSAGES" in s or "CHAT_CONVERSATIONS" in s for s in sqls)
        assert has_unified, f"No unified_messages/conversations write found. SQLs: {sqls}"
        assert not has_chat, f"FU9 chat_* dual-write not fully removed. SQLs: {sqls}"

    def test_no_inline_insert_in_gateway(self):
        """Regression: the old inline INSERT INTO telegram_message_log must not exist in gateway."""
        with open(
            os.getenv(
                "TELEGRAM_GATEWAY_PATH",
                os.getenv("TELEGRAM_GATEWAY_PATH", "/mnt/archie_brain/ai_bridge/telegram_gateway.py"),
            )
        ) as f:
            source = f.read()

        # The old block opened a log_conn = get_db() and committed manually.
        # After refactor, only the _tg_log() call should appear.
        assert (
            "log_conn = get_db()" not in source
        ), "Old inline log_conn pattern still present — inline INSERT not fully removed"
        assert (
            "log_cur.execute" not in source or "telegram_message_log" not in source.split("log_cur.execute")[1][:200]
            if "log_cur.execute" in source
            else True
        )


# ---------------------------------------------------------------------------
# 4. send() is still sync-callable (no asyncio required)
# ---------------------------------------------------------------------------


class TestTelegramServiceSync:
    def test_send_is_sync(self):
        """telegram_service.send() must be callable from sync context without an event loop."""
        import services.telegram_service as ts_mod

        # Should not raise even without a running asyncio loop.
        # We patch the outbound call to avoid needing a real bot token.
        # source_agent is REQUIRED, and not as boilerplate: production added an
        # A.R.C.H.I.E.-voice authorisation guard (_PRIVILEGED_SOURCES, telegram_service.py:159)
        # that raises PermissionError for an unprivileged caller BEFORE any asyncio code runs.
        # Without it this test died on AUTHORISATION while claiming to assert a SYNC-CALLABILITY
        # property — it never reached the code under test. Passing a privileged source restores
        # the original assertion instead of weakening the guard to accommodate the test.
        with patch("services.telegram_service._get_token", return_value=None):
            result = ts_mod.send(
                category="info",
                title="Test",
                message="Test body",
                source_agent="A.R.C.H.I.E.",
            )

        # Without a token it logs a failure — that's fine, the point is no asyncio error.
        assert isinstance(result, dict)
