// ═══════════════════════════════════════════════════════════════════════════════
// LCARS FRAME-BUILD BOOT SEQUENCE
// Black overlay + scanline + "THREAT LEVEL MIDNIGHT" flash, then frames
// construct themselves sequentially. Click/key to skip. sessionStorage bypass.
// ═══════════════════════════════════════════════════════════════════════════════
(function initFrameBoot() {
    if (sessionStorage.getItem('archie-booted')) {
        document.getElementById('bootOverlay')?.remove();
        document.querySelectorAll('.boot-hidden').forEach(function(f) { f.classList.remove('boot-hidden'); });
        return;
    }

    var overlay = document.getElementById('bootOverlay');
    var threatFlash = document.getElementById('bootThreatFlash');
    var bootLogo = document.getElementById('bootLogo');
    var bootLogoSub = document.getElementById('bootLogoSub');
    var bootTerminal = document.getElementById('bootTerminal');
    var bootProgress = document.getElementById('bootProgress');
    var bootSkip = document.getElementById('bootSkip');
    var frames = document.querySelectorAll('.lcars-frame');
    var skipped = false;

    frames.forEach(function(f) { f.classList.add('boot-hidden'); });

    // Boot sequence lines — typed out one by one
    // NOTE: All content is hardcoded (no user input) — safe for innerHTML
    var bootLines = [
        { text: 'LCARS OPERATING SYSTEM \u2014 FEDERATION STANDARD', cls: 'system', delay: 400 },
        { text: 'INITIALIZING KERNEL...', cls: 'info', ok: 'OK', delay: 600 },
        { text: 'LOADING NEURAL CORE MATRIX...', cls: '', ok: 'OK', delay: 800 },
        { text: 'SCANNING AI BRIDGE SUBSYSTEMS...', cls: '', ok: 'ONLINE', delay: 700 },
        { text: 'MOUNTING KNOWLEDGE BASE...', cls: '', ok: 'OK', delay: 600 },
        { text: 'AGENT ROSTER: 10 REGISTERED / 10 ACTIVE', cls: 'success', delay: 500 },
        { text: 'ORCHESTRATION ENGINE...', cls: '', ok: 'ARMED', delay: 500 },
        { text: 'SMART ROUTER \u2014 11-TIER CASCADE...', cls: '', ok: 'READY', delay: 500 },
        { text: 'EMBEDDING SERVICE (ARCTIC-EMBED)...', cls: '', ok: 'WARM', delay: 400 },
        { text: 'SECURITY PROTOCOLS...', cls: 'warn', ok: 'ENGAGED', delay: 400 },
        { text: 'C.R.E.E.D. GOVERNANCE LAYER...', cls: '', ok: 'ACTIVE', delay: 400 },
        { text: 'GPU: QUADRO M4000 (8GB VRAM)...', cls: 'system', ok: 'OK', delay: 300 },
        { text: 'ALL SUBSYSTEMS NOMINAL', cls: 'success', delay: 600 },
        { text: 'WELCOME BACK, COMMANDER', cls: 'info', delay: 400 }
    ];

    var totalLines = bootLines.length;

    // Show skip hint after 2s
    setTimeout(function() {
        if (!skipped && bootSkip) bootSkip.classList.add('visible');
    }, 2000);

    // Phase 1: Logo reveal (0-1s)
    setTimeout(function() {
        if (skipped) return;
        bootLogo.classList.add('visible');
    }, 300);
    setTimeout(function() {
        if (skipped) return;
        bootLogoSub.classList.add('visible');
    }, 800);

    // Phase 2: Threat Level Midnight flash + screen flicker (1.5s, lasts 2.5s)
    setTimeout(function() {
        if (skipped) return;
        overlay.classList.add('threat-flicker');
        threatFlash.classList.add('flash');
    }, 1500);

    // Phase 3: Terminal lines begin (4.5s — after threat flash finishes)
    var cumulativeDelay = 4500;

    bootLines.forEach(function(line, i) {
        cumulativeDelay += line.delay;
        var t = cumulativeDelay;
        setTimeout(function() {
            if (skipped) return;
            var div = document.createElement('div');
            div.className = 'boot-line' + (line.cls ? ' ' + line.cls : '');
            // Build content safely — all strings are hardcoded above
            var span = '';
            if (line.ok) span = '<span class="ok">[ ' + line.ok + ' ]</span>';
            div.innerHTML = line.text + span;  // eslint-disable-line -- hardcoded content only
            bootTerminal.appendChild(div);
            void div.offsetWidth;
            div.classList.add('visible');
            // Update progress bar
            bootProgress.style.width = Math.round(((i + 1) / totalLines) * 100) + '%';
        }, t);
    });

    // Phase 4: Terminal done, pause (cumulativeDelay + 800ms)
    var terminalEnd = cumulativeDelay + 800;

    // Phase 5: Build frames with dramatic pacing
    var frameBuildStart = terminalEnd;
    var slowFrameGap = 600;
    var fastFrameGap = 300;

    frames.forEach(function(frame, i) {
        var delay;
        if (i < 4) {
            delay = frameBuildStart + i * slowFrameGap;
        } else {
            delay = frameBuildStart + 4 * slowFrameGap + (i - 4) * fastFrameGap;
        }
        setTimeout(function() {
            if (skipped) return;
            frame.classList.remove('boot-hidden');
            frame.classList.add('frame-build');
        }, delay);
    });

    // Phase 6: Overlay fades out after all frames built
    var lastFrameTime = frameBuildStart + 4 * slowFrameGap + Math.max(0, frames.length - 4) * fastFrameGap;
    var fadeTime = lastFrameTime + 800;

    setTimeout(function() {
        if (skipped) return;
        overlay.classList.add('fade-out');
        sessionStorage.setItem('archie-booted', '1');
        setTimeout(function() { overlay.remove(); }, 600);
    }, fadeTime);

    // Skip on click or keypress
    function skipBoot() {
        if (skipped) return;
        skipped = true;
        frames.forEach(function(f) {
            f.classList.remove('boot-hidden');
            f.classList.remove('frame-build');
        });
        overlay.remove();
        sessionStorage.setItem('archie-booted', '1');
        document.removeEventListener('click', skipBoot);
        document.removeEventListener('keydown', skipBoot);
    }
    document.addEventListener('click', skipBoot);
    document.addEventListener('keydown', skipBoot);
})();

// ═══════════════════════════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════════════════════════
// SHARED: Relative timestamp helper (used by notifications + mission briefing)
// ═══════════════════════════════════════════════════════════════════════════════
window.timeAgo = function timeAgo(isoString) {
    if (!isoString) return '';
    return ArchieTime.age(isoString);
};

