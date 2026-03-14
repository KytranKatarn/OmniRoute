(function () {
    'use strict';

    // =========================================================================
    // Section 1: State + Helpers
    // =========================================================================

    var API_BASE = '/tools/game-studio';

    var _currentGameId = null;
    var _currentGame = null;
    var _scenes = [];
    var _sceneMap = {};
    var _currentSceneId = null;
    var _gameConfig = null;
    var _monacoEditor = null;
    var _activeTab = 'config';
    var _aiHistory = [];
    var _previewTimer = null;
    var _monacoReady = false;

    var DEFAULT_SHOOTER_CONFIG = {
        title: 'Top-Down Shooter',
        type: 'top_down_shooter',
        map: { width: 1200, height: 800, backgroundColor: '#111' },
        player: { x: 600, y: 400, speed: 200, health: 100, size: 20, color: '#4af', fireRate: 0.2 },
        enemies: [
            { x: 200, y: 200, speed: 80, health: 30, size: 16, color: '#f44', ai: 'chase' },
            { x: 1000, y: 200, speed: 80, health: 30, size: 16, color: '#f44', ai: 'chase' },
            { x: 200, y: 600, speed: 60, health: 40, size: 18, color: '#f84', ai: 'patrol' },
            { x: 1000, y: 600, speed: 60, health: 40, size: 18, color: '#f84', ai: 'patrol' },
            { x: 600, y: 100, speed: 40, health: 80, size: 24, color: '#f00', ai: 'circle' }
        ],
        bullets: { speed: 400, size: 4, color: '#ff0', damage: 10 },
        walls: [
            { x: 0, y: 0, width: 1200, height: 10, color: '#555' },
            { x: 0, y: 790, width: 1200, height: 10, color: '#555' },
            { x: 0, y: 0, width: 10, height: 800, color: '#555' },
            { x: 1190, y: 0, width: 10, height: 800, color: '#555' }
        ],
        ui: { showScore: true, showHealth: true, showMinimap: false }
    };

    function api(method, path, body) {
        var opts = {
            method: method,
            headers: { 'Content-Type': 'application/json' }
        };
        if (body !== undefined) {
            opts.body = JSON.stringify(body);
        }
        return fetch(API_BASE + path, opts).then(function (r) {
            return r.json();
        });
    }

    function toast(msg) {
        var el = document.createElement('div');
        el.textContent = msg;
        el.style.cssText = 'position:fixed;bottom:24px;right:24px;background:#1a3a2a;color:#4af;border:1px solid #4af;padding:10px 18px;border-radius:4px;z-index:9999;font-family:monospace;font-size:13px;';
        document.body.appendChild(el);
        setTimeout(function () {
            if (el.parentNode) el.parentNode.removeChild(el);
        }, 3000);
    }

    function openNewGameModal() {
        var m = document.getElementById('gsNewGameModal');
        if (m) m.style.display = 'flex';
    }

    function openNewSceneModal() {
        var m = document.getElementById('gsNewSceneModal');
        if (m) m.style.display = 'flex';
    }

    window.closeModal = function (id) {
        var m = document.getElementById(id);
        if (m) m.style.display = 'none';
    };

    function clearEl(el) {
        while (el.firstChild) {
            el.removeChild(el.firstChild);
        }
    }

    // =========================================================================
    // Section 2: Dashboard
    // =========================================================================

    function loadDashboard() {
        var dashboard = document.getElementById('gsDashboard');
        var builder = document.getElementById('gsBuilder');
        if (dashboard) dashboard.style.display = '';
        if (builder) builder.style.display = 'none';

        api('GET', '/api/games').then(function (data) {
            var grid = document.getElementById('gsProjectGrid');
            if (!grid) return;
            clearEl(grid);

            if (data.games && data.games.length > 0) {
                data.games.forEach(function (game) {
                    var card = document.createElement('div');
                    card.className = 'gs-project-card';
                    card.onclick = function () { openProject(game.id); };

                    var title = document.createElement('div');
                    title.className = 'gs-project-title';
                    title.textContent = game.title;

                    var meta = document.createElement('div');
                    meta.className = 'gs-project-meta';
                    meta.textContent = (game.engine_type || 'custom') + ' · ' + (game.status || 'draft');

                    var progress = document.createElement('div');
                    progress.className = 'gs-project-progress';
                    var bar = document.createElement('div');
                    bar.className = 'gs-project-progress-bar';
                    bar.style.width = (game.progress || 0) + '%';
                    progress.appendChild(bar);

                    card.appendChild(title);
                    card.appendChild(meta);
                    card.appendChild(progress);
                    grid.appendChild(card);
                });
            } else {
                var empty = document.createElement('div');
                empty.className = 'gs-empty-state';
                empty.textContent = 'No projects yet. Create one below!';
                grid.appendChild(empty);
            }
        }).catch(function (e) {
            console.error('Failed to load games:', e);
        });

        renderTemplateCards();
    }

    function renderTemplateCards() {
        var container = document.getElementById('gsTemplateGrid');
        if (!container) return;
        clearEl(container);

        var templates = [
            {
                id: 'top_down_shooter',
                name: 'Top-Down Shooter',
                desc: 'Enemies, bullets, walls — ready to play.',
                active: true
            },
            {
                id: 'blank',
                name: 'Blank Canvas',
                desc: 'Start from scratch.',
                active: true
            },
            {
                id: 'space_explorer',
                name: 'Space Explorer',
                desc: 'Coming soon.',
                active: false
            },
            {
                id: 'base_builder',
                name: 'Base Builder',
                desc: 'Coming soon.',
                active: false
            }
        ];

        templates.forEach(function (tpl) {
            var card = document.createElement('div');
            card.className = 'gs-template-card' + (tpl.active ? '' : ' gs-coming-soon');

            var name = document.createElement('div');
            name.className = 'gs-template-name';
            name.textContent = tpl.name;

            var desc = document.createElement('div');
            desc.className = 'gs-template-desc';
            desc.textContent = tpl.desc;

            card.appendChild(name);
            card.appendChild(desc);

            if (tpl.active) {
                card.onclick = function () {
                    var titleInput = document.getElementById('gsNewGameName');
                    if (titleInput) titleInput.value = tpl.name + ' ' + new Date().getFullYear();
                    var tplInput = document.getElementById('gsNewGameTemplate');
                    if (tplInput) tplInput.value = tpl.id;
                    openNewGameModal();
                };
            }

            container.appendChild(card);
        });
    }

    // =========================================================================
    // Section 3: Game CRUD + Scene Management
    // =========================================================================

    window.createGame = function () {
        var nameEl = document.getElementById('gsNewGameName');
        var tplEl = document.getElementById('gsNewGameTemplate');
        var title = nameEl ? nameEl.value.trim() : 'New Game';
        var template = tplEl ? tplEl.value : 'blank';

        if (!title) { toast('Enter a project name'); return; }

        api('POST', '/api/games', { title: title, engine: 'canvas2d', template: template })
            .then(function (data) {
                if (!data.game) { toast('Failed to create game'); return; }
                var gameId = data.game.id;
                closeModal('gsNewGameModal');

                if (template === 'top_down_shooter') {
                    return api('POST', '/api/games/' + gameId + '/scenes', {
                        name: 'Main',
                        scene_data: DEFAULT_SHOOTER_CONFIG
                    }).then(function () {
                        openProject(gameId);
                    });
                } else {
                    openProject(gameId);
                }
            })
            .catch(function (e) {
                console.error(e);
                toast('Error creating game');
            });
    };

    function openProject(gameId) {
        _currentGameId = gameId;

        var dashboard = document.getElementById('gsDashboard');
        var builder = document.getElementById('gsBuilder');
        if (dashboard) dashboard.style.display = 'none';
        if (builder) builder.style.display = '';

        Promise.all([
            api('GET', '/api/games/' + gameId),
            api('GET', '/api/games/' + gameId + '/scenes')
        ]).then(function (results) {
            var gameData = results[0];
            var scenesData = results[1];

            _currentGame = gameData.game || gameData;
            _scenes = scenesData.scenes || [];
            _sceneMap = {};
            _scenes.forEach(function (s) { _sceneMap[s.id] = s; });

            // Update title
            var titleEl = document.getElementById('gsGameTitle');
            if (titleEl) titleEl.value = _currentGame.title || 'Untitled';

            // Update project selector
            updateProjectSelector();

            // Render scene list
            renderSceneList();

            // Load first scene
            if (_scenes.length > 0) {
                loadScene(_scenes[0].id);
            } else {
                _gameConfig = JSON.parse(JSON.stringify(DEFAULT_SHOOTER_CONFIG));
                renderConfigEditor();
                refreshPreview();
            }
        }).catch(function (e) {
            console.error('Failed to open project:', e);
            toast('Error loading project');
        });
    }

    function updateProjectSelector() {
        api('GET', '/api/games').then(function (data) {
            var sel = document.getElementById('gsProjectSelector');
            if (!sel) return;
            clearEl(sel);
            (data.games || []).forEach(function (g) {
                var opt = document.createElement('option');
                opt.value = g.id;
                opt.textContent = g.title;
                if (g.id === _currentGameId) opt.selected = true;
                sel.appendChild(opt);
            });
        });
    }

    window.switchProject = function (id) {
        if (id && id !== _currentGameId) {
            openProject(parseInt(id, 10));
        }
    };

    function renderSceneList() {
        var list = document.getElementById('gsSceneList');
        if (!list) return;
        clearEl(list);

        _scenes.forEach(function (scene) {
            var item = document.createElement('div');
            item.className = 'gs-scene-item' + (scene.id === _currentSceneId ? ' active' : '');
            item.textContent = scene.name || ('Scene ' + scene.scene_order);
            item.onclick = function () { loadScene(scene.id); };
            list.appendChild(item);
        });

        var addBtn = document.createElement('button');
        addBtn.className = 'gs-add-scene-btn';
        addBtn.textContent = '+ New Scene';
        addBtn.onclick = openNewSceneModal;
        list.appendChild(addBtn);
    }

    function loadScene(sceneId) {
        _currentSceneId = sceneId;
        var scene = _sceneMap[sceneId];
        if (!scene) return;

        var data = scene.scene_data;
        if (typeof data === 'string') {
            try { data = JSON.parse(data); } catch (e) { data = {}; }
        }
        _gameConfig = data || JSON.parse(JSON.stringify(DEFAULT_SHOOTER_CONFIG));

        renderSceneList();

        if (_activeTab === 'config') {
            renderConfigEditor();
        } else if (_activeTab === 'code' && _monacoEditor) {
            _monacoEditor.setValue(JSON.stringify(_gameConfig, null, 2));
        }

        refreshPreview();
    }

    window.createScene = function () {
        var nameEl = document.getElementById('gsNewSceneName');
        var name = nameEl ? nameEl.value.trim() : 'New Scene';
        if (!name) { toast('Enter a scene name'); return; }

        api('POST', '/api/games/' + _currentGameId + '/scenes', {
            name: name,
            scene_data: {}
        }).then(function (data) {
            closeModal('gsNewSceneModal');
            if (nameEl) nameEl.value = '';
            return api('GET', '/api/games/' + _currentGameId + '/scenes');
        }).then(function (data) {
            _scenes = data.scenes || [];
            _sceneMap = {};
            _scenes.forEach(function (s) { _sceneMap[s.id] = s; });
            renderSceneList();
            if (_scenes.length > 0) {
                loadScene(_scenes[_scenes.length - 1].id);
            }
        }).catch(function (e) {
            console.error(e);
            toast('Error creating scene');
        });
    };

    // =========================================================================
    // Section 4: Config Editor
    // =========================================================================

    function makeLabel(text) {
        var lbl = document.createElement('label');
        lbl.className = 'gs-config-label';
        lbl.textContent = text;
        return lbl;
    }

    function makeField(labelText, input) {
        var row = document.createElement('div');
        row.className = 'gs-config-field';
        row.appendChild(makeLabel(labelText));
        row.appendChild(input);
        return row;
    }

    function makeRangeInput(value, min, max, step, onChange) {
        var wrap = document.createElement('div');
        wrap.className = 'gs-range-wrap';

        var input = document.createElement('input');
        input.type = 'range';
        input.min = min;
        input.max = max;
        input.step = step;
        input.value = value;

        var display = document.createElement('span');
        display.className = 'gs-range-val';
        display.textContent = value;

        input.oninput = function () {
            display.textContent = input.value;
            onChange(parseFloat(input.value));
        };

        wrap.appendChild(input);
        wrap.appendChild(display);
        return wrap;
    }

    function makeNumberInput(value, onChange) {
        var input = document.createElement('input');
        input.type = 'number';
        input.className = 'gs-number-input';
        input.value = value;
        input.onchange = function () { onChange(parseFloat(input.value) || 0); };
        return input;
    }

    function makeColorInput(value, onChange) {
        var input = document.createElement('input');
        input.type = 'color';
        input.className = 'gs-color-input';
        input.value = value || '#ffffff';
        input.oninput = function () { onChange(input.value); };
        return input;
    }

    function makeCheckbox(checked, labelText, onChange) {
        var wrap = document.createElement('div');
        wrap.className = 'gs-checkbox-wrap';
        var input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = !!checked;
        input.onchange = function () { onChange(input.checked); };
        var lbl = document.createElement('label');
        lbl.textContent = labelText;
        wrap.appendChild(input);
        wrap.appendChild(lbl);
        return wrap;
    }

    function makeSection(title) {
        var section = document.createElement('div');
        section.className = 'gs-config-section';
        var h = document.createElement('div');
        h.className = 'gs-config-section-title';
        h.textContent = title;
        section.appendChild(h);
        return section;
    }

    function renderConfigEditor() {
        var container = document.getElementById('gsConfigEditor');
        if (!container || !_gameConfig) return;
        clearEl(container);

        var cfg = _gameConfig;

        // --- Player Section ---
        var playerSec = makeSection('Player');

        playerSec.appendChild(makeField('Speed', makeRangeInput(
            cfg.player ? cfg.player.speed : 200, 50, 500, 10,
            function (v) { if (!cfg.player) cfg.player = {}; cfg.player.speed = v; debouncePreview(); }
        )));
        playerSec.appendChild(makeField('Health', makeNumberInput(
            cfg.player ? cfg.player.health : 100,
            function (v) { if (!cfg.player) cfg.player = {}; cfg.player.health = v; debouncePreview(); }
        )));
        playerSec.appendChild(makeField('Size', makeRangeInput(
            cfg.player ? cfg.player.size : 20, 5, 50, 1,
            function (v) { if (!cfg.player) cfg.player = {}; cfg.player.size = v; debouncePreview(); }
        )));
        playerSec.appendChild(makeField('Color', makeColorInput(
            cfg.player ? cfg.player.color : '#4af',
            function (v) { if (!cfg.player) cfg.player = {}; cfg.player.color = v; debouncePreview(); }
        )));
        playerSec.appendChild(makeField('Fire Rate', makeRangeInput(
            cfg.player ? cfg.player.fireRate : 0.2, 0.05, 1.0, 0.05,
            function (v) { if (!cfg.player) cfg.player = {}; cfg.player.fireRate = v; debouncePreview(); }
        )));
        container.appendChild(playerSec);

        // --- Enemies Section ---
        var enemies = cfg.enemies || [];
        var enemySec = makeSection('Enemies (' + enemies.length + ')');

        enemies.forEach(function (enemy, idx) {
            var card = document.createElement('div');
            card.className = 'gs-entity-card';

            var header = document.createElement('div');
            header.className = 'gs-entity-header';

            var badge = document.createElement('span');
            badge.className = 'gs-entity-badge';
            badge.textContent = enemy.ai || 'chase';

            var removeBtn = document.createElement('button');
            removeBtn.className = 'gs-remove-btn';
            removeBtn.textContent = '✕';
            removeBtn.onclick = (function (i) {
                return function () { removeEnemy(i); };
            }(idx));

            header.appendChild(badge);
            header.appendChild(removeBtn);
            card.appendChild(header);

            var fields = document.createElement('div');
            fields.className = 'gs-entity-fields';

            fields.appendChild(makeField('X', makeNumberInput(enemy.x || 0,
                function (v) { cfg.enemies[idx].x = v; debouncePreview(); })));
            fields.appendChild(makeField('Y', makeNumberInput(enemy.y || 0,
                function (v) { cfg.enemies[idx].y = v; debouncePreview(); })));
            fields.appendChild(makeField('Speed', makeNumberInput(enemy.speed || 80,
                function (v) { cfg.enemies[idx].speed = v; debouncePreview(); })));
            fields.appendChild(makeField('Health', makeNumberInput(enemy.health || 30,
                function (v) { cfg.enemies[idx].health = v; debouncePreview(); })));
            fields.appendChild(makeField('Size', makeNumberInput(enemy.size || 16,
                function (v) { cfg.enemies[idx].size = v; debouncePreview(); })));
            fields.appendChild(makeField('Color', makeColorInput(enemy.color || '#f44',
                function (v) { cfg.enemies[idx].color = v; debouncePreview(); })));

            var aiSelect = document.createElement('select');
            aiSelect.className = 'gs-select-input';
            ['chase', 'patrol', 'circle'].forEach(function (opt) {
                var o = document.createElement('option');
                o.value = opt;
                o.textContent = opt;
                if (enemy.ai === opt) o.selected = true;
                aiSelect.appendChild(o);
            });
            aiSelect.onchange = (function (i) {
                return function () {
                    cfg.enemies[i].ai = aiSelect.value;
                    debouncePreview();
                };
            }(idx));
            fields.appendChild(makeField('AI', aiSelect));

            card.appendChild(fields);
            enemySec.appendChild(card);
        });

        var addEnemyBtn = document.createElement('button');
        addEnemyBtn.className = 'gs-add-btn';
        addEnemyBtn.textContent = '+ Add Enemy';
        addEnemyBtn.onclick = addEnemy;
        enemySec.appendChild(addEnemyBtn);
        container.appendChild(enemySec);

        // --- Map Section ---
        var mapSec = makeSection('Map');
        var map = cfg.map || {};

        mapSec.appendChild(makeField('Width', makeNumberInput(map.width || 1200,
            function (v) { if (!cfg.map) cfg.map = {}; cfg.map.width = v; debouncePreview(); })));
        mapSec.appendChild(makeField('Height', makeNumberInput(map.height || 800,
            function (v) { if (!cfg.map) cfg.map = {}; cfg.map.height = v; debouncePreview(); })));
        mapSec.appendChild(makeField('Background', makeColorInput(map.backgroundColor || '#111',
            function (v) { if (!cfg.map) cfg.map = {}; cfg.map.backgroundColor = v; debouncePreview(); })));
        container.appendChild(mapSec);

        // --- Walls Section ---
        var walls = cfg.walls || [];
        var wallSec = makeSection('Walls');

        walls.forEach(function (wall, idx) {
            var card = document.createElement('div');
            card.className = 'gs-entity-card';

            var header = document.createElement('div');
            header.className = 'gs-entity-header';
            var badge = document.createElement('span');
            badge.className = 'gs-entity-badge';
            badge.textContent = 'Wall ' + (idx + 1);
            var removeBtn = document.createElement('button');
            removeBtn.className = 'gs-remove-btn';
            removeBtn.textContent = '✕';
            removeBtn.onclick = (function (i) {
                return function () { removeWall(i); };
            }(idx));
            header.appendChild(badge);
            header.appendChild(removeBtn);
            card.appendChild(header);

            var fields = document.createElement('div');
            fields.className = 'gs-entity-fields';
            fields.appendChild(makeField('X', makeNumberInput(wall.x || 0,
                function (v) { cfg.walls[idx].x = v; debouncePreview(); })));
            fields.appendChild(makeField('Y', makeNumberInput(wall.y || 0,
                function (v) { cfg.walls[idx].y = v; debouncePreview(); })));
            fields.appendChild(makeField('Width', makeNumberInput(wall.width || 100,
                function (v) { cfg.walls[idx].width = v; debouncePreview(); })));
            fields.appendChild(makeField('Height', makeNumberInput(wall.height || 10,
                function (v) { cfg.walls[idx].height = v; debouncePreview(); })));
            card.appendChild(fields);
            wallSec.appendChild(card);
        });

        var addWallBtn = document.createElement('button');
        addWallBtn.className = 'gs-add-btn';
        addWallBtn.textContent = '+ Add Wall';
        addWallBtn.onclick = addWall;
        wallSec.appendChild(addWallBtn);
        container.appendChild(wallSec);

        // --- UI Section ---
        var uiSec = makeSection('UI');
        var ui = cfg.ui || {};

        uiSec.appendChild(makeCheckbox(ui.showScore, 'Show Score', function (v) {
            if (!cfg.ui) cfg.ui = {};
            cfg.ui.showScore = v;
            debouncePreview();
        }));
        uiSec.appendChild(makeCheckbox(ui.showHealth, 'Show Health', function (v) {
            if (!cfg.ui) cfg.ui = {};
            cfg.ui.showHealth = v;
            debouncePreview();
        }));
        uiSec.appendChild(makeCheckbox(ui.showMinimap, 'Show Minimap', function (v) {
            if (!cfg.ui) cfg.ui = {};
            cfg.ui.showMinimap = v;
            debouncePreview();
        }));
        container.appendChild(uiSec);
    }

    function addEnemy() {
        if (!_gameConfig.enemies) _gameConfig.enemies = [];
        _gameConfig.enemies.push({
            x: Math.floor(Math.random() * 1000) + 100,
            y: Math.floor(Math.random() * 600) + 100,
            speed: 80,
            health: 30,
            size: 16,
            color: '#f44',
            ai: 'chase'
        });
        renderConfigEditor();
        debouncePreview();
    }

    function removeEnemy(idx) {
        if (_gameConfig.enemies) {
            _gameConfig.enemies.splice(idx, 1);
        }
        renderConfigEditor();
        debouncePreview();
    }

    function addWall() {
        if (!_gameConfig.walls) _gameConfig.walls = [];
        _gameConfig.walls.push({ x: 100, y: 100, width: 200, height: 20, color: '#555' });
        renderConfigEditor();
        debouncePreview();
    }

    function removeWall(idx) {
        if (_gameConfig.walls) {
            _gameConfig.walls.splice(idx, 1);
        }
        renderConfigEditor();
        debouncePreview();
    }

    // =========================================================================
    // Section 5: Monaco + Tabs
    // =========================================================================

    function initMonaco(cb) {
        if (typeof require === 'undefined') {
            // Monaco not available, skip
            if (cb) cb();
            return;
        }

        require.config({
            paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs' }
        });

        require(['vs/editor/editor.main'], function () {
            var container = document.getElementById('gsCodeContainer');
            if (!container) { if (cb) cb(); return; }

            _monacoEditor = monaco.editor.create(container, {
                value: _gameConfig ? JSON.stringify(_gameConfig, null, 2) : '{}',
                language: 'json',
                theme: 'vs-dark',
                automaticLayout: true,
                minimap: { enabled: false },
                fontSize: 13,
                scrollBeyondLastLine: false
            });

            var changeTimer = null;
            _monacoEditor.onDidChangeModelContent(function () {
                if (changeTimer) clearTimeout(changeTimer);
                changeTimer = setTimeout(function () {
                    try {
                        var val = _monacoEditor.getValue();
                        var parsed = JSON.parse(val);
                        _gameConfig = parsed;
                        debouncePreview();
                    } catch (e) {
                        // Invalid JSON — don't update
                    }
                }, 800);
            });

            _monacoReady = true;
            if (cb) cb();
        });
    }

    window.setTab = function (tab) {
        _activeTab = tab;

        var configContainer = document.getElementById('gsConfigContainer');
        var codeContainer = document.getElementById('gsCodeContainer');
        var previewContainer = document.getElementById('gsPreviewContainer');

        if (configContainer) configContainer.style.display = tab === 'config' ? '' : 'none';
        if (codeContainer) codeContainer.style.display = tab === 'code' ? '' : 'none';
        if (previewContainer) previewContainer.style.display = tab === 'preview' ? '' : 'none';

        // Update tab button active states
        var tabs = document.querySelectorAll('.gs-tab-btn');
        tabs.forEach(function (btn) {
            btn.classList.remove('active');
            if (btn.dataset.tab === tab) btn.classList.add('active');
        });

        if (tab === 'code') {
            if (_monacoEditor && _gameConfig) {
                _monacoEditor.setValue(JSON.stringify(_gameConfig, null, 2));
            } else if (!_monacoReady) {
                initMonaco(function () {
                    if (_monacoEditor && _gameConfig) {
                        _monacoEditor.setValue(JSON.stringify(_gameConfig, null, 2));
                    }
                });
            }
        } else if (tab === 'preview') {
            refreshPreview();
        } else if (tab === 'config') {
            renderConfigEditor();
        }
    };

    // =========================================================================
    // Section 6: Preview
    // =========================================================================

    function refreshPreview() {
        var iframe = document.getElementById('gsPreviewFrame');
        if (!iframe) return;

        var html = '<!DOCTYPE html><html><head><style>*{margin:0;padding:0;}body{overflow:hidden;background:#000;}canvas{display:block;}</style></head><body>';
        html += '<canvas id="gameCanvas"></canvas>';
        html += '<scr' + 'ipt src="/static/js/game-engine.js"></scr' + 'ipt>';
        html += '</body></html>';

        iframe.srcdoc = html;
        iframe.onload = function () {
            if (_gameConfig) {
                try {
                    iframe.contentWindow.postMessage({ type: 'loadConfig', config: _gameConfig }, '*');
                } catch (e) {
                    console.warn('Could not post config to iframe:', e);
                }
            }
        };
    }

    function debouncePreview() {
        if (_previewTimer) clearTimeout(_previewTimer);
        _previewTimer = setTimeout(function () {
            if (_activeTab === 'preview') {
                refreshPreview();
            }
            // Sync monaco if code tab was open
            if (_activeTab === 'code' && _monacoEditor && _gameConfig) {
                var current = _monacoEditor.getValue();
                var updated = JSON.stringify(_gameConfig, null, 2);
                if (current !== updated) {
                    _monacoEditor.setValue(updated);
                }
            }
        }, 500);
    }

    // =========================================================================
    // Section 7: AI Chat
    // =========================================================================

    window.sendAiChat = function () {
        var input = document.getElementById('gsAiInput');
        if (!input) return;
        var message = input.value.trim();
        if (!message) return;
        input.value = '';

        addAiEntry('user', message);

        var context = {};
        if (_gameConfig) {
            try {
                context.current_config = JSON.stringify(_gameConfig);
            } catch (e) {}
        }

        api('POST', '/api/ai/chat', {
            message: message,
            game_id: _currentGameId,
            context: context
        }).then(function (data) {
            if (!data.success) {
                addAiEntry('assistant', data.error || 'Error from AI');
                return;
            }

            var responseText = data.response || '';
            var configChanged = false;

            // Try direct JSON parse
            try {
                var parsed = JSON.parse(responseText);
                if (parsed && typeof parsed === 'object') {
                    _gameConfig = mergeConfig(_gameConfig || {}, parsed);
                    configChanged = true;
                    addAiEntry('assistant', 'Config updated via AI.');
                }
            } catch (e1) {
                // Try regex for ```json block
                var match = responseText.match(/```json\s*([\s\S]*?)\s*```/);
                if (match) {
                    try {
                        var patchObj = JSON.parse(match[1]);
                        _gameConfig = mergeConfig(_gameConfig || {}, patchObj);
                        configChanged = true;
                        addAiEntry('assistant', responseText.replace(/```json[\s\S]*?```/, '[Config patch applied]'));
                    } catch (e2) {
                        addAiEntry('assistant', responseText);
                    }
                } else {
                    addAiEntry('assistant', responseText);
                }
            }

            if (configChanged) {
                renderConfigEditor();
                if (_activeTab === 'preview') refreshPreview();
                if (_monacoEditor) _monacoEditor.setValue(JSON.stringify(_gameConfig, null, 2));
                toast('AI applied changes');
            }
        }).catch(function (e) {
            console.error(e);
            addAiEntry('assistant', 'Network error contacting AI.');
        });
    };

    function mergeConfig(base, patch) {
        if (!base || typeof base !== 'object') return patch;
        if (!patch || typeof patch !== 'object') return base;

        var result = {};
        var allKeys = Object.keys(base).concat(
            Object.keys(patch).filter(function (k) { return !(k in base); })
        );

        allKeys.forEach(function (key) {
            if (!(key in patch)) {
                result[key] = base[key];
            } else if (!(key in base)) {
                result[key] = patch[key];
            } else if (Array.isArray(patch[key])) {
                result[key] = patch[key];
            } else if (
                typeof base[key] === 'object' && base[key] !== null &&
                typeof patch[key] === 'object' && patch[key] !== null &&
                !Array.isArray(base[key])
            ) {
                result[key] = mergeConfig(base[key], patch[key]);
            } else {
                result[key] = patch[key];
            }
        });

        return result;
    }

    function addAiEntry(role, text) {
        var history = document.getElementById('gsAiHistory');
        if (!history) return;

        var entry = document.createElement('div');
        entry.className = 'gs-ai-entry gs-ai-' + role;

        var label = document.createElement('div');
        label.className = 'gs-ai-role';
        label.textContent = role === 'user' ? 'You' : 'AI';

        var content = document.createElement('div');
        content.className = 'gs-ai-content';
        content.textContent = text;

        entry.appendChild(label);
        entry.appendChild(content);
        history.appendChild(entry);
        history.scrollTop = history.scrollHeight;

        _aiHistory.push({ role: role, text: text });
    }

    // =========================================================================
    // Section 8: Save + Properties + Init
    // =========================================================================

    window.saveGame = function () {
        if (!_currentGameId) { toast('No project open'); return; }

        var titleEl = document.getElementById('gsGameTitle');
        var title = titleEl ? titleEl.value.trim() : (_currentGame ? _currentGame.title : 'Untitled');

        // Save scene data first
        var saveScenePromise = Promise.resolve();
        if (_currentSceneId && _gameConfig) {
            saveScenePromise = api('PUT', '/api/games/' + _currentGameId + '/scenes/' + _currentSceneId, {
                scene_data: _gameConfig
            });
        }

        saveScenePromise.then(function () {
            return api('PUT', '/api/games/' + _currentGameId, {
                title: title,
                settings: _gameConfig
            });
        }).then(function (data) {
            toast('Project saved');
            if (_currentGame) _currentGame.title = title;
        }).catch(function (e) {
            console.error(e);
            toast('Save failed');
        });
    };

    window.toggleRightPanel = function () {
        var panel = document.getElementById('gsRightPanel');
        if (panel) panel.classList.toggle('gs-right-collapsed');
    };

    window.restartPreview = function () {
        var iframe = document.getElementById('gsPreviewFrame');
        if (!iframe) return;
        try {
            iframe.contentWindow.postMessage({ type: 'restart' }, '*');
        } catch (e) {
            // iframe may have navigated; do a full refresh
            refreshPreview();
        }
    };

    // Expose helpers for HTML onclick use
    window.openNewGameModal = openNewGameModal;
    window.openNewSceneModal = openNewSceneModal;
    window.loadDashboard = loadDashboard;
    window.openProject = openProject;
    window.addEnemy = addEnemy;
    window.removeEnemy = removeEnemy;
    window.addWall = addWall;
    window.removeWall = removeWall;
    window.refreshPreview = refreshPreview;
    window.sendAiChat = window.sendAiChat;

    // Init
    document.addEventListener('DOMContentLoaded', function () {
        initMonaco(function () {
            loadDashboard();
        });
    });

}());
