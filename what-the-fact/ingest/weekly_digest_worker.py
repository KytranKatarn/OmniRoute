"""weekly_digest_worker.py — Weekly bias digest email for WTF subscribers.

Sends every Monday. Queries users with active alerts (subscriber-only feature)
and sends each a personalized weekly summary: top stories by bias band, outlet
averages, fact-check highlights.

Default OFF. Set WTF_WEEKLY_DIGEST_ENABLED=true.
SMTP: WTF_SMTP_HOST, WTF_SMTP_PORT, WTF_SMTP_USER, WTF_SMTP_PASS (same as alerts).
"""
from __future__ import annotations

import datetime
import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest")

_ENABLED = os.environ.get("WTF_WEEKLY_DIGEST_ENABLED", "false").lower() == "true"
# Default = the cluster SMTP egress relay on Citadel/boston-2 (mesh IP, port 25,
# unauthenticated from mesh peers, handles DKIM). The relay moved here from
# outpost-us in the 2026-08-29 outpost sunset (decision #1051); outpost-us keeps
# a rollback relay until Mar 2027. Hub Stalwart :587 is NOT reachable from
# Citadel containers (connection closed).
# Setting WTF_SMTP_PASS switches to authenticated STARTTLS submission instead.
_SMTP_HOST = os.environ.get("WTF_SMTP_HOST", "100.64.0.10")
_SMTP_PORT = int(os.environ.get("WTF_SMTP_PORT", "25"))
_SMTP_USER = os.environ.get("WTF_SMTP_USER", "archie@kytranempowerment.com")
_SMTP_PASS = os.environ.get("WTF_SMTP_PASS", "")
_FROM_ADDR = os.environ.get("WTF_SMTP_FROM", "digest@kytranempowerment.com")
_APP_URL = os.environ.get("WTF_APP_URL", "https://what-the-fact.com")

_BAND_LABELS = {
    "left": "Left", "center-left": "Center-Left", "center": "Center",
    "center-right": "Center-Right", "right": "Right", "unscored": "Unscored",
}


def _fetch_digest_data(engine, schema: str) -> dict:
    """Fetch 7-day summary stats and top articles per bias band."""
    with engine.connect() as c:
        stats = c.execute(text(f"""
            SELECT
              (SELECT COUNT(*) FROM {schema}.articles
               WHERE published_at > NOW() - INTERVAL '7 days') AS total_articles,
              (SELECT COUNT(*) FROM {schema}.articles
               WHERE ai_analyzed=TRUE AND published_at > NOW() - INTERVAL '7 days') AS analyzed,
              (SELECT COUNT(DISTINCT article_id) FROM {schema}.fact_checks
               WHERE checked_at > NOW() - INTERVAL '7 days') AS fact_checked
        """)).mappings().first()

        band_counts = c.execute(text(f"""
            SELECT COALESCE(b.band, 'unscored') AS band, COUNT(*) AS n
            FROM {schema}.articles a
            LEFT JOIN {schema}.bias_scores b ON b.article_id = a.id
            WHERE a.published_at > NOW() - INTERVAL '7 days'
            GROUP BY 1 ORDER BY 2 DESC
        """)).mappings().all()

        top_articles = c.execute(text(f"""
            SELECT a.id, a.title, a.url, b.band, b.score,
                   s.name AS source, a.published_at
            FROM {schema}.articles a
            JOIN {schema}.sources s ON s.id = a.source_id
            LEFT JOIN {schema}.bias_scores b ON b.article_id = a.id
            WHERE a.ai_analyzed=TRUE AND a.published_at > NOW() - INTERVAL '7 days'
            ORDER BY b.score DESC NULLS LAST
            LIMIT 10
        """)).mappings().all()

        outlet_avgs = c.execute(text(f"""
            SELECT s.name, obs.band, obs.avg_score
            FROM {schema}.outlet_bias_scores obs
            JOIN {schema}.sources s ON s.id = obs.source_id
            ORDER BY ABS(obs.avg_score) DESC NULLS LAST
            LIMIT 10
        """)).mappings().all()

    return {
        "stats": dict(stats) if stats else {},
        "band_counts": [dict(r) for r in band_counts],
        "top_articles": [dict(r) for r in top_articles],
        "outlet_avgs": [dict(r) for r in outlet_avgs],
    }


