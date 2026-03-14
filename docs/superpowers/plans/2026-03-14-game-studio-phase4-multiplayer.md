# Game Studio Phase 4: Multiplayer + Persistent World — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real-time multiplayer via Flask-SocketIO, persistent world state, player profiles with progression, lobby/session system, and cross-game event foundation.

**Architecture:** `game_server.py` handles SocketIO WebSocket connections (namespace `/game`). `world_state_service.py` manages persistent resources + events + player profiles. `game-network.js` is the client-side WebSocket layer in the game iframe. REST routes handle profile/session/world CRUD. SocketIO initialized on the Flask app with threading async mode.

**Tech Stack:** Flask-SocketIO, python-socketio, HTML5 Canvas, vanilla JS

**Key patterns:**
- DB: `from database import get_db_cursor` with `with get_db_cursor(commit=True) as (conn, cur):`
- SocketIO: `from flask_socketio import SocketIO, emit, join_room, leave_room`
- Game engine in iframe communicates via postMessage
- Routes: `@game_studio_bp.route(...)` + `@login_required`
- Existing files: game-engine.js (~270 lines core), game-studio.js (~1100+ lines), game_studio.html, routes.py
- IMPORTANT: No innerHTML — createElement/textContent only

---

## Task 1: Dependencies + Migration 162

**Files:**
- Create: `database/migrations/162_game_multiplayer.sql`
- Modify: `platform_v2/requirements.txt`

- [ ] **Step 1: Add flask-socketio to requirements.txt**

Append:
```
flask-socketio>=5.3
python-socketio>=5.10
python-engineio>=4.8
```

- [ ] **Step 2: Write migration**

```sql
-- Migration 162: Multiplayer — profiles, world state, events, sessions
-- Idempotent: safe to run multiple times

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

CREATE TABLE IF NOT EXISTS game_world_state (
    id SERIAL PRIMARY KEY,
    resource_type VARCHAR(50) NOT NULL UNIQUE,
    amount NUMERIC DEFAULT 0,
    last_updated_by INTEGER,
    updated_at TIMESTAMP DEFAULT NOW()
);

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

-- Seed world resources
INSERT INTO game_world_state (resource_type, amount) VALUES
    ('military_credits', 1000),
    ('trade_goods', 500),
    ('supplies', 750),
    ('discoveries', 0),
    ('population', 100)
ON CONFLICT (resource_type) DO NOTHING;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_game_profiles_user ON game_player_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_game_profiles_guest ON game_player_profiles(guest_session_id);
CREATE INDEX IF NOT EXISTS idx_game_world_events_type ON game_world_events(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_game_sessions_status ON game_sessions(status);
CREATE INDEX IF NOT EXISTS idx_game_sessions_room ON game_sessions(room_code);
```

- [ ] **Step 3: Run migration**

```bash
docker cp database/migrations/162_game_multiplayer.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/162_game_multiplayer.sql
```

- [ ] **Step 4: Commit**

```bash
git add database/migrations/162_game_multiplayer.sql platform_v2/requirements.txt
git commit -m "feat(game-studio): add migration 162 — multiplayer tables + flask-socketio dep"
```

---

## Task 2: World State Service

**Files:**
- Create: `platform_v2/tools/game_studio/world_state_service.py`

- [ ] **Step 1: Write world state service (~120 lines)**

```python
"""World state service — resources, events, player profiles.

Public API:
- get_world_resources()
- update_resource(type, delta, profile_id)
- apply_session_effects(session_id)
- create_world_event(type, source_game_type, profile_id, data)
- get_pending_events(game_type, limit)
- mark_event_consumed(event_id, game_type)
- create_profile(user_id, guest_session_id, display_name)
- get_profile(profile_id)
- get_profile_by_user(user_id)
- update_stats(profile_id, stat_deltas)
- convert_guest(guest_session_id, user_id)
"""
```

All functions use `from database import get_db_cursor` pattern.

**get_world_resources()**: SELECT all from game_world_state, return {resource_type: float(amount)}.

**update_resource(resource_type, delta, profile_id)**: UPDATE SET amount = GREATEST(0, amount + delta), last_updated_by, updated_at=NOW().

