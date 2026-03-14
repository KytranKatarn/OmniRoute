# Game Studio Phase 5: Cross-Game World Interconnection — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect shooter/explorer/builder into one living world — cross-game event effects, dynamic market economy, world map visualization, and module-level integration that modifies gameplay based on other players' actions.

**Architecture:** `world_engine.py` processes events every 30s via APScheduler, mapping them to bonuses/resources/world changes per game type. `market_service.py` manages supply/demand pricing updated every 5 min. Game engine fetches effects before module init. Frontend adds world map canvas + event feed + market trading panel.

**Tech Stack:** Flask, PostgreSQL, Canvas 2D, APScheduler, vanilla JS

**Key patterns:**
- DB: `from database import get_db_cursor` with `with get_db_cursor(commit=True) as (conn, cur):`
- World state: `game_world_state`, `game_world_events` tables (from Phase 4)
- Agent loop: `with_app_context`, `IntervalTrigger`, `replace_existing=True`
- Game engine: postMessage API, modules register via `GameEngine.registerModuleType()`
- No innerHTML — createElement/textContent only

---

## Task 1: Migration 163

**Files:**
- Create: `database/migrations/163_game_world_interconnection.sql`

- [ ] **Step 1: Write migration**

```sql
-- Migration 163: World interconnection — bonuses, changes, market
-- Idempotent: safe to run multiple times

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

CREATE TABLE IF NOT EXISTS game_world_changes (
    id SERIAL PRIMARY KEY,
    game_type VARCHAR(30) NOT NULL,
    change_key VARCHAR(50) NOT NULL,
    config_patch JSONB NOT NULL,
    source_event_id INTEGER REFERENCES game_world_events(id),
    applied BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS game_market_prices (
    id SERIAL PRIMARY KEY,
    resource_type VARCHAR(50) NOT NULL UNIQUE,
    base_price NUMERIC DEFAULT 1.0,
    current_price NUMERIC DEFAULT 1.0,
    supply_1h NUMERIC DEFAULT 0,
    demand_1h NUMERIC DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO game_market_prices (resource_type, base_price, current_price) VALUES
    ('military_credits', 1.0, 1.0),
    ('trade_goods', 1.5, 1.5),
    ('supplies', 1.2, 1.2),
    ('discoveries', 3.0, 3.0),
    ('population', 0.5, 0.5)
ON CONFLICT (resource_type) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_game_bonuses_type ON game_world_bonuses(game_type, consumed, expires_at);
CREATE INDEX IF NOT EXISTS idx_game_changes_type ON game_world_changes(game_type, applied);
```

- [ ] **Step 2: Run + verify + commit**

```bash
docker cp database/migrations/163_game_world_interconnection.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/163_game_world_interconnection.sql
git add database/migrations/163_game_world_interconnection.sql
git commit -m "feat(game-studio): add migration 163 — world bonuses, changes, market prices"
```

---

## Task 2: World Engine

**Files:**
- Create: `platform_v2/tools/game_studio/world_engine.py`

- [ ] **Step 1: Write world engine (~180 lines)**

DB: `from database import get_db_cursor`, `psycopg2.extras.Json`

**EFFECT_MAP** constant: dict mapping event_type → {game_type: {type, key, value/delta/generator}}. Cover all 5 event types x 2 target game types each (10 effects total).

**process_pending_events():**
1. Query unconsumed events: `SELECT * FROM game_world_events WHERE consumed_by IS NULL OR NOT (consumed_by @> %s)` for each game type
2. For each event + each affected game_type from EFFECT_MAP:
   - bonus → INSERT game_world_bonuses
   - resource → call world_state_service.update_resource
   - world_change → call generator, INSERT game_world_changes with config_patch
3. Mark consumed via world_state_service.mark_event_consumed
4. Return count processed

**get_active_bonuses(game_type):**
SELECT FROM game_world_bonuses WHERE game_type=%s AND NOT consumed AND expires_at > NOW(). Return list of {key, value}.

**get_pending_world_changes(game_type):**
SELECT FROM game_world_changes WHERE game_type=%s AND NOT applied. Return list of {key, config_patch}.

**mark_changes_applied(game_type):**
UPDATE game_world_changes SET applied=true WHERE game_type=%s AND NOT applied.

