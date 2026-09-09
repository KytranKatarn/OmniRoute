"""
Telegram Gateway — Bot handlers, message routing, notification forwarding

Uses python-telegram-bot v21+ (async).
Messages route through the orchestration engine for AI responses.

Author: A.R.C.H.I.E. Platform
Created: 2026-02-17
"""

import asyncio
import json
import logging
import os
from db import _get_db_password
import secrets
import sys
import threading
from datetime import datetime, timedelta
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from db import get_db

# Module-level import: resolve platform_v2 path once at startup rather than on
# every _send_telegram_message call in a long-running process.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "platform_v2"))
try:
    from services.telegram_service import send as _telegram_service_send
except ImportError:
    _telegram_service_send = None

logger = logging.getLogger("telegram_gateway")


class TelegramGateway:
    """
    Telegram bot gateway for ARCHIE.

    Commands: /start, /link, /status, /approve, /inbox, /briefing
    Messages route through orchestration engine.
    Notifications forwarded based on user rules.
    """

    def __init__(self, bot_token: str, flask_app=None):
        self.bot_token = bot_token
        self.flask_app = flask_app
        self._running = False
        self._thread = None
        self._application = None
        self._loop = None

    def start(self):
        """Start the Telegram bot in a background thread."""
        if self._running:
            logger.warning("Telegram bot already running")
            return

        self._thread = threading.Thread(target=self._run_bot, daemon=True, name="telegram-bot")
        self._thread.start()
        self._running = True
        logger.info("Telegram gateway started")

    def stop(self):
        """Stop the Telegram bot.

        Sets _running=False which causes the _run() coroutine's while loop
        to exit, triggering graceful shutdown (updater.stop → app.stop → app.shutdown).
        """
        self._running = False
        logger.info("Telegram gateway stopping (will shutdown within ~1s)")

    @property
    def is_running(self):
        return self._running

    def _run_bot(self):
        """Run the bot event loop in a separate thread.

        Uses lower-level initialize/start/polling instead of run_polling()
        because run_polling() registers signal handlers which only work
        in the main thread.
        """
        try:
            from telegram.ext import (
                ApplicationBuilder,
                CallbackQueryHandler,
                CommandHandler,
                MessageHandler,
                filters,
            )

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop

            app = ApplicationBuilder().token(self.bot_token).build()
            self._application = app

            # Register handlers
            app.add_handler(CommandHandler("start", self._cmd_start))
            app.add_handler(CommandHandler("link", self._cmd_link))
            app.add_handler(CommandHandler("status", self._cmd_status))
            app.add_handler(CommandHandler("approve", self._cmd_approve))
            app.add_handler(CommandHandler("inbox", self._cmd_inbox))
            app.add_handler(CommandHandler("briefing", self._cmd_briefing))
            app.add_handler(CommandHandler("cancel", self._cmd_cancel))
            app.add_handler(CommandHandler("heal", self._cmd_heal))
            app.add_handler(CommandHandler("repairs", self._cmd_repairs))
            app.add_handler(CommandHandler("scan", self._cmd_scan))
            app.add_handler(CallbackQueryHandler(self._email_callback, pattern=r"^email_"))
            app.add_handler(CallbackQueryHandler(self._escalation_callback, pattern=r"^esc_"))
            app.add_handler(CallbackQueryHandler(self._node_callback, pattern=r"^node_"))
            app.add_handler(CallbackQueryHandler(self._social_callback, pattern=r"^social_"))
            app.add_handler(CallbackQueryHandler(self._pr_merge_callback, pattern=r"^pr_merge_"))
            app.add_handler(CallbackQueryHandler(self._welfare_callback, pattern=r"^welfare_"))
            app.add_handler(CallbackQueryHandler(self._alert_callback, pattern=r"^alert_"))
            app.add_handler(CallbackQueryHandler(self._callback_handler))
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
            app.add_handler(MessageHandler(filters.VOICE, self._handle_voice))

            logger.info("Telegram bot polling started")

            # Use lower-level API to avoid signal handler issues in non-main thread
            async def _run():
                await app.initialize()
                # drop_pending_updates MUST be False: True silently DISCARDS every
                # button tap made while the gateway is down — on 2026-07-02 four of
                # the owner's five Approve taps were flushed by a container restart
                # (task #4631). Approval taps must never be lost; processing a
                # slightly-stale update on startup is harmless (handlers are
                # id-scoped and idempotent; Telegram retains updates for 24h).
                await app.updater.start_polling(drop_pending_updates=False)
                await app.start()
                # Keep running until stopped
                while self._running:
                    await asyncio.sleep(1)
                await app.updater.stop()
                await app.stop()
                await app.shutdown()

            loop.run_until_complete(_run())

        except Exception as e:
            logger.error(f"Telegram bot crashed: {e}")
            self._running = False

    # ------------------------------------------------------------------
    # Command Handlers
    # ------------------------------------------------------------------

    async def _cmd_start(self, update, context):
        """Handle /start command."""
        tg_user = update.effective_user
        self._ensure_telegram_user(tg_user)

        await update.message.reply_text(
            f"Hello {tg_user.first_name}! I'm A.R.C.H.I.E.\n\n"
            "To get started, link your account:\n"
            "1. Go to the ARCHIE web dashboard > Autonomy > Telegram\n"
            "2. Generate a link code\n"
            "3. Send: /link YOUR_CODE\n\n"
            "Commands:\n"
            "/link CODE - Link your ARCHIE account\n"
            "/status - System status\n"
            "/approve - View pending approvals\n"
            "/inbox - Recent emails\n"
            "/briefing - Daily briefing\n\n"
            "Or just send me a message!"
        )

    async def _cmd_link(self, update, context):
        """Handle /link CODE command to link Telegram to ARCHIE user."""
        tg_user = update.effective_user
        args = context.args

        if not args:
            await update.message.reply_text("Usage: /link YOUR_CODE\nGet a code from the web dashboard.")
            return

        code = args[0].strip()

        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                # Find matching code
                cur.execute(
                    """
                    SELECT id, user_id FROM telegram_users
                    WHERE link_code = %s AND link_code_expires_at > NOW()
                    """,
                    (code,),
                )
                row = cur.fetchone()

                if not row:
                    await update.message.reply_text("Invalid or expired code. Please generate a new one.")
                    return

                # Update with Telegram info
                cur.execute(
                    """
                    UPDATE telegram_users
                    SET telegram_id = %s, telegram_username = %s, first_name = %s, last_name = %s,
                        is_authorized = TRUE, link_code = NULL, link_code_expires_at = NULL, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        tg_user.id,
                        tg_user.username,
                        tg_user.first_name,
                        tg_user.last_name,
                        row["id"],
                    ),
                )

                # Create default notification rule (all notifications)
                cur.execute(
                    """
                    INSERT INTO telegram_notification_rules (telegram_user_id, is_active)
                    VALUES (%s, TRUE)
                    ON CONFLICT DO NOTHING
                    """,
                    (row["id"],),
                )

                conn.commit()

                await update.message.reply_text(
                    "Account linked successfully! You'll now receive notifications here.\n"
                    "Send me any message to chat with ARCHIE."
                )
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Link failed: {e}")
            await update.message.reply_text(f"Link failed: {e}")

    async def _cmd_status(self, update, context):
        """Handle /status command."""
        tg_user = update.effective_user
        user_info = self._get_authorized_user(tg_user.id)

        if not user_info:
            await update.message.reply_text("Please link your account first with /link")
            return

        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                # Unread notifications
                cur.execute("SELECT COUNT(*) as c FROM system_notifications WHERE is_read = FALSE")
                unread = cur.fetchone()["c"]

                # Pending approvals
                cur.execute("SELECT COUNT(*) as c FROM autonomy_approval_queue WHERE status = 'pending'")
                pending = cur.fetchone()["c"]

                # Unread emails
                cur.execute("SELECT COUNT(*) as c FROM email_inbox WHERE is_read = FALSE AND is_archived = FALSE")
                unread_emails = cur.fetchone()["c"]

                await update.message.reply_text(
                    "ARCHIE Status\n"
                    f"Notifications: {unread} unread\n"
                    f"Approvals: {pending} pending\n"
                    f"Emails: {unread_emails} unread"
                )
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_approve(self, update, context):
        """Handle /approve command — show pending approvals with inline keyboards."""
        tg_user = update.effective_user
        user_info = self._get_authorized_user(tg_user.id)
        if not user_info:
            await update.message.reply_text("Please link your account first with /link")
            return

        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT id, action_type, reason, priority, created_at
                    FROM autonomy_approval_queue
                    WHERE status = 'pending'
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 5
                    """
                )
                items = cur.fetchall()

                if not items:
                    await update.message.reply_text("No pending approvals.")
                    return

                for item in items:
                    keyboard = InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton("Approve", callback_data=f"approve_{item['id']}"),
                                InlineKeyboardButton("Reject", callback_data=f"reject_{item['id']}"),
                            ]
                        ]
                    )
                    await update.message.reply_text(
                        f"#{item['id']} | {item['action_type']}\n"
                        f"Priority: {item['priority']} | {item['reason'] or 'No reason'}\n"
                        f"Created: {item['created_at']}",
                        reply_markup=keyboard,
                    )
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_inbox(self, update, context):
        """Handle /inbox command — show recent unread emails."""
        tg_user = update.effective_user
        user_info = self._get_authorized_user(tg_user.id)
        if not user_info:
            await update.message.reply_text("Please link your account first with /link")
            return

        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT from_name, from_address, subject, ai_category, ai_priority, received_at
                    FROM email_inbox
                    WHERE is_read = FALSE AND is_archived = FALSE
                    ORDER BY received_at DESC
                    LIMIT 10
                    """
                )
                emails = cur.fetchall()

                if not emails:
                    await update.message.reply_text("No unread emails.")
                    return

                lines = ["Unread Emails:\n"]
                for e in emails:
                    cat = f"[{e['ai_category']}]" if e.get("ai_category") else ""
                    pri = f"P{e['ai_priority']}" if e.get("ai_priority") else ""
                    name = e["from_name"] or e["from_address"]
                    lines.append(f"{cat}{pri} {name}: {e['subject'] or '(no subject)'}")

                await update.message.reply_text("\n".join(lines))
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_briefing(self, update, context):
        """Handle /briefing command — generate a quick status briefing."""
        tg_user = update.effective_user
        user_info = self._get_authorized_user(tg_user.id)
        if not user_info:
            await update.message.reply_text("Please link your account first with /link")
            return

        # Route through orchestration engine for a briefing
        response = self._orchestrate_message(
            "Give me a brief status update. Include unread notifications, pending approvals, and any important alerts.",
            user_info["user_id"],
            voice_mode=True,
        )
        await update.message.reply_text(response or "Unable to generate briefing right now.")

    # ------------------------------------------------------------------
    # Message Handlers
    # ------------------------------------------------------------------

    def _detect_heal_intent(self, text: str) -> bool:
        """Return True if the message is a self-healing / repair command."""
        t = text.lower().strip()
        return any(
            kw in t
            for kw in [
                "run self-healing",
                "run self healing",
                "self heal",
                "run fixes",
                "apply repairs",
                "deploy all safe",
                "batch deploy",
                "fix all issues",
                "run healing",
                "auto fix",
                "/heal",
                "/repairs",
                "/scan",
                "repair bay status",
                "what needs fixing",
                "deploy queue",
            ]
        )

    async def _handle_heal_request(self, update, text: str) -> None:
        """Run batch self-healing and report results to Telegram."""
        import threading
        import json as _json
        import sys as _sys

        t = text.lower().strip()
        await update.message.reply_text(
            "🔧 F.O.R.G.E. self-healing pipeline starting…\n"
            "Queuing low/medium risk proposals for director auto-review → sandbox gate → deploy."
        )

        def _run():
            try:
                _sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                from services.proposal_service import get_deploy_ready, request_tiered_deploy_approval

                ready = get_deploy_ready()
                proposals = [p for p in ready.get("proposals", []) if p.get("risk_level") in ("low", "medium")][:10]
                results = []
                for p in proposals:
                    r = request_tiered_deploy_approval(p["id"])
                    results.append(
                        {
                            "id": p["id"],
                            "title": p["title"][:50],
                            "approver": r.get("approver"),
                            "queue_id": r.get("queue_id"),
                        }
                    )

                queued = sum(1 for r in results if r.get("queue_id"))
                total_ready = len(ready.get("proposals", []))
                lines = [
                    f"✅ F.O.R.G.E. self-healing queued {queued}/{len(proposals)} proposals",
                    f"📊 Total ready: {total_ready} | Queued: {queued}",
                    "",
                ]
                for r in results[:5]:
                    icon = "🤖" if r.get("queue_id") else "⏭"
                    lines.append(f"{icon} #{r['id']}: {r['title'][:45]} → {r.get('approver', '?')}")
                if len(results) > 5:
                    lines.append(f"… and {len(results)-5} more")
                lines.append("\nmodel_dispatch_worker will execute reviews → sandbox gate → deploy automatically.")

                import asyncio

                asyncio.run_coroutine_threadsafe(update.message.reply_text("\n".join(lines)), self._loop)
            except Exception as e:
                import asyncio

                asyncio.run_coroutine_threadsafe(update.message.reply_text(f"❌ Self-healing error: {e}"), self._loop)

        threading.Thread(target=_run, daemon=True).start()

    async def _cmd_heal(self, update, context):
        """/heal — run self-healing pipeline via Telegram."""
        await self._handle_heal_request(update, "/heal")

    async def _cmd_repairs(self, update, context):
        """/repairs — show ready-to-deploy repair proposals."""
        import sys as _sys

        _sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        try:
            from services.proposal_service import get_deploy_ready

            ready = get_deploy_ready()
            proposals = ready.get("proposals", [])
            if not proposals:
                await update.message.reply_text("✅ No proposals ready to deploy right now.")
                return
            lines = [f"🔧 Repair Bay — {len(proposals)} proposals ready to deploy:\n"]
            for p in proposals[:8]:
                risk = p.get("risk_level", "?")
                icon = "🟢" if risk == "low" else "🔵" if risk == "medium" else "🟡" if risk == "high" else "🔴"
                lines.append(f"{icon} #{p['id']} [{risk}] {p['title'][:55]}")
            if len(proposals) > 8:
                lines.append(f"… and {len(proposals)-8} more. See Repair Bay → Ship tab.")
            lines.append('\nReply "run self-healing" or use /heal to queue auto-fixes.')
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def _cmd_scan(self, update, context):
        """/scan [module] — run P.R.O.B.E. scan on a module."""
        args = context.args
        module = args[0] if args else ""
        import sys as _sys
        import threading as _t

        _sys.path.insert(0, "/mnt/archie_brain/platform_v2")

        await update.message.reply_text(
            f"🔍 Running P.R.O.B.E. scan on {'module: ' + module if module else 'full platform'}…"
        )

        def _run():
            try:
                from services.qa_service import run_suite_for_module

                results = run_suite_for_module(module or "platform", triggered_by="telegram_scan")
                passed = sum(r.get("passed", 0) for r in results)
                total = sum(r.get("total", 0) for r in results)
                icon = "✅" if passed == total else "⚠️"
                import asyncio

                asyncio.run_coroutine_threadsafe(
                    update.message.reply_text(
                        f"{icon} Scan complete: {passed}/{total} tests passed\n" f"Suites run: {len(results)}"
                    ),
                    self._loop,
                )
            except Exception as e:
                import asyncio

                asyncio.run_coroutine_threadsafe(update.message.reply_text(f"❌ Scan error: {e}"), self._loop)

        _t.Thread(target=_run, daemon=True).start()

    def _detect_social_intent(self, text: str):
        """Return (topic, platform) if text is a social post request, else None."""
        import re

        text_lower = text.lower().strip()
        patterns = [
            (
                r"(?:write|create|draft|make|compose)\s+(?:a\s+)?(?:linkedin\s+post|linkedin\s+update)\s+(?:about\s+)?(.+)",
                "linkedin",
            ),
            (r"(?:write|create|draft|make|compose)\s+(?:a\s+)?tweet\s+(?:about\s+)?(.+)", "twitter"),
            (r"post\s+(?:something\s+)?(?:on\s+linkedin\s+)?about\s+(.+)", "linkedin"),
            (r"tweet\s+about\s+(.+)", "twitter"),
            (
                r"(?:write|create|draft|make|compose)\s+(?:a\s+)?(?:social\s+(?:media\s+)?)?post\s+(?:about\s+)?(.+)",
                "both",
            ),
            (r"(?:s\.i\.g\.n\.a\.l\.|signal)[,:\s]+(?:write|post|create|draft)\s+(?:about\s+)?(.+)", "both"),
        ]
        for pattern, platform in patterns:
            m = re.match(pattern, text_lower, re.IGNORECASE)
            if m:
                topic = m.group(1).strip().rstrip(".!?")
                if len(topic) > 5:
                    return topic, platform
        return None

    async def _handle_social_request(self, update, topic: str, platform: str) -> None:
        """Generate a social draft via S.I.G.N.A.L. and send to Telegram for approval."""
        import json
        import urllib.request as _urlreq

        await update.message.reply_text(f"✍️ S.I.G.N.A.L. is writing your {platform} post…")

        api_key = os.getenv("ARCHIE_API_KEY", "dev-api-key-change-in-production")
        kytran_tenant_id = int(os.getenv("KBS_KYTRAN_TENANT_ID", "9908"))

        account_map = {
            "linkedin": (int(os.getenv("KBS_KYTRAN_LINKEDIN_ID", "1")), "Kytran Katarn"),
            "twitter": (int(os.getenv("KBS_KYTRAN_TWITTER_ID", "2")), "Kytran"),
            "both": (int(os.getenv("KBS_KYTRAN_LINKEDIN_ID", "1")), "Kytran Katarn"),
        }
        account_id, account_name = account_map.get(platform, account_map["linkedin"])

        try:
            # Generate content
            payload = json.dumps(
                {
                    "capability": "social_content",
                    "prompt": f"Write a social media post about: {topic}",
                    "platform": platform,
                    "tone": "professional",
                }
            ).encode()
            req = _urlreq.Request(
                "http://localhost:3000/api/signal/dispatch",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                method="POST",
            )
            with _urlreq.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            content = data.get("response", "").strip()
            if not content:
                await update.message.reply_text("⚠️ S.I.G.N.A.L. returned an empty response. Try again.")
                return

            # Save to KBS DB
            from services.social_content_jobs import _save_draft, _notify_telegram

            draft_id = _save_draft(content, account_id, kytran_tenant_id)
            if draft_id:
                _notify_telegram(
                    content, platform if platform != "both" else "linkedin", account_name, draft_id, kytran_tenant_id
                )
            else:
                await update.message.reply_text(
                    f"✅ S.I.G.N.A.L. wrote:\n\n{content}\n\n_(draft could not be saved to KBS)_", parse_mode="Markdown"
                )

        except Exception as exc:
            logger.error("[TelegramGateway] social request failed: %s", exc)
            await update.message.reply_text(f"❌ Generation failed: {exc}")

    async def _handle_message(self, update, context):
        """Handle regular text messages — route through orchestration."""
        # Check for pending email reply FIRST
        pending_reply_id = context.user_data.get("pending_reply_email_id")
        if pending_reply_id:
            await self._send_email_reply(update, context, pending_reply_id)
            return

        # Check for pending S.I.G.N.A.L. draft suggestion
        pending_suggestion_id = context.user_data.get("pending_linkedin_suggestion_id")
        if pending_suggestion_id:
            del context.user_data["pending_linkedin_suggestion_id"]
            await self._handle_linkedin_suggestion(update, context, pending_suggestion_id, update.message.text)
            return

        # Check for pending S.I.G.N.A.L. personal post check-in
        checkin_state = self._get_pending_checkin()
        if checkin_state:
            reply_text = update.message.text or ""
            await update.message.reply_text(
                "✅ Got it — S.I.G.N.A.L. is drafting your personal post with A.R.C.H.I.E.'s briefing + your input."
            )
            import asyncio as _asyncio
            import threading as _threading

            def _do_draft():
                try:
                    import sys

                    sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                    from services.agent_jobs import _draft_personal_post_from_context

                    _draft_personal_post_from_context(reply_text, checkin_state)
                except Exception as _e:
                    logger.error("[TelegramGateway] personal checkin draft failed: %s", _e)

            _threading.Thread(target=_do_draft, daemon=True, name="personal-checkin-draft").start()
            return

        tg_user = update.effective_user
        user_info = self._get_authorized_user(tg_user.id)

        if not user_info:
            await update.message.reply_text("Please link your account first with /link")
            return

        text = update.message.text
        self._log_message(user_info["id"], "in", "text", text)

        # Intercept social post requests before general orchestration
        social = self._detect_social_intent(text)
        if social:
            topic, platform = social
            await self._handle_social_request(update, topic, platform)
            return

        # Intercept self-healing / repair commands
        if self._detect_heal_intent(text):
            await self._handle_heal_request(update, text)
            return

        response = self._orchestrate_message(text, user_info["user_id"], voice_mode=True)
        if response:
            self._log_message(user_info["id"], "out", "text", response)
            await update.message.reply_text(response)
        else:
            await update.message.reply_text("I couldn't process that right now. Please try again.")

    async def _handle_voice(self, update, context):
        """Handle voice messages — download, transcribe, respond."""
        tg_user = update.effective_user
        user_info = self._get_authorized_user(tg_user.id)

        if not user_info:
            await update.message.reply_text("Please link your account first with /link")
            return

        await update.message.reply_text("Voice messages are not yet supported. Please send text.")

    @staticmethod
    async def _safe_answer(query):
        """Ack a callback tap, tolerating stale queries. With drop_pending_updates=False
        (task #4631) taps queued while the gateway was down are REPLAYED on startup —
        Telegram rejects answers to callbacks older than ~1h ('Query is too old') and an
        unguarded answer() would abort the handler BEFORE the tap is processed. The ack
        is cosmetic; processing the tap is not."""
        try:
            await query.answer()
        except Exception as e:
            logger.info(f"[TelegramGateway] callback ack skipped (stale query is ok): {e}")

    async def _callback_handler(self, update, context):
        """Handle inline keyboard callbacks (approve/reject) — fallback for non-esc_ patterns."""
        query = update.callback_query
        await self._safe_answer(query)

        logger.info(f"[TelegramGateway] Generic callback: data={query.data}")

        tg_user = query.from_user
        user_info = self._get_authorized_user(tg_user.id)
        if not user_info:
            await query.edit_message_text("Unauthorized.")
            return

        data = query.data
        if data.startswith("approve_"):
            approval_id = int(data.split("_")[1])
            self._process_approval(approval_id, user_info["user_id"], approved=True)
            await query.edit_message_text(f"Approved #{approval_id}")
        elif data.startswith("reject_"):
            approval_id = int(data.split("_")[1])
            self._process_approval(approval_id, user_info["user_id"], approved=False)
            await query.edit_message_text(f"Rejected #{approval_id}")

    async def _node_callback(self, update, context):
        """Handle node approve/deny buttons from Telegram."""
        query = update.callback_query
        await self._safe_answer(query)

        user_info = self._get_authorized_user(query.from_user.id)
        if not user_info:
            await query.edit_message_text("Unauthorized.")
            return

        data = query.data  # e.g. "node_approve_67" or "node_deny_67"
        try:
            parts = data.split("_")  # ["node", "approve", "67"]
            action = parts[1]
            node_db_id = int(parts[2])

            from psycopg2.extras import RealDictCursor

            conn = psycopg2.connect(
                host=os.getenv("DB_HOST", "192.168.1.200"),
                port=int(os.getenv("DB_PORT", "5432")),
                dbname=os.getenv("DB_NAME", "archie"),
                user=os.getenv("DB_USER", "archie"),
                password=_get_db_password(),
                cursor_factory=RealDictCursor,
            )
            try:
                cur = conn.cursor()
                if action == "approve":
                    cur.execute(
                        "UPDATE remote_nodes SET approval_status = 'approved', approved_by = %s, approved_at = NOW() WHERE id = %s RETURNING node_name",
                        (user_info["user_id"], node_db_id),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    name = row["node_name"] if row else f"#{node_db_id}"
                    await query.edit_message_text(
                        f"✅ Node '{name}' approved by {user_info.get('display_name', 'admin')}"
                    )
                elif action == "deny":
                    cur.execute(
                        "UPDATE remote_nodes SET approval_status = 'rejected' WHERE id = %s RETURNING node_name",
                        (node_db_id,),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    name = row["node_name"] if row else f"#{node_db_id}"
                    await query.edit_message_text(
                        f"❌ Node '{name}' denied by {user_info.get('display_name', 'admin')}"
                    )
                else:
                    await query.edit_message_text(f"Unknown action: {action}")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[TelegramGateway] Node callback error: {e}")
            await query.edit_message_text(f"Error processing node action")

    async def _alert_callback(self, update, context):
        """Handle interactive operational-alert buttons from Telegram (#alert-buttons).

        Callback data: alert_<action>_<alert_key>  — split with maxsplit=2 so an
        alert_key containing '_' (e.g. 'disk_primary', 'hr_1234') is preserved:
          alert_details_<key> — read-only diagnostic, posted as a REPLY (original
                                 alert + its buttons stay intact so you can still snooze)
          alert_snooze_<key>  — suppress this alert_key for 24h (edits msg, clears buttons)
          alert_ack_hr_<id>   — resolve an agent_alerts row (edits msg, clears buttons)
        All actions live in services/alert_actions_service.py and are SAFE — no
        destructive one-tap op (deletes stay on the approval path).
        """
        query = update.callback_query
        await self._safe_answer(query)

        user_info = self._get_authorized_user(query.from_user.id)
        if not user_info:
            await query.edit_message_text("Unauthorized.")
            return

        by = user_info.get("display_name", "Kytran")

        # Markdown alert keys contain '_' → guard every send with a plain-text retry
        # (mirrors telegram_service's own 400 "can't parse entities" fallback).
        async def _out(txt, edit=True):
            fn = query.edit_message_text if edit else query.message.reply_text
            try:
                await fn(txt, parse_mode="Markdown")
            except Exception:
                try:
                    await fn(txt)
                except Exception as _e:
                    logger.debug("[TelegramGateway] alert reply failed: %s", _e)

        data = query.data  # e.g. "alert_snooze_disk_primary" / "alert_ack_hr_1234"
        try:
            parts = data.split("_", 2)  # ["alert", action, key]
            action = parts[1] if len(parts) > 1 else ""
            alert_key = parts[2] if len(parts) > 2 else ""

            from services.alert_actions_service import (
                acknowledge_hr,
                alert_details,
                snooze,
            )

            if action == "details":
                await _out(alert_details(alert_key), edit=False)
            elif action == "snooze":
                await _out(snooze(alert_key, 24, by), edit=True)
            elif action == "ack":
                if alert_key.startswith("hr_"):
                    try:
                        alert_id = int(alert_key.split("_", 1)[1])
                    except (IndexError, ValueError):
                        await _out("⚠️ Malformed alert id.", edit=True)
                        return
                    await _out(acknowledge_hr(alert_id, by), edit=True)
                else:
                    await _out("⚠️ Nothing to acknowledge for this alert.", edit=True)
            else:
                await _out(f"Unknown alert action: {action}", edit=True)
        except Exception as e:
            logger.error(f"[TelegramGateway] Alert callback error: {e}")
            await _out("⚠️ Couldn't complete that alert action.", edit=True)

    async def _welfare_callback(self, update, context):
        """Handle K.I.N. welfare action buttons from Telegram.

        Callback data formats:
          welfare_rest8h_{agent_id}   — grant approved 8h rest cycle
          welfare_snooze_{agent_id}   — snooze alert (K.I.N. will re-alert in 4h)
          welfare_dismiss_{agent_id}  — dismiss alert, no action taken
        """
        query = update.callback_query
        await self._safe_answer(query)

        user_info = self._get_authorized_user(query.from_user.id)
        if not user_info:
            await query.edit_message_text("Unauthorized.")
            return

        data = query.data  # e.g. "welfare_rest8h_42_7" or "welfare_dismiss_7"
        try:
            # data format: "welfare_{action}_{agent_id}" or "welfare_{action}_{agent_id}_{queue_id}"
            parts = data.split("_", 3)  # max 4 parts
            action = parts[1] if len(parts) > 1 else ""
            agent_id = int(parts[2]) if len(parts) > 2 else 0
            # queue_id is optional (present when approval was registered in autonomy_approval_queue)
            queue_id = int(parts[3]) if len(parts) > 3 else None
            approved_by = user_info.get("display_name", "Kytran")

            if action == "rest8h":
                # RealDictCursor is module-level (line 24). Importing it here shadowed it for
                # the whole callback — the mirror image of the psycopg2 defect fixed below.
                conn = psycopg2.connect(
                    host=os.getenv("DB_HOST", "192.168.1.200"),
                    port=int(os.getenv("DB_PORT", "5432")),
                    dbname=os.getenv("DB_NAME", "archie"),
                    user=os.getenv("DB_USER", "archie"),
                    password=_get_db_password(),
                    cursor_factory=RealDictCursor,
                )
                try:
                    cur = conn.cursor()
                    # Get agent name
                    cur.execute("SELECT name, department FROM agents WHERE id = %s", (agent_id,))
                    agent_row = cur.fetchone()
                    agent_name = agent_row["name"] if agent_row else f"Agent #{agent_id}"

                    # Open 8h approved rest cycle
                    cur.execute(
                        """
                        INSERT INTO agent_rest_cycles
                            (agent_id, rest_type, reason, started_at, ended_at,
                             initiated_by, workload_before, stress_at_start, energy_at_start)
                        SELECT %s, 'approved_rest',
                               'Kytran approved 8h rest via Telegram (overwork >12h)',
                               NOW(), NOW() + INTERVAL '8 hours',
                               'telegram_approval',
                               %s::jsonb, 0.9, 0.2
                        WHERE NOT EXISTS (
                            -- block on ANY active rest cycle (overlap fix); the old 30-min
                            -- window let a long active rest slip past and stack a duplicate.
                            SELECT 1 FROM agent_rest_cycles
                            WHERE agent_id = %s
                              AND (ended_at IS NULL OR ended_at > NOW())
                        )
                        """,
                        (agent_id, json.dumps({"approved_by": approved_by}), agent_id),
                    )

                    # Transition agent to winding_down (completes current tasks, then rests)
                    cur.execute(
                        """
                        UPDATE agents
                           SET shift_state = 'winding_down', updated_at = NOW()
                         WHERE id = %s
                           AND shift_state NOT IN ('winding_down', 'cooldown', 'barracked', 'off_duty')
                        """,
                        (agent_id,),
                    )

                    # Reset task counters so agent wakes with full capacity
                    cur.execute(
                        """
                        UPDATE agent_budgets
                           SET current_task_count = 0,
                               last_task_reset_at = NOW(),
                               task_reset_reason  = 'Kytran-approved 8h rest: counters reset',
                               task_reset_by      = 'telegram_approval',
                               updated_at         = NOW()
                         WHERE agent_id = %s
                        """,
                        (agent_id,),
                    )

                    # Mark approval queue row as approved (shows in DHQ Approvals tab)
                    if queue_id:
                        cur.execute(
                            """
                            UPDATE autonomy_approval_queue
                               SET status = 'approved',
                                   approved_at = NOW(),
                                   execution_result = %s::jsonb,
                                   updated_at = NOW()
                             WHERE id = %s
                            """,
                            (
                                json.dumps({"approved_by": approved_by, "action": "rest_8h_granted"}),
                                queue_id,
                            ),
                        )

                    conn.commit()
                    logger.info("[Welfare] %s granted 8h rest for agent %s (id=%d)", approved_by, agent_name, agent_id)
                    await query.edit_message_text(
                        f"😴 *{agent_name}* granted 8h rest.\n\n"
                        f"Agent is winding down current tasks and will be restored "
                        f"automatically at {(datetime.now() + timedelta(hours=8)).strftime('%I:%M %p')}.\n\n"
                        f"_Approved by {approved_by}_"
                    )
                finally:
                    conn.close()

            elif action == "snooze":
                # No action — K.I.N. cooldown_hours=4 on the inbox submission
                # means the next alert arrives in ~4h automatically.
                await query.edit_message_text(
                    f"⏰ Snoozed — K.I.N. will re-alert in ~4 hours if the agent is still overloaded."
                )

            elif action == "dismiss":
                # Mark queue row as rejected so DHQ Approvals tab clears it
                if queue_id:
                    try:
                        # psycopg2 + RealDictCursor are imported at MODULE level (lines 23-24).
                        # Re-importing them HERE made both names function-LOCAL for the whole
                        # of _welfare_callback, so the `rest8h` branch ~100 lines above — which
                        # calls psycopg2.connect() without passing through this block — raised
                        # UnboundLocalError. Same defect as #6022 in agent_loop.py; found by the
                        # sweep added with that fix. The module-level imports do NOT protect you:
                        # a local binding anywhere in a function shadows them everywhere in it.
                        _dc = psycopg2.connect(
                            host=os.getenv("DB_HOST", "192.168.1.200"),
                            port=int(os.getenv("DB_PORT", "5432")),
                            dbname=os.getenv("DB_NAME", "archie"),
                            user=os.getenv("DB_USER", "archie"),
                            password=_get_db_password(),
                            cursor_factory=RealDictCursor,
                        )
                        try:
                            _dcur = _dc.cursor()
                            _dcur.execute(
                                """UPDATE autonomy_approval_queue
                                      SET status='rejected',
                                          rejected_reason='Dismissed by Kytran via Telegram',
                                          updated_at=NOW()
                                    WHERE id=%s""",
                                (queue_id,),
                            )
                            _dc.commit()
                        finally:
                            _dc.close()
                    except Exception as _de:
                        logger.warning("[Welfare] dismiss queue update failed: %s", _de)
                await query.edit_message_text(f"🔕 Welfare alert dismissed. No rest scheduled.")

            else:
                await query.edit_message_text(f"Unknown welfare action: {action}")

        except Exception as e:
            logger.error(f"[TelegramGateway] Welfare callback error: {e}")
            await query.edit_message_text("Error processing welfare action.")

    async def _escalation_callback(self, update, context):
        """Handle escalation buttons (advisory ack, cloud/paid escalate, approval approve/deny/defer)."""
        query = update.callback_query
        await self._safe_answer(query)

        tg_user = query.from_user
        logger.info(f"[TelegramGateway] Escalation callback: data={query.data} from user={tg_user.id}")

        user_info = self._get_authorized_user(tg_user.id)
        if not user_info:
            logger.warning(f"[TelegramGateway] Unauthorized callback from {tg_user.id}")
            await query.edit_message_text("Unauthorized.")
            return

        data = query.data  # e.g. "esc_ack", "esc_cloud", "esc_paid", "esc_approve_47"

        # --- Simple advisory buttons (no ID) ---
        if data == "esc_ack":
            original = query.message.text or ""
            await query.edit_message_text(f"{original}\n\n\u2705 Acknowledged")
            return

        if data == "esc_cloud":
            original = query.message.text or ""
            await query.edit_message_text(
                f"{original}\n\n\u2601\ufe0f Cloud escalation noted. "
                f"Will use cloud contractor for next similar request."
            )
            return

        if data == "esc_paid":
            original = query.message.text or ""
            await query.edit_message_text(
                f"{original}\n\n\U0001f4b3 Paid escalation noted. "
                f"Will request paid contractor approval for next similar request."
            )
            return

        # --- Approval buttons (with ID) ---
        parts = data.split("_", 2)
        if len(parts) < 3:
            await query.edit_message_text("Invalid escalation action")
            return

        action = parts[1]  # approve, deny, defer, suggest
        try:
            approval_id = int(parts[2])
        except ValueError:
            await query.edit_message_text("Invalid escalation ID")
            return

        # Suggest — no DB needed, just store pending state and prompt user
        if action == "suggest":
            context.user_data["pending_linkedin_suggestion_id"] = approval_id
            original = query.message.text or ""
            await query.edit_message_text(
                f"{original}\n\n✏️ *S.I.G.N.A.L. is waiting* — reply with your suggestion and she'll revise the draft."
            )
            return

        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                if action == "approve":
                    cur.execute(
                        """
                        UPDATE autonomy_approval_queue
                        SET status = 'approved', approved_by = %s, approved_at = NOW(), updated_at = NOW()
                        WHERE id = %s AND status = 'pending'
                        RETURNING action_data
                    """,
                        (user_info["user_id"], approval_id),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    if row:
                        action_data = (
                            row["action_data"]
                            if isinstance(row["action_data"], dict)
                            else json.loads(row["action_data"])
                        )
                        await query.edit_message_text(
                            f"\u2705 Approved escalation #{approval_id}\n"
                            f"Model: {action_data.get('escalated_model', '?')}\n"
                            f"Will execute on next dispatch cycle."
                        )
                    else:
                        await query.edit_message_text(f"Escalation #{approval_id} not found or already processed.")

                elif action == "deny":
                    cur.execute(
                        """
                        UPDATE autonomy_approval_queue
                        SET status = 'rejected', approved_by = %s,
                            rejected_reason = 'Denied via Telegram', updated_at = NOW()
                        WHERE id = %s AND status = 'pending'
                    """,
                        (user_info["user_id"], approval_id),
                    )
                    conn.commit()
                    await query.edit_message_text(f"\u274c Denied escalation #{approval_id}")

                elif action == "defer":
                    cur.execute(
                        """
                        UPDATE autonomy_approval_queue
                        SET expires_at = NOW() + INTERVAL '1 hour', updated_at = NOW()
                        WHERE id = %s AND status = 'pending'
                    """,
                        (approval_id,),
                    )
                    conn.commit()
                    await query.edit_message_text(f"\u23f3 Deferred escalation #{approval_id} for 1 hour")

            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Escalation callback error: {e}")
            await query.edit_message_text(f"Error processing escalation: {e}")

    def _get_pending_checkin(self):
        """Return pending check-in state dict if one exists and hasn't expired, else None."""
        try:
            import json as _j
            from datetime import datetime as _dt, timezone as _tz
            from database import get_db_cursor

            with get_db_cursor() as (_c, _cur):
                _cur.execute("SELECT value FROM system_config WHERE key = 'signal_personal_checkin'")
                row = _cur.fetchone()
            if not row:
                return None
            state = _j.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
            if state.get("status") != "pending":
                return None
            expires_at = _dt.fromisoformat(state["expires_at"].replace("Z", "+00:00"))
            if _dt.now(_tz.utc) > expires_at:
                return None  # expired — timeout job will handle it
            return state
        except Exception as exc:
            logger.debug("[TelegramGateway] _get_pending_checkin failed: %s", exc)
            return None

    async def _handle_linkedin_suggestion(self, update, context, approval_id: int, suggestion: str):
        """User replied with revision feedback — send to S.I.G.N.A.L. and re-queue."""
        await update.message.reply_text("✏️ Got it — sending to S.I.G.N.A.L. for revision...")

        try:
            # Load original draft and mark it superseded
            original_draft = ""
            action_data = {}
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    "SELECT action_data FROM autonomy_approval_queue WHERE id = %s",
                    (approval_id,),
                )
                row = cur.fetchone()
                if not row:
                    await update.message.reply_text(f"❌ Approval #{approval_id} not found.")
                    return
                action_data = (
                    row["action_data"] if isinstance(row["action_data"], dict) else json.loads(row["action_data"])
                )
                original_draft = action_data.get("content", "")
                cur.execute(
                    """UPDATE autonomy_approval_queue
                       SET status = 'rejected', rejected_reason = %s, updated_at = NOW()
                       WHERE id = %s AND status = 'pending'""",
                    (f"Revision requested: {suggestion[:120]}", approval_id),
                )
                conn.commit()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

            # Redraft via S.I.G.N.A.L. (blocking call — run in executor)
            import asyncio as _asyncio

            loop = _asyncio.get_event_loop()

            def _do_redraft():
                from signal_dispatch import redraft_with_suggestion

                return redraft_with_suggestion(original_draft, suggestion, action_data)

            new_approval_id, preview = await loop.run_in_executor(None, _do_redraft)

            await update.message.reply_text(
                f"✅ Revised draft queued (approval #{new_approval_id}).\n"
                f"_{preview[:150]}…_\n\n"
                f"Check Telegram for the new approval request."
            )

        except Exception as exc:
            logger.error("[TelegramGateway] linkedin suggestion handling failed: %s", exc)
            await update.message.reply_text(f"❌ Revision failed: {exc}")

    def send_escalation_notification(self, approval_id: int, context: dict):
        """Send escalation approval request to linked Telegram users."""
        if not self._running or not self._loop:
            return

        dept = context.get("department", context.get("station", "?"))
        text = (
            f"Escalation Request #{approval_id}\n"
            f"Agent: {context.get('agent_name', '?')} ({dept})\n"
            f"Capability: {context.get('capability', '?')}\n"
            f"Failed {context.get('failure_count', '?')}x on: {context.get('original_model', '?')}\n"
            f"Next tier: {context.get('escalated_model', '?')} (~${context.get('est_cost', 0):.4f})\n"
            f"Module: {context.get('module_id', '?')}\n\n"
            f"ARCHIE recommends: {context.get('recommendation', 'Approve')}"
        )

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Approve", callback_data=f"esc_approve_{approval_id}"),
                    InlineKeyboardButton("Deny", callback_data=f"esc_deny_{approval_id}"),
                    InlineKeyboardButton("Defer 1hr", callback_data=f"esc_defer_{approval_id}"),
                ]
            ]
        )

        async def _send():
            try:
                conn = get_db()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT telegram_id FROM telegram_users "
                        "WHERE is_authorized = TRUE AND telegram_id IS NOT NULL"
                    )
                    rows = cur.fetchall()

                    for row in rows:
                        chat_id = row[0]
                        send_status = "sent"
                        send_err = None
                        msg_obj = None
                        try:
                            msg_obj = await self._application.bot.send_message(
                                chat_id=chat_id, text=text, reply_markup=keyboard
                            )
                        except Exception as e:
                            send_status = "failed"
                            send_err = str(e)
                            logger.warning(f"Failed to notify {chat_id}: {e}")

                        # Mirror to telegram_message_log via unified service (one row per send).
                        try:
                            from services.telegram_service import _log_message as _tg_log

                            _tg_log(
                                category="escalation",
                                title=f"Escalation #{approval_id}",
                                message=text,
                                source_agent=context.get("agent_name"),
                                source_department=context.get("department"),
                                source_module=context.get("module_id"),
                                status=send_status,
                                error_message=send_err,
                                chat_id=str(chat_id),
                                telegram_message_id=getattr(msg_obj, "message_id", None) if msg_obj else None,
                            )
                        except Exception as log_err:
                            logger.debug(f"Escalation COMs log insert failed: {log_err}")

                        # Mirror to unified_messages (A.R.C.H.I.E. Chat, Project #265)
                        # so the user sees the escalation in their canonical conversation.
                        try:
                            from database import get_db_cursor

                            with get_db_cursor(commit=True) as (_c, uc_cur):
                                uc_cur.execute(
                                    "SELECT user_id FROM telegram_users WHERE telegram_id=%s",
                                    (chat_id,),
                                )
                                u = uc_cur.fetchone()
                                if not u:
                                    raise RuntimeError("no linked user_id")
                                user_id = u["user_id"] if isinstance(u, dict) else u[0]
                                if not user_id:
                                    raise RuntimeError("no linked user_id")

                                uc_cur.execute(
                                    """SELECT id FROM unified_conversations
                                       WHERE user_id=%s AND topic=%s AND status='active'
                                       ORDER BY last_activity DESC LIMIT 1""",
                                    (user_id, "A.R.C.H.I.E. Escalations"),
                                )
                                conv_row = uc_cur.fetchone()
                                if conv_row:
                                    conv_id = conv_row["id"] if isinstance(conv_row, dict) else conv_row[0]
                                    uc_cur.execute(
                                        "UPDATE unified_conversations SET last_activity=NOW() WHERE id=%s",
                                        (conv_id,),
                                    )
                                else:
                                    uc_cur.execute(
                                        """INSERT INTO unified_conversations
                                           (user_id, topic, status, created_at, last_activity)
                                           VALUES (%s, %s, 'active', NOW(), NOW())
                                           RETURNING id""",
                                        (user_id, "A.R.C.H.I.E. Escalations"),
                                    )
                                    first = uc_cur.fetchone()
                                    conv_id = first["id"] if isinstance(first, dict) else first[0]

                                import json as _json

                                uc_cur.execute(
                                    """INSERT INTO unified_messages
                                       (conversation_id, channel, direction, sender, content, metadata, created_at)
                                       VALUES (%s, %s, %s, %s, %s, %s, NOW())""",
                                    (
                                        conv_id,
                                        "telegram",
                                        "outbound",
                                        "A.R.C.H.I.E.",
                                        text,
                                        _json.dumps(
                                            {
                                                "approval_id": approval_id,
                                                "agent_name": context.get("agent_name"),
                                                "department": context.get("department"),
                                                "est_cost": context.get("est_cost"),
                                                "telegram_message_id": (
                                                    getattr(msg_obj, "message_id", None) if msg_obj else None
                                                ),
                                                "send_status": send_status,
                                            }
                                        ),
                                    ),
                                )
                        except Exception as uc_err:
                            logger.debug(f"Escalation unified_messages log failed: {uc_err}")

                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
                    try:
                        conn.close()
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Escalation notification failed: {e}")

        asyncio.run_coroutine_threadsafe(_send(), self._loop)

    def send_dispatch_advisory(self, title: str, message: str):
        """Send FYI advisory to all linked Telegram users (no approval buttons).

        Routes through telegram_service.send() so every advisory produces
        exactly one telegram_message_log row and benefits from A.R.C.H.I.E.'s
        unified voice + throttling logic.
        """
        try:
            from services.telegram_service import send as _tg_send

            _tg_send(
                category="info",
                title=title,
                message=message,
                source_module="telegram_gateway",
            )
        except Exception as e:
            logger.debug(f"[TelegramGateway] Advisory send failed: {e}")

    # ------------------------------------------------------------------
    # Social Media Draft Approval via Telegram (Project #286)
    # ------------------------------------------------------------------

    async def _social_callback(self, update, context):
        """Handle social draft approve/discard buttons from Telegram.

        callback_data formats:
            social_pub_{draft_id}_{tenant_id}   — publish the draft
            social_dis_{draft_id}_{tenant_id}   — discard (delete) the draft
        """
        import urllib.request as _urlreq
        import json as _json

        query = update.callback_query
        await self._safe_answer(query)

        user_info = self._get_authorized_user(query.from_user.id)
        if not user_info:
            await query.edit_message_text("Unauthorized.")
            return

        data = query.data  # e.g. "social_pub_42_9908"
        try:
            parts = data.split("_")  # ["social", "pub"|"dis", draft_id, tenant_id]
            action = parts[1]  # "pub" or "dis"
            draft_id = int(parts[2])
            tenant_id = int(parts[3])
        except (IndexError, ValueError):
            await query.edit_message_text("Invalid callback data.")
            return

        kbs_url = os.getenv("KBS_APP_URL", "http://kbs_app:8091")
        token = os.getenv("KBS_SERVICE_TOKEN") or os.getenv("ARCHIE_COMMS_SERVICE_TOKEN", "")  # #6657
        endpoint = f"{kbs_url}/api/social/telegram-callback"
        payload = _json.dumps(
            {
                "action": "publish" if action == "pub" else "discard",
                "draft_id": draft_id,
                "tenant_id": tenant_id,
            }
        ).encode()

        try:
            req = _urlreq.Request(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                method="POST",
            )
            with _urlreq.urlopen(req, timeout=30) as resp:
                result = _json.loads(resp.read())
            if action == "pub":
                platform = result.get("platform", "social media")
                await query.edit_message_text(f"✅ Published to {platform}!")
            else:
                await query.edit_message_text("🗑 Draft discarded.")
        except Exception as exc:
            logger.error("[TelegramGateway] social callback failed: %s", exc)
            await query.edit_message_text(f"❌ Action failed: {exc}")

    # ------------------------------------------------------------------
    # PR Merge Authority via Telegram
    # ------------------------------------------------------------------

    async def _pr_merge_callback(self, update, context):
        """Handle pr_merge_approve_N and pr_merge_deny_N inline button callbacks."""
        query = update.callback_query
        await self._safe_answer(query)

        # AUTHORIZATION — MUST run before any merge (#5283). This handler passes
        # human_override=True below, which SKIPS the #5194 unattended-merge
        # governance gate. Without this check, anyone able to deliver the callback
        # data could force-merge ANY PR past governance entirely. Every sibling
        # callback (_node_callback, the generic approve_/reject_ handler) already
        # does this; this one did not.
        user_info = self._get_authorized_user(query.from_user.id)
        if not user_info:
            await query.edit_message_text("Unauthorized.")
            return

        data = query.data  # e.g. "pr_merge_approve_692"

        try:
            parts = data.split("_")
            # data format: pr_merge_approve_123 -> parts = ['pr', 'merge', 'approve', '123']
            action = parts[2]  # "approve" or "deny"
            pr_number = int(parts[3])
        except (IndexError, ValueError):
            await query.edit_message_text("Invalid PR merge callback data.")
            return

        try:
            from tools.repair_bay.services.github_service import merge_pr  # noqa: PLC0415
            from tools.repair_bay.services.pr_review_service import (  # noqa: PLC0415
                _mark_tier_processed,
                resolve_pr_merge_approval,
            )
            from database import get_db_cursor as _gdc  # noqa: PLC0415
            from psycopg2.extras import Json as _Json  # noqa: PLC0415

            if action == "approve":
                # human_override=True — REQUIRED, and safe only because of the
                # authorization check at the top of this handler (#5283).
                #
                # This button exists SOLELY for Tier 3, which is Kytran's alone and
                # is auto-merged by nobody. Without the override this call runs the
                # unattended-merge gate under the default authority 'forge'
                # (FORGE_AUTO_MERGE_MAX_TIER=1), so `tier 3 > 1` refused EVERY tap:
                # the one escalation path for Tier 3 could never actually merge.
                # An authenticated owner tapping their own approve button is exactly
                # the "INTERACTIVE, authenticated caller" case human_override is for.
                result = merge_pr(pr_number, "squash", human_override=True)
                if result.get("merged"):
                    _mark_tier_processed(pr_number, tier=3)
                    # Close the Approvals-tab row too, so the other surface stops
                    # showing this as pending (#5283).
                    resolve_pr_merge_approval(pr_number, approved=True, user_id=user_info.get("user_id"))

                    # MERGED != DEPLOYED (#5375). /app is bind-mounted from the
                    # /mnt/archie_brain checkout; merging updates *origin*, not
                    # that working tree. This reply used to say "merged
                    # successfully" full stop, which reads as "shipped" — and on
                    # 2026-07-28 two PRs (#2543, #2542) sat merged-but-dead
                    # behind exactly that message while every other signal
                    # (GitHub, Repair Bay, a clean container restart) read green.
                    #
                    # We report the deploy state; we do NOT pull or restart here.
                    # This handler runs INSIDE archie_platform, so restarting
                    # would kill it mid-reply, and /mnt/archie_brain holds
                    # Kytran's uncommitted work — automating git there is how you
                    # lose it. Fail-safe: any error degrades to a plain merge
                    # confirmation rather than swallowing the merge result.
                    deploy_line = ""
                    try:
                        from services.hub_deploy_provenance import (  # noqa: PLC0415
                            check_hub_deploy,
                            describe,
                        )

                        deploy_line = f"\n\n{describe(check_hub_deploy())}"
                    except Exception as _dep_exc:  # noqa: BLE001
                        logger.warning(
                            "[PRMergeCallback] deploy provenance unavailable for PR #%s: %s",
                            pr_number,
                            _dep_exc,
                        )
                        deploy_line = "\n\n❔ deploy state UNKNOWN (provenance check unavailable)"

                    await query.edit_message_text(f"✅ Kytran approved — PR #{pr_number} merged.{deploy_line}")
                else:
                    await query.edit_message_text(
                        f"❌ Merge failed for PR #{pr_number}: {result.get('error', 'unknown error')}"
                    )

            elif action == "deny":
                payload = _Json({"kytran_denied": True})
                with _gdc(commit=True) as (_conn, _cur):
                    _cur.execute(
                        "UPDATE pr_reviews SET metadata = COALESCE(metadata, '{}'::jsonb) || %s WHERE pr_number = %s",
                        (payload, pr_number),
                    )
                # A denial must clear the Approvals tab too, or the PR keeps
                # showing as pending on the other surface forever (#5283).
                resolve_pr_merge_approval(pr_number, approved=False, user_id=user_info.get("user_id"))
                await query.edit_message_text(
                    f"❌ PR #{pr_number} denied. Please close it manually on GitHub if needed."
                )

        except Exception as e:
            logger.error("[PRMergeCallback] Error for PR #%s: %s", pr_number, e)
            await query.edit_message_text(f"❌ Error processing PR #{pr_number}: {e}")

    # ------------------------------------------------------------------
    # Email Interaction via Telegram
    # ------------------------------------------------------------------

    async def _email_callback(self, update, context):
        """Handle email action buttons from Telegram notifications."""
        query = update.callback_query
        await self._safe_answer(query)

        data = query.data  # e.g. "email_reply_123"
        parts = data.split("_", 2)  # ["email", "reply", "123"]
        if len(parts) < 3:
            await query.edit_message_text("Invalid action")
            return

        action = parts[1]
        try:
            email_id = int(parts[2])
        except ValueError:
            await query.edit_message_text("Invalid email ID")
            return

        user = self._get_authorized_user(query.from_user.id)
        if not user:
            await query.message.reply_text("Not authorized. Use /link to connect your account.")
            return

        # Mail HQ Smart Inbox (Slice 4): approve-to-send drafted replies. These act on
        # autonomy_approval_queue (email_id == queue id) — distinct from the legacy
        # email_inbox actions below. Single-token actions keep split("_", 2) valid.
        if action in ("replysend", "replycancel"):
            await self._handle_email_reply_action(query, action, email_id, user)
            return

        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                if action == "archive":
                    cur.execute(
                        "UPDATE email_inbox SET is_archived = TRUE, updated_at = NOW() WHERE id = %s",
                        (email_id,),
                    )
                    conn.commit()
                    await query.edit_message_text(query.message.text + "\n\nArchived")

                elif action == "star":
                    cur.execute(
                        "UPDATE email_inbox SET is_starred = NOT is_starred, updated_at = NOW() WHERE id = %s RETURNING is_starred",
                        (email_id,),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    status = "Starred" if row and row["is_starred"] else "Unstarred"
                    await query.edit_message_text(query.message.text + "\n\n" + status)

                elif action == "read":
                    cur.execute(
                        "UPDATE email_inbox SET is_read = TRUE, updated_at = NOW() WHERE id = %s",
                        (email_id,),
                    )
                    conn.commit()
                    await query.edit_message_text(query.message.text + "\n\nMarked as read")

                elif action == "reply":
                    # Set user into reply mode
                    context.user_data["pending_reply_email_id"] = email_id
                    cur.execute(
                        "SELECT from_address, from_name, subject FROM email_inbox WHERE id = %s",
                        (email_id,),
                    )
                    email = cur.fetchone()
                    if email:
                        reply_to = email.get("from_name") or email["from_address"]
                        await query.message.reply_text(
                            f"Replying to: {reply_to}\n"
                            f"Subject: Re: {email['subject']}\n\n"
                            "Type your reply message now. Send /cancel to abort."
                        )
                    else:
                        await query.message.reply_text("Email not found.")
                else:
                    await query.message.reply_text(f"Unknown action: {action}")

            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Email callback failed: {e}")
            try:
                await query.message.reply_text(f"Error: {str(e)}")
            except Exception:
                pass

    async def _handle_email_reply_action(self, query, action, queue_id, user):
        """Mail HQ Smart Inbox (Slice 4): approve-to-send / cancel a drafted reply.

        `queue_id` is an autonomy_approval_queue id. The SMTP send runs off the event
        loop via asyncio.to_thread so a multi-second send never blocks the bot. The
        executor is idempotent — a double-tap cannot double-send.
        """
        import asyncio

        approved_by = (user or {}).get("user_id")
        try:
            if action == "replycancel":
                from tools.email_manager.draft_proposal_service import reject_email_reply

                await asyncio.to_thread(reject_email_reply, queue_id, approved_by)
                await query.edit_message_text(query.message.text + "\n\n❌ Cancelled — not sent")
                return

            # replysend — send the drafted reply
            from tools.email_manager.draft_proposal_service import execute_email_reply

            res = await asyncio.to_thread(execute_email_reply, queue_id, approved_by)
            if res.get("success"):
                await query.edit_message_text(query.message.text + "\n\n✅ Sent")
            else:
                await query.edit_message_text(query.message.text + f"\n\n⚠️ Not sent: {res.get('error', 'unknown')}")
        except Exception as e:
            # Full traceback — this drives a real email send, so failures must be diagnosable.
            logger.exception("email reply action failed (q=%s, action=%s): %s", queue_id, action, e)
            try:
                await query.edit_message_text(query.message.text + f"\n\n⚠️ Error: {e}")
            except Exception as edit_err:
                logger.debug("email reply action: could not edit Telegram message (q=%s): %s", queue_id, edit_err)

    async def _send_email_reply(self, update, context, email_id):
        """Send an email reply from Telegram message text via SMTP."""
        reply_text = update.message.text

        if reply_text.strip().lower() == "/cancel":
            del context.user_data["pending_reply_email_id"]
            await update.message.reply_text("Reply cancelled.")
            return

        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                # Get original email
                cur.execute(
                    "SELECT from_address, subject, message_id FROM email_inbox WHERE id = %s",
                    (email_id,),
                )
                email = cur.fetchone()
                if not email:
                    await update.message.reply_text("Original email not found.")
                    del context.user_data["pending_reply_email_id"]
                    return

                # Get SMTP settings
                cur.execute("SELECT * FROM email_settings WHERE is_default = TRUE AND is_active = TRUE LIMIT 1")
                smtp = cur.fetchone()
                if not smtp:
                    await update.message.reply_text("No SMTP configured. Cannot send reply.")
                    del context.user_data["pending_reply_email_id"]
                    return

                # Build and send email
                import smtplib
                from email.mime.text import MIMEText

                msg = MIMEText(reply_text, "plain")
                msg["From"] = f"{smtp['from_name']} <{smtp['from_email']}>"
                msg["To"] = email["from_address"]
                msg["Subject"] = f"Re: {email['subject']}"
                if email.get("message_id"):
                    msg["In-Reply-To"] = email["message_id"]
                    msg["References"] = email["message_id"]

                if smtp["encryption"] == "ssl":
                    server = smtplib.SMTP_SSL(smtp["smtp_host"], smtp["smtp_port"])
                else:
                    server = smtplib.SMTP(smtp["smtp_host"], smtp["smtp_port"])
                    if smtp["encryption"] == "tls":
                        server.starttls()
                try:
                    server.login(smtp["smtp_user"], smtp["smtp_password_encrypted"])
                    server.send_message(msg)
                finally:
                    server.quit()

                # Log the send
                cur.execute(
                    """
                    INSERT INTO email_logs (recipient, subject, body_preview, status, sent_at, created_by, created_at)
                    VALUES (%s, %s, %s, 'sent', NOW(), %s, NOW())
                    """,
                    (email["from_address"], f"Re: {email['subject']}", reply_text[:200], 1),
                )

                # Mark original as read
                cur.execute(
                    "UPDATE email_inbox SET is_read = TRUE, updated_at = NOW() WHERE id = %s",
                    (email_id,),
                )
                conn.commit()

                # Log governance event
                try:
                    from ai_bridge.agent_loop import log_governance_event

                    log_governance_event(
                        "email_sent_telegram",
                        "execute",
                        "success",
                        {
                            "email_id": email_id,
                            "to": email["from_address"],
                            "method": "telegram",
                        },
                    )
                except Exception:
                    pass

                del context.user_data["pending_reply_email_id"]
                await update.message.reply_text(f"Reply sent to {email['from_address']}")

            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Telegram email reply failed: {e}")
            await update.message.reply_text(f"Failed to send reply: {str(e)}")
            if "pending_reply_email_id" in context.user_data:
                del context.user_data["pending_reply_email_id"]

    async def _cmd_cancel(self, update, context):
        """Cancel any pending operation."""
        if "pending_reply_email_id" in context.user_data:
            del context.user_data["pending_reply_email_id"]
            await update.message.reply_text("Reply cancelled.")
        else:
            await update.message.reply_text("Nothing to cancel.")

    # ------------------------------------------------------------------
    # Notification Forwarding
    # ------------------------------------------------------------------

    def forward_notifications(self):
        """
        Forward unread system notifications to linked Telegram users.
        Called by the agent loop every 15s.
        """
        if not self._running:
            return

        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                # Get un-forwarded notifications
                cur.execute(
                    """
                    SELECT n.id, n.type, n.title, n.message, n.priority, n.source, n.created_at
                    FROM system_notifications n
                    WHERE n.telegram_forwarded = FALSE AND n.is_read = FALSE
                    ORDER BY n.created_at DESC
                    LIMIT 20
                    """
                )
                notifications = cur.fetchall()

                if not notifications:
                    return

                # Get authorized users with rules
                cur.execute(
                    """
                    SELECT tu.id, tu.telegram_id, tu.user_id,
                           tnr.notification_type, tnr.priority_min, tnr.source_filter,
                           tnr.quiet_hours_start, tnr.quiet_hours_end
                    FROM telegram_users tu
                    JOIN telegram_notification_rules tnr ON tnr.telegram_user_id = tu.id
                    WHERE tu.is_authorized = TRUE AND tu.telegram_id IS NOT NULL AND tnr.is_active = TRUE
                    """
                )
                rules = cur.fetchall()

                forwarded_ids = set()

                for notif in notifications:
                    for rule in rules:
                        if self._matches_rule(notif, rule):
                            try:
                                self._send_telegram_message(
                                    f"[{notif['type'].upper()}] {notif['title']}\n{notif['message']}",
                                )
                                forwarded_ids.add(notif["id"])
                            except Exception as e:
                                logger.warning(f"Failed to forward notification #{notif['id']}: {e}")

                # Mark as forwarded
                if forwarded_ids:
                    cur.execute(
                        "UPDATE system_notifications SET telegram_forwarded = TRUE WHERE id = ANY(%s)",
                        (list(forwarded_ids),),
                    )
                    conn.commit()

            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Notification forwarding error: {e}")

    def _matches_rule(self, notification: dict, rule: dict) -> bool:
        """Check if a notification matches a forwarding rule."""
        # Type filter
        if rule["notification_type"] and rule["notification_type"] != notification["type"]:
            return False

        # Source filter
        if rule["source_filter"] and rule["source_filter"] != notification.get("source"):
            return False

        # Priority filter
        priority_order = {"low": 0, "normal": 1, "high": 2, "critical": 3}
        min_pri = priority_order.get(rule.get("priority_min", "normal"), 1)
        notif_pri = priority_order.get(notification.get("priority", "normal"), 1)
        if notif_pri < min_pri:
            return False

        # Quiet hours
        if rule.get("quiet_hours_start") and rule.get("quiet_hours_end"):
            now = datetime.now().time()
            start = rule["quiet_hours_start"]
            end = rule["quiet_hours_end"]
            if start <= end:
                if start <= now <= end:
                    return False
            else:
                if now >= start or now <= end:
                    return False

        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_telegram_user(self, tg_user) -> dict:
        """Create or update Telegram user record."""
        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    INSERT INTO telegram_users (telegram_id, telegram_username, first_name, last_name)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (telegram_id) DO UPDATE
                    SET telegram_username = EXCLUDED.telegram_username,
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        updated_at = NOW()
                    RETURNING id, user_id, is_authorized
                    """,
                    (tg_user.id, tg_user.username, tg_user.first_name, tg_user.last_name),
                )
                result = cur.fetchone()
                conn.commit()
                return dict(result) if result else {}
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to ensure telegram user: {e}")
            return {}

    def _get_authorized_user(self, telegram_id: int) -> Optional[dict]:
        """Get authorized Telegram user info.

        #5404: this is THE resolution chokepoint — every handler (including the
        approval buttons whose user_id lands in autonomy_approval_queue
        .approved_by) goes through it. For ~3 months telegram_users id 2 mapped
        Kytran's real Telegram identity to the DEACTIVATED users row id 2, so
        every Telegram approval was attributed to a dead account and NOTHING
        noticed. The mapping is fixed (-> id 4, the canonical live account); the
        check below makes any future rot SELF-ANNOUNCING on the first
        interaction: warn-and-honor, never reject — silently refusing the
        single most privileged actor's approval is the worse failure mode
        (that is how PR #2549's approval went unseen).
        """
        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    "SELECT * FROM telegram_users WHERE telegram_id = %s AND is_authorized = TRUE",
                    (telegram_id,),
                )
                result = cur.fetchone()
                if result:
                    try:
                        mapped = result.get("user_id")
                        anomaly = None
                        if not mapped:
                            anomaly = "authorized telegram identity has NO linked users row"
                        else:
                            cur.execute("SELECT is_active FROM users WHERE id = %s", (mapped,))
                            u = cur.fetchone()
                            if u is None:
                                anomaly = f"linked users row {mapped} does not exist"
                            elif not u.get("is_active"):
                                anomaly = f"linked users row {mapped} is DEACTIVATED"
                        if anomaly:
                            logger.error(
                                "telegram_gateway: attribution anomaly for telegram_id %s: %s — "
                                "honoring the interaction but the audit trail is naming a dead "
                                "identity; fix telegram_users.user_id (#5404)",
                                telegram_id,
                                anomaly,
                            )
                            try:
                                cur.execute(
                                    """INSERT INTO audit_log (action, resource_type, details, severity, category)
                                       VALUES ('TELEGRAM_ATTRIBUTION_ANOMALY', 'telegram_user', %s, 'warning', 'governance')""",
                                    (f"telegram_id {telegram_id}: {anomaly}",),
                                )
                                conn.commit()
                            except Exception:
                                pass
                    except Exception as _chk_err:
                        logger.debug(f"attribution check skipped: {_chk_err}")
                return dict(result) if result else None
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to get authorized user: {e}")
            return None

    def _orchestrate_message(self, message: str, user_id: int, voice_mode: bool = False) -> Optional[str]:
        """Route a message through the orchestration engine."""
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
            from tools.department_hq.services.orchestration_engine import OrchestrationEngine

            engine = OrchestrationEngine()
            result = engine.orchestrate(
                message=message,
                user_id=user_id,
                voice_mode=voice_mode,
            )

            if result.success:
                return result.response
            return result.error or "Processing failed"
        except Exception as e:
            logger.error(f"Orchestration failed: {e}")
            return f"Error: {e}"

    def _process_approval(self, approval_id: int, user_id: int, approved: bool):
        """Process an approval/rejection from Telegram."""
        try:
            conn = get_db()
            try:
                cur = conn.cursor()
                if approved:
                    cur.execute(
                        """
                        UPDATE autonomy_approval_queue
                        SET status = 'approved', approved_by = %s, approved_at = NOW(), updated_at = NOW()
                        WHERE id = %s AND status = 'pending'
                        """,
                        (user_id, approval_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE autonomy_approval_queue
                        SET status = 'rejected', approved_by = %s, rejected_reason = 'Rejected via Telegram', updated_at = NOW()
                        WHERE id = %s AND status = 'pending'
                        """,
                        (user_id, approval_id),
                    )
                conn.commit()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to process approval: {e}")

    def _log_message(self, telegram_user_id: int, direction: str, msg_type: str, content: str):
        """Log a Telegram message."""
        try:
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO telegram_messages (telegram_user_id, direction, message_type, content)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        telegram_user_id,
                        direction,
                        msg_type,
                        content[:5000] if content else "",
                    ),
                )
                conn.commit()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to log telegram message: {e}")

    def _send_telegram_message(self, text: str) -> bool:
        """Route through A.R.C.H.I.E. director report inbox instead of direct Telegram.

        # chat_id routing removed — unified-voice routes via director report inbox
        """
        if _telegram_service_send is None:
            logger.error("telegram_gateway: telegram_service not available for redirect")
            return False
        try:
            result = _telegram_service_send(
                category="notification",
                title="Notification",
                message=text,
                source_module="telegram_gateway",
            )
            if not result.get("success", False):
                logger.warning(f"telegram_gateway: redirect returned non-success: {result}")
                return False
            return True
        except Exception as e:
            logger.error(f"telegram_gateway _send_telegram_message redirect failed: {e}")
            return False


def generate_link_code(user_id: int) -> str:
    """Generate a one-time link code for Telegram account linking."""
    code = secrets.token_hex(4).upper()  # 8 char hex code
    try:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Check if user already has a telegram_users entry
            cur.execute("SELECT id FROM telegram_users WHERE user_id = %s", (user_id,))
            existing = cur.fetchone()

            if existing:
                cur.execute(
                    """
                    UPDATE telegram_users
                    SET link_code = %s, link_code_expires_at = NOW() + INTERVAL '15 minutes', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (code, existing["id"]),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO telegram_users (telegram_id, user_id, link_code, link_code_expires_at)
                    VALUES (0, %s, %s, NOW() + INTERVAL '15 minutes')
                    """,
                    (user_id, code),
                )

            conn.commit()
            return code
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Failed to generate link code: {e}")
        return ""