**apply_session_effects(session_id)**: Load game_sessions.world_effects, for each resource delta call update_resource. Also create world events for significant effects.

**create_world_event(event_type, source_game_type, profile_id, data)**: INSERT into game_world_events. Return event_id.

**get_pending_events(game_type, limit=20)**: SELECT WHERE NOT (consumed_by @> '["{game_type}"]') ORDER BY created_at DESC LIMIT. Return list of event dicts with datetime serialization.

**mark_event_consumed(event_id, game_type)**: UPDATE consumed_by = consumed_by || '["game_type"]'.

**create_profile(user_id=None, guest_session_id=None, display_name=None)**: If no display_name, generate random (e.g., "Pilot_" + random 4 digits). INSERT RETURNING id. Return {profile_id, display_name}.

**get_profile(profile_id)**: SELECT, return dict (no guest_session_id exposed). Serialize datetimes.

**get_profile_by_user(user_id)**: SELECT WHERE user_id=%s, return dict or None.

**update_stats(profile_id, stat_deltas)**: Load current stats JSONB, merge numeric deltas (addition for matching keys), UPDATE.

**convert_guest(guest_session_id, user_id)**: UPDATE SET user_id=%s, guest_session_id=NULL WHERE guest_session_id=%s. Return success/error.

- [ ] **Step 2: Verify import**

```bash
docker exec archie_platform python3 -c "from tools.game_studio.world_state_service import get_world_resources, create_profile, create_world_event; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/game_studio/world_state_service.py
git commit -m "feat(game-studio): add world state service — resources, events, profiles"
```

---

## Task 3: Game Server (Flask-SocketIO)

**Files:**
- Create: `platform_v2/tools/game_studio/game_server.py`
- Modify: `platform_v2/app.py` (SocketIO init)

- [ ] **Step 1: Write game server (~200 lines)**

```python
"""Game server — Flask-SocketIO WebSocket handler for multiplayer.

Namespace: /game
Events: join_session, leave_session, player_action, start_game
Broadcasts: state_update, player_joined, player_left, game_started, game_ended
"""

import logging
import time
import secrets
from flask_socketio import emit, join_room, leave_room, Namespace
from database import get_db_cursor

logger = logging.getLogger(__name__)

# Server-side state for active rooms
# {room_code: {players: {profile_id: {x,y,name,color,...}}, game_state: {...}, last_tick: float}}
_rooms = {}
```

**Class GameNamespace(Namespace)** with namespace='/game':

**on_join_session(data)**: Validate room_code exists in game_sessions + status in ('lobby','playing'). Validate not full. join_room(room_code). Add to _rooms[room_code].players. UPDATE game_sessions.current_players. emit('player_joined', player_info, room=room_code).

**on_leave_session(data)**: leave_room. Remove from _rooms. UPDATE current_players. emit('player_left'). If host left + players remain → assign new host. If empty → cleanup room.

**on_player_action(data)**: Validate action_type in ('move','shoot','interact','build','navigate'). Basic validation: move speed cap, shoot cooldown. Queue action for next tick. emit('state_update', broadcast to room).

**on_start_game(data)**: Verify host. UPDATE game_sessions status='playing'. emit('game_started', room=room_code).

**on_disconnect()**: Find all rooms for this sid, leave each.

**Helper: generate_room_code()**: 6 uppercase letters. Check uniqueness.

**Helper: create_session(game_id, host_profile_id, game_type, config, max_players)**: INSERT game_sessions. Init _rooms entry. Return room_code.

**Helper: end_session(room_code)**: Apply world_effects via world_state_service.apply_session_effects. UPDATE status='ended', ended_at=NOW(). Cleanup _rooms. emit('game_ended').

- [ ] **Step 2: Add SocketIO init to app.py**

Read `platform_v2/app.py` to find where the Flask app is created and where `app.run()` is called. Add:

Near the top (after Flask app creation):
```python
from flask_socketio import SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
```

Register the game namespace:
```python
from tools.game_studio.game_server import GameNamespace
socketio.on_namespace(GameNamespace('/game'))
```

