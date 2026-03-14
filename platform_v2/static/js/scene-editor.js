/**
 * scene-editor.js — Visual Scene Editor for Game Studio
 * Runs inside the preview iframe alongside game-engine.js and modules.
 * Instantiated after engine starts, dormant until enableEditor message received.
 */

class SceneEditor {
    constructor(engine) {
        this.engine = engine;
        this.active = false;
        this.selectedEntity = null;
        this.dragging = false;
        this.dragStartX = 0;
        this.dragStartY = 0;
        this.dragOffsetX = 0;
        this.dragOffsetY = 0;
        this.contextMenu = null; // {x, y, worldX, worldY, items: [{label, type}]}
        this.gridSnap = engine.config.type === 'base_builder' ? 32 : 1;
        this.showGrid = engine.config.type === 'base_builder';
        this._boundMouseDown = this.onMouseDown.bind(this);
        this._boundMouseMove = this.onMouseMove.bind(this);
        this._boundMouseUp = this.onMouseUp.bind(this);
        this._boundContextMenu = this.onRightClick.bind(this);
        this._boundKeyDown = this.onKeyDown.bind(this);
        this._hoveredEntity = null;
        this._renderLoop = null;
        this._lastMouseScreen = { x: 0, y: 0 };

        // Listen for enable/disable messages from parent
        window.addEventListener('message', (e) => {
            if (!e.data) return;
            if (e.data.type === 'enableEditor') this.enable();
            if (e.data.type === 'disableEditor') this.disable();
        });
    }

    // -------------------------------------------------------------------------
    // Enable / Disable
    // -------------------------------------------------------------------------

    enable() {
        this.active = true;
        if (this.engine.stop) this.engine.stop();

        var canvas = this.engine.canvas;
        canvas.addEventListener('mousedown', this._boundMouseDown);
        canvas.addEventListener('mousemove', this._boundMouseMove);
        canvas.addEventListener('mouseup', this._boundMouseUp);
        canvas.addEventListener('contextmenu', this._boundContextMenu);
        window.addEventListener('keydown', this._boundKeyDown);

        this._startRenderLoop();
        window.parent.postMessage({ type: 'editorEnabled' }, '*');
    }

    disable() {
        this.active = false;

        var canvas = this.engine.canvas;
        canvas.removeEventListener('mousedown', this._boundMouseDown);
        canvas.removeEventListener('mousemove', this._boundMouseMove);
        canvas.removeEventListener('mouseup', this._boundMouseUp);
        canvas.removeEventListener('contextmenu', this._boundContextMenu);
        window.removeEventListener('keydown', this._boundKeyDown);

        this._stopRenderLoop();
        this.selectedEntity = null;
        this.contextMenu = null;
        this._hoveredEntity = null;
        this.dragging = false;

        if (this.engine.start) this.engine.start();
        window.parent.postMessage({ type: 'editorDisabled' }, '*');
    }

    _startRenderLoop() {
        var self = this;
        var loop = function () {
            if (!self.active) return;
            self._renderLoop = requestAnimationFrame(loop);
            self.render(self.engine.ctx);
        };
        this._renderLoop = requestAnimationFrame(loop);
    }

    _stopRenderLoop() {
        if (this._renderLoop) {
            cancelAnimationFrame(this._renderLoop);
            this._renderLoop = null;
        }
    }

    // -------------------------------------------------------------------------
    // Coordinate helpers
    // -------------------------------------------------------------------------

    _canvasCoords(e) {
        var rect = this.engine.canvas.getBoundingClientRect();
        return {
            x: e.clientX - rect.left,
            y: e.clientY - rect.top
        };
    }

    _screenToWorld(sx, sy) {
        var cam = this.engine.camera || { x: 0, y: 0 };
        if (cam.screenToWorld) return cam.screenToWorld(sx, sy);
        return { x: sx + (cam.x || 0), y: sy + (cam.y || 0) };
    }

    _worldToScreen(wx, wy) {
        var cam = this.engine.camera || { x: 0, y: 0 };
        if (cam.worldToScreen) return cam.worldToScreen(wx, wy);
        return { x: wx - (cam.x || 0), y: wy - (cam.y || 0) };
    }

    _snap(v) {
        if (this.gridSnap <= 1) return v;
        return Math.round(v / this.gridSnap) * this.gridSnap;
    }

    // -------------------------------------------------------------------------
    // Hit testing
    // -------------------------------------------------------------------------

    _hitTest(worldX, worldY) {
        var module = this.engine._module;
        if (!module || !module.getEntities) return null;
        var entities = module.getEntities();
        // Iterate in reverse so topmost entity wins
        for (var i = entities.length - 1; i >= 0; i--) {
            var e = entities[i];
            var b = this.getEntityBounds(e);
            if (worldX >= b.x && worldX <= b.x + b.width &&
                worldY >= b.y && worldY <= b.y + b.height) {
                return e;
            }
        }
        return null;
    }

