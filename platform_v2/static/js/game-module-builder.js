/**
 * game-module-builder.js — Base Builder Module (Game Studio Phase 2, Task 3)
 * Grid-based colony management: buildings, colonists, resources, raids
 * Runs inside iframe alongside game-engine.js
 */

(function () {
    'use strict';

    // ── Constants ──────────────────────────────────────────────────────────────

    var CELL = 32;

    var TERRAIN = { GRASS: 0, ROCK: 1, WATER: 2, SAND: 3, TREE: 4 };
    var TERRAIN_COLORS = { 0: '#3a5', 1: '#776', 2: '#36a', 3: '#ca8', 4: '#274' };

    var BUILDING_DEFS = {
        shelter:  { color: '#88f', letter: 'S', cost: { wood: 20, stone: 10 }, capacity: 4, hp: 100 },
        farm:     { color: '#6b4', letter: 'F', cost: { wood: 10 }, produces: 'food', rate: 2, hp: 60 },
        workshop: { color: '#a86', letter: 'W', cost: { wood: 15, stone: 15 }, hp: 80 },
        storage:  { color: '#aa6', letter: 'T', cost: { wood: 25 }, extraCap: 50, hp: 70 },
        wall:     { color: '#555', letter: '#', cost: { stone: 5 }, hp: 50 },
        turret:   { color: '#f44', letter: '!', cost: { metal: 10, wood: 5 }, hp: 30, range: 5, damage: 5 },
        well:     { color: '#4af', letter: '~', cost: { stone: 15 }, hp: 80 },
    };

    var COLONIST_NAMES = [
        'Alex', 'Sam', 'Jordan', 'Taylor', 'Morgan', 'Casey', 'Drew', 'Quinn',
        'Reese', 'Avery', 'Blake', 'Charlie', 'Finley', 'Harper', 'Logan'
    ];

    var DEFAULT_BUILDER_CONFIG = {
        type: 'base_builder',
        map: { width: 40, height: 30, cellSize: 32 },
        terrain: [],
        buildings: [{ type: 'shelter', gridX: 20, gridY: 15, hp: 100, id: 'b_1' }],
        colonists: [
            { id: 'c_1', name: 'Alex',   gridX: 21, gridY: 15, task: 'idle', health: 100 },
            { id: 'c_2', name: 'Sam',    gridX: 19, gridY: 15, task: 'idle', health: 100 },
            { id: 'c_3', name: 'Jordan', gridX: 20, gridY: 16, task: 'idle', health: 100 },
        ],
        resources: { wood: 50, stone: 30, metal: 10, food: 20 },
        resourceNodes: [],
        threats: { raidInterval: 8, raidSize: 3, raidScaling: 1.2 },
        cycle: 0,
        cycleLength: 60,
    };

    // ── Helpers ────────────────────────────────────────────────────────────────

    var _nextId = 1000;
    function uid(prefix) { return (prefix || 'e') + '_' + (++_nextId); }

    function rnd(min, max) { return Math.floor(Math.random() * (max - min + 1)) + min; }

    function manhattan(ax, ay, bx, by) { return Math.abs(ax - bx) + Math.abs(ay - by); }

    function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

    function randName() {
        return COLONIST_NAMES[rnd(0, COLONIST_NAMES.length - 1)];
    }

    // ── BFS Pathfinding ────────────────────────────────────────────────────────

    function bfs(terrain, buildings, startX, startY, targetX, targetY, mapW, mapH) {
        if (startX === targetX && startY === targetY) return null;

        // Build obstacle set (skip target cell)
        var obstacles = {};
        for (var i = 0; i < buildings.length; i++) {
            var b = buildings[i];
            if (b.gridX === targetX && b.gridY === targetY) continue;
            obstacles[b.gridX + ',' + b.gridY] = true;
        }

        var queue = [{ x: startX, y: startY, path: [] }];
        var visited = {};
        visited[startX + ',' + startY] = true;
        var dirs = [[0, -1], [0, 1], [-1, 0], [1, 0]];
        var iters = 0;

        while (queue.length > 0 && iters < 200) {
            iters++;
            var cur = queue.shift();
            for (var d = 0; d < dirs.length; d++) {
                var nx = cur.x + dirs[d][0];
                var ny = cur.y + dirs[d][1];
                if (nx < 0 || ny < 0 || nx >= mapW || ny >= mapH) continue;
                var key = nx + ',' + ny;
                if (visited[key]) continue;
                var t = terrain[ny] && terrain[ny][nx];
                if (t === TERRAIN.WATER || t === TERRAIN.ROCK) continue;
                if (obstacles[key]) continue;
                visited[key] = true;
                var newPath = cur.path.concat([{ x: nx, y: ny }]);
                if (nx === targetX && ny === targetY) {
                    return newPath.length > 0 ? newPath[0] : null;
                }
                queue.push({ x: nx, y: ny, path: newPath });
            }
        }
        return null;
    }

    // ── BuilderModule ──────────────────────────────────────────────────────────

    function BuilderModule() {
        this.engine       = null;
        this.config       = null;
        this.terrain      = [];
        this.buildings    = [];
        this.colonists    = [];
        this.resourceNodes = [];
        this.resources    = {};
        this.threats      = {};
        this.raiders      = [];
        this.cycle        = 0;
        this.cycleLength  = 60;
        this._cycleTimer  = 0;
        this._camX        = 0;
        this._camY        = 0;
        this._zoom        = 1;
        this._selectedCell = null;
        this._buildMode   = null; // building type to place on click
        this._mapW        = 40;
        this._mapH        = 30;
        this._keys        = {};
        this._touchStart  = null;
        this._panDrag     = null;
        this._boundKeyDown = null;
        this._boundKeyUp   = null;
    }

    BuilderModule.prototype.init = function (engine, config) {
        this.engine = engine;
        var cfg = Object.assign({}, DEFAULT_BUILDER_CONFIG, config || {});
        this.config       = cfg;
        this._mapW        = cfg.map.width  || 40;
        this._mapH        = cfg.map.height || 30;
        this.cycleLength  = cfg.cycleLength || 60;
        this.cycle        = cfg.cycle || 0;
        this._cycleTimer  = 0;
        this.resources    = Object.assign({ wood: 50, stone: 30, metal: 10, food: 20 }, cfg.resources);
        this.threats      = Object.assign({ raidInterval: 8, raidSize: 3, raidScaling: 1.2 }, cfg.threats);
        this.raiders      = [];

        // Deep-clone arrays
        this.buildings     = (cfg.buildings || []).map(function (b) {
            var def = BUILDING_DEFS[b.type] || {};
            return Object.assign({ id: uid('b'), hp: def.hp || 100, maxHp: def.hp || 100 }, b);
        });
        this.colonists     = (cfg.colonists || []).map(function (c) {
            return Object.assign({ id: uid('c'), task: 'idle', health: 100, _moveTimer: 0, _gatherTimer: 0, _pathTarget: null }, c);
        });
        this.resourceNodes = (cfg.resourceNodes || []).map(function (n) {
            return Object.assign({ id: uid('n'), amount: 20 }, n);
        });

        // Generate terrain if not provided
        if (!cfg.terrain || cfg.terrain.length === 0) {
            this._generateTerrain();
        } else {
            this.terrain = cfg.terrain;
        }

        // Generate resource nodes if none
        if (this.resourceNodes.length === 0) {
            this._generateResourceNodes();
        }

        // Center camera on map
        this._camX = (this._mapW * CELL) / 2;
        this._camY = (this._mapH * CELL) / 2;

        // Assign colonist tasks
        this._assignColonistTasks();

        // Keyboard listeners
        var self = this;
        this._boundKeyDown = function (e) { self._keys[e.key] = true; };
        this._boundKeyUp   = function (e) { self._keys[e.key] = false; };
        window.addEventListener('keydown', this._boundKeyDown);
        window.addEventListener('keyup',   this._boundKeyUp);

        // Canvas input
        var canvas = engine.canvas || (engine.getCanvas && engine.getCanvas());
        if (canvas) {
            canvas.addEventListener('click',      function (e) { self._onClick(e); });
            canvas.addEventListener('wheel',      function (e) { self._onWheel(e); });
            canvas.addEventListener('touchstart', function (e) { self._onTouchStart(e); });
            canvas.addEventListener('touchmove',  function (e) { self._onTouchMove(e); });
            canvas.addEventListener('touchend',   function (e) { self._onTouchEnd(e); });
        }
    };

    BuilderModule.prototype._generateTerrain = function () {
        var w = this._mapW, h = this._mapH;
        this.terrain = [];
        for (var y = 0; y < h; y++) {
            this.terrain[y] = [];
            for (var x = 0; x < w; x++) {
                // Borders: trees
                if (x === 0 || y === 0 || x === w - 1 || y === h - 1) {
                    this.terrain[y][x] = TERRAIN.TREE;
                } else if (x < 3 || y < 3 || x > w - 4 || y > h - 4) {
                    this.terrain[y][x] = Math.random() < 0.5 ? TERRAIN.TREE : TERRAIN.GRASS;
                } else {
                    this.terrain[y][x] = TERRAIN.GRASS;
                }
            }
        }
        // Scatter rocks
        for (var r = 0; r < 20; r++) {
            var rx = rnd(5, w - 6), ry = rnd(5, h - 6);
            this.terrain[ry][rx] = TERRAIN.ROCK;
        }
        // 2-3 water patches
        var waterCount = rnd(2, 3);
        for (var wc = 0; wc < waterCount; wc++) {
            var wx = rnd(6, w - 7), wy = rnd(6, h - 7);
            for (var dy = -1; dy <= 1; dy++) {
                for (var dx = -1; dx <= 1; dx++) {
                    if (wy + dy >= 0 && wx + dx >= 0) {
                        this.terrain[wy + dy][wx + dx] = TERRAIN.WATER;
                    }
                }
            }
        }
        // Sand patches
        for (var sc = 0; sc < 8; sc++) {
            var sx = rnd(4, w - 5), sy = rnd(4, h - 5);
            this.terrain[sy][sx] = TERRAIN.SAND;
        }
    };

    BuilderModule.prototype._generateResourceNodes = function () {
        var w = this._mapW, h = this._mapH;
        this.resourceNodes = [];
        // Trees on outer band
        for (var i = 0; i < 25; i++) {
            var tx = rnd(1, w - 2), ty = rnd(1, h - 2);
            if (this.terrain[ty] && this.terrain[ty][tx] === TERRAIN.TREE) {
                this.resourceNodes.push({ id: uid('n'), type: 'tree', gridX: tx, gridY: ty, amount: rnd(15, 30), maxAmount: 30 });
            }
        }
        // Rocks scattered
        for (var j = 0; j < 12; j++) {
            var rx = rnd(3, w - 4), ry = rnd(3, h - 4);
            if (this.terrain[ry] && this.terrain[ry][rx] === TERRAIN.ROCK) {
                this.resourceNodes.push({ id: uid('n'), type: 'rock', gridX: rx, gridY: ry, amount: rnd(20, 40), maxAmount: 40 });
            }
        }
        // 2-3 ore deposits
        var oreCount = rnd(2, 3);
        for (var k = 0; k < oreCount; k++) {
            var ox = rnd(8, w - 9), oy = rnd(8, h - 9);
            this.resourceNodes.push({ id: uid('n'), type: 'ore', gridX: ox, gridY: oy, amount: rnd(25, 50), maxAmount: 50 });
        }
    };

    BuilderModule.prototype._assignColonistTasks = function () {
        var nodes = this.resourceNodes.filter(function (n) { return n.amount > 0; });
        this.colonists.forEach(function (c, i) {
            c.task = nodes.length > 0 ? 'gather' : 'idle';
            c._moveTimer = 0;
            c._gatherTimer = 0;
            c._pathTarget = null;
            c.gridX = c.gridX || 20;
            c.gridY = c.gridY || 15;
            c.fx = c.gridX; // float positions for smooth movement
            c.fy = c.gridY;
        });
    };

    // ── Update ─────────────────────────────────────────────────────────────────

    BuilderModule.prototype.update = function (engine, dt) {
        this._handleCamera(engine, dt);
        this._updateCycle(dt);
        this._updateColonists(dt);
        this._updateRaiders(dt);
        this._updateTurrets(dt);
    };

    BuilderModule.prototype._handleCamera = function (engine, dt) {
        var speed = 200 * dt;
        if (this._keys['w'] || this._keys['W'] || this._keys['ArrowUp'])    this._camY -= speed;
        if (this._keys['s'] || this._keys['S'] || this._keys['ArrowDown'])  this._camY += speed;
        if (this._keys['a'] || this._keys['A'] || this._keys['ArrowLeft'])  this._camX -= speed;
        if (this._keys['d'] || this._keys['D'] || this._keys['ArrowRight']) this._camX += speed;

        var maxX = this._mapW * CELL;
        var maxY = this._mapH * CELL;
        this._camX = clamp(this._camX, 0, maxX);
        this._camY = clamp(this._camY, 0, maxY);

        if (engine.camera) {
            engine.camera.x = this._camX;
            engine.camera.y = this._camY;
        }
    };

    BuilderModule.prototype._updateCycle = function (dt) {
        this._cycleTimer += dt;
        if (this._cycleTimer >= this.cycleLength) {
            this._cycleTimer -= this.cycleLength;
            this.cycle++;
            this._onCycleTick();
        }
    };

    BuilderModule.prototype._onCycleTick = function () {
        var self = this;
        // Farm production: adjacent water or well → produce food
        this.buildings.forEach(function (b) {
            if (b.type !== 'farm') return;
            var adjacent = [[0,-1],[0,1],[-1,0],[1,0]];
            var hasWater = adjacent.some(function (d) {
                var nx = b.gridX + d[0], ny = b.gridY + d[1];
                var t = self.terrain[ny] && self.terrain[ny][nx];
                return t === TERRAIN.WATER;
            });
            var hasWell = adjacent.some(function (d) {
                return self.buildings.some(function (wb) {
                    return wb.type === 'well' && wb.gridX === b.gridX + d[0] && wb.gridY === b.gridY + d[1];
                });
            });
            if (hasWater || hasWell) {
                var def = BUILDING_DEFS['farm'];
                self.resources.food = (self.resources.food || 0) + (def.rate || 2);
            }
        });

        // Colonist arrival: shelter with space + food
        var shelters = this.buildings.filter(function (b) { return b.type === 'shelter'; });
        shelters.forEach(function (s) {
            var occupants = self.colonists.filter(function (c) {
                return c.gridX === s.gridX && c.gridY === s.gridY;
            }).length;
            var cap = BUILDING_DEFS.shelter.capacity || 4;
            if (occupants < cap && self.resources.food > 10) {
                self.resources.food -= 5;
                self.colonists.push({
                    id: uid('c'), name: randName(),
                    gridX: s.gridX, gridY: s.gridY,
                    fx: s.gridX, fy: s.gridY,
                    task: 'idle', health: 100,
                    _moveTimer: 0, _gatherTimer: 0, _pathTarget: null
                });
            }
        });

        // Threat check
        if (this.cycle % this.threats.raidInterval === 0) {
            this._spawnRaiders();
        }

        // Re-assign idle colonists
        this._assignColonistTasks();
    };

    BuilderModule.prototype._spawnRaiders = function () {
        var size = Math.ceil(this.threats.raidSize * Math.pow(this.threats.raidScaling || 1.2, Math.floor(this.cycle / this.threats.raidInterval)));
        var raiderHp = 30 + this.cycle * 2;
        for (var i = 0; i < size; i++) {
            var edge = rnd(0, 3);
            var gx, gy;
            if (edge === 0) { gx = rnd(0, this._mapW - 1); gy = 0; }
            else if (edge === 1) { gx = rnd(0, this._mapW - 1); gy = this._mapH - 1; }
            else if (edge === 2) { gx = 0; gy = rnd(0, this._mapH - 1); }
            else { gx = this._mapW - 1; gy = rnd(0, this._mapH - 1); }
            this.raiders.push({
                id: uid('r'), gridX: gx, gridY: gy,
                fx: gx, fy: gy,
                hp: raiderHp, maxHp: raiderHp,
                _moveTimer: 0
            });
        }
    };

    BuilderModule.prototype._updateColonists = function (dt) {
        var self = this;
        var hasRaiders = this.raiders.length > 0;

        this.colonists.forEach(function (c) {
            if (c.health <= 0) return;
            c._moveTimer = (c._moveTimer || 0) + dt;

            if (hasRaiders) {
                // Flee to nearest shelter
                c.task = 'flee';
                if (c._moveTimer >= 0.5) {
                    c._moveTimer = 0;
                    var shelter = self._nearestBuilding(c.gridX, c.gridY, 'shelter');
                    if (shelter && (c.gridX !== shelter.gridX || c.gridY !== shelter.gridY)) {
                        var next = bfs(self.terrain, self.buildings, c.gridX, c.gridY, shelter.gridX, shelter.gridY, self._mapW, self._mapH);
                        if (next) { c.gridX = next.x; c.gridY = next.y; }
                    }
                }
                return;
            }

            // Assign gather if nodes available
            if (c.task === 'idle') {
                var nodes = self.resourceNodes.filter(function (n) { return n.amount > 0; });
                if (nodes.length > 0) c.task = 'gather';
            }

            if (c.task === 'gather') {
                // Find adjacent resource node
                var adjNode = self._adjacentResourceNode(c.gridX, c.gridY);
                if (adjNode) {
                    c._gatherTimer = (c._gatherTimer || 0) + dt;
                    if (c._gatherTimer >= 1.0) {
                        c._gatherTimer = 0;
                        var yield_ = Math.min(1, adjNode.amount);
                        adjNode.amount -= yield_;
                        var resType = adjNode.type === 'tree' ? 'wood' : adjNode.type === 'ore' ? 'metal' : 'stone';
                        self.resources[resType] = (self.resources[resType] || 0) + yield_;
                        if (adjNode.amount <= 0) {
                            c._pathTarget = null;
                            c.task = 'idle';
                        }
                    }
                } else {
                    // Move toward nearest resource node
                    if (c._moveTimer >= 0.5) {
                        c._moveTimer = 0;
                        var activeNodes = self.resourceNodes.filter(function (n) { return n.amount > 0; });
                        if (activeNodes.length === 0) { c.task = 'idle'; return; }
                        var nearest = self._nearestNode(c.gridX, c.gridY, activeNodes);
                        if (nearest) {
                            var step = bfs(self.terrain, self.buildings, c.gridX, c.gridY, nearest.gridX, nearest.gridY, self._mapW, self._mapH);
                            if (step) { c.gridX = step.x; c.gridY = step.y; }
                        }
                    }
                }
            }
        });

        // Remove depleted nodes
        this.resourceNodes = this.resourceNodes.filter(function (n) { return n.amount > 0; });
    };

    BuilderModule.prototype._updateRaiders = function (dt) {
        var self = this;
        var toRemove = [];

        this.raiders.forEach(function (r) {
            r._moveTimer = (r._moveTimer || 0) + dt;
            // Find nearest building
            var target = self._nearestBuilding(r.gridX, r.gridY, null);
            if (!target) return;

            if (r.gridX === target.gridX && r.gridY === target.gridY) {
                // Attack building
                target.hp -= 5 * dt;
                if (target.hp <= 0) {
                    self.buildings = self.buildings.filter(function (b) { return b !== target; });
                }
            } else if (r._moveTimer >= 1.0) {
                r._moveTimer = 0;
                var step = bfs(self.terrain, [], r.gridX, r.gridY, target.gridX, target.gridY, self._mapW, self._mapH);
                if (step) { r.gridX = step.x; r.gridY = step.y; }
            }

            if (r.hp <= 0) toRemove.push(r.id);
        });

        this.raiders = this.raiders.filter(function (r) { return toRemove.indexOf(r.id) === -1; });
    };

    BuilderModule.prototype._updateTurrets = function (dt) {
        var self = this;
        var turrets = this.buildings.filter(function (b) { return b.type === 'turret' && b.hp > 0; });
        turrets.forEach(function (t) {
            var def = BUILDING_DEFS.turret;
            self.raiders.forEach(function (r) {
                if (manhattan(t.gridX, t.gridY, r.gridX, r.gridY) <= def.range) {
                    r.hp -= def.damage * dt;
                }
            });
        });
    };

    // ── Helpers ────────────────────────────────────────────────────────────────

    BuilderModule.prototype._nearestBuilding = function (x, y, type) {
        var best = null, bestDist = Infinity;
        this.buildings.forEach(function (b) {
            if (type && b.type !== type) return;
            if (b.hp <= 0) return;
            var d = manhattan(x, y, b.gridX, b.gridY);
            if (d < bestDist) { bestDist = d; best = b; }
        });
        return best;
    };

    BuilderModule.prototype._nearestNode = function (x, y, nodes) {
        var best = null, bestDist = Infinity;
        nodes.forEach(function (n) {
            var d = manhattan(x, y, n.gridX, n.gridY);
            if (d < bestDist) { bestDist = d; best = n; }
        });
        return best;
    };

    BuilderModule.prototype._adjacentResourceNode = function (x, y) {
        var dirs = [[0, 0], [0, -1], [0, 1], [-1, 0], [1, 0]];
        for (var i = 0; i < dirs.length; i++) {
            var nx = x + dirs[i][0], ny = y + dirs[i][1];
            for (var j = 0; j < this.resourceNodes.length; j++) {
                var n = this.resourceNodes[j];
                if (n.gridX === nx && n.gridY === ny && n.amount > 0) return n;
            }
        }
        return null;
    };

    BuilderModule.prototype._cellOccupied = function (gx, gy) {
        return this.buildings.some(function (b) { return b.gridX === gx && b.gridY === gy; });
    };

    BuilderModule.prototype.placeBuilding = function (type, gx, gy) {
        var def = BUILDING_DEFS[type];
        if (!def) return false;
        var t = this.terrain[gy] && this.terrain[gy][gx];
        if (t !== TERRAIN.GRASS && t !== TERRAIN.SAND) return false;
        if (this._cellOccupied(gx, gy)) return false;
        // Check resources
        var cost = def.cost || {};
        for (var res in cost) {
            if ((this.resources[res] || 0) < cost[res]) return false;
        }
        // Deduct
        for (var res2 in cost) { this.resources[res2] -= cost[res2]; }
        this.buildings.push({
            id: uid('b'), type: type,
            gridX: gx, gridY: gy,
            hp: def.hp || 100, maxHp: def.hp || 100
        });
        return true;
    };

    // ── Render ─────────────────────────────────────────────────────────────────

    BuilderModule.prototype.render = function (engine, ctx) {
        if (!ctx) return;
        var w = ctx.canvas ? ctx.canvas.width  : 800;
        var h = ctx.canvas ? ctx.canvas.height : 600;

        ctx.save();

        // Camera translation
        var offX = w / 2 - this._camX;
        var offY = h / 2 - this._camY;
        ctx.translate(offX, offY);

        // Visible cell range
        var startX = Math.max(0, Math.floor((this._camX - w / 2) / CELL));
        var startY = Math.max(0, Math.floor((this._camY - h / 2) / CELL));
        var endX   = Math.min(this._mapW - 1, Math.ceil((this._camX + w / 2) / CELL));
        var endY   = Math.min(this._mapH - 1, Math.ceil((this._camY + h / 2) / CELL));

        // 1. Draw terrain
        for (var ty = startY; ty <= endY; ty++) {
            for (var tx = startX; tx <= endX; tx++) {
                var tval = this.terrain[ty] ? this.terrain[ty][tx] : TERRAIN.GRASS;
                ctx.fillStyle = TERRAIN_COLORS[tval] || '#3a5';
                ctx.fillRect(tx * CELL, ty * CELL, CELL, CELL);
                // Grid lines (subtle)
                ctx.strokeStyle = 'rgba(0,0,0,0.08)';
                ctx.lineWidth = 0.5;
                ctx.strokeRect(tx * CELL, ty * CELL, CELL, CELL);
            }
        }

        // 2. Draw resource nodes
        this.resourceNodes.forEach(function (n) {
            var px = n.gridX * CELL + CELL / 2;
            var py = n.gridY * CELL + CELL / 2;
            if (n.type === 'tree') {
                // Green triangle
                ctx.fillStyle = '#2a7';
                ctx.beginPath();
                ctx.moveTo(px, py - 10);
                ctx.lineTo(px - 8, py + 8);
                ctx.lineTo(px + 8, py + 8);
                ctx.closePath();
                ctx.fill();
            } else if (n.type === 'rock') {
                // Grey diamond
                ctx.fillStyle = '#999';
                ctx.beginPath();
                ctx.moveTo(px, py - 10);
                ctx.lineTo(px + 10, py);
                ctx.lineTo(px, py + 10);
                ctx.lineTo(px - 10, py);
                ctx.closePath();
                ctx.fill();
            } else if (n.type === 'ore') {
                // Brown circle
                ctx.fillStyle = '#8b4513';
                ctx.beginPath();
                ctx.arc(px, py, 9, 0, Math.PI * 2);
                ctx.fill();
                ctx.fillStyle = '#c87941';
                ctx.beginPath();
                ctx.arc(px - 2, py - 2, 4, 0, Math.PI * 2);
                ctx.fill();
            }
        });

        // 3. Draw buildings
        this.buildings.forEach(function (b) {
            var def = BUILDING_DEFS[b.type] || {};
            var px = b.gridX * CELL;
            var py = b.gridY * CELL;
            ctx.fillStyle = def.color || '#888';
            ctx.fillRect(px + 2, py + 2, CELL - 4, CELL - 4);
            // Letter
            ctx.fillStyle = '#fff';
            ctx.font = 'bold 14px monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(def.letter || '?', px + CELL / 2, py + CELL / 2);
            // HP bar if damaged
            if (b.hp < (b.maxHp || 100)) {
                var barW = CELL - 4;
                var hpPct = b.hp / (b.maxHp || 100);
                ctx.fillStyle = '#300';
                ctx.fillRect(px + 2, py - 6, barW, 4);
                ctx.fillStyle = hpPct > 0.5 ? '#0f0' : hpPct > 0.25 ? '#ff0' : '#f00';
                ctx.fillRect(px + 2, py - 6, barW * hpPct, 4);
            }
        });

        // 4. Draw colonists
        this.colonists.forEach(function (c) {
            if (c.health <= 0) return;
            var px = c.gridX * CELL + CELL / 2;
            var py = c.gridY * CELL + CELL / 2;
            ctx.fillStyle = '#fff';
            ctx.beginPath();
            ctx.arc(px, py, 6, 0, Math.PI * 2);
            ctx.fill();
            // Task color dot
            ctx.fillStyle = c.task === 'gather' ? '#0f0' : c.task === 'flee' ? '#f00' : '#00f';
            ctx.beginPath();
            ctx.arc(px + 3, py - 3, 3, 0, Math.PI * 2);
            ctx.fill();
        });

        // 5. Draw raiders
        this.raiders.forEach(function (r) {
            var px = r.gridX * CELL + CELL / 2;
            var py = r.gridY * CELL + CELL / 2;
            ctx.fillStyle = '#f44';
            ctx.beginPath();
            ctx.arc(px, py, 7, 0, Math.PI * 2);
            ctx.fill();
            // X mark
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(px - 4, py - 4); ctx.lineTo(px + 4, py + 4);
            ctx.moveTo(px + 4, py - 4); ctx.lineTo(px - 4, py + 4);
            ctx.stroke();
        });

        // 6. Selection highlight
        if (this._selectedCell) {
            var sx = this._selectedCell.x * CELL;
            var sy = this._selectedCell.y * CELL;
            ctx.strokeStyle = '#4af';
            ctx.lineWidth = 2;
            ctx.strokeRect(sx + 1, sy + 1, CELL - 2, CELL - 2);
        }

        // 7. Day/night overlay
        var nightPhase = Math.abs(Math.sin(Math.PI * this._cycleTimer / this.cycleLength));
        ctx.fillStyle = 'rgba(0,0,30,' + (0.3 * nightPhase) + ')';
        ctx.fillRect(startX * CELL, startY * CELL, (endX - startX + 1) * CELL, (endY - startY + 1) * CELL);

        ctx.restore();

        // 8. HUD (screen-space, no transform)
        this._renderHUD(ctx, w, h);
    };

    BuilderModule.prototype._renderHUD = function (ctx, w, h) {
        // Resource bar background
        ctx.fillStyle = 'rgba(0,0,0,0.6)';
        ctx.fillRect(0, 0, w, 36);

        ctx.font = '13px monospace';
        ctx.textBaseline = 'middle';
        ctx.textAlign = 'left';
        var res = this.resources;
        var labels = [
            { icon: '🪵', key: 'wood',  x: 10 },
            { icon: '🪨', key: 'stone', x: 100 },
            { icon: '⚙',  key: 'metal', x: 190 },
            { icon: '🌾', key: 'food',  x: 280 },
        ];
        labels.forEach(function (l) {
            ctx.fillStyle = '#fff';
            ctx.fillText(l.icon + ' ' + Math.floor(res[l.key] || 0), l.x, 18);
        });

        // Cycle info
        ctx.textAlign = 'right';
        ctx.fillStyle = '#adf';
        var nextRaid = (this.threats.raidInterval - (this.cycle % this.threats.raidInterval)) + ' cycles';
        if (this.cycle % this.threats.raidInterval === 0 && this.cycle > 0) nextRaid = 'RAID!';
        ctx.fillText('Cycle: ' + this.cycle + '  Colonists: ' + this.colonists.length + '  Next Raid: ' + nextRaid, w - 10, 18);

        // Build mode indicator
        if (this._buildMode) {
            ctx.fillStyle = 'rgba(0,0,0,0.6)';
            ctx.fillRect(0, h - 30, w, 30);
            ctx.textAlign = 'center';
            ctx.fillStyle = '#ff0';
            ctx.fillText('Build Mode: ' + this._buildMode + '  (click to place, Esc to cancel)', w / 2, h - 15);
        }
    };

    // ── Input Handlers ─────────────────────────────────────────────────────────

    BuilderModule.prototype._screenToGrid = function (screenX, screenY, canvasW, canvasH) {
        var worldX = screenX - (canvasW / 2 - this._camX);
        var worldY = screenY - (canvasH / 2 - this._camY);
        return {
            x: Math.floor(worldX / CELL),
            y: Math.floor(worldY / CELL),
        };
    };

    BuilderModule.prototype._onClick = function (e) {
        var canvas = e.target;
        var rect   = canvas.getBoundingClientRect();
        var scaleX = canvas.width  / rect.width;
        var scaleY = canvas.height / rect.height;
        var sx = (e.clientX - rect.left) * scaleX;
        var sy = (e.clientY - rect.top)  * scaleY;
        var cell = this._screenToGrid(sx, sy, canvas.width, canvas.height);

        if (cell.x < 0 || cell.y < 0 || cell.x >= this._mapW || cell.y >= this._mapH) return;

        if (this._buildMode) {
            this.placeBuilding(this._buildMode, cell.x, cell.y);
            this._buildMode = null;
        } else {
            this._selectedCell = cell;
        }
    };

    BuilderModule.prototype._onWheel = function (e) {
        e.preventDefault();
        // Optional zoom (Phase 2: simple)
        this._zoom = clamp(this._zoom - e.deltaY * 0.001, 0.5, 2.0);
    };

    BuilderModule.prototype._onTouchStart = function (e) {
        if (e.touches.length === 1) {
            this._touchStart = { x: e.touches[0].clientX, y: e.touches[0].clientY };
            this._panDrag    = { camX: this._camX, camY: this._camY };
        }
    };

    BuilderModule.prototype._onTouchMove = function (e) {
        if (e.touches.length === 1 && this._panDrag) {
            var dx = e.touches[0].clientX - this._touchStart.x;
            var dy = e.touches[0].clientY - this._touchStart.y;
            this._camX = clamp(this._panDrag.camX - dx, 0, this._mapW * CELL);
            this._camY = clamp(this._panDrag.camY - dy, 0, this._mapH * CELL);
        }
    };

    BuilderModule.prototype._onTouchEnd = function (e) {
        // If short tap (not drag), treat as click
        if (this._touchStart) {
            var endX = e.changedTouches[0].clientX;
            var endY = e.changedTouches[0].clientY;
            var dx = Math.abs(endX - this._touchStart.x);
            var dy = Math.abs(endY - this._touchStart.y);
            if (dx < 10 && dy < 10) {
                var canvas = e.target;
                var rect   = canvas.getBoundingClientRect();
                var scaleX = canvas.width  / rect.width;
                var scaleY = canvas.height / rect.height;
                var sx = (this._touchStart.x - rect.left) * scaleX;
                var sy = (this._touchStart.y - rect.top)  * scaleY;
                var cell = this._screenToGrid(sx, sy, canvas.width, canvas.height);
                if (this._buildMode) {
                    this.placeBuilding(this._buildMode, cell.x, cell.y);
                    this._buildMode = null;
                } else {
                    this._selectedCell = cell;
                }
            }
        }
        this._touchStart = null;
        this._panDrag    = null;
    };

    // ── Entity Interface ───────────────────────────────────────────────────────

    BuilderModule.prototype.getEntities = function () {
        var entities = [];
        this.buildings.forEach(function (b) {
            entities.push({ id: b.id, type: 'building_' + b.type, gridX: b.gridX, gridY: b.gridY });
        });
        this.colonists.forEach(function (c) {
            entities.push({ id: c.id, type: 'colonist', gridX: c.gridX, gridY: c.gridY });
        });
        this.resourceNodes.forEach(function (n) {
            entities.push({ id: n.id, type: 'resource_' + n.type, gridX: n.gridX, gridY: n.gridY });
        });
        return entities;
    };

    BuilderModule.prototype.addEntity = function (entityType, x, y) {
        var gx = Math.floor(x / CELL), gy = Math.floor(y / CELL);
        if (entityType.indexOf('building_') === 0) {
            var btype = entityType.slice(9);
            return this.placeBuilding(btype, gx, gy);
        } else if (entityType === 'colonist') {
            this.colonists.push({
                id: uid('c'), name: randName(),
                gridX: gx, gridY: gy,
                fx: gx, fy: gy,
                task: 'idle', health: 100,
                _moveTimer: 0, _gatherTimer: 0, _pathTarget: null
            });
            return true;
        } else if (entityType.indexOf('resource_') === 0) {
            var ntype = entityType.slice(9) || 'tree';
            this.resourceNodes.push({ id: uid('n'), type: ntype, gridX: gx, gridY: gy, amount: 20, maxAmount: 20 });
            return true;
        }
        return false;
    };

    BuilderModule.prototype.removeEntity = function (id) {
        this.buildings     = this.buildings.filter(function (b) { return b.id !== id; });
        this.colonists     = this.colonists.filter(function (c) { return c.id !== id; });
        this.resourceNodes = this.resourceNodes.filter(function (n) { return n.id !== id; });
    };

    BuilderModule.prototype.moveEntity = function (id, gridX, gridY) {
        var gx = Math.floor(gridX), gy = Math.floor(gridY);
        var all = [].concat(this.buildings, this.colonists, this.resourceNodes);
        all.forEach(function (e) {
            if (e.id === id) { e.gridX = gx; e.gridY = gy; }
        });
    };

    BuilderModule.prototype.getConfig = function () {
        return {
            type: 'base_builder',
            map: { width: this._mapW, height: this._mapH, cellSize: CELL },
            terrain: this.terrain,
            buildings: this.buildings.map(function (b) {
                return { type: b.type, gridX: b.gridX, gridY: b.gridY, hp: b.hp, id: b.id };
            }),
            colonists: this.colonists.map(function (c) {
                return { id: c.id, name: c.name, gridX: c.gridX, gridY: c.gridY, task: c.task, health: c.health };
            }),
            resources: Object.assign({}, this.resources),
            resourceNodes: this.resourceNodes.map(function (n) {
                return { id: n.id, type: n.type, gridX: n.gridX, gridY: n.gridY, amount: n.amount };
            }),
            threats: Object.assign({}, this.threats),
            cycle: this.cycle,
            cycleLength: this.cycleLength,
        };
    };

    // Public API for editor: set build mode
    BuilderModule.prototype.setBuildMode = function (type) {
        this._buildMode = BUILDING_DEFS[type] ? type : null;
    };

    // ── Register ───────────────────────────────────────────────────────────────

    if (typeof GameEngine !== 'undefined' && GameEngine.registerModuleType) {
        GameEngine.registerModuleType('base_builder', BuilderModule);
    }

    // Also expose globally for iframe access
    window.BuilderModule = BuilderModule;
    window.BUILDER_DEFS  = BUILDING_DEFS;
    window.BUILDER_DEFAULT_CONFIG = DEFAULT_BUILDER_CONFIG;

})();
