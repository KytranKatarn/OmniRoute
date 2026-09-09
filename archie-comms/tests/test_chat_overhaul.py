"""Tests for Sub-A ARCHIE Chat Overhaul: streaming, memory, status routes."""
import json
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestGetSessionContext:
    def test_returns_string_always(self, monkeypatch):
        from services import conversation_service
        monkeypatch.setattr(conversation_service, "_fetch_kb_conversation_memory", lambda limit: [])
        assert isinstance(conversation_service.get_session_context(user_id=1), str)

    def test_empty_when_no_entries(self, monkeypatch):
        from services import conversation_service
        monkeypatch.setattr(conversation_service, "_fetch_kb_conversation_memory", lambda limit: [])
        assert conversation_service.get_session_context(user_id=1) == ""

    def test_prefix_when_entries_exist(self, monkeypatch):
        from services import conversation_service
        monkeypatch.setattr(
            conversation_service,
            "_fetch_kb_conversation_memory",
            lambda limit: [{"title": "Health check", "content": "All nominal."}],
        )
        result = conversation_service.get_session_context(user_id=1)
        assert result.startswith("[ARCHIE MEMORY]")
        assert "Health check" in result


class TestStreamSendMessage:
    def test_yields_tokens_then_done(self, monkeypatch):
        from services import conversation_service

        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: 42)
        monkeypatch.setattr(conversation_service, "save_message", lambda *a, **kw: {"id": 1})
        monkeypatch.setattr(conversation_service, "get_conversation_messages", lambda *a, **kw: [])
        monkeypatch.setattr(conversation_service, "get_session_context", lambda *a, **kw: "")
        monkeypatch.setattr("services.conversation_service._get_system_prompt", lambda: "sys")

        # #6654: the reply now streams THROUGH the dispatcher (stream_dhq_chat),
        # yielding token strings then a final done dict.
        def _fake_stream(system_prompt, user_prompt, user_id=None, capability="conversation", **kw):
            yield "Hello"
            yield " world"
            yield {"type": "done", "model_used": "llama3.2:3b", "agent_name": "A.R.C.H.I.E."}

        monkeypatch.setattr("services.conversation_service.stream_dhq_chat", _fake_stream)

        items = list(conversation_service.stream_send_message(user_id=1, message="hi"))
        tokens = [i for i in items if isinstance(i, str)]
        done_events = [i for i in items if isinstance(i, dict) and i.get("type") == "done"]
        assert "".join(tokens) == "Hello world"
        assert len(done_events) == 1
        assert done_events[0]["conversation_id"] == 42
        assert done_events[0]["model_used"] == "llama3.2:3b"

    def test_dhq_unavailable_yields_error_and_saves_no_turn(self, monkeypatch):
        """No direct-Ollama fallback (#6654): if the dispatcher is unreachable the
        stream yields an honest error + done and saves NO assistant message."""
        from services import conversation_service

        saved = []
        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: 7)
        monkeypatch.setattr(
            conversation_service, "save_message", lambda conv, ch, direction, sender, content, *a, **kw: saved.append((direction, sender))
        )
        monkeypatch.setattr(conversation_service, "get_conversation_messages", lambda *a, **kw: [])
        monkeypatch.setattr(conversation_service, "get_session_context", lambda *a, **kw: "")
        monkeypatch.setattr("services.conversation_service._get_system_prompt", lambda: "sys")

        def _boom(*a, **kw):
            raise conversation_service.DHQUnavailable("hub down")

        monkeypatch.setattr("services.conversation_service.stream_dhq_chat", _boom)

        items = list(conversation_service.stream_send_message(user_id=1, message="hi"))
        assert any(isinstance(i, dict) and i.get("type") == "error" for i in items)
        assert any(isinstance(i, dict) and i.get("type") == "done" for i in items)
        # only the inbound user turn was saved — never a fabricated assistant reply
        assert ("outbound", "archie") not in saved

    def test_markers_never_reach_the_stream(self, monkeypatch):
        """A {{DELEGATE}} marker split across tokens is held back by the filter and
        never appears in the streamed text, while its event still fires."""
        from services import conversation_service

        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: 9)
        monkeypatch.setattr(conversation_service, "save_message", lambda *a, **kw: {"id": 1})
        monkeypatch.setattr(conversation_service, "get_conversation_messages", lambda *a, **kw: [])
        monkeypatch.setattr(conversation_service, "get_session_context", lambda *a, **kw: "")
        monkeypatch.setattr("services.conversation_service._get_system_prompt", lambda: "sys")

        def _fake_stream(system_prompt, user_prompt, user_id=None, capability="conversation", **kw):
            # marker arrives split across three tokens
            for t in ["On it. ", '{{DELEGATE capability="code_review" ', 'reason="do X"}}', " Done."]:
                yield t
            yield {"type": "done", "model_used": "m", "agent_name": "A.R.C.H.I.E."}

        monkeypatch.setattr("services.conversation_service.stream_dhq_chat", _fake_stream)

        items = list(conversation_service.stream_send_message(user_id=1, message="delegate this"))
        streamed = "".join(i for i in items if isinstance(i, str))
        assert "{{" not in streamed and "DELEGATE" not in streamed
        assert "On it." in streamed and "Done." in streamed
        assert any(isinstance(i, dict) and i.get("type") == "delegation_detected" for i in items)

    def test_error_when_no_conversation(self, monkeypatch):
        from services import conversation_service
        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: None)
        monkeypatch.setattr(conversation_service, "save_message", lambda *a, **kw: {"id": 1})
        monkeypatch.setattr(conversation_service, "get_session_context", lambda *a, **kw: "")
        items = list(conversation_service.stream_send_message(user_id=1, message="hi"))
        assert any(isinstance(i, dict) and i.get("type") == "error" for i in items)