Change `app.run()` to `socketio.run(app, ...)` at the startup point. If the app uses gunicorn or another WSGI server, add socketio as a fallback.

IMPORTANT: Read the actual app.py startup section first. The change may be a simple replacement or may need to be conditional. Be careful not to break the existing startup.

- [ ] **Step 3: Download socket.io client JS**

```bash
curl -o platform_v2/static/js/socket.io.min.js "https://cdn.socket.io/4.7.5/socket.io.min.js"
```

Or alternatively, the game-network.js can load it from CDN in the iframe.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/game_studio/game_server.py platform_v2/app.py platform_v2/static/js/socket.io.min.js
git commit -m "feat(game-studio): add Flask-SocketIO game server + namespace"
```

---

## Task 4: Client Network Layer

**Files:**
- Create: `platform_v2/static/js/game-network.js`
- Modify: `platform_v2/static/js/game-engine.js`

- [ ] **Step 1: Write game-network.js (~150 lines)**

```javascript
/**
 * GameNetwork — WebSocket client for multiplayer.
 * Loaded in game iframe alongside engine.
 * Connects to Flask-SocketIO /game namespace.
 */
class GameNetwork {
    constructor(engine) {
        this.engine = engine;
        this.socket = null;
        this.roomCode = null;
        this.profileId = null;
        this.players = {};     // {profileId: {x, y, name, color, health, ...}}
        this.isMultiplayer = false;
        this.isHost = false;
        this._actionQueue = [];
        this._lastSend = 0;
        this._sendInterval = 50; // 20 actions/sec max
    }
}
```

**connect(roomCode, profileId, isHost)**:
- `this.socket = io('/game', {transports: ['websocket']})`
- Emit `join_session` with room_code + profile_id
- Listen for `state_update` → update this.players
- Listen for `player_joined`/`player_left` → update players + notify engine
- Listen for `game_started` → engine.start()
- Listen for `game_ended` → show game over with world effects
- Set isMultiplayer = true

**disconnect()**:
- Emit `leave_session`
- socket.disconnect()
- Reset state

**sendAction(actionType, data)**:
- Throttle: if Date.now() - _lastSend < _sendInterval, queue
- Emit `player_action` with roomCode + action

**sendPlayerState()**:
- Called from engine update loop every 100ms
- Sends current player position/health/state as a `move` action

**getOtherPlayers()**:
- Returns this.players dict for rendering

**postMessage listener** (at bottom):
```javascript
window.addEventListener('message', function(e) {
    if (e.data.type === 'connectMultiplayer') {
        if (!window._engine) return;
        window._network = new GameNetwork(window._engine);
        window._network.connect(e.data.roomCode, e.data.profileId, e.data.isHost);
    }
    if (e.data.type === 'disconnectMultiplayer') {
        if (window._network) window._network.disconnect();
        window._network = null;
    }
    if (e.data.type === 'startMultiplayerGame') {
        if (window._network && window._network.socket) {
            window._network.socket.emit('start_game', {room_code: window._network.roomCode});
        }
    }
});
```

- [ ] **Step 2: Add network integration to game-engine.js**

Read game-engine.js. Add to the update loop (after module.update):
```javascript
// Send player state to network
if (window._network && window._network.isMultiplayer) {
    window._network.sendPlayerState();
}
```

Add to the render method (after module.render):
```javascript
// Render other players
if (window._network && window._network.isMultiplayer) {
    var others = window._network.getOtherPlayers();
    var self = this;
    Object.keys(others).forEach(function(pid) {
        var p = others[pid];
        self.ctx.save();
        self.ctx.globalAlpha = 0.8;
        self.drawCircle(p.x, p.y, p.size || 16, p.color || '#aaf');
        self.drawText(p.name || 'Player', p.x, p.y - 20, {color: '#fff', size: 10, align: 'center'});
        self.ctx.restore();
    });
}
```

Add `loadBehaviors` for network in postMessage — already handled. Just add `socket.io.min.js` to iframe script loading.

- [ ] **Step 3: Update refreshPreview in game-studio.js**

Add socket.io + game-network.js to iframe scripts:
```javascript
html += '<scr' + 'ipt src="/static/js/socket.io.min.js"></scr' + 'ipt>';
html += '<scr' + 'ipt src="/static/js/game-network.js"></scr' + 'ipt>';
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/static/js/game-network.js platform_v2/static/js/game-engine.js platform_v2/static/js/game-studio.js
git commit -m "feat(game-studio): add client network layer + engine multiplayer rendering"
```

---

## Task 5: REST Routes — Profile + Session + World

**Files:**
- Modify: `platform_v2/tools/game_studio/routes.py`

- [ ] **Step 1: Append 8 REST endpoints**

**Profile routes:**

POST /api/profile — create profile. Body: {display_name, avatar_config}. If user logged in, link user_id. Else create guest with session ID.
GET /api/profile — get current user's profile (or guest by session).
PUT /api/profile — update display_name + avatar_config.

**Session routes:**

POST /api/sessions — create session. Body: {game_id, game_type, max_players}. Calls game_server.create_session(). Returns {room_code, session_id}.
GET /api/sessions — list open sessions (status in lobby/playing, ordered by created_at DESC).
GET /api/sessions/<room_code> — get session detail with player list.
POST /api/sessions/<room_code>/end — end session (host only). Calls game_server.end_session().

**World route:**

GET /api/world — get world resources + recent events (last 20). Calls world_state_service.

All routes use @game_studio_bp.route + @login_required (except profile creation which can be guest).

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/game_studio/routes.py
git commit -m "feat(game-studio): add profile + session + world REST endpoints"
```

