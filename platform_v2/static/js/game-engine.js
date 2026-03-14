/**
 * A.R.C.H.I.E. Game Studio — Core Game Engine
 * Runs inside preview iframe. Zero external dependencies.
 * Plugin architecture: game logic lives in registered modules.
 */

(function () {
    'use strict';

    function GameEngine(canvas, config) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.config = config;

        this._module = null;
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

        // Camera
        this.camera = {
            x: 0, y: 0, zoom: 1,
            follow: function (entity) {
                if (!entity) return;
                this.x = entity.x - canvas.width / 2 / this.zoom;
                this.y = entity.y - canvas.height / 2 / this.zoom;
            },
            screenToWorld: function (sx, sy) {
                return { x: sx / this.zoom + this.x, y: sy / this.zoom + this.y };
            },
            worldToScreen: function (wx, wy) {
                return { x: (wx - this.x) * this.zoom, y: (wy - this.y) * this.zoom };
            }
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

        // Behavior sandbox
        this._behaviors = {};
    }

    // --- Behavior sandbox ---
    GameEngine.createSandboxedBehavior = function(codeStr) {
        try {
            var wrapper = '"use strict";\n' +
                'var document=void 0,window=void 0,fetch=void 0,XMLHttpRequest=void 0;\n' +
                'return (' + codeStr + ');';
            var result = (new (Function.bind.apply(Function, [null, 'entity', 'engine', 'dt', wrapper])))();
            return typeof result === 'function' ? result : null;
        } catch(e) {
            console.warn('Invalid behavior code:', e.message);
            return null;
        }
    };

    GameEngine.prototype.loadBehaviors = function(behaviors) {
        this._behaviors = {};
        var self = this;
        (behaviors || []).forEach(function(b) {
            if (b.name && b.code) {
                var fn = GameEngine.createSandboxedBehavior(b.code);
                if (fn) self._behaviors[b.name] = fn;
            }
        });
    };

    GameEngine.prototype.runBehavior = function(name, entity, dt) {
        if (this._behaviors && this._behaviors[name]) {
            try { this._behaviors[name](entity, this, dt); }
            catch(e) { console.warn('Behavior error [' + name + ']:', e.message); }
        }
    };

    // --- Static module registry ---
    GameEngine.MODULES = {};

    GameEngine.registerModuleType = function (type, ModuleClass) {
        GameEngine.MODULES[type] = ModuleClass;
    };

    // --- Instance: register module ---
    GameEngine.prototype.registerModule = function (module) {
        this._module = module;
        module.init(this, this.config);
    };

    // --- Lifecycle ---
    GameEngine.prototype.start = function () {
        var map = this.config.map || {};
        this.canvas.width = map.width || 800;
        this.canvas.height = map.height || 600;
        this.canvas.style.width = '100%';
        this.canvas.style.height = '100%';

        this._bindInputs();
        this.lastTime = performance.now();
        this.frameId = requestAnimationFrame(this._boundLoop);
    };

    GameEngine.prototype.stop = function () {
        if (this.frameId) {
            cancelAnimationFrame(this.frameId);
            this.frameId = null;
        }
        this._unbindInputs();
    };

    // --- Game loop ---
    GameEngine.prototype._loop = function (timestamp) {
        var dt = Math.min((timestamp - this.lastTime) / 1000, 0.05);
        this.lastTime = timestamp;

        this.update(dt);
        this.render();

        this.frameId = requestAnimationFrame(this._boundLoop);
    };

    GameEngine.prototype.update = function (dt) {
        if (this._module) {
            this._module.update(this, dt);
        }
    };

    GameEngine.prototype.render = function () {
        if (this._module) {
            this._module.render(this, this.ctx);
        }
    };

    // --- Input binding ---
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

    GameEngine.prototype._onMouseDown = function () { this.mouse.down = true; };
    GameEngine.prototype._onMouseUp = function () { this.mouse.down = false; };

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

    // --- Drawing primitives ---
    GameEngine.prototype.drawCircle = function (x, y, r, color) {
        var ctx = this.ctx;
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
    };

    GameEngine.prototype.drawRect = function (x, y, w, h, color) {
        this.ctx.fillStyle = color;
        this.ctx.fillRect(x, y, w, h);
    };

    GameEngine.prototype.drawText = function (text, x, y, opts) {
        var ctx = this.ctx;
        opts = opts || {};
        ctx.fillStyle = opts.color || '#ffffff';
        ctx.font = opts.font || '16px monospace';
        ctx.textAlign = opts.align || 'left';
        ctx.fillText(text, x, y);
        ctx.textAlign = 'left';
    };

    GameEngine.prototype.drawLine = function (x1, y1, x2, y2, color, width) {
        var ctx = this.ctx;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.strokeStyle = color || '#ffffff';
        ctx.lineWidth = width || 1;
        ctx.stroke();
    };

    // --- Collision helpers ---
    GameEngine.prototype.checkCircleCollision = function (a, b) {
        var dx = a.x - b.x;
        var dy = a.y - b.y;
        var dist = Math.sqrt(dx * dx + dy * dy);
        return dist < (a.radius + b.radius);
    };

    GameEngine.prototype.checkRectCollision = function (a, b) {
        return a.x < b.x + b.w && a.x + a.w > b.x &&
               a.y < b.y + b.h && a.y + a.h > b.y;
    };

    // --- HUD helpers ---
    GameEngine.prototype.drawBar = function (x, y, w, h, value, max, color) {
        var ctx = this.ctx;
        ctx.fillStyle = '#222';
        ctx.fillRect(x, y, w, h);
        var pct = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
        ctx.fillStyle = color || '#00ff88';
        ctx.fillRect(x, y, w * pct, h);
        ctx.strokeStyle = '#ffffff44';
        ctx.lineWidth = 1;
        ctx.strokeRect(x, y, w, h);
    };

    // --- postMessage bridge ---
    window.addEventListener('message', function (e) {
        if (e.data && e.data.type === 'loadConfig') {
            var config = e.data.config;
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
            var ModuleClass = GameEngine.MODULES[config.type || 'top_down_shooter'];
            if (!ModuleClass) { console.error('Unknown game type:', config.type); return; }
            window._engine = new GameEngine(canvas, config);
            window._engine.registerModule(new ModuleClass());
            window._engine.start();
            // Init scene editor (dormant until enabled)
            if (typeof SceneEditor !== 'undefined') {
                window._sceneEditor = new SceneEditor(window._engine);
            }
        }
        if (e.data && e.data.type === 'enableEditor' && window._sceneEditor) {
            window._sceneEditor.enable();
        }
        if (e.data && e.data.type === 'disableEditor' && window._sceneEditor) {
            window._sceneEditor.disable();
        }
        if (e.data && e.data.type === 'restart' && window._engine && window._engine._module) {
            window._engine._module.init(window._engine, window._engine.config);
        }
        if (e.data && e.data.type === 'loadBehaviors') {
            if (window._engine) window._engine.loadBehaviors(e.data.behaviors);
        }
    });

    // Expose globally
    window.GameEngine = GameEngine;

}());
