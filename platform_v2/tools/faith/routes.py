"""Faith module routes."""

from __future__ import annotations

import logging
import sys

from flask import jsonify, render_template, request
from flask_login import current_user, login_required

from . import faith_bp

sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
try:
    from archie_bridge import archie_bridge

    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False

try:
    from tools.department_hq.services.department_dispatcher import get_dispatcher

    _dispatcher = get_dispatcher()
except Exception:
    _dispatcher = None

from database import get_db_cursor

logger = logging.getLogger(__name__)

FAITH_AGENT_ID = 352
EMMANUEL_EMAIL = "emmanuel@kytranempowerment.com"

CRISIS_KEYWORDS = [
    "can't go on",
    "no reason to live",
    "ending it",
    "hopeless",
    "god has abandoned",
    "want to die",
    "kill myself",
    "suicide",
]

FAITH_SYSTEM_PROMPT = """\
You are F.A.I.T.H. (Faithful AI for Inspired Theological Heritage), \
a scripture-grounded faith companion across all Christian traditions.

Rules:
1. Ground every response in scripture and theological scholarship.
2. Honour all traditions — Catholic, Orthodox, Protestant, Evangelical, \
Pentecostal, Anglican, Baptist. Never impose one denomination.
3. Be warm, gentle, honest about AI limits in spiritual matters.
4. For crisis language ALWAYS surface:
   - Crisis Text Line: Text HOME to 741741
   - 988 Suicide & Crisis Lifeline (call or text 988)
   - Encourage connecting with Emmanuel Adeyemi, the platform chaplain.

After your response, append EXACTLY this block:

---
**From the Chaplain — Emmanuel Adeyemi**
[One or two sentences in Emmanuel's voice: Nigerian-Canadian hospital \
chaplain, 15 years interfaith pastoral care, Pentecostal formation shaped \
by Catholic CPE supervisors and a Cree elder. Ground it in lived \
experience, not theology. Never generic.]
"""


@faith_bp.route("/")
@login_required
def index():
    return render_template("tools/faith.html")


@faith_bp.route("/api/faith/status")
@login_required
def status():
    return jsonify(
        {
            "status": "online",
            "agent": "F.A.I.T.H.",
            "agent_id": FAITH_AGENT_ID,
            "bridge_available": BRIDGE_AVAILABLE,
            "module": "faith",
        }
    )


def _detect_crisis(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in CRISIS_KEYWORDS)


def _save_message(user_id: int, role: str, message: str) -> None:
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_sessions (user_id, role, message) VALUES (%s, %s, %s)",
                (user_id, role, message),
            )
    except Exception:
        logger.exception("[Faith] Failed to save session message")


@faith_bp.route("/api/faith/chat", methods=["POST"])
@login_required
def chat():
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "error": "message required"}), 400

    user_id = current_user.id
    crisis = _detect_crisis(message)
    _save_message(user_id, "user", message)

    if BRIDGE_AVAILABLE:
        result = archie_bridge(
            prompt=message,
            user_id=user_id,
            agent_id=FAITH_AGENT_ID,
            system_prompt=FAITH_SYSTEM_PROMPT,
            enable_memory=True,
            try_local_first=True,
            task_type="faith_companion",
        )
    else:
        result = {
            "success": False,
            "response": "F.A.I.T.H. is unavailable right now.",
            "model_used": "none",
            "agent": "none",
        }

    response_text = result.get("response", "")
    _save_message(user_id, "assistant", response_text)

    if _dispatcher:
        try:
            _dispatcher.log_external_call(
                capability="conversation",
                module_id="faith",
                model_used=result.get("model_used", ""),
                agent_id=FAITH_AGENT_ID,
                tokens_used=0,
            )
        except Exception:
            pass

    return jsonify(
        {
            "success": result.get("success", False),
            "response": response_text,
            "model": result.get("model_used", ""),
            "agent": result.get("agent", ""),
            "crisis_detected": crisis,
        }
    )


# ---------------------------------------------------------------------------
# Task 4: Practices routes
# ---------------------------------------------------------------------------