---

## Task 6: Frontend — Lobby + Profile + World UI

**Files:**
- Modify: `platform_v2/static/js/game-studio.js`
- Modify: `platform_v2/templates/tools/game_studio.html`
- Modify: `platform_v2/static/css/game-studio.css`

- [ ] **Step 1: Add Lobby + World tabs to HTML**

In the tab bar (alongside Config/Code/Preview), add:
```html
<button class="gs-tab" data-tab="lobby" onclick="setTab('lobby')">Lobby</button>
<button class="gs-tab" data-tab="world" onclick="setTab('world')">World</button>
```

Add tab content containers:
```html
<!-- Lobby Tab -->
<div id="gsLobbyTab" style="display:none;" class="gs-tab-content">
    <div class="gs-lobby-header">
        <button class="gs-toolbar-btn" onclick="openCreateSessionModal()">Create Session</button>
        <button class="gs-toolbar-btn" onclick="openJoinSessionModal()">Join Session</button>
    </div>
    <div id="gsSessionList" class="gs-session-list"></div>
    <div id="gsActiveLobby" style="display:none;">
        <div class="gs-prop-group-title">Room: <span id="gsRoomCode" class="gs-room-code"></span></div>
        <div id="gsLobbyPlayers"></div>
        <button id="gsStartGameBtn" class="gs-toolbar-btn" style="display:none;" onclick="startMultiplayerGame()">Start Game</button>
        <button class="gs-toolbar-btn" onclick="leaveSession()">Leave</button>
    </div>
</div>

<!-- World Tab -->
<div id="gsWorldTab" style="display:none;" class="gs-tab-content">
    <div class="gs-prop-group-title">World Resources</div>
    <div id="gsWorldResources"></div>
    <div class="gs-prop-group-title" style="margin-top:1rem;">Recent Events</div>
    <div id="gsWorldEvents"></div>
</div>
```

Add session modals:
```html
<!-- Create Session Modal -->
<div id="gsCreateSessionModal" class="gs-modal" style="display:none;">
    <div class="gs-modal-content">
        <div class="gs-modal-title">Create Session</div>
        <label>Max Players: <input type="number" id="gsSessionMaxPlayers" value="4" min="2" max="8" class="gs-prop-input"></label>
        <div class="gs-modal-actions">
            <button class="gs-toolbar-btn" onclick="closeModal('gsCreateSessionModal')">Cancel</button>
            <button class="gs-toolbar-btn" style="background:var(--gs-accent);color:#000;" onclick="createSession()">Create</button>
        </div>
    </div>
</div>

<!-- Join Session Modal -->
<div id="gsJoinSessionModal" class="gs-modal" style="display:none;">
    <div class="gs-modal-content">
        <div class="gs-modal-title">Join Session</div>
        <label>Room Code: <input type="text" id="gsJoinRoomCode" class="gs-prop-input" placeholder="ABCDEF" maxlength="6" style="text-transform:uppercase;"></label>
        <div class="gs-modal-actions">
            <button class="gs-toolbar-btn" onclick="closeModal('gsJoinSessionModal')">Cancel</button>
            <button class="gs-toolbar-btn" style="background:var(--gs-accent);color:#000;" onclick="joinSession()">Join</button>
        </div>
    </div>
</div>
```

