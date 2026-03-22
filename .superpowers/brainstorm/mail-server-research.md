# Self-Hosted Docker Mail Server Research
**Date**: 2026-03-21
**Context**: 140+ mailboxes on @kytranempowerment.com, Docker host 192.168.1.200, 128GB RAM

---

## Executive Summary

**Recommendation: Stalwart Mail Server** with Amazon SES as outbound SMTP relay.

Stalwart is the strongest fit for the ARCHIE platform: single Docker container, full REST API for programmatic account CRUD (critical for platform integration), built-in CalDAV/CardDAV/WebDAV, web admin UI, and minimal resource usage. Combined with Amazon SES at $0.10/1,000 emails for outbound relay, this solves the residential IP / port 25 blocking problem cleanly.

---

## Option 1: Mailu

**Website**: https://mailu.io | **GitHub**: ~8,600 stars | **License**: MIT
**Architecture**: Multi-container (Postfix + Dovecot + Rspamd + Nginx + Redis + ClamAV + webmail)

### Docker Compose Complexity
- **6-12 containers**: front (nginx), redis, admin, imap (dovecot), smtp (postfix), antispam (rspamd), antivirus (clamav), webdav (radicale), fetchmail, webmail (roundcube/snappymail), oletools, fts_attachments (tika)
- Setup wizard generates docker-compose.yml + mailu.env
- Most complex of the three options

### Resource Requirements
- **RAM**: ~2-4GB minimum; ClamAV alone needs 1GB+. With 140 mailboxes expect 4-6GB
- **CPU**: Moderate. Rspamd and ClamAV are the heaviest consumers
- **Storage**: ~50GB base + mailbox data. Plan 500GB+ for 140 active mailboxes

### Admin UI
- **Yes** - Full web admin at /admin
- Domain management, user CRUD, aliases, quotas, auto-reply all via web UI

### REST API
- **Yes** - Full RESTful API (Swagger/OpenAPI documented)
- Everything in the web admin is available via API
- Auth via API_TOKEN header
- SwaggerUI built in at /api endpoint
- **Can fully automate mailbox creation** from ARCHIE platform

### Webmail
- **Yes** - Roundcube or SnappyMail (choose during setup)
- Built into the stack

### Antispam/Antivirus
- **Rspamd** (excellent, ML-based, battle-tested)
- **ClamAV** (optional but recommended; 1GB+ RAM cost)
- Greylisting, DNSBL, neural network spam classification

### DKIM/SPF/DMARC
- Full support. Auto-generates DKIM keys per domain
- SPF/DMARC verification on inbound
- DKIM signing on outbound

### CalDAV/CardDAV
- **Yes** - Radicale integration (basic but functional)

### Backup
- All data in /mailu directory - standard filesystem backup
- Database is SQLite (admin) + mail files

### Pros
- Most feature-complete out-of-the-box
- Best antispam (Rspamd with ML)
- Setup wizard simplifies initial config
- Large community, many tutorials
- Full REST API for automation

### Cons
- **Heavy**: 6-12 containers, 4-6GB RAM for 140 mailboxes
- Complex to debug (which container has the issue?)
- ClamAV is a resource hog
- Upgrade path can be tricky with multi-container orchestration
- Radicale CalDAV is basic compared to dedicated solutions

---

## Option 2: Docker Mailserver (docker-mailserver/docker-mailserver)

**Website**: https://docker-mailserver.github.io | **GitHub**: ~15,000+ stars | **License**: MIT
**Architecture**: Single container (Postfix + Dovecot + everything bundled)

### Docker Compose Complexity
- **1 container** - Everything in one image
- Simple docker-compose.yml (~30 lines)
- Config via env vars + mounted config files
- Simplest Docker setup of the three

### Resource Requirements
- **RAM**: ~1-2GB without ClamAV, ~2-3GB with. Lightest of the multi-component options
- **CPU**: Low-moderate
- **Storage**: Mail data + config. Same 500GB+ estimate for 140 mailboxes

### Admin UI
- **No web UI** - CLI only via setup.sh
- `./setup.sh email add user@domain.com password`
- `./setup.sh alias add alias@domain.com target@domain.com`
- Config files in /tmp/docker-mailserver/

