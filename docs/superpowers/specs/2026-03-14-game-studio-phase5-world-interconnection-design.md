# Game Studio Phase 5: Cross-Game World Interconnection — Design Spec

## Overview

Connect the three game types (shooter, explorer, builder) into a living interconnected world. Events in one game create real effects in the others — passive bonuses apply in real-time, active world changes modify configs between sessions. A dynamic supply/demand market economy drives resource exchange. A shared world map visualization shows all game activity overlaid.

**Goal:** Make the three game types feel like one living world. Shooter victories reduce pirate threats for explorers. Explorer discoveries unlock new locations for builders. Builder colonies provide health depots for shooters. A dynamic market economy ties it all together with fluctuating resource prices.

## Scope

Four capabilities:
1. **World engine** — event processor that converts cross-game events into bonuses, resource changes, and world config patches
2. **Dynamic market** — supply/demand pricing, resource trading between game types
3. **Module integration** — game modules apply world effects at session start (bonuses + world changes)
4. **World map + feed** — canvas visualization of all game activity + real-time event ticker + market panel

## Event Effect Mapping

| Event | Source | Shooter Effect | Explorer Effect | Builder Effect |
|-------|--------|---------------|-----------------|----------------|
| battle_won | Shooter | — | pirate_threat -10% | +50 supplies |
| planet_discovered | Explorer | new arena map | — | new build location |
| colony_built | Builder | health depot +25 | new trade station | — |
| raid_survived | Builder | enemy wave -2 | safe zone +50 | — |
| trade_completed | Explorer | damage boost +15% | — | +20 metal |

Effect types:
- **bonus**: stat modifier applied to config (real-time, expires 24h)
- **resource**: world resource delta via world_state_service
- **world_change**: config patch adding new entities (applied on session start)

## Database Schema

### New table: game_world_bonuses

```sql
CREATE TABLE IF NOT EXISTS game_world_bonuses (
    id SERIAL PRIMARY KEY,
    game_type VARCHAR(30) NOT NULL,
    bonus_key VARCHAR(50) NOT NULL,
    bonus_value NUMERIC NOT NULL,
    source_event_id INTEGER REFERENCES game_world_events(id),
    consumed BOOLEAN DEFAULT FALSE,
    expires_at TIMESTAMP DEFAULT NOW() + INTERVAL '24 hours',
    created_at TIMESTAMP DEFAULT NOW()
);
```

### New table: game_world_changes

```sql
CREATE TABLE IF NOT EXISTS game_world_changes (
    id SERIAL PRIMARY KEY,
    game_type VARCHAR(30) NOT NULL,
    change_key VARCHAR(50) NOT NULL,
    config_patch JSONB NOT NULL,
    source_event_id INTEGER REFERENCES game_world_events(id),
    applied BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### New table: game_market_prices

```sql
CREATE TABLE IF NOT EXISTS game_market_prices (
    id SERIAL PRIMARY KEY,
    resource_type VARCHAR(50) NOT NULL UNIQUE,
    base_price NUMERIC DEFAULT 1.0,
    current_price NUMERIC DEFAULT 1.0,
    supply_1h NUMERIC DEFAULT 0,
    demand_1h NUMERIC DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

Seeded with base prices: military_credits=1.0, trade_goods=1.5, supplies=1.2, discoveries=3.0, population=0.5.

## World Engine

New file: platform_v2/tools/game_studio/world_engine.py (~180 lines)

### process_pending_events()

Called by APScheduler every 30 seconds. Loads unconsumed events, looks up effect mapping, creates bonuses/resource changes/world changes, marks events consumed, broadcasts via SocketIO.

### get_active_bonuses(game_type)

Returns unexpired, unconsumed bonuses for a game type.

### get_pending_world_changes(game_type)

Returns unapplied config patches for a game type.

### apply_world_to_config(game_type, config)

Merges active bonuses and pending world changes into a game config. Bonuses modify stats, world changes add entities.

### World change generators

- generate_arena_from_planet(event_data) — creates wall layout + enemy set for shooter
- generate_build_site(event_data) — adds buildable terrain patch for builder
- generate_trade_station(event_data) — adds station to star system for explorer

## Market Service

New file: platform_v2/tools/game_studio/market_service.py (~100 lines)

Price formula: current_price = base_price * (demand_1h / max(supply_1h, 1)), clamped 0.1x-10x.

### Functions

- get_market_prices() — all prices with supply/demand
- update_market_prices() — recalculate from recent activity (APScheduler every 5 min)
- trade(from_resource, to_resource, amount, profile_id) — exchange at market rate, record event
- get_trade_history(limit) — recent trades

## Module Integration

Game engine fetches world effects before module init:

GET /api/world/effects?game_type=X returns {bonuses, changes}.

Engine applies bonuses (stat modifiers) and world changes (config patches) to the config before starting the game module.

Shooter bonuses: health_depot, damage_boost, enemy_wave_reduction.
Explorer bonuses: pirate_threat_reduction, safe_zone_expansion.
Builder bonuses: resource deliveries (metal, food, supplies).

World changes applied as deep merges into config: new arenas, new stations, new build sites.

## World Map Visualization

Canvas in World tab showing shared galaxy with activity overlays:
- Red pulse rings: recent shooter battles
- Blue dotted lines: explorer travel routes
- Green squares: builder colonies
- Yellow dashes: active trade routes
- Animated icons: event markers (explosion, sparkle, hammer)

Data from GET /api/world/map. Auto-refreshes every 10 seconds.

## Event Feed

Real-time ticker below world map showing processed events with their cross-game effects. Format: [time] icon event_type arrow affected_games: effect descriptions.

Also receives SocketIO world_event_processed broadcasts.

## Market Panel

Below event feed in World tab:
- Price table: resource, current price, trend arrow, supply/demand bars
- Trade form: from/to resource, amount, rate preview, execute
- Trade history: last 10 trades

## API Routes (3 new)

- GET /api/world/effects?game_type=X — bonuses + world changes for a game type
- GET /api/world/map — aggregated activity data for visualization
- POST /api/world/trade — execute resource trade at market rate

## APScheduler Jobs

Job #24: game_world_event_processor — every 30s, calls process_pending_events()
Job #25: game_market_price_update — every 5min, calls update_market_prices()

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| Create | database/migrations/163_game_world_interconnection.sql | 3 tables + seed + indexes |
| Create | platform_v2/tools/game_studio/world_engine.py | Event processor (~180 lines) |
| Create | platform_v2/tools/game_studio/market_service.py | Dynamic economy (~100 lines) |
| Modify | platform_v2/static/js/game-engine.js | Fetch effects before init (~20 lines) |
| Modify | platform_v2/static/js/game-studio.js | World map + feed + market UI (~200 lines) |
| Modify | platform_v2/templates/tools/game_studio.html | World map canvas, market panel |
| Modify | platform_v2/static/css/game-studio.css | World map + market styles (~25 lines) |
| Modify | platform_v2/tools/game_studio/routes.py | 3 routes |
| Modify | ai_bridge/agent_loop.py | 2 APScheduler jobs (#24, #25) |

Total: ~480 lines new, ~245 lines modified

## Scope constraints

- Bonuses expire after 24 hours
- Market prices clamped 0.1x-10x
- World changes applied on session start only
- No PvP between game types
- No leaderboard
- World map uses explorer star positions
