# AI-Powered Security Integrations Research Report
**Date**: 2026-03-16 | **For**: ARCHIE Platform (128GB RAM, Quadro M4000 8GB, Docker)

---

## 1. Home Assistant Camera AI Integration

### Recommended Stack: Frigate + CompreFace

| Tool | Purpose | Docker | GPU | Cost | API | HA Integration |
|------|---------|--------|-----|------|-----|----------------|
| **Frigate 0.16** | NVR + object/face/LPR detection | Yes | CUDA 5.0+ (M4000 = 5.2, compatible) | Free (Frigate+ optional $50/yr) | REST API | Native HA integration |
| **CompreFace** | Dedicated face recognition engine | Yes (CPU + GPU images) | Optional NVIDIA | Free (Apache 2.0) | REST API | Via Double Take |
| **Double Take** | Face recognition UI + automation | Yes | None (delegates to backends) | Free | REST API + MQTT | Native HA via MQTT |
| **CodeProject.AI** | Object detection + face + LPR | Yes | CUDA optional | Free | REST API | HACS custom component |
| **HA Video Vision** | AI video analysis + facial recognition | HACS integration | Local GPU option | Free | HA native | HACS custom integration |

### Recommended Architecture
```
Cameras -> Frigate (object detection, recording, M4000 GPU)
              |
              +-> Built-in face recognition (v0.16+)
              +-> Built-in license plate recognition (v0.16+)
              +-> Double Take (optional, for multi-backend face matching)
                    +-> CompreFace (face DB + REST API)
              |
              +-> MQTT -> Home Assistant (automations, alerts)
```

### Hardware Notes
- **Quadro M4000**: Compute Capability 5.2 (Maxwell). Meets Frigate's minimum (5.0+). Driver must be >= 545.
- Frigate enrichments (face/LPR) can run on CPU with acceptable performance — GPU helps but isn't required for these.
- GPU is most valuable for video decoding (ffmpeg hardware acceleration) and TensorRT object detection.
- CompreFace GPU mode recommended if doing frequent face matching against large databases.

### Key Capabilities
- **Unknown face alerts**: Frigate + Double Take can trigger HA automations when unrecognized faces appear.
- **Package/animal/car detection**: Frigate detects person, car, dog, cat, package, delivery logos out of the box.
- **License plate recognition**: Built into Frigate 0.16. Also achievable via CodeProject.AI ALPR module.
- **Face library**: Upload known faces via Frigate UI or CompreFace API; alerts on unknown faces.

### Value/Effort Rankings
1. **Frigate 0.16** - HIGH value, MEDIUM effort. All-in-one NVR with face+LPR+object detection. Single Docker container.
2. **Double Take + CompreFace** - MEDIUM value, LOW effort. Add-on for face recognition if Frigate's built-in isn't sufficient.
3. **CodeProject.AI** - MEDIUM value, MEDIUM effort. Alternative detection engine, good for LPR if Frigate LPR is insufficient.
4. **HA Video Vision** - LOW-MEDIUM value, LOW effort. HACS integration, simpler but less powerful.

---

## 2. AdGuard DNS Security Features

### Current Capabilities (Already Available)
- DNS-over-HTTPS (DoH) and DNS-over-TLS (DoT) built into AdGuard Home
- Custom filtering rules with regex and modifier tags (more powerful than Pi-hole syntax)
- Auto-update of blocklists on configurable schedule (already built-in)

### Recommended Blocklists to Add

| List | Purpose | URL |
|------|---------|-----|
| **HaGeZi Pro** | Comprehensive ad/tracker/malware blocking | `https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/adblock/pro.txt` |
| **HaGeZi Threat Intelligence Feeds** | C2, malware, phishing domains | `https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/adblock/tif.txt` |
| **OISD Big** | Curated multi-source blocklist | `https://big.oisd.nl` |
| **ph00lt0 Blocklist** | Combined 80+ lists in one | `https://raw.githubusercontent.com/ph00lt0/blocklist/master/blocklist.txt` |
| **1Hosts Pro** | Privacy + security focused | `https://o0.pages.dev/Pro/adblock.txt` |