def _fetch_recipients(engine, schema: str) -> list[tuple[str, str | None]]:
    """Return (email, unsub_token|None) — active alert subscribers UNION the
    public newsletter list (#4899). When an address is on both, the newsletter
    row wins so the email carries a working one-click unsubscribe token;
    alert-only recipients keep the /account manage link (token None)."""
    with engine.connect() as c:
        rows = c.execute(text(f"""
            SELECT DISTINCT ON (email) email, unsub_token::text AS token
            FROM (
                SELECT LOWER(user_email) AS email, NULL::uuid AS unsub_token, 0 AS pri
                FROM {schema}.user_alerts
                WHERE active = TRUE AND user_email IS NOT NULL AND user_email != ''
                UNION ALL
                SELECT LOWER(email), unsub_token, 1
                FROM {schema}.newsletter_subscribers
                WHERE active = TRUE
            ) u
            ORDER BY email, pri DESC
        """)).fetchall()
    return [(r[0], r[1]) for r in rows]


def _already_sent_this_week(engine, schema: str) -> bool:
    """Check system_config to see if digest was sent this week."""
    with engine.connect() as c:
        row = c.execute(text(f"""
            SELECT config_value FROM system_config
            WHERE config_key = 'wtf_weekly_digest_last_sent'
        """)).fetchone()
    if not row:
        return False
    try:
        last = datetime.date.fromisoformat(row[0])
        return (datetime.date.today() - last).days < 7
    except Exception:
        return False


def _mark_sent(engine, schema: str) -> None:
    """Record today as the last send date."""
    today = datetime.date.today().isoformat()
    with engine.begin() as c:
        c.execute(text(f"""
            INSERT INTO system_config (config_key, config_value, updated_at)
            VALUES ('wtf_weekly_digest_last_sent', :v, NOW())
            ON CONFLICT (config_key) DO UPDATE SET config_value = :v, updated_at = NOW()
        """), {"v": today})


