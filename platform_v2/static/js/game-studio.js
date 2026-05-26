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

    var _editMode = false;

    window.toggleEditMode = function () {
        _editMode = !_editMode;
        var iframe = document.getElementById('gsPreviewFrame');
        if (iframe && iframe.contentWindow) {
            iframe.contentWindow.postMessage({ type: _editMode ? 'enableEditor' : 'disableEditor' }, '*');
        }
        var btn = document.querySelector('[data-action="edit-mode"]');
        if (btn) btn.classList.toggle('active', _editMode);
        toast(_editMode ? 'Edit Mode ON' : 'Edit Mode OFF');
    };

    window.addEventListener('message', function (e) {
        if (e.data && e.data.type === 'configUpdated') {
            _gameConfig = e.data.config;
            if (_activeTab === 'config') renderConfigEditor();
        }
        if (e.data && e.data.type === 'entitySelected' && e.data.entity) {
            // Could update properties panel - for now just log
        }
    });

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

    var DEFAULT_EXPLORER_CONFIG = {
        title: 'Space Explorer',
        type: 'space_explorer',
        mode: 'galaxy',
        map: { width: 1200, height: 800, backgroundColor: '#05050f' },
        player: { x: 600, y: 400, speed: 250, health: 100, size: 14, color: '#4af' },
        stars: [
            { x: 300, y: 200, name: 'Alpha Centauri', type: 'yellow_dwarf', size: 18, color: '#ffe066' },
            { x: 900, y: 300, name: 'Sirius', type: 'blue_giant', size: 22, color: '#66ccff' },
            { x: 500, y: 600, name: 'Betelgeuse', type: 'red_giant', size: 26, color: '#ff6633' }
        ],
        ui: { showMap: true, showFuel: true }
    };

    var DEFAULT_BUILDER_CONFIG = {
        title: 'Base Builder',
        type: 'base_builder',
        map: { width: 1280, height: 896, backgroundColor: '#1a2a1a', gridSize: 32 },
        player: { x: 640, y: 448, speed: 160, health: 100, size: 14, color: '#4af' },
        resources: { wood: 100, stone: 50, food: 80 },
        buildings: [
            { x: 608, y: 416, type: 'building_shelter', width: 64, height: 64 }
        ],
        ui: { showResources: true, showMinimap: true }
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
                desc: 'Explore star systems and planets.',
                active: true
            },
            {
                id: 'base_builder',
                name: 'Base Builder',
                desc: 'Build and defend your base.',
                active: true
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
                } else if (template === 'space_explorer') {
                    return api('POST', '/api/games/' + gameId + '/scenes', {
                        name: 'Galaxy',
                        scene_data: DEFAULT_EXPLORER_CONFIG
                    }).then(function () {
                        openProject(gameId);
                    });
                } else if (template === 'base_builder') {
                    return api('POST', '/api/games/' + gameId + '/scenes', {
                        name: 'Base Camp',
                        scene_data: DEFAULT_BUILDER_CONFIG
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
        var lobbyTab = document.getElementById('gsLobbyTab');
        var worldTab = document.getElementById('gsWorldTab');

        if (configContainer) configContainer.style.display = tab === 'config' ? '' : 'none';
        if (codeContainer) codeContainer.style.display = tab === 'code' ? '' : 'none';
        if (previewContainer) previewContainer.style.display = tab === 'preview' ? '' : 'none';
        if (lobbyTab) lobbyTab.style.display = tab === 'lobby' ? '' : 'none';
        if (worldTab) worldTab.style.display = tab === 'world' ? '' : 'none';

        // Update tab button active states
        var tabs = document.querySelectorAll('.gs-tab, .gs-tab-btn');
        tabs.forEach(function (btn) {
            btn.classList.remove('active', 'gs-tab-active');
            if (btn.dataset.tab === tab) btn.classList.add('active', 'gs-tab-active');
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
        } else if (tab === 'lobby') {
            loadOpenSessions();
            loadProfile();
        } else if (tab === 'world') {
            loadWorldState();
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
        html += '<scr' + 'ipt src="/static/js/game-module-shooter.js"></scr' + 'ipt>';
        html += '<scr' + 'ipt src="/static/js/game-module-explorer.js"></scr' + 'ipt>';
        html += '<scr' + 'ipt src="/static/js/game-module-builder.js"></scr' + 'ipt>';
        html += '<scr' + 'ipt src="/static/js/scene-editor.js"></scr' + 'ipt>';
        html += '<scr' + 'ipt src="/static/js/socket.io.min.js"></scr' + 'ipt>';
        html += '<scr' + 'ipt src="/static/js/game-network.js"></scr' + 'ipt>';
        html += '</body></html>';

        iframe.srcdoc = html;
        iframe.onload = function () {
            if (_gameConfig) {
                try {
                    iframe.contentWindow.postMessage({ type: 'loadConfig', config: _gameConfig }, '*');
                    // Load behaviors if present in config
                    if (_gameConfig.behaviors && Array.isArray(_gameConfig.behaviors) && _gameConfig.behaviors.length > 0) {
                        iframe.contentWindow.postMessage({ type: 'loadBehaviors', behaviors: _gameConfig.behaviors }, '*');
                    }
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

            // Build pipeline triggered — open wizard and start polling
            if (data.build_session) {
                addAiEntry('assistant', data.response || 'Building your game...');
                _buildSessionId = data.build_session && data.build_session.id;
                openBuildWizard();
                document.getElementById('gsBuildInput').style.display = 'none';
                document.getElementById('gsBuildPipeline').style.display = '';
                renderPipelineStages('concept', 'running');
                if (_buildSessionId) pollBuildStatus(_buildSessionId);
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

    // =========================================================================
    // Section 9: AI Build Wizard
    // =========================================================================

    var _buildSessionId = null;
    var _buildProjectId = null;
    var _buildPollTimer = null;

    window.openBuildWizard = function () {
        var modal = document.getElementById('gsBuildWizard');
        if (!modal) return;
        modal.style.display = 'flex';
        document.getElementById('gsBuildInput').style.display = '';
        document.getElementById('gsBuildPipeline').style.display = 'none';
        var desc = document.getElementById('gsBuildDesc');
        if (desc) desc.value = '';
    };

    window.closeBuildWizard = function () {
        var modal = document.getElementById('gsBuildWizard');
        if (modal) modal.style.display = 'none';
        if (_buildPollTimer) { clearTimeout(_buildPollTimer); _buildPollTimer = null; }
    };

    window.startBuild = function () {
        var desc = (document.getElementById('gsBuildDesc') || {}).value || '';
        var type = (document.getElementById('gsBuildType') || {}).value || '';
        desc = desc.trim();
        if (!desc) { toast('Please describe your game'); return; }

        document.getElementById('gsBuildInput').style.display = 'none';
        document.getElementById('gsBuildPipeline').style.display = '';
        renderPipelineStages('concept', 'running');

        api('POST', '/api/ai/build', { description: desc, game_type: type })
            .then(function (data) {
                if (!data.success) { toast('Build failed: ' + (data.error || 'Unknown error')); return; }
                _buildSessionId = data.session && data.session.id;
                if (_buildSessionId) pollBuildStatus(_buildSessionId);
            })
            .catch(function (e) {
                console.error(e);
                toast('Build request failed');
            });
    };

    function pollBuildStatus(sessionId) {
        api('GET', '/api/ai/build/' + sessionId)
            .then(function (data) {
                if (!data.success) return;
                var s = data.session || {};
                var stage = s.current_stage || 'concept';
                var status = s.status || 'running';

                renderPipelineStages(stage, status);

                if (status === 'checkpoint') {
                    showCheckpointReview(s);
                } else if (status === 'complete') {
                    showBuildComplete(s);
                } else if (status === 'running' || status === 'queued') {
                    _buildPollTimer = setTimeout(function () { pollBuildStatus(sessionId); }, 3000);
                } else if (status === 'error') {
                    toast('Build error: ' + (s.error || 'Unknown'));
                }
            })
            .catch(function (e) {
                console.error(e);
                _buildPollTimer = setTimeout(function () { pollBuildStatus(sessionId); }, 5000);
            });
    }

    function renderPipelineStages(currentStage, status) {
        var container = document.getElementById('gsBuildStages');
        if (!container) return;
        var stages = ['concept', 'level', 'mechanics', 'qa'];
        var labels = { concept: 'Concept', level: 'Level', mechanics: 'Mechanics', qa: 'QA' };
        var currentIdx = stages.indexOf(currentStage);

        while (container.firstChild) container.removeChild(container.firstChild);

        stages.forEach(function (s, i) {
            var div = document.createElement('div');
            div.className = 'gs-pipeline-stage';
            if (i < currentIdx) {
                div.classList.add('complete');
            } else if (i === currentIdx) {
                div.classList.add(status === 'checkpoint' ? 'checkpoint' : status === 'complete' ? 'complete' : 'running');
            }
            var circle = document.createElement('div');
            circle.className = 'gs-pipeline-circle';
            var label = document.createElement('div');
            label.className = 'gs-pipeline-label';
            label.textContent = labels[s];
            div.appendChild(circle);
            div.appendChild(label);
            container.appendChild(div);
        });
    }

    function _buildReviewContent(outputText, btnLabel, btnFn) {
        var review = document.getElementById('gsBuildReview');
        if (!review) return;
        while (review.firstChild) review.removeChild(review.firstChild);

        var pre = document.createElement('div');
        pre.className = 'gs-build-output';
        pre.textContent = typeof outputText === 'string' ? outputText : JSON.stringify(outputText, null, 2);

        var row = document.createElement('div');
        row.style.cssText = 'margin-top:0.75rem;text-align:right;';

        var btn = document.createElement('button');
        btn.className = 'gs-toolbar-btn';
        btn.style.cssText = 'background:var(--gs-accent,#4f6);color:#000;';
        btn.textContent = btnLabel;
        btn.addEventListener('click', btnFn);

        row.appendChild(btn);
        review.appendChild(pre);
        review.appendChild(row);
        review.style.display = '';
    }

    function showCheckpointReview(sessionData) {
        _buildReviewContent(
            sessionData.stage_output || '',
            'Approve & Continue',
            window.approveBuildCheckpoint
        );
    }

    function showBuildComplete(sessionData) {
        var review = document.getElementById('gsBuildReview');
        if (!review) return;
        while (review.firstChild) review.removeChild(review.firstChild);

        var pre = document.createElement('div');
        pre.className = 'gs-build-output';
        var output = sessionData.final_config || sessionData.stage_output || '';
        pre.textContent = typeof output === 'string' ? output : JSON.stringify(output, null, 2);

        var row = document.createElement('div');
        row.style.cssText = 'margin-top:0.75rem;text-align:right;';

        var applyBtn = document.createElement('button');
        applyBtn.className = 'gs-toolbar-btn';
        applyBtn.style.cssText = 'background:var(--gs-accent,#4f6);color:#000;';
        applyBtn.textContent = 'Apply & Play';
        applyBtn.addEventListener('click', window.applyBuildResult);

        var dismissBtn = document.createElement('button');
        dismissBtn.className = 'gs-toolbar-btn';
        dismissBtn.style.cssText = 'margin-left:0.5rem;';
        dismissBtn.textContent = 'Dismiss';
        dismissBtn.addEventListener('click', window.closeBuildWizard);

        row.appendChild(applyBtn);
        row.appendChild(dismissBtn);
        review.appendChild(pre);
        review.appendChild(row);
        review.style.display = '';
    }

    window.approveBuildCheckpoint = function () {
        if (!_buildSessionId) return;
        api('POST', '/api/ai/build/' + _buildSessionId + '/approve', {})
            .then(function (data) {
                if (!data.success) { toast('Approve failed'); return; }
                var review = document.getElementById('gsBuildReview');
                if (review) review.style.display = 'none';
                pollBuildStatus(_buildSessionId);
            })
            .catch(function (e) { console.error(e); toast('Approve failed'); });
    };

    window.applyBuildResult = function () {
        if (!_buildSessionId) return;
        api('POST', '/api/ai/build/' + _buildSessionId + '/apply', {})
            .then(function (data) {
                if (!data.success) { toast('Apply failed'); return; }
                closeBuildWizard();
                toast('Game created!');
                loadDashboard();
            })
            .catch(function (e) { console.error(e); toast('Apply failed'); });
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
    window.openBuildWizard = openBuildWizard;
    window.closeBuildWizard = closeBuildWizard;
    window.startBuild = startBuild;
    window.approveBuildCheckpoint = window.approveBuildCheckpoint;
    window.applyBuildResult = window.applyBuildResult;

    // =========================================================================
    // Section N: Multiplayer — Profile, Sessions, World
    // =========================================================================

    var _profile = null;
    var _currentRoomCode = null;

    function loadProfile() {
        api('GET', '/api/profile').then(function (data) {
            _profile = data.profile;
            renderProfile(_profile);
        }).catch(function (e) { console.error('loadProfile', e); });
    }

    function renderProfile(profile) {
        var nameEl = document.getElementById('gsProfileName');
        if (!nameEl) return;
        if (profile) {
            nameEl.textContent = profile.display_name || 'Player #' + profile.id;
        } else {
            nameEl.textContent = '— (no profile)';
        }
    }

    function loadOpenSessions() {
        var list = document.getElementById('gsSessionList');
        if (list) list.innerHTML = '<div class="gs-empty-state">Loading…</div>';
        api('GET', '/api/sessions').then(function (data) {
            var sessions = data.sessions || [];
            if (!list) return;
            if (!sessions.length) {
                list.innerHTML = '<div class="gs-empty-state">No open sessions. Create one!</div>';
                return;
            }
            list.innerHTML = sessions.map(function (s) {
                return '<div class="gs-session-card">' +
                    '<div class="gs-session-info">' +
                        '<span class="gs-room-code">' + (s.room_code || '') + '</span>' +
                        '<span class="gs-session-host">Host: ' + (s.host_name || '?') + '</span>' +
                        '<span class="gs-session-type">' + (s.game_type || '') + '</span>' +
                    '</div>' +
                    '<div class="gs-session-meta">' +
                        '<span class="gs-session-players">' + (s.current_players || 0) + '/' + (s.max_players || 4) + '</span>' +
                        '<span class="gs-session-status gs-status-' + (s.status || '') + '">' + (s.status || '') + '</span>' +
                    '</div>' +
                    '<button class="gs-btn gs-btn-sm gs-btn-primary" onclick="joinMultiplayer(\'' + s.room_code + '\')">' +
                        'Join' +
                    '</button>' +
                '</div>';
            }).join('');
        }).catch(function (e) {
            console.error('loadOpenSessions', e);
            if (list) list.innerHTML = '<div class="gs-empty-state">Failed to load sessions.</div>';
        });
    }

    function loadSessionPlayers(roomCode) {
        api('GET', '/api/sessions/' + roomCode).then(function (data) {
            var players = data.players || [];
            var el = document.getElementById('gsSessionPlayers');
            if (!el) return;
            el.innerHTML = players.length
                ? players.map(function (p) {
                    return '<div class="gs-player-card' + (p.is_host ? ' gs-player-host' : '') + '">' +
                        (p.display_name || '?') +
                        (p.is_host ? ' <span class="gs-host-badge">HOST</span>' : '') +
                    '</div>';
                  }).join('')
                : '<div class="gs-empty-state">No players yet.</div>';
            var startBtn = document.getElementById('gsStartMultiBtn');
            if (startBtn && _profile && players.length) {
                var isHost = players.some(function (p) { return p.is_host && p.profile_id === _profile.id; });
                startBtn.style.display = isHost ? '' : 'none';
            }
        }).catch(function (e) { console.error('loadSessionPlayers', e); });
    }

    // =========================================================================
    // World Map + Market (Phase 5)
    // =========================================================================

    var EFFECT_MAP = {
        health_depot:            { label: 'Health Depot',         affects: ['top_down_shooter'] },
        damage_boost:            { label: 'Damage Boost',         affects: ['top_down_shooter'] },
        enemy_wave_reduction:    { label: 'Enemy Wave Reduction', affects: ['top_down_shooter'] },
        pirate_threat_reduction: { label: 'Pirate Threat ↓',     affects: ['space_explorer'] },
        safe_zone_expansion:     { label: 'Safe Zone ↑',          affects: ['space_explorer'] },
        trade_bonus:             { label: 'Trade Bonus',          affects: ['base_builder', 'space_explorer'] },
        resource_boost:          { label: 'Resource Boost',       affects: ['base_builder'] },
        raid_reduction:          { label: 'Raid Reduction',       affects: ['base_builder'] },
    };

    var _mapStarCache = null;

    function _getMapStars() {
        if (_mapStarCache) return _mapStarCache;
        // Known star positions from DEFAULT_EXPLORER_CONFIG
        _mapStarCache = [
            { x: 300, y: 200, name: 'Alpha Centauri' },
            { x: 900, y: 300, name: 'Sirius' },
            { x: 500, y: 600, name: 'Betelgeuse' },
        ];
        return _mapStarCache;
    }

    var _bgStarsCache = null;

    function _getBgStars(cw, ch) {
        if (_bgStarsCache && _bgStarsCache.cw === cw && _bgStarsCache.ch === ch) return _bgStarsCache.stars;
        var stars = [];
        for (var i = 0; i < 120; i++) {
            stars.push({ x: Math.random() * cw, y: Math.random() * ch });
        }
        _bgStarsCache = { cw: cw, ch: ch, stars: stars };
        return stars;
    }

    function renderWorldMap(data) {
        var canvas = document.getElementById('gsWorldMapCanvas');
        if (!canvas) return;
        var ctx = canvas.getContext('2d');
        var cw = canvas.width, ch = canvas.height;

        // Clear
        ctx.fillStyle = '#05050f';
        ctx.fillRect(0, 0, cw, ch);

        // Background stars
        var bgStars = _getBgStars(cw, ch);
        ctx.fillStyle = 'rgba(255,255,255,0.25)';
        bgStars.forEach(function (s) {
            ctx.fillRect(s.x, s.y, 1, 1);
        });

        // Scale source map (1200x800) to canvas
        var scaleX = cw / 1200, scaleY = ch / 800;
        var mapStars = _getMapStars();

        // Explorer routes (blue dashed lines)
        var routes = data.explorer_routes || [];
        ctx.save();
        ctx.strokeStyle = 'rgba(68,170,255,0.5)';
        ctx.lineWidth = 1;
        ctx.setLineDash([6, 4]);
        routes.forEach(function (r) {
            var from = mapStars.find(function (s) { return s.name === r.from_star; });
            var to   = mapStars.find(function (s) { return s.name === r.to_star; });
            if (from && to) {
                ctx.beginPath();
                ctx.moveTo(from.x * scaleX, from.y * scaleY);
                ctx.lineTo(to.x * scaleX, to.y * scaleY);
                ctx.stroke();
            }
        });
        ctx.setLineDash([]);
        ctx.restore();

        // Builder colonies (green squares at star positions)
        var colonies = data.builder_colonies || [];
        colonies.forEach(function (c) {
            var star = mapStars.find(function (s) { return s.name === c.star; });
            if (star) {
                ctx.fillStyle = 'rgba(0,200,100,0.7)';
                ctx.fillRect(star.x * scaleX - 6, star.y * scaleY - 6, 12, 12);
            }
        });

        // Shooter battles (red pulsing circles, fade by age)
        var battles = data.shooter_battles || [];
        battles.forEach(function (b) {
            var alpha = Math.max(0, 1 - (b.age_s || 0) / 3600);
            ctx.save();
            ctx.strokeStyle = 'rgba(255,60,60,' + alpha + ')';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.arc((b.x || 0) * scaleX, (b.y || 0) * scaleY, 8, 0, Math.PI * 2);
            ctx.stroke();
            ctx.restore();
        });

        // Known stars (white dots + names)
        mapStars.forEach(function (s) {
            ctx.beginPath();
            ctx.fillStyle = '#ffffff';
            ctx.arc(s.x * scaleX, s.y * scaleY, 4, 0, Math.PI * 2);
            ctx.fill();
            ctx.fillStyle = 'rgba(200,220,255,0.85)';
            ctx.font = '10px IBM Plex Mono, monospace';
            ctx.fillText(s.name, s.x * scaleX + 7, s.y * scaleY + 4);
        });

        // Recent event dots
        var events = data.recent_events || [];
        var typeColors = {
            top_down_shooter: '#ff4444',
            space_explorer:   '#44aaff',
            base_builder:     '#44ff88',
            market:           '#ffcc00',
        };
        events.forEach(function (ev) {
            var evData = ev.data || {};
            var ex = (evData.x || Math.random() * 1200) * scaleX;
            var ey = (evData.y || Math.random() * 800) * scaleY;
            var color = typeColors[ev.source_game_type] || '#aaaaaa';
            ctx.beginPath();
            ctx.fillStyle = color;
            ctx.arc(ex, ey, 3, 0, Math.PI * 2);
            ctx.fill();
        });
    }

    function loadMarketPrices() {
        api('GET', '/api/world/effects?game_type=base_builder').then(function (data) {
            // Market uses world resources table — fetch resources for price data
            api('GET', '/api/world').then(function (worldData) {
                var resources = worldData.resources || [];
                var tableEl = document.getElementById('gsMarketPriceTable');
                if (!tableEl) return;
                if (!resources.length) {
                    tableEl.innerHTML = '<div class="gs-empty-state">No market data.</div>';
                    return;
                }
                var rows = resources.map(function (r) {
                    var base = r.base_price || 1;
                    var cur  = r.current_price || base;
                    var trend = cur > base ? '▲' : cur < base ? '▼' : '—';
                    var trendCls = cur > base ? 'gs-trend-up' : cur < base ? 'gs-trend-down' : '';
                    return '<tr>' +
                        '<td>' + (r.resource_type || r.name || '?') + '</td>' +
                        '<td class="gs-price-mono">' + (cur !== undefined ? cur.toFixed ? cur.toFixed(2) : cur : '—') + '</td>' +
                        '<td class="' + trendCls + '">' + trend + '</td>' +
                    '</tr>';
                });
                tableEl.innerHTML = '<table class="gs-market-table"><thead><tr>' +
                    '<th>Resource</th><th>Price</th><th>Trend</th>' +
                    '</tr></thead><tbody>' + rows.join('') + '</tbody></table>';

                // Populate trade dropdowns
                var fromSel = document.getElementById('gsTradeFrom');
                var toSel   = document.getElementById('gsTradeTo');
                if (fromSel && toSel) {
                    var opts = resources.map(function (r) {
                        var key = r.resource_type || r.name || '';
                        return '<option value="' + key + '">' + key + '</option>';
                    }).join('');
                    fromSel.innerHTML = opts;
                    toSel.innerHTML   = opts;
                }
            });
        }).catch(function (e) { console.error('loadMarketPrices', e); });
    }

    function executeTrade() {
        var fromSel  = document.getElementById('gsTradeFrom');
        var toSel    = document.getElementById('gsTradeTo');
        var amtInput = document.getElementById('gsTradeAmount');
        var from   = fromSel  ? fromSel.value  : '';
        var to     = toSel    ? toSel.value    : '';
        var amount = amtInput ? parseFloat(amtInput.value) : NaN;

        if (!from || !to)          { toast('Select from/to resources'); return; }
        if (from === to)           { toast('Cannot trade same resource'); return; }
        if (!amount || isNaN(amount) || amount <= 0) { toast('Enter a valid amount'); return; }

        api('POST', '/api/world/trade', { from: from, to: to, amount: amount }).then(function (data) {
            if (data.error || !data.success) { toast(data.error || 'Trade failed'); return; }
            toast('Traded ' + amount + ' ' + from + ' → ' + data.exchanged.toFixed(2) + ' ' + to);
            loadWorldState();
        }).catch(function (e) { console.error('executeTrade', e); toast('Trade failed'); });
    }

    function renderEventFeedEnhanced(events) {
        var evtEl = document.getElementById('gsWorldEvents');
        if (!evtEl) return;
        if (!events.length) {
            evtEl.innerHTML = '<div class="gs-empty-state">No pending events.</div>';
            return;
        }
        evtEl.innerHTML = events.map(function (e) {
            var effect = EFFECT_MAP[e.event_type] || null;
            var affectsHtml = effect
                ? ' <span class="gs-event-affects">→ ' + effect.affects.join(', ') + '</span>'
                : '';
            var labelHtml = effect
                ? '<span class="gs-event-label">' + effect.label + '</span>'
                : '<span class="gs-event-type">' + (e.event_type || '?') + '</span>';
            return '<div class="gs-world-event-item gs-event-' + (e.event_type || '') + '">' +
                labelHtml + affectsHtml +
                '<span class="gs-event-data">' + JSON.stringify(e.event_data || e.data || {}) + '</span>' +
            '</div>';
        }).join('');
    }

    function loadWorldState() {
        api('GET', '/api/world').then(function (data) {
            var resEl = document.getElementById('gsWorldResources');
            var resources = data.resources || [];
            var events = data.events || [];
            if (resEl) {
                resEl.innerHTML = resources.length
                    ? resources.map(function (r) {
                        return '<div class="gs-world-resource-row">' +
                            '<span class="gs-resource-name">' + (r.resource_type || r.name || '?') + '</span>' +
                            '<span class="gs-resource-qty">' + (r.quantity !== undefined ? r.quantity : '') + '</span>' +
                            '<span class="gs-resource-region">' + (r.region_id || '') + '</span>' +
                        '</div>';
                      }).join('')
                    : '<div class="gs-empty-state">No resources.</div>';
            }
            renderEventFeedEnhanced(events);
        }).catch(function (e) { console.error('loadWorldState', e); });

        // Load map data
        api('GET', '/api/world/map').then(function (mapData) {
            renderWorldMap(mapData);
        }).catch(function (e) { console.warn('world map', e); });

        loadMarketPrices();
    }

    function createSession() {
        if (!_profile) { toast('Create a profile first'); return; }
        var gameId = document.getElementById('gsSessionGameId');
        var gameType = document.getElementById('gsSessionGameType');
        var maxPlayers = document.getElementById('gsSessionMaxPlayers');
        api('POST', '/api/sessions', {
            game_id: gameId ? (gameId.value || null) : null,
            game_type: gameType ? gameType.value : 'top_down_shooter',
            max_players: maxPlayers ? parseInt(maxPlayers.value) || 4 : 4,
        }).then(function (data) {
            if (data.error) { toast(data.error); return; }
            closeCreateSessionModal();
            _currentRoomCode = data.room_code;
            toast('Session created: ' + data.room_code);
            loadOpenSessions();
            joinMultiplayer(data.room_code);
        }).catch(function (e) { console.error('createSession', e); toast('Failed to create session'); });
    }

    function joinSession() {
        var input = document.getElementById('gsJoinRoomCode');
        if (!input || !input.value.trim()) { toast('Enter a room code'); return; }
        _currentRoomCode = input.value.trim().toUpperCase();
        loadSessionPlayers(_currentRoomCode);
    }

    function leaveSession() {
        _currentRoomCode = null;
        closeJoinSessionModal();
        loadOpenSessions();
    }

    function joinMultiplayer(roomCode) {
        _currentRoomCode = roomCode;
        var input = document.getElementById('gsJoinRoomCode');
        if (input) input.value = roomCode;
        openJoinSessionModal();
        loadSessionPlayers(roomCode);
    }

    function startMultiplayerGame() {
        if (!_currentRoomCode) return;
        api('POST', '/api/sessions/' + _currentRoomCode + '/end', {}).then(function () {
            toast('Session ended');
            leaveSession();
        }).catch(function (e) { console.error('startMultiplayerGame', e); });
    }

    function openCreateSessionModal() {
        var modal = document.getElementById('gsCreateSessionModal');
        if (modal) {
            // Populate game dropdown from loaded games
            var sel = document.getElementById('gsSessionGameId');
            if (sel && window._gsGames) {
                sel.innerHTML = '<option value="">— Select a game —</option>' +
                    window._gsGames.map(function (g) {
                        return '<option value="' + g.id + '">' + (g.name || g.id) + '</option>';
                    }).join('');
            }
            modal.style.display = 'flex';
        }
    }

    function closeCreateSessionModal() {
        var modal = document.getElementById('gsCreateSessionModal');
        if (modal) modal.style.display = 'none';
    }

    function openJoinSessionModal() {
        var modal = document.getElementById('gsJoinSessionModal');
        if (modal) modal.style.display = 'flex';
    }

    function closeJoinSessionModal() {
        var modal = document.getElementById('gsJoinSessionModal');
        if (modal) modal.style.display = 'none';
    }

    function openProfileModal() {
        if (!_profile) {
            // No profile yet — prompt to create
            api('POST', '/api/profile', { display_name: '' }).then(function (data) {
                _profile = data.profile;
                renderProfile(_profile);
                _openProfileModalUI();
            }).catch(function (e) { console.error('createProfile', e); toast('Failed to create profile'); });
        } else {
            _openProfileModalUI();
        }
    }

    function _openProfileModalUI() {
        var modal = document.getElementById('gsProfileModal');
        var nameInput = document.getElementById('gsProfileDisplayName');
        if (nameInput && _profile) nameInput.value = _profile.display_name || '';
        if (modal) modal.style.display = 'flex';
    }

    function closeProfileModal() {
        var modal = document.getElementById('gsProfileModal');
        if (modal) modal.style.display = 'none';
    }

    function saveProfile() {
        var nameInput = document.getElementById('gsProfileDisplayName');
        var name = nameInput ? nameInput.value.trim() : '';
        if (!name) { toast('Display name required'); return; }
        var method = _profile ? 'PUT' : 'POST';
        api(method, '/api/profile', { display_name: name }).then(function (data) {
            if (data.error) { toast(data.error); return; }
            closeProfileModal();
            loadProfile();
            toast('Profile saved');
        }).catch(function (e) { console.error('saveProfile', e); toast('Failed to save profile'); });
    }

    // Expose multiplayer functions to HTML onclick
    window.loadProfile = loadProfile;
    window.loadOpenSessions = loadOpenSessions;
    window.loadWorldState = loadWorldState;
    window.executeTrade = executeTrade;
    window.renderWorldMap = renderWorldMap;
    window.loadMarketPrices = loadMarketPrices;
    window.createSession = createSession;
    window.joinSession = joinSession;
    window.leaveSession = leaveSession;
    window.joinMultiplayer = joinMultiplayer;
    window.startMultiplayerGame = startMultiplayerGame;
    window.openCreateSessionModal = openCreateSessionModal;
    window.closeCreateSessionModal = closeCreateSessionModal;
    window.openJoinSessionModal = openJoinSessionModal;
    window.closeJoinSessionModal = closeJoinSessionModal;
    window.openProfileModal = openProfileModal;
    window.closeProfileModal = closeProfileModal;
    window.saveProfile = saveProfile;

    // GS namespace — bridges HTML onclick="GS.switchTab(...)" calls
    window.GS = window.GS || {};
    window.GS.switchTab = window.setTab;
    window.GS.saveScene = window.saveScene || function () {};
    window.GS.playPreview = window.playPreview || function () {};
    window.GS.restartPreview = window.restartPreview || function () {};
    window.GS.collapseRightPanel = window.collapseRightPanel || function () {};
    window.GS.sendAiMessage = window.sendAiChat || function () {};
    window.GS.toggleAiHistory = window.toggleAiHistory || function () {};
    window.GS.openProfileModal = openProfileModal;
    window.GS.openCreateSessionModal = openCreateSessionModal;
    window.GS.loadOpenSessions = loadOpenSessions;
    window.GS.loadWorldState = loadWorldState;
    window.GS.executeTrade = executeTrade;

    // Init
    document.addEventListener('DOMContentLoaded', function () {
        initMonaco(function () {
            loadDashboard();
            loadProfile();
        });
    });

}());
