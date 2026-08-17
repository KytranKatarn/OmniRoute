# Security Network Rules

## Module
- Route: `/tools/security-network` | Blueprint: `security_network_bp`
- Category: `admin_operations`
- Chat overlay: **V.I.G.I.L.** (#3) → `security-network-chat.js`, red `#ef4444`
- Briefing: `tools/archie_chat/security_network_briefing.py`
- KB Docs: #263992 · #264473 (audit 2026-05-09)

## Capabilities (7 feature groups)

| Group | What it does |
|-------|-------------|
| SSL/TLS Watch | Cert expiry monitoring for all subdomains |
| Hostinger DNS | Full CRUD via Hostinger API MCP tools |
| NPM Proxy | Proxy host lifecycle — create/delete/SSL force |
| Compliance Scans | 5 rule packs, one-click remediation, auto-scan every 6h |
| Device Discovery | AdGuard + ARP scan every 5min, Home Assistant cameras |
| Supervision Schedules | Camera + sensor schedule management |
| V.I.G.I.L. Chat | Security briefings, on-demand audits |

## Compliance Rule Packs (stored in `rule_packs/`)

| Pack | Rules | SOC 2 mapped |
|------|-------|-------------|
| Ubuntu STIG | 51 | Yes |
| Docker STIG | 30 | Yes |
| HIPAA | 30 | Yes |
| Network STIG | 27 | Yes |
| CIS Ubuntu | 40 | Yes |

- Rule format: `rule_id`, `severity` (low/medium/high), `check_type`, `fix`, `soc2_mapping`
- Findings: `compliance_scan_results` table, severity + remediation path
- Automatable fixes: host command client → one-click remediation
- Scan auto-run: every 6h via agent loop

## DB Tables

| Table | Key use |
|-------|---------|
| `security_events` | Threat/anomaly log |
| `security_scan_results` | Compliance findings per scan |
| `security_recon_scans` | Port/service discovery results |
| `network_devices` | ARP/AdGuard-discovered devices |
| `security_dns_changes` | DNS record change audit trail |
| `org_domains` | Domain verification for orgs |
| `managed_dns_records` | Hostinger DNS records in sync |

## Gotchas

- LCARS CSS: template uses BOTH `--frame-color` CSS vars AND direct `background: #HEX !important` — two-pass replacement required for color changes (64+ sites)
- **AdGuard host**: `http://network_adguard:3000` (Docker internal) — NOT 192.168.1.200:3000 (that's the platform)
- **NPM API**: `http://nginx_proxy_manager:81` — requires JWT token from `/api/tokens`
- Hostinger DNS changes: use `mcp__hostinger-api__DNS_updateDNSRecordsV1` — NEVER `curl` Hostinger API directly
- Compliance scanning requires `host_monitor.py` bridge for SSH-based checks

## V.I.G.I.L. Dispatch Pattern

```python
# Delegate security audit to V.I.G.I.L.:
mcp__archie__delegate_task(
    capability='security',
    reason='Run compliance check on docker containers',
    delegation_source='claude'
)

# Known-tool shortcut (no LLM):
mcp__archie__delegate_task(
    capability='compliance_check',
    reason='Run full compliance scan',
    delegation_source='claude'
)
```

## Public Compliance Posture

- Live SVG badges: Green (90%+), Blue (80%+), Yellow (70%+), Red (<60%)
- Grade scale: A+ (95%), A (90%), B+ (85%), B (80%), C (70%), D (60%), F (<60%)
- Trust center page: any product offered as a service needs one
- Badge scores auto-refresh from latest scan results

## Full Security Review — changes (2026-08-16, project #392, PRs #2617–#2621)

Audit: KB #289778 (62/62 findings verified) · remediation #289779 · pattern-bug KB #289780.
7 PRs, 84 unit tests. **Static+unit verified only — a live drive of the scanners/controls is still
pending** (was blocked on an `archie_platform` restart hold). New/changed operational surface:

- **Scanner injection guard — NEW `scan_input_validator.py`** (fail-closed chokepoint). Every scan
  path (`argus_service._docker_scan`, `stack_integration.SecurityScannerService`, and all
  `/api/scanner/*` + campaign routes) validates `target`/`ports`/`severity`: rejects leading-dash
  option injection (nmap `-oN`/`--script`), shell metachars, and — without `confirm_internal=true` —
  loopback/RFC1918/`100.64.0.0/10` mesh/cloud-metadata SSRF targets. nmap/testssl use `--` separators.
  SSRF **policy** is at the ROUTE layer (`confirm_internal`); the service layer is injection-only
  (`allow_internal=True`).
- **`/api/compliance/rule-packs` is now GATED** — internal-key (`X-Internal-Key`/`Bearer INTERNAL_API_KEY`)
  OR admin session (was fully public; it leaks host remediation command strings). KSO must send the key
  (kytran-system-operations PR #11; provision `INTERNAL_API_KEY` in KSO `.env`, else KSO falls back to
  bundled local packs).
- **Host command queue is HMAC-authenticated** — `host_command_client` signs the 4 privileged
  `compliance_fix_*` types with `INTERNAL_API_KEY`; `scripts/host_monitor.py` verifies before executing,
  **fails closed**. Closes the world-writable-queue root RCE. ⚠️ SUPERVISED deploy: restart
  `archie_platform` FIRST, then `systemctl restart host_monitor`.
- **New alert type `recommendation`** in `security_alerts.VALID_ALERT_TYPES` — the V.I.G.I.L. auto-block
  job now says "Action recommended … NOT automatically blocked" (approve_suggestion is a no-op; nothing
  consumes approved rows). Real auto-execution is an owner decision, not wired.
- **New route `GET /api/domains/certificates`** — surfaces `security_ssl_monitors` for the Domains ›
  Certificates subtab (was a 404). **New service method `HostingerService.delete_dns_records(type,name,domain)`**
  (name+type filtered; never the whole zone). ntopng `is_healthy()` now requires authenticated JSON (rc==0),
  not a bare 200 (login page 200 = fail-open).
- **Contract fixes** — incidents + supervision list endpoints return `{success, <collection>}` (were bare
  arrays the UI couldn't read); Devices Add-Mapping/Type-filter/Edit accept the UI's actual keys/kwargs;
  AdGuard `toggle_filter` sends the full `set_url` `data` object. Reports-tab DNS stat IDs renamed `rpt-*`
  (were duplicated with DNS Overview). Info-leak: incident/supervision/noc no longer return raw `str(exc)`.
- ⚠️ **RealDictCursor pattern bug (KB #289780)** — `get_db_cursor(dict_cursor=True)` (no such kwarg → 500)
  and `dict(zip(cur.description, row))` (→ column-names-as-values) recurred 10+ times here. Drop the kwarg;
  use `dict(row)`/`row['col']`; never index a row by int position.
- Deferred (need a live drive / host work): tasks #5675 scanner findings pipeline (containers in `created`),
  #5676 fail2ban/ufw/ssh host-status checks, #5677 honeypot real-port capture. Accepted-risk: module
  `/health` stays public (conventional; flags non-sensitive).