// ═══════════════════════════════════════════════════════════════════════════════
// COMMAND BAR + HUD VITALS — Task 3
// Scroll handler, data fetch, ring gauges, notifications, search shortcut
// ═══════════════════════════════════════════════════════════════════════════════
(function initCommandBarAndHUD() {
    'use strict';

    // ── Scroll handler: add .scrolled class to command bar ──
    var cmdBar = document.getElementById('command-bar');
    if (cmdBar) {
        window.addEventListener('scroll', function() {
            if (window.scrollY > 10) {
                cmdBar.classList.add('scrolled');
            } else {
                cmdBar.classList.remove('scrolled');
            }
        }, { passive: true });
    }

    // ── Ctrl+K: focus search input ──
    var searchInput = document.getElementById('cbSearchInput');
    if (searchInput) {
        document.addEventListener('keydown', function(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                searchInput.focus();
            }
            // Escape clears and blurs search
            if (e.key === 'Escape' && document.activeElement === searchInput) {
                searchInput.value = '';
                searchInput.dispatchEvent(new Event('input'));
                searchInput.blur();
            }
        });

        // ── Spotlight Search Popover ──
        var popover = document.getElementById('cbSearchPopover');
        var activeIdx = -1;
        var searchTimeout;

        // Category accent colors for result icons
        var catAccents = {
            admin_operations: '#ef4444', ai_command: '#00ffff',
            saas_services: '#f59e0b', project_knowledge: '#00ff41',
            applications_concepts: '#0ea5e9', crypto: '#eab308',
            what_the_fact: '#3b82f6', watch_series: '#10b981', creed: '#a855f7',
            creative_studios: '#ec4899',
            placeholders_future: '#6b7280'
        };

        // Category display names
        var catNames = {
            admin_operations: 'Admin Operations', ai_command: 'AI Command',
            saas_services: 'SaaS Services',
            project_knowledge: 'Project & Knowledge', applications_concepts: 'Applications & Concepts',
            crypto: 'Crypto', what_the_fact: 'What The Fact',
            watch_series: 'The Watch Series', creed: 'C.R.E.E.D.',
            creative_studios: 'Creative Studios',
            placeholders_future: 'Coming Soon'
        };

        // Build module index from DOM
        var moduleIndex = [];
        document.querySelectorAll('.category-grid .module-card').forEach(function(card) {
            moduleIndex.push({
                id: card.getAttribute('data-module-id') || '',
                name: card.getAttribute('data-module-name') || '',
                icon: card.getAttribute('data-module-icon') || 'box',
                desc: card.getAttribute('data-module-desc') || '',
                category: card.getAttribute('data-module-category') || '',
                href: card.getAttribute('href') || '#',
                comingSoon: card.classList.contains('coming-soon'),
                el: card
            });
        });

        function showPopover(results, query) {
            if (!results.length) {
                popover.innerHTML = '<div class="cb-search-empty" data-i18n="js.search.no_results">No modules found</div>';
                popover.classList.add('visible');
                activeIdx = -1;
                return;
            }
            var html = '';
            results.forEach(function(mod, i) {
                var accent = catAccents[mod.category] || '#00FF41';
                var catLabel = catNames[mod.category] || mod.category;
                // Use visible translated name if available
                var nameEl = mod.el.querySelector('.module-card-name');
                var displayName = nameEl ? nameEl.textContent : mod.name;
                // Translate category if i18n available
                if (typeof window.archieI18n !== 'undefined' && window.archieI18n.t) {
                    var tCat = window.archieI18n.t('cat.' + mod.category, catLabel);
                    if (tCat !== 'cat.' + mod.category) catLabel = tCat;
                }
                html += '<a href="' + mod.href + '" class="cb-search-result' + (i === 0 ? ' active' : '') + '" data-idx="' + i + '" style="--result-accent:' + accent + ';">' +
                    '<div class="cb-search-result-icon"><i data-lucide="' + mod.icon + '"></i></div>' +
                    '<div class="cb-search-result-info">' +
                        '<div class="cb-search-result-name">' + escHtml(displayName) + '</div>' +
                        '<div class="cb-search-result-cat">' + escHtml(catLabel) + '</div>' +
                    '</div>' +
                '</a>';
            });
            popover.innerHTML = html;
            popover.classList.add('visible');
            activeIdx = 0;
            // Re-render lucide icons in popover
            if (window.lucide) lucide.createIcons({ nodes: popover.querySelectorAll('[data-lucide]') });
        }

        function hidePopover() {
            popover.classList.remove('visible');
            popover.innerHTML = '';
            activeIdx = -1;
        }

        function escHtml(s) {
            var d = document.createElement('div');
            d.textContent = s;
            return d.innerHTML;
        }

        function setActiveResult(idx) {
            var items = popover.querySelectorAll('.cb-search-result');
            if (!items.length) return;
            items.forEach(function(el) { el.classList.remove('active'); });
            if (idx < 0) idx = items.length - 1;
            if (idx >= items.length) idx = 0;
            activeIdx = idx;
            items[idx].classList.add('active');
            items[idx].scrollIntoView({ block: 'nearest' });
        }

        searchInput.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            var query = searchInput.value.trim().toLowerCase();
            if (!query) {
                hidePopover();
                return;
            }
            searchTimeout = setTimeout(function() {
                var results = moduleIndex.filter(function(mod) {
                    var visibleName = (mod.el.querySelector('.module-card-name') || {}).textContent || '';
                    return mod.name.toLowerCase().indexOf(query) >= 0 ||
                           mod.id.toLowerCase().indexOf(query) >= 0 ||
                           mod.desc.toLowerCase().indexOf(query) >= 0 ||
                           visibleName.toLowerCase().indexOf(query) >= 0;
                });
                showPopover(results.slice(0, 8), query);
            }, 100);
        });

        searchInput.addEventListener('keydown', function(e) {
            if (!popover.classList.contains('visible')) return;
            var items = popover.querySelectorAll('.cb-search-result');
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                setActiveResult(activeIdx + 1);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setActiveResult(activeIdx - 1);
            } else if (e.key === 'Enter') {
                e.preventDefault();
                if (items[activeIdx]) {
                    window.location.href = items[activeIdx].getAttribute('href');
                }
            }
        });

        searchInput.addEventListener('focus', function() {
            var query = searchInput.value.trim().toLowerCase();
            if (query) searchInput.dispatchEvent(new Event('input'));
        });

        // Close popover on outside click
        document.addEventListener('click', function(e) {
            if (!popover.contains(e.target) && e.target !== searchInput) {
                hidePopover();
            }
        });
    }

    // ── Language menu ──
    window.toggleLangMenu = function(btn) {
        var menu = document.getElementById('cbLangMenu');
        if (!menu) return;
        menu.classList.toggle('hidden');
        // Position relative to button
        var rect = btn.getBoundingClientRect();
        menu.style.top = (rect.bottom + 4) + 'px';
        menu.style.right = (window.innerWidth - rect.right) + 'px';
    };

    // Close lang menu on outside click
    document.addEventListener('click', function(e) {
        var menu = document.getElementById('cbLangMenu');
        var btn = document.getElementById('cbLangBtn');
        if (!menu || menu.classList.contains('hidden')) return;
        if (!menu.contains(e.target) && e.target !== btn && !btn.contains(e.target)) {
            menu.classList.add('hidden');
        }
    });

    // Language selection
    document.querySelectorAll('.cb-lang-option').forEach(function(opt) {
        opt.addEventListener('click', function() {
            var lang = opt.getAttribute('data-lang');
            document.querySelectorAll('.cb-lang-option').forEach(function(o) { o.classList.remove('active'); });
            opt.classList.add('active');
            document.getElementById('cbLangMenu').classList.add('hidden');
            if (window.archieI18n) {
                archieI18n.switchLanguage(lang);
            }
        });
    });

    // Initialize i18n on load and sync active language in dropdown
    if (window.archieI18n) {
        archieI18n.init();
        // Sync dropdown active state after init
        setTimeout(function() {
            var curLang = archieI18n.getCurrentLanguage();
            document.querySelectorAll('.cb-lang-option').forEach(function(o) {
                o.classList.toggle('active', o.getAttribute('data-lang') === curLang);
            });
        }, 600);
    }

    // ── Theme toggle icon sync ──
    function syncThemeIcons() {
        var sunIcon = document.getElementById('cbThemeIconSun');
        var moonIcon = document.getElementById('cbThemeIconMoon');
        if (!sunIcon || !moonIcon) return;
        var isLight = document.documentElement.getAttribute('data-theme') === 'light' ||
                      document.body.classList.contains('light-mode');
        sunIcon.style.display = isLight ? 'none' : 'inline-block';
        moonIcon.style.display = isLight ? 'inline-block' : 'none';
    }
    syncThemeIcons();
    // Re-sync on theme change
    var themeObserver = new MutationObserver(syncThemeIcons);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    themeObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] });

    // ── Notifications Popover ──
    var notifBtn = document.getElementById('cbNotifBtn');
    var notifPopover = document.getElementById('cbNotifPopover');
    var notifOverlay = document.getElementById('cbNotifOverlay');
    var notifList = document.getElementById('cbNotifList');
    var notifMarkAll = document.getElementById('cbNotifMarkAll');

    function openNotifPopover() {
        if (notifOverlay) notifOverlay.classList.add('visible');
        notifPopover.classList.add('visible');
        fetchNotifications();
    }
    function closeNotifPopover() {
        notifPopover.classList.remove('visible');
        if (notifOverlay) notifOverlay.classList.remove('visible');
    }

    if (notifBtn && notifPopover) {
        notifBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            var isOpen = notifPopover.classList.contains('visible');
            if (isOpen) {
                closeNotifPopover();
            } else {
                openNotifPopover();
            }
        });

        // Close on overlay click
        if (notifOverlay) {
            notifOverlay.addEventListener('click', function() {
                closeNotifPopover();
            });
        }

        // Close on outside click (keyboard Escape handled below)
        document.addEventListener('click', function(e) {
            if (!notifPopover.contains(e.target) && e.target !== notifBtn && !notifBtn.contains(e.target)) {
                closeNotifPopover();
            }
        });

        // Close on Escape key
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && notifPopover.classList.contains('visible')) {
                closeNotifPopover();
            }
        });

        // Mark all read
        if (notifMarkAll) {
            notifMarkAll.addEventListener('click', function() {
                fetch('/api/notifications/mark-all-read', { method: 'POST' })
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (data.success) {
                            fetchNotifications();
                            fetchNotifCount();
                        }
                    })
                    .catch(function(err) { console.warn('Mark all read failed:', err); });
            });
        }

        // Clear all (archive all notifications)
        var notifClearAll = document.getElementById('cbNotifClearAll');
        if (notifClearAll) {
            notifClearAll.addEventListener('click', function() {
                if (!confirm('Archive all notifications? This clears the list.')) return;
                fetch('/api/notifications/clear-all', { method: 'POST' })
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (data.success) {
                            fetchNotifications();
                            fetchNotifCount();
                        }
                    })
                    .catch(function(err) { console.warn('Clear all failed:', err); });
            });
        }
    }

    function fetchNotifications() {
        fetch('/api/notifications')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success || !data.notifications) return;
                renderNotifications(data.notifications);
            })
            .catch(function(err) {
                console.warn('Notifications fetch failed:', err);
                notifList.innerHTML = '<div class="cb-notif-empty">Failed to load</div>';
            });
    }

    function renderNotifications(items) {
        if (!items.length) {
            notifList.textContent = '';
            var emptyDiv = document.createElement('div');
            emptyDiv.className = 'cb-notif-empty';
            emptyDiv.setAttribute('data-i18n', 'js.notif.none');
            emptyDiv.textContent = archieI18n.t('js.notif.none', 'No notifications');
            notifList.appendChild(emptyDiv);
            return;
        }
        notifList.textContent = '';
        var sourceLabels = {
            'email_intelligence': 'Email',
            'bridge': 'Bridge',
            'security': 'Security',
            'system': 'System',
            'proposals': 'Proposals',
            'admin-panel': 'Admin',
            'agent_loop': 'Agent',
            'anomaly_detector': 'Anomaly'
        };

        items.slice(0, 25).forEach(function(n) {
            var div = document.createElement('div');
            div.className = 'cb-notif-item' + (n.is_read ? '' : ' unread');
            div.setAttribute('data-notif-id', n.id);

            var dot = document.createElement('div');
            var dotClass = n.type || 'info';
            if (['info','warning','error','success','system'].indexOf(dotClass) < 0) dotClass = 'info';
            dot.className = 'cb-notif-dot ' + dotClass;
            div.appendChild(dot);

            var info = document.createElement('div');
            info.className = 'cb-notif-info';

            var title = document.createElement('div');
            title.className = 'cb-notif-item-title';
            title.textContent = n.title || 'Notification';
            info.appendChild(title);

            if (n.message) {
                var msg = document.createElement('div');
                msg.className = 'cb-notif-item-msg';
                msg.textContent = n.message;
                info.appendChild(msg);
            }

            var meta = document.createElement('div');
            meta.className = 'cb-notif-item-meta';

            if (n.created_at) {
                var time = document.createElement('span');
                time.className = 'cb-notif-item-time';
                time.textContent = timeAgo(n.created_at);
                meta.appendChild(time);
            }

            if (n.source) {
                var badge = document.createElement('span');
                var srcClass = sourceLabels[n.source] ? 'src-' + n.source : 'src-default';
                badge.className = 'cb-notif-source-badge ' + srcClass;
                badge.textContent = sourceLabels[n.source] || n.source;
                meta.appendChild(badge);
            }

            info.appendChild(meta);
            div.appendChild(info);

            // Dismiss (X) button
            var dismissBtn = document.createElement('button');
            dismissBtn.className = 'cb-notif-dismiss';
            dismissBtn.title = 'Dismiss';
            dismissBtn.textContent = '\u00D7';
            dismissBtn.addEventListener('click', (function(notif, itemDiv) {
                return function(e) {
                    e.stopPropagation();
                    itemDiv.style.opacity = '0.3';
                    fetch('/api/notifications/dismiss/' + notif.id, { method: 'POST' })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            if (data.success) {
                                itemDiv.style.transition = 'all 0.2s ease';
                                itemDiv.style.maxHeight = '0';
                                itemDiv.style.padding = '0 16px';
                                itemDiv.style.overflow = 'hidden';
                                setTimeout(function() { itemDiv.remove(); fetchNotifCount(); }, 200);
                                // If list is now empty, show empty state
                                setTimeout(function() {
                                    if (notifList.querySelectorAll('.cb-notif-item').length === 0) {
                                        var emptyDiv = document.createElement('div');
                                        emptyDiv.className = 'cb-notif-empty';
                                        emptyDiv.textContent = archieI18n.t('js.notif.none', 'No notifications');
                                        notifList.appendChild(emptyDiv);
                                    }
                                }, 250);
                            } else {
                                itemDiv.style.opacity = '1';
                            }
                        })
                        .catch(function() { itemDiv.style.opacity = '1'; });
                };
            })(n, div));
            div.appendChild(dismissBtn);

            notifList.appendChild(div);

            // Click to open detail modal
            div.addEventListener('click', (function(notif, itemDiv) {
                return function() {
                    openNotifModal(notif, itemDiv, sourceLabels);
                };
            })(n, div));
        });
    }

    function openNotifModal(n, itemDiv, sourceLabels) {
        var modal = document.getElementById('cbNotifModal');
        var modalDot = document.getElementById('cbNotifModalDot');
        var modalTitle = document.getElementById('cbNotifModalTitle');
        var modalMsg = document.getElementById('cbNotifModalMsg');
        var modalMeta = document.getElementById('cbNotifModalMeta');
        var modalFooter = document.getElementById('cbNotifModalFooter');
        if (!modal) return;

        // Set type dot
        var dotClass = n.type || 'info';
        if (['info','warning','error','success','reminder'].indexOf(dotClass) < 0) dotClass = 'info';
        modalDot.className = 'cb-notif-modal-dot ' + dotClass;

        // Title
        modalTitle.textContent = n.title || 'Notification';

        // Full message
        modalMsg.textContent = n.message || 'No details available.';

        // Meta: source + time + priority
        modalMeta.textContent = '';
        if (n.source) {
            var srcItem = document.createElement('span');
            srcItem.className = 'cb-notif-modal-meta-item';
            srcItem.innerHTML = ''; // clear
            var srcLabel = document.createElement('strong');
            srcLabel.textContent = 'Source: ';
            srcItem.appendChild(srcLabel);
            srcItem.appendChild(document.createTextNode(sourceLabels[n.source] || n.source));
            modalMeta.appendChild(srcItem);
        }
        if (n.created_at) {
            var timeItem = document.createElement('span');
            timeItem.className = 'cb-notif-modal-meta-item';
            var timeLabel = document.createElement('strong');
            timeLabel.textContent = 'When: ';
            timeItem.appendChild(timeLabel);
            timeItem.appendChild(document.createTextNode(timeAgo(n.created_at)));
            modalMeta.appendChild(timeItem);
        }
        if (n.priority && n.priority !== 'normal') {
            var prioItem = document.createElement('span');
            prioItem.className = 'cb-notif-modal-meta-item';
            var prioLabel = document.createElement('strong');
            prioLabel.textContent = 'Priority: ';
            prioItem.appendChild(prioLabel);
            prioItem.appendChild(document.createTextNode(n.priority.toUpperCase()));
            modalMeta.appendChild(prioItem);
        }

        // Footer buttons
        modalFooter.textContent = '';
        if (!n.is_read && n.id > 0) {
            var markBtn = document.createElement('button');
            markBtn.className = 'cb-notif-modal-btn';
            markBtn.textContent = 'Mark as Read';
            markBtn.addEventListener('click', function() {
                fetch('/api/notifications/mark-read/' + n.id, { method: 'POST' })
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (data.success) {
                            n.is_read = true;
                            itemDiv.classList.remove('unread');
                            fetchNotifCount();
                            markBtn.textContent = 'Read';
                            markBtn.disabled = true;
                            markBtn.style.opacity = '0.4';
                        }
                    });
            });
            modalFooter.appendChild(markBtn);
        }
        // Dismiss (archive) button
        if (n.id > 0) {
            var dismissModalBtn = document.createElement('button');
            dismissModalBtn.className = 'cb-notif-modal-btn dismiss';
            dismissModalBtn.textContent = 'Dismiss';
            dismissModalBtn.addEventListener('click', function() {
                fetch('/api/notifications/dismiss/' + n.id, { method: 'POST' })
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (data.success) {
                            modal.classList.remove('visible');
                            fetchNotifications();
                            fetchNotifCount();
                        }
                    });
            });
            modalFooter.appendChild(dismissModalBtn);
        }

        var closeBtn = document.createElement('button');
        closeBtn.className = 'cb-notif-modal-btn';
        closeBtn.textContent = 'Close';
        closeBtn.addEventListener('click', function() {
            modal.classList.remove('visible');
        });
        modalFooter.appendChild(closeBtn);

        // Show modal
        modal.classList.add('visible');

        // Close on overlay click
        modal.onclick = function(e) {
            if (e.target === modal) modal.classList.remove('visible');
        };
    }

    // Close modal on X button
    var notifModalClose = document.getElementById('cbNotifModalClose');
    if (notifModalClose) {
        notifModalClose.addEventListener('click', function() {
            document.getElementById('cbNotifModal').classList.remove('visible');
        });
    }

    // Close modal on Escape
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            var modal = document.getElementById('cbNotifModal');
            if (modal && modal.classList.contains('visible')) {
                modal.classList.remove('visible');
            }
        }
    });

    // ── Lucide icons: re-render for command bar ──
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }

    // ── Segmented bar helper ──
    var NUM_SEGMENTS = 12;

    // Initialize bar segments on load
    function initBar(barId) {
        var bar = document.getElementById(barId);
        if (!bar || bar.children.length > 0) return;
        for (var i = 0; i < NUM_SEGMENTS; i++) {
            var seg = document.createElement('div');
            seg.className = 'hud-seg';
            bar.appendChild(seg);
        }
    }
    initBar('hudBarSystem');
    initBar('hudBarCpu');
    initBar('hudBarMem');

    function setBar(barId, percent, invert) {
        var bar = document.getElementById(barId);
        if (!bar) return;
        var p = Math.max(0, Math.min(100, percent));
        var litCount = Math.round((p / 100) * NUM_SEGMENTS);
        var segs = bar.querySelectorAll('.hud-seg');
        // Determine color class
        var cls = '';
        if (invert) {
            if (p <= 25) cls = 'critical';
            else if (p <= 50) cls = 'warning';
        } else {
            if (p >= 90) cls = 'critical';
            else if (p >= 75) cls = 'warning';
        }
        segs.forEach(function(seg, i) {
            seg.classList.remove('lit', 'warning', 'critical');
            if (i < litCount) {
                seg.classList.add('lit');
                if (cls) seg.classList.add(cls);
            }
        });
        // Update value color
        var valEl = bar.parentElement.querySelector('.hud-row-value');
        if (valEl) {
            valEl.classList.remove('warning', 'critical');
            if (cls) valEl.classList.add(cls);
        }
    }

    // ── Fetch system stats ──
    function fetchSystemStats() {
        fetch('/api/dashboard/system-stats')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) return;

                // CPU
                var cpuPct = Math.round(data.cpu_percent || 0);
                setBar('hudBarCpu', cpuPct);
                var cpuValEl = document.getElementById('hudValCpu');
                if (cpuValEl) cpuValEl.textContent = cpuPct + '%';

                // Memory
                var memPct = Math.round(data.memory_percent || 0);
                setBar('hudBarMem', memPct);
                var memValEl = document.getElementById('hudValMem');
                if (memValEl) memValEl.textContent = memPct + '%';
                var memDetail = document.getElementById('hudMemDetail');
                if (memDetail) {
                    memDetail.textContent = (data.memory_used_gb || '--') + '/' + (data.memory_total_gb || '--') + ' GB';
                }

                // Uptime
                var uptimeEl = document.getElementById('hudValUptime');
                if (uptimeEl && data.uptime_formatted) {
                    uptimeEl.textContent = data.uptime_formatted;
                }

                // System aggregate: average of CPU and Memory health (inverse of usage)
                var systemPct = Math.round(100 - (cpuPct + memPct) / 2);
                if (systemPct < 0) systemPct = 0;
                setBar('hudBarSystem', systemPct, true);
                var sysValEl = document.getElementById('hudValSystem');
                if (sysValEl) sysValEl.textContent = systemPct + '%';

                // Reset footer refresh timer
                if (typeof lastRefreshTime !== 'undefined') {
                    lastRefreshTime = Date.now();
                }
            })
            .catch(function(err) {
                console.warn('HUD system-stats fetch failed:', err);
            });
    }

    // ── Fetch AI status ──
    // Store globally so Mission Briefing can reuse
    window._archieAiStatusData = null;

    function fetchAiStatus() {
        fetch('/api/dashboard/ai-status')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) return;

                // Store globally for mission briefing reuse
                window._archieAiStatusData = data;

                // AI dot
                var dot = document.getElementById('hudAiDot');
                var label = document.getElementById('hudValAi');
                if (dot) {
                    if (data.ai_online) {
                        dot.classList.remove('offline');
                    } else {
                        dot.classList.add('offline');
                    }
                }
                if (label) {
                    label.textContent = data.ai_online ? archieI18n.t('js.status.online', 'ONLINE') : archieI18n.t('js.status.offline', 'OFFLINE');
                }

                // ARCHIE status (consciousness service)
                var archieDot = document.getElementById('hudArchieDot');
                var archieLabel = document.getElementById('hudValArchie');
                if (archieDot) {
                    var consciousnessOk = data.services && data.services.consciousness === 'online';
                    if (consciousnessOk) {
                        archieDot.classList.remove('offline');
                        archieDot.classList.add('online');
                    } else {
                        archieDot.classList.remove('online');
                        archieDot.classList.add('offline');
                    }
                }
                if (archieLabel) {
                    var consciousnessOk2 = data.services && data.services.consciousness === 'online';
                    archieLabel.textContent = consciousnessOk2 ? archieI18n.t('js.status.online', 'ONLINE') : archieI18n.t('js.status.offline', 'OFFLINE');
                }

                // Agents count
                var agentsEl = document.getElementById('hudValAgents');
                if (agentsEl) {
                    agentsEl.textContent = data.active_agents || 0;
                }

                // Update mission briefing AI insights card
                if (typeof renderAiInsights === 'function') {
                    renderAiInsights(data);
                }
            })
            .catch(function(err) {
                console.warn('HUD ai-status fetch failed:', err);
            });
    }

    // ── Fetch notification count ──
    function fetchNotifCount() {
        fetch('/api/notifications/count')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) return;
                var badge = document.getElementById('cbNotifBadge');
                if (!badge) return;
                var count = data.unread || 0;
                if (count > 0) {
                    badge.textContent = count > 99 ? '99+' : count;
                    badge.classList.remove('hidden');
                } else {
                    badge.classList.add('hidden');
                }
            })
            .catch(function(err) {
                console.warn('Notification count fetch failed:', err);
            });
    }

    // ── Initial fetch + interval ──
    // Wait until dashboard is visible (boot may still be running)
    function startHUDPolling() {
        fetchSystemStats();
        fetchAiStatus();
        fetchNotifCount();
        setInterval(fetchSystemStats, 15000);
        setInterval(fetchAiStatus, 15000);
        setInterval(fetchNotifCount, 60000);
    }

    // Start polling immediately (boot sequence handles frame visibility separately)
    startHUDPolling();
})();

