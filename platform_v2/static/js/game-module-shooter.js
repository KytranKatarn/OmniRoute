/**
 * A.R.C.H.I.E. Game Studio — Top-Down Shooter Module
 * Plugin for game-engine.js core. Registered as 'top_down_shooter'.
 */

(function () {
    'use strict';

    var ShooterModule = function () {};

    ShooterModule.prototype.type = 'top_down_shooter';

    ShooterModule.prototype.init = function (engine, config) {
        var cfg = config || {};
        var canvas = engine.canvas;

        // Game state
        this.score = 0;
        this.wave = 1;
        this.gameOver = false;
        this.bullets = [];
        this.entities = [];
        this.walls = [];

        // Reset input-adjacent state
        engine.keys = {};
        engine.mouse = { x: 0, y: 0, down: false };
        engine.touch = {
            active: false,
            joystick: { active: false, startX: 0, startY: 0, dx: 0, dy: 0 },
            aim: { active: false, x: 0, y: 0, shooting: false }
        };

        // Walls
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
            x: pc.x || canvas.width / 2,
            y: pc.y || canvas.height / 2,
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

        this._spawnWave(engine, this.wave);
    };

    ShooterModule.prototype.update = function (engine, dt) {
        if (this.gameOver) return;

        var p = this.player;
        var canvas = engine.canvas;
        var cw = canvas.width;
        var ch = canvas.height;
        var self = this;

        // --- Player movement ---
        var vx = 0, vy = 0;
        if (engine.touch.active && engine.touch.joystick.active) {
            vx = engine.touch.joystick.dx;
            vy = engine.touch.joystick.dy;
        } else {
            if (engine.keys['KeyW'] || engine.keys['ArrowUp']) vy -= 1;
            if (engine.keys['KeyS'] || engine.keys['ArrowDown']) vy += 1;
            if (engine.keys['KeyA'] || engine.keys['ArrowLeft']) vx -= 1;
            if (engine.keys['KeyD'] || engine.keys['ArrowRight']) vx += 1;
            var len = Math.sqrt(vx * vx + vy * vy);
            if (len > 0) { vx /= len; vy /= len; }
        }

        var nx = p.x + vx * p.speed * dt;
        var ny = p.y + vy * p.speed * dt;
        var pos = self._resolveWallCollision(nx, ny, p.radius);
        p.x = Math.max(p.radius, Math.min(cw - p.radius, pos.x));
        p.y = Math.max(p.radius, Math.min(ch - p.radius, pos.y));

        // --- Shooting ---
        p._fireCooldown = Math.max(0, p._fireCooldown - dt);
        p._damageCooldown = Math.max(0, p._damageCooldown - dt);

        var shooting = engine.mouse.down || (engine.touch.aim.active && engine.touch.aim.shooting);
        if (shooting && p._fireCooldown <= 0) {
            var aimX = engine.touch.aim.active ? engine.touch.aim.x : engine.mouse.x;
            var aimY = engine.touch.aim.active ? engine.touch.aim.y : engine.mouse.y;
            var adx = aimX - p.x;
            var ady = aimY - p.y;
            var alen = Math.sqrt(adx * adx + ady * ady);
            if (alen > 0) {
                this.bullets.push({
                    x: p.x, y: p.y,
                    dx: adx / alen, dy: ady / alen,
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
            if (self._bulletHitsWall(b)) {
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
            var epos = self._resolveWallCollision(en.x, en.y, en.radius);
            en.x = epos.x;
            en.y = epos.y;

            // Enemy-player collision
            var epDist = Math.sqrt(Math.pow(p.x - en.x, 2) + Math.pow(p.y - en.y, 2));
            if (epDist < p.radius + en.radius && p._damageCooldown <= 0) {
                p.health -= 10;
                p._damageCooldown = 1.0;
                if (p.health <= 0) { p.health = 0; this.gameOver = true; }
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
                if (p.health <= 0) { p.health = 0; this.gameOver = true; }
            }
        }

        // Wave complete
        if (this.entities.length === 0) {
            this.wave++;
            this._spawnWave(engine, this.wave);
        }

        // Restart key
        if (engine.keys['KeyR'] && this.gameOver) {
            this.init(engine, engine.config);
        }
    };

    ShooterModule.prototype.render = function (engine, ctx) {
        var cw = engine.canvas.width;
        var ch = engine.canvas.height;

        // Background
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
            var aimX = engine.touch.aim.active ? engine.touch.aim.x : engine.mouse.x;
            var aimY = engine.touch.aim.active ? engine.touch.aim.y : engine.mouse.y;
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
        if (engine.touch.joystick.active) {
            var jx = engine.touch.joystick.startX;
            var jy = engine.touch.joystick.startY;
            ctx.beginPath();
            ctx.arc(jx, jy, 50, 0, Math.PI * 2);
            ctx.strokeStyle = '#ffffff33';
            ctx.lineWidth = 2;
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(jx + engine.touch.joystick.dx * 50, jy + engine.touch.joystick.dy * 50, 20, 0, Math.PI * 2);
            ctx.fillStyle = '#ffffff44';
            ctx.fill();
        }

        // HUD
        this._renderHUD(engine, ctx, cw, ch);

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

    ShooterModule.prototype._renderHUD = function (engine, ctx, cw, ch) {
        var p = this.player;
        if (!p) return;

        ctx.fillStyle = '#00ccff';
        ctx.font = 'bold 18px monospace';
        ctx.textAlign = 'left';
        ctx.fillText('SCORE: ' + this.score, 12, 26);

        ctx.fillStyle = '#ffcc00';
        ctx.textAlign = 'center';
        ctx.fillText('WAVE ' + this.wave, cw / 2, 26);

        ctx.fillStyle = '#ff6644';
        ctx.textAlign = 'right';
        ctx.fillText('ENEMIES: ' + this.entities.length, cw - 12, 26);

        // Health bar
        var hbw = 160, hbh = 14;
        var hbx = 12, hby = ch - 28;
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
    };

    // --- Entity API (for scene editor) ---
    ShooterModule.prototype.getEntities = function () {
        return this.entities.slice();
    };

    ShooterModule.prototype.addEntity = function (type, x, y) {
        var id = 'e_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7);
        this.entities.push({
            id: id,
            x: x, y: y,
            spawnX: x, spawnY: y,
            radius: 14,
            speed: 80,
            health: 50, maxHealth: 50,
            color: '#ff2244',
            ai: type || 'chase',
            points: 10,
            _fireCooldown: 0
        });
        return id;
    };

    ShooterModule.prototype.removeEntity = function (id) {
        for (var i = this.entities.length - 1; i >= 0; i--) {
            if (this.entities[i].id === id) { this.entities.splice(i, 1); return; }
        }
    };

    ShooterModule.prototype.moveEntity = function (id, x, y) {
        for (var i = 0; i < this.entities.length; i++) {
            if (this.entities[i].id === id) {
                this.entities[i].x = x;
                this.entities[i].y = y;
                this.entities[i].spawnX = x;
                this.entities[i].spawnY = y;
                return;
            }
        }
    };

    ShooterModule.prototype.getConfig = function () {
        return {
            type: 'top_down_shooter',
            player: this.player,
            walls: this.walls,
            score: this.score,
            wave: this.wave
        };
    };

    // --- Internal helpers ---
    ShooterModule.prototype._spawnWave = function (engine, num) {
        var count = 3 + num * 2;
        var speedMult = 1 + (num - 1) * 0.15;
        var cw = engine.canvas.width;
        var ch = engine.canvas.height;
        var aiTypes = ['chase', 'patrol', 'circle'];

        for (var i = 0; i < count; i++) {
            var ai = aiTypes[i % aiTypes.length];
            var sx, sy;
            var edge = Math.floor(Math.random() * 4);
            if (edge === 0) { sx = Math.random() * cw; sy = 20; }
            else if (edge === 1) { sx = cw - 20; sy = Math.random() * ch; }
            else if (edge === 2) { sx = Math.random() * cw; sy = ch - 20; }
            else { sx = 20; sy = Math.random() * ch; }

            this.entities.push({
                id: 'e_' + Date.now() + '_' + i,
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

    ShooterModule.prototype._resolveWallCollision = function (x, y, radius) {
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

    ShooterModule.prototype._bulletHitsWall = function (b) {
        for (var i = 0; i < this.walls.length; i++) {
            var w = this.walls[i];
            if (b.x + b.radius > w.x && b.x - b.radius < w.x + w.w &&
                b.y + b.radius > w.y && b.y - b.radius < w.y + w.h) {
                return true;
            }
        }
        return false;
    };

    // Register with engine
    if (typeof GameEngine !== 'undefined') {
        GameEngine.registerModuleType('top_down_shooter', ShooterModule);
    }

    window.ShooterModule = ShooterModule;

}());
