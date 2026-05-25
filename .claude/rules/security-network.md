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