// ═══════════════════════════════════════════════════════════════════════════════
// MISSION BRIEFING — Collapsible sections (admin-only)
// Recent Activity + System Alerts — collapsed by default, badge counts for new items
// ═══════════════════════════════════════════════════════════════════════════════
(function initMissionBriefing() {
    'use strict';

    // Guard: if mission-briefing section isn't in DOM (non-admin), skip entirely
    if (!document.getElementById('mission-briefing')) return;

    // ── localStorage keys for "last seen" counts ──
    var STORAGE_KEY = 'archie_briefing_seen';

    function getSeenCounts() {
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : { activity: 0, alerts: 0 };
        } catch (e) { return { activity: 0, alerts: 0 }; }
    }

    function setSeenCount(section, count) {
        var seen = getSeenCounts();
        seen[section] = count;
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(seen)); } catch (e) {}
    }

    // ── Update badge for a section ──
    function updateBadge(section, totalCount) {
        var badgeId = section === 'activity' ? 'briefingBadgeActivity' : 'briefingBadgeAlerts';
        var badge = document.getElementById(badgeId);
        if (!badge) return;

        var seen = getSeenCounts();
        var newCount = Math.max(0, totalCount - (seen[section] || 0));

        badge.textContent = newCount > 0 ? newCount : '';
        badge.setAttribute('data-count', newCount);
    }

    // Track current item counts so toggle can mark as seen
    var _currentCounts = { activity: 0, alerts: 0 };

    // ── Toggle section open/close ──
    window.toggleBriefingSection = function(section) {
        var sectionId = section === 'activity' ? 'briefingSectionActivity' : 'briefingSectionAlerts';
        var el = document.getElementById(sectionId);
        if (!el) return;

        var isOpen = el.classList.toggle('is-open');

        // When opening: mark all current items as seen
        if (isOpen) {
            setSeenCount(section, _currentCounts[section] || 0);
            var badgeId = section === 'activity' ? 'briefingBadgeActivity' : 'briefingBadgeAlerts';
            var badge = document.getElementById(badgeId);
            if (badge) {
                badge.textContent = '';
                badge.setAttribute('data-count', '0');
            }
        }
    };

    // timeAgo is defined as window.timeAgo above (shared with notifications)

    // ── Render Recent Activity ──
    function renderRecentActivity(activities) {
        var container = document.getElementById('briefingActivity');
        if (!container) return;

        if (!activities || activities.length === 0) {
            _currentCounts.activity = 0;
            updateBadge('activity', 0);
            var noActivitySpan = document.createElement('span');
            noActivitySpan.className = 'briefing-muted';
            noActivitySpan.textContent = archieI18n.t('js.briefing.no_recent_activity', 'No recent activity');
            container.innerHTML = '';
            container.appendChild(noActivitySpan);
            return;
        }

        var items = activities.slice(0, 15);
        _currentCounts.activity = items.length;
        updateBadge('activity', items.length);

        var ul = document.createElement('ul');
        ul.className = 'briefing-activity-list';

        var sourceIcons = {
            user: '\u25C6',
            bridge: '\u2726',
            governance: '\u2738',
            knowledge: '\u25CB'
        };

        items.forEach(function(item) {
            var li = document.createElement('li');
            li.className = 'briefing-activity-item';
            if (item.source) li.setAttribute('data-source', item.source);

            var iconSpan = document.createElement('span');
            iconSpan.className = 'briefing-activity-icon';
            iconSpan.textContent = sourceIcons[item.source] || '\u25C6';
            li.appendChild(iconSpan);

            var textSpan = document.createElement('span');
            textSpan.className = 'briefing-activity-text';
            textSpan.textContent = item.action || 'Activity';
            textSpan.title = item.details || item.action || '';

            var timeSpan = document.createElement('span');
            timeSpan.className = 'briefing-activity-time';
            timeSpan.textContent = timeAgo(item.timestamp);

            li.appendChild(textSpan);
            li.appendChild(timeSpan);
            ul.appendChild(li);
        });

        container.innerHTML = '';
        container.appendChild(ul);
    }

    // ── Render System Alerts (legacy — kept for reference) ──
    function _renderAlertsLegacy(data) {
        var container = document.getElementById('briefingAlerts');
        if (!container) return;

        var alerts = data.alerts || [];
        var serviceIssues = data.service_issues || [];
        var totalAlerts = alerts.length + serviceIssues.length;

        _currentCounts.alerts = totalAlerts;
        updateBadge('alerts', totalAlerts);

        // If nothing is wrong, show nominal
        if (totalAlerts === 0) {
            container.innerHTML = '';
            var nominal = document.createElement('div');
            nominal.className = 'briefing-alert-nominal';
            var nomIcon = document.createElement('i');
            nomIcon.setAttribute('data-lucide', 'check-circle');
            nominal.appendChild(nomIcon);
            var nomText = document.createElement('span');
            nomText.textContent = archieI18n.t('js.briefing.all_nominal', 'ALL SYSTEMS NOMINAL');
            nominal.appendChild(nomText);
            container.appendChild(nominal);
            if (typeof lucide !== 'undefined') lucide.createIcons();
            return;
        }

        container.innerHTML = '';

        serviceIssues.forEach(function(issue) {
            var div = document.createElement('div');
            var severity = (issue.status === 'error' || issue.status === 'down' || issue.status === 'offline') ? 'alert-critical' : 'alert-warning';
            div.className = 'briefing-alert-item ' + severity;

            var icon = document.createElement('i');
            icon.setAttribute('data-lucide', severity === 'alert-critical' ? 'x-circle' : 'alert-triangle');
            div.appendChild(icon);

            var textWrap = document.createElement('span');
            textWrap.className = 'briefing-alert-text';
            var titleSpan = document.createElement('span');
            titleSpan.className = 'briefing-alert-title';
            titleSpan.textContent = (issue.service || 'Service').replace('_', ' ').toUpperCase() + ' \u2014 ' + (issue.status || 'issue');
            textWrap.appendChild(titleSpan);
            if (issue.error) {
                var detail = document.createElement('span');
                detail.className = 'briefing-alert-detail';
                detail.textContent = issue.error;
                textWrap.appendChild(detail);
            }
            div.appendChild(textWrap);
            container.appendChild(div);
        });

        alerts.forEach(function(alert) {
            var div = document.createElement('div');
            var severity = 'alert-info';
            if (alert.priority === 'high' || alert.priority === 'critical') {
                severity = 'alert-critical';
            } else if (alert.priority === 'medium' || alert.priority === 'warning') {
                severity = 'alert-warning';
            }
            div.className = 'briefing-alert-item ' + severity;

            var iconMap = {
                'alert-critical': 'x-circle',
                'alert-warning': 'alert-triangle',
                'alert-info': 'info'
            };
            var icon = document.createElement('i');
            icon.setAttribute('data-lucide', iconMap[severity] || 'info');
            div.appendChild(icon);

            var textWrap = document.createElement('span');
            textWrap.className = 'briefing-alert-text';
            var titleSpan = document.createElement('span');
            titleSpan.className = 'briefing-alert-title';
            titleSpan.textContent = alert.title || 'Alert';
            textWrap.appendChild(titleSpan);
            if (alert.message) {
                var detail = document.createElement('span');
                detail.className = 'briefing-alert-detail';
                detail.textContent = alert.message;
                textWrap.appendChild(detail);
            }
            div.appendChild(textWrap);

            if (alert.timestamp) {
                var time = document.createElement('span');
                time.className = 'briefing-alert-time';
                time.textContent = timeAgo(alert.timestamp);
                div.appendChild(time);
            }
            container.appendChild(div);
        });

        if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    // ── Keep renderAiInsights global for HUD (no-op if briefingAi element missing) ──
    window.renderAiInsights = function renderAiInsights(data) {
        var container = document.getElementById('briefingAi');
        if (!container) return;
    };

    // ── Fetch Recent Activity ──
    function fetchRecentActivity() {
        fetch('/api/dashboard/recent-activity')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success) {
                    renderRecentActivity(data.activities);
                }
            })
            .catch(function(err) {
                console.warn('Mission briefing recent-activity fetch failed:', err);
                var container = document.getElementById('briefingActivity');
                if (container) {
                    container.innerHTML = '';
                    var actErrSpan = document.createElement('span');
                    actErrSpan.className = 'briefing-muted';
                    actErrSpan.textContent = archieI18n.t('js.briefing.unable_load_activity', 'Unable to load activity');
                    container.appendChild(actErrSpan);
                }
            });
    }

    // ── Build a single briefing alert item — expandable with click-to-read ──
    function _buildBriefingAlertItem(a, severity) {
        var container = document.createElement('div');
        container.style.cssText = 'border-bottom:1px solid rgba(0,229,255,0.06);';

        // Summary row (always visible)
        var div = document.createElement('div');
        div.className = 'briefing-alert-item ' + (severity || 'alert-warning');
        div.style.cursor = 'pointer';

        var icon = document.createElement('i');
        icon.setAttribute('data-lucide', severity === 'alert-critical' ? 'x-circle' : 'alert-triangle');
        div.appendChild(icon);

        var textWrap = document.createElement('span');
        textWrap.className = 'briefing-alert-text';
        textWrap.style.flex = '1';

        var titleSpan = document.createElement('span');
        titleSpan.className = 'briefing-alert-title';
        titleSpan.textContent = a.title || 'Alert';
        textWrap.appendChild(titleSpan);

        div.appendChild(textWrap);

        // Chevron
        var chevron = document.createElement('span');
        chevron.textContent = '\u25B8';
        chevron.style.cssText = 'color:#64748b;font-size:0.7rem;flex-shrink:0;transition:transform 0.2s ease;margin-left:auto;';
        div.appendChild(chevron);

        container.appendChild(div);

        // Detail panel (hidden by default)
        var detail = document.createElement('div');
        detail.style.cssText = 'display:none;padding:6px 12px 10px 32px;';

        // Message
        if (a.message) {
            var msgEl = document.createElement('div');
            msgEl.style.cssText = 'font-size:0.65rem;color:#94a3b8;margin-bottom:6px;line-height:1.4;word-break:break-word;';
            msgEl.textContent = a.message;
            detail.appendChild(msgEl);
        }

        // Meta row
        var meta = document.createElement('div');
        meta.style.cssText = 'display:flex;gap:8px;font-size:0.55rem;color:#475569;font-family:"IBM Plex Mono",monospace;flex-wrap:wrap;';

        var srcEl = document.createElement('span');
        srcEl.textContent = (a.source || 'system').replace(/_/g, ' ').toUpperCase();
        srcEl.style.cssText = 'background:rgba(0,229,255,0.08);padding:1px 6px;border-radius:3px;';
        meta.appendChild(srcEl);

        var priEl = document.createElement('span');
        priEl.textContent = (a.priority || 'medium').toUpperCase();
        var priColor = a.priority === 'critical' ? '#ef4444' : a.priority === 'high' ? '#ff9f43' : '#64748b';
        priEl.style.cssText = 'color:' + priColor + ';';
        meta.appendChild(priEl);

        if (a.timestamp) {
            var tsEl = document.createElement('span');
            try { tsEl.textContent = new Date(a.timestamp).toLocaleString(); } catch (e) { tsEl.textContent = a.timestamp; }
            meta.appendChild(tsEl);
        }
        detail.appendChild(meta);

        // Mark read button
        var markBtn = document.createElement('button');
        markBtn.textContent = 'MARK READ';
        markBtn.style.cssText = 'margin-top:8px;background:rgba(0,229,255,0.1);border:1px solid rgba(0,229,255,0.2);color:#00e5ff;font-family:"Antonio",sans-serif;font-size:0.6rem;letter-spacing:1px;padding:3px 10px;border-radius:4px;cursor:pointer;';
        markBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            fetch('/api/alerts/unified/mark-read', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ alert_key: a.id })
            }).then(function() {
                container.style.opacity = '0.4';
                a.is_read = true;
                markBtn.textContent = 'READ';
                markBtn.disabled = true;
                // Refresh counts
                fetchAlerts();
            });
        });
        detail.appendChild(markBtn);

        container.appendChild(detail);

        // Toggle on click
        var expanded = false;
        div.addEventListener('click', function() {
            expanded = !expanded;
            detail.style.display = expanded ? 'block' : 'none';
            chevron.style.transform = expanded ? 'rotate(90deg)' : 'rotate(0deg)';
        });

        return container;
    }

    // ── Render System Alerts (unified endpoint) ──
    function renderAlertsUnified(data) {
        var container = document.getElementById('briefingAlerts');
        if (!container) return;

        var counts = data.counts || {};
        var totalAlerts = counts.unread || 0;

        _currentCounts.alerts = totalAlerts;
        updateBadge('alerts', totalAlerts);

        container.textContent = '';

        if (totalAlerts === 0) {
            var nominal = document.createElement('div');
            nominal.className = 'briefing-alert-nominal';
            var nomIcon = document.createElement('i');
            nomIcon.setAttribute('data-lucide', 'check-circle');
            nominal.appendChild(nomIcon);
            var nomText = document.createElement('span');
            nomText.textContent = archieI18n.t('js.briefing.all_nominal', 'ALL SYSTEMS NOMINAL');
            nominal.appendChild(nomText);
            container.appendChild(nominal);
            if (typeof lucide !== 'undefined') lucide.createIcons();
            return;
        }

        // Critical alerts first
        var criticals = data.critical || [];
        criticals.forEach(function(a) {
            container.appendChild(_buildBriefingAlertItem(a, 'alert-critical'));
        });

        // Category alerts (unread only), in fixed order
        var categories = data.categories || {};
        var catOrder = ['infrastructure', 'agents', 'security', 'jobs'];
        catOrder.forEach(function(cat) {
            var items = (categories[cat] || []).filter(function(a) {
                return !a.is_read;
            });
            var header = document.createElement('div');
            header.style.cssText = [
                'font-family:Antonio,sans-serif',
                'font-size:0.7rem',
                'letter-spacing:0.1em',
                'color:var(--archie-accent,#00e5ff)',
                'border-top:1px solid var(--archie-accent,#00e5ff)',
                'padding-top:4px',
                'margin-top:6px',
                'text-transform:uppercase'
            ].join(';');
            header.textContent = cat;
            container.appendChild(header);

            if (items.length === 0) {
                var none = document.createElement('div');
                none.style.cssText = 'color:var(--archie-text-muted,#666);font-size:0.75rem;padding:2px 0 2px 4px;font-style:italic;';
                none.textContent = '— none —';
                container.appendChild(none);
            } else {
                items.forEach(function(a) {
                    var sev = (a.severity === 'critical' || a.priority === 'critical') ? 'alert-critical' : 'alert-warning';
                    container.appendChild(_buildBriefingAlertItem(a, sev));
                });
            }
        });

        if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    // ── Fetch Alerts ──
    function fetchAlerts() {
        fetch('/api/alerts/unified')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success) {
                    renderAlertsUnified(data);
                }
            })
            .catch(function(err) {
                console.warn('Mission briefing alerts fetch failed:', err);
                var container = document.getElementById('briefingAlerts');
                if (container) {
                    container.innerHTML = '';
                    var alertErrSpan = document.createElement('span');
                    alertErrSpan.className = 'briefing-muted';
                    alertErrSpan.textContent = archieI18n.t('js.briefing.unable_load_alerts', 'Unable to load alerts');
                    container.appendChild(alertErrSpan);
                }
            });
    }

    // ── Start fetching ──
    function startBriefingFetch() {
        fetchRecentActivity();
        fetchAlerts();

        // Update footer timestamp
        var tsEl = document.getElementById('briefingTimestamp');
        if (tsEl) {
            var now = new Date();
            var hh = String(now.getHours()).padStart(2, '0');
            var mm = String(now.getMinutes()).padStart(2, '0');
            var ss = String(now.getSeconds()).padStart(2, '0');
            tsEl.textContent = 'UPDATED ' + hh + ':' + mm + ':' + ss;
        }

        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }

    startBriefingFetch();
})();