    _isCircleEntity(e) {
        return e.size !== undefined && e.width === undefined && e.height === undefined;
    }

    // -------------------------------------------------------------------------
    // Mouse handlers
    // -------------------------------------------------------------------------

    onMouseDown(ev) {
        if (ev.button !== 0) return;
        var sc = this._canvasCoords(ev);
        var wc = this._screenToWorld(sc.x, sc.y);

        // Context menu interaction
        if (this.contextMenu) {
            var item = this._menuItemAt(sc.x, sc.y);
            if (item) {
                var module = this.engine._module;
                if (module && module.addEntity) {
                    module.addEntity(item.type, this.contextMenu.worldX, this.contextMenu.worldY);
                }
                this.contextMenu = null;
                this._syncConfig();
                return;
            }
            // Click outside menu — close it
            this.contextMenu = null;
            return;
        }

        var hit = this._hitTest(wc.x, wc.y);
        if (hit) {
            // Check delete handle first
            if (this.selectedEntity && this.selectedEntity.id === hit.id &&
                this._isOnDeleteHandle(sc.x, sc.y, hit)) {
                var mod = this.engine._module;
                if (mod && mod.removeEntity) mod.removeEntity(hit.id);
                this.selectedEntity = null;
                this.dragging = false;
                this._syncConfig();
                window.parent.postMessage({ type: 'entitySelected', entity: null }, '*');
                return;
            }

            this.selectedEntity = hit;
            this.dragging = true;
            this.dragStartX = wc.x;
            this.dragStartY = wc.y;

            if (this._isCircleEntity(hit)) {
                this.dragOffsetX = wc.x - hit.x;
                this.dragOffsetY = wc.y - hit.y;
            } else if (hit.gridX !== undefined) {
                this.dragOffsetX = 0;
                this.dragOffsetY = 0;
            } else {
                this.dragOffsetX = wc.x - hit.x;
                this.dragOffsetY = wc.y - hit.y;
            }
        } else {
            this.selectedEntity = null;
            this.dragging = false;
        }

        window.parent.postMessage({ type: 'entitySelected', entity: this.selectedEntity || null }, '*');
    }

    onMouseMove(ev) {
        var sc = this._canvasCoords(ev);
        var wc = this._screenToWorld(sc.x, sc.y);
        this._lastMouseScreen = sc;

        if (this.dragging && this.selectedEntity) {
            var module = this.engine._module;
            var newX, newY;

            if (this._isCircleEntity(this.selectedEntity)) {
                newX = this._snap(wc.x - this.dragOffsetX);
                newY = this._snap(wc.y - this.dragOffsetY);
            } else if (this.selectedEntity.gridX !== undefined) {
                newX = this._snap(wc.x);
                newY = this._snap(wc.y);
            } else {
                newX = this._snap(wc.x - this.dragOffsetX);
                newY = this._snap(wc.y - this.dragOffsetY);
            }

            if (module && module.moveEntity) {
                module.moveEntity(this.selectedEntity.id, newX, newY);
            }
            // Mirror update locally so bounds recalculate correctly
            if (this.selectedEntity.gridX !== undefined) {
                this.selectedEntity.gridX = Math.round(newX / 32);
                this.selectedEntity.gridY = Math.round(newY / 32);
            } else {
                this.selectedEntity.x = newX;
                this.selectedEntity.y = newY;
            }
        } else {
            this._hoveredEntity = this._hitTest(wc.x, wc.y);
        }
    }

    onMouseUp(ev) {
        if (this.dragging) {
            this.dragging = false;
            this._syncConfig();
        }
    }

    onRightClick(ev) {
        ev.preventDefault();
        var sc = this._canvasCoords(ev);
        var wc = this._screenToWorld(sc.x, sc.y);

        var items = this._buildContextMenuItems();
        this.contextMenu = {
            x: sc.x,
            y: sc.y,
            worldX: this._snap(wc.x),
            worldY: this._snap(wc.y),
            items: items
        };
    }

    onKeyDown(ev) {
        if (!this.active) return;
        var key = ev.key;

        if (key === 'Delete' || key === 'Backspace') {
            if (this.selectedEntity) {
                var module = this.engine._module;
                if (module && module.removeEntity) {
                    module.removeEntity(this.selectedEntity.id);
                }
                this.selectedEntity = null;
                this._syncConfig();
                window.parent.postMessage({ type: 'entitySelected', entity: null }, '*');
            }
        } else if (key === 'Escape') {
            this.selectedEntity = null;
            this.contextMenu = null;
            this.dragging = false;
            window.parent.postMessage({ type: 'entitySelected', entity: null }, '*');
        } else if (key === 'g' || key === 'G') {
            this.showGrid = !this.showGrid;
        }
    }

