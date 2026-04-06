# Security Network Ultimate — 15 Features Design Spec

**Date**: 2026-04-05
**Module**: `platform_v2/tools/security_network/`
**Pattern**: ADR-045 route splitting, digest alerts, jobs in `jobs.py`

## Tab Layout

### New Tabs
- **Topology** — D3.js force-directed network map, device connections, traffic flows
- **Parental Controls** — Per-device/user schedules, content blocking via AdGuard client rules
- **Reports** — Weekly PDF, incident correlation view, threat intel feed status

### Existing Tab Additions
- **Overview** — Threat intel hits badge, incident count
- **Devices** — Bandwidth charts (Chart.js), fingerprint (OS/ports), WOL button, traffic class pie
- **Traffic** — Speed test widget, PCAP capture button
- **DNS** — Sinkhole analytics (blocked by category), VPN leak alerts
- **Monitoring** — Port change alerts, honeypot hit log

## Features by Tier

### Tier 1 — High Impact

#### 1. Network Topology Map
- D3.js force-directed graph on new Topology tab
- Nodes = devices (sized by bandwidth), edges = traffic flows
- Color by device type, click to open device detail
- API: `GET /api/topology/graph` — returns nodes + links from device registry + traffic stats
- Route file: `topology_routes.py`

#### 2. Bandwidth Usage Charts
- Chart.js line charts on Devices tab (per-device detail modal)
- Hourly/daily/weekly views, per-user aggregate view
- API: `GET /api/devices/bandwidth-history/<ip>?period=24h|7d|30d`
- Data source: `network_traffic_stats` (already collected every 5 min)
- Route file: extends `device_routes.py`

#### 3. Device Fingerprinting
- nmap scan (-O -sV) per device, scheduled weekly + on-demand
- Store OS, open ports, services in `device_fingerprints` table
- Job: `scan_device_fingerprints` (weekly Sunday 4 AM)
- API: `GET /api/devices/fingerprint/<ip>`, `POST /api/devices/fingerprint/<ip>/scan`
- Route file: `fingerprint_routes.py`

#### 4. Threat Intelligence Feeds
- Pull IOCs from abuse.ch URLhaus, Feodo Tracker, SSL Blacklist
- Cross-reference against `device_dns_history` domains
- Store in `threat_intel_iocs` + `threat_intel_hits`
- Job: `sync_threat_intel` (every 6h), `check_threat_intel_hits` (every 30 min)
- API: `GET /api/threat-intel/status`, `GET /api/threat-intel/hits`
- Route file: `threat_intel_routes.py`
- Service file: `threat_intel_service.py`

#### 5. Weekly Security PDF Report
- Auto-generated Monday 8 AM, sent via Telegram
- Sections: bandwidth summary, top users, blocked domains, anomalies, compliance score, new devices, V.I.G.I.L. summary
- Uses reportlab or weasyprint for PDF generation
- API: `POST /api/reports/generate-weekly`, `GET /api/reports/list`, `GET /api/reports/download/<id>`
- Job: `generate_weekly_report` (Monday 8 AM cron)
- Route file: extends `report_routes.py`
- Service file: `report_generator.py`

### Tier 2 — Quality of Life

#### 6. Parental Controls
- New tab: per-device/user internet schedules
- Uses AdGuard client API to set per-client blocking schedules
- Content categories: social, gaming, streaming, adult
- DB: `parental_schedules` (device_mac, schedule JSON, categories)
- Job: `enforce_parental_schedules` (every 5 min)
- API: CRUD at `/api/parental/schedules`
- Route file: `parental_routes.py`
- Service file: `parental_service.py`

#### 7. Alert Correlation / Incidents
- Group related alerts into incidents (same device within time window)
- DB: `security_incidents` (status, severity, device_ip, alert_ids[], created_at)
- Auto-create incident when 3+ alerts for same device in 1 hour
- API: `GET /api/incidents`, `POST /api/incidents/<id>/resolve`
- Shows on Reports tab + Overview badge
- Route file: `incident_routes.py`
- Service file: `incident_service.py`

#### 8. Network Speed Testing
- speedtest-cli periodic runs with historical Chart.js graph
- DB: `speed_test_results` (download_mbps, upload_mbps, ping_ms, server, tested_at)
- Job: `run_speed_test` (every 6h)
- Widget on Traffic tab
- API: `GET /api/speed-test/history`, `POST /api/speed-test/run`
- Route file: `speed_test_routes.py`