### Advanced Configuration
- **Upstream DNS**: Use DoH upstream (e.g., `https://dns.cloudflare.com/dns-query` or `https://dns.quad9.net/dns-query`)
- **Bootstrap DNS**: `1.1.1.1` and `9.9.9.9` for resolving DoH hostnames
- **DNSSEC**: Enable in AdGuard settings for response validation
- **Rewrites**: Use DNS rewrites for internal service discovery
- **Query Log Analysis**: AdGuard's query log can feed into SIEM for anomaly detection

### Integration with ARCHIE
- AdGuard exposes a REST API — Vigil (security agent) could query it for blocked domain stats
- Query logs can be parsed for threat intelligence (domains hitting malware lists)
- No additional tools needed — AdGuard is already well-equipped

### Value/Effort Rankings
1. **Add HaGeZi TIF + Pro lists** - HIGH value, MINIMAL effort. Just add URLs to AdGuard blocklist config.
2. **Enable DoH upstream** - HIGH value, MINIMAL effort. Single config change.
3. **Enable DNSSEC** - MEDIUM value, MINIMAL effort. Toggle in settings.
4. **API integration with ARCHIE** - MEDIUM value, LOW effort. REST API already available.

---

## 3. Network Security AI Tools

### Recommended Stack: CrowdSec + Suricata

| Tool | Purpose | Docker | RAM | Cost | API | HA Integration |
|------|---------|--------|-----|------|-----|----------------|
| **CrowdSec** | Collaborative IPS, behavioral analysis | Yes | ~512MB | Free (community) | REST API (LAPI) | Official HA add-on |
| **Suricata** | Signature-based IDS/IPS, deep packet inspection | Yes | 1-4GB | Free | EVE JSON logs | Via CrowdSec |
| **Maltrail** | Malicious traffic detection | Yes | ~256MB | Free | Web UI + API | No native |

### CrowdSec Details
- **How it works**: Parses logs (nginx, SSH, HA, etc.), detects attack patterns, shares threat intel with community, receives crowd-sourced blocklists.
- **60x faster** than Fail2ban for log processing.
- **Bouncers**: Remediation components that enforce decisions (firewall, nginx, Cloudflare).
- **Split architecture**: Detection on one server, remediation on others.
- **Home Assistant add-on**: Official add-on detects brute-force attacks on HA login.
- **Free tier**: Community edition is fully free. Premium adds console features.

### CrowdSec + Suricata Integration
- CrowdSec has an official Suricata collection — parses Suricata's EVE JSON logs.
- Detects high/medium severity alerts, auto-blocks offending IPs, shares with community.
- **Best approach**: Run both. Suricata for network-level detection, CrowdSec for log-based behavioral analysis.

### Integration with Existing Argus Tools
- **nmap results** -> Feed scan results into CrowdSec as custom scenarios
- **nuclei results** -> Parse vulnerability findings, auto-create CrowdSec alerts for confirmed issues
- **nikto results** -> Similar integration path via custom parsers

### Value/Effort Rankings
1. **CrowdSec** - HIGH value, LOW effort. Docker container, official HA add-on, immediate community blocklists.
2. **Suricata** - HIGH value, MEDIUM effort. Needs network mirroring/inline setup, but powerful.
3. **CrowdSec + Suricata collection** - HIGH value, LOW effort (once both are running).
4. **Maltrail** - MEDIUM value, LOW effort. Simple traffic monitoring.

---

## 4. Automated Security Agent Actions

### IP Reputation APIs (Free Tiers)

| Service | Free Tier | Best For |
|---------|-----------|----------|
| **AbuseIPDB** | 1,000 lookups/day | IP abuse reputation |
| **VirusTotal** | 500 requests/day | File/URL/domain scanning |
| **Shodan** | Limited (paid for full) | Internet-facing service discovery |
| **GreyNoise** | 50 lookups/day (community) | Mass scanner identification |
| **URLhaus** | Unlimited | Malware URL detection |

### SSL/TLS Certificate Monitoring

| Tool | Cost | Method |
|------|------|--------|
| **Cert Spotter** (SSLMate) | Free hosted | CT log monitoring, Slack alerts |
| **LetsMonitor.org** | Free | Email alerts on expiry |
| **TrackSSL** | Free | Expiry + change notifications |
| **Red Sift Certificates Lite** | Free (250 certs) | Let's Encrypt recommended |
| **Custom script** | Free | `openssl s_client` + cron |