    // -------------------------------------------------------------------------
    // Context menu helpers
    // -------------------------------------------------------------------------

    _buildContextMenuItems() {
        var type = this.engine.config.type;
        if (type === 'top_down_shooter') {
            return [
                { label: 'Add Enemy (Chase)',   type: 'enemy_chase' },
                { label: 'Add Enemy (Patrol)',  type: 'enemy_patrol' },
                { label: 'Add Enemy (Circle)',  type: 'enemy_circle' },
                { label: 'Add Wall',            type: 'wall' }
            ];
        }
        if (type === 'space_explorer') {
            var layer = (this.engine._module && this.engine._module.layer) || 'galaxy';
            if (layer === 'galaxy') return [{ label: 'Add Star',   type: 'star' }];
            if (layer === 'system') return [{ label: 'Add Planet', type: 'planet' }];
            return [];
        }
        if (type === 'base_builder') {
            return [
                { label: 'Add Shelter',   type: 'building_shelter' },
                { label: 'Add Farm',      type: 'building_farm' },
                { label: 'Add Workshop',  type: 'building_workshop' },
                { label: 'Add Wall',      type: 'building_wall' },
                { label: 'Add Turret',    type: 'building_turret' },
                { label: 'Add Well',      type: 'building_well' },
                { label: 'Add Tree',      type: 'resource_tree' },
                { label: 'Add Rock',      type: 'resource_rock' }
            ];
        }
        return [];
    }

    _menuItemAt(sx, sy) {
        if (!this.contextMenu) return null;
        var itemH = 28;
        var menuW = 180;
        var mx = this._clampedMenuX();
        var my = this._clampedMenuY();
        for (var i = 0; i < this.contextMenu.items.length; i++) {
            var iy = my + i * itemH;
            if (sx >= mx && sx <= mx + menuW && sy >= iy && sy <= iy + itemH) {
                return this.contextMenu.items[i];
            }
        }
        return null;
    }

    _clampedMenuX() {
        var menuW = 180;
        var w = this.engine.canvas.width;
        return Math.min(this.contextMenu.x, w - menuW - 4);
    }

    _clampedMenuY() {
        var itemH = 28;
        var menuH = this.contextMenu.items.length * itemH;
        var h = this.engine.canvas.height;
        return Math.min(this.contextMenu.y, h - menuH - 4);
    }

    // -------------------------------------------------------------------------
    // Entity bounds
    // -------------------------------------------------------------------------

    getEntityBounds(e) {
        // Grid-based entities (base_builder)
        if (e.gridX !== undefined && e.gridY !== undefined) {
            return { x: e.gridX * 32, y: e.gridY * 32, width: 32, height: 32 };
        }
        // Circle entities (enemies, player, colonists)
        if (this._isCircleEntity(e)) {
            var sz = e.size || 16;
            return { x: e.x - sz, y: e.y - sz, width: sz * 2, height: sz * 2 };
        }
        // Rect entities (walls, buildings)
        return { x: e.x, y: e.y, width: e.width || 32, height: e.height || 32 };
    }

    _isOnDeleteHandle(sx, sy, entity) {
        var b = this.getEntityBounds(entity);
        var sp = this._worldToScreen(b.x + b.width, b.y);
        var hx = sp.x + 3;
        var hy = sp.y - 3 - 14;
        return sx >= hx - 10 && sx <= hx + 10 && sy >= hy - 2 && sy <= hy + 16;
    }

    // -------------------------------------------------------------------------
    // Config sync
    // -------------------------------------------------------------------------

    _syncConfig() {
        var module = this.engine._module;
        var config = (module && module.getConfig) ? module.getConfig() : null;
        window.parent.postMessage({ type: 'configUpdated', config: config }, '*');
    }

    // -------------------------------------------------------------------------
    // Render
    // -------------------------------------------------------------------------

    render(ctx) {
        if (!this.active) return;

        var cw = this.engine.canvas.width;
        var ch = this.engine.canvas.height;

        // Draw the static paused game frame
        if (this.engine._module && this.engine._module.render) {
            ctx.clearRect(0, 0, cw, ch);
            this.engine._module.render(this.engine, ctx);
        }

        var cam = this.engine.camera || { x: 0, y: 0 };
        var camX = cam.x || 0;
        var camY = cam.y || 0;

        // ── Grid overlay ──────────────────────────────────────────────────────
        if (this.showGrid && this.gridSnap > 1) {
            ctx.save();
            ctx.strokeStyle = 'rgba(255,255,255,0.05)';
            ctx.lineWidth = 1;
            var startX = ((-camX) % this.gridSnap + this.gridSnap) % this.gridSnap;
            var startY = ((-camY) % this.gridSnap + this.gridSnap) % this.gridSnap;
            for (var gx = startX; gx < cw; gx += this.gridSnap) {
                ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, ch); ctx.stroke();
            }
            for (var gy = startY; gy < ch; gy += this.gridSnap) {
                ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(cw, gy); ctx.stroke();
            }
            ctx.restore();
        }

