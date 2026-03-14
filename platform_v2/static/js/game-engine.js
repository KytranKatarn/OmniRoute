/**
 * A.R.C.H.I.E. Game Studio — Standalone Canvas Game Engine
 * Runs inside preview iframe. Zero external dependencies.
 * Communicates with editor via postMessage.
 */

(function () {
    'use strict';

    function GameEngine(canvas, config) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.config = config;

        // Game state
        this.entities = [];
        this.bullets = [];
        this.walls = [];
        this.player = null;
        this.score = 0;
        this.wave = 1;
        this.gameOver = false;
        this.lastTime = 0;
        this.frameId = null;

        // Input state
        this.keys = {};
        this.mouse = { x: 0, y: 0, down: false };
        this.touch = {
            active: false,
            joystick: { active: false, startX: 0, startY: 0, dx: 0, dy: 0 },
            aim: { active: false, x: 0, y: 0, shooting: false }
        };

        this._boundLoop = this._loop.bind(this);
        this._boundKeyDown = this._onKeyDown.bind(this);
        this._boundKeyUp = this._onKeyUp.bind(this);
        this._boundMouseMove = this._onMouseMove.bind(this);
        this._boundMouseDown = this._onMouseDown.bind(this);
        this._boundMouseUp = this._onMouseUp.bind(this);
        this._boundTouchStart = this._onTouchStart.bind(this);
        this._boundTouchMove = this._onTouchMove.bind(this);
        this._boundTouchEnd = this._onTouchEnd.bind(this);
    }

    GameEngine.prototype.start = function () {
        var map = this.config.map || {};
        this.canvas.width = map.width || 800;
        this.canvas.height = map.height || 600;
        this.canvas.style.width = '100%';
        this.canvas.style.height = '100%';

        this._initFromConfig();
        this._bindInputs();

        this.lastTime = performance.now();
        this.frameId = requestAnimationFrame(this._boundLoop);
    };

    GameEngine.prototype._initFromConfig = function () {
        var cfg = this.config;

        // Walls
        this.walls = [];
        if (cfg.walls && Array.isArray(cfg.walls)) {
            for (var i = 0; i < cfg.walls.length; i++) {
                this.walls.push({
                    x: cfg.walls[i].x || 0,
                    y: cfg.walls[i].y || 0,
                    w: cfg.walls[i].w || 50,
                    h: cfg.walls[i].h || 50,
                    color: cfg.walls[i].color || '#445566'
                });
            }
        }

        // Player
        var pc = cfg.player || {};
        this.player = {
            x: pc.x || this.canvas.width / 2,
            y: pc.y || this.canvas.height / 2,
            radius: pc.radius || 16,
            speed: pc.speed || 180,
            health: pc.health || 100,
            maxHealth: pc.health || 100,
            color: pc.color || '#00ccff',
            fireRate: pc.fireRate || 0.25,
            bulletSpeed: pc.bulletSpeed || 400,
            _fireCooldown: 0,
            _damageCooldown: 0
        };

        // Enemies
        this.entities = [];
        this.spawnWave(this.wave);

        // Bullets
        this.bullets = [];
    };

    GameEngine.prototype._bindInputs = function () {
        window.addEventListener('keydown', this._boundKeyDown);
        window.addEventListener('keyup', this._boundKeyUp);
        this.canvas.addEventListener('mousemove', this._boundMouseMove);
        this.canvas.addEventListener('mousedown', this._boundMouseDown);
        this.canvas.addEventListener('mouseup', this._boundMouseUp);
        this.canvas.addEventListener('touchstart', this._boundTouchStart, { passive: false });
        this.canvas.addEventListener('touchmove', this._boundTouchMove, { passive: false });
        this.canvas.addEventListener('touchend', this._boundTouchEnd, { passive: false });
    };

    GameEngine.prototype._unbindInputs = function () {
        window.removeEventListener('keydown', this._boundKeyDown);
        window.removeEventListener('keyup', this._boundKeyUp);
        this.canvas.removeEventListener('mousemove', this._boundMouseMove);
        this.canvas.removeEventListener('mousedown', this._boundMouseDown);
        this.canvas.removeEventListener('mouseup', this._boundMouseUp);
        this.canvas.removeEventListener('touchstart', this._boundTouchStart);
        this.canvas.removeEventListener('touchmove', this._boundTouchMove);
        this.canvas.removeEventListener('touchend', this._boundTouchEnd);
    };

    GameEngine.prototype._onKeyDown = function (e) { this.keys[e.code] = true; };
    GameEngine.prototype._onKeyUp = function (e) { this.keys[e.code] = false; };

    GameEngine.prototype._onMouseMove = function (e) {
        var rect = this.canvas.getBoundingClientRect();
        var scaleX = this.canvas.width / rect.width;
        var scaleY = this.canvas.height / rect.height;
        this.mouse.x = (e.clientX - rect.left) * scaleX;
        this.mouse.y = (e.clientY - rect.top) * scaleY;
    };

    GameEngine.prototype._onMouseDown = function (e) { this.mouse.down = true; };
    GameEngine.prototype._onMouseUp = function (e) { this.mouse.down = false; };

    GameEngine.prototype._onTouchStart = function (e) {
        e.preventDefault();
        this.touch.active = true;
        var rect = this.canvas.getBoundingClientRect();
        var scaleX = this.canvas.width / rect.width;
        var scaleY = this.canvas.height / rect.height;

        for (var i = 0; i < e.changedTouches.length; i++) {
            var t = e.changedTouches[i];
            var tx = (t.clientX - rect.left) * scaleX;
            var ty = (t.clientY - rect.top) * scaleY;

            if (tx < this.canvas.width * 0.4) {
                this.touch.joystick.active = true;
                this.touch.joystick.startX = tx;
                this.touch.joystick.startY = ty;
                this.touch.joystick.dx = 0;
                this.touch.joystick.dy = 0;
                this.touch.joystick.id = t.identifier;
            } else {
                this.touch.aim.active = true;
                this.touch.aim.x = tx;
                this.touch.aim.y = ty;
                this.touch.aim.shooting = true;
                this.touch.aim.id = t.identifier;
            }
        }
    };

    GameEngine.prototype._onTouchMove = function (e) {
        e.preventDefault();
        var rect = this.canvas.getBoundingClientRect();
        var scaleX = this.canvas.width / rect.width;
        var scaleY = this.canvas.height / rect.height;

        for (var i = 0; i < e.changedTouches.length; i++) {
            var t = e.changedTouches[i];
            var tx = (t.clientX - rect.left) * scaleX;
            var ty = (t.clientY - rect.top) * scaleY;

            if (this.touch.joystick.active && t.identifier === this.touch.joystick.id) {
                var dx = tx - this.touch.joystick.startX;
                var dy = ty - this.touch.joystick.startY;
                var len = Math.sqrt(dx * dx + dy * dy);
                var maxR = 50;
                if (len > maxR) { dx = dx / len * maxR; dy = dy / len * maxR; }
                this.touch.joystick.dx = dx / maxR;
                this.touch.joystick.dy = dy / maxR;
            } else if (this.touch.aim.active && t.identifier === this.touch.aim.id) {
                this.touch.aim.x = tx;
                this.touch.aim.y = ty;
            }
        }
    };

    GameEngine.prototype._onTouchEnd = function (e) {
        e.preventDefault();
        for (var i = 0; i < e.changedTouches.length; i++) {
            var t = e.changedTouches[i];
            if (this.touch.joystick.active && t.identifier === this.touch.joystick.id) {
                this.touch.joystick.active = false;
                this.touch.joystick.dx = 0;
                this.touch.joystick.dy = 0;
            }
            if (this.touch.aim.active && t.identifier === this.touch.aim.id) {
                this.touch.aim.active = false;
                this.touch.aim.shooting = false;
            }
        }
        if (!this.touch.joystick.active && !this.touch.aim.active) {
            this.touch.active = false;
        }
    };

    GameEngine.prototype._loop = function (timestamp) {
        var dt = Math.min((timestamp - this.lastTime) / 1000, 0.05);
        this.lastTime = timestamp;

        if (!this.gameOver) {
            this.update(dt);
        }
        this.render();

        this.frameId = requestAnimationFrame(this._boundLoop);
    };

    GameEngine.prototype.update = function (dt) {
        var p = this.player;
        var cw = this.canvas.width;
        var ch = this.canvas.height;

        // --- Player movement ---
        var vx = 0, vy = 0;
        if (this.touch.active && this.touch.joystick.active) {
            vx = this.touch.joystick.dx;
            vy = this.touch.joystick.dy;
        } else {
            if (this.keys['KeyW'] || this.keys['ArrowUp']) vy -= 1;
            if (this.keys['KeyS'] || this.keys['ArrowDown']) vy += 1;
            if (this.keys['KeyA'] || this.keys['ArrowLeft']) vx -= 1;
            if (this.keys['KeyD'] || this.keys['ArrowRight']) vx += 1;
            var len = Math.sqrt(vx * vx + vy * vy);
            if (len > 0) { vx /= len; vy /= len; }
        }

        var nx = p.x + vx * p.speed * dt;
        var ny = p.y + vy * p.speed * dt;

        // Wall collision for player
        var pos = this._resolveWallCollision(nx, ny, p.radius);
        p.x = Math.max(p.radius, Math.min(cw - p.radius, pos.x));
        p.y = Math.max(p.radius, Math.min(ch - p.radius, pos.y));

        // --- Shooting ---
        p._fireCooldown = Math.max(0, p._fireCooldown - dt);
        p._damageCooldown = Math.max(0, p._damageCooldown - dt);

        var shooting = this.mouse.down || (this.touch.aim.active && this.touch.aim.shooting);
        if (shooting && p._fireCooldown <= 0) {
            var aimX, aimY;
            if (this.touch.aim.active) {
                aimX = this.touch.aim.x;
                aimY = this.touch.aim.y;
            } else {
                aimX = this.mouse.x;
                aimY = this.mouse.y;
            }
            var adx = aimX - p.x;
            var ady = aimY - p.y;
            var alen = Math.sqrt(adx * adx + ady * ady);
            if (alen > 0) {
                this.bullets.push({
                    x: p.x, y: p.y,
                    dx: adx / alen,
                    dy: ady / alen,
                    speed: p.bulletSpeed,
                    radius: 5,
                    color: '#ffff00',
                    fromPlayer: true
                });
                p._fireCooldown = p.fireRate;
            }
        }

        // --- Bullet movement ---
        for (var bi = this.bullets.length - 1; bi >= 0; bi--) {
            var b = this.bullets[bi];
            b.x += b.dx * b.speed * dt;
            b.y += b.dy * b.speed * dt;
            if (b.x < -20 || b.x > cw + 20 || b.y < -20 || b.y > ch + 20) {
                this.bullets.splice(bi, 1);
                continue;
            }
            // Bullet-wall collision
            if (this._bulletHitsWall(b)) {
                this.bullets.splice(bi, 1);
                continue;
            }
        }

        // --- Enemy update ---
        for (var ei = this.entities.length - 1; ei >= 0; ei--) {
            var en = this.entities[ei];
            en._fireCooldown = Math.max(0, (en._fireCooldown || 0) - dt);

            if (en.ai === 'chase') {
                var edx = p.x - en.x;
                var edy = p.y - en.y;
                var elen = Math.sqrt(edx * edx + edy * edy);
                if (elen > 0) {
                    en.x += (edx / elen) * en.speed * dt;
                    en.y += (edy / elen) * en.speed * dt;
                }

            } else if (en.ai === 'patrol') {
                var distToPlayer = Math.sqrt(Math.pow(p.x - en.x, 2) + Math.pow(p.y - en.y, 2));
                if (distToPlayer < 200) {
                    var pdx = p.x - en.x;
                    var pdy = p.y - en.y;
                    var plen = Math.sqrt(pdx * pdx + pdy * pdy);
                    if (plen > 0) { en.x += (pdx / plen) * en.speed * dt; en.y += (pdy / plen) * en.speed * dt; }
                } else {
                    if (!en._patrolDir) en._patrolDir = 1;
                    en.x += en._patrolDir * en.speed * dt;
                    if (Math.abs(en.x - en.spawnX) > 100) en._patrolDir *= -1;
                }

            } else if (en.ai === 'circle') {
                en._angle = (en._angle || 0) + en.speed * dt * 0.02;
                en.x = en.spawnX + Math.cos(en._angle) * 80;
                en.y = en.spawnY + Math.sin(en._angle) * 80;
                // Circle enemies shoot at player every 2s
                if (en._fireCooldown <= 0) {
                    var cdx = p.x - en.x;
                    var cdy = p.y - en.y;
                    var clen = Math.sqrt(cdx * cdx + cdy * cdy);
                    if (clen > 0) {
                        this.bullets.push({
                            x: en.x, y: en.y,
                            dx: cdx / clen, dy: cdy / clen,
                            speed: 200, radius: 5,
                            color: '#ff4444', fromPlayer: false
                        });
                    }
                    en._fireCooldown = 2;
                }
            }

            // Clamp enemies to canvas
            en.x = Math.max(en.radius, Math.min(cw - en.radius, en.x));
            en.y = Math.max(en.radius, Math.min(ch - en.radius, en.y));

            // Enemy-wall collision
            var epos = this._resolveWallCollision(en.x, en.y, en.radius);
            en.x = epos.x;
            en.y = epos.y;

            // Enemy-player collision
            var epDist = Math.sqrt(Math.pow(p.x - en.x, 2) + Math.pow(p.y - en.y, 2));
            if (epDist < p.radius + en.radius && p._damageCooldown <= 0) {
                p.health -= 10;
                p._damageCooldown = 1.0;
                if (p.health <= 0) {
                    p.health = 0;
                    this.gameOver = true;
                }
            }

            // Bullet-enemy collision
            for (var bj = this.bullets.length - 1; bj >= 0; bj--) {
                var bull = this.bullets[bj];
                if (!bull.fromPlayer) continue;
                var beDist = Math.sqrt(Math.pow(bull.x - en.x, 2) + Math.pow(bull.y - en.y, 2));
                if (beDist < bull.radius + en.radius) {
                    en.health -= 25;
                    this.bullets.splice(bj, 1);
                    if (en.health <= 0) {
                        this.score += en.points || 10;
                        this.entities.splice(ei, 1);
                        break;
                    }
                }
            }
        }

        // Enemy bullets hitting player
        for (var bk = this.bullets.length - 1; bk >= 0; bk--) {
            var ebull = this.bullets[bk];
            if (ebull.fromPlayer) continue;
            var bpDist = Math.sqrt(Math.pow(ebull.x - p.x, 2) + Math.pow(ebull.y - p.y, 2));
            if (bpDist < ebull.radius + p.radius && p._damageCooldown <= 0) {
                p.health -= 15;
                p._damageCooldown = 0.5;
                this.bullets.splice(bk, 1);
                if (p.health <= 0) {
                    p.health = 0;
                    this.gameOver = true;
                }
            }
        }

        // --- Wave complete ---
        if (this.entities.length === 0 && !this.gameOver) {
            this.wave++;
            this.spawnWave(this.wave);
        }
    };

    GameEngine.prototype._resolveWallCollision = function (x, y, radius) {
        for (var i = 0; i < this.walls.length; i++) {
            var w = this.walls[i];
            var nearX = Math.max(w.x, Math.min(w.x + w.w, x));
            var nearY = Math.max(w.y, Math.min(w.y + w.h, y));
            var dx = x - nearX;
            var dy = y - nearY;
            var dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < radius && dist > 0) {
                var overlap = radius - dist;
                x += (dx / dist) * overlap;
                y += (dy / dist) * overlap;
            }
        }
        return { x: x, y: y };
    };

    GameEngine.prototype._bulletHitsWall = function (b) {
        for (var i = 0; i < this.walls.length; i++) {
            var w = this.walls[i];
            if (b.x + b.radius > w.x && b.x - b.radius < w.x + w.w &&
                b.y + b.radius > w.y && b.y - b.radius < w.y + w.h) {
                return true;
            }
        }
        return false;
    };

    GameEngine.prototype.spawnWave = function (num) {
        var count = 3 + num * 2;
        var speedMult = 1 + (num - 1) * 0.15;
        var cw = this.canvas.width;
        var ch = this.canvas.height;
        var aiTypes = ['chase', 'patrol', 'circle'];

        for (var i = 0; i < count; i++) {
            var ai = aiTypes[i % aiTypes.length];
            // Spawn at edges, away from player
            var sx, sy;
            var edge = Math.floor(Math.random() * 4);
            if (edge === 0) { sx = Math.random() * cw; sy = 20; }
            else if (edge === 1) { sx = cw - 20; sy = Math.random() * ch; }
            else if (edge === 2) { sx = Math.random() * cw; sy = ch - 20; }
            else { sx = 20; sy = Math.random() * ch; }

            this.entities.push({
                x: sx, y: sy,
                spawnX: sx, spawnY: sy,
                radius: 14,
                speed: 80 * speedMult,
                health: 50 + num * 10,
                maxHealth: 50 + num * 10,
                color: ai === 'circle' ? '#ff6600' : ai === 'patrol' ? '#cc44ff' : '#ff2244',
                ai: ai,
                points: 10 + num * 5,
                _fireCooldown: Math.random() * 2
            });
        }
    };

    GameEngine.prototype.render = function () {
        var ctx = this.ctx;
        var cw = this.canvas.width;
        var ch = this.canvas.height;

        // Clear
        ctx.fillStyle = '#0a0a1a';
        ctx.fillRect(0, 0, cw, ch);

        // Grid
        ctx.strokeStyle = '#111133';
        ctx.lineWidth = 1;
        for (var gx = 0; gx < cw; gx += 40) {
            ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, ch); ctx.stroke();
        }
        for (var gy = 0; gy < ch; gy += 40) {
            ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(cw, gy); ctx.stroke();
        }

        // Walls
        for (var wi = 0; wi < this.walls.length; wi++) {
            var wall = this.walls[wi];
            ctx.fillStyle = wall.color || '#445566';
            ctx.fillRect(wall.x, wall.y, wall.w, wall.h);
            ctx.strokeStyle = '#667788';
            ctx.lineWidth = 1;
            ctx.strokeRect(wall.x, wall.y, wall.w, wall.h);
        }

        // Enemies
        for (var ei = 0; ei < this.entities.length; ei++) {
            var en = this.entities[ei];
            ctx.beginPath();
            ctx.arc(en.x, en.y, en.radius, 0, Math.PI * 2);
            ctx.fillStyle = en.color;
            ctx.fill();
            ctx.strokeStyle = '#ffffff44';
            ctx.lineWidth = 1;
            ctx.stroke();
            // Health bar
            var hbw = en.radius * 2;
            ctx.fillStyle = '#440000';
            ctx.fillRect(en.x - hbw / 2, en.y - en.radius - 8, hbw, 4);
            ctx.fillStyle = '#ff4444';
            ctx.fillRect(en.x - hbw / 2, en.y - en.radius - 8, hbw * (en.health / en.maxHealth), 4);
        }

        // Bullets
        for (var bi = 0; bi < this.bullets.length; bi++) {
            var bull = this.bullets[bi];
            ctx.beginPath();
            ctx.arc(bull.x, bull.y, bull.radius, 0, Math.PI * 2);
            ctx.fillStyle = bull.color;
            ctx.shadowColor = bull.color;
            ctx.shadowBlur = 8;
            ctx.fill();
            ctx.shadowBlur = 0;
        }

        // Player
        var p = this.player;
        if (p) {
            // Damage flash
            var flashing = p._damageCooldown > 0 && Math.floor(p._damageCooldown * 10) % 2 === 0;
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
            ctx.fillStyle = flashing ? '#ffffff' : p.color;
            ctx.shadowColor = p.color;
            ctx.shadowBlur = 12;
            ctx.fill();
            ctx.shadowBlur = 0;
            ctx.strokeStyle = '#ffffff66';
            ctx.lineWidth = 2;
            ctx.stroke();

            // Aim line
            var aimX = this.touch.aim.active ? this.touch.aim.x : this.mouse.x;
            var aimY = this.touch.aim.active ? this.touch.aim.y : this.mouse.y;
            var adx = aimX - p.x;
            var ady = aimY - p.y;
            var alen = Math.sqrt(adx * adx + ady * ady);
            if (alen > 5) {
                ctx.beginPath();
                ctx.setLineDash([4, 6]);
                ctx.strokeStyle = '#00ccff44';
                ctx.lineWidth = 1;
                ctx.moveTo(p.x, p.y);
                ctx.lineTo(p.x + (adx / alen) * 60, p.y + (ady / alen) * 60);
                ctx.stroke();
                ctx.setLineDash([]);
            }
        }

        // Virtual joystick
        if (this.touch.joystick.active) {
            var jx = this.touch.joystick.startX;
            var jy = this.touch.joystick.startY;
            ctx.beginPath();
            ctx.arc(jx, jy, 50, 0, Math.PI * 2);
            ctx.strokeStyle = '#ffffff33';
            ctx.lineWidth = 2;
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(jx + this.touch.joystick.dx * 50, jy + this.touch.joystick.dy * 50, 20, 0, Math.PI * 2);
            ctx.fillStyle = '#ffffff44';
            ctx.fill();
        }

        // HUD
        this._renderHUD(ctx, cw, ch);

        // Game over overlay
        if (this.gameOver) {
            ctx.fillStyle = 'rgba(0,0,0,0.7)';
            ctx.fillRect(0, 0, cw, ch);

            ctx.fillStyle = '#ff2244';
            ctx.font = 'bold 48px monospace';
            ctx.textAlign = 'center';
            ctx.fillText('GAME OVER', cw / 2, ch / 2 - 40);

            ctx.fillStyle = '#ffffff';
            ctx.font = '24px monospace';
            ctx.fillText('Score: ' + this.score, cw / 2, ch / 2 + 10);
            ctx.fillText('Wave: ' + this.wave, cw / 2, ch / 2 + 45);

            ctx.fillStyle = '#00ccff';
            ctx.font = '18px monospace';
            ctx.fillText('Press R to restart', cw / 2, ch / 2 + 90);
            ctx.textAlign = 'left';
        }
    };

    GameEngine.prototype._renderHUD = function (ctx, cw, ch) {
        var p = this.player;
        if (!p) return;

        // Score
        ctx.fillStyle = '#00ccff';
        ctx.font = 'bold 18px monospace';
        ctx.textAlign = 'left';
        ctx.fillText('SCORE: ' + this.score, 12, 26);

        // Wave
        ctx.fillStyle = '#ffcc00';
        ctx.textAlign = 'center';
        ctx.fillText('WAVE ' + this.wave, cw / 2, 26);

        // Enemies remaining
        ctx.fillStyle = '#ff6644';
        ctx.textAlign = 'right';
        ctx.fillText('ENEMIES: ' + this.entities.length, cw - 12, 26);

        // Health bar
        var hbw = 160;
        var hbh = 14;
        var hbx = 12;
        var hby = ch - 28;
        ctx.fillStyle = '#330000';
        ctx.fillRect(hbx, hby, hbw, hbh);
        var hpPct = p.health / p.maxHealth;
        ctx.fillStyle = hpPct > 0.5 ? '#00ff88' : hpPct > 0.25 ? '#ffcc00' : '#ff2244';
        ctx.fillRect(hbx, hby, hbw * hpPct, hbh);
        ctx.strokeStyle = '#ffffff44';
        ctx.lineWidth = 1;
        ctx.strokeRect(hbx, hby, hbw, hbh);

        ctx.fillStyle = '#ffffff';
        ctx.font = '11px monospace';
        ctx.textAlign = 'left';
        ctx.fillText('HP: ' + p.health + '/' + p.maxHealth, hbx + 4, hby + 11);

        ctx.textAlign = 'left';
    };

    GameEngine.prototype.restart = function () {
        this.score = 0;
        this.wave = 1;
        this.gameOver = false;
        this.bullets = [];
        this.entities = [];
        this.keys = {};
        this.mouse = { x: 0, y: 0, down: false };
        this.touch = {
            active: false,
            joystick: { active: false, startX: 0, startY: 0, dx: 0, dy: 0 },
            aim: { active: false, x: 0, y: 0, shooting: false }
        };
        this._initFromConfig();
    };

    // Restart key handler
    function _globalKeyHandler(e) {
        if (e.code === 'KeyR' && window._engine && window._engine.gameOver) {
            window._engine.restart();
        }
    }
    window.addEventListener('keydown', _globalKeyHandler);

    // postMessage bridge
    window.addEventListener('message', function (e) {
        if (!e.data) return;

        if (e.data.type === 'loadConfig') {
            var canvas = document.getElementById('gameCanvas');
            if (!canvas) {
                canvas = document.createElement('canvas');
                canvas.id = 'gameCanvas';
                document.body.appendChild(canvas);
                document.body.style.margin = '0';
                document.body.style.overflow = 'hidden';
                document.body.style.background = '#000';
            }
            if (window._engine && window._engine.frameId) {
                cancelAnimationFrame(window._engine.frameId);
                window._engine._unbindInputs();
            }
            window._engine = new GameEngine(canvas, e.data.config);
            window._engine.start();
        }

        if (e.data.type === 'restart' && window._engine) {
            window._engine.restart();
        }
    });

    // Expose globally
    window.GameEngine = GameEngine;

}());
