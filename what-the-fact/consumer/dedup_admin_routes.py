"""WTF Consumer — Admin review UI for the Shared Entity Graph dedup queue (#3792, #373).

Surfaces shared.merge_review_queue so an admin can resolve pending candidate pairs:
approve (merge), reject (distinct), or defer. Merging MUTATES the canonical graph, so this
gate FAILS CLOSED — it requires WTF_ADMIN_KEY to be configured AND matched via X-Admin-Key
(unlike claim_admin's _require_admin which allows-if-unset). Reuses the already-tested
ingest.entity_graph_dedup.list_pending / decide (decide('same') is revertable via --revert).

  GET  /admin/dedup           -> the review page (shell; data + actions require the key)
  GET  /admin/dedup/queue?n=  -> pending pairs (X-Admin-Key)
  POST /admin/dedup/decide    -> {queue_id, decision} resolve a pair (X-Admin-Key)
"""
import json
import os

from flask import Blueprint, Response, jsonify, render_template, request

dedup_admin_bp = Blueprint("dedup_admin", __name__)


def _require_dedup_admin():
    """Fail-CLOSED: deny unless WTF_ADMIN_KEY is set AND matches X-Admin-Key. Destructive
    merges must never be open, even when the key is unconfigured."""
    key = os.getenv("WTF_ADMIN_KEY", "")
    if not key:
        return jsonify({"error": "admin key not configured (set WTF_ADMIN_KEY)"}), 503
    if request.headers.get("X-Admin-Key") != key:
        return jsonify({"error": "unauthorized"}), 401
    return None


@dedup_admin_bp.get("/admin/dedup")
def dedup_review_page():
    # The shell is harmless without the key — the queue + decide endpoints are gated.
    return render_template("dedup_review.html")


@dedup_admin_bp.get("/admin/dedup/queue")
def dedup_queue():
    err = _require_dedup_admin()
    if err:
        return err
    try:
        n = min(max(int(request.args.get("n", 50)), 1), 200)
    except (TypeError, ValueError):
        n = 50
    from ingest.entity_graph_dedup import list_pending
    # json.dumps(default=str) — list_pending rows carry Decimal similarity + jsonb (KB #269068).
    return Response(json.dumps({"pending": list_pending(n)}, default=str),
                    mimetype="application/json")


@dedup_admin_bp.post("/admin/dedup/decide")
def dedup_decide():
    err = _require_dedup_admin()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    qid = body.get("queue_id")
    decision = body.get("decision")
    if not qid or decision not in ("same", "distinct", "defer"):
        return jsonify({"error": "queue_id + decision (same|distinct|defer) required"}), 400
    from ingest.entity_graph_dedup import decide
    try:
        return Response(json.dumps(decide(int(qid), decision, by="web_review"), default=str),
                        mimetype="application/json")
    except Exception as exc:  # surface DB/logic errors without leaking a traceback
        return jsonify({"error": str(exc)[:300]}), 500
