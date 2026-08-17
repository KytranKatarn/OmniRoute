# Email Manager Rules

**New file** — documents Stalwart connection rule, IMAP table gotchas, R.E.S.O.L.V.E. integration, mailbox structure.

## Module

- Route: `/tools/email-manager` | Blueprint: `email_manager_bp`
- Category: `saas_services`
- KB Docs: #265260 (user guide) · #265261 (coder guide) · Migrations 375–378

## Layout

3-panel command center:
1. **Sidebar** — mailbox list, folder tree, rules
2. **Message List** — filtered/sorted thread list
3. **Read Pane** — full message + AI triage + R.E.S.O.L.V.E. draft

## Mailbox Scale

- **70 mailboxes total**: 38 AI agent mailboxes + 10 business mailboxes + 1 owner mailbox + 21 human_agent (COLLABORATOR) mailboxes
- IMAP sync: every **5 minutes** (polling; T3279 targets IMAP IDLE push)
- AI triage: priority scoring, routing to correct agent mailbox

## Stalwart SMTP/IMAP — Critical Connection Rule

```
CORRECT:   http://stalwart_mail:8080   (plain HTTP, Docker internal hostname)
WRONG:     https://192.168.1.200:8443  (hairpin NAT blocks TLS from containers)
WRONG:     https://mail.kytranempowerment.com  (external, TLS, hairpin NAT)
```

**Why:** Containers cannot complete TLS hairpin NAT to the host's external IP. The `stalwart_mail` Docker hostname resolves correctly on the internal compose network and uses plain HTTP on port 8080 (Stalwart's admin/API port). Never use the external HTTPS endpoint from inside a container.

## Key DB Tables

| Table | Key Columns | Gotchas |
|-------|-------------|---------|
| `email_mailboxes` | `id`, `user_id`, `imap_host`, `imap_port`, `username`, `password_encrypted` | — |
| `email_messages` | `id`, `mailbox_id`, `imap_uid`, `thread_id`, `in_reply_to`, `attachment_count`, `ai_priority` | Use `imap_uid` NOT `uid` — `uid` column does not exist |
| `email_threads` | `id`, `mailbox_id`, `subject`, `participant_count`, `last_message_at` | — |
| `email_rules` | `id`, `mailbox_id`, `conditions` JSONB, `actions` JSONB, `enabled` | — |
| `email_activity_log` | `id`, `mailbox_id`, `action_type`, `created_at` | — |

**Column gotchas on `email_messages`:**
- `imap_uid` is the IMAP UID (use this in IMAP operations)
- `ai_priority` is the AI-assigned priority score (float, 0.0–1.0)
- `attachment_count` tracks attachment count at sync time
- `thread_id` FK → `email_threads.id` (may be NULL for unthreaded)
- `in_reply_to` stores the `In-Reply-To` header value (string, for threading)

## R.E.S.O.L.V.E. Integration

