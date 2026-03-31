# i18n Audit: Security Network Module

**File**: `/mnt/archie_brain/platform_v2/templates/tools/security_network.html`
**Lines**: 4,766
**Date**: 2026-03-31
**Key prefix**: `sn.`

## Summary

| Category | Count |
|----------|-------|
| HTML elements missing `data-i18n` | 202 |
| JS strings needing `t()` wrapping | 318 |
| **Total untranslated text** | **520** |
| Elements already translated | ~12 (stat cards on dashboard, a few tab labels) |

The module is approximately **2% translated**. Only the dashboard stat cards and 3 tab labels (Compliance, Hardening, Domain Manager) have `data-i18n` attributes.

---

## HTML Elements Missing `data-i18n`

### Header & Navigation

| Line | Element | Current Text | Suggested Key |
|------|---------|-------------|---------------|
| 49 | lcars-bar-status | SEC OPS | sn.header.status |
| 55 | svc-badge | AdGuard | sn.service.adguard |
| 56 | svc-badge | Hostinger | sn.service.hostinger |
| 57 | svc-badge | Cameras | sn.service.cameras |
| 58 | svc-badge | NPM | sn.service.npm |
| 59 | svc-badge | SSH | sn.service.ssh |
| 60 | svc-badge | fail2ban | sn.service.fail2ban |
| 61 | svc-badge | DDNS | sn.service.ddns |
| 62 | svc-badge | Argus | sn.service.argus |
| 63 | svc-badge | Agent | sn.service.agent |

### Tab Buttons (7 of 10 missing)

| Line | Element | Current Text | Suggested Key |
|------|---------|-------------|---------------|
| 68 | tab-btn | Dashboard | sn.tab.dashboard |
| 72 | tab-btn | AdGuard DNS | sn.tab.adguard_dns |
| 76 | tab-btn | Surveillance | sn.tab.surveillance |
| 80 | tab-btn | Reconnaissance | sn.tab.reconnaissance |
| 84 | tab-btn | Scanning | sn.tab.scanning |
| 88 | tab-btn | Access Control | sn.tab.access_control |
| 92 | tab-btn | Reports | sn.tab.reports |

### Dashboard Tab

| Line | Element | Current Text | Suggested Key |
|------|---------|-------------|---------------|
| 114 | stn-ops-title | SECURITY OPERATIONS | sn.dashboard.ops_title |
| 116 | stn-ops-status | ONLINE | sn.dashboard.status_online |
| 152 | card-title | STIG Compliance | sn.dashboard.stig_compliance |
| 153 | button | View Details | sn.dashboard.view_details |
| 162 | div | Ubuntu 22.04 | sn.dashboard.ubuntu_label |
| 166 | div | Docker | sn.dashboard.docker_label |
| 170 | div | Network | sn.dashboard.network_label |
| 175 | div | Last Scan | sn.dashboard.last_scan |
| 176 | div | Never | sn.dashboard.never |
| 186 | button | Refresh | sn.action.refresh |
| 200 | span | DNS Protection | sn.dashboard.dns_protection |

### AdGuard DNS Tab

| Line | Element | Current Text | Suggested Key |
|------|---------|-------------|---------------|
| 227 | tab-btn | Clients | sn.dns.clients_tab |
| 255 | placeholder | Domain or client... | sn.dns.search_placeholder |
| 288 | placeholder | Filter name | sn.dns.filter_name_placeholder |
| 292 | placeholder | https://... | sn.dns.filter_url_placeholder |
| 310 | placeholder | local.example.com | sn.dns.rewrite_domain_placeholder |
| 314 | placeholder | 192.168.1.100 | sn.dns.rewrite_ip_placeholder |
| 327 | card-title | Quick Block / Unblock | sn.dns.quick_block_title |
| 331 | label | Domain | sn.dns.domain_label |
| 332 | placeholder | example.com | sn.dns.domain_placeholder |
| 334 | button | Block | sn.dns.block_btn |
| 335 | button | Unblock | sn.dns.unblock_btn |
| 343 | placeholder | # Custom AdGuard filtering rules... | sn.dns.custom_rules_placeholder |

