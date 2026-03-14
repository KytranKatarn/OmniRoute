/**
 * Space Explorer Module — Game Studio Phase 2
 * Galaxy, System, Planet, and Combat layers
 * Registered as 'space_explorer' with GameEngine
 */

var DEFAULT_EXPLORER_CONFIG = {
    type: 'space_explorer',
    player: {x: 500, y: 400, fuel: 100, maxFuel: 100, credits: 500, health: 100, cargo: [], cargoMax: 20},
    stars: [
        {id: 'sol', name: 'Sol', x: 500, y: 400, type: 'yellow', color: '#ff0', size: 8, planets: [
            {name: 'Mercury', orbitRadius: 40, size: 6, color: '#a86', type: 'rocky', resources: {minerals: 5}, hazard: 0.2, angle: 0},
            {name: 'Earth', orbitRadius: 80, size: 10, color: '#48f', type: 'terran', resources: {minerals: 3, bio: 8}, hazard: 0.1, angle: 1.2},
            {name: 'Mars', orbitRadius: 120, size: 8, color: '#c64', type: 'rocky', resources: {minerals: 8}, hazard: 0.3, angle: 2.4}
        ]},
        {id: 'alpha_centauri', name: 'Alpha Centauri', x: 200, y: 150, type: 'yellow', color: '#ff0', size: 7, planets: [
            {name: 'Proxima b', orbitRadius: 50, size: 9, color: '#6a9', type: 'terran', resources: {minerals: 4, bio: 6}, hazard: 0.15, angle: 0},
            {name: 'Proxima c', orbitRadius: 90, size: 7, color: '#964', type: 'rocky', resources: {minerals: 6}, hazard: 0.25, angle: 0.8}
        ]},
        {id: 'sirius', name: 'Sirius', x: 750, y: 120, type: 'blue', color: '#48f', size: 9, planets: [
            {name: 'Sirius I', orbitRadius: 45, size: 5, color: '#888', type: 'barren', resources: {minerals: 9}, hazard: 0.5, angle: 0.3},
            {name: 'Sirius II', orbitRadius: 85, size: 7, color: '#a7b', type: 'ice', resources: {minerals: 2, bio: 1}, hazard: 0.4, angle: 1.6},
            {name: 'Sirius III', orbitRadius: 130, size: 11, color: '#77a', type: 'gas', resources: {bio: 3}, hazard: 0.6, angle: 3.0}
        ]},
        {id: 'vega', name: 'Vega', x: 850, y: 350, type: 'blue', color: '#6af', size: 8, planets: [
            {name: 'Vega Prime', orbitRadius: 60, size: 12, color: '#4a9', type: 'terran', resources: {minerals: 5, bio: 10}, hazard: 0.05, angle: 0.5},
            {name: 'Vega II', orbitRadius: 110, size: 8, color: '#c96', type: 'rocky', resources: {minerals: 7}, hazard: 0.35, angle: 2.1},
            {name: 'Vega III', orbitRadius: 160, size: 14, color: '#49c', type: 'gas', resources: {bio: 5}, hazard: 0.45, angle: 4.2}
        ]},
        {id: 'betelgeuse', name: 'Betelgeuse', x: 120, y: 500, type: 'red', color: '#f44', size: 10, planets: [
            {name: 'Bete I', orbitRadius: 70, size: 8, color: '#b55', type: 'volcanic', resources: {minerals: 12}, hazard: 0.7, angle: 1.0},
            {name: 'Bete II', orbitRadius: 120, size: 10, color: '#c77', type: 'rocky', resources: {minerals: 10, bio: 2}, hazard: 0.5, angle: 2.5},
            {name: 'Bete III', orbitRadius: 180, size: 7, color: '#966', type: 'barren', resources: {minerals: 4}, hazard: 0.4, angle: 0.2},
            {name: 'Bete IV', orbitRadius: 250, size: 16, color: '#744', type: 'gas', resources: {bio: 2}, hazard: 0.55, angle: 3.8}
        ]},
        {id: 'rigel', name: 'Rigel', x: 680, y: 650, type: 'blue', color: '#88f', size: 9, planets: [
            {name: 'Rigel I', orbitRadius: 55, size: 6, color: '#aac', type: 'barren', resources: {minerals: 8}, hazard: 0.6, angle: 0.7},
            {name: 'Rigel II', orbitRadius: 100, size: 9, color: '#8af', type: 'ice', resources: {minerals: 3, bio: 4}, hazard: 0.3, angle: 1.9}
        ]},
        {id: 'antares', name: 'Antares', x: 300, y: 700, type: 'red', color: '#f64', size: 10, planets: [
            {name: 'Antares I', orbitRadius: 50, size: 7, color: '#d55', type: 'volcanic', resources: {minerals: 15}, hazard: 0.8, angle: 2.2},
            {name: 'Antares II', orbitRadius: 95, size: 9, color: '#c88', type: 'rocky', resources: {minerals: 9}, hazard: 0.55, angle: 0.4},
            {name: 'Antares III', orbitRadius: 145, size: 13, color: '#a66', type: 'gas', resources: {bio: 4}, hazard: 0.5, angle: 5.1}
        ]},
        {id: 'tau_ceti', name: 'Tau Ceti', x: 900, y: 550, type: 'yellow', color: '#fe8', size: 6, planets: [
            {name: 'Tau Ceti e', orbitRadius: 65, size: 11, color: '#5a8', type: 'terran', resources: {minerals: 6, bio: 12}, hazard: 0.1, angle: 0.9},
            {name: 'Tau Ceti f', orbitRadius: 105, size: 9, color: '#3c7', type: 'terran', resources: {minerals: 4, bio: 9}, hazard: 0.2, angle: 3.3},
            {name: 'Tau Ceti g', orbitRadius: 155, size: 6, color: '#9b5', type: 'rocky', resources: {minerals: 5}, hazard: 0.35, angle: 1.7},
            {name: 'Tau Ceti h', orbitRadius: 210, size: 15, color: '#5b9', type: 'gas', resources: {bio: 6}, hazard: 0.4, angle: 4.9}
        ]},
        {id: 'epsilon_eridani', name: 'Epsilon Eridani', x: 150, y: 280, type: 'yellow', color: '#fa8', size: 5, planets: [
            {name: 'EE b', orbitRadius: 55, size: 8, color: '#7a5', type: 'rocky', resources: {minerals: 7}, hazard: 0.3, angle: 1.4},
            {name: 'EE c', orbitRadius: 100, size: 10, color: '#4b8', type: 'terran', resources: {minerals: 5, bio: 7}, hazard: 0.2, angle: 2.8}
        ]},
        {id: 'pollux', name: 'Pollux', x: 460, y: 220, type: 'red', color: '#f88', size: 7, planets: [
            {name: 'Pollux b', orbitRadius: 80, size: 13, color: '#c89', type: 'gas', resources: {bio: 8}, hazard: 0.45, angle: 0.6},
            {name: 'Pollux c', orbitRadius: 140, size: 7, color: '#a77', type: 'rocky', resources: {minerals: 6}, hazard: 0.4, angle: 3.6},
            {name: 'Pollux d', orbitRadius: 200, size: 5, color: '#986', type: 'barren', resources: {minerals: 3}, hazard: 0.5, angle: 1.1}
        ]},
        {id: 'fomalhaut', name: 'Fomalhaut', x: 600, y: 780, type: 'white', color: '#eee', size: 8, planets: [
            {name: 'Fomalhaut b', orbitRadius: 90, size: 9, color: '#ccc', type: 'ice', resources: {minerals: 4, bio: 2}, hazard: 0.55, angle: 2.0},
            {name: 'Fomalhaut c', orbitRadius: 150, size: 11, color: '#aae', type: 'gas', resources: {bio: 7}, hazard: 0.35, angle: 4.5}
        ]},
        {id: 'capella', name: 'Capella', x: 820, y: 760, type: 'yellow', color: '#ff8', size: 7, planets: [
            {name: 'Capella I', orbitRadius: 60, size: 7, color: '#8b6', type: 'rocky', resources: {minerals: 8}, hazard: 0.3, angle: 0.3},
            {name: 'Capella II', orbitRadius: 110, size: 10, color: '#6a9', type: 'terran', resources: {minerals: 4, bio: 9}, hazard: 0.15, angle: 1.8},
            {name: 'Capella III', orbitRadius: 165, size: 8, color: '#9a7', type: 'rocky', resources: {minerals: 6}, hazard: 0.4, angle: 3.7},
            {name: 'Capella IV', orbitRadius: 230, size: 17, color: '#7c9', type: 'gas', resources: {bio: 5}, hazard: 0.45, angle: 5.5},
            {name: 'Capella V', orbitRadius: 300, size: 6, color: '#666', type: 'barren', resources: {minerals: 2}, hazard: 0.6, angle: 2.9}
        ]},
        {id: 'deneb', name: 'Deneb', x: 95, y: 750, type: 'white', color: '#eef', size: 9, planets: [
            {name: 'Deneb I', orbitRadius: 75, size: 8, color: '#bbd', type: 'ice', resources: {minerals: 5, bio: 3}, hazard: 0.5, angle: 1.3},
            {name: 'Deneb II', orbitRadius: 130, size: 12, color: '#99c', type: 'gas', resources: {bio: 9}, hazard: 0.4, angle: 3.1}
        ]},
        {id: 'altair', name: 'Altair', x: 380, y: 580, type: 'white', color: '#ddf', size: 6, planets: [
            {name: 'Altair b', orbitRadius: 50, size: 6, color: '#aab', type: 'barren', resources: {minerals: 7}, hazard: 0.5, angle: 0.8},
            {name: 'Altair c', orbitRadius: 90, size: 9, color: '#88b', type: 'rocky', resources: {minerals: 9}, hazard: 0.4, angle: 2.3},
            {name: 'Altair d', orbitRadius: 135, size: 14, color: '#66a', type: 'gas', resources: {bio: 6}, hazard: 0.35, angle: 4.7}
        ]},
        {id: 'spica', name: 'Spica', x: 700, y: 430, type: 'blue', color: '#4ff', size: 8, planets: [
            {name: 'Spica I', orbitRadius: 65, size: 7, color: '#6cc', type: 'barren', resources: {minerals: 11}, hazard: 0.65, angle: 1.5},
            {name: 'Spica II', orbitRadius: 115, size: 10, color: '#4bb', type: 'ice', resources: {minerals: 4, bio: 2}, hazard: 0.55, angle: 3.4}
        ]}
    ],
    stations: [{starId: 'sol', name: 'Starbase Alpha', services: ['refuel', 'trade']}],
    fuelPerJump: 5,
    encounters: {pirateChance: 0.15}
};