#### 9. Port Change Detection
- Compare nmap results between scans, alert on new open ports
- Uses `device_fingerprints` + `port_scan_history` tables
- Job: runs as part of `scan_device_fingerprints`, diffs results
- API: `GET /api/devices/port-changes`
- Shows on Monitoring tab
- Extends fingerprint_routes.py

#### 10. DNS Sinkhole Analytics
- Dashboard showing what AdGuard blocks by category
- Categories: ads, trackers, malware, adult, social, gaming
- API: `GET /api/dns/sinkhole-stats?hours=24`
- Chart.js pie chart + table on DNS tab
- Route: extends existing DNS routes or analytics_routes.py

### Tier 3 — Advanced

#### 11. Internal Honeypot
- Lightweight TCP listener on unused IPs/ports
- Any connection = alert (lateral movement indicator)
- DB: `honeypot_events` (source_ip, dest_port, timestamp, payload_preview)
- Python asyncio server in a thread, configurable ports
- API: `GET /api/honeypot/events`, `POST /api/honeypot/config`
- Route file: `honeypot_routes.py`
- Service file: `honeypot_service.py`

#### 12. PCAP Capture on Demand
- Trigger tcpdump for specific device IP from dashboard
- Store captures as .pcap files, metadata in DB
- DB: `pcap_captures` (device_ip, file_path, duration, size, started_at)
- API: `POST /api/pcap/start`, `POST /api/pcap/stop/<id>`, `GET /api/pcap/list`
- Button on device detail modal + Traffic tab
- Route file: `pcap_routes.py`

#### 13. Wake-on-LAN
- Send WOL magic packet to any device by MAC
- Button on device detail + Devices tab
- API: `POST /api/devices/wol/<mac>`
- No DB needed, uses socket broadcast
- Extends device_routes.py

#### 14. VPN Split-Tunnel Detection
- Detect devices on VPN that leak DNS outside tunnel
- Compare device DNS queries against expected VPN DNS servers
- Alert when device with known VPN also queries public DNS
- Job: `check_vpn_leaks` (every 30 min)
- Shows on DNS tab
- Extends analytics_routes.py

#### 15. Traffic Classification
- Categorize bandwidth by type using domain-to-category mapping
- Categories: streaming, gaming, work, social, shopping, cloud, other
- DB: `traffic_categories` (domain_pattern, category) — seed + learn
- Pie chart per device and per user on Devices tab
- API: `GET /api/devices/traffic-breakdown/<ip>`, `GET /api/traffic/categories`
- Extends analytics_routes.py

## New DB Tables Summary

```sql
device_fingerprints (device_ip, device_mac, os_name, os_version, open_ports JSONB, services JSONB, scanned_at)
threat_intel_iocs (id, feed_name, ioc_type, ioc_value, severity, first_seen, last_updated)
threat_intel_hits (id, device_ip, domain, ioc_id FK, detected_at)
speed_test_results (id, download_mbps, upload_mbps, ping_ms, jitter_ms, server, tested_at)
port_scan_history (id, device_ip, port, service, state, first_seen, last_seen)
parental_schedules (id, device_mac, user_name, schedule JSONB, blocked_categories TEXT[], enabled, created_at)
security_incidents (id, title, severity, device_ip, alert_ids INTEGER[], status, created_at, resolved_at)
honeypot_events (id, source_ip, source_mac, dest_port, protocol, payload_preview, detected_at)
pcap_captures (id, device_ip, file_path, duration_sec, file_size, status, started_at, stopped_at)
traffic_categories (id, domain_pattern, category, source, created_at)
```

## New Route Files
- `topology_routes.py`
- `fingerprint_routes.py`
- `threat_intel_routes.py`
- `parental_routes.py`
- `incident_routes.py`
- `speed_test_routes.py`
- `honeypot_routes.py`
- `pcap_routes.py`

## New Service Files
- `threat_intel_service.py`
- `report_generator.py`
- `parental_service.py`
- `incident_service.py`
- `honeypot_service.py`

## Build Order
1. DB migration (all tables at once)
2. Tier 1: topology, bandwidth charts, fingerprinting, threat intel, weekly report
3. Tier 2: parental, incidents, speed test, port detection, sinkhole
4. Tier 3: honeypot, PCAP, WOL, VPN leak, traffic classification
5. JS wiring for all features
6. Register all route files in __init__.py
