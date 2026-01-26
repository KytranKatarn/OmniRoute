# LLM Connections Monitor (Phase 27)

**Status:** COMPLETE (2026-01-16)

## Overview

The LLM Connections Monitor provides real-time health monitoring for all AI model connections in the A.R.C.H.I.E. platform. It tracks the status, latency, and availability of both local (Ollama) and remote API (Claude, OpenAI, Grok, Gemini) models.

## Architecture

### Database Schema

**Table: `llm_connections`** (Migration 022)
```sql
- id, provider, model_name, display_name
- endpoint_url, api_key_configured
- status: online | offline | degraded | unknown
- last_check, last_success, last_failure
- avg_latency_ms, p95_latency_ms, success_rate
- total_requests, failed_requests, consecutive_failures
- health_check_enabled, health_check_interval_seconds
- cost_per_1k_input, cost_per_1k_output
- capabilities (JSONB)
```

**Table: `llm_connection_history`**
- Stores historical check data for trend analysis
- Used for latency graphs and availability charts

**Table: `llm_alerts`**
- Tracks connection failures and recoveries
- Alert types: offline, degraded, high_latency, error_rate, recovered
- Severity levels: info, warning, critical
- Acknowledgement tracking

**Views:**
- `llm_status_summary` - Provider-level aggregations
- `recent_llm_alerts` - Last 24 hours of alerts

### Backend Service

**File:** `/mnt/archie_brain/platform_v2/llm_monitor.py`

The `LLMMonitor` class runs as a background thread performing health checks every 30 seconds.

Provider-specific check methods:
- `_check_ollama()` - Tests local Ollama API at `/api/tags`
- `_check_claude()` - Tests Anthropic API via `/v1/models`
- `_check_openai()` - Tests OpenAI API via `/v1/models`
- `_check_grok()` - Tests xAI API via `/v1/models`
- `_check_gemini()` - Tests Google API via model listing

### API Endpoints

**Location:** `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/llm/status` | GET | Get all connection statuses |
| `/api/llm/check` | POST | Trigger immediate health check |
| `/api/llm/alerts` | GET | Get recent alerts |
| `/api/llm/alerts/<id>/acknowledge` | POST | Dismiss an alert |
| `/api/llm/history/<connection_id>` | GET | Get historical data for charts |

### UI Components

**Location:** `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`

The LLM Connections Monitor panel includes:

1. **Provider Summary Tab**
   - Cards showing each provider (Ollama, Claude, OpenAI, Grok, Gemini)
   - Model count, average latency, online/offline status
   - Visual status indicators (green/yellow/red)

2. **Models Tab**
   - Individual model status cards
   - Display name, provider/model identifier
   - Last check time, success rate
   - Latency with color coding (green < 500ms, yellow >= 500ms)
   - Cost badge (FREE for Ollama, PAID for APIs)

3. **Alerts Tab**
   - Active alerts with severity indicators
   - Alert type, message, and timestamp
   - Dismiss button for acknowledgement
   - Badge count on tab

## Seed Data

The migration includes seed data for 10 LLM models:

**Ollama (Local - FREE)**
- deepseek-coder-v2:16b
- qwen2.5-coder:7b
- llama3.2:latest
- mistral:latest

**Claude API (PAID)**
- claude-sonnet-4-20250514
- claude-opus-4-20250514

**OpenAI API (PAID)**
- gpt-4o
- gpt-4o-mini

**Grok API (PAID)**
- grok-beta

**Gemini API (PAID)**
- gemini-pro

## Status Indicators

| Status | Color | Description |
|--------|-------|-------------|
| online | Green (#00ff41) | Connection successful, model responding |
| degraded | Yellow (#FFAA00) | Elevated latency or intermittent failures |
| offline | Red (#ff4444) | Connection failed or model unavailable |
| unknown | Gray (#8b949e) | API key not configured or never checked |

## Alert Types

| Type | Severity | Trigger |
|------|----------|---------|
| offline | critical | 3+ consecutive failures |
| degraded | warning | High latency or intermittent issues |
| high_latency | warning | P95 latency exceeds threshold |
| error_rate | warning | Success rate below threshold |
| recovered | info | Connection restored after offline |

## Configuration

Health check settings are per-connection:
- `health_check_enabled` - Toggle monitoring on/off
- `health_check_interval_seconds` - Check frequency (default: 30)
- `failure_threshold` - Failures before marking offline (default: 3)

## Usage

### Viewing Status
Navigate to Bridge Command (`/tools/bridge`) and scroll to the "LLM CONNECTIONS MONITOR" panel.

### Manual Health Check
Click "Run Health Check" to trigger an immediate check of all connections.

### Managing Alerts
1. Switch to the "Alerts" tab
2. Review active alerts
3. Click "Dismiss" to acknowledge

### Adding New Models
Insert into `llm_connections` table:
```sql
INSERT INTO llm_connections (provider, model_name, display_name, endpoint_url, capabilities)
VALUES ('ollama', 'new-model:tag', 'New Model', 'http://localhost:11434', '{"coding": true}');
```

## Files Modified/Created

| File | Action |
|------|--------|
| `database/migrations/022_llm_connections.sql` | NEW |
| `platform_v2/llm_monitor.py` | NEW |
| `platform_v2/tools/bridge/routes.py` | MODIFIED (added LLM APIs) |
| `platform_v2/templates/tools/bridge.html` | MODIFIED (added monitor panel) |
| `platform_v2/module_registry.py` | MODIFIED (Bridge icon to 🎛️) |
| `platform_v2/templates/dashboard.html` | MODIFIED (added Admin Ops with red styling) |
| `platform_v2/templates/dashboard_dynamic.html` | MODIFIED (added admin_ops CSS) |
| `platform_v2/dashboard_generator.py` | MODIFIED (admin_ops category) |

## Additional UI Updates (2026-01-16)

- **Bridge Icon**: Changed from 🌉 (bridge) to 🎛️ (control panel) across all templates
- **Dashboard Styling**: Admin Operations modules (Bridge, Team Management, Consciousness) display with red (#FF6B6B) borders and text
- **Naming**: Standardized to "Consciousness" (not "Mind") across all templates

## Related Documentation

- [MASTER_STATUS_AND_ROADMAP_2026.md](./MASTER_STATUS_AND_ROADMAP_2026.md) - Phase 27 entry
- [BRIDGE_STATION_ARCHITECTURE.md](./BRIDGE_STATION_ARCHITECTURE.md) - Bridge overview
- [DATABASE_SCHEMA_DOCUMENTATION.md](./DATABASE_SCHEMA_DOCUMENTATION.md) - Full schema reference
