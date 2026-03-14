/**
 * A.R.C.H.I.E. Game Studio — Client Network Layer
 * Handles multiplayer WebSocket communication via Socket.IO.
 * Runs inside the game preview iframe.
 */

(function () {
    'use strict';

    // -------------------------------------------------------------------------
    // GameNetwork class
    // -------------------------------------------------------------------------

    function GameNetwork(engine) {
        this.engine = engine;
        this.socket = null;
        this.roomCode = null;
        this.profileId = null;
        this.players = {};      // {profile_id: {x, y, name, color, health}}
        this.isMultiplayer = false;
        this.isHost = false;
        this._lastSend = 0;
    }

    /**
     * Connect to the /game namespace and join a session.
     * @param {string} roomCode
     * @param {string|number} profileId
     * @param {boolean} isHost
     */
    GameNetwork.prototype.connect = function (roomCode, profileId, isHost) {
        var self = this;

        if (typeof io === 'undefined') {
            console.warn('[GameNetwork] socket.io not available — multiplayer disabled');
            return;
        }

        this.roomCode = roomCode;
        this.profileId = profileId;
        this.isHost = !!isHost;
        this.isMultiplayer = true;

        this.socket = io('/game', { transports: ['websocket'] });

        this.socket.on('connect', function () {
            console.log('[GameNetwork] connected sid=' + self.socket.id);
            self.socket.emit('join_session', {
                room_code: self.roomCode,
                profile_id: self.profileId,
            });
        });

        this.socket.on('state_update', function (data) {
            if (!data || !data.players) return;
            // Update remote players (exclude self)
            var updated = {};
            Object.keys(data.players).forEach(function (pid) {
                if (String(pid) !== String(self.profileId)) {
                    updated[pid] = data.players[pid];
                }
            });
            self.players = updated;
        });

        this.socket.on('player_joined', function (data) {
            console.log('[GameNetwork] player_joined', data.name, data.profile_id);
        });

        this.socket.on('player_left', function (data) {
            delete self.players[data.profile_id];
            console.log('[GameNetwork] player_left', data.profile_id);
        });

        this.socket.on('game_started', function (data) {
            console.log('[GameNetwork] game_started', data);
            if (self.engine && typeof self.engine.start === 'function' && !self.engine.frameId) {
                self.engine.start();
            }
        });

        this.socket.on('game_ended', function (data) {
            console.log('[GameNetwork] game_ended', data);
            // Notify parent frame
            try {
                window.parent.postMessage({ type: 'multiplayerGameEnded', roomCode: self.roomCode }, '*');
            } catch (e) { /* cross-origin guard */ }
        });

        this.socket.on('host_changed', function (data) {
            if (String(data.profile_id) === String(self.profileId)) {
                self.isHost = true;
                console.log('[GameNetwork] You are now the host');
            }
        });

        this.socket.on('error', function (data) {
            console.error('[GameNetwork] server error:', data.message);
        });

        this.socket.on('disconnect', function (reason) {
            console.warn('[GameNetwork] disconnected:', reason);
            self.isMultiplayer = false;
        });
    };

    /**
     * Leave session and disconnect socket.
     */
    GameNetwork.prototype.disconnect = function () {
        if (this.socket) {
            if (this.roomCode && this.profileId) {
                this.socket.emit('leave_session', {
                    room_code: this.roomCode,
                    profile_id: this.profileId,
                });
            }
            this.socket.disconnect();
            this.socket = null;
        }
        this.roomCode = null;
        this.profileId = null;
        this.players = {};
        this.isMultiplayer = false;
        this.isHost = false;
        this._lastSend = 0;
    };

    /**
     * Send local player state to server. Throttled to 50ms (20 Hz).
     */
    GameNetwork.prototype.sendPlayerState = function () {
        if (!this.socket || !this.isMultiplayer) return;

        var now = Date.now();
        if (now - this._lastSend < 50) return;
        this._lastSend = now;

        // Get local player entity from the engine module
        var x = 400, y = 400, health = 100;
        try {
            var module = this.engine && this.engine._module;
            if (module && typeof module.getEntities === 'function') {
                var entities = module.getEntities();
                if (entities && entities[0]) {
                    x = entities[0].x || x;
                    y = entities[0].y || y;
                    health = entities[0].health !== undefined ? entities[0].health : health;
                }
            } else if (module && module.player) {
                x = module.player.x || x;
                y = module.player.y || y;
                health = module.player.health !== undefined ? module.player.health : health;
            }
        } catch (e) {
            /* entity access may fail during transition */
        }

        this.socket.emit('player_action', {
            room_code: this.roomCode,
            action_type: 'move',
            action_data: { x: x, y: y, health: health },
        });
    };

    /**
     * Return remote players dict (excludes local player).
     * @returns {Object} {profile_id: {x, y, name, color, health}}
     */
    GameNetwork.prototype.getOtherPlayers = function () {
        return this.players;
    };

    // -------------------------------------------------------------------------
    // postMessage listener — called by parent game-studio.js
    // -------------------------------------------------------------------------

    window.addEventListener('message', function (e) {
        var data = e.data;
        if (!data || !data.type) return;

        if (data.type === 'connectMultiplayer') {
            // Lazy-init network
            var engine = window._gameEngine || null;
            var net = new GameNetwork(engine);
            window._network = net;
            net.connect(data.roomCode, data.profileId, data.isHost);

        } else if (data.type === 'disconnectMultiplayer') {
            if (window._network) {
                window._network.disconnect();
                window._network = null;
            }

        } else if (data.type === 'startMultiplayerGame') {
            var net = window._network;
            if (net && net.socket && net.isHost) {
                net.socket.emit('start_game', { room_code: net.roomCode });
            }
        }
    });

    // Expose class
    window.GameNetwork = GameNetwork;

}());