### Surveillance Tab (Devices)

| Line | Element | Current Text | Suggested Key |
|------|---------|-------------|---------------|
| 350 | stat-label | Total Devices | sn.surveillance.total_devices |
| 351 | stat-label | Online Now | sn.surveillance.online_now |
| 352 | stat-label | Unregistered | sn.surveillance.unregistered |
| 358 | h4 | Unregistered Devices | sn.surveillance.unregistered_devices |
| 361 | th | IP | sn.surveillance.ip_header |
| 370 | option | All Zones | sn.surveillance.all_zones |
| 371 | option | Trusted | sn.surveillance.zone_trusted |
| 372 | option | Family | sn.surveillance.zone_family |
| 373 | option | Guest | sn.surveillance.zone_guest |
| 374 | option | IoT | sn.surveillance.zone_iot |
| 375 | option | Quarantined | sn.surveillance.zone_quarantined |
| 378 | option | All Types | sn.surveillance.all_types |
| 379 | option | Phone | sn.surveillance.type_phone |
| 380 | option | Laptop | sn.surveillance.type_laptop |
| 381 | option | Desktop | sn.surveillance.type_desktop |
| 382 | option | Tablet | sn.surveillance.type_tablet |
| 383 | option | Server | sn.surveillance.type_server |
| 384 | option | Camera | sn.surveillance.type_camera |
| 385 | option | Smart TV | sn.surveillance.type_smart_tv |
| 386 | option | IoT | sn.surveillance.type_iot |
| 387 | option | Gaming | sn.surveillance.type_gaming |
| 388 | option | Other | sn.surveillance.type_other |
| 390 | button | Refresh | sn.action.refresh |
| 391 | button | Sync to AdGuard | sn.surveillance.sync_adguard |
| 397 | th | Name | sn.surveillance.name_header |
| 420 | inline-text | HOME ASSISTANT | sn.surveillance.home_assistant |

### Camera Feed Modal

| Line | Element | Current Text | Suggested Key |
|------|---------|-------------|---------------|
| 464 | bm-header-title | CAMERA FEED | sn.camera.feed_title |
| 477 | button | Close | sn.action.close |
| 478 | button | Refresh Snapshot | sn.camera.refresh_snapshot |

### Reconnaissance Tab

| Line | Element | Current Text | Suggested Key |
|------|---------|-------------|---------------|
| 504 | placeholder | example.com or 192.168.1.0/24 | sn.recon.target_placeholder |

### Scanning Tab

| Line | Element | Current Text | Suggested Key |
|------|---------|-------------|---------------|
| 565 | placeholder | IP, hostname, or URL | sn.scanning.target_placeholder |

### Access Control Tab (UFW)

| Line | Element | Current Text | Suggested Key |
|------|---------|-------------|---------------|
| 614 | card-title | UFW Firewall | sn.access.ufw_title |
| 616 | button | Enable | sn.access.enable_btn |
| 617 | button | Disable | sn.access.disable_btn |
| 629 | label | Port | sn.access.port_label |
| 630 | placeholder | 443 | sn.access.port_placeholder |
| 633 | label | Protocol | sn.access.protocol_label |
| 635 | option | TCP | sn.access.tcp |
| 636 | option | UDP | sn.access.udp |
| 640 | label | Action | sn.access.action_label |
| 642 | option | Allow | sn.access.allow |
| 643 | option | Deny | sn.access.deny |
| 647 | label | From (optional) | sn.access.from_label |
| 648 | placeholder | 192.168.1.0/24 | sn.access.from_placeholder |
| 650 | button | Add Rule | sn.access.add_rule |
| 674 | placeholder | 192.168.1.x | sn.access.ip_placeholder |
| 678 | placeholder | Reason for blocking | sn.access.reason_placeholder |

