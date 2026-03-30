/**
 * A.R.C.H.I.E. Satellite PWA — Main Application Logic
 * Mobile fleet presence for the A.R.C.H.I.E. mesh network.
 */
(function () {
  'use strict';

  // ── State ────────────────────────────────────────────
  var HUB_URL = localStorage.getItem('sat_hub_url') || location.origin;
  var nodeId = localStorage.getItem('sat_node_id') || null;
  var authToken = localStorage.getItem('sat_auth_token') || null;
  var status = localStorage.getItem('sat_status') || 'unregistered'; // unregistered | pending | approved
  var heartbeatInterval = null;
  var pollInterval = null;

  // ── Init ─────────────────────────────────────────────
  function init() {
    registerServiceWorker();
    updateStatusDot();

    if (status === 'approved' && nodeId && authToken) {
      showScreen('dashboard');
      loadDashboard();
      startHeartbeat();
    } else if (status === 'pending' && nodeId) {
      showScreen('register');
      showWaiting('Awaiting hub approval...');
      pollApproval();
    } else {
      showScreen('register');
    }
  }

  // ── Service Worker Registration ──────────────────────
  function registerServiceWorker() {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/fleet/satellite/sw.js', {
        scope: '/fleet/satellite/'
      }).catch(function (err) {
        console.warn('SW registration failed:', err);
      });
    }
  }

  // ── Screen Management ────────────────────────────────
  function showScreen(name) {
    var screens = document.querySelectorAll('.sat-screen');
    for (var i = 0; i < screens.length; i++) {
      screens[i].classList.remove('active');
    }

    var target = document.getElementById('screen-' + name);
    if (target) {
      target.classList.add('active');
    }

    // Show/hide nav bar — only show after registration
    var nav = document.querySelector('.sat-nav');
    if (nav) {
      nav.style.display = (status === 'approved') ? 'flex' : 'none';
    }

    // Update nav highlights
    var navBtns = document.querySelectorAll('.sat-nav button');
    for (var j = 0; j < navBtns.length; j++) {
      var btn = navBtns[j];
      if (btn.getAttribute('data-screen') === name) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    }

    // Load screen-specific data
    if (name === 'dashboard') loadDashboard();
    if (name === 'fleet') loadFleetStatus();
    if (name === 'settings') loadSettings();
  }

  // ── Registration ─────────────────────────────────────
  function register() {
    var nameInput = document.getElementById('node-name');
    var name = nameInput ? nameInput.value.trim() : '';

    if (!name) {
      nameInput.focus();
      return;
    }

    var btn = document.getElementById('register-btn');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'REGISTERING...';
    }

    var deviceInfo = getDeviceInfo();

    fetch(HUB_URL + '/starbase/api/fleet/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name,
        type: 'satellite',
        device_info: deviceInfo
      })
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (!data.success) {
          showWaiting('Registration failed: ' + (data.error || 'Unknown error'));
          if (btn) {
            btn.disabled = false;
            btn.textContent = 'JOIN FLEET';
          }
          return;
        }

        nodeId = data.node_id;
        localStorage.setItem('sat_node_id', nodeId);
        localStorage.setItem('sat_hub_url', HUB_URL);

        if (data.status === 'approved' && data.api_key) {
          // Token-based instant approval
          authToken = data.api_key;
          localStorage.setItem('sat_auth_token', authToken);
          status = 'approved';
          localStorage.setItem('sat_status', status);
          updateStatusDot();
          showScreen('dashboard');
          startHeartbeat();
        } else {
          // Pending manual approval
          status = 'pending';
          localStorage.setItem('sat_status', status);
          updateStatusDot();
          showWaiting('Registration submitted. Awaiting hub approval...');
          pollApproval();
        }
      })
      .catch(function () {
        showWaiting('Connection failed. Is the hub reachable?');
        if (btn) {
          btn.disabled = false;
          btn.textContent = 'JOIN FLEET';
        }
      });
  }

  // ── Poll Approval ────────────────────────────────────
  function pollApproval() {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(function () {
      if (!nodeId) {
        clearInterval(pollInterval);
        return;
      }

      fetch(HUB_URL + '/starbase/api/fleet/status/' + nodeId + '?need_key=true')
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (!data.success) return;

          if (data.status === 'approved') {
            clearInterval(pollInterval);
            pollInterval = null;

            if (data.api_key) {
              authToken = data.api_key;
              localStorage.setItem('sat_auth_token', authToken);
            }

            status = 'approved';
            localStorage.setItem('sat_status', status);
            updateStatusDot();
            showScreen('dashboard');
            startHeartbeat();
          } else if (data.status === 'denied') {
            clearInterval(pollInterval);
            pollInterval = null;
            status = 'unregistered';
            localStorage.removeItem('sat_node_id');
            localStorage.removeItem('sat_status');
            localStorage.removeItem('sat_auth_token');
            nodeId = null;
            authToken = null;
            updateStatusDot();
            showWaiting('Registration denied by hub administrator.');
          }
        })
        .catch(function () {
          // Network error — keep polling
        });
    }, 10000);
  }

  // ── Heartbeat ────────────────────────────────────────
  function startHeartbeat() {
    if (heartbeatInterval) clearInterval(heartbeatInterval);

    sendHeartbeat(); // immediate first beat

    heartbeatInterval = setInterval(function () {
      sendHeartbeat();
    }, 60000);
  }

  function sendHeartbeat() {
    if (!nodeId || !authToken) return;

    var deviceInfo = getDeviceInfo();

    fetch(HUB_URL + '/starbase/api/fleet/heartbeat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Node-Id': nodeId,
        'X-Api-Key': authToken
      },
      body: JSON.stringify({
        node_id: nodeId,
        device_info: deviceInfo
      })
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.success) {
          updateStatusDot('online');
        }
      })
      .catch(function () {
        updateStatusDot('offline');
      });
  }

  // ── Device Info ──────────────────────────────────────
  function getDeviceInfo() {
    var info = {
      platform: navigator.platform || 'unknown',
      userAgent: navigator.userAgent || 'unknown',
      language: navigator.language || 'unknown',
      screenWidth: screen.width || 0,
      screenHeight: screen.height || 0,
      online: navigator.onLine
    };

    // Network info (best-effort)
    if (navigator.connection) {
      info.connectionType = navigator.connection.effectiveType || 'unknown';
      info.downlink = navigator.connection.downlink || 0;
    }

    // Battery info (best-effort, async — updates on next heartbeat)
    if (navigator.getBattery) {
      navigator.getBattery().then(function (battery) {
        info.batteryLevel = Math.round(battery.level * 100);
        info.batteryCharging = battery.charging;
      }).catch(function () {
        // Battery API not available
      });
    }

    return info;
  }

  // ── Dashboard ────────────────────────────────────────
  function loadDashboard() {
    var elStatus = document.getElementById('stat-status');
    var elType = document.getElementById('stat-type');
    var elNodeId = document.getElementById('stat-node-id');

    if (elStatus) elStatus.textContent = status === 'approved' ? 'ONLINE' : status.toUpperCase();
    if (elType) elType.textContent = 'SATELLITE';
    if (elNodeId) elNodeId.textContent = nodeId || '-';
  }

  // ── Fleet Status ─────────────────────────────────────
  function loadFleetStatus() {
    var listEl = document.getElementById('fleet-list');
    if (!listEl) return;

    // Clear and build self-entry using safe DOM methods
    while (listEl.firstChild) {
      listEl.removeChild(listEl.firstChild);
    }

    var li = document.createElement('li');
    li.className = 'sat-fleet-item';

    var infoDiv = document.createElement('div');

    var nameDiv = document.createElement('div');
    nameDiv.className = 'node-name';
    nameDiv.textContent = nodeId || 'this-device';
    infoDiv.appendChild(nameDiv);

    var typeDiv = document.createElement('div');
    typeDiv.className = 'node-type';
    typeDiv.textContent = 'satellite';
    infoDiv.appendChild(typeDiv);

    li.appendChild(infoDiv);

    var badge = document.createElement('span');
    badge.className = 'sat-badge ' + (status === 'approved' ? 'online' : 'pending');
    badge.textContent = status === 'approved' ? 'online' : status;
    li.appendChild(badge);

    listEl.appendChild(li);
  }

  // ── Settings ─────────────────────────────────────────
  function loadSettings() {
    var hubUrlEl = document.getElementById('settings-hub-url');
    if (hubUrlEl) hubUrlEl.textContent = HUB_URL;
  }

  // ── Disconnect ───────────────────────────────────────
  function disconnect() {
    if (!confirm('Disconnect from fleet? This will remove all local data.')) return;

    if (heartbeatInterval) clearInterval(heartbeatInterval);
    if (pollInterval) clearInterval(pollInterval);

    localStorage.removeItem('sat_node_id');
    localStorage.removeItem('sat_auth_token');
    localStorage.removeItem('sat_status');
    localStorage.removeItem('sat_hub_url');

    nodeId = null;
    authToken = null;
    status = 'unregistered';

    location.reload();
  }

  // ── Status Dot ───────────────────────────────────────
  function updateStatusDot(override) {
    var dot = document.getElementById('status-dot');
    if (!dot) return;

    dot.classList.remove('online', 'pending', 'offline');

    var state = override || status;
    if (state === 'approved' || state === 'online') {
      dot.classList.add('online');
    } else if (state === 'pending') {
      dot.classList.add('pending');
    } else if (state === 'offline') {
      dot.classList.add('offline');
    }
  }

  // ── Waiting Message ──────────────────────────────────
  function showWaiting(msg) {
    var el = document.getElementById('waiting-msg');
    if (!el) return;
    el.style.display = 'block';
    // Use safe DOM methods
    while (el.firstChild) {
      el.removeChild(el.firstChild);
    }
    var span = document.createElement('span');
    span.className = 'status-text';
    span.textContent = msg;
    el.appendChild(span);
  }

  // ── Public API ───────────────────────────────────────
  window.satellite = {
    register: register,
    showScreen: showScreen,
    disconnect: disconnect
  };

  // ── Boot ─────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', init);
})();