        // ── Hover highlight ───────────────────────────────────────────────────
        if (this._hoveredEntity && this._hoveredEntity !== this.selectedEntity) {
            var hb = this.getEntityBounds(this._hoveredEntity);
            var hsp = this._worldToScreen(hb.x, hb.y);
            ctx.save();
            ctx.strokeStyle = 'rgba(255,255,255,0.4)';
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.strokeRect(hsp.x - 2, hsp.y - 2, hb.width + 4, hb.height + 4);
            ctx.restore();
        }

        // ── Selection ─────────────────────────────────────────────────────────
        if (this.selectedEntity) {
            var sb = this.getEntityBounds(this.selectedEntity);
            var ssp = this._worldToScreen(sb.x, sb.y);
            var sx = ssp.x - 3;
            var sy = ssp.y - 3;
            var sw = sb.width + 6;
            var sh = sb.height + 6;

            ctx.save();

            // Selection box
            ctx.strokeStyle = '#44aaff';
            ctx.lineWidth = 2;
            ctx.setLineDash([]);
            ctx.strokeRect(sx, sy, sw, sh);

            // Corner handles
            ctx.fillStyle = '#44aaff';
            var hSize = 5;
            ctx.fillRect(sx,            sy,            hSize, hSize);
            ctx.fillRect(sx + sw - hSize, sy,          hSize, hSize);
            ctx.fillRect(sx,            sy + sh - hSize, hSize, hSize);
            ctx.fillRect(sx + sw - hSize, sy + sh - hSize, hSize, hSize);

            // Delete handle — red X at top-right
            var dx = sx + sw + 3;
            var dy = sy - 14;
            ctx.fillStyle = '#ff4444';
            ctx.fillRect(dx - 7, dy, 14, 14);
            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(dx - 3, dy + 3);  ctx.lineTo(dx + 3, dy + 11);
            ctx.stroke();
            ctx.beginPath();
            ctx.moveTo(dx + 3, dy + 3);  ctx.lineTo(dx - 3, dy + 11);
            ctx.stroke();

            ctx.restore();
        }

        // ── Context menu ──────────────────────────────────────────────────────
        if (this.contextMenu && this.contextMenu.items.length > 0) {
            var itemH = 28;
            var menuW = 180;
            var items = this.contextMenu.items;
            var menuH = items.length * itemH;
            var mx = this._clampedMenuX();
            var my = this._clampedMenuY();
            var mouseS = this._lastMouseScreen;

            ctx.save();

            // Background
            ctx.fillStyle = 'rgba(10,15,30,0.95)';
            ctx.fillRect(mx, my, menuW, menuH);
            ctx.strokeStyle = '#44aaff';
            ctx.lineWidth = 1;
            ctx.strokeRect(mx, my, menuW, menuH);

            for (var mi = 0; mi < items.length; mi++) {
                var iy = my + mi * itemH;

                // Hover row highlight
                if (mouseS.x >= mx && mouseS.x <= mx + menuW &&
                    mouseS.y >= iy && mouseS.y <= iy + itemH) {
                    ctx.fillStyle = 'rgba(68,170,255,0.2)';
                    ctx.fillRect(mx + 1, iy + 1, menuW - 2, itemH - 2);
                }

                // Separator line
                if (mi > 0) {
                    ctx.strokeStyle = 'rgba(68,170,255,0.2)';
                    ctx.lineWidth = 0.5;
                    ctx.beginPath();
                    ctx.moveTo(mx + 8, iy);
                    ctx.lineTo(mx + menuW - 8, iy);
                    ctx.stroke();
                }

                // Label
                ctx.fillStyle = '#c8e6ff';
                ctx.font = '12px "IBM Plex Mono", monospace';
                ctx.textBaseline = 'middle';
                ctx.fillText(items[mi].label, mx + 10, iy + itemH / 2);
            }

            ctx.restore();
        }
    }
}

// ---------------------------------------------------------------------------
// Auto-init: poll until window._engine is available
// ---------------------------------------------------------------------------
var _editorInitInterval = setInterval(function () {
    if (window._engine) {
        window._sceneEditor = new SceneEditor(window._engine);
        clearInterval(_editorInitInterval);
    }
}, 100);