### Reports Tab

| Line | Element | Current Text | Suggested Key |
|------|---------|-------------|---------------|
| 726 | inline-text | Generate Report | sn.reports.generate_title |
| 730 | label | Report Type | sn.reports.type_label |
| 732 | option | Daily Summary | sn.reports.daily_summary |
| 733 | option | Weekly Report | sn.reports.weekly_report |
| 734 | option | Device Audit | sn.reports.device_audit |
| 735 | option | DNS Analysis | sn.reports.dns_analysis |
| 739 | label | From (optional) | sn.reports.from_label |
| 743 | label | To (optional) | sn.reports.to_label |
| 760 | h3 | Report History | sn.reports.history_title |

### Compliance Tab

| Line | Element | Current Text | Suggested Key |
|------|---------|-------------|---------------|
| 777 | h3 | Compliance Dashboard | sn.compliance.dashboard_title |
| 781 | button | PDF Report | sn.compliance.pdf_report |
| 782 | button | Export | sn.compliance.export |
| 783 | button | Evidence ZIP | sn.compliance.evidence_zip |
| 784 | button | Run Scan | sn.compliance.run_scan |
| 791 | label | Overall | sn.compliance.overall |
| 796 | inline-text | NO DATA | sn.compliance.no_data |
| 797 | inline-text | Run a scan to begin | sn.compliance.scan_prompt |
| 804 | span | Frameworks | sn.compliance.frameworks |
| 809 | inline-text | Awaiting scan data... | sn.compliance.awaiting_data |
| 818 | span | Findings | sn.compliance.findings |
| 821 | option | All Packs | sn.compliance.all_packs |
| 822 | option | Ubuntu 22.04 | sn.compliance.ubuntu |
| 823 | option | Docker | sn.compliance.docker |
| 824 | option | Network | sn.compliance.network |
| 825 | option | HIPAA | sn.compliance.hipaa |
| 828 | option | All Severity | sn.compliance.all_severity |
| 829 | option | Critical | sn.compliance.critical |
| 830 | option | High | sn.compliance.high |
| 831 | option | Medium | sn.compliance.medium |
| 832 | option | Low | sn.compliance.low |
| 835 | option | All Status | sn.compliance.all_status |
| 836 | option | Pass | sn.compliance.pass |
| 837 | option | Fail | sn.compliance.fail |
| 838 | option | Error | sn.compliance.error |
| 853 | span | Evidence Collection | sn.compliance.evidence_collection |
| 866 | span | Scan History | sn.compliance.scan_history |

### Hardening Tab

| Line | Element | Current Text | Suggested Key |
|------|---------|-------------|---------------|
| 879 | h3 | System Hardening | sn.hardening.title |
| 880 | inline-text | One-click fixes for compliance failures | sn.hardening.subtitle |

### Domain Manager Tab

