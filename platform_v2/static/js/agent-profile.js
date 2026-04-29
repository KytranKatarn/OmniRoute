/**
 * Unified Agent Profile Renderer
 * Replaces _renderFullProfile (bridge.js) and _renderNodeAgentProfile (starship.js)
 * Both modules include this file and call window.renderAgentProfile().
 *
 * CSS dependencies:
 *   - profile-card / profile-card-header / profile-row / .label / .value  (starship.css)
 *   - crew-profile-portrait / crew-profile-portrait-fallback              (bridge.css)
 *   - crew-profile-ranking / crew-profile-shift-row                       (bridge.css)
 *   - crew-profile-welfare-bar / crew-profile-welfare-fill                (bridge.css)
 *   - crew-status-badge                                                   (bridge.css)
 */
(function () {
    'use strict';

    /* ── helpers ─────────────────────────────────────────────────────── */

    /** HTML-escape user data via DOM */
    function esc(s) {
        if (s == null) return '';
        var d = document.createElement('div');
        d.textContent = String(s);
        return d.innerHTML;
    }

    /** Format milliseconds into human-readable duration */
    function fmtDur(ms) {
        if (ms == null) return '--';
        ms = Number(ms);
        if (ms < 1000) return ms + 'ms';
        if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
        var m = Math.floor(ms / 60000);
        var s = Math.round((ms % 60000) / 1000);
        return m + 'm ' + s + 's';
    }

    /** Stress level to traffic-light colour */
    function stressColor(level) {
        var v = level || 0;
        return v <= 0.4 ? '#00ff41' : v <= 0.7 ? '#ffaa00' : '#ff4444';
    }

    /** Energy level to traffic-light colour (inverted — higher is better) */
    function energyColor(level) {
        var v = level || 0;
        return v >= 0.6 ? '#00ff41' : v >= 0.3 ? '#ffaa00' : '#ff4444';
    }

    /** Create a DOM element with class, style, and text */
    function el(tag, opts) {
        var node = document.createElement(tag);
        if (opts.cls) node.className = opts.cls;
        if (opts.style) node.style.cssText = opts.style;
        if (opts.text) node.textContent = opts.text;
        if (opts.title) node.title = opts.title;
        return node;
    }

    /** Build a profile-card section with header and content children */
    function makeCard(titleText, accentColor) {
        var cardEl = el('div', { cls: 'profile-card' });
        var header = el('div', { cls: 'profile-card-header' });
        var span = el('span', { text: titleText, style: 'border-color:' + accentColor + ';' });
        header.appendChild(span);
        cardEl.appendChild(header);
        return cardEl;
    }

    /** Build a profile-row (label / value pair) — safe DOM construction */
    function makeRow(label, value, valueStyle) {
        var rowEl = el('div', { cls: 'profile-row' });
        rowEl.appendChild(el('span', { cls: 'label', text: label }));
        var valSpan = el('span', { cls: 'value', style: valueStyle || '' });
        valSpan.textContent = value;
        rowEl.appendChild(valSpan);
        return rowEl;
    }

    /* ── main renderer ──────────────────────────────────────────────── */

    /**
     * Render a full agent profile into the given DOM elements.
     *
     * @param {Object} data       - Response from /tools/department-hq/api/agents/<id>/profile
     * @param {Element} bodyEl    - Container element for the profile body
     * @param {Element} titleEl   - Element to set the title text
     * @param {Object} [options]  - { stationColor, agentId, onClose, showSkillEdit,
     *                                showEdit, showDelete, showPersonnelLink,
     *                                onEdit, onDelete, onPersonnelFile }
     */
    function renderAgentProfile(data, bodyEl, titleEl, options) {
        options = options || {};
        if (!data || !data.success) {
            bodyEl.textContent = 'Failed to load profile';
            return;
        }

        var a = data.agent;
        var agentId = options.agentId || a.id;
        var stColor = options.stationColor || a.station_color || '#00e5ff';
        var fullName = ((a.first_name || '') + ' ' + (a.last_name || '')).trim() || a.display_name || a.name;
        titleEl.textContent = fullName;

        // Clear body and build via DOM
        while (bodyEl.firstChild) bodyEl.removeChild(bodyEl.firstChild);

        /* ── 1. Header ───────────────────────────────────────────── */
        var headerRow = el('div', { style: 'display:flex;gap:12px;align-items:center;margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid rgba(255,255,255,0.1);' });

        var portraitSrc = (data.portraits && data.portraits.portrait) || '';
        var initial = (a.first_name || a.name || '?')[0].toUpperCase();

        if (portraitSrc) {
            var img = document.createElement('img');
            img.className = 'crew-profile-portrait';
            img.style.borderColor = stColor;
            img.src = portraitSrc;
            img.alt = initial;
            img.onerror = function () {
                this.style.display = 'none';
                this.nextElementSibling.style.display = 'flex';
            };
            headerRow.appendChild(img);
        }

        var fallback = el('div', { cls: 'crew-profile-portrait-fallback', text: initial, style: 'background:' + stColor + ';' + (portraitSrc ? 'display:none;' : '') });
        headerRow.appendChild(fallback);

        var nameBlock = el('div', { style: 'flex:1;' });
        nameBlock.appendChild(el('div', { text: a.display_name || fullName, style: 'font-size:1rem;font-weight:600;color:#fff;' }));

        var subtitle = el('div', { style: 'font-size:0.75rem;color:rgba(255,255,255,0.5);' });
        subtitle.textContent = a.name + (a.title ? ' \u2014 ' + a.title : '');
        nameBlock.appendChild(subtitle);

        var metaParts = [a.model, a.communication_style, a.worker_type].filter(Boolean);
        var metaText = metaParts.join(' \u2022 ') + (a.pronouns ? ' \u2022 ' + a.pronouns : '');
        nameBlock.appendChild(el('div', { text: metaText, style: 'font-size:0.7rem;color:rgba(255,255,255,0.3);' }));
        headerRow.appendChild(nameBlock);

        var badgeCol = el('div', { style: 'display:flex;flex-direction:column;align-items:flex-end;gap:3px;' });
        var statusBadge = el('span', { cls: 'crew-status-badge ' + (a.status || 'active'), text: (a.status || 'active').toUpperCase(), style: 'font-size:0.7rem;' });
        badgeCol.appendChild(statusBadge);
        var shift = a.shift_state || 'active';
        if (shift !== 'active') {
            badgeCol.appendChild(el('span', { cls: 'crew-status-badge ' + shift, text: shift.replace(/_/g, ' ').toUpperCase(), style: 'font-size:0.65rem;' }));
        }
        headerRow.appendChild(badgeCol);
        bodyEl.appendChild(headerRow);

        /* ── ACTION BUTTONS ROW ─────────────────────────────────── */
        var actionsRow = document.createElement('div');
        actionsRow.style.cssText = 'display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap;';

        // Bridge: Edit Personnel button
        if (options.showEdit) {
            var editBtn = document.createElement('button');
            editBtn.className = 'bm-btn';
            editBtn.style.cssText = 'background:rgba(139,92,246,0.15);border:1px solid rgba(139,92,246,0.3);color:#a78bfa;font-size:0.65rem;padding:3px 10px;cursor:pointer;';
            editBtn.textContent = '\u270E Edit Personnel';
            editBtn.onclick = function() { if (options.onEdit) options.onEdit(agentId); };
            actionsRow.appendChild(editBtn);
        }

        // Bridge: Delete Agent button
        if (options.showDelete) {
            var delBtn = document.createElement('button');
            delBtn.className = 'bm-btn';
            delBtn.style.cssText = 'background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.25);color:#ef4444;font-size:0.65rem;padding:3px 10px;cursor:pointer;';
            delBtn.textContent = '\u2716 Delete';
            delBtn.onclick = function() { if (options.onDelete) options.onDelete(agentId); };
            actionsRow.appendChild(delBtn);
        }

        // Starship: Personnel File link → Bridge profile
        if (options.showPersonnelLink) {
            var persBtn = document.createElement('button');
            persBtn.className = 'bm-btn';
            persBtn.style.cssText = 'background:rgba(34,211,238,0.1);border:1px solid rgba(34,211,238,0.25);color:#22d3ee;font-size:0.65rem;padding:3px 10px;cursor:pointer;';
            persBtn.textContent = '\uD83D\uDCC1 Full Personnel File';
            persBtn.onclick = function() { window.location.href = '/tools/fleet#crew'; };
            actionsRow.appendChild(persBtn);
        }

        // Admin toggle — hidden section for prompts/config
        var editSection = document.createElement('div');
        editSection.style.display = 'none';
        editSection.className = 'profile-edit-section';

        var adminToggle = document.createElement('button');
        adminToggle.className = 'bm-btn';
        adminToggle.style.cssText = 'background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.15);color:rgba(255,255,255,0.4);font-size:0.6rem;padding:2px 8px;cursor:pointer;margin-left:auto;';
        adminToggle.textContent = '\u2699 Admin';
        adminToggle.onclick = function() {
            var isOpen = editSection.style.display !== 'none';
            editSection.style.display = isOpen ? 'none' : 'block';
            adminToggle.textContent = isOpen ? '\u2699 Admin' : '\u2716 Close';
            adminToggle.style.color = isOpen ? 'rgba(255,255,255,0.4)' : '#f472b6';
        };
        actionsRow.appendChild(adminToggle);

        bodyEl.appendChild(actionsRow);

        /* ── 2. Bio ──────────────────────────────────────────────── */
        if (a.bio) {
            var bioCard = makeCard('Bio', stColor);
            bioCard.appendChild(el('div', { text: a.bio, style: 'font-size:0.75rem;color:rgba(255,255,255,0.6);line-height:1.4;' }));
            bodyEl.appendChild(bioCard);
        }

        /* ── 3. System Prompt (EDIT ONLY) ───────────────────────── */
        if (a.system_prompt) {
            var spCard = makeCard('System Prompt', '#00e5ff');
            spCard.appendChild(el('div', { text: a.system_prompt, style: "font-size:0.72rem;color:rgba(255,255,255,0.55);line-height:1.4;font-family:'IBM Plex Mono',monospace;background:rgba(0,0,0,0.3);padding:8px;border-radius:4px;max-height:120px;overflow-y:auto;" }));
            editSection.appendChild(spCard);
        }

        /* ── 4. Portrait Prompt + Generate Button (EDIT ONLY) ──── */
        if (a.avatar_generation_prompt) {
            var ppCard = makeCard('Portrait Prompt', '#f472b6');
            ppCard.appendChild(el('div', { text: a.avatar_generation_prompt, style: "font-size:0.72rem;color:rgba(255,255,255,0.55);line-height:1.4;font-family:'IBM Plex Mono',monospace;background:rgba(0,0,0,0.3);padding:8px;border-radius:4px;max-height:80px;overflow-y:auto;" }));

            // Media Studio link \u2014 generation happens in Media Studio, not here
            var msLink = document.createElement('a');
            msLink.href = '/tools/media-studio#portraits';
            msLink.textContent = 'Edit portrait in Media Studio \u2192';
            msLink.style.cssText = 'display:inline-block;margin-top:8px;font-size:0.7rem;color:#f472b6;text-decoration:none;opacity:0.8;';
            msLink.onmouseover = function() { this.style.opacity = '1'; };
            msLink.onmouseout = function() { this.style.opacity = '0.8'; };
            ppCard.appendChild(msLink);
            editSection.appendChild(ppCard);
        }

        /* ── 5. Configuration (EDIT ONLY) ────────────────────────── */
        var cfgCard = makeCard('Configuration', '#fbbf24');
        cfgCard.appendChild(makeRow('Model', a.model || '--', 'color:#00e5ff;'));
        if (a.temperature !== undefined && a.temperature !== null) {
            cfgCard.appendChild(makeRow('Temperature', String(a.temperature)));
        }
        cfgCard.appendChild(makeRow('Tier', String(a.tier || 1)));
        cfgCard.appendChild(makeRow('Cloneable', a.is_cloneable ? 'Yes' : 'No'));
        if (a.image_model) {
            cfgCard.appendChild(makeRow('Image Model', a.image_model, 'color:#f472b6;'));
        }
        if (a.hardware) {
            cfgCard.appendChild(makeRow('Hardware', a.hardware));
        }
        editSection.appendChild(cfgCard);
        bodyEl.appendChild(editSection);

        /* ── 6. Station ──────────────────────────────────────────── */
        if (a.station_code) {
            var stEl = el('div', { style: 'display:flex;gap:6px;align-items:center;margin-bottom:10px;font-size:0.75rem;' });
            stEl.appendChild(el('span', { text: '\u25A0 ' + (a.station_name || a.station_code), style: 'color:' + stColor + ';font-weight:600;' }));
            bodyEl.appendChild(stEl);
        }

        /* ── 7a. Portrait Variants Grid (Admin only) ─────────── */
        if (data.portrait_variants && data.portrait_variants.length > 0) {
            var pvCard = makeCard('Portrait Variants', '#f472b6');
            var pvGrid = el('div', { style: 'display:grid;grid-template-columns:repeat(3,1fr);gap:8px;' });

            data.portrait_variants.forEach(function (pv) {
                var pvItem = el('div', { style: 'background:rgba(0,0,0,0.3);border-radius:6px;overflow:hidden;cursor:pointer;border:2px solid ' + (pv.is_primary ? '#00e5ff' : 'rgba(255,255,255,0.08)') + ';transition:border-color 0.2s;' + (pv.is_primary ? 'box-shadow:0 0 8px rgba(0,229,255,0.3);' : '') });

                if (pv.canonical_image_path) {
                    var pvImg = document.createElement('img');
                    pvImg.src = pv.canonical_image_path;
                    pvImg.alt = pv.variant_name || 'variant';
                    pvImg.style.cssText = 'width:100%;aspect-ratio:1;object-fit:cover;display:block;';
                    pvImg.onerror = function () { this.style.display = 'none'; };
                    pvItem.appendChild(pvImg);

                    // Click to swap main portrait
                    pvImg.onclick = function () {
                        var mainImg = bodyEl.querySelector('.crew-profile-portrait');
                        if (mainImg) {
                            mainImg.src = pv.canonical_image_path;
                            mainImg.style.display = '';
                        }
                        var fb = bodyEl.querySelector('.crew-profile-portrait-fallback');
                        if (fb) fb.style.display = 'none';
                    };
                }

                var pvInfo = el('div', { style: 'padding:4px 6px;' });
                pvInfo.appendChild(el('div', { text: pv.variant_name || 'Default', style: 'font-size:0.65rem;color:#00e5ff;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;' }));

                if (pv.benchmark_score != null) {
                    var scoreColor = pv.benchmark_score >= 8 ? '#00ff41' : pv.benchmark_score >= 5 ? '#ffaa00' : '#ff4444';
                    pvInfo.appendChild(el('span', { text: pv.benchmark_score.toFixed(1), style: 'font-size:0.6rem;color:' + scoreColor + ';background:rgba(255,255,255,0.05);padding:1px 5px;border-radius:3px;' }));
                }

                if (pv.is_primary) {
                    pvInfo.appendChild(el('div', { text: 'PRIMARY', style: 'font-size:0.5rem;color:#00e5ff;font-weight:700;margin-top:2px;letter-spacing:0.05em;' }));
                }

                pvItem.appendChild(pvInfo);
                pvGrid.appendChild(pvItem);
            });

            pvCard.appendChild(pvGrid);

            if (data.portrait_variants.length === 1) {
                pvCard.appendChild(el('div', { text: 'Single variant \u2014 generate more from Media Studio', style: 'font-size:0.65rem;color:rgba(255,255,255,0.3);text-align:center;margin-top:6px;font-style:italic;' }));
            }

            editSection.appendChild(pvCard);
        }

        /* ── 7b. Bridge Dispatch Benchmark ─────────────────────── */
        if (data.benchmark) {
            var bm = data.benchmark;
            var bmCard = makeCard('Dispatch Benchmark', '#10b981');
            var bmGrid = el('div', { style: 'display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;' });

            // Total Jobs
            var tjBox = el('div', { style: 'background:rgba(0,229,255,0.06);border:1px solid rgba(0,229,255,0.15);border-radius:6px;padding:8px;text-align:center;' });
            tjBox.appendChild(el('div', { text: String(bm.total_jobs), style: 'font-size:1.2rem;font-weight:700;color:#00e5ff;font-family:Orbitron,sans-serif;' }));
            tjBox.appendChild(el('div', { text: 'Total Jobs', style: 'font-size:0.6rem;color:rgba(255,255,255,0.4);text-transform:uppercase;letter-spacing:0.05em;' }));
            bmGrid.appendChild(tjBox);

            // Success Rate
            var sr = bm.success_rate || 0;
            var srColor = sr >= 90 ? '#10b981' : sr >= 75 ? '#ffaa00' : '#ef4444';
            var srBox = el('div', { style: 'background:' + srColor + '0f;border:1px solid ' + srColor + '26;border-radius:6px;padding:8px;text-align:center;' });
            srBox.appendChild(el('div', { text: sr.toFixed(1) + '%', style: 'font-size:1.2rem;font-weight:700;color:' + srColor + ';font-family:Orbitron,sans-serif;' }));
            srBox.appendChild(el('div', { text: 'Success Rate', style: 'font-size:0.6rem;color:rgba(255,255,255,0.4);text-transform:uppercase;letter-spacing:0.05em;' }));
            bmGrid.appendChild(srBox);

            // Avg Duration
            var adBox = el('div', { style: 'background:rgba(139,92,246,0.06);border:1px solid rgba(139,92,246,0.15);border-radius:6px;padding:8px;text-align:center;' });
            var durText = bm.avg_duration_seconds < 60 ? bm.avg_duration_seconds.toFixed(1) + 's' : (bm.avg_duration_seconds / 60).toFixed(1) + 'm';
            adBox.appendChild(el('div', { text: durText, style: 'font-size:1.2rem;font-weight:700;color:#8b5cf6;font-family:Orbitron,sans-serif;' }));
            adBox.appendChild(el('div', { text: 'Avg Duration', style: 'font-size:0.6rem;color:rgba(255,255,255,0.4);text-transform:uppercase;letter-spacing:0.05em;' }));
            bmGrid.appendChild(adBox);

            bmCard.appendChild(bmGrid);
            editSection.appendChild(bmCard);
        } else if (!data.benchmark) {
            var nbCard = makeCard('Dispatch Benchmark', '#10b981');
            nbCard.appendChild(el('span', { text: 'No dispatch history', style: 'font-size:0.75rem;color:rgba(255,255,255,0.3);' }));
            editSection.appendChild(nbCard);
        }

        /* ── 7 + 8. Performance (24h) + Wellness — two columns ─── */
        var gridRow = el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;' });

        var p = data.performance_24h || {};
        var perfCard = makeCard('Performance (24h)', '#00ff41');
        perfCard.appendChild(makeRow('Tasks', String(p.tasks || 0), 'color:#00e5ff;'));
        perfCard.appendChild(makeRow('Completed', String(p.completed || 0), 'color:#00ff41;'));
        perfCard.appendChild(makeRow('Failed', String(p.failed || 0), 'color:#ff4444;'));
        perfCard.appendChild(makeRow('Avg Duration', fmtDur(p.avg_duration_ms)));
        gridRow.appendChild(perfCard);

        var em = data.emotional_state;
        var wellCard = makeCard('Wellness', '#8b5cf6');
        if (em) {
            var mc = stressColor(em.stress_level);
            wellCard.appendChild(makeRow('Mood', em.current_mood || 'neutral', 'text-transform:capitalize;'));
            wellCard.appendChild(makeRow('Stress', Math.round((em.stress_level || 0) * 100) + '%', 'color:' + mc + ';'));
            wellCard.appendChild(makeRow('Energy', Math.round((em.energy_level || 0) * 100) + '%'));
            wellCard.appendChild(makeRow('Intensity', Math.round((em.mood_intensity || 0) * 100) + '%'));
        } else {
            wellCard.appendChild(el('span', { text: 'No wellness data', style: 'font-size:0.75rem;color:rgba(255,255,255,0.3);' }));
        }
        gridRow.appendChild(wellCard);
        bodyEl.appendChild(gridRow);

        /* ── 9. Identity Traits ──────────────────────────────────── */
        if (data.identity && data.identity.length > 0) {
            var idCard = makeCard('Identity Traits', '#e879f9');
            data.identity.forEach(function (t) {
                idCard.appendChild(makeRow(t.identity_key, t.identity_value, 'text-transform:capitalize;'));
            });
            bodyEl.appendChild(idCard);
        }

        /* ── 10. Skills ──────────────────────────────────────────── */
        var skillCard = makeCard('Skills', '#ffaa00');
        var skillList = el('div', { style: 'display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px;' });
        skillList.id = 'profile-skills-list';
        if (data.skills && data.skills.length > 0) {
            data.skills.forEach(function (s) {
                var level = parseInt(s.proficiency_level) || 1;
                var dots = '';
                for (var i = 0; i < 5; i++) dots += i < level ? '\u25CF' : '\u25CB';

                var chip = el('span', { style: 'display:inline-flex;align-items:center;gap:4px;background:rgba(255,255,255,0.05);padding:2px 6px;border-radius:4px;font-size:0.7rem;color:rgba(255,255,255,0.7);' });
                chip.appendChild(document.createTextNode(s.skill_name + ' '));
                chip.appendChild(el('span', { text: dots, style: 'color:#ffaa00;font-size:0.6rem;' }));

                if (options.showSkillEdit && typeof window.removeSkill === 'function') {
                    var rmBtn = el('span', { text: '\u00D7', style: 'cursor:pointer;color:#ff4444;font-size:0.6rem;margin-left:2px;', title: 'Remove' });
                    rmBtn.dataset.agentId = parseInt(agentId);
                    rmBtn.dataset.skillId = String(s.id);
                    rmBtn.addEventListener('click', function () {
                        window.removeSkill(parseInt(this.dataset.agentId), this.dataset.skillId);
                    });
                    chip.appendChild(rmBtn);
                }
                skillList.appendChild(chip);
            });
        } else {
            skillList.appendChild(el('span', { text: 'No skills recorded', style: 'font-size:0.7rem;color:rgba(255,255,255,0.3);' }));
        }
        skillCard.appendChild(skillList);

        if (options.showSkillEdit && typeof window.addSkill === 'function') {
            var addRow = el('div', { style: 'display:flex;gap:4px;align-items:center;' });
            var nameInput = document.createElement('input');
            nameInput.type = 'text';
            nameInput.id = 'add-skill-name';
            nameInput.placeholder = 'Skill name';
            nameInput.style.cssText = 'flex:1;padding:2px 6px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:3px;color:inherit;font-size:0.65rem;';
            addRow.appendChild(nameInput);

            var levelSel = document.createElement('select');
            levelSel.id = 'add-skill-level';
            levelSel.style.cssText = 'padding:2px 4px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:3px;color:inherit;font-size:0.65rem;';
            [1, 2, 3, 4, 5].forEach(function (lv) {
                var opt = document.createElement('option');
                opt.value = String(lv);
                opt.textContent = String(lv);
                if (lv === 3) opt.selected = true;
                levelSel.appendChild(opt);
            });
            addRow.appendChild(levelSel);

            var addBtn = el('span', { text: 'Add', style: 'background:rgba(0,255,65,0.15);border:1px solid rgba(0,255,65,0.3);color:#00ff41;padding:2px 6px;border-radius:3px;font-size:0.6rem;cursor:pointer;' });
            addBtn.dataset.agentId = parseInt(agentId);
            addBtn.addEventListener('click', function () {
                window.addSkill(parseInt(this.dataset.agentId));
            });
            addRow.appendChild(addBtn);
            skillCard.appendChild(addRow);
        }
        bodyEl.appendChild(skillCard);

        /* ── 11. Voice DNA + Emotional History — side by side ───── */
        var hasVoice = data.voice;
        var hasEmHist = data.emotional_history && data.emotional_history.length > 0;
        if (hasVoice || hasEmHist) {
            var cols = (hasVoice && hasEmHist) ? '1fr 1fr' : '1fr';
            var voiceGrid = el('div', { style: 'display:grid;grid-template-columns:' + cols + ';gap:10px;margin-bottom:10px;' });

            if (hasVoice) {
                var v = data.voice;
                var vCard = makeCard('Voice DNA', '#06b6d4');
                if (v.engine) vCard.appendChild(makeRow('Engine', v.engine));
                if (v.language) vCard.appendChild(makeRow('Language', v.language));
                if (v.profile_name) vCard.appendChild(makeRow('Profile', v.profile_name));
                if (v.speaker) vCard.appendChild(makeRow('Speaker', v.speaker, 'font-size:0.65rem;color:rgba(255,255,255,0.4);'));
                voiceGrid.appendChild(vCard);
            }

            if (hasEmHist) {
                var emCard = makeCard('Emotional History', '#8b5cf6');
                var emScroll = el('div', { style: 'max-height:160px;overflow-y:auto;' });
                data.emotional_history.forEach(function (e) {
                    var sColor = stressColor(e.stress_level);
                    var emRow = el('div', { style: 'display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:0.72rem;' });
                    emRow.appendChild(el('span', { text: e.current_mood || 'neutral', style: 'text-transform:capitalize;color:rgba(255,255,255,0.6);' }));
                    emRow.appendChild(el('span', { text: 'stress ' + Math.round((e.stress_level || 0) * 100) + '%', style: 'color:' + sColor + ';font-size:0.65rem;' }));
                    if (e.timestamp && typeof ArchieTime !== 'undefined') {
                        emRow.appendChild(el('span', { text: ArchieTime.age(e.timestamp), style: 'color:rgba(255,255,255,0.25);font-size:0.65rem;' }));
                    }
                    emScroll.appendChild(emRow);
                });
                emCard.appendChild(emScroll);
                voiceGrid.appendChild(emCard);
            }

            bodyEl.appendChild(voiceGrid);
        }

        /* ── 12. Rest Cycles ─────────────────────────────────────── */
        if (data.rest_cycles && data.rest_cycles.length > 0) {
            var rcCard = makeCard('Rest Cycles', '#a78bfa');
            data.rest_cycles.forEach(function (rc) {
                var rcRow = el('div', { style: 'display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:0.72rem;' });
                rcRow.appendChild(el('span', { text: rc.rest_type || 'break', style: 'color:rgba(255,255,255,0.6);' }));
                rcRow.appendChild(el('span', { text: rc.reason || '', style: 'color:rgba(255,255,255,0.35);' }));
                var endedText = rc.ended_at
                    ? (typeof ArchieTime !== 'undefined' ? ArchieTime.age(rc.ended_at) : rc.ended_at)
                    : 'ongoing';
                var endedSpan = el('span', { text: endedText, style: 'color:' + (rc.ended_at ? 'rgba(255,255,255,0.25)' : '#ffaa00') + ';font-size:0.65rem;' });
                rcRow.appendChild(endedSpan);
                rcCard.appendChild(rcRow);
            });
            bodyEl.appendChild(rcCard);
        }

        /* ── 13. Rankings ────────────────────────────────────────── */
        if (data.rankings && data.rankings.length > 0) {
            var rkCard = makeCard('Performance Rankings', '#00d4ff');
            data.rankings.forEach(function (rk) {
                var rkRow = el('div', { cls: 'crew-profile-ranking' });
                rkRow.appendChild(el('span', { text: rk.capability || '' }));

                var rkVals = el('span', { style: 'display:flex;gap:8px;' });
                rkVals.appendChild(el('span', { cls: 'rank-pos', text: '#' + parseInt(rk.rank_position || 0) }));
                rkVals.appendChild(el('span', { text: rk.rank_score != null ? parseFloat(rk.rank_score).toFixed(2) : '--', style: 'color:#ffaa00;' }));
                rkVals.appendChild(el('span', { text: parseInt(rk.tasks_completed || 0) + ' tasks', style: 'color:rgba(255,255,255,0.4);' }));
                var sr = rk.success_rate != null ? Math.round(rk.success_rate * 100) : 0;
                var srColor = sr >= 90 ? '#00ff41' : sr >= 70 ? '#ffaa00' : '#ff4444';
                rkVals.appendChild(el('span', { text: sr + '%', style: 'color:' + srColor + ';' }));
                rkRow.appendChild(rkVals);
                rkCard.appendChild(rkRow);
            });
            bodyEl.appendChild(rkCard);
        }

        /* ── 14. Memories ────────────────────────────────────────── */
        if (data.memories && data.memories.length > 0) {
            var memCard = makeCard('Memory Highlights', '#e879f9');
            data.memories.forEach(function (m) {
                var memItem = el('div', { style: 'padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.05);font-size:0.7rem;' });
                var memTop = el('div', { style: 'display:flex;justify-content:space-between;' });
                memTop.appendChild(el('span', { text: m.memory_type || '', style: 'color:rgba(255,255,255,0.4);text-transform:capitalize;' }));
                memTop.appendChild(el('span', { text: m.importance_score ? parseFloat(m.importance_score).toFixed(2) : '--', style: 'color:#ffaa00;' }));
                memItem.appendChild(memTop);
                var preview = (m.content || '').substring(0, 120) + (m.content && m.content.length > 120 ? '...' : '');
                memItem.appendChild(el('div', { text: preview, style: 'color:rgba(255,255,255,0.35);font-size:0.65rem;margin-top:1px;' }));
                memCard.appendChild(memItem);
            });
            bodyEl.appendChild(memCard);
        }

        /* ── 15. Shift History ───────────────────────────────────── */
        if (data.shift_history && data.shift_history.length > 0) {
            var shCard = makeCard('Shift History', '#f59e0b');
            var shScroll = el('div', { style: 'max-height:180px;overflow-y:auto;' });
            data.shift_history.forEach(function (sh) {
                var stateColors = { active: '#00ff41', winding_down: '#ffaa00', cooldown: '#60a5fa', off_duty: '#888', barracked: '#666' };
                var sColor = stateColors[sh.shift_state] || '#888';

                var shRow = el('div', { cls: 'crew-profile-shift-row' });
                shRow.appendChild(el('span', { text: sh.shift_state || '', style: 'color:' + sColor + ';text-transform:uppercase;font-weight:600;min-width:80px;' }));
                shRow.appendChild(el('span', { text: sh.station_code || '\u2014', style: 'min-width:70px;' }));
                shRow.appendChild(el('span', { text: sh.reason || '', style: 'flex:1;color:rgba(255,255,255,0.4);' }));

                var taskText = sh.tasks_completed ? parseInt(sh.tasks_completed) + '/' + (parseInt(sh.tasks_completed) + parseInt(sh.tasks_failed || 0)) : '';
                shRow.appendChild(el('span', { text: taskText }));

                if (sh.replaced_by_name) {
                    shRow.appendChild(el('span', { text: '\u2192 ' + sh.replaced_by_name, style: 'color:#e879f9;margin-left:4px;', title: 'Replaced by' }));
                }

                var shTime = sh.started_at && typeof ArchieTime !== 'undefined' ? ArchieTime.age(sh.started_at) : '';
                shRow.appendChild(el('span', { text: shTime, style: 'min-width:60px;text-align:right;' }));
                shScroll.appendChild(shRow);
            });
            shCard.appendChild(shScroll);
            bodyEl.appendChild(shCard);
        }

        /* ── 16. Recent Tasks ────────────────────────────────────── */
        if (data.recent_tasks && data.recent_tasks.length > 0) {
            var taskCard = makeCard('Recent Tasks', '#00e5ff');
            data.recent_tasks.forEach(function (t) {
                var icon = t.success === true ? '\u25CF' : t.success === false ? '\u25CF' : '\u25CB';
                var color = t.success === true ? '#00ff41' : t.success === false ? '#ff4444' : 'rgba(255,255,255,0.4)';
                var tRow = el('div', { style: 'display:flex;justify-content:space-between;padding:2px 0;font-size:0.7rem;' });
                tRow.appendChild(el('span', { text: icon + ' ' + (t.module_source || '') + (t.capability ? ' / ' + t.capability : ''), style: 'color:' + color + ';' }));
                tRow.appendChild(el('span', { text: fmtDur(t.duration_ms), style: 'color:rgba(255,255,255,0.25);' }));
                taskCard.appendChild(tRow);
            });
            bodyEl.appendChild(taskCard);
        }

        /* ── 17. Welfare Gauges (stress + energy bars) ───────────── */
        if (em) {
            var stress = Math.round((em.stress_level || 0) * 100);
            var energy = Math.round((em.energy_level || 0) * 100);
            var stC = stressColor(em.stress_level);
            var enC = energyColor(em.energy_level);

            var gaugeCard = makeCard('Welfare Gauges', stC);

            // Stress bar
            var stressLabel = el('div', { style: 'display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:2px;' });
            stressLabel.appendChild(el('span', { text: 'Stress' }));
            stressLabel.appendChild(el('span', { text: stress + '%' }));
            gaugeCard.appendChild(stressLabel);
            var stressBar = el('div', { cls: 'crew-profile-welfare-bar' });
            stressBar.appendChild(el('div', { cls: 'crew-profile-welfare-fill', style: 'width:' + stress + '%;background:' + stC + ';' }));
            gaugeCard.appendChild(stressBar);

            // Energy bar
            var energyLabel = el('div', { style: 'display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:2px;margin-top:8px;' });
            energyLabel.appendChild(el('span', { text: 'Energy' }));
            energyLabel.appendChild(el('span', { text: energy + '%' }));
            gaugeCard.appendChild(energyLabel);
            var energyBar = el('div', { cls: 'crew-profile-welfare-bar' });
            energyBar.appendChild(el('div', { cls: 'crew-profile-welfare-fill', style: 'width:' + energy + '%;background:' + enC + ';' }));
            gaugeCard.appendChild(energyBar);

            bodyEl.appendChild(gaugeCard);
        }

        /* ── 18. C.R.E.E.D. Compliance — placeholder, filled async ─────── */
        var creedSection = el('div', {});
        creedSection.id = 'profile-creed-section';
        bodyEl.appendChild(creedSection);

        /* ── 19. Work History — placeholder, filled async ────────── */
        var whSection = el('div', {});
        whSection.id = 'profile-work-history-section';
        bodyEl.appendChild(whSection);

        /* ── Async: C.R.E.E.D. Welfare & Compliance ────────────────────── */
        fetch('/tools/department-hq/api/agents/workload')
            .then(function (r) { return r.json(); })
            .then(function (wData) {
                var section = document.getElementById('profile-creed-section');
                if (!section || !wData.success) return;
                var me = null;
                (wData.agents || []).forEach(function (w) { if (w.id === parseInt(agentId)) me = w; });
                if (!me) return;

                var riskColors = { healthy: '#00ff41', elevated: '#ffaa00', critical: '#ff6b6b', overloaded: '#ff0000' };
                var riskColor = riskColors[me.risk_level] || '#888';

                var creedCard = makeCard('C.R.E.E.D. Welfare & Compliance', riskColor);

                // Risk badge in header
                var creedHeader = creedCard.querySelector('.profile-card-header');
                var riskBadge = el('span', { text: me.risk_level || 'unknown', style: 'background:' + riskColor + '22;color:' + riskColor + ';padding:1px 6px;border-radius:3px;font-size:0.6rem;text-transform:uppercase;border:1px solid ' + riskColor + '44;margin-left:8px;' });
                creedHeader.appendChild(riskBadge);

                // Workload gauge
                var wPct = me.workload_pct || 0;
                var wColor = wPct < 60 ? '#00ff41' : wPct < 80 ? '#ffaa00' : '#ff4444';
                var wlBlock = el('div', { style: 'margin-bottom:8px;' });
                var wlLabel = el('div', { style: 'display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:2px;' });
                wlLabel.appendChild(el('span', { text: 'Workload (24h)' }));
                wlLabel.appendChild(el('span', { text: parseInt(me.tasks_24h) + ' / ' + parseInt(me.daily_cap) + ' tasks' }));
                wlBlock.appendChild(wlLabel);
                var wlBar = el('div', { cls: 'crew-profile-welfare-bar' });
                wlBar.appendChild(el('div', { cls: 'crew-profile-welfare-fill', style: 'width:' + Math.min(wPct, 100) + '%;background:' + wColor + ';' }));
                wlBlock.appendChild(wlBar);
                creedCard.appendChild(wlBlock);

                // Token gauge
                var tPct = me.token_usage_pct || 0;
                var tColor = tPct < 60 ? '#00ff41' : tPct < 80 ? '#ffaa00' : '#ff4444';
                var tkBlock = el('div', { style: 'margin-bottom:8px;' });
                var tkLabel = el('div', { style: 'display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:2px;' });
                tkLabel.appendChild(el('span', { text: 'Token Usage' }));
                tkLabel.appendChild(el('span', { text: parseInt(me.tokens_used_24h).toLocaleString() + ' / ' + parseInt(me.token_cap).toLocaleString() }));
                tkBlock.appendChild(tkLabel);
                var tkBar = el('div', { cls: 'crew-profile-welfare-bar' });
                tkBar.appendChild(el('div', { cls: 'crew-profile-welfare-fill', style: 'width:' + Math.min(tPct, 100) + '%;background:' + tColor + ';' }));
                tkBlock.appendChild(tkBar);
                creedCard.appendChild(tkBlock);

                // Stats row
                var statsRow = el('div', { style: 'display:flex;gap:12px;font-size:0.7rem;margin-bottom:8px;' });
                var compSpan = el('span', {});
                compSpan.appendChild(document.createTextNode('Completed: '));
                compSpan.appendChild(el('span', { text: String(parseInt(me.completed_24h)), style: 'color:#00ff41;' }));
                statsRow.appendChild(compSpan);
                var failSpan = el('span', {});
                failSpan.appendChild(document.createTextNode('Failed: '));
                failSpan.appendChild(el('span', { text: String(parseInt(me.failed_24h)), style: 'color:#ff4444;' }));
                statsRow.appendChild(failSpan);
                var avgSpan = el('span', {});
                avgSpan.appendChild(document.createTextNode('Avg: '));
                avgSpan.appendChild(el('span', { text: fmtDur(me.avg_duration_ms), style: 'color:#00e5ff;' }));
                statsRow.appendChild(avgSpan);
                creedCard.appendChild(statsRow);

                // Send to rest if at risk
                if (wPct >= 80 || (em && (em.stress_level || 0) > 0.7)) {
                    if (typeof window.sendToLoungeById === 'function' && options.onClose) {
                        var restBtn = el('span', { text: 'Send to Rest (Recommended)', style: 'display:block;text-align:center;background:rgba(255,107,107,0.15);border:1px solid rgba(255,107,107,0.3);color:#ff6b6b;padding:4px 10px;border-radius:4px;font-size:0.7rem;cursor:pointer;width:100%;box-sizing:border-box;' });
                        restBtn.dataset.agentId = parseInt(agentId);
                        restBtn.addEventListener('click', function () {
                            window.sendToLoungeById(parseInt(this.dataset.agentId));
                            if (typeof options.onClose === 'function') options.onClose();
                            else if (typeof window[options.onClose] === 'function') window[options.onClose]();
                        });
                        creedCard.appendChild(restBtn);
                    }
                }

                section.appendChild(creedCard);
            }).catch(function () { /* silently skip */ });

        /* ── Async: Work History ──────────────────────────────────── */
        fetch('/tools/department-hq/api/agents/' + parseInt(agentId) + '/work-history')
            .then(function (r) { return r.json(); })
            .then(function (whData) {
                var section = document.getElementById('profile-work-history-section');
                if (!section || !whData.success) return;
                var proposals = whData.proposals || [];
                if (proposals.length === 0) return;

                var whCard = makeCard('Work History \u2014 Proposals', '#60a5fa');

                var shown = proposals.slice(0, 5);
                shown.forEach(function (pr) {
                    var prRow = el('div', { style: 'display:flex;align-items:center;gap:6px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.05);font-size:0.7rem;' });

                    var statusText = (pr.status || 'unknown').toLowerCase();
                    var statusColor = statusText === 'deployed' ? '#6ee7b7' : statusText === 'approved' ? '#93c5fd' : 'rgba(255,255,255,0.3)';
                    prRow.appendChild(el('span', { style: 'display:inline-block;width:8px;height:8px;border-radius:50%;background:' + statusColor + ';flex-shrink:0;', title: statusText }));

                    prRow.appendChild(el('span', { text: pr.title || 'Untitled', style: 'flex:1;color:rgba(255,255,255,0.5);' }));
                    prRow.appendChild(el('span', { text: statusText, style: 'color:' + statusColor + ';font-size:0.65rem;text-transform:capitalize;' }));
                    whCard.appendChild(prRow);
                });

                var deployed = proposals.filter(function (pr) { return (pr.status || '').toLowerCase() === 'deployed'; }).length;
                whCard.appendChild(el('div', { text: deployed + '/' + proposals.length + ' proposals deployed', style: 'margin-top:6px;font-size:0.65rem;color:rgba(255,255,255,0.4);' }));

                section.appendChild(whCard);
            }).catch(function () { /* silently skip */ });
    }

    /* ── Export ──────────────────────────────────────────────────── */
    window.renderAgentProfile = renderAgentProfile;
})();
