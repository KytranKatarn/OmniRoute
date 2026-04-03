---
globs: ["platform_v2/tools/compliance/**", "platform_v2/services/compliance_*", "rule_packs/**", "Dockerfile*", "docker-compose*.yml"]
---

# Compliance Standards (Established 2026-03-25)

Platform-wide security, code quality, compliance scanning, and public posture rules.
These apply to ALL work — platform modules, standalone products, and infrastructure.

## Security Hardening

- All Docker containers: `read_only: true`, no `--privileged`, explicit capability drops
- Resource limits required on every container (CPU + memory in `docker-compose.yml`)
- No secrets in env vars or code — use Docker secrets or `.env` files (never committed)
- DB passwords: `os.getenv("DB_PASSWORD", "")` only, never hardcoded
- TLS required for all external-facing services (NPM proxy + SSL cert)
- UFW firewall: default deny inbound, explicit allow rules only
- SSH: key-only auth, no root login, fail2ban active
- Container images: pinned version tags (no `:latest` in production), trusted base images only
- Tmpfs mounts for writable temp directories inside read-only containers
- Secrets scanning: check for credentials before every commit

## Code Quality

- Route splitting per ADR-045: `register_*_routes(bp, admin_required)` pattern
- No single route file over 600 lines — split by domain
- Service extraction: routes are thin HTTP handlers, business logic in `services/`
- All DB connections: `try/finally: conn.close()` or context manager — no leaks
- Specific exceptions only — no bare `except:`, minimum `except Exception`
- No direct Ollama inference from modules — Bridge dispatcher only (ADR-013)
- Black formatting enforced via pre-commit hook
- No hardcoded IPs or ports — use config/env vars
- Import shared modules (`from db import get_db`) — no local redefinitions

## Compliance Scanning

- Any customer-facing or infrastructure service MUST have a compliance scan profile
- Rule packs: JSON-driven, stored in `rule_packs/` directory — add rules without code changes
- Rule format: `rule_id`, `severity` (low/medium/high), `check_type`, `fix`, `soc2_mapping`
- Scans auto-run every 6 hours via agent loop
- Findings tracked in `compliance_scan_results` with severity + remediation path
- One-click remediation via host command client for automatable fixes
- 5 active rule packs: Ubuntu STIG (51), Docker STIG (30), HIPAA (30), Network STIG (27), CIS Ubuntu (40)

## Public Compliance Posture

- Live SVG badges for all applicable frameworks (STIG, SOC 2, HIPAA, CIS, Network)
- Badge scoring: Green (90%+), Blue (80%+), Yellow (70%+), Red (<60%)
- Grade scale: A+ (95%), A (90%), B+ (85%), B (80%), C (70%), D (60%), F (<60%)
- Trust center page required for any product offered as a service
- SOC 2 evidence collection mapped to 5/5 Trust Service Criteria
- Badge scores auto-refresh from latest scan results
- Competitor comparison page updated when new products ship

## Standalone Products

- All standalone products must follow the extraction playbook in `standalone-extraction.md`
- Standalone products must be registered in Code Health scanner (`STANDALONE_PRODUCTS` in `code_metrics_service.py`)
- Each standalone tracked in Consciousness module with compliance tier status
- See `standalone-extraction.md` for Tier 1/2/3 requirements