| Line | Element | Current Text | Suggested Key |
|------|---------|-------------|---------------|
| 894 | tab-btn | Overview | sn.domains.tab_overview |
| 895 | tab-btn | DNS Records | sn.domains.tab_dns |
| 896 | tab-btn | Proxy Hosts | sn.domains.tab_proxy |
| 897 | tab-btn | SSL Certificates | sn.domains.tab_ssl |
| 898 | tab-btn | Quick Setup | sn.domains.tab_quick_setup |
| 905 | stat-label | Public IP | sn.domains.public_ip |
| 907 | inline-text | Refresh | sn.action.refresh |
| 910 | stat-label | Domain | sn.domains.domain_label |
| 911 | inline-text | kytranempowerment.com | sn.domains.domain_value |
| 912 | stat-subtitle | Root domain | sn.domains.root_domain |
| 915 | stat-label | DNS Records | sn.domains.dns_records |
| 917 | stat-subtitle | Total records | sn.domains.total_records |
| 920 | stat-label | Proxy Hosts | sn.domains.proxy_hosts |
| 922 | stat-subtitle | NPM managed | sn.domains.npm_managed |
| 925 | stat-label | SSL Certificates | sn.domains.ssl_certs |
| 927 | stat-subtitle | Let's Encrypt | sn.domains.lets_encrypt |
| 931 | h3 | Subdomain Map | sn.domains.subdomain_map |
| 936 | th | Subdomain | sn.domains.th_subdomain |
| 937 | th | DNS IP | sn.domains.th_dns_ip |
| 938 | th | NPM Target | sn.domains.th_npm_target |
| 939 | th | SSL | sn.domains.th_ssl |
| 940 | th | Actions | sn.domains.th_actions |
| 960 | h4 | Add DNS Record | sn.domains.add_dns_record |
| 963 | label | Type | sn.domains.type_label |
| 966 | option | CNAME | sn.domains.cname |
| 967 | option | TXT | sn.domains.txt |
| 968 | option | MX | sn.domains.mx |
| 972 | label | Name | sn.domains.name_label |
| 973 | placeholder | subdomain | sn.domains.subdomain_placeholder |
| 976 | label | Content | sn.domains.content_label |
| 977 | placeholder | IP or value | sn.domains.content_placeholder |
| 980 | label | TTL | sn.domains.ttl_label |
| 983 | button | Add Record | sn.domains.add_record_btn |
| 991 | th | Type | sn.domains.th_type |
| 992 | th | Name | sn.domains.th_name |
| 993 | th | Content | sn.domains.th_content |
| 994 | th | TTL | sn.domains.th_ttl |
| 1016 | th | Domain | sn.domains.th_domain |
| 1017 | th | Forward Target | sn.domains.th_forward_target |
| 1018 | th | SSL | sn.domains.th_ssl_status |
| 1019 | th | Status | sn.domains.th_status |
| 1020 | th | Actions | sn.domains.th_actions_proxy |
| 1042 | th | Domain(s) | sn.domains.th_domains |
| 1043 | th | Provider | sn.domains.th_provider |
| 1044 | th | Valid From | sn.domains.th_valid_from |
| 1045 | th | Expires | sn.domains.th_expires |
| 1046 | th | Status | sn.domains.th_cert_status |
| 1069 | label | Subdomain | sn.domains.setup_subdomain |
| 1071 | placeholder | myapp | sn.domains.setup_subdomain_placeholder |
| 1076 | label | Forward Host | sn.domains.setup_forward_host |
| 1080 | label | Forward Port | sn.domains.setup_forward_port |

### Modals