### Honeypot: OpenCanary

- **Docker**: Yes (Linux host only, needs `--network=host`)
- **RAM**: ~512MB (runs on Raspberry Pi)
- **Services emulated**: SSH, HTTP, FTP, MySQL, SMB, RDP, Redis, SNMP, SIP, Telnet, Git, NTP, TFTP
- **Alerting**: Syslog, email, file logging — can feed into SIEM
- **Configuration**: JSON config file, enable/disable services individually
- **Use case**: Deploy on unused ports to detect lateral movement or external probing

### SIEM-Lite: Wazuh vs Graylog

| Tool | Docker | RAM Required | Best For |
|------|--------|-------------|----------|
| **Wazuh** | Yes (3 containers) | 6GB minimum | Full XDR + SIEM, vulnerability detection, compliance |
| **Graylog Open** | Yes | 4GB minimum | Log aggregation + analysis, lighter weight |
| **Prelude SIEM** | Yes | 2-4GB | Integrates with Suricata/OSSEC/Snort |

**Recommendation**: Wazuh is the most complete but resource-heavy. With 128GB RAM, it's easily feasible. However, for a home server, **CrowdSec + OpenCanary + log aggregation** may be more practical than a full SIEM.

### Automated Scanning Schedule (for Argus/Vigil)
```
Daily:    SSL cert expiry check (custom script)
Daily:    AbuseIPDB lookup on flagged IPs from CrowdSec
Weekly:   nmap scan of external-facing services
Weekly:   nuclei scan with latest templates
Monthly:  nikto web vulnerability scan
On-event: VirusTotal lookup on suspicious files/URLs
```

### Value/Effort Rankings
1. **OpenCanary** - HIGH value, LOW effort. Single Docker container, immediate attacker detection.
2. **AbuseIPDB + VirusTotal API integration** - HIGH value, LOW effort. Simple REST calls, generous free tiers.
3. **SSL cert monitoring** - MEDIUM value, MINIMAL effort. Free services, email alerts.
4. **Wazuh SIEM** - HIGH value, HIGH effort. Powerful but complex setup.
5. **Automated scan scheduling** - HIGH value, MEDIUM effort. Cron jobs + result parsing.

---

## 5. Master Recommendation Matrix

### Tier 1: Deploy Now (High Value, Low Effort)

| # | Tool | Purpose | RAM | Docker Containers |
|---|------|---------|-----|-------------------|
| 1 | **CrowdSec** | Collaborative IPS + community blocklists | 512MB | 1 |
| 2 | **AdGuard blocklist upgrade** | HaGeZi TIF + Pro lists | 0 (config change) | 0 |
| 3 | **OpenCanary** | Honeypot for attacker detection | 512MB | 1 |
| 4 | **AbuseIPDB/VirusTotal API** | IP reputation checking | 0 (API calls) | 0 |

**Total additional RAM**: ~1GB

### Tier 2: Deploy Soon (High Value, Medium Effort)

| # | Tool | Purpose | RAM | Docker Containers |
|---|------|---------|-----|-------------------|
| 5 | **Frigate 0.16** | AI camera NVR with face+LPR | 2-4GB + GPU | 1 |
| 6 | **Suricata** | Network IDS/IPS | 1-4GB | 1 |
| 7 | **CrowdSec HA add-on** | Protect Home Assistant login | Minimal | HA add-on |
| 8 | **SSL cert monitoring** | Certificate expiry alerts | 0 | 0 |

**Total additional RAM**: ~4-8GB

### Tier 3: Deploy Later (High Value, High Effort)

| # | Tool | Purpose | RAM | Docker Containers |
|---|------|---------|-----|-------------------|
| 9 | **CompreFace** | Face recognition database + API | 1-2GB | 3 (API, DB, admin) |
| 10 | **Double Take** | Face recognition orchestration | 512MB | 1 |
| 11 | **Wazuh** | Full SIEM/XDR platform | 6GB+ | 3 |
| 12 | **Automated scan pipeline** | Scheduled nmap/nuclei/nikto | 512MB | 1 (custom) |

**Total additional RAM**: ~8-10GB

### Total Resource Budget
- **All tiers combined**: ~13-19GB additional RAM (easily within 128GB budget)
- **GPU**: Frigate uses M4000 for video decode + TensorRT detection. CompreFace can share GPU.
- **Disk**: Frigate recording storage is the biggest consideration (plan 500GB+ for camera recordings)