// ═══════════════════════════════════════════════════════════════════════════════
// FEATURED MODULES — Priority Stations — Task 5
// Pin/unpin from category grid stars, max 4, dynamic rebuild
// ═══════════════════════════════════════════════════════════════════════════════
(function initFeaturedModules() {
    'use strict';

    var STORAGE_KEY = 'archie-pinned-modules';
    var MAX_PINS = 6;
    var DEFAULT_PINS = ['archie_chat', 'bridge', 'consciousness'];

    // ── Get / save pinned modules ──
    function getPinnedModules() {
        try {
            var stored = localStorage.getItem(STORAGE_KEY);
            if (stored !== null) {
                var parsed = JSON.parse(stored);
                if (Array.isArray(parsed)) return parsed.slice(0, MAX_PINS);
            }
        } catch (e) {}
        return DEFAULT_PINS.slice();
    }

    function savePinnedModules(pins) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(pins.slice(0, MAX_PINS)));
        } catch (e) {
            console.warn('Failed to save pinned modules:', e);
        }
    }

    // ── Sync all star buttons (grid + featured) to match localStorage ──
    function syncAllStars() {
        var pins = getPinnedModules();
        // Grid stars
        document.querySelectorAll('.module-pin-btn').forEach(function(btn) {
            var id = btn.getAttribute('data-pin-id');
            btn.classList.toggle('pinned', pins.indexOf(id) >= 0);
            btn.title = pins.indexOf(id) >= 0 ? archieI18n.t('js.pin.unpin_from', 'Unpin from Priority Stations') : archieI18n.t('js.pin.pin_to', 'Pin to Priority Stations');
        });
        // Featured card stars
        document.querySelectorAll('.featured-pin-btn').forEach(function(btn) {
            var id = btn.getAttribute('data-pin-id');
            btn.classList.toggle('pinned', pins.indexOf(id) >= 0);
            btn.title = pins.indexOf(id) >= 0 ? archieI18n.t('js.pin.unpin_module', 'Unpin module') : archieI18n.t('js.pin.pin_module', 'Pin module');
        });
    }

    // ── Build a featured card HTML from module data ──
    function buildFeaturedCard(mod) {
        var nameKey = 'module.' + mod.id + '.name';
        var descKey = 'module.' + mod.id + '.desc';
        var translatedName = archieI18n.t(nameKey, mod.name);
        var translatedDesc = archieI18n.t(descKey, mod.desc);
        return '<a href="' + mod.route + '" class="featured-card" data-module-id="' + mod.id + '" data-category="' + mod.category + '">' +
            '<button class="featured-pin-btn pinned" data-pin-id="' + mod.id + '" title="' + archieI18n.t('js.pin.unpin_module', 'Unpin module') + '" ' +
                'onclick="event.preventDefault(); event.stopPropagation(); toggleGridPin(this, \'' + mod.id + '\');">' +
                '<i data-lucide="star"></i></button>' +
            '<div class="featured-card-icon"><i data-lucide="' + mod.icon + '"></i></div>' +
            '<div class="featured-card-name" data-i18n="' + nameKey + '">' + translatedName + '</div>' +
            '<div class="featured-card-desc" data-i18n="' + descKey + '">' + translatedDesc + '</div>' +
            '<div class="featured-card-footer">' +
                '<div class="featured-card-status">' +
                    '<span class="featured-status-dot online" id="featStatus-' + mod.id + '"></span>' +
                    '<span class="featured-status-text" id="featStatusText-' + mod.id + '">' + archieI18n.t('js.status.online', 'ONLINE') + '</span>' +
                '</div>' +
            '</div></a>';
    }

    // ── Get module data from its grid card's data attributes ──
    function getModuleData(moduleId) {
        var card = document.querySelector('.module-card[data-module-id="' + moduleId + '"]');
        if (!card) return null;
        return {
            id: moduleId,
            name: card.getAttribute('data-module-name') || moduleId,
            icon: card.getAttribute('data-module-icon') || 'box',
            desc: card.getAttribute('data-module-desc') || '',
            route: card.getAttribute('href') || '#',
            category: card.getAttribute('data-module-category') || ''
        };
    }

    // ── Rebuild the featured cards row from current pins ──
    function rebuildFeaturedCards() {
        var pins = getPinnedModules();
        var row = document.getElementById('featuredCardsRow');
        var section = document.getElementById('featured-modules');
        if (!row) return;

        if (pins.length === 0) {
            // Hide section if no pins
            if (section) section.style.display = 'none';
            return;
        }
        if (section) section.style.display = '';

        var html = '';
        pins.forEach(function(pinId) {
            var mod = getModuleData(pinId);
            if (mod) {
                html += buildFeaturedCard(mod);
            }
        });

        row.innerHTML = html;

        // Re-render Lucide icons
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }

        // Re-apply i18n translations to new DOM elements
        if (typeof archieI18n !== 'undefined' && archieI18n.getCurrentLanguage() !== 'en') {
            archieI18n.switchLanguage(archieI18n.getCurrentLanguage());
        }

        syncAllStars();
        fetchModuleHealth();
    }

    // ── Toggle pin from grid or featured card star (exposed globally) ──
    window.toggleGridPin = function(btn, moduleId) {
        var pins = getPinnedModules();
        var idx = pins.indexOf(moduleId);

        if (idx >= 0) {
            // Unpin
            pins.splice(idx, 1);
        } else {
            // Pin — enforce max
            if (pins.length >= MAX_PINS) {
                // Brief flash on the button to indicate limit
                btn.style.color = '#ff3b3b';
                setTimeout(function() { btn.style.color = ''; }, 600);
                return;
            }
            pins.push(moduleId);
        }

        savePinnedModules(pins);
        rebuildFeaturedCards();
    };

    // Keep old togglePin working for featured card stars
    window.togglePin = window.toggleGridPin;

    // ── Capture-phase handler: prevent <a> navigation when clicking pin stars ──
    document.addEventListener('click', function(e) {
        var pinBtn = e.target.closest('.module-pin-btn, .featured-pin-btn');
        if (pinBtn) {
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            var moduleId = pinBtn.getAttribute('data-pin-id');
            if (moduleId) toggleGridPin(pinBtn, moduleId);
        }
    }, true);  // true = capture phase, fires before <a> click

    // ── Fetch module health and update featured status dots ──
    function fetchModuleHealth() {
        fetch('/api/modules/health')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) return;
                var modules = data.modules || data.health || {};

                document.querySelectorAll('.featured-card').forEach(function(card) {
                    var moduleId = card.getAttribute('data-module-id');
                    var dot = document.getElementById('featStatus-' + moduleId);
                    var text = document.getElementById('featStatusText-' + moduleId);
                    if (!dot || !text) return;

                    var health = modules[moduleId];
                    var isHealthy = health ? (health.healthy || health.status === 'active' || health.status === 'ok') : true;

                    dot.classList.remove('online', 'offline');
                    dot.classList.add(isHealthy ? 'online' : 'offline');
                    text.textContent = isHealthy ? archieI18n.t('js.status.online', 'ONLINE') : archieI18n.t('js.status.offline', 'OFFLINE');
                });
            })
            .catch(function(err) {
                console.warn('Featured module health fetch failed:', err);
                document.querySelectorAll('.featured-status-dot').forEach(function(dot) { dot.classList.add('online'); });
                document.querySelectorAll('.featured-status-text').forEach(function(text) { text.textContent = archieI18n.t('js.status.online', 'ONLINE'); });
            });
    }

    // ── Start when dashboard is visible ──
    function startFeaturedModules() {
        rebuildFeaturedCards();
    }

    // Start immediately (boot sequence handles frame visibility separately)
    startFeaturedModules();
})();