def _build_html(data: dict, week_str: str) -> str:
    stats = data["stats"]
    bands = {r["band"]: r["n"] for r in data["band_counts"]}
    articles = data["top_articles"]
    outlets = data["outlet_avgs"]

    band_rows = ""
    for band, label in _BAND_LABELS.items():
        n = bands.get(band, 0)
        bar = min(100, int(n / max(stats.get("total_articles", 1), 1) * 100))
        band_rows += f'<tr><td style="color:#9ca3af;font-size:12px;padding:3px 8px 3px 0;width:100px;">{label}</td><td style="font-size:12px;color:#e0e0e0;padding:3px 0;"><div style="width:{bar}%;background:#374151;height:6px;border-radius:2px;display:inline-block;"></div> {n}</td></tr>'

    article_rows = ""
    BAND_EMOJIS = {"left": "◀", "center-left": "◁", "center": "○", "center-right": "▷", "right": "▶"}
    for a in articles[:7]:
        emoji = BAND_EMOJIS.get(a.get("band", ""), "○")
        article_rows += f'<tr><td style="padding:6px 0;border-bottom:1px solid #1f2937;"><a href="{_APP_URL}/article/{a["id"]}" style="color:#60a5fa;text-decoration:none;font-size:13px;">{(a["title"] or "")[:90]}</a><br><span style="color:#4b5563;font-size:11px;">{emoji} {a.get("band","").upper() or "—"} · {a.get("source","")}</span></td></tr>'

    outlet_rows = ""
    for o in outlets[:6]:
        outlet_rows += f'<tr><td style="color:#9ca3af;font-size:12px;padding:3px 0;width:160px;">{o["name"][:25]}</td><td style="color:#e0e0e0;font-size:12px;">{(o["band"] or "—").upper()} ({"{:.2f}".format(float(o["avg_score"])) if o["avg_score"] else "—"})</td></tr>'

    return f"""<!DOCTYPE html><html><body style="background:#050d1a;color:#e0e0e0;font-family:Georgia,serif;margin:0;padding:0;">
<div style="max-width:560px;margin:0 auto;padding:24px 16px;">
  <div style="border-bottom:2px solid #dc2626;padding-bottom:12px;margin-bottom:20px;">
    <div style="font-size:10px;letter-spacing:3px;color:#dc2626;text-transform:uppercase;">What The Fact</div>
    <h1 style="font-size:22px;margin:4px 0 0;color:#f0f0f0;">Weekly Bias Digest</h1>
    <div style="font-size:11px;color:#6b7280;margin-top:4px;">{week_str}</div>
  </div>
  <div style="display:flex;gap:20px;margin-bottom:20px;flex-wrap:wrap;">
    <div><div style="font-size:24px;color:#e0e0e0;font-weight:700;">{stats.get("total_articles",0)}</div><div style="font-size:10px;color:#4b5563;letter-spacing:1px;text-transform:uppercase;">Articles</div></div>
    <div><div style="font-size:24px;color:#e0e0e0;font-weight:700;">{stats.get("analyzed",0)}</div><div style="font-size:10px;color:#4b5563;letter-spacing:1px;text-transform:uppercase;">AI Analyzed</div></div>
    <div><div style="font-size:24px;color:#e0e0e0;font-weight:700;">{stats.get("fact_checked",0)}</div><div style="font-size:10px;color:#4b5563;letter-spacing:1px;text-transform:uppercase;">Fact Checked</div></div>
  </div>
  <h2 style="font-size:14px;color:#9ca3af;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">Bias Distribution</h2>
  <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">{band_rows}</table>
  <h2 style="font-size:14px;color:#9ca3af;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">Top Scored Stories</h2>
  <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">{article_rows}</table>
  <h2 style="font-size:14px;color:#9ca3af;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">Outlet Bias Averages</h2>
  <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">{outlet_rows}</table>
  <div style="border-top:1px solid #1f2937;padding-top:16px;font-size:11px;color:#4b5563;">
    <a href="{_APP_URL}" style="color:#60a5fa;text-decoration:none;">what-the-fact.com</a>
    · __UNSUB_LINK__
    · Built on radical transparency.
  </div>
</div></body></html>"""


def _send_digest(recipient: str, html_body: str, week_str: str) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"WTF Weekly Bias Digest — {week_str}"
        msg["From"] = _FROM_ADDR
        msg["To"] = recipient
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as srv:
            if _SMTP_PASS:
                # Authenticated STARTTLS submission (mailbox creds provided)
                ctx = ssl.create_default_context()
                srv.starttls(context=ctx)
                srv.login(_SMTP_USER, _SMTP_PASS)
            # else: mesh egress relay — no auth, relay handles DKIM/signing
            srv.sendmail(_FROM_ADDR, [recipient], msg.as_string())
        return True
    except Exception as exc:
        logger.warning("[weekly_digest] send to %s failed: %s", recipient, exc)
        return False


_HEARTBEAT_TASK = "weekly_digest"


def _heartbeat(engine, *, sent: int = 0, error: str | None = None) -> None:
    """Write one parliament.ingest_log row so drift_guard can see this task at all.

    ⚠️ WHY THIS EXISTS (#6233): the digest crashed EVERY Monday for weeks with zero
    observable signal — run.py logs only when sent/errors is truthy, the crash
    log.exception lines die with each container rebuild, and there was no heartbeat.
    drift_guard._source_freshness measures MAX(run_at) FILTER (error = ''), i.e. the
    last SUCCESS, so a task with no rows at all is invisible rather than alarming.
    This is the same failure the _MAX_AGE_DAYS comment block documents for the five
    feeds that rotted 2-3 months.

    ⚠️ NEVER call this on the not_monday or disabled paths. The worker returns
    not_monday six days out of seven; writing a success row there would keep the
    freshness alarm permanently green and reproduce the exact "unmonitored while
    APPEARING monitored" bug this is meant to close. A heartbeat must mean
    "the weekly send actually ran", not "the process woke up".

    Never raises: a bookkeeping failure must not take down the send.
    """
    try:
        with engine.begin() as conn:
            if error:
                conn.execute(
                    text(
                        "INSERT INTO parliament.ingest_log (task, error) "
                        "VALUES (:t, :e)"
                    ),
                    {"t": _HEARTBEAT_TASK, "e": str(error)[:500]},
                )
            else:
                conn.execute(
                    text(
                        "INSERT INTO parliament.ingest_log "
                        "(task, records_fetched, records_upserted) VALUES (:t, :n, :n)"
                    ),
                    {"t": _HEARTBEAT_TASK, "n": sent},
                )
    except Exception as exc:  # pragma: no cover - bookkeeping must never break the send
        logger.warning("[weekly_digest] heartbeat write failed: %s", exc)


