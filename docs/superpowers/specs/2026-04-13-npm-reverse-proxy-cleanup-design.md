# NPM Reverse Proxy Cleanup + DNS Housekeeping

**Date:** 2026-04-13
**Project:** #235 — NPM Reverse Proxy Restoration + DNS Cleanup
**Status:** Approved

## Context

NPM (Nginx Proxy Manager v2.14.0) is running healthy on hub (.200) with 24 proxy hosts. However, several hosts point to offline node .250, watch products have redundant proxy entries, SSL isn't forced on all hosts, and DNS has orphan records. This spec covers a full cleanup pass.

## 1. Fix Stale .250 Forwarding

Two hosts still forward to 192.168.1.250 (offline). Update to .200:

| NPM ID | Domain | Old Target | New Target |
|--------|--------|-----------|------------|
| 3 | adguard.kytranempowerment.com | 192.168.1.250:5354 | 192.168.1.200:5354 |
| 6 | nagios.kytranempowerment.com | 192.168.1.250:8082 | 192.168.1.200:8082 |

## 2. Remove Dead Proxy Hosts (7 total)

| NPM ID | Domain | Reason |
|--------|--------|--------|
| 4 | portainer.kytranempowerment.com | Service no longer used |
| 5 | mdm.kytranempowerment.com | Service no longer used |
| 14 | *.fleet.kytranempowerment.com | No fleet nodes online, no SSL cert (cert:0), recreate when needed |
| 24 | civic.kytranempowerment.com | Runs on VPS — DNS already points to VPS directly |
| 25 | legal.kytranempowerment.com | Runs on VPS — DNS already points to VPS directly |
| 26 | market.kytranempowerment.com | Runs on VPS — DNS already points to VPS directly |
| 27 | gov.kytranempowerment.com | Runs on VPS — DNS already points to VPS directly |

After cleanup: 24 - 7 = **17 proxy hosts** remaining.

## 3. Force SSL on Remaining Non-SSL Hosts

After removals, these hosts have certs but don't force SSL:

| NPM ID | Domain | Cert ID |
|--------|--------|---------|
| 3 | adguard.kytranempowerment.com | 3 |
| 6 | nagios.kytranempowerment.com | 5 |
| 22 | api.kytranempowerment.com | 27 |
| 23 | proxy.kytranempowerment.com | 29 |
| 28 | mail.kytranempowerment.com | 34 |

Set `ssl_forced: true` and `http2_support: true` on all 5.

## 4. DNS Record Cleanup (Hostinger API)

### Remove (5 A records)

| Subdomain | Current IP | Reason |
|-----------|-----------|--------|
| portainer | 153.68.195.85 | Dead service |
| mdm | 153.68.195.85 | Dead service |
| code | 153.68.195.85 | No longer needed |
| devhq | 153.68.195.85 | Accessed via archie.kytranempowerment.com/#devhq |
| *.fleet | 153.68.195.85 | No fleet nodes, recreate when needed |

### Keep (no change)

| Subdomain | Reason |
|-----------|--------|
| plex | Future standalone media server (project to be created) |
| n8n | KBS integration planned |
| voice | KBS voice system planned (project to be created) |

## 5. Update DDNS Script

Remove `portainer` and `mdm` from the `SUBDOMAINS` array in `/mnt/archie_brain/scripts/ddns_updater.sh`.

Note: `code` and `devhq` are not in the DDNS script, and `*.fleet` is a wildcard not managed by DDNS.

## 6. Update operational-state.md

Change NPM entry from `NOT DEPLOYED` to deployed:

```
| NPM Proxy | 80/443 | proxy.kytranempowerment.com | nginx_proxy_manager | Hub |
```

## 7. Create New Projects

### Standalone Media Server
- Redesign Plex/Jellyfin as standalone product following extraction playbook
- DNS record `plex.kytranempowerment.com` already exists
- Priority: 7 (future work)

### KBS Voice System
- Voice integration for Kytran Business Suite
- DNS record `voice.kytranempowerment.com` already exists
- Priority: 7 (future work)

## Implementation Method

- All NPM changes via NPM REST API (token auth from inside Docker network)
- DNS changes via Hostinger API
- DDNS script: direct file edit
- operational-state.md: direct file edit
- No container restarts needed — NPM applies changes live

## Verification

After all changes:
1. Confirm 17 proxy hosts remain via NPM API
2. Confirm all remaining hosts have `ssl_forced: true`
3. Confirm removed DNS records no longer resolve
4. Confirm `https://archie.kytranempowerment.com` still works (regression check)
5. Confirm `https://adguard.kytranempowerment.com` and `https://nagios.kytranempowerment.com` now reach hub services