- Agent: **R.E.S.O.L.V.E.** (ID #142) — Customer Success & Support
- Chat overlay: `email-manager-chat.js`
- Briefing: `email_hq_briefing.py`
- Accent color: red `#ef4444`
- Capabilities: auto-reply drafting, triage suggestions, escalation routing
- Draft generation: dispatched via Bridge with `capability='support'`

## AI Triage Pipeline

1. New message arrives via IMAP sync
2. `ai_priority` score assigned (Bridge dispatch → `classify` capability)
3. Message routed to correct agent mailbox based on content/sender
4. R.E.S.O.L.V.E. generates draft reply for flagged messages
5. Draft surfaced in Read Pane for human approval before send

## Routes Structure

- `messages_routes.py` — sidebar, message list, single message read, search, thread fetch
- `sync_routes.py` — IMAP sync triggers, status (`@admin_required`)
- `rules_routes.py` — email rules CRUD (`@admin_required`)
- `ai_routes.py` — triage, draft generation via Bridge (`@admin_required`)
- `imap_routes.py` — low-level IMAP operations (`@admin_required`)
- `inbox_routes.py`, `sent_routes.py`, `overview_routes.py`, `hq_routes.py`, `compose_routes.py` — user-facing (`email_access_required`)
- `mailbox_routes.py` — provisioning (`@admin_required`)
- Each registered via `register_*_routes(bp, access_decorator)` in `__init__.py`

## COLLABORATOR Access Control (T3290, migration 406)

```python
from tools.email_manager.access_control import get_visible_mailbox_ids, email_access_required

visible = get_visible_mailbox_ids(current_user)
# None  → admin, unrestricted
# list  → dept-scoped mailbox IDs (own dept agents + explicit grants)
```

- `email_access_required = require_any_permission(ADMIN_ACCESS, EMAIL_INBOX_VIEW)`
- `email_mailboxes.department` column (denormalized from `agents.department`) enables fast scoping
- `user_mailbox_grants` table — explicit cross-dept grants
- `users.agent_department` — set on COLLABORATOR provision, drives scope
- Filter applied in: sidebar, message list, message read, search — all in `messages_routes.py`

## JS State & Compose Patterns (T3280)

```javascript
// state.currentMsg — set in selectMessage() after API fetch
// contains: mailbox_address, mailbox_type, from_addr, subject, body, ...
state.currentMsg = msg;

// openCompose — 4th param auto-selects From dropdown to receiving mailbox
openCompose(toAddr, subject, quotedBody, fromAddr);
// fromAddr = state.currentMsg.mailbox_address

// AI Reply button — visible for ALL mailbox types (owner, business, human_agent, ai)
// was restricted to owner/business only before T3280
var showDraft = true;
```

- `state.currentMsg` is set by `selectMessage()` after the `/api/email/messages/<id>` GET
- Single-message GET returns `mailbox_address` + `mailbox_type` — list-view rows do NOT
- AI Reply dispatches to `POST /api/email/messages/<id>/draft-reply` → Bridge `capability='support'` → R.E.S.O.L.V.E.

## Migrations

| Migration | Content |
|-----------|---------|
| 375 | `email_mailboxes` + `email_messages` base schema |
| 376 | `email_threads` + threading columns |
| 377 | `email_rules` + `email_activity_log` |
| 378 | AI priority + attachment_count columns |

## Gotchas

- `imap_uid` NOT `uid` — `uid` column does not exist, will cause KeyError at runtime
- Stalwart MUST use `http://stalwart_mail:8080` — never the external HTTPS endpoint
- IMAP sync is every 5 minutes — don't trigger manual syncs in rapid succession
- 38 AI mailboxes exist — one per agent. Don't create duplicates. Check `email_mailboxes` first
- `ai_priority` is a float score, not a string category
- Thread reconstruction uses `in_reply_to` header matching — fragile if headers are stripped
- R.E.S.O.L.V.E. drafts require Bridge dispatch — no direct Ollama calls from email routes

## Stalwart auto-ban of INTERNAL clients (2026-08-17 outage — 20h total IMAP/SMTP loss)

All 156 mailboxes failed with `SSL: UNEXPECTED_EOF_WHILE_READING` / `Connection reset by peer`.
Root cause: Stalwart's built-in scan-protection **banned `archie_scheduler`'s bridge IP
(172.27.0.19) on a SINGLE "Invalid IMAP command"** (`security.scan-ban`, 2026-08-16T16:43Z) —
after 13,799 clean auths that day, zero auth failures. The ban is **persistent** (stored as
`server.blocked-ip.<ip>` in Stalwart's settings DB) and covers **every listener** (993/25/587/
8080/443/4190). The Docker gateway 172.27.0.1 (= all host-originated traffic) was banned the
same way. KB #290279 (mistake) / #290280 (runbook).

- **Symptom signature**: TCP connect OK, then EOF before any banner — on plaintext ports too.
  Empty banner on port 25 ⇒ it's a BAN, not TLS. Check `logs/stalwart.log.<date>` inside the
  container for `security.ip-blocked` lines (Stalwart logs to file, stdout is EMPTY).
- **`trusted-networks` on listeners does NOT exempt an IP from scan-ban/fail2ban** — config.toml
  had `172.16.0.0/12` trusted on every listener and the ban happened anyway. The real exemption
  is **`server.allowed-ip.<cidr>`** in the settings DB, which was EMPTY until 2026-08-17. Now
  set: `172.16.0.0/12`, `10.0.0.0/8`, `127.0.0.0/8`, `100.64.0.0/10` — never remove these.
- **Unban procedure**: from an UNBLOCKED container (`archie_platform`), admin API
  `GET /api/settings/list?prefix=server.blocked-ip` → `POST /api/settings`
  `[{"type":"delete","keys":["server.blocked-ip.<ip>"]}]` → **`docker restart stalwart_mail`**.
  `/api/reload` alone does NOT flush the in-memory ban set — the restart is required.
- **172.x is NOT automatically private**: RFC1918 is only 172.16–172.31. `172.104.x`/`172.105.x`
  are Linode public IPs — legitimate external scanner bans. Don't sweep them in a bulk unban.