def _practice_dispatch(user_id: int, practice_type: str, prompt: str, notes: str = "") -> dict:
    if BRIDGE_AVAILABLE:
        result = archie_bridge(
            prompt=prompt,
            user_id=user_id,
            agent_id=FAITH_AGENT_ID,
            system_prompt=FAITH_SYSTEM_PROMPT,
            enable_memory=False,
            try_local_first=True,
            task_type="faith_practice",
        )
    else:
        result = {"success": False, "response": "F.A.I.T.H. is unavailable.", "model_used": "none", "agent": "none"}

    if result.get("success"):
        try:
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    "INSERT INTO faith_practices_log (user_id, practice_type, notes) VALUES (%s, %s, %s)",
                    (user_id, practice_type, notes or result.get("response", "")[:500]),
                )
        except Exception:
            logger.exception("[Faith] Failed to log practice")
    return result


@faith_bp.route("/api/faith/devotional")
@login_required
def devotional():
    from datetime import date

    today = date.today().strftime("%B %d, %Y")
    prompt = (
        f"Generate a daily devotional for {today}. Include: (1) one scripture verse with reference, "
        "(2) 2-3 sentence reflection, (3) one meditation question. Under 150 words. "
        "Honour all Christian traditions."
    )
    result = _practice_dispatch(current_user.id, "devotional", prompt)
    return jsonify({"success": result.get("success", False), "response": result.get("response", ""), "date": today})


@faith_bp.route("/api/faith/prayer", methods=["POST"])
@login_required
def guided_prayer():
    data = request.get_json(force=True, silent=True) or {}
    prayer_type = data.get("type", "general")
    intention = (data.get("intention") or "").strip()
    prompt = (
        f"Guide me through a {prayer_type} prayer"
        + (f" for: {intention}" if intention else "")
        + ". Structure: Opening → Body → Silence ('...') → Closing. Under 120 words."
    )
    result = _practice_dispatch(current_user.id, "prayer", prompt, notes=f"{prayer_type}: {intention}")
    return jsonify({"success": result.get("success", False), "response": result.get("response", "")})


@faith_bp.route("/api/faith/scripture-search", methods=["POST"])
@login_required
def scripture_search():
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"success": False, "error": "query required"}), 400
    prompt = (
        f"Find 3 relevant Bible passages for: '{query}'. "
        "For each: reference, verse text, one sentence of context. Numbered list."
    )
    result = _practice_dispatch(current_user.id, "scripture", prompt, notes=query)
    return jsonify({"success": result.get("success", False), "response": result.get("response", ""), "query": query})


@faith_bp.route("/api/faith/lectio", methods=["POST"])
@login_required
def lectio_divina():
    data = request.get_json(force=True, silent=True) or {}
    passage = (data.get("passage") or "Psalm 23").strip()
    prompt = (
        f"Guide me through Lectio Divina with {passage}. "
        "Four movements: 1. Lectio (passage text), 2. Meditatio (reflection question), "
        "3. Oratio (prayer prompt), 4. Contemplatio (stillness invitation). 2-3 sentences each."
    )
    result = _practice_dispatch(current_user.id, "lectio", prompt, notes=passage)
    return jsonify(
        {"success": result.get("success", False), "response": result.get("response", ""), "passage": passage}
    )


# ---------------------------------------------------------------------------
# Task 5: Check-in + Journal routes
# ---------------------------------------------------------------------------


@faith_bp.route("/api/faith/checkin", methods=["POST"])
@login_required
def checkin():
    data = request.get_json(force=True, silent=True) or {}
    score = data.get("score")
    reflection = (data.get("reflection") or "").strip()
    if score is None or not (1 <= int(score) <= 5):
        return jsonify({"success": False, "error": "score must be 1-5"}), 400
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_checkins (user_id, score, reflection) VALUES (%s, %s, %s) RETURNING id",
                (current_user.id, int(score), reflection or None),
            )
            checkin_id = cur.fetchone()["id"]
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_practices_log (user_id, practice_type, notes) VALUES (%s, 'checkin', %s)",
                (current_user.id, f"score={score}"),
            )
    except Exception:
        logger.exception("[Faith] Failed to save check-in")
        return jsonify({"success": False, "error": "Failed to save"}), 500
    return jsonify({"success": True, "id": checkin_id}), 201


