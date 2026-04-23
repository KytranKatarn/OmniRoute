"""
ARCHIE Chat — Code Tab REST Endpoints

All OpenCode session lifecycle endpoints.
Registered via register_code_routes(bp) pattern (ADR-045).
"""

import json as _json
import queue as _queue

from flask import Response, jsonify, request, stream_with_context
from flask_login import login_required

from . import code_service


def register_code_routes(bp):

    def _require_session(session_id):
        session = code_service.get_session(session_id)
        if not session:
            return None, (jsonify({"error": "session not found"}), 404)
        return session, None

    @bp.route("/api/code-sessions", methods=["GET"])
    @login_required
    def list_code_sessions():
        view = request.args.get("view", "source")
        sessions = code_service.list_sessions(view)
        return jsonify({"sessions": sessions})

    @bp.route("/api/code-sessions", methods=["POST"])
    @login_required
    def create_code_session():
        data = request.get_json() or {}
        session_id = code_service.create_session(
            title=data.get("title", "New Session"),
            source=data.get("source", "user"),
            tier=int(data.get("tier", 2)),
            created_by="user",
            project_id=data.get("project_id"),
            proposal_id=data.get("proposal_id"),
        )
        return jsonify({"session_id": session_id}), 201

    @bp.route("/api/code-sessions/<int:session_id>", methods=["GET"])
    @login_required
    def get_code_session(session_id):
        session = code_service.get_session(session_id)
        if not session:
            return jsonify({"error": "not found"}), 404
        events = code_service.get_session_events(session_id)
        return jsonify({"session": session, "events": events})

    @bp.route("/api/code-sessions/<int:session_id>/start", methods=["POST"])
    @login_required
    def start_code_session(session_id):
        session, err = _require_session(session_id)
        if err:
            return err
        data = request.get_json() or {}
        pid = code_service.start_opencode(session_id, initial_instruction=data.get("instruction"))
        return jsonify({"pid": pid})

    @bp.route("/api/code-sessions/<int:session_id>/resume", methods=["POST"])
    @login_required
    def resume_code_session(session_id):
        session, err = _require_session(session_id)
        if err:
            return err
        code_service.resume_session(session_id)
        return jsonify({"ok": True})

    @bp.route("/api/code-sessions/<int:session_id>/abort", methods=["POST"])
    @login_required
    def abort_code_session(session_id):
        session, err = _require_session(session_id)
        if err:
            return err
        code_service.terminate_session(session_id, final_status="paused")
        return jsonify({"ok": True})

    @bp.route("/api/code-sessions/<int:session_id>/finalize", methods=["POST"])
    @login_required
    def finalize_code_session(session_id):
        session, err = _require_session(session_id)
        if err:
            return err
        code_service.finalize_session(session_id)
        return jsonify({"ok": True})

    @bp.route("/api/code-sessions/<int:session_id>/message", methods=["POST"])
    @login_required
    def message_code_session(session_id):
        session, err = _require_session(session_id)
        if err:
            return err
        data = request.get_json() or {}
        text = data.get("text", "")
        code_service.send_to_opencode(session_id, text)
        return jsonify({"ok": True})

    @bp.route("/api/code-sessions/<int:session_id>/mode", methods=["POST"])
    @login_required
    def set_code_session_mode(session_id):
        session, err = _require_session(session_id)
        if err:
            return err
        data = request.get_json() or {}
        raw = bool(data.get("raw", False))
        code_service.set_session_raw_mode(session_id, raw)
        return jsonify({"ok": True})

    @bp.route("/api/code-sessions/<int:session_id>/stream")
    @login_required
    def stream_code_session(session_id):
        session, err = _require_session(session_id)
        if err:
            return err

        import uuid as _uuid

        conn_id = str(_uuid.uuid4())

        # Register per-connection queue in _SSE_QUEUES as a nested dict
        # _SSE_QUEUES[session_id] is a dict: {conn_id: queue.Queue}
        if session_id not in code_service._SSE_QUEUES:
            code_service._SSE_QUEUES[session_id] = {}
        q = _queue.Queue(maxsize=200)
        code_service._SSE_QUEUES[session_id][conn_id] = q

        past = code_service.get_session_events(session_id, limit=50)

        def generate():
            try:
                for evt in past:
                    yield f"data: {_json.dumps(evt, default=str)}\n\n"
                while True:
                    try:
                        event = q.get(timeout=30)
                        if event is None:
                            break
                        yield f"data: {_json.dumps(event, default=str)}\n\n"
                    except _queue.Empty:
                        yield ": keepalive\n\n"
            finally:
                # Clean up this connection's queue
                conns = code_service._SSE_QUEUES.get(session_id, {})
                conns.pop(conn_id, None)
                if not conns:
                    code_service._SSE_QUEUES.pop(session_id, None)

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # WebSocket raw terminal — stdin/stdout passthrough to OpenCode subprocess
    # Wrapped in try/except so the rest of the app works if flask-sock is absent.
    try:
        from flask_sock import Sock as _Sock
        import threading as _threading

        _sock = _Sock()

        @_sock.route("/api/code-sessions/<int:session_id>/terminal", bp=bp)
        def ws_terminal(ws, session_id):
            """Bidirectional raw terminal over WebSocket.

            Switches the session to raw mode so subprocess stdout is written
            into _RAW_QUEUES[session_id] instead of the SSE event queue.
            """
            code_service.set_session_raw_mode(session_id, True)
            raw_q = code_service._RAW_QUEUES.setdefault(session_id, _queue.Queue(maxsize=500))

            # Background thread: drain raw_q → WebSocket
            def _send_output():
                while True:
                    try:
                        chunk = raw_q.get(timeout=1)
                        if chunk is None:
                            break
                        ws.send(chunk)
                    except _queue.Empty:
                        pass
                    except Exception:
                        break

            sender = _threading.Thread(target=_send_output, daemon=True)
            sender.start()

            try:
                # Forward WebSocket input → subprocess stdin
                while True:
                    data = ws.receive(timeout=60)
                    if data is None:
                        break
                    code_service.send_to_opencode(session_id, data)
            finally:
                code_service.set_session_raw_mode(session_id, False)
                raw_q.put(None)  # Signal sender thread to stop

    except ImportError:
        pass  # flask-sock not installed — WS terminal unavailable