// ═══════════════════════════════════════════════════════════════════════════════
// CATEGORY GRID — LCARS Frame Collapse/Expand, Health Status, Staggered Entry
// Task 8 of Dashboard Rebuild — Full LCARS OKUDAGRAM frames per category
// ═══════════════════════════════════════════════════════════════════════════════

// ── Toggle category collapse/expand (uses lcars-frame--collapsed) ──
function toggleCategory(catKey) {
    'use strict';
    var STORAGE_KEY = 'archie-dashboard-collapsed';
    var frame = document.querySelector('.category-frame[data-category="' + catKey + '"]');
    if (!frame) return;

    frame.classList.toggle('lcars-frame--collapsed');

    // Update aria-expanded on the header bar
    var bar = frame.querySelector('.lcars-bar');
    if (bar) {
        bar.setAttribute('aria-expanded', !frame.classList.contains('lcars-frame--collapsed'));
    }

    // Save state to localStorage
    var collapsed = [];
    try {
        collapsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    } catch(e) { collapsed = []; }

    var idx = collapsed.indexOf(catKey);
    if (frame.classList.contains('lcars-frame--collapsed')) {
        if (idx === -1) collapsed.push(catKey);
    } else {
        if (idx !== -1) collapsed.splice(idx, 1);
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(collapsed));
}