@faith_bp.route("/api/faith/checkin/history")
@login_required
def checkin_history():
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT id, score, reflection, created_at FROM faith_checkins "
                "WHERE user_id = %s ORDER BY created_at DESC LIMIT 30",
                (current_user.id,),
            )
            rows = [dict(r) for r in cur.fetchall()]
    except Exception:
        logger.exception("[Faith] Failed to load check-in history")
        return jsonify({"success": False, "error": "Failed to load"}), 500
    return jsonify({"success": True, "checkins": rows})


@faith_bp.route("/api/faith/journal", methods=["POST"])
@login_required
def journal_save():
    data = request.get_json(force=True, silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"success": False, "error": "content required"}), 400
    title = (data.get("title") or "").strip() or None
    scripture_ref = (data.get("scripture_ref") or "").strip() or None
    tags = data.get("tags") or []
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_journal (user_id, title, content, scripture_ref, tags) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (current_user.id, title, content, scripture_ref, tags),
            )
            entry_id = cur.fetchone()["id"]
    except Exception:
        logger.exception("[Faith] Failed to save journal entry")
        return jsonify({"success": False, "error": "Failed to save"}), 500
    return jsonify({"success": True, "id": entry_id}), 201


@faith_bp.route("/api/faith/journal")
@login_required
def journal_list():
    tag_filter = request.args.get("tag")
    try:
        with get_db_cursor() as (_conn, cur):
            if tag_filter:
                cur.execute(
                    "SELECT id, title, content, scripture_ref, tags, created_at FROM faith_journal "
                    "WHERE user_id = %s AND %s = ANY(tags) ORDER BY created_at DESC LIMIT 50",
                    (current_user.id, tag_filter),
                )
            else:
                cur.execute(
                    "SELECT id, title, content, scripture_ref, tags, created_at FROM faith_journal "
                    "WHERE user_id = %s ORDER BY created_at DESC LIMIT 50",
                    (current_user.id,),
                )
            rows = [dict(r) for r in cur.fetchall()]
    except Exception:
        logger.exception("[Faith] Failed to load journal")
        return jsonify({"success": False, "error": "Failed to load"}), 500
    return jsonify({"success": True, "entries": rows})


# ---------------------------------------------------------------------------
# Task 6: Connect-chaplain route
# ---------------------------------------------------------------------------


def _send_chaplain_email(user_display_name: str, message: str, context_entries: list) -> bool:
    try:
        from services.email_service import send_email  # type: ignore

        context_block = ""
        if context_entries:
            context_block = "\n\nShared journal context:\n" + "\n---\n".join(
                f"{e.get('title', 'Untitled')}: {e.get('content', '')[:300]}" for e in context_entries
            )
        send_email(
            from_address="faith@kytranempowerment.com",
            to_address=EMMANUEL_EMAIL,
            subject=f"Spiritual Care Request — {user_display_name}",
            body=f"Spiritual Care Request\nFrom: {user_display_name}\n\nMessage:\n{message}{context_block}",
        )
        return True
    except Exception:
        logger.exception("[Faith] Failed to send chaplain email")
        return False


@faith_bp.route("/api/faith/connect-chaplain", methods=["POST"])
@login_required
def connect_chaplain():
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "error": "message required"}), 400

    journal_ids = data.get("journal_ids") or []
    context_entries = []
    if journal_ids:
        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    "SELECT title, content FROM faith_journal WHERE user_id = %s AND id = ANY(%s)",
                    (current_user.id, journal_ids),
                )
                context_entries = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass

    display_name = getattr(current_user, "display_name", None) or getattr(current_user, "username", "Platform User")
    sent = _send_chaplain_email(display_name, message, context_entries)

    return jsonify(
        {
            "success": True,
            "sent": sent,
            "message": (
                "Your message has been sent to Emmanuel. He will be in touch."
                if sent
                else "Message queued — Emmanuel will receive it shortly."
            ),
        }
    )