| Line | Element | Current Text | Suggested Key |
|------|---------|-------------|---------------|
| 1114 | bm-header-title | BLOCK DOMAIN | sn.modal.block_domain_title |
| 1123 | label | Domain to Block | sn.modal.domain_to_block |
| 1124 | placeholder | example.com | sn.modal.block_domain_placeholder |
| 1126 | inline-text | This will add the domain to AdGuard's block list... | sn.modal.block_domain_warning |
| 1129 | button | Cancel | sn.action.cancel |
| 1130 | button | Block Domain | sn.modal.block_domain_btn |
| 1158 | bm-header-title | EDIT DNS RECORD | sn.modal.edit_dns_title |
| 1167 | label | Type | sn.modal.dns_type_label |
| 1170-1174 | option | A/CNAME/TXT/MX/AAAA/NS | sn.modal.dns_type_* |
| 1176 | label | Name | sn.modal.dns_name_label |
| 1177 | placeholder | subdomain | sn.modal.dns_name_placeholder |
| 1178 | label | Content | sn.modal.dns_content_label |
| 1179 | placeholder | IP address or value | sn.modal.dns_content_placeholder |
| 1180 | label | TTL (seconds) | sn.modal.dns_ttl_label |
| 1184 | button | Cancel | sn.action.cancel |
| 1185 | button | Save Record | sn.modal.save_record_btn |
| 1186 | button | Delete | sn.action.delete |
| 1214 | bm-header-title | PROXY HOST | sn.modal.proxy_host_title |
| 1223 | label | Domain | sn.modal.proxy_domain_label |
| 1224 | placeholder | subdomain.kytranempowerment.com | sn.modal.proxy_domain_placeholder |
| 1225 | label | Forward Host | sn.modal.proxy_forward_host |
| 1226 | placeholder | 192.168.1.200 | sn.modal.proxy_forward_placeholder |
| 1227 | label | Forward Port | sn.modal.proxy_forward_port |
| 1229 | label | SSL Status | sn.modal.proxy_ssl_label |
| 1233 | button | Cancel | sn.action.cancel |
| 1234 | button | Save Changes | sn.action.save_changes |
| 1235 | button | Delete | sn.action.delete |
| 1263 | bm-header-title | REGISTER DEVICE | sn.modal.register_device_title |
| 1272 | label | Friendly Name | sn.modal.device_name_label |
| 1273 | placeholder | e.g. Ky's iPhone | sn.modal.device_name_placeholder |
| 1274 | label | Device Type | sn.modal.device_type_label |
| 1276-1285 | option | Phone/Laptop/Desktop/... | sn.modal.device_type_* |
| 1287 | label | Owner | sn.modal.device_owner_label |
| 1288 | placeholder | e.g. Ky | sn.modal.device_owner_placeholder |
| 1289 | label | Security Zone | sn.modal.device_zone_label |
| 1291-1295 | option | Trusted/Family/Guest/IoT/Quarantined | sn.modal.device_zone_* |
| 1298 | label | Status | sn.modal.device_status_label |
| 1300-1303 | option | Active/Inactive/Decommissioned/Banned | sn.modal.device_status_* |
| 1306 | label | MAC Address | sn.modal.device_mac_label |
| 1308 | label | IP Address | sn.modal.device_ip_label |
| 1310 | label | Manufacturer | sn.modal.device_manufacturer_label |
| 1312 | label | Notes | sn.modal.device_notes_label |
| 1313 | placeholder | Optional notes about this device | sn.modal.device_notes_placeholder |
| 1316 | button | Cancel | sn.action.cancel |
| 1317 | button | Save Device | sn.modal.save_device_btn |
| 1318 | button | DNS Report | sn.modal.dns_report_btn |
| 1319 | button | Delete | sn.action.delete |
| 1347 | bm-header-title | DNS REPORT | sn.modal.dns_report_title |
| 1356 | inline-text | Loading report... | sn.modal.loading_report |
| 1359 | button | Close | sn.action.close |

---

## JavaScript Strings Needing `t()` Wrapping

### Dashboard JS

| Line | Type | Current Text | Suggested Key |
|------|------|-------------|---------------|
| 1637 | js-content | DNS Protection ON | sn.js.dns_protection_on |
| 1640 | js-content | DNS Protection OFF | sn.js.dns_protection_off |
| 1675 | js-content | Blocking... | sn.js.blocking |
| 1682 | js-content | Block Domain | sn.js.block_domain |
| 1706 | js-content | Block Domain | sn.js.block_domain |
| 1709 | js-content | Error: | sn.js.error_prefix |

### AdGuard DNS JS

| Line | Type | Current Text | Suggested Key |
|------|------|-------------|---------------|
| 1983 | js-content | Delete | sn.js.delete |
| 2004 | js-confirm | Delete rewrite | sn.js.confirm_delete_rewrite |
| 2030 | js-content | Delete | sn.js.delete |
| 2051 | js-confirm | Delete this DNS record? | sn.js.confirm_delete_dns |

### Surveillance JS

