# WiFi Sensing Projects Research — Security & Network Integration

**Date**: 2026-03-16
**Purpose**: Evaluate WiFi-based sensing/tracking projects for ARCHIE Security & Network module integration

---

## Project Comparison Table

| Criteria | **ESPectre** | **RuView** | **WiFiTracker** |
|----------|-------------|-----------|----------------|
| **Purpose** | Motion detection via WiFi CSI (Channel State Information) analysis | WiFi DensePose — pose estimation, vital signs, presence detection from WiFi signals | People counting & movement tracking via enterprise WiFi SNMP queries |
| **Technology** | ESP32 + ESPHome + Home Assistant | Rust + ESP32-S3 mesh + Docker server | Python 3.11 microservices + SNMP |
| **How it works** | Analyzes WiFi signal disturbances (CSI subcarrier amplitude/phase) to detect motion — no probe sniffing | Analyzes CSI to reconstruct body position, breathing rate, heart rate; self-learning ML at edge | Queries enterprise AP controllers via SNMP to count connected devices per room |
| **Hardware needed** | ESP32 (~$8 each), existing WiFi router | 3-6x ESP32-S3 (~$9 each) + WiFi router | Enterprise AP controller with SNMP support (Cisco WLC etc.) |
| **Monitor mode adapter?** | **No** — uses CSI from ESP32, not probe requests | **No** — uses CSI from ESP32-S3, not probe requests | **No** — uses SNMP, not monitor mode |
| **Docker support** | No (runs on ESP32 + Home Assistant) | **Yes** — `docker pull ruvnet/wifi-densepose:latest` (amd64 + arm64) | No official Docker; microservice architecture could be containerized |
| **API** | Home Assistant native integration (ESPHome binary sensors) | HTTP server on port 3000; WebSocket for live data; REST endpoints | Streamlit visualization; no documented REST API |
| **License** | GPLv3 | MIT | GPLv3 |
| **Stars** | 6,788 | 37,297 | 6 |
| **Last commit** | 2026-03-15 (very active) | 2026-03-16 (very active) | 2024-10-21 (stale, ~17 months old) |
| **Maturity** | Stable v2.5 with ML detector | Active development, 1300+ tests, 62 ADRs | Academic project, limited maintenance |
| **Privacy** | No cameras, no video, no probe sniffing | No cameras, no video, privacy-first design | Tracks connected MAC addresses (privacy concern) |

---

## What is WiFi CSI Sensing (NOT Probe Request Monitoring)

Important distinction: **None of these projects use probe request monitoring.** They use two different approaches:

### CSI-Based Sensing (ESPectre, RuView)
- **How**: ESP32 chips extract Channel State Information — per-subcarrier amplitude and phase data from WiFi signals
- **What it detects**: Human body presence disturbs the WiFi signal field; CSI changes reveal motion, breathing, heartbeat
- **Privacy**: Does NOT capture MAC addresses, device identifiers, or any personal data — purely physics-based
- **Hardware**: Requires CSI-capable hardware (ESP32-S3 recommended). Standard consumer WiFi NICs only provide RSSI (much less capable)
- **No monitor mode needed**: The ESP32 acts as a dedicated sensor, not a packet sniffer

### SNMP-Based Tracking (WiFiTracker)
- **How**: Queries enterprise access point controllers via SNMP to get connected client counts
- **What it detects**: Number of connected devices per AP/room, movement between APs
- **Privacy**: Works with anonymized MAC addresses but still tracks device associations
- **Hardware**: Requires enterprise WiFi infrastructure with SNMP-enabled controllers
- **Not applicable to home use**: Needs Cisco WLC or similar enterprise AP controllers

---

## WiFi Probe Request Monitoring (Background Context)

For reference, probe request monitoring is a *different* technique not used by these projects:
- Devices broadcast probe requests when searching for WiFi networks
- These contain MAC addresses (though modern devices use MAC randomization)
- Requires a WiFi adapter in **monitor mode** (e.g., Alfa AWUS036ACH, ~$35-50)
- Tools: Kismet, Probemon, Aircrack-ng suite
- **Legal concerns**: In many jurisdictions, passive monitoring of probe requests is legal, but storing/correlating MAC addresses may violate GDPR/privacy laws
- **Effectiveness declining**: iOS 14+, Android 10+ use random MACs for probe requests, reducing tracking accuracy significantly
- **Not recommended** for home security due to privacy concerns and declining effectiveness

---

## Integration Analysis with ARCHIE Security & Network Module

Current module features: AdGuard DNS, device registry, surveillance cameras, Telegram alerts.

### Best Fit: ESPectre (Recommended for Phase 1)

**Why**:
1. **Home Assistant integration** — ARCHIE already runs Docker; Home Assistant can run as a container and expose sensor data via its REST API
2. **Simple hardware** — One ESP32 per room (~$8), no special adapters, no monitor mode
3. **Proven & stable** — v2.5, 6,788 stars, active development, extensive documentation
4. **Privacy-safe** — No cameras, no MAC tracking, no probe sniffing
5. **Complements cameras** — CSI detects through walls and in darkness where cameras fail
6. **Telegram integration** — Home Assistant has native Telegram notification support, aligning with ARCHIE's existing alert system

**Integration approach**:
- ESP32 sensors in key rooms → ESPHome → Home Assistant
- Home Assistant REST API → ARCHIE Security panel polls/subscribes for motion events
- Telegram alerts triggered by ARCHIE when motion detected in secured zones
- Device registry augmented with "presence zones" from CSI data

### Future Consideration: RuView (Phase 2+)

**Why wait**:
1. **More complex** — Requires 3-6 ESP32-S3 per room for full capability
2. **Overkill for home security** — Pose estimation, vital signs, DensePose are impressive but unnecessary for intrusion detection
3. **Docker server available** — Could run on ARCHIE server (`docker run -p 3000:3000 ruvnet/wifi-densepose:latest`)
4. **MIT license** — More permissive than ESPectre's GPLv3
5. **Massive community** — 37K stars, very active
6. **Future value** — If ARCHIE expands to elderly care, health monitoring, or advanced occupancy analytics

### Not Recommended: WiFiTracker

**Why skip**:
- Designed for enterprise/university WiFi infrastructure (SNMP-based)
- Requires Cisco WLC or similar enterprise AP controllers — not applicable to home network
- Stale project (last commit Oct 2024), only 6 stars
- Tracks connected devices, not presence — fundamentally different use case

---

## Hardware Shopping List (ESPectre Phase 1)

| Item | Qty | Cost (approx) | Notes |
|------|-----|---------------|-------|
| ESP32-S3-DevKitC-1 | 3 | $27 total | One per key zone (entry, living, hallway) |
| USB cables | 3 | $10 | Power only (data via WiFi) |
| USB power adapters | 3 | $15 | 5V/1A sufficient |
| **Total** | | **~$52** | No special adapters, no monitor mode hardware |

Optional for RuView later: Same ESP32-S3 boards work for both projects.

---

## Legal/Privacy Summary

| Approach | Legal Risk | Privacy Impact |
|----------|-----------|----------------|
| **CSI sensing (ESPectre/RuView)** | Very low — analyzes signal physics, no PII captured | None — no MAC addresses, no device tracking, no video |
| **Probe monitoring** | Medium — passive capture may be legal but storage/correlation risks GDPR | High — captures MAC addresses even with randomization |
| **SNMP tracking** | Low in own network | Medium — tracks device associations |
| **Camera surveillance** | Low on own property with signage | Medium — captures video of visitors |

**Recommendation**: CSI-based sensing is the most privacy-safe approach and has zero legal risk for home deployment.
