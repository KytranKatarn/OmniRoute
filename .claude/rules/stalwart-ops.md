# Stalwart Mail Operations

Loaded unconditionally on purpose: the recovery below is run with `docker`/admin-API calls during an outage, when no `email_manager/**` file is being edited, so a path-scoped rule would never load. Split out of `email-manager.md`.

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