| Line | Type | Current Text | Suggested Key |
|------|------|-------------|---------------|
| 2215 | js-content | Entity: | sn.js.entity_prefix |
| 2228 | js-content | Live Stream | sn.js.live_stream |
| 2239 | js-content | Live Stream | sn.js.live_stream |
| 2243 | js-content | Connecting... | sn.js.connecting |
| 2246 | js-content | Stream Failed -- Retry | sn.js.stream_failed_retry |
| 2250 | js-content | Stop Stream | sn.js.stop_stream |
| 2268 | js-content | ARMED | sn.js.armed |
| 2271 | js-content | DISARMED | sn.js.disarmed |
| 2278 | js-content | Arming... | sn.js.arming |
| 2294 | js-content | Disarming... | sn.js.disarming |

### Reconnaissance / Scanning JS

| Line | Type | Current Text | Suggested Key |
|------|------|-------------|---------------|
| 2369 | js-content | View | sn.js.view |
| 2372 | js-content | Del | sn.js.del |
| 2402 | js-content | Scan # | sn.js.scan_number |
| 2405 | js-content | Close | sn.js.close |
| 2414 | js-content | Target: | sn.js.target_prefix |
| 2426 | js-confirm | Delete scan # | sn.js.confirm_delete_scan |

### SSL Monitoring JS

| Line | Type | Current Text | Suggested Key |
|------|------|-------------|---------------|
| 2622 | js-content | No SSL monitors configured. | sn.js.no_ssl_monitors |
| 2626 | js-content | Auto-add from NPM Proxy Hosts | sn.js.auto_add_npm |
| 2721 | js-content | Delete | sn.js.delete |

### Access Control JS

| Line | Type | Current Text | Suggested Key |
|------|------|-------------|---------------|
| 2875 | js-content | Resolve | sn.js.resolve |

### Reports JS

| Line | Type | Current Text | Suggested Key |
|------|------|-------------|---------------|
| 2931 | js-table-cell | Title / Type / Generated / Actions | sn.js.report_th_* |
| 2960 | js-content | View | sn.js.view |
| 2968 | js-content | Download | sn.js.download |
| 3024 | js-heading | Events by Severity | sn.js.events_by_severity |
| 3030 | js-table-cell | Type / Severity / Status / Description | sn.js.event_th_* |
| 3037 | js-heading | Daily Breakdown | sn.js.daily_breakdown |
| 3041 | js-table-cell | Hostname / Type / Zone / Status | sn.js.device_th_* |

### Domain Manager JS

| Line | Type | Current Text | Suggested Key |
|------|------|-------------|---------------|
| 3260 | js-content | No subdomains found | sn.js.no_subdomains |
| 3287 | js-content | Active | sn.js.ssl_active |
| 3288 | js-content | Cert Only | sn.js.ssl_cert_only |
| 3289 | js-content | None | sn.js.ssl_none |
| 3297 | js-content | Delete Proxy | sn.js.delete_proxy |
| 3337 | js-content | No DNS records | sn.js.no_dns_records |
| 3556 | js-content | Expiring (...) | sn.js.ssl_expiring |
| 3557 | js-content | Renew Soon (...) | sn.js.ssl_renew_soon |
| 3558 | js-content | Valid (...) | sn.js.ssl_valid |
| 3559 | js-content | Unknown | sn.js.ssl_unknown |
| 3580 | js-content | Setting up... | sn.js.setting_up |
| 3599 | js-content | Setup Complete | sn.js.setup_complete |
| 3604 | js-content | Domain: | sn.js.domain_prefix |
| 3610 | js-content | DNS: | sn.js.dns_prefix |
| 3623 | js-content | Setup Failed | sn.js.setup_failed |
| 3634 | js-content | Error: | sn.js.error_prefix |
| 3700 | js-confirm | Delete DNS record | sn.js.confirm_delete_dns |
| 3762 | js-confirm | Delete this proxy host? | sn.js.confirm_delete_proxy |
| 3814 | js-content | AT CAPACITY | sn.js.at_capacity |
| 3818 | js-content | ONLINE | sn.js.online |
| 3909 | js-content | Protected | sn.js.protected |
| 3915 | js-content | Unprotected | sn.js.unprotected |
| 3941 | js-content | (dynamic badge) | sn.js.device_badge_* |
| 3985 | js-content | Unprotected | sn.js.unprotected |
| 4009 | js-content | No registered devices found. | sn.js.no_devices |
| 4021 | js-content | Error loading devices: | sn.js.error_loading_devices |

