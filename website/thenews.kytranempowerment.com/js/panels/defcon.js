/* ==========================================================================
   Kytran News — DEFCON / Threat Index
   Composite "KYTRAN THREAT INDEX" calculated from all data sources
   ========================================================================== */

var Defcon = (function () {
    'use strict';

    var _level = 5;
    var _scores = {};
    var _barEl = null;
    var _levelEl = null;
    var _labelEl = null;

    /* Weights per data source */
    var WEIGHTS = {
        conflicts: 3,
        disasters: 2,
        weather: 1,
        cyber: 2,
        outages: 1
    };

    /* Thresholds: total weighted score -> DEFCON level */
    var THRESHOLDS = [
        { min: 200, level: 1 },
        { min: 100, level: 2 },
        { min: 50,  level: 3 },
        { min: 20,  level: 4 },
        { min: 0,   level: 5 }
    ];

    function init() {
        _barEl = document.querySelector('.defcon-bar');
        _levelEl = document.getElementById('threat-level');
        _labelEl = document.getElementById('threat-label');

        EventBus.on('data:conflicts:updated', function (d) { _scores.conflicts = d.length; _recalculate(); });
        EventBus.on('data:disasters:updated', function (d) {
            _scores.disasters = (d.earthquakes ? d.earthquakes.length : 0) + (d.eonet ? d.eonet.length : 0);
            _recalculate();
        });
        EventBus.on('data:weather:updated', function (d) { _scores.weather = d.length; _recalculate(); });
        EventBus.on('data:cyber:updated', function (d) { _scores.cyber = d.length; _recalculate(); });
        EventBus.on('data:outages:updated', function (d) { _scores.outages = d.length; _recalculate(); });
    }

    function _recalculate() {
        var total = 0;
        Object.keys(_scores).forEach(function (key) {
            total += (_scores[key] || 0) * (WEIGHTS[key] || 1);
        });

        var newLevel = 5;
        for (var i = 0; i < THRESHOLDS.length; i++) {
            if (total >= THRESHOLDS[i].min) {
                newLevel = THRESHOLDS[i].level;
                break;
            }
        }

        _level = newLevel;
        _updateUI();
        EventBus.emit('defcon:update', { level: _level, scores: _scores, total: total });
    }

    function _updateUI() {
        var def = Config.DEFCON[_level] || Config.DEFCON[5];

        if (_barEl) _barEl.setAttribute('data-level', _level);
        if (_levelEl) {
            _levelEl.textContent = _level;
            _levelEl.style.color = def.color;
        }
        if (_labelEl) {
            _labelEl.textContent = def.label;
            _labelEl.style.color = def.color;
        }

        /* Update breakdown rows */
        Object.keys(_scores).forEach(function (key) {
            var el = document.getElementById('threat-' + key);
            if (el) el.textContent = _scores[key] || 0;
        });
    }

    function getLevel() { return _level; }
    function getScores() { return Object.assign({}, _scores); }

    return { init: init, getLevel: getLevel, getScores: getScores };
})();