**apply_world_to_config(game_type, config):**
1. bonuses = get_active_bonuses(game_type)
2. changes = get_pending_world_changes(game_type)
3. Apply bonuses by key:
   - shooter: health_depot→player.health+=, damage_boost→bullets.damage*=, enemy_wave_reduction→reduce enemy count
   - explorer: pirate_threat_reduction→encounters.pirateChance*=, safe_zone_expansion→player.fuel+=
   - builder: resource bonuses→resources[key]+=
4. Apply world changes: deep merge each config_patch into config
5. mark_changes_applied(game_type)
6. Return modified config

**World change generators:**
- generate_arena_from_planet(data): return config patch with walls array + extra enemies
- generate_build_site(data): return config patch with resource nodes at new positions
- generate_trade_station(data): return config patch adding a station to nearest star

- [ ] **Step 2: Verify + commit**

```bash
docker exec archie_platform python3 -c "from tools.game_studio.world_engine import process_pending_events, get_active_bonuses, apply_world_to_config; print('OK')"
git add platform_v2/tools/game_studio/world_engine.py
git commit -m "feat(game-studio): add world engine — event processor + effect mapping"
```

---

## Task 3: Market Service

**Files:**
- Create: `platform_v2/tools/game_studio/market_service.py`

- [ ] **Step 1: Write market service (~100 lines)**

**get_market_prices():** SELECT all from game_market_prices, return dict.

**update_market_prices():**
1. For each resource: count world_events with positive/negative resource deltas in last hour
2. new_price = base * (demand / max(supply, 1)), clamp 0.1x–10x
3. UPDATE game_market_prices

**trade(from_resource, to_resource, amount, profile_id):**
1. Load prices for both resources
2. cost = amount * price[from] / price[to]
3. Check world resources sufficient (or profile credits)
4. update_resource(from, -amount), update_resource(to, +cost)
5. create_world_event('trade_completed', source_game_type='market', profile_id, {from, to, amount, rate})
6. Return {success, exchanged, rate}

**get_trade_history(limit=20):** Query recent trade_completed events.

- [ ] **Step 2: Verify + commit**

```bash
docker exec archie_platform python3 -c "from tools.game_studio.market_service import get_market_prices, trade; print('OK')"
git add platform_v2/tools/game_studio/market_service.py
git commit -m "feat(game-studio): add market service — dynamic pricing + trading"
```

---

## Task 4: APScheduler Jobs + Routes

**Files:**
- Modify: `ai_bridge/agent_loop.py`
- Modify: `platform_v2/tools/game_studio/routes.py`

- [ ] **Step 1: Add 2 APScheduler jobs to agent_loop.py**

Job #24: world event processor (30s interval)
Job #25: market price updater (5min interval)

Methods:
```python
def _process_world_events(self):
    from tools.game_studio.world_engine import process_pending_events
    try:
        count = process_pending_events()
        if count > 0:
            logger.info(f"[World Engine] Processed {count} events")
    except Exception as e:
        logger.error(f"[World Engine] Error: {e}")

def _update_market_prices(self):
    from tools.game_studio.market_service import update_market_prices
    try:
        update_market_prices()
    except Exception as e:
        logger.error(f"[Market] Price update error: {e}")
```

Update job count 23→25, add both IDs to stop() list.

- [ ] **Step 2: Add 3 routes to routes.py**

**GET /api/world/effects** — returns bonuses + changes for a game_type
```python
@game_studio_bp.route("/api/world/effects", methods=["GET"])
@login_required
def get_world_effects():
    from world_engine import get_active_bonuses, get_pending_world_changes
    game_type = request.args.get("game_type", "top_down_shooter")
    bonuses = get_active_bonuses(game_type)
    changes = get_pending_world_changes(game_type)
    return jsonify({"bonuses": bonuses, "changes": changes})
```

**GET /api/world/map** — aggregated activity for visualization
```python
@game_studio_bp.route("/api/world/map", methods=["GET"])
@login_required
def get_world_map():
    from database import get_db_cursor
    with get_db_cursor() as (conn, cur):
        # Recent shooter events (battles)
        cur.execute("SELECT data, created_at FROM game_world_events WHERE event_type='battle_won' AND created_at > NOW() - INTERVAL '1 hour' ORDER BY created_at DESC LIMIT 20")
        shooter = [{"data": r["data"], "age_s": ...} for r in cur.fetchall()]
        # Recent explorer events
        cur.execute("SELECT data, created_at FROM game_world_events WHERE event_type='planet_discovered' AND created_at > NOW() - INTERVAL '1 hour' ORDER BY created_at DESC LIMIT 20")
        explorer = [...]
        # Builder colonies
        cur.execute("SELECT data, created_at FROM game_world_events WHERE event_type='colony_built' ORDER BY created_at DESC LIMIT 20")
        builder = [...]
        # Recent events (all types, last 20)
        cur.execute("SELECT event_type, source_game_type, data, created_at FROM game_world_events ORDER BY created_at DESC LIMIT 20")
        events = [...]
    return jsonify({"shooter_activity": shooter, "explorer_routes": explorer, "builder_colonies": builder, "recent_events": events})
```