Add profile panel in right sidebar:
```html
<div class="gs-prop-group" id="gsProfilePanel">
    <div class="gs-prop-group-title">Player Profile</div>
    <div id="gsProfileContent"></div>
</div>
```

- [ ] **Step 2: Add multiplayer JS (~220 lines)**

Insert before DOMContentLoaded in the IIFE:

```javascript
// ── Phase 4: Multiplayer ──

var _profile = null;
var _currentRoomCode = null;
var _worldRefreshInterval = null;

// Profile
window.loadProfile = function() {
    api('GET', '/api/profile').then(function(data) {
        if (data.profile) {
            _profile = data.profile;
            renderProfile();
        } else {
            renderProfileCreate();
        }
    });
};

function renderProfile() {
    var container = document.getElementById('gsProfileContent');
    clearEl(container);
    var name = document.createElement('div');
    name.className = 'gs-prop-row';
    var nameLabel = document.createElement('span');
    nameLabel.className = 'gs-prop-label';
    nameLabel.textContent = 'Name';
    var nameVal = document.createElement('span');
    nameVal.className = 'gs-prop-value';
    nameVal.textContent = _profile.display_name;
    name.appendChild(nameLabel);
    name.appendChild(nameVal);
    container.appendChild(name);
    // Level + Credits
    var level = document.createElement('div');
    level.className = 'gs-prop-row';
    var lvlLabel = document.createElement('span');
    lvlLabel.className = 'gs-prop-label';
    lvlLabel.textContent = 'Level';
    var lvlVal = document.createElement('span');
    lvlVal.className = 'gs-prop-value';
    lvlVal.textContent = _profile.level + ' (' + _profile.xp + ' XP)';
    level.appendChild(lvlLabel);
    level.appendChild(lvlVal);
    container.appendChild(level);
    var cred = document.createElement('div');
    cred.className = 'gs-prop-row';
    var credLabel = document.createElement('span');
    credLabel.className = 'gs-prop-label';
    credLabel.textContent = 'Credits';
    var credVal = document.createElement('span');
    credVal.className = 'gs-prop-value';
    credVal.textContent = _profile.credits;
    cred.appendChild(credLabel);
    cred.appendChild(credVal);
    container.appendChild(cred);
}

function renderProfileCreate() {
    var container = document.getElementById('gsProfileContent');
    clearEl(container);
    var btn = document.createElement('button');
    btn.className = 'gs-toolbar-btn';
    btn.textContent = 'Create Profile';
    btn.onclick = function() {
        var name = prompt('Display name:');
        if (!name) return;
        api('POST', '/api/profile', {display_name: name}).then(function(data) {
            if (data.profile) { _profile = data.profile; renderProfile(); }
        });
    };
    container.appendChild(btn);
}

// Sessions
window.openCreateSessionModal = function() {
    document.getElementById('gsCreateSessionModal').style.display = 'flex';
};
window.openJoinSessionModal = function() {
    document.getElementById('gsJoinSessionModal').style.display = 'flex';
};

window.createSession = function() {
    if (!_profile) { alert('Create a profile first'); return; }
    if (!_currentGameId) { alert('Open a game project first'); return; }
    var maxPlayers = parseInt(document.getElementById('gsSessionMaxPlayers').value) || 4;
    api('POST', '/api/sessions', {
        game_id: _currentGameId,
        game_type: _gameConfig ? _gameConfig.type : 'top_down_shooter',
        max_players: maxPlayers,
    }).then(function(data) {
        if (data.error) { alert(data.error); return; }
        closeModal('gsCreateSessionModal');
        _currentRoomCode = data.room_code;
        joinMultiplayer(data.room_code, true);
        toast('Session created: ' + data.room_code);
    });
};

window.joinSession = function() {
    if (!_profile) { alert('Create a profile first'); return; }
    var code = document.getElementById('gsJoinRoomCode').value.trim().toUpperCase();
    if (!code) { alert('Enter a room code'); return; }
    closeModal('gsJoinSessionModal');
    _currentRoomCode = code;
    joinMultiplayer(code, false);
};

function joinMultiplayer(roomCode, isHost) {
    // Show active lobby
    document.getElementById('gsSessionList').style.display = 'none';
    document.getElementById('gsActiveLobby').style.display = '';
    document.getElementById('gsRoomCode').textContent = roomCode;
    document.getElementById('gsStartGameBtn').style.display = isHost ? '' : 'none';
    // Send connect command to iframe
    var iframe = document.getElementById('gsPreviewFrame');
    if (iframe && iframe.contentWindow) {
        iframe.contentWindow.postMessage({
            type: 'connectMultiplayer',
            roomCode: roomCode,
            profileId: _profile.id,
            isHost: isHost,
        }, '*');
    }
    // Switch to preview tab
    setTab('preview');
    loadSessionPlayers(roomCode);
}

window.startMultiplayerGame = function() {
    var iframe = document.getElementById('gsPreviewFrame');
    if (iframe && iframe.contentWindow) {
        iframe.contentWindow.postMessage({type: 'startMultiplayerGame'}, '*');
    }
};

window.leaveSession = function() {
    var iframe = document.getElementById('gsPreviewFrame');
    if (iframe && iframe.contentWindow) {
        iframe.contentWindow.postMessage({type: 'disconnectMultiplayer'}, '*');
    }
    _currentRoomCode = null;
    document.getElementById('gsActiveLobby').style.display = 'none';
    document.getElementById('gsSessionList').style.display = '';
    loadOpenSessions();
};

function loadSessionPlayers(roomCode) {
    api('GET', '/api/sessions/' + roomCode).then(function(data) {
        var container = document.getElementById('gsLobbyPlayers');
        clearEl(container);
        // Render player list from session data
        var players = data.players || [];
        players.forEach(function(p) {
            var div = document.createElement('div');
            div.className = 'gs-lobby-player';
            div.textContent = p.display_name + (p.is_host ? ' (Host)' : '');
            container.appendChild(div);
        });
    });
}

window.loadOpenSessions = function() {
    api('GET', '/api/sessions').then(function(data) {
        var container = document.getElementById('gsSessionList');
        clearEl(container);
        var sessions = data.sessions || [];
        if (sessions.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'gs-text-muted';
            empty.textContent = 'No open sessions';
            container.appendChild(empty);
            return;
        }
        sessions.forEach(function(s) {
            var card = document.createElement('div');
            card.className = 'gs-lobby-player';
            card.style.cursor = 'pointer';
            var info = document.createElement('span');
            info.textContent = s.room_code + ' — ' + s.game_type + ' (' + s.current_players + '/' + s.max_players + ')';
            var joinBtn = document.createElement('button');
            joinBtn.className = 'gs-toolbar-btn';
            joinBtn.textContent = 'Join';
            joinBtn.onclick = function(e) {
                e.stopPropagation();
                _currentRoomCode = s.room_code;
                joinMultiplayer(s.room_code, false);
            };
            card.appendChild(info);
            card.appendChild(joinBtn);
            container.appendChild(card);
        });
    });
};

// World State
window.loadWorldState = function() {
    api('GET', '/api/world').then(function(data) {
        // Resources
        var resContainer = document.getElementById('gsWorldResources');
        clearEl(resContainer);
        var resources = data.resources || {};
        Object.keys(resources).forEach(function(key) {
            var row = document.createElement('div');
            row.className = 'gs-world-resource';
            var label = document.createElement('span');
            label.textContent = key.replace(/_/g, ' ');
            var val = document.createElement('span');
            val.textContent = Math.floor(resources[key]);
            row.appendChild(label);
            row.appendChild(val);
            resContainer.appendChild(row);
        });
        // Events
        var evContainer = document.getElementById('gsWorldEvents');
        clearEl(evContainer);
        var events = data.events || [];
        events.forEach(function(ev) {
            var div = document.createElement('div');
            div.className = 'gs-world-event';
            div.textContent = ev.event_type.replace(/_/g, ' ') + ' — ' + (ev.source_game_type || '') + ' (' + (ev.created_at || '').split('T')[0] + ')';
            evContainer.appendChild(div);
        });
    });
};
```

