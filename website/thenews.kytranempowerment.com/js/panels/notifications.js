/* ==========================================================================
   Kytran News — Notifications & Sound Alerts
   Browser push notifications for major events + optional sound
   ========================================================================== */

var Notifications = (function () {
    'use strict';

    var _enabled = false;
    var _soundEnabled = false;
    var _lastDefcon = 5;
    var _notifiedIds = new Set();
    var _audioCtx = null;

    function init() {
        var btn = document.getElementById('notify-btn');
        if (btn) {
            btn.addEventListener('click', toggleNotifications);
        }

        var soundBtn = document.getElementById('sound-btn');
        if (soundBtn) {
            soundBtn.addEventListener('click', toggleSound);
        }

        /* Watch for major events */
        EventBus.on('defcon:update', _checkDefconChange);
        EventBus.on('data:disasters:updated', _checkMajorEarthquake);
        EventBus.on('data:conflicts:updated', _checkCriticalConflict);
    }

    function toggleNotifications() {
        if (!_enabled) {
            if ('Notification' in window) {
                Notification.requestPermission().then(function (perm) {
                    if (perm === 'granted') {
                        _enabled = true;
                        _updateBtn(true);
                        _notify('Kytran News', 'Notifications enabled. You will be alerted for major events.');
                    }
                });
            }
        } else {
            _enabled = false;
            _updateBtn(false);
        }
    }

    function toggleSound() {
        _soundEnabled = !_soundEnabled;
        var btn = document.getElementById('sound-btn');
        if (btn) btn.classList.toggle('active', _soundEnabled);
        if (_soundEnabled && !_audioCtx) {
            _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
    }

    function _updateBtn(active) {
        var btn = document.getElementById('notify-btn');
        if (btn) btn.classList.toggle('active', active);
    }

    function _checkDefconChange(data) {
        if (!_enabled) return;
        if (data.level < _lastDefcon && data.level <= 2) {
            _notify('DEFCON ' + data.level + ' — ' + (data.level === 1 ? 'CRITICAL' : 'HIGH'),
                    'Threat level has escalated. Total weighted events: ' + data.total);
            if (_soundEnabled) _playAlertSound(data.level === 1 ? 'critical' : 'warning');
        }
        _lastDefcon = data.level;
    }

    function _checkMajorEarthquake(data) {
        if (!_enabled) return;
        var eq = data.earthquakes || [];
        eq.forEach(function (d) {
            if ((d.magnitude || 0) >= 6.0 && !_notifiedIds.has(d.id)) {
                _notifiedIds.add(d.id);
                _notify('Major Earthquake — M' + d.magnitude,
                        d.title + (d.depth ? ' (Depth: ' + d.depth.toFixed(0) + 'km)' : ''));
                if (_soundEnabled) _playAlertSound('warning');
            }
        });
    }

    function _checkCriticalConflict(data) {
        if (!_enabled) return;
        data.forEach(function (d) {
            if (d.severity === 'critical' && !_notifiedIds.has(d.id)) {
                _notifiedIds.add(d.id);
                _notify('Critical Conflict Event', d.title);
                if (_soundEnabled) _playAlertSound('info');
            }
        });
    }

    function _notify(title, body) {
        if (!_enabled || !('Notification' in window)) return;
        if (Notification.permission === 'granted') {
            new Notification(title, {
                body: body,
                icon: 'favicon.svg',
                badge: 'favicon.svg',
                tag: title, /* prevent duplicates */
                silent: true
            });
        }
    }

    function _playAlertSound(type) {
        if (!_audioCtx) return;
        var osc = _audioCtx.createOscillator();
        var gain = _audioCtx.createGain();
        osc.connect(gain);
        gain.connect(_audioCtx.destination);

        if (type === 'critical') {
            osc.frequency.setValueAtTime(880, _audioCtx.currentTime);
            osc.frequency.setValueAtTime(440, _audioCtx.currentTime + 0.15);
            osc.frequency.setValueAtTime(880, _audioCtx.currentTime + 0.3);
        } else if (type === 'warning') {
            osc.frequency.setValueAtTime(660, _audioCtx.currentTime);
            osc.frequency.setValueAtTime(550, _audioCtx.currentTime + 0.2);
        } else {
            osc.frequency.setValueAtTime(440, _audioCtx.currentTime);
        }

        gain.gain.setValueAtTime(0.15, _audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, _audioCtx.currentTime + 0.5);
        osc.start(_audioCtx.currentTime);
        osc.stop(_audioCtx.currentTime + 0.5);
    }

    return { init: init, toggleNotifications: toggleNotifications, toggleSound: toggleSound };
})();