### REST API
- **No REST API** - This is the critical weakness
- Account management is CLI-only (setup.sh or docker exec)
- To integrate with ARCHIE platform, would need to:
  - Shell out to `docker exec` commands, OR
  - Write a custom API wrapper around the config files, OR
  - Use LDAP backend (adds complexity)

### Webmail
- **Not included** - Must add separately (Roundcube, SnappyMail, etc.)

### Antispam/Antivirus
- **SpamAssassin** or **Rspamd** (configurable)
- **Amavis** + **ClamAV** for antivirus (optional)
- Postgrey for greylisting

### DKIM/SPF/DMARC
- Full support. `setup.sh config dkim` generates keys
- OpenDKIM or Rspamd for signing

### CalDAV/CardDAV
- **Not included** - Must add separately

### Backup
- Config files + mail data in mounted volumes
- Straightforward filesystem backup

### Pros
- Most mature and battle-tested (Postfix/Dovecot are the gold standard)
- Largest community (15K+ GitHub stars)
- Single container = simple ops
- Excellent documentation
- Lightest resource usage of multi-component options
- Most RFC-compliant

### Cons
- **No REST API** - Cannot programmatically manage accounts without custom wrapper
- **No web admin UI** - CLI only
- **No webmail included** - Must bolt on separately
- **No CalDAV/CardDAV** - Must bolt on separately
- For 140 mailboxes, CLI management is painful without automation layer

---

## Option 3: Stalwart Mail Server (RECOMMENDED)

**Website**: https://stalw.art | **GitHub**: ~15,000+ stars | **License**: AGPL-3.0
**Architecture**: Single Rust binary, single container (SMTP + IMAP + JMAP + CalDAV + CardDAV + WebDAV)

### Docker Compose Complexity
- **1 container** - Single binary handles everything
- Minimal docker-compose.yml (~20 lines)
- Config via TOML file or web admin
- RocksDB default backend (zero external dependencies)

### Resource Requirements
- **RAM**: ~512MB-1GB for the server itself. Rust efficiency means dramatically less than Mailu
- **CPU**: Very low. Rust performance is exceptional
- **Storage**: Mail data. Same 500GB+ for 140 mailboxes
- **With 128GB RAM on the host, Stalwart is negligible overhead**

### Admin UI
- **Yes** - Full web admin (SPA built in Rust/WASM)
- User management, domain config, queue monitoring
- Included with the server, no separate container

### REST API
- **Yes** - Full Management REST API
- User CRUD, domain management, configuration, monitoring
- **Can fully automate mailbox creation** from ARCHIE platform
- Well-documented at stalw.art/docs/category/management-api/
- Native JMAP support (modern email API standard)

### Webmail
- **Yes** - Built-in webmail interface
- Also supports any standard IMAP client

### Antispam/Antivirus
- Built-in spam filtering via Sieve scripts
- DNS blocklists (DNSBL), SPF/DKIM/DMARC verification
- Reputation scoring
- Less sophisticated than Rspamd (no ML classification) but functional
- Can integrate external antivirus if needed

### DKIM/SPF/DMARC
- Full support. DKIM signing, SPF/DMARC verification
- ARC (Authenticated Received Chain) support
- MTA-STS support