Update setTab to handle lobby + world:
```javascript
// In existing setTab function, add cases:
if (tab === 'lobby') { loadOpenSessions(); }
if (tab === 'world') { loadWorldState(); }
```

Update DOMContentLoaded init to load profile:
```javascript
// After initMonaco → loadDashboard, also:
loadProfile();
```

- [ ] **Step 3: Add multiplayer CSS (~30 lines)**

```css
/* Phase 4: Multiplayer */
.gs-lobby-header { display:flex; gap:0.5rem; margin-bottom:0.75rem; }
.gs-session-list { display:flex; flex-direction:column; gap:0.5rem; }
.gs-lobby-player {
    display:flex; justify-content:space-between; align-items:center;
    padding:0.4rem 0.5rem; border:1px solid var(--gs-border,#232);
    border-radius:4px; font-size:0.75rem; color:var(--gs-text,#aab);
}
.gs-room-code {
    font-family:'IBM Plex Mono',monospace; font-size:1.2rem;
    color:var(--gs-accent,#4f6); letter-spacing:0.2em;
}
.gs-world-resource {
    display:flex; justify-content:space-between; padding:0.3rem 0;
    font-size:0.75rem; color:var(--gs-text,#aab);
    border-bottom:1px solid rgba(255,255,255,0.03);
}
.gs-world-event {
    padding:0.25rem 0; font-size:0.65rem; color:var(--gs-text,#aab);
    border-bottom:1px solid rgba(255,255,255,0.03);
}
.gs-text-muted { font-size:0.7rem; color:#556; padding:0.5rem 0; }
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/static/js/game-studio.js platform_v2/templates/tools/game_studio.html platform_v2/static/css/game-studio.css
git commit -m "feat(game-studio): add lobby, profile, world state multiplayer UI"
```