(function initCategoryGrid() {
    'use strict';

    var STORAGE_KEY = 'archie-dashboard-collapsed';

    // ── Restore collapsed state from localStorage ──
    function restoreCollapseState() {
        var collapsed = [];
        try {
            collapsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
        } catch(e) { collapsed = []; }

        collapsed.forEach(function(catKey) {
            var frame = document.querySelector('.category-frame[data-category="' + catKey + '"]');
            if (frame) {
                frame.classList.add('lcars-frame--collapsed');
                var bar = frame.querySelector('.lcars-bar');
                if (bar) bar.setAttribute('aria-expanded', 'false');
            }
        });
    }

    // ── Staggered card materialize animation ──
    function animateCards() {
        var cards = document.querySelectorAll('.category-grid .module-card');
        cards.forEach(function(card, index) {
            card.style.opacity = '0';
            card.style.animationDelay = (index * 0.05) + 's';
            card.classList.add('materialize');
        });
    }

    // ── Update category grid health status dots ──
    function updateCategoryGridHealth(healthData) {
        var cards = document.querySelectorAll('.category-grid .module-card');
        cards.forEach(function(card) {
            var moduleId = card.getAttribute('data-module-id');
            var statusContainer = card.querySelector('[data-status-for="' + moduleId + '"]');
            if (!statusContainer) return;

            var dot = statusContainer.querySelector('.status-dot');
            var text = statusContainer.querySelector('.status-text');
            if (!dot || !text) return;

            var health = healthData[moduleId];
            var isHealthy = false;

            if (health) {
                isHealthy = health.healthy || health.status === 'active' || health.status === 'ok';
            } else {
                // If no specific health data, assume online
                isHealthy = true;
            }

            dot.classList.remove('checking', 'online', 'offline', 'degraded');
            if (isHealthy) {
                dot.classList.add('online');
                text.textContent = archieI18n.t('js.status.online', 'ONLINE');
            } else {
                dot.classList.add('offline');
                text.textContent = archieI18n.t('js.status.offline', 'OFFLINE');
            }
        });
    }

    // ── Fetch health data for all modules in category grid ──
    function fetchCategoryHealth() {
        fetch('/api/modules/health')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) return;
                var modules = data.modules || data.health || {};
                updateCategoryGridHealth(modules);
            })
            .catch(function(err) {
                console.warn('Category grid health fetch failed:', err);
                // On error, mark all as online (graceful fallback)
                var dots = document.querySelectorAll('.category-grid .status-dot');
                dots.forEach(function(dot) {
                    dot.classList.remove('checking');
                    dot.classList.add('online');
                });
                var texts = document.querySelectorAll('.category-grid .status-text');
                texts.forEach(function(text) {
                    text.textContent = archieI18n.t('js.status.online', 'ONLINE');
                });
            });
    }

    // ── Start category grid when dashboard is visible ──
    function startCategoryGrid() {
        restoreCollapseState();
        animateCards();
        // Slight delay to let featured modules health fetch finish first
        setTimeout(fetchCategoryHealth, 500);
    }

    // Start immediately (boot sequence handles frame visibility separately)
    startCategoryGrid();
})();

