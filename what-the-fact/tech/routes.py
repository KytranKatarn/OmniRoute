import os
from flask import Blueprint, render_template, session, abort, redirect, url_for
from sqlalchemy import create_engine, text

bp = Blueprint("wtf_tech", __name__)
_engine = None


def _db():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    return _engine


def _schema():
    return os.environ.get("WTF_SCHEMA", "wtf")


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/transparency/<int:article_id>")
def transparency(article_id: int):
    S = _schema()
    with _db().begin() as c:
        art = c.execute(text(f"""
            SELECT a.id, a.title, a.url, b.band, b.score, b.rationale, b.heuristic_version
            FROM {S}.articles a LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.id = :id
        """), {"id": article_id}).mappings().first()
        if not art:
            abort(404)
        trail = c.execute(text(f"""
            SELECT event_type, payload, created_at FROM {S}.audit_trail
            WHERE article_id = :id ORDER BY created_at
        """), {"id": article_id}).mappings().all()
    return render_template("transparency.html", a=art, trail=trail)


@bp.get("/dashboard")
def dashboard():
    if "kytran_user" not in session:
        return redirect(url_for("kytran_login", next="/dashboard"))
    return render_template("dashboard.html", user=session["kytran_user"])