class TestStatusEndpoint:
    def test_unauthenticated_returns_401(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        sys.modules.pop("app_comms", None)
        import app_comms
        app_comms.app.config["TESTING"] = True
        app_comms.app.config["SESSION_COOKIE_SECURE"] = False
        app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None
        with app_comms.app.test_client() as c:
            resp = c.get("/api/status")
            assert resp.status_code == 401

    def test_returns_expected_keys(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        sys.modules.pop("app_comms", None)  # force fresh import with test SECRET_KEY
        import app_comms
        app_comms.app.config["TESTING"] = True
        app_comms.app.config["SESSION_COOKIE_SECURE"] = False
        app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None
        monkeypatch.setattr(app_comms, "_fetch_agent_status", lambda: [])
        monkeypatch.setattr(app_comms, "_fetch_platform_health", lambda: {"db": "healthy"})
        with app_comms.app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = 1
            resp = c.get("/api/status")
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert "agents" in data
            assert "platform" in data


class TestTerminalEndpoints:
    def test_snapshot_unauthenticated_returns_401(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        sys.modules.pop("app_comms", None)
        import app_comms
        app_comms.app.config["TESTING"] = True
        app_comms.app.config["SESSION_COOKIE_SECURE"] = False
        app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None
        with app_comms.app.test_client() as c:
            resp = c.get("/api/terminal/snapshot")
            assert resp.status_code == 401

    def test_snapshot_returns_lines_structure(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        sys.modules.pop("app_comms", None)
        import app_comms
        app_comms.app.config["TESTING"] = True
        app_comms.app.config["SESSION_COOKIE_SECURE"] = False
        app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None
        monkeypatch.setattr(app_comms, "_tmux_capture_claude_code", lambda: ["$ hello", "$ _"])
        with app_comms.app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = 1
            resp = c.get("/api/terminal/snapshot")
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert "lines" in data
            assert isinstance(data["lines"], list)

    def test_terminal_context_injected_in_stream(self, monkeypatch):
        from services import conversation_service
        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: 99)
        monkeypatch.setattr(conversation_service, "save_message", lambda *a, **kw: {"id": 1})
        monkeypatch.setattr(conversation_service, "get_conversation_messages", lambda *a, **kw: [])
        monkeypatch.setattr(conversation_service, "get_session_context", lambda *a, **kw: "")
        monkeypatch.setattr("services.conversation_service._get_system_prompt", lambda: "sys")
        def _fs(sys_p, user_p, user_id=None, capability="conversation", **kw):
            yield "ok"
            yield {"type": "done", "model_used": "m", "agent_name": "A.R.C.H.I.E."}

        monkeypatch.setattr("services.conversation_service.stream_dhq_chat", _fs)
        items = list(conversation_service.stream_send_message(
            user_id=1, message="hi", terminal_context="$ pytest\nPASSED"
        ))
        done_events = [i for i in items if isinstance(i, dict) and i.get("type") == "done"]
        assert len(done_events) == 1

    def test_terminal_context_not_injected_when_none(self, monkeypatch):
        from services import conversation_service
        captured_prompts = []
        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: 99)
        monkeypatch.setattr(conversation_service, "save_message", lambda *a, **kw: {"id": 1})
        monkeypatch.setattr(conversation_service, "get_conversation_messages", lambda *a, **kw: [])
        monkeypatch.setattr(conversation_service, "get_session_context", lambda *a, **kw: "")
        monkeypatch.setattr("services.conversation_service._get_system_prompt", lambda: "base-sys")

        def capture_stream(sys_p, user_p, user_id=None, capability="conversation", **kw):
            captured_prompts.append(sys_p)
            yield "ok"
            yield {"type": "done", "model_used": "m", "agent_name": "A.R.C.H.I.E."}

        monkeypatch.setattr("services.conversation_service.stream_dhq_chat", capture_stream)
        list(conversation_service.stream_send_message(user_id=1, message="hi", terminal_context=None))
        assert "[TERMINAL CONTEXT]" not in captured_prompts[0]


class TestDelegationRoutes:
    def test_delegation_submit_unauthenticated(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        sys.modules.pop("app_comms", None)
        import app_comms
        app_comms.app.config["TESTING"] = True
        app_comms.app.config["SESSION_COOKIE_SECURE"] = False
        app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None
        with app_comms.app.test_client() as c:
            resp = c.post("/api/delegation/submit",
                          json={"capability": "health_check", "reason": "test"})
            assert resp.status_code == 401

    def test_delegation_submit_calls_platform(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        sys.modules.pop("app_comms", None)
        import app_comms
        app_comms.app.config["TESTING"] = True
        app_comms.app.config["SESSION_COOKIE_SECURE"] = False
        app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None

        class MockResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"task_id": 42, "status": "queued",
                                    "capability": "health_check", "reason": "test"}

        monkeypatch.setattr(app_comms, "_call_platform_delegation_submit",
                            lambda cap, reason, args: MockResp().json())

        with app_comms.app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = 1
            resp = c.post("/api/delegation/submit",
                          json={"capability": "health_check", "reason": "test"})
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["task_id"] == 42
            assert data["status"] == "queued"

    def test_delegate_marker_stripped_from_response(self, monkeypatch):
        from services import conversation_service
        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: 1)
        monkeypatch.setattr(conversation_service, "save_message", lambda *a, **kw: {"id": 1})
        monkeypatch.setattr(conversation_service, "get_conversation_messages", lambda *a, **kw: [])
        monkeypatch.setattr(conversation_service, "get_session_context", lambda *a, **kw: "")
        monkeypatch.setattr("services.conversation_service._get_system_prompt", lambda: "sys")
        def _fs(sys_p, user_p, user_id=None, capability="conversation", **kw):
            yield "Hello! "
            yield '{{DELEGATE capability="health_check" reason="check VPS"}}'
            yield {"type": "done", "model_used": "m", "agent_name": "A.R.C.H.I.E."}

        monkeypatch.setattr("services.conversation_service.stream_dhq_chat", _fs)
        items = list(conversation_service.stream_send_message(user_id=1, message="hi"))
        tokens = [i for i in items if isinstance(i, str)]
        delegation_events = [i for i in items if isinstance(i, dict) and i.get("type") == "delegation_detected"]
        done_events = [i for i in items if isinstance(i, dict) and i.get("type") == "done"]
        full_text = "".join(tokens)
        assert "{{DELEGATE" not in full_text
        assert len(delegation_events) == 1
        assert delegation_events[0]["capability"] == "health_check"
        assert len(done_events) == 1


class TestPlanningRequest:
    def test_planning_prompt_injected_when_is_plan_request(self, monkeypatch):
        from services import conversation_service
        captured = []
        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: 1)
        monkeypatch.setattr(conversation_service, "save_message", lambda *a, **kw: {"id": 1})
        monkeypatch.setattr(conversation_service, "get_conversation_messages", lambda *a, **kw: [])
        monkeypatch.setattr(conversation_service, "get_session_context", lambda *a, **kw: "")
        monkeypatch.setattr("services.conversation_service._get_system_prompt", lambda: "base-sys")

        def capture_ollama(sys_p, user_p, user_id=None, capability="conversation", **kw):
            captured.append(sys_p)
            yield "plan"
            yield {"type": "done", "model_used": "m", "agent_name": "A.R.C.H.I.E."}

        monkeypatch.setattr("services.conversation_service.stream_dhq_chat", capture_ollama)
        list(conversation_service.stream_send_message(
            user_id=1, message="build a scheduler", is_plan_request=True
        ))
        assert "[FEATURE PLANNING]" in captured[0]

    def test_planning_prompt_not_injected_by_default(self, monkeypatch):
        from services import conversation_service
        captured = []
        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: 1)
        monkeypatch.setattr(conversation_service, "save_message", lambda *a, **kw: {"id": 1})
        monkeypatch.setattr(conversation_service, "get_conversation_messages", lambda *a, **kw: [])
        monkeypatch.setattr(conversation_service, "get_session_context", lambda *a, **kw: "")
        monkeypatch.setattr("services.conversation_service._get_system_prompt", lambda: "base-sys")

        def capture_ollama(sys_p, user_p, user_id=None, capability="conversation", **kw):
            captured.append(sys_p)
            yield "normal"
            yield {"type": "done", "model_used": "m", "agent_name": "A.R.C.H.I.E."}

        monkeypatch.setattr("services.conversation_service.stream_dhq_chat", capture_ollama)
        list(conversation_service.stream_send_message(
            user_id=1, message="hello", is_plan_request=False
        ))
        assert "[FEATURE PLANNING]" not in captured[0]


class TestRepairCount:
    def test_repair_count_unauthenticated(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        sys.modules.pop("app_comms", None)
        import app_comms
        app_comms.app.config["TESTING"] = True
        app_comms.app.config["SESSION_COOKIE_SECURE"] = False
        app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None
        with app_comms.app.test_client() as c:
            resp = c.get("/api/repair/count")
            assert resp.status_code == 401

    def test_repair_count_proxies_platform(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        sys.modules.pop("app_comms", None)
        import app_comms
        app_comms.app.config["TESTING"] = True
        app_comms.app.config["SESSION_COOKIE_SECURE"] = False
        app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None
        monkeypatch.setattr(app_comms, "_call_platform_repair_count", lambda: {"count": 5})
        with app_comms.app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = 1
            resp = c.get("/api/repair/count")
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["count"] == 5