**POST /api/world/trade** — execute trade
```python
@game_studio_bp.route("/api/world/trade", methods=["POST"])
@login_required
def execute_trade():
    from market_service import trade
    from world_state_service import get_profile_by_user
    data = request.get_json() or {}
    profile = get_profile_by_user(current_user.id)
    if not profile:
        return jsonify({"error": "No profile"}), 400
    result = trade(data.get("from"), data.get("to"), float(data.get("amount", 0)), profile["id"])
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)
```

- [ ] **Step 3: Commit**

```bash
git add ai_bridge/agent_loop.py platform_v2/tools/game_studio/routes.py
git commit -m "feat(game-studio): add world engine + market APScheduler jobs + 3 routes"
```

---

## Task 5: Engine Integration — Fetch Effects Before Init

**Files:**
- Modify: `platform_v2/static/js/game-engine.js`

- [ ] **Step 1: Update loadConfig handler**

In the postMessage listener where `loadConfig` is handled, add a fetch for world effects BEFORE module init:

```javascript
if (e.data.type === 'loadConfig') {
    var config = e.data.config;
    var canvas = ...; // existing canvas setup

    // Fetch world effects before starting
    fetch('/tools/game-studio/api/world/effects?game_type=' + (config.type || 'top_down_shooter'))
        .then(function(r) { return r.json(); })
        .then(function(effects) {
            // Apply bonuses
            if (effects.bonuses) {
                effects.bonuses.forEach(function(b) {
                    if (config.type === 'top_down_shooter') {
                        if (b.bonus_key === 'health_depot' && config.player) config.player.health += Number(b.bonus_value);
                        if (b.bonus_key === 'damage_boost' && config.bullets) config.bullets.damage *= (1 + Number(b.bonus_value));
                        if (b.bonus_key === 'enemy_wave_reduction' && config.enemies) {
                            config.enemies = config.enemies.slice(0, Math.max(1, config.enemies.length - Number(b.bonus_value)));
                        }
                    } else if (config.type === 'space_explorer') {
                        if (b.bonus_key === 'pirate_threat_reduction' && config.encounters) config.encounters.pirateChance *= (1 - Number(b.bonus_value));
                        if (b.bonus_key === 'safe_zone_expansion' && config.player) config.player.fuel += Number(b.bonus_value);
                    } else if (config.type === 'base_builder') {
                        if (config.resources && config.resources[b.bonus_key] !== undefined) config.resources[b.bonus_key] += Number(b.bonus_value);
                    }
                });
            }
            // Apply world changes (deep merge config patches)
            if (effects.changes) {
                effects.changes.forEach(function(c) {
                    var patch = c.config_patch;
                    if (patch && typeof patch === 'object') {
                        Object.keys(patch).forEach(function(k) {
                            if (Array.isArray(patch[k]) && Array.isArray(config[k])) {
                                config[k] = config[k].concat(patch[k]);
                            } else if (typeof patch[k] === 'object' && typeof config[k] === 'object') {
                                Object.assign(config[k], patch[k]);
                            } else {
                                config[k] = patch[k];
                            }
                        });
                    }
                });
            }
            // Now init engine with world-enhanced config
            _startEngine(canvas, config);
        })
        .catch(function() {
            // Fallback: start without world effects
            _startEngine(canvas, config);
        });
}
```

Extract the existing engine start logic into a `_startEngine(canvas, config)` helper function so it can be called from both the fetch callback and the fallback.

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/js/game-engine.js
git commit -m "feat(game-studio): fetch world effects before module init"
```

---

## Task 6: Frontend — World Map + Feed + Market

**Files:**
- Modify: `platform_v2/static/js/game-studio.js`
- Modify: `platform_v2/templates/tools/game_studio.html`
- Modify: `platform_v2/static/css/game-studio.css`

- [ ] **Step 1: Add world map canvas + market panel to HTML**

Update the existing World tab content (from Phase 4) — add canvas and market:

```html
<!-- Inside gsWorldTab, after existing resources + events sections -->
<div class="gs-prop-group-title" style="margin-top:1rem;">World Map</div>
<canvas id="gsWorldMapCanvas" width="800" height="500" style="width:100%;border:1px solid var(--gs-border,#232);border-radius:4px;background:#000;"></canvas>