def run_weekly_digest(engine, schema: str = "wtf") -> dict:
    """Send weekly digest to all active alert subscribers. Returns counters.

    Writes a parliament.ingest_log heartbeat on every path that represents a real
    weekly run — success, all-sends-failed, and crash — so drift_guard alarms on a
    missed Monday. See _heartbeat for which paths deliberately write nothing.

    Never raises. A digest that crashes the ingest loop is worse than one that
    records the error and retries next week (same contract as
    securities_issuer_contracts.run_issuer_contracts_sync).
    """
    if not _ENABLED:
        return {"sent": 0, "errors": 0, "stopped": "disabled"}

    today = datetime.date.today()
    if today.weekday() != 0:  # Monday only
        return {"sent": 0, "errors": 0, "stopped": "not_monday"}

    try:
        return _run_weekly_digest_inner(engine, schema, today)
    except Exception as exc:
        # Previously this propagated into run.py, which logs only when sent/errors
        # is truthy — so the crash vanished. Now it lands in the heartbeat.
        logger.exception("[weekly_digest] run failed: %s", exc)
        _heartbeat(engine, error=str(exc))
        return {"sent": 0, "errors": 0, "stopped": "error", "error": str(exc)}


def _run_weekly_digest_inner(engine, schema: str, today: datetime.date) -> dict:
    """The Monday body. Raises on failure — run_weekly_digest converts that to a
    heartbeat + an error dict."""
    if _already_sent_this_week(engine, schema):
        # A real successful state for this week, not a no-op: the send happened.
        _heartbeat(engine, sent=0)
        return {"sent": 0, "errors": 0, "stopped": "already_sent"}

    recipients = _fetch_recipients(engine, schema)
    if not recipients:
        # A genuine run that had nothing to send. Recorded as a success so an empty
        # list does not read as a dead job — the subscriber count is a separate signal.
        _heartbeat(engine, sent=0)
        return {"sent": 0, "errors": 0, "stopped": "no_subscribers"}

    data = _fetch_digest_data(engine, schema)
    week_str = today.strftime("Week of %B %d, %Y")
    html_body = _build_html(data, week_str)

    sent = errors = 0
    for email, token in recipients:
        # CASL: newsletter recipients get a one-click tokenized unsubscribe;
        # alert-only recipients (no token) keep the account manage link.
        if token:
            unsub = (f'<a href="{_APP_URL}/newsletter/unsubscribe?token={token}" '
                     f'style="color:#4b5563;text-decoration:none;">Unsubscribe</a>')
        else:
            unsub = (f'<a href="{_APP_URL}/account" '
                     f'style="color:#4b5563;text-decoration:none;">Manage subscription</a>')
        if _send_digest(email, html_body.replace("__UNSUB_LINK__", unsub), week_str):
            sent += 1
        else:
            errors += 1

    if sent > 0:
        _mark_sent(engine, schema)
        logger.info("[weekly_digest] sent=%d errors=%d week=%s", sent, errors, week_str)
        _heartbeat(engine, sent=sent)
    else:
        # Recipients existed but NOTHING got through. That is a failed weekly run,
        # not a quiet one — record it as an error so drift_guard's last-SUCCESS
        # clock keeps ticking and the freshness alarm eventually fires.
        logger.error(
            "[weekly_digest] every send failed: recipients=%d errors=%d week=%s",
            len(recipients), errors, week_str,
        )
        _heartbeat(engine, error=f"all {errors} sends failed for {len(recipients)} recipients")

    return {"sent": sent, "errors": errors, "stopped": "complete"}