### CalDAV/CardDAV
- **Yes** - Built-in CalDAV + CardDAV + WebDAV
- No separate container needed (unlike Mailu's Radicale bolt-on)
- Full collaboration suite in one binary

### Backup
- RocksDB data directory - filesystem backup
- Or use PostgreSQL/MySQL backend for enterprise-grade backup
- Can configure PostgreSQL backend to share ARCHIE's existing database infrastructure

### Pros
- **Full REST API** for platform integration (critical requirement met)
- **Single container**, minimal resource usage (~512MB-1GB RAM)
- **All-in-one**: SMTP + IMAP + JMAP + CalDAV + CardDAV + WebDAV + webmail + admin UI
- Modern Rust codebase - fast, memory-safe, efficient
- JMAP support (next-gen email protocol, better than IMAP for programmatic access)
- Active development, frequent releases
- Can use PostgreSQL backend (integrates with existing ARCHIE DB infrastructure)
- 15K+ GitHub stars, growing rapidly

### Cons
- Younger project (2023+) - less battle-tested than Postfix/Dovecot
- Spam filtering less sophisticated than Rspamd
- Smaller community (though growing fast)
- AGPL license (not an issue for self-hosted, but worth noting)
- Some edge cases in email RFC compliance may still be discovered
- Less third-party documentation/tutorials than Mailu or docker-mailserver

---

## Port 25 Blocking & SMTP Relay (CRITICAL)

### The Problem
- Residential ISPs almost universally block outbound port 25
- Even if port 25 is open, residential IPs are on spam blacklists
- Emails from residential IPs will be rejected by Gmail, Outlook, etc.
- **You WILL need an external SMTP relay for outbound delivery**

### Inbound Email (Receiving)
- Port 25 inbound is typically NOT blocked by ISPs
- MX records point to your public IP
- NPM (Nginx Proxy Manager) can proxy TCP port 25 to the mail server
- **Inbound should work fine on residential IP**

### Outbound Email (Sending) - Requires SMTP Relay

#### Amazon SES (RECOMMENDED)
- **Price**: $0.10 per 1,000 emails ($0.0001/email)
- 140 mailboxes sending ~20 emails/day = ~2,800/day = ~84,000/month = **~$8.40/month**
- SMTP interface - configure as relay in any mail server
- Excellent deliverability (Amazon's IP reputation)
- Free tier: 3,000 emails/month free for 12 months (new accounts)
- Easy setup: generate SMTP credentials in AWS console

#### Alternatives
| Service | Price per 1K emails | Free Tier | Notes |
|---------|---------------------|-----------|-------|
| Amazon SES | $0.10 | 3K/mo (12mo) | Best value, highest reliability |
| Mailgun | $0.80 | 100/day | More expensive |
| SendGrid | $0.50-1.00 | 100/day | Popular but pricier |
| Brevo (Sendinblue) | Free up to 300/day | 300/day | Good free tier |
| Postmark | $1.25 | None | Premium deliverability |

### DNS Requirements
```
MX record:     kytranempowerment.com -> your-public-ip (or mail.kytranempowerment.com)
SPF record:    v=spf1 ip4:YOUR_PUBLIC_IP include:amazonses.com ~all
DKIM record:   Generated by mail server + SES DKIM
DMARC record:  v=DMARC1; p=quarantine; rua=mailto:dmarc@kytranempowerment.com
PTR record:    Reverse DNS (ask ISP or use Hostinger if hosting there)
```

---

## Comparison Matrix

| Feature | Mailu | Docker Mailserver | Stalwart |
|---------|-------|-------------------|----------|
| **Docker containers** | 6-12 | 1 | 1 |
| **RAM (140 mailboxes)** | 4-6 GB | 2-3 GB | 0.5-1 GB |
| **Web Admin UI** | Yes | No | Yes |
| **REST API** | Yes (Swagger) | No | Yes |
| **Webmail** | Yes (Roundcube) | No (bolt-on) | Yes (built-in) |
| **Antispam quality** | Excellent (Rspamd) | Good (configurable) | Good (built-in) |
| **Antivirus** | ClamAV (+1GB RAM) | ClamAV (optional) | External only |
| **DKIM/SPF/DMARC** | Full | Full | Full |
| **CalDAV/CardDAV** | Yes (Radicale) | No | Yes (native) |
| **JMAP support** | No | No | Yes |
| **Setup complexity** | Medium (wizard) | Low (simple) | Low (simple) |
| **Maturity** | High (2016+) | Highest (Postfix/Dovecot) | Medium (2023+) |
| **GitHub stars** | ~8,600 | ~15,000 | ~15,000 |
| **Platform integration** | Good (API) | Poor (CLI only) | Best (REST API + JMAP) |
| **License** | MIT | MIT | AGPL-3.0 |

---

## Recommendation: Stalwart + Amazon SES

### Why Stalwart

1. **REST API is the dealbreaker** - ARCHIE platform needs programmatic mailbox CRUD. Stalwart and Mailu both have APIs; docker-mailserver does not. Stalwart's API is more modern and comprehensive.

2. **Resource efficiency** - On a host already running ARCHIE platform, Ollama (128GB RAM budget), Docker containers, and PostgreSQL, adding 0.5-1GB for Stalwart is negligible. Mailu's 4-6GB is wasteful.

3. **Single container simplicity** - Aligns with ARCHIE's Docker infrastructure patterns. One container to monitor, backup, and upgrade.

4. **Built-in CalDAV/CardDAV** - Calendar and contacts for all 140 mailboxes without additional containers.

5. **JMAP support** - Modern email API enables richer platform integration than IMAP.

6. **PostgreSQL backend option** - Can use ARCHIE's existing PostgreSQL infrastructure for mail metadata storage.

### Why Amazon SES for Relay

1. **Port 25 is almost certainly blocked** on residential 192.168.1.200
2. **$8-10/month** for 140 mailboxes at moderate usage
3. **Best deliverability** - Amazon's IP reputation ensures emails reach Gmail/Outlook
4. **Simple SMTP relay config** - Just set Stalwart's relay host to SES SMTP endpoint

### Proposed Architecture
```
Internet --> NPM (ports 25,587,993,443) --> Stalwart container
                                               |
                                               +--> Outbound via Amazon SES relay
                                               +--> RocksDB or PostgreSQL backend
                                               +--> Web admin at mail.kytranempowerment.com/admin
                                               +--> Webmail at mail.kytranempowerment.com
                                               +--> CalDAV/CardDAV at mail.kytranempowerment.com
```

### Port Mapping
```
25   (SMTP inbound)     --> Stalwart
465  (SMTPS)            --> Stalwart
587  (Submission)       --> Stalwart
993  (IMAPS)            --> Stalwart
443  (HTTPS - webmail)  --> Stalwart (via NPM)
4190 (ManageSieve)      --> Stalwart
8080 (Admin UI)         --> Stalwart (internal only or via NPM)
```

### Integration with ARCHIE Platform
- Use Stalwart REST API to auto-create mailboxes for all 107 agents + 15 functional + 9 department
- Build a mail management module in platform_v2/tools/ that calls Stalwart API
- Sync agent roster changes to mailbox provisioning
- JMAP integration for in-platform email reading/composing

### Risk: Stalwart Maturity
Stalwart is younger (2023+) than Postfix/Dovecot stacks. Mitigation:
- Monitor Stalwart GitHub releases closely
- Keep Mailu as fallback plan (also has REST API)
- Start with a test deployment before migrating all 140 mailboxes
- The 15K+ GitHub stars and active development are encouraging signs

---

## Next Steps (if proceeding)

1. **Verify port 25** - Check if ISP blocks inbound/outbound port 25
2. **Set up Amazon SES** - Verify domain, generate SMTP credentials
3. **Deploy Stalwart** - Single Docker container on 192.168.1.200
4. **Configure DNS** - MX, SPF, DKIM, DMARC records via Hostinger API
5. **NPM proxy** - Route mail.kytranempowerment.com to Stalwart
6. **Test with 5 mailboxes** - Validate send/receive before full rollout
7. **Build ARCHIE integration** - REST API module for bulk mailbox provisioning
8. **Full rollout** - Create all 140+ mailboxes

---

## Sources

- [Mailu Official](https://mailu.io/)
- [Mailu GitHub](https://github.com/Mailu/Mailu)
- [Mailu REST API Docs](https://mailu.io/master/api.html)
- [Mailu Docker Compose Setup](https://mailu.io/2.0/compose/setup.html)
- [docker-mailserver GitHub](https://github.com/docker-mailserver/docker-mailserver)
- [docker-mailserver setup.sh Docs](https://docker-mailserver.github.io/docker-mailserver/latest/config/setup.sh/)
- [Stalwart Official](https://stalw.art/)
- [Stalwart GitHub](https://github.com/stalwartlabs/stalwart)
- [Stalwart Docker Docs](https://stalw.art/docs/install/platform/docker/)
- [Stalwart Management API](https://stalw.art/docs/category/management-api/)
- [Stalwart Web Admin](https://stalw.art/docs/category/web-based-administration/)
- [docker-mailserver vs Stalwart Comparison](https://dev.to/selfhostingsh/docker-mailserver-vs-stalwart-email-servers-4ldd)
- [Mailu vs Stalwart Comparison](https://selfhosting.sh/compare/mailu-vs-stalwart/)
- [Amazon SES Pricing](https://aws.amazon.com/ses/pricing/)
- [Port 25 ISP Blocking Solutions](https://forwardemail.net/en/guides/port-25-blocked-by-isp-workaround)
- [ISP Port 25 Blocking - No-IP](https://blog.noip.com/my-isp-blocks-smtp-port-25-can-i-still-host-a-mail-server)