### Compliance JS

| Line | Type | Current Text | Suggested Key |
|------|------|-------------|---------------|
| 4184 | js-table-cell | Domain / Count | sn.js.dns_stats_th_* |
| 4197 | js-table-cell | Domain / Count | sn.js.dns_blocked_th_* |
| 4210 | js-table-cell | Time / Domain / Type / Status | sn.js.dns_log_th_* |
| 4272 | js-content | Scanning all frameworks... | sn.js.scanning_frameworks |
| 4287 | js-content | Last scan: | sn.js.last_scan_prefix |
| 4297 | js-content | Scan failed: | sn.js.scan_failed |
| 4301 | js-content | Error: | sn.js.error_prefix |

### Hardening JS

| Line | Type | Current Text | Suggested Key |
|------|------|-------------|---------------|
| 4719 | js-content | Error loading hardening data: | sn.js.error_loading_hardening |
| 4733 | js-content | Last scan: | sn.js.last_scan_prefix |
| 4745 | js-alert | Run a scan first | sn.js.run_scan_first |
| 4754 | js-alert | Run a scan first | sn.js.run_scan_first |
| 4760 | js-alert | Run a scan first | sn.js.run_scan_first |

### showToast Messages (throughout JS, ~120 calls)

Toast messages use short strings like "success", "error", "info", "warning" as the type parameter, but many also have hardcoded English message strings as the second argument. These are spread across lines 1637-4760 and should all be wrapped with `t()`.

Representative sample:

| Line | Current Pattern | Suggested Pattern |
|------|----------------|-------------------|
| 1652 | `showToast('success', 'Protection enabled')` | `showToast('success', t('sn.toast.protection_enabled'))` |
| 1653 | `showToast('error', 'Failed to toggle')` | `showToast('error', t('sn.toast.toggle_failed'))` |
| 2006 | `showToast('success', 'Rewrite deleted')` | `showToast('success', t('sn.toast.rewrite_deleted'))` |
| 2309 | `showToast('success', 'Scan started')` | `showToast('success', t('sn.toast.scan_started'))` |

---

## Recommendations

1. **Priority 1 -- Tab labels and section headers** (~30 items): These are the most visible text and simplest to fix with `data-i18n` attributes.

2. **Priority 2 -- Form labels, buttons, and options** (~80 items): Standard form elements in HTML that just need `data-i18n` attributes added.

3. **Priority 3 -- Modal content** (~50 items): All 6 LCARS modals have untranslated labels and buttons.

4. **Priority 4 -- JS-generated content** (~240 items): Requires wrapping string literals with `t()` function. This is the bulk of the work and the most error-prone.

5. **Priority 5 -- Toast messages** (~120 calls): Many `showToast()` calls have hardcoded English messages.

### Estimated Effort

- HTML `data-i18n` additions: ~2 hours (mechanical, low risk)
- JS `t()` wrapping: ~4-6 hours (needs careful testing per tab)
- Translation file entries: ~1 hour to generate key-value JSON for 8 languages
- **Total**: ~8-10 hours

### Key Pattern Notes

- Reuse `sn.action.*` keys for common buttons (Cancel, Close, Delete, Refresh, Save Changes)
- Device type and zone options appear in both HTML selects and JS -- use same keys
- Toast messages could use a centralized `sn.toast.*` namespace
- Table headers in JS template literals are the trickiest -- consider extracting to `data-*` attributes on container elements