// ═══════════════════════════════════════════════════════════════════════════════
// STATUS FOOTER — Clock, Connection Status, Refresh Timer
// Task 7 of Dashboard Rebuild
// ═══════════════════════════════════════════════════════════════════════════════

// Track last data refresh time (updated by fetchSystemStats)
var lastRefreshTime = Date.now();

// Update clock every second
function updateFooterTime() {
    var el = document.getElementById('footerTime');
    if (!el) return;
    var now = new Date();
    var h = String(now.getHours()).padStart(2, '0');
    var m = String(now.getMinutes()).padStart(2, '0');
    var s = String(now.getSeconds()).padStart(2, '0');
    el.textContent = h + ':' + m + ':' + s;
}
setInterval(updateFooterTime, 1000);
updateFooterTime();

// Update "last refreshed" counter
function updateRefreshCounter() {
    var el = document.getElementById('footerRefresh');
    if (!el) return;
    var ago = Math.floor((Date.now() - lastRefreshTime) / 1000);
    el.textContent = archieI18n.t('js.footer.last_refreshed', 'Last refreshed') + ' ' + ago + archieI18n.t('js.time.seconds_ago', 's ago');
}
setInterval(updateRefreshCounter, 1000);

// ═══════════════════════════════════════════════════════════════════════════════
// FINAL POLISH — Ensure Lucide icons render after all sections
// ═══════════════════════════════════════════════════════════════════════════════
(function finalIconRender() {
    // Render Lucide icons once DOM is fully ready
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
})();