---

## 6. ARCHIE Integration Architecture

```
                    ARCHIE Platform
                         |
          +--------------+--------------+
          |              |              |
     Vigil Agent    Argus Module    Bridge Dispatcher
     (Security)    (Scanning)     (Orchestration)
          |              |              |
     +----+----+    +----+----+    +----+----+
     |         |    |         |    |         |
  CrowdSec  AdGuard nmap    nuclei Frigate  Suricata
  (IPS)     (DNS)   nikto          (Cameras) (IDS)
     |                              |
  OpenCanary                    CompreFace
  (Honeypot)                   (Face DB)
     |                              |
  AbuseIPDB/VT                 Double Take
  (IP Reputation)              (HA Automations)
```

### Integration Points for ARCHIE Agents
- **Vigil**: Monitor CrowdSec decisions API, check AbuseIPDB for flagged IPs, parse AdGuard query logs
- **Argus**: Schedule nmap/nuclei/nikto scans, feed results to CrowdSec custom scenarios
- **Sentry**: Monitor Suricata EVE JSON alerts, correlate with CrowdSec decisions
- **Bridge**: Dispatch security alerts to appropriate agents, escalate via Telegram

---

## Sources

### Camera AI
- [Frigate Face Recognition Docs](https://docs.frigate.video/configuration/face_recognition/)
- [Frigate License Plate Recognition](https://docs.frigate.video/configuration/license_plate_recognition/)
- [Frigate Hardware Requirements](https://docs.frigate.video/frigate/hardware/)
- [Frigate 0.16 Facial + LPR Announcement](https://idtechwire.com/frigate-0-16-adds-facial-and-license-plate-recognition-to-open-source-nvr/)
- [CompreFace GitHub](https://github.com/exadel-inc/CompreFace)
- [CodeProject.AI HA Integration](https://github.com/codeproject/CodeProject.AI-HomeAssist-ObjectDetect)
- [HA Video Vision Custom Integration](https://community.home-assistant.io/t/custom-integration-ha-video-vision-ai-video-analysis-facial-recognition/968110)
- [Local LPR Guide with CodeProject.AI + Frigate](https://community.home-assistant.io/t/guide-local-license-plate-recognition-with-home-assistant-codeproject-ai-and-frigate/627745)

### DNS Security
- [HaGeZi DNS Blocklists](https://github.com/hagezi/dns-blocklists)
- [AdGuard/Pi-hole Blocklists 2025](https://windgate.net/adguard-privacy-security-block-lists-2025/)
- [DNS Security and Threat Intelligence](https://ismalicious.com/posts/dns-security-threat-intelligence-blocklist)
- [Best Malware Blocklists](https://cyberhost.uk/malware-blocklists-pi-hole-adguard-home/)

### Network Security
- [CrowdSec vs Suricata](https://www.crowdsec.net/blog/suricata-vs-crowdsec)
- [CrowdSec vs Fail2Ban](https://www.crowdsec.net/blog/crowdsec-not-your-typical-fail2ban-clone)
- [CrowdSec HA Add-ons](https://github.com/crowdsecurity/home-assistant-addons)
- [CrowdSec Docker Setup Guide](https://www.simplehomelab.com/udms-22-crowdsec-docker-compose/)

### SIEM & Honeypots
- [Wazuh Docker Deployment](https://documentation.wazuh.com/current/deployment-options/docker/wazuh-container.html)
- [OpenCanary GitHub](https://github.com/thinkst/opencanary)
- [Best Open Source SIEM Tools 2026](https://www.sentinelone.com/cybersecurity-101/data-and-ai/open-source-siem-tools/)
- [Best Honeypot Solutions 2026](https://anantis.io/best-honeypot-solutions-in-2026-including-open-source/)

### Threat Intelligence APIs
- [Best Threat Intelligence APIs 2026](https://ismalicious.com/posts/best-threat-intelligence-api-comparison-2026)
- [AbuseIPDB](https://www.abuseipdb.com/)
- [Cert Spotter](https://github.com/SSLMate/certspotter)
- [Let's Encrypt Monitoring Options](https://letsencrypt.org/docs/monitoring-options/)
