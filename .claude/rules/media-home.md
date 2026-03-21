# Media Home Rules

## Module
- **Media Hub** — `/tools/media-hub`, `media_hub_bp` (25+ routes)

## Structure
- Routes: `tools/media_hub/routes.py`
- Template: `templates/tools/media_hub.html`

## Service Clients
- **Plex** / **Jellyfin** — media server (abstracted for migration support)
- **Sonarr** — TV series management
- **Radarr** — movie management
- **Prowlarr** — indexer management
- **Overseerr** — media requests
- **SABnzbd** — download client
- **TMDB** — metadata/search

## Key DB Tables
- `media_hub_requests` — user media requests
- `media_hub_settings` — service credentials (encrypted)
- `media_library_cache` — cached library data with TTL

## Key Routes
- `/api/search` — smart search (local library first, then TMDB)
- `/api/library/*` — library browser
- `/api/requests` — media request management
- `/api/calendar/upcoming` — upcoming releases
- `/api/downloads` — active downloads
- `/api/settings` — service configuration with auto-discovery

## Patterns
- NO Bridge dispatch — external service integrations via client wrappers
- Encryption layer for stored credentials
- Service abstraction: Plex/Jellyfin migration support
- Cache management with TTL for library data
- Auto-discovery: scans network for Plex/Jellyfin/Sonarr/Radarr instances
