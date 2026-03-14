# Game Studio Phase 4: Multiplayer + Persistent World — Design Spec

## Overview

Add real-time multiplayer to Game Studio via Flask-SocketIO WebSocket server with a persistent world state database. Players create profiles, join game sessions via room codes, and play together. A shared economy (resources) and event system connect the three game types. Guest play supported without registration.

**Goal:** Transform single-player games into multiplayer experiences with lobby system, real-time state sync, player profiles with progression, and a persistent world state that bridges the three game types (shooter/explorer/builder).

## Scope

Six capabilities:
1. **Game server** — Flask-SocketIO WebSocket handling for real-time player state sync
2. **Session/lobby system** — create/join rooms, player list, host controls, room codes
3. **Player profiles** — display name, avatar, stats, inventory, XP/level, guest support
4. **World state** — shared resource pool across all game sessions + cross-game event system
5. **Client network layer** — WebSocket client in game iframe, action sending, state receiving
6. **Multiplayer UI** — lobby tab, world tab, profile panel, session management

## Database Schema

### New table: game_player_profiles

```sql
CREATE TABLE IF NOT EXISTS game_player_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    guest_session_id VARCHAR(100),
    display_name VARCHAR(50) NOT NULL,
    avatar_config JSONB DEFAULT '{}',
    stats JSONB DEFAULT '{}',
    inventory JSONB DEFAULT '[]',
    credits INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
    xp INTEGER DEFAULT 0,
    last_active_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);
```

### New table: game_world_state

```sql
CREATE TABLE IF NOT EXISTS game_world_state (
    id SERIAL PRIMARY KEY,
    resource_type VARCHAR(50) NOT NULL UNIQUE,
    amount NUMERIC DEFAULT 0,
    last_updated_by INTEGER,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

Seeded: military_credits, trade_goods, supplies, discoveries, population.

### New table: game_world_events

```sql
CREATE TABLE IF NOT EXISTS game_world_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    source_game_type VARCHAR(30),
    source_session_id VARCHAR(100),
    profile_id INTEGER REFERENCES game_player_profiles(id),
    data JSONB DEFAULT '{}',
    consumed_by JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW()
);
```

### New table: game_sessions

```sql
CREATE TABLE IF NOT EXISTS game_sessions (
    id SERIAL PRIMARY KEY,
    room_code VARCHAR(20) NOT NULL UNIQUE,
    game_id INTEGER REFERENCES game_projects(id),
    host_profile_id INTEGER REFERENCES game_player_profiles(id),
    game_type VARCHAR(30) NOT NULL,
    config JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'lobby',
    max_players INTEGER DEFAULT 8,
    current_players INTEGER DEFAULT 0,
    world_effects JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP
);
```

### Indexes

On owner, guest, event type, session status, room code.

## Game Server (Flask-SocketIO)

New file: platform_v2/tools/game_studio/game_server.py (~200 lines)

SocketIO namespace: /game. Threading async mode.

### Client to server events

- join_session(room_code, profile_id) — validate, join_room, broadcast player_joined
- leave_session(room_code, profile_id) — leave_room, broadcast player_left
- player_action(room_code, action_type, data) — validate action, apply to server state, broadcast state_update
- start_game(room_code) — host only, change status, broadcast game_started

### Server to client events

- state_update — 10Hz broadcast of player positions + entity changes (delta)
- player_joined / player_left — lobby updates
- game_started / game_ended — lifecycle
- world_event — cross-game event notification

### Server-side state

Each room has a server-side state dict. Server tick loop (10Hz) processes queued actions, validates moves, broadcasts deltas. Semi-authoritative: validates and relays, heavy game logic still client-side.

### Session lifecycle

Host creates via REST, players join via WebSocket, host starts, play loop runs, game ends, world_effects applied to world state.

## World State Service

New file: platform_v2/tools/game_studio/world_state_service.py (~120 lines)

- get_world_resources() — all resources as dict
- update_resource(type, delta, profile_id) — atomic update, floor at 0
- apply_session_effects(session_id) — apply accumulated effects + create world events
- create_world_event(type, source_game_type, profile_id, data)
- get_pending_events(game_type, limit) — events not yet consumed by this game type
- mark_event_consumed(event_id, game_type)
- create_profile(user_id, guest_session_id, display_name)
- get_profile(profile_id) / get_profile_by_user(user_id)
- update_stats(profile_id, stat_deltas)
- convert_guest(guest_session_id, user_id)

## Client Network Layer

New file: platform_v2/static/js/game-network.js (~150 lines)

GameNetwork class loaded in iframe. Handles SocketIO connection, action sending (throttled 20/s), state receiving, other player rendering. Single-player: network is null, everything works as before.

Communication via postMessage from main page: connectMultiplayer/disconnectMultiplayer commands.

## API Routes (8 endpoints)

- POST /api/profile — create profile
- GET /api/profile — get current user profile
- PUT /api/profile — update name/avatar
- POST /api/sessions — create session (returns room_code)
- GET /api/sessions — list open sessions
- GET /api/sessions/<room_code> — session details
- POST /api/sessions/<room_code>/end — end session (host)
- GET /api/world — world resources + recent events

## Frontend

### Lobby tab
Create/join sessions, browse open rooms, session player list, host start/kick controls.

### World tab
Global resource counters, recent events feed, auto-refresh 10s.

### Profile panel (right sidebar)
Display name, avatar color, stats summary, level/XP bar, credits.

### CSS additions (~30 lines)
Lobby player cards, profile panel, world resource bars, event feed items, room code display.

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| Create | database/migrations/162_game_multiplayer.sql | 4 tables + seed + indexes |
| Create | platform_v2/tools/game_studio/game_server.py | SocketIO game server (~200 lines) |
| Create | platform_v2/tools/game_studio/world_state_service.py | World state + profiles (~120 lines) |
| Create | platform_v2/static/js/game-network.js | Client WebSocket layer (~150 lines) |
| Modify | platform_v2/static/js/game-engine.js | Network integration (~30 lines) |
| Modify | platform_v2/static/js/game-studio.js | Lobby, profile, world UI (~220 lines) |
| Modify | platform_v2/templates/tools/game_studio.html | Lobby/World tabs, session modals, profile |
| Modify | platform_v2/static/css/game-studio.css | Multiplayer styles (~30 lines) |
| Modify | platform_v2/tools/game_studio/routes.py | 8 REST endpoints |
| Modify | platform_v2/requirements.txt | flask-socketio + deps |
| Modify | platform_v2/app.py | SocketIO init (~5 lines) |

Total: ~690 lines new, ~285 lines modified

## Dependencies

flask-socketio>=5.3, python-socketio>=5.10, python-engineio>=4.8
socket.io client JS v4 (CDN or static file)

## Scope constraints

- Semi-authoritative server (validate + relay)
- Max 8 players per session
- No voice/video chat
- No anti-cheat beyond server validation
- World events stored but cross-game effects deferred to Phase 5
- Threading async mode (not eventlet/gevent)
- No matchmaking (manual room codes)
- Guest profiles ephemeral until converted
