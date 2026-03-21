# Admin Operations Rules

## Modules
- **Backup Manager** — `/tools/backup-manager`, `backup_manager_bp`
- **Security Network** — `/tools/security-network`, `security_network_bp` (30+ routes)
- **Account Center** — `/tools/account-center`, `account_center_bp` (20+ routes)
- **System Operations** — `/tools/system-operations`, `system_operations_bp` (25+ routes)

## Structure
- Each module: `routes.py` + `__init__.py` in `tools/{module_name}/`
- Templates: `templates/tools/{module_name}.html`
- Auth: `@admin_required(f)` decorator + `@rate_limit(max_requests, window_seconds)`

## Key DB Tables
- `audit_log` — all admin actions logged
- `security_events`, `security_scan_results`, `security_recon_scans` — Security Network
- `network_devices`, `security_dns_changes`, `org_domains`, `managed_dns_records` — device/DNS tracking
- `users`, `subscription_tiers`, `user_subscriptions` — Account Center

## Security Patterns
- Account lockout: 5 failed attempts (auth_service.py)
- IP rate limiting per endpoint
- Password complexity validation
- All admin actions → `audit_log` table

## Backup Manager Gotchas
- Uses `get_backup_db_cursor(commit=True)` with lock timeouts (2 hours)
- External USB storage sync support
- Pre/post hooks for automation
- Backup types: DB dump, file system, configuration

## Key Patterns
- No Bridge dispatch — these are infrastructure/config modules
- External service integrations: AdGuard, SSH, cameras, DNS providers
- Security Network has 39 agent loop jobs (monitoring, scanning, alerts)