---

## Task 7: Integration Test

**Files:**
- Create: `/tmp/test_game_studio_phase4.py`

- [ ] **Step 1: Write integration test**

Test:
- DB tables exist: game_player_profiles, game_world_state, game_world_events, game_sessions
- World resources seeded (5 rows)
- Service imports: world_state_service (get_world_resources, create_profile, create_world_event)
- Profile creation works (create + get)
- World resources readable
- Routes registered (profile, sessions, world — at least 8 new)
- HTML has: gsLobbyTab, gsWorldTab, gsRoomCode, gsActiveLobby, gsProfilePanel, gsCreateSessionModal
- JS has: loadProfile, createSession, joinSession, leaveSession, loadWorldState, loadOpenSessions
- CSS has: .gs-lobby-player, .gs-room-code, .gs-world-resource
- game-network.js exists with GameNetwork class
- game-engine.js has network rendering (_network, getOtherPlayers)

- [ ] **Step 2: Run test**

```bash
docker cp /tmp/test_game_studio_phase4.py archie_platform:/tmp/
docker exec archie_platform python3 /tmp/test_game_studio_phase4.py
```

- [ ] **Step 3: Fix any failures**

---

## Task 8: Deploy + Push + Dev HQ

- [ ] **Step 1: Docker rebuild (for flask-socketio)**

```bash
docker compose build archie_platform && docker compose up -d
```

- [ ] **Step 2: Push**

```bash
git push origin main
```

- [ ] **Step 3: Update Dev HQ**

- complete_task #866 (Phase 4)
- store_memory — Game Studio Phase 4 complete
- log_decision — Flask-SocketIO threading mode, semi-authoritative server, hybrid world state