(function () {
    'use strict';

    function ExplorerModule(engine, config) {
        this.engine = engine;
        this.config = JSON.parse(JSON.stringify(config || DEFAULT_EXPLORER_CONFIG));
        this._layer = 'galaxy';
        this._currentStar = null;
        this._currentPlanet = null;
        this._hoverStar = null;
        this._travelTarget = null;
        this._travelProgress = 0;
        this._travelDuration = 1.0;
        this._encounter = null;
        this._fireTimer = 0;
        this._scanResult = null;
        this._gameOver = false;
        this._shipVx = 0;
        this._shipVy = 0;
        this._nearPlanet = null;
        this._nearStation = null;
        this._ePressed = false;
    }

    ExplorerModule.prototype.init = function () {
        var cfg = this.config;
        // Set initial star to home star
        this._currentStar = cfg.stars[0];
        // Assign planet angles if not set
        cfg.stars.forEach(function (star) {
            star.planets.forEach(function (p) {
                if (p.angle === undefined) p.angle = Math.random() * Math.PI * 2;
            });
        });
        // Bind input handlers
        var self = this;
        if (this.engine.input && this.engine.input.onTap) {
            this.engine.input.onTap(function (x, y) { self._handleTap(x, y); });
        }
    };

    ExplorerModule.prototype.update = function (dt) {
        if (this._gameOver) return;

        if (this._encounter) {
            this._updateEncounter(dt);
            return;
        }

        if (this._layer === 'galaxy') {
            this._updateGalaxy(dt);
        } else if (this._layer === 'system') {
            this._updateSystem(dt);
        } else if (this._layer === 'planet') {
            this._updatePlanet(dt);
        }
    };

    ExplorerModule.prototype._updateGalaxy = function (dt) {
        var cfg = this.config;
        var player = cfg.player;

        // Handle travel animation
        if (this._travelTarget) {
            this._travelProgress += dt / this._travelDuration;
            if (this._travelProgress >= 1) {
                player.x = this._travelTarget.x;
                player.y = this._travelTarget.y;
                var dist = this._starDistance(this._currentStar, this._travelTarget);
                var fuelCost = Math.ceil(dist / 100 * cfg.fuelPerJump);
                player.fuel = Math.max(0, player.fuel - fuelCost);
                this._currentStar = this._travelTarget;
                this._travelTarget = null;
                this._travelProgress = 0;
                this._enterSystem();
            } else {
                var src = this._currentStar;
                var tgt = this._travelTarget;
                var t = this._travelProgress;
                player.x = src.x + (tgt.x - src.x) * t;
                player.y = src.y + (tgt.y - src.y) * t;
            }
        }

        // Mouse hover for stars
        var mouse = this.engine.input ? this.engine.input.mouse : null;
        this._hoverStar = null;
        if (mouse) {
            var self = this;
            cfg.stars.forEach(function (star) {
                var dx = mouse.x - star.x;
                var dy = mouse.y - star.y;
                if (Math.sqrt(dx * dx + dy * dy) < 20) {
                    self._hoverStar = star;
                }
            });
        }
    };

    ExplorerModule.prototype._updateSystem = function (dt) {
        var cfg = this.config;
        var player = cfg.player;
        var star = this._currentStar;

        // Orbit planets
        star.planets.forEach(function (p) {
            p.angle += dt * (0.3 / p.orbitRadius * 50);
        });

        // Ship movement — WASD
        var keys = this.engine.input ? this.engine.input.keys : {};
        var speed = 120;
        var vx = 0, vy = 0;
        if (keys['w'] || keys['ArrowUp'])    vy -= speed;
        if (keys['s'] || keys['ArrowDown'])  vy += speed;
        if (keys['a'] || keys['ArrowLeft'])  vx -= speed;
        if (keys['d'] || keys['ArrowRight']) vx += speed;

        // Touch/joystick
        if (this.engine.input && this.engine.input.joystick) {
            var j = this.engine.input.joystick;
            vx += j.x * speed;
            vy += j.y * speed;
        }

        player.x += vx * dt;
        player.y += vy * dt;

        // Clamp to canvas
        var w = this.engine.canvas ? this.engine.canvas.width : 1000;
        var h = this.engine.canvas ? this.engine.canvas.height : 800;
        player.x = Math.max(20, Math.min(w - 20, player.x));
        player.y = Math.max(60, Math.min(h - 20, player.y));

        // Proximity checks
        this._nearPlanet = null;
        this._nearStation = null;
        var cx = star.x + (this.engine.camera ? this.engine.camera.x : 0);
        var cy = star.y + (this.engine.camera ? this.engine.camera.y : 0);
        // Use canvas center for system star display
        var displayCx = w / 2, displayCy = h / 2;

        var self = this;
        star.planets.forEach(function (p) {
            var px = displayCx + Math.cos(p.angle) * p.orbitRadius;
            var py = displayCy + Math.sin(p.angle) * p.orbitRadius;
            var dx = player.x - px;
            var dy = player.y - py;
            if (Math.sqrt(dx * dx + dy * dy) < p.size + 25) {
                self._nearPlanet = p;
            }
        });

        // Station proximity
        var station = this._getStationForStar(star.id);
        if (station) {
            var sx = displayCx + 180, sy = displayCy - 80;
            var sdx = player.x - sx, sdy = player.y - sy;
            if (Math.sqrt(sdx * sdx + sdy * sdy) < 30) {
                this._nearStation = station;
            }
        }

        // E key to land/dock
        var eNow = keys['e'] || keys['E'];
        if (eNow && !this._ePressed) {
            if (this._nearPlanet) {
                this._currentPlanet = this._nearPlanet;
                this._layer = 'planet';
                this._scanResult = null;
            } else if (this._nearStation) {
                this._dockStation(this._nearStation);
            }
        }
        this._ePressed = eNow;
    };

    ExplorerModule.prototype._updatePlanet = function (dt) {
        // Nothing to animate continuously on planet surface
    };

    ExplorerModule.prototype._updateEncounter = function (dt) {
        var enc = this._encounter;
        enc.fireTimer -= dt;
        if (enc.fireTimer <= 0) {
            enc.fireTimer = 0.5;
            var playerDmg = 8 + Math.floor(Math.random() * 5);
            var pirateDmg = 8 + Math.floor(Math.random() * 5);
            enc.pirateHp -= pirateDmg;
            this.config.player.health -= playerDmg;

            if (enc.pirateHp <= 0) {
                this.config.player.credits += 50;
                var loot = ['minerals', 'bio'];
                var r = loot[Math.floor(Math.random() * loot.length)];
                this._addCargo(r, 3);
                this._encounter = null;
                return;
            }

            if (this.config.player.health <= 0) {
                this.config.player.health = 0;
                this._gameOver = true;
                this._encounter = null;
            }
        }
    };

    ExplorerModule.prototype._enterSystem = function () {
        this._layer = 'system';
        var w = this.engine.canvas ? this.engine.canvas.width : 1000;
        var h = this.engine.canvas ? this.engine.canvas.height : 800;
        this.config.player.x = w / 2;
        this.config.player.y = h / 2 + 200;
        this._scanResult = null;
        this._nearPlanet = null;
        this._nearStation = null;

        // Random encounter on entry
        if (Math.random() < this.config.encounters.pirateChance) {
            var dist = this._starDistanceFromHome();
            var pirateHp = 50 + Math.floor(dist / 100 * 30);
            this._encounter = {
                pirateHp: pirateHp,
                pirateMaxHp: pirateHp,
                fireTimer: 0.5
            };
        }
    };

    ExplorerModule.prototype._starDistance = function (a, b) {
        var dx = a.x - b.x, dy = a.y - b.y;
        return Math.sqrt(dx * dx + dy * dy);
    };

    ExplorerModule.prototype._starDistanceFromHome = function () {
        var home = this.config.stars[0];
        return this._starDistance(home, this._currentStar);
    };

    ExplorerModule.prototype._avgStarDistance = function () {
        var stars = this.config.stars;
        var total = 0;
        for (var i = 1; i < stars.length; i++) {
            total += this._starDistance(stars[0], stars[i]);
        }
        return total / (stars.length - 1);
    };

    ExplorerModule.prototype._fuelCostTo = function (star) {
        var dist = this._starDistance(this._currentStar, star);
        return Math.ceil(dist / 100 * this.config.fuelPerJump);
    };

    ExplorerModule.prototype._getStationForStar = function (starId) {
        var stations = this.config.stations;
        for (var i = 0; i < stations.length; i++) {
            if (stations[i].starId === starId) return stations[i];
        }
        return null;
    };

    ExplorerModule.prototype._addCargo = function (type, amount) {
        var p = this.config.player;
        if (p.cargo.length >= p.cargoMax) return;
        var existing = p.cargo.find(function (c) { return c.type === type; });
        if (existing) {
            existing.amount += amount;
        } else {
            p.cargo.push({type: type, amount: amount});
        }
    };

    ExplorerModule.prototype._totalCargo = function () {
        return this.config.player.cargo.reduce(function (sum, c) { return sum + c.amount; }, 0);
    };

    ExplorerModule.prototype._dockStation = function (station) {
        var p = this.config.player;
        if (station.services.indexOf('refuel') !== -1) {
            var needed = p.maxFuel - p.fuel;
            var cost = needed * 2;
            if (p.credits >= cost) {
                p.credits -= cost;
                p.fuel = p.maxFuel;
            }
        }
        if (station.services.indexOf('trade') !== -1) {
            var sold = 0;
            p.cargo.forEach(function (c) { sold += c.amount * 10; });
            p.credits += sold;
            p.cargo = [];
        }
    };

    ExplorerModule.prototype._handleTap = function (x, y) {
        if (this._gameOver) { this._resetGame(); return; }

        if (this._layer === 'galaxy' && !this._travelTarget) {
            var cfg = this.config;
            var self = this;
            cfg.stars.forEach(function (star) {
                if (star === self._currentStar) return;
                var dx = x - star.x, dy = y - star.y;
                if (Math.sqrt(dx * dx + dy * dy) < 20) {
                    var cost = self._fuelCostTo(star);
                    if (cfg.player.fuel >= cost) {
                        self._travelTarget = star;
                        self._travelProgress = 0;
                    }
                }
            });
        } else if (this._layer === 'system') {
            var w = this.engine.canvas ? this.engine.canvas.width : 1000;
            var h = this.engine.canvas ? this.engine.canvas.height : 800;
            // "Leave System" button
            if (x > w - 140 && x < w - 10 && y > 10 && y < 44) {
                this._layer = 'galaxy';
            }
            // E-land from tap
            if (this._nearPlanet && x > w / 2 - 80 && x < w / 2 + 80 && y > h - 50 && y < h - 10) {
                this._currentPlanet = this._nearPlanet;
                this._layer = 'planet';
                this._scanResult = null;
            }
            // Encounter flee
            if (this._encounter) {
                if (x > w / 2 - 40 && x < w / 2 + 40 && y > h / 2 + 80 && y < h / 2 + 110) {
                    if (this.config.player.fuel >= 5) {
                        this.config.player.fuel -= 5;
                        this._encounter = null;
                        this._layer = 'galaxy';
                    }
                }
            }
        } else if (this._layer === 'planet') {
            this._handlePlanetTap(x, y);
        }
    };

    ExplorerModule.prototype._handlePlanetTap = function (x, y) {
        var w = this.engine.canvas ? this.engine.canvas.width : 1000;
        var h = this.engine.canvas ? this.engine.canvas.height : 800;
        var btnY = h - 80;
        var b1x = w / 2 - 180, b2x = w / 2 - 40, b3x = w / 2 + 100;
        var bw = 120, bh = 36;

        if (y >= btnY && y <= btnY + bh) {
            if (x >= b1x && x <= b1x + bw) {
                // Scan
                this._scanPlanet();
            } else if (x >= b2x && x <= b2x + bw) {
                // Collect
                this._collectResources();
            } else if (x >= b3x && x <= b3x + bw) {
                // Launch
                this._layer = 'system';
            }
        }
    };

    ExplorerModule.prototype._scanPlanet = function () {
        var p = this._currentPlanet;
        if (!p) return;
        var result = {};
        Object.keys(p.resources).forEach(function (r) {
            result[r] = Math.floor(p.resources[r] * (0.8 + Math.random() * 0.4));
        });
        this._scanResult = result;
    };

    ExplorerModule.prototype._collectResources = function () {
        var p = this._currentPlanet;
        var player = this.config.player;
        if (!p) return;
        if (this._totalCargo() >= player.cargoMax) return;

        Object.keys(p.resources).forEach(function (r) {
            var amt = Math.ceil(p.resources[r] * (0.5 + Math.random() * 0.5));
            player.cargo.push({type: r, amount: amt});
        });

        if (Math.random() < p.hazard) {
            player.health -= Math.floor(p.hazard * 20);
            if (player.health < 0) player.health = 0;
            if (player.health === 0) this._gameOver = true;
        }
    };

    ExplorerModule.prototype._resetGame = function () {
        var fresh = JSON.parse(JSON.stringify(DEFAULT_EXPLORER_CONFIG));
        this.config.player = fresh.player;
        this._layer = 'galaxy';
        this._currentStar = this.config.stars[0];
        this._encounter = null;
        this._gameOver = false;
        this._travelTarget = null;
    };

    // ─── RENDER ──────────────────────────────────────────────────────────────

    ExplorerModule.prototype.render = function (ctx) {
        if (this._gameOver) { this._renderGameOver(ctx); return; }

        if (this._layer === 'galaxy') {
            this._renderGalaxy(ctx);
        } else if (this._layer === 'system') {
            this._renderSystem(ctx);
        } else if (this._layer === 'planet') {
            this._renderPlanet(ctx);
        }

        if (this._encounter) this._renderEncounter(ctx);
    };

    ExplorerModule.prototype._renderGalaxy = function (ctx) {
        var w = ctx.canvas.width, h = ctx.canvas.height;
        var cfg = this.config;
        var player = cfg.player;
        var eng = this.engine;

        // Background
        eng.drawRect(ctx, 0, 0, w, h, '#000');

        // Background stars (twinkle noise)
        for (var i = 0; i < 80; i++) {
            var sx = (i * 137.5) % w;
            var sy = (i * 93.1) % h;
            eng.drawCircle(ctx, sx, sy, 1, '#444');
        }

        var self = this;
        var avg = this._avgStarDistance();
        var fuelRange = (player.fuel / cfg.fuelPerJump) * avg;

        // Fuel range circle (dashed)
        ctx.save();
        ctx.strokeStyle = '#555';
        ctx.setLineDash([6, 4]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(this._currentStar.x, this._currentStar.y, fuelRange, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.restore();

        // Draw connection lines for reachable stars
        cfg.stars.forEach(function (star) {
            if (star === self._currentStar) return;
            var cost = self._fuelCostTo(star);
            if (player.fuel >= cost) {
                ctx.save();
                ctx.strokeStyle = 'rgba(80,120,80,0.3)';
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(self._currentStar.x, self._currentStar.y);
                ctx.lineTo(star.x, star.y);
                ctx.stroke();
                ctx.restore();
            }
        });

        // Draw stars
        cfg.stars.forEach(function (star) {
            var size = star.size || 6;
            // Glow
            ctx.save();
            ctx.shadowColor = star.color;
            ctx.shadowBlur = 10;
            eng.drawCircle(ctx, star.x, star.y, size, star.color);
            ctx.restore();

            // Star name
            ctx.save();
            ctx.fillStyle = '#aaa';
            ctx.font = '10px monospace';
            ctx.textAlign = 'center';
            ctx.fillText(star.name, star.x, star.y + size + 14);
            ctx.restore();
        });

        // Hover tooltip
        if (self._hoverStar && self._hoverStar !== self._currentStar) {
            var hs = self._hoverStar;
            var cost = self._fuelCostTo(hs);
            var affordable = player.fuel >= cost;
            var tipX = hs.x + 12, tipY = hs.y - 14;
            eng.drawRect(ctx, tipX - 4, tipY - 14, 120, 34, 'rgba(0,0,0,0.8)');
            ctx.save();
            ctx.fillStyle = affordable ? '#0f0' : '#f44';
            ctx.font = 'bold 11px monospace';
            ctx.textAlign = 'left';
            ctx.fillText(hs.name, tipX, tipY);
            ctx.fillStyle = '#ccc';
            ctx.font = '10px monospace';
            ctx.fillText('Fuel: ' + cost + (affordable ? '' : ' (not enough)'), tipX, tipY + 14);
            ctx.restore();
        }

        // Player ship (diamond shape)
        var px = player.x, py = player.y;
        ctx.save();
        ctx.fillStyle = '#0f8';
        ctx.beginPath();
        ctx.moveTo(px, py - 8);
        ctx.lineTo(px + 6, py);
        ctx.lineTo(px, py + 8);
        ctx.lineTo(px - 6, py);
        ctx.closePath();
        ctx.fill();
        ctx.restore();

        // HUD
        this._renderHUD(ctx, w, h);
    };

    ExplorerModule.prototype._renderSystem = function (ctx) {
        var w = ctx.canvas.width, h = ctx.canvas.height;
        var eng = this.engine;
        var cfg = this.config;
        var player = cfg.player;
        var star = this._currentStar;
        var cx = w / 2, cy = h / 2;

        // Background
        eng.drawRect(ctx, 0, 0, w, h, '#050510');

        // Background stars
        for (var i = 0; i < 60; i++) {
            var bx = (i * 157.3 + 50) % w;
            var by = (i * 89.7 + 30) % h;
            eng.drawCircle(ctx, bx, by, 1, '#333');
        }

        // Orbit lines
        star.planets.forEach(function (p) {
            ctx.save();
            ctx.strokeStyle = 'rgba(80,80,80,0.4)';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.arc(cx, cy, p.orbitRadius, 0, Math.PI * 2);
            ctx.stroke();
            ctx.restore();
        });

        // Central star glow
        ctx.save();
        ctx.shadowColor = star.color;
        ctx.shadowBlur = 30;
        var starSize = 20 + (star.size || 6);
        eng.drawCircle(ctx, cx, cy, starSize, star.color);
        ctx.restore();

        // Planets
        var self = this;
        star.planets.forEach(function (p) {
            var px = cx + Math.cos(p.angle) * p.orbitRadius;
            var py = cy + Math.sin(p.angle) * p.orbitRadius;
            ctx.save();
            ctx.shadowColor = p.color;
            ctx.shadowBlur = 6;
            eng.drawCircle(ctx, px, py, p.size, p.color);
            ctx.restore();
            ctx.save();
            ctx.fillStyle = '#aaa';
            ctx.font = '9px monospace';
            ctx.textAlign = 'center';
            ctx.fillText(p.name, px, py - p.size - 4);
            ctx.restore();
        });

        // Station
        var station = this._getStationForStar(star.id);
        if (station) {
            var sx = cx + 180, sy = cy - 80;
            ctx.save();
            ctx.fillStyle = '#ff8';
            ctx.beginPath();
            ctx.moveTo(sx, sy - 10);
            ctx.lineTo(sx + 10, sy);
            ctx.lineTo(sx, sy + 10);
            ctx.lineTo(sx - 10, sy);
            ctx.closePath();
            ctx.fill();
            ctx.fillStyle = '#cc8';
            ctx.font = '9px monospace';
            ctx.textAlign = 'center';
            ctx.fillText(station.name, sx, sy + 20);
            ctx.restore();
        }

        // Player ship (triangle)
        var px = player.x, py = player.y;
        ctx.save();
        ctx.fillStyle = '#0f8';
        ctx.beginPath();
        ctx.moveTo(px, py - 10);
        ctx.lineTo(px + 7, py + 7);
        ctx.lineTo(px - 7, py + 7);
        ctx.closePath();
        ctx.fill();
        ctx.restore();

        // Proximity prompt
        if (this._nearPlanet) {
            eng.drawRect(ctx, cx - 100, h - 50, 200, 36, 'rgba(0,40,0,0.8)');
            ctx.save();
            ctx.fillStyle = '#0f0';
            ctx.font = 'bold 12px monospace';
            ctx.textAlign = 'center';
            ctx.fillText('Press E or tap to Land', cx, h - 27);
            ctx.restore();
        } else if (this._nearStation) {
            eng.drawRect(ctx, cx - 100, h - 50, 200, 36, 'rgba(40,30,0,0.8)');
            ctx.save();
            ctx.fillStyle = '#ff8';
            ctx.font = 'bold 12px monospace';
            ctx.textAlign = 'center';
            ctx.fillText('Press E or tap to Dock', cx, h - 27);
            ctx.restore();
        }

        // "Leave System" button
        eng.drawRect(ctx, w - 140, 10, 130, 34, 'rgba(20,40,60,0.9)');
        ctx.save();
        ctx.fillStyle = '#48f';
        ctx.font = '12px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('Leave System', w - 75, 32);
        ctx.restore();

        // System name
        ctx.save();
        ctx.fillStyle = '#8af';
        ctx.font = 'bold 13px monospace';
        ctx.textAlign = 'left';
        ctx.fillText(star.name + ' System', 10, 26);
        ctx.restore();

        this._renderHUD(ctx, w, h);
    };

    ExplorerModule.prototype._renderPlanet = function (ctx) {
        var w = ctx.canvas.width, h = ctx.canvas.height;
        var eng = this.engine;
        var p = this._currentPlanet;
        if (!p) return;

        // Background
        eng.drawRect(ctx, 0, 0, w, h, '#080818');

        // Planet circle
        ctx.save();
        ctx.shadowColor = p.color;
        ctx.shadowBlur = 40;
        eng.drawCircle(ctx, w / 2, h / 3, 100, p.color);
        ctx.restore();

        // Stats panel
        var panelX = w / 2 - 160, panelY = h / 3 + 120;
        eng.drawRect(ctx, panelX, panelY, 320, 130, 'rgba(0,0,0,0.7)');
        ctx.save();
        ctx.fillStyle = '#ccc';
        ctx.font = '13px monospace';
        ctx.textAlign = 'left';
        ctx.fillText('Planet: ' + p.name, panelX + 12, panelY + 22);
        ctx.fillText('Type: ' + p.type, panelX + 12, panelY + 44);
        ctx.fillText('Hazard: ' + (p.hazard * 100).toFixed(0) + '%', panelX + 12, panelY + 66);

        var resText = Object.keys(p.resources).map(function (r) { return r + ': ' + p.resources[r]; }).join(', ');
        ctx.fillText('Resources: ' + resText, panelX + 12, panelY + 88);

        if (this._scanResult) {
            ctx.fillStyle = '#0f8';
            var scanned = Object.keys(this._scanResult).map(function (r) { return r + ': ~' + self._scanResult[r]; }).join(', ');
            ctx.fillText('Scan: ' + scanned, panelX + 12, panelY + 110);
        }
        ctx.restore();

        // Buttons
        var btnY = h - 80;
        var self = this;
        var buttons = [
            {label: 'Scan', x: w / 2 - 180, color: '#48f'},
            {label: 'Collect', x: w / 2 - 40, color: '#4a4'},
            {label: 'Launch', x: w / 2 + 100, color: '#f84'}
        ];
        buttons.forEach(function (btn) {
            eng.drawRect(ctx, btn.x, btnY, 120, 36, btn.color);
            ctx.save();
            ctx.fillStyle = '#fff';
            ctx.font = 'bold 13px monospace';
            ctx.textAlign = 'center';
            ctx.fillText(btn.label, btn.x + 60, btnY + 23);
            ctx.restore();
        });

        this._renderHUD(ctx, w, h);
    };

    ExplorerModule.prototype._renderEncounter = function (ctx) {
        var w = ctx.canvas.width, h = ctx.canvas.height;
        var eng = this.engine;
        var enc = this._encounter;
        var player = this.config.player;
        var cx = w / 2, cy = h / 2;

        // Overlay
        eng.drawRect(ctx, 0, 0, w, h, 'rgba(0,0,0,0.75)');
        eng.drawRect(ctx, cx - 200, cy - 120, 400, 260, 'rgba(20,0,30,0.95)');

        ctx.save();
        ctx.fillStyle = '#f44';
        ctx.font = 'bold 16px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('PIRATE ENCOUNTER!', cx, cy - 96);
        ctx.restore();

        // Player ship (left)
        ctx.save();
        ctx.fillStyle = '#0f8';
        ctx.beginPath();
        ctx.moveTo(cx - 120, cy - 30);
        ctx.lineTo(cx - 90, cy - 50);
        ctx.lineTo(cx - 80, cy - 20);
        ctx.lineTo(cx - 90, cy + 10);
        ctx.lineTo(cx - 120, cy - 10);
        ctx.closePath();
        ctx.fill();
        ctx.restore();

        // Pirate ship (right)
        ctx.save();
        ctx.fillStyle = '#f44';
        ctx.beginPath();
        ctx.moveTo(cx + 120, cy - 30);
        ctx.lineTo(cx + 90, cy - 50);
        ctx.lineTo(cx + 80, cy - 20);
        ctx.lineTo(cx + 90, cy + 10);
        ctx.lineTo(cx + 120, cy - 10);
        ctx.closePath();
        ctx.fill();
        ctx.restore();

        // HP Bars
        eng.drawBar(ctx, cx - 150, cy - 70, 100, 10, player.health / 100, '#0a0', '#200');
        eng.drawBar(ctx, cx + 50, cy - 70, 100, 10, enc.pirateHp / enc.pirateMaxHp, '#a00', '#200');
        ctx.save();
        ctx.fillStyle = '#ccc';
        ctx.font = '10px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('You ' + player.health + 'HP', cx - 100, cy - 58);
        ctx.fillText('Pirate ' + enc.pirateHp + 'HP', cx + 100, cy - 58);
        ctx.fillText('Auto-combat in progress...', cx, cy + 40);
        ctx.restore();

        // Flee button
        eng.drawRect(ctx, cx - 40, cy + 60, 80, 30, '#a40');
        ctx.save();
        ctx.fillStyle = '#fff';
        ctx.font = 'bold 12px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('Flee (5 fuel)', cx, cy + 80);
        ctx.restore();
    };

    ExplorerModule.prototype._renderHUD = function (ctx, w, h) {
        var p = this.config.player;
        var eng = this.engine;

        // Fuel bar
        eng.drawRect(ctx, 10, 10, 120, 14, 'rgba(0,0,0,0.6)');
        eng.drawBar(ctx, 10, 10, 120, 14, p.fuel / p.maxFuel, '#0a8', '#200');
        ctx.save();
        ctx.fillStyle = '#ccc';
        ctx.font = '10px monospace';
        ctx.textAlign = 'left';
        ctx.fillText('Fuel: ' + Math.floor(p.fuel) + '/' + p.maxFuel, 14, 22);
        ctx.restore();

        // Health bar
        eng.drawRect(ctx, 10, 28, 120, 10, 'rgba(0,0,0,0.6)');
        eng.drawBar(ctx, 10, 28, 120, 10, p.health / 100, '#f44', '#400');
        ctx.save();
        ctx.fillStyle = '#ccc';
        ctx.font = '10px monospace';
        ctx.textAlign = 'left';
        ctx.fillText('HP: ' + p.health, 14, 37);
        ctx.restore();

        // Credits
        ctx.save();
        ctx.fillStyle = '#ff8';
        ctx.font = '11px monospace';
        ctx.textAlign = 'left';
        ctx.fillText('Credits: ' + p.credits, 10, 54);
        ctx.restore();

        // Cargo
        ctx.save();
        ctx.fillStyle = '#8cf';
        ctx.font = '11px monospace';
        ctx.textAlign = 'left';
        ctx.fillText('Cargo: ' + this._totalCargo() + '/' + p.cargoMax, 10, 69);
        ctx.restore();
    };

    ExplorerModule.prototype._renderGameOver = function (ctx) {
        var w = ctx.canvas.width, h = ctx.canvas.height;
        var eng = this.engine;
        var cx = w / 2, cy = h / 2;

        eng.drawRect(ctx, 0, 0, w, h, '#000');
        ctx.save();
        ctx.fillStyle = '#f44';
        ctx.font = 'bold 32px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('SHIP DESTROYED', cx, cy - 30);
        ctx.fillStyle = '#888';
        ctx.font = '14px monospace';
        ctx.fillText('Tap or click to try again', cx, cy + 20);
        ctx.restore();
    };

    // ─── ENTITY INTERFACE ────────────────────────────────────────────────────

    ExplorerModule.prototype.getEntities = function () {
        if (this._layer === 'galaxy') {
            return this.config.stars.map(function (s) {
                return {id: s.id, type: 'star', x: s.x, y: s.y, name: s.name};
            });
        } else if (this._layer === 'system' && this._currentStar) {
            return this._currentStar.planets.map(function (p, i) {
                return {id: p.name, type: 'planet', orbitRadius: p.orbitRadius, index: i};
            });
        }
        return [];
    };

    ExplorerModule.prototype.addEntity = function (type, x, y) {
        if (type === 'star') {
            var newStar = {
                id: 'star_' + Date.now(),
                name: 'New Star',
                x: x, y: y,
                type: 'yellow', color: '#ff0', size: 6,
                planets: [
                    {name: 'Planet I', orbitRadius: 60, size: 8, color: '#888', type: 'rocky', resources: {minerals: 5}, hazard: 0.3, angle: 0}
                ]
            };
            this.config.stars.push(newStar);
            return newStar.id;
        } else if (type === 'planet' && this._currentStar) {
            var cx = this.engine.canvas ? this.engine.canvas.width / 2 : 500;
            var cy = this.engine.canvas ? this.engine.canvas.height / 2 : 400;
            var dx = x - cx, dy = y - cy;
            var orbitRadius = Math.sqrt(dx * dx + dy * dy);
            var newPlanet = {
                name: 'Planet ' + (this._currentStar.planets.length + 1),
                orbitRadius: Math.round(orbitRadius),
                size: 8, color: '#888', type: 'rocky',
                resources: {minerals: 5}, hazard: 0.3, angle: Math.atan2(dy, dx)
            };
            this._currentStar.planets.push(newPlanet);
            return newPlanet.name;
        }
        return null;
    };

    ExplorerModule.prototype.removeEntity = function (id) {
        var stars = this.config.stars;
        for (var i = 0; i < stars.length; i++) {
            if (stars[i].id === id) { stars.splice(i, 1); return; }
            var planets = stars[i].planets;
            for (var j = 0; j < planets.length; j++) {
                if (planets[j].name === id) { planets.splice(j, 1); return; }
            }
        }
    };

    ExplorerModule.prototype.moveEntity = function (id, x, y) {
        var stars = this.config.stars;
        for (var i = 0; i < stars.length; i++) {
            if (stars[i].id === id) { stars[i].x = x; stars[i].y = y; return; }
        }
    };

    ExplorerModule.prototype.getConfig = function () {
        return JSON.parse(JSON.stringify(this.config));
    };

    // ─── REGISTRATION ────────────────────────────────────────────────────────

    if (typeof GameEngine !== 'undefined' && GameEngine.registerModuleType) {
        GameEngine.registerModuleType('space_explorer', ExplorerModule);
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {ExplorerModule: ExplorerModule, DEFAULT_EXPLORER_CONFIG: DEFAULT_EXPLORER_CONFIG};
    } else if (typeof window !== 'undefined') {
        window.ExplorerModule = ExplorerModule;
        window.DEFAULT_EXPLORER_CONFIG = DEFAULT_EXPLORER_CONFIG;
    }

}());