<div class="gs-prop-group-title" style="margin-top:1rem;">Market</div>
<div id="gsMarketPrices" class="gs-market-prices"></div>
<div class="gs-market-trade" id="gsMarketTrade">
    <select id="gsTradeFrom" class="gs-prop-input" style="width:auto;"></select>
    <span style="color:var(--gs-text);">→</span>
    <select id="gsTradeTo" class="gs-prop-input" style="width:auto;"></select>
    <input type="number" id="gsTradeAmount" class="gs-prop-input" value="10" min="1" style="width:60px;">
    <span id="gsTradeRate" style="font-size:0.65rem;color:var(--gs-text);">Rate: --</span>
    <button class="gs-toolbar-btn" onclick="executeTrade()">Trade</button>
</div>
```

- [ ] **Step 2: Add world map renderer + market JS (~200 lines)**

In game-studio.js, enhance the existing `loadWorldState()` and add:

**renderWorldMap():**
1. GET /api/world/map
2. Draw on #gsWorldMapCanvas:
   - Background: dark fill + scattered dim stars
   - Use DEFAULT_EXPLORER_CONFIG.stars for star positions (scale to canvas size)
   - Shooter activity: red circles with fading alpha based on age
   - Explorer routes: blue dotted lines between stars
   - Builder colonies: green squares at star positions
   - Event markers: small animated icons at event locations
3. Called from loadWorldState, auto-refreshes with it

**loadMarketPrices():**
1. GET /api/world (already returns resources)
2. Also GET market prices from /api/world/trade endpoint or inline with world data
3. Render price table: resource name, price, trend arrow (compare to base_price)
4. Populate trade dropdowns

**updateTradeRate():**
On dropdown/amount change, calculate preview rate from loaded prices.

**executeTrade():**
POST /api/world/trade with from/to/amount. Toast result. Reload market + world state.

**renderEventFeed(events):**
Enhance existing event rendering with icons and effect descriptions:
- battle_won: sword icon + "Explorer: pirate -10% | Builder: +50 supplies"
- planet_discovered: planet icon + "Shooter: new arena | Builder: new location"
- etc.

- [ ] **Step 3: Add market + world map CSS (~25 lines)**

```css
.gs-market-prices {
    display: flex; flex-direction: column; gap: 0.25rem; margin-bottom: 0.75rem;
}
.gs-market-price-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 0.25rem 0; font-size: 0.7rem; color: var(--gs-text, #aab);
    border-bottom: 1px solid rgba(255,255,255,0.03);
}
.gs-market-price-value { font-family: 'IBM Plex Mono', monospace; }
.gs-market-trend-up { color: #4f6; }
.gs-market-trend-down { color: #f44; }
.gs-market-trade {
    display: flex; gap: 0.5rem; align-items: center;
    padding: 0.5rem; background: rgba(255,255,255,0.02);
    border-radius: 4px; font-size: 0.7rem;
}
#gsWorldMapCanvas { image-rendering: pixelated; }
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/static/js/game-studio.js platform_v2/templates/tools/game_studio.html platform_v2/static/css/game-studio.css
git commit -m "feat(game-studio): add world map visualization + market trading + event feed"
```

---

## Task 7: Integration Test

- [ ] **Step 1: Write + run test**

Test: 3 new DB tables + market seed, world_engine + market_service imports, process_pending_events callable, get_market_prices returns 5 resources, trade function exists, 3 new routes (effects/map/trade), engine has world effects fetch, JS has renderWorldMap + executeTrade + loadMarketPrices, HTML has gsWorldMapCanvas + gsMarketPrices + gsMarketTrade, CSS has .gs-market-prices + .gs-market-trade.

- [ ] **Step 2: Fix failures + re-test**

---

## Task 8: Deploy + Push + Dev HQ

- [ ] **Step 1: Push**

```bash
git push origin main
```

- [ ] **Step 2: Update Dev HQ**

- complete_task #867 (Phase 5)
- store_memory — Game Studio Phase 5 complete, all 5 phases done
- log_decision — event-driven world interconnection, supply/demand market, 24h bonus expiry