// ═══════════════════════════════════════════════════════════════════════════════
// SHUTDOWN SEQUENCE — Animated logout with ARCHIE personality
// ═══════════════════════════════════════════════════════════════════════════════
function startShutdownSequence() {
    // Prevent double-trigger
    if (document.getElementById('shutdownOverlay')) return;

    var overlay = document.createElement('div');
    overlay.className = 'shutdown-overlay';
    overlay.id = 'shutdownOverlay';

    var scanline = document.createElement('div');
    scanline.className = 'shutdown-scanline';

    var terminal = document.createElement('div');
    terminal.className = 'shutdown-terminal';
    overlay.appendChild(terminal);

    document.body.appendChild(overlay);
    document.body.appendChild(scanline);

    // Fade in
    requestAnimationFrame(function() {
        overlay.classList.add('visible');
    });

    // Shutdown lines — system + ARCHIE personality (translated via i18n)
    var _t = (window.archieI18n && archieI18n.t) ? archieI18n.t.bind(archieI18n) : function(k, fb) { return fb || k; };
    var lines = [
        { text: _t('shutdown.session', '[SESSION] Terminating user session...'), delay: 400 },
        { text: _t('shutdown.bridge', '[BRIDGE] Securing all active stations...'), delay: 350 },
        { text: _t('shutdown.memory', '[MEMORY] Flushing session cache \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588 OK'), delay: 400 },
        { text: _t('shutdown.agents', '[AGENTS] Standing down 10 agents...'), delay: 500 },
        { cls: 'archie-msg', text: '<span class="archie-name">A.R.C.H.I.E.:</span> ' + _t('shutdown.archie1', 'Already? We were just getting started.'), delay: 700 },
        { text: _t('shutdown.network', '[NETWORK] Closing secure channels...'), delay: 350 },
        { text: _t('shutdown.creed', '[C.R.E.E.D.] Governance checkpoint .......... PASSED'), delay: 400 },
        { cls: 'archie-msg', text: '<span class="archie-name">A.R.C.H.I.E.:</span> ' + _t('shutdown.archie2', 'Don\u2019t worry \u2014 I\u2019ll keep the lights on.'), delay: 800 },
        { text: _t('shutdown.hud', '[HUD] Powering down vitals display...'), delay: 300 },
        { text: _t('shutdown.matrix', '[MATRIX] Suspending rain animation...'), delay: 300 },
        { cls: 'warning', text: _t('shutdown.core', '[CORE] Main reactor entering standby mode'), delay: 500 },
        { cls: 'archie-msg', text: '<span class="archie-name">A.R.C.H.I.E.:</span> ' + _t('shutdown.archie3', 'I\u2019ll be right here when you get back. Always am. \uD83D\uDC9A'), delay: 900 },
        { text: _t('shutdown.auth', '[AUTH] Session token revoked'), delay: 400 },
        { cls: 'final', text: _t('shutdown.farewell', 'SEE YOU SOON, COMMANDER').toUpperCase().split('').join('\u2009'), delay: 1200 },
    ];

    var totalDelay = 200; // initial pause

    lines.forEach(function(line) {
        totalDelay += line.delay;
        setTimeout(function() {
            var el = document.createElement('div');
            el.className = 'shutdown-line' + (line.cls ? ' ' + line.cls : '');
            el.innerHTML = line.text;
            terminal.appendChild(el);
            requestAnimationFrame(function() {
                el.classList.add('visible');
            });
            // Auto-scroll to bottom
            terminal.scrollTop = terminal.scrollHeight;
        }, totalDelay);
    });

    // Fade out and redirect after all lines
    totalDelay += 1500;
    setTimeout(function() {
        overlay.style.transition = 'opacity 1s ease';
        overlay.style.opacity = '0';
        scanline.remove();
        setTimeout(function() {
            window.location.href = '/logout';
        }, 1000);
    }, totalDelay);
}

/* ============================================================
   Standing-condition row (#5300) — dr / critical / diverted on the dashboard HUD.
   The LCARS header banner only renders on tool pages (the include is not in
   base.html), so during a divert or DR event /dashboard showed NOTHING. This row
   sits under AI CORE / A.R.C.H.I.E. in System Status.
   ONE data source (/api/alerts/unified) → ONE resolver → ONE writer — the #2463
   lesson: two pollers racing on one element is how the header bug shipped.
   Field contract mirrors lcars-header.js _pollNotifications:
     dispatch_mode 'platform'|'news' ⇒ diverted · dr_mode === true ⇒ DR (strict)
     counts.critical > 0 ⇒ critical.  Precedence: dr > critical > diverted > hidden.
   textContent only — never innerHTML.
   ============================================================ */
(function () {
    var row = document.getElementById('hudConditionRow');
    if (!row) return;

    function render(data) {
        var dot = document.getElementById('hudConditionDot');
        var val = document.getElementById('hudValCondition');
        if (!dot || !val) return;
        var mode = (data && data.dispatch_mode) || 'auto';
        var diverted = mode === 'platform' || mode === 'news';
        var drActive = !!(data && data.dr_mode === true);
        var critical = (((data && data.counts) || {}).critical || 0) > 0;
        var state = drActive ? 'dr' : critical ? 'critical' : diverted ? 'diverted' : null;
        if (!state) { row.style.display = 'none'; return; }
        var text, color;
        if (state === 'dr') {
            text = 'RED ALERT · STARBASE LOST COMMUNICATION — running on Citadel standby';
            color = '#ef4444';
        } else if (state === 'critical') {
            text = 'CRITICAL ALERTS ACTIVE — check notifications';
            color = '#ef4444';
        } else {
            text = 'DIVERTED · agent mobility profile: ' + String(mode).toUpperCase() + ' priority';
            color = '#ffcc00';
        }
        val.textContent = text;
        val.style.color = color;
        dot.style.background = color;
        dot.style.boxShadow = '0 0 8px ' + color;
        row.style.display = '';
    }

    // Exposed so a live browser drive can exercise the renderer with a synthetic
    // payload without touching prod flags (ARCHIE_DR_MODE sheds inference — never
    // set it to test UI).
    window._dashRenderCondition = render;

    function poll() {
        fetch('/api/alerts/unified')
            .then(function (r) { return r.json(); })
            .then(function (d) { if (d && d.success) render(d); })
            .catch(function () { /* network blip — keep last rendered state */ });
    }
    poll();
    setInterval(poll, 60000);
})();
