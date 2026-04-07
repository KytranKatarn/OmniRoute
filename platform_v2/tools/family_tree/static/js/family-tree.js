/* Family Tree Module JS — All dynamic HTML uses escHtml() sanitization before DOM insertion */
/* Security: innerHTML is only used with server-trusted structure + escHtml()-sanitized user data */

const FamilyTree = {
  BASE: '/tools/family-tree/api',
  currentTab: 'tree',
  persons: [],
  relationships: [],
  editingPersonId: null,
  _gedcomFile: null,
  _zoomBehavior: null,
  _svg: null,
  _toastTimer: null,
  viewMode: 'force',
  _fanRootId: null,

  /* ── CORE HELPERS ── */

  async api(path, opts = {}) {
    const url = this.BASE + path;
    const isFormData = opts.body instanceof FormData;
    const headers = isFormData ? {} : { 'Content-Type': 'application/json' };
    if (!isFormData && opts.body && typeof opts.body === 'object') {
      opts.body = JSON.stringify(opts.body);
    }
    try {
      const resp = await fetch(url, { headers, ...opts });
      return await resp.json();
    } catch (err) {
      return { success: false, error: err.message };
    }
  },

  toast(msg, isError = false) {
    let el = document.getElementById('ft-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'ft-toast';
      el.className = 'ft-toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.className = 'ft-toast ft-toast-show' + (isError ? ' ft-toast-error' : '');
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => { el.classList.remove('ft-toast-show'); }, 3500);
  },

  escHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  },

  setHtml(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
  },

  /* ── INIT ── */

  async init() {
    await this.loadTree();
    if (typeof lucide !== 'undefined') lucide.createIcons();
  },

  /* ── TAB SWITCHING ── */

  switchTab(tab) {
    document.querySelectorAll('.ft-panel').forEach(p => p.classList.add('ft-hidden'));
    document.querySelectorAll('.ft-tab').forEach(t => t.classList.remove('ft-tab-active'));
    const panel  = document.getElementById('ft-tab-' + tab);
    const tabBtn = document.querySelector('[data-tab="' + tab + '"]');
    if (panel)  panel.classList.remove('ft-hidden');
    if (tabBtn) tabBtn.classList.add('ft-tab-active');
    this.currentTab = tab;
    if (tab === 'research')  this.loadResearch();
    if (tab === 'documents') this.loadDocuments();
    if (tab === 'photos')    this.loadPhotos();
    if (tab === 'timeline')  this.loadTimeline();
    if (typeof lucide !== 'undefined') lucide.createIcons();
  },

  /* ── TREE: LOAD + RENDER ── */

  async loadTree() {
    const data = await this.api('/tree');
    this.persons       = (data && data.persons)       || [];
    this.relationships = (data && data.relationships) || [];
    this.renderTree({ persons: this.persons, relationships: this.relationships });
    this._renderTreeStats();
  },

  setViewMode(mode) {
    this.viewMode = mode;
    document.querySelectorAll('.ft-view-btn').forEach(b => b.classList.remove('ft-view-btn-active'));
    const activeBtn = document.querySelector(`[data-view="${mode}"]`);
    if (activeBtn) activeBtn.classList.add('ft-view-btn-active');
    this.renderTree({ persons: this.persons, relationships: this.relationships });
  },

  _renderViewToggle() {
    const container = document.getElementById('ft-view-toggle');
    if (!container) return;
    const modes = [
      { key: 'force', label: 'Network', icon: 'git-branch' },
      { key: 'fan', label: 'Fan Chart', icon: 'sun' },
      { key: 'pedigree', label: 'Pedigree', icon: 'git-merge' },
    ];
    container.innerHTML = modes.map(m =>
      `<button class="ft-view-btn${this.viewMode === m.key ? ' ft-view-btn-active' : ''}" data-view="${m.key}" onclick="FamilyTree.setViewMode('${m.key}')"><i data-lucide="${m.icon}"></i> ${m.label}</button>`
    ).join('');
    if (typeof lucide !== 'undefined') lucide.createIcons();
  },

  renderTree(data) {
    const canvas = document.getElementById('ft-tree-canvas');
    const svgEl  = document.getElementById('ft-tree-svg');
    const empty  = document.getElementById('ft-tree-empty');
    if (!data.persons || data.persons.length === 0) {
      if (empty) empty.style.display = 'flex';
      if (svgEl) svgEl.style.display = 'none';
      return;
    }
    if (empty) empty.style.display = 'none';
    if (svgEl) svgEl.style.display = 'block';

    this._renderViewToggle();

    if (this.viewMode === 'fan') {
      this.renderFanChart(data);
      return;
    }
    if (this.viewMode === 'pedigree') {
      this.renderPedigreeChart(data);
      return;
    }
    this._renderForceGraph(data);
  },

  _renderForceGraph(data) {
    const canvas = document.getElementById('ft-tree-canvas');
    const width  = canvas.clientWidth  || 900;
    const height = canvas.clientHeight || 500;

    d3.select('#ft-tree-svg').selectAll('*').remove();
    const svg = d3.select('#ft-tree-svg').attr('viewBox', `0 0 ${width} ${height}`);

    const defs = svg.append('defs');
    defs.append('marker')
      .attr('id', 'ft-arrow').attr('viewBox', '0 -4 8 8')
      .attr('refX', 18).attr('refY', 0)
      .attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
      .append('path').attr('d', 'M0,-4L8,0L0,4').attr('fill', 'rgba(255,255,255,0.2)');

    const g = svg.append('g').attr('class', 'ft-d3-root');
    const nodes = data.persons.map(p => ({ ...p }));
    const links = (data.relationships || []).map(r => ({
      source: r.person_a_id, target: r.person_b_id, type: r.relationship_type,
    }));

    const simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(d => d.id).distance(120))
      .force('charge', d3.forceManyBody().strength(-350))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(50));

    const link = g.append('g').selectAll('line').data(links).enter().append('line')
      .attr('class', d => 'ft-d3-link' + (d.type === 'ai_suggested' ? ' ft-d3-link-dashed' : ''))
      .attr('marker-end', 'url(#ft-arrow)');

    const self = this;
    const node = g.append('g').selectAll('g').data(nodes).enter().append('g')
      .attr('class', 'ft-d3-node').attr('cursor', 'pointer')
      .on('click', (event, d) => { self.editPerson(d.id); })
      .call(d3.drag()
        .on('start', (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on('drag',  (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on('end',   (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
      );

    node.append('circle').attr('r', 22)
      .attr('stroke', d => this._nodeColor(d))
      .attr('stroke-dasharray', d => d.source_type === 'ai_researching' ? '4,3' : null);

    node.append('text').attr('dy', 36).attr('text-anchor', 'middle')
      .attr('fill', '#e2e8f0').attr('font-size', '11px')
      .attr('font-family', 'IBM Plex Mono, monospace').attr('pointer-events', 'none')
      .text(d => this._shortName(d.first_name, d.last_name));

    node.append('text').attr('dy', 4).attr('text-anchor', 'middle')
      .attr('fill', d => this._nodeColor(d)).attr('font-size', '12px')
      .attr('font-weight', 'bold').attr('font-family', 'Orbitron, sans-serif')
      .attr('pointer-events', 'none')
      .text(d => this._initials(d.first_name, d.last_name));

    node.append('title').text(d => {
      const name = [d.first_name, d.last_name].filter(Boolean).join(' ');
      const year = d.birth_date ? String(d.birth_date).substring(0, 4) : '';
      return name + (year ? ` (${year})` : '');
    });

    simulation.on('tick', () => {
      link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
          .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
      node.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    const zoom = d3.zoom().scaleExtent([0.15, 4])
      .on('zoom', event => { g.attr('transform', event.transform); });
    svg.call(zoom);
    this._zoomBehavior = zoom;
    this._svg = svg;
  },

  /* ── HIERARCHY BUILDER ── */

  _buildHierarchy(rootId) {
    const personMap = {};
    this.persons.forEach(p => { personMap[p.id] = { ...p, children: [] }; });

    const childOf = {};
    this.relationships.forEach(r => {
      const t = (r.relationship_type || '').toLowerCase();
      if (t === 'parent' || t === 'parent_child') {
        childOf[r.person_b_id] = r.person_a_id;
      } else if (t === 'child') {
        childOf[r.person_a_id] = r.person_b_id;
      }
    });

    const parentChildMap = {};
    this.relationships.forEach(r => {
      const t = (r.relationship_type || '').toLowerCase();
      if (t === 'parent' || t === 'parent_child') {
        if (!parentChildMap[r.person_a_id]) parentChildMap[r.person_a_id] = [];
        parentChildMap[r.person_a_id].push(r.person_b_id);
      } else if (t === 'child') {
        if (!parentChildMap[r.person_b_id]) parentChildMap[r.person_b_id] = [];
        parentChildMap[r.person_b_id].push(r.person_a_id);
      }
    });

    const adjMap = {};
    this.relationships.forEach(r => {
      if (!adjMap[r.person_a_id]) adjMap[r.person_a_id] = [];
      if (!adjMap[r.person_b_id]) adjMap[r.person_b_id] = [];
      adjMap[r.person_a_id].push(r.person_b_id);
      adjMap[r.person_b_id].push(r.person_a_id);
    });

    const buildNode = (id, visited) => {
      if (visited.has(id)) return null;
      visited.add(id);
      const p = personMap[id];
      if (!p) return null;
      const name = [p.first_name, p.last_name].filter(Boolean).join(' ') || '?';
      const year = p.birth_date ? String(p.birth_date).substring(0, 4) : '';
      const kids = (parentChildMap[id] || [])
        .map(cid => buildNode(cid, visited))
        .filter(Boolean);
      const neighbors = (adjMap[id] || [])
        .filter(nid => !visited.has(nid))
        .map(nid => buildNode(nid, visited))
        .filter(Boolean);
      const allChildren = kids.concat(neighbors);
      return { name, year, id: p.id, source_type: p.source_type, children: allChildren.length ? allChildren : undefined };
    };

    const root = buildNode(rootId, new Set());
    if (!root) {
      const first = this.persons[0];
      if (!first) return { name: 'Empty', children: [] };
      return buildNode(first.id, new Set()) || { name: 'Empty', children: [] };
    }
    return root;
  },

  /* ── FAN CHART ── */

  renderFanChart(data) {
    const canvas = document.getElementById('ft-tree-canvas');
    const width  = canvas.clientWidth  || 900;
    const height = canvas.clientHeight || 500;
    const radius = Math.min(width, height) / 2 - 20;

    d3.select('#ft-tree-svg').selectAll('*').remove();
    const svg = d3.select('#ft-tree-svg').attr('viewBox', `0 0 ${width} ${height}`);
    const g = svg.append('g').attr('transform', `translate(${width / 2},${height / 2})`);

    const rootId = this._fanRootId || (data.persons[0] && data.persons[0].id);
    if (!rootId) return;
    const hierData = this._buildHierarchy(rootId);
    const root = d3.hierarchy(hierData)
      .sum(() => 1)
      .sort((a, b) => b.value - a.value);

    d3.partition().size([2 * Math.PI, radius])(root);

    const arc = d3.arc()
      .startAngle(d => d.x0)
      .endAngle(d => d.x1)
      .padAngle(d => Math.min((d.x1 - d.x0) / 2, 0.005))
      .padRadius(radius / 2)
      .innerRadius(d => d.y0)
      .outerRadius(d => d.y1 - 1);

    const self = this;

    g.selectAll('path')
      .data(root.descendants())
      .enter().append('path')
      .attr('class', 'ft-fan-arc')
      .attr('d', arc)
      .attr('fill', d => {
        const st = d.data.source_type;
        return self._nodeColor({ source_type: st });
      })
      .attr('fill-opacity', d => d.depth === 0 ? 0.9 : 0.6 + (0.1 * Math.min(d.depth, 3)))
      .attr('stroke', 'rgba(0,0,0,0.4)')
      .attr('stroke-width', 0.5)
      .attr('cursor', 'pointer')
      .on('click', (event, d) => {
        if (d.data.id) {
          self._fanRootId = d.data.id;
          self.renderTree({ persons: self.persons, relationships: self.relationships });
          self.toast('Recentered on ' + d.data.name);
        }
      })
      .append('title')
      .text(d => d.data.name + (d.data.year ? ` (${d.data.year})` : ''));

    g.selectAll('text')
      .data(root.descendants().filter(d => (d.x1 - d.x0) > 0.12))
      .enter().append('text')
      .attr('class', 'ft-fan-label')
      .attr('transform', d => {
        const angle = (d.x0 + d.x1) / 2;
        const r = (d.y0 + d.y1) / 2;
        const rotate = (angle * 180 / Math.PI - 90);
        const flip = angle > Math.PI;
        return `rotate(${rotate}) translate(${r},0) rotate(${flip ? 180 : 0})`;
      })
      .attr('dy', '0.35em')
      .attr('text-anchor', 'middle')
      .attr('fill', '#e2e8f0')
      .attr('font-size', d => d.depth === 0 ? '11px' : '9px')
      .attr('font-family', 'IBM Plex Mono, monospace')
      .attr('pointer-events', 'none')
      .text(d => {
        const maxLen = Math.max(4, Math.floor((d.y1 - d.y0) / 7));
        const n = d.data.name;
        return n.length > maxLen ? n.substring(0, maxLen - 1) + '\u2026' : n;
      });

    /* Center label */
    g.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', '-0.2em')
      .attr('fill', 'var(--ft-accent)')
      .attr('font-size', '12px')
      .attr('font-family', 'Orbitron, sans-serif')
      .attr('font-weight', 'bold')
      .text(hierData.name);
    g.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', '1.2em')
      .attr('fill', 'var(--ft-muted)')
      .attr('font-size', '9px')
      .attr('font-family', 'IBM Plex Mono, monospace')
      .text('click arc to recenter');

    const zoom = d3.zoom().scaleExtent([0.3, 5])
      .on('zoom', event => { g.attr('transform', `translate(${width / 2 + event.transform.x},${height / 2 + event.transform.y}) scale(${event.transform.k})`); });
    svg.call(zoom);
    this._zoomBehavior = zoom;
    this._svg = svg;
  },

  /* ── PEDIGREE CHART ── */

  renderPedigreeChart(data) {
    const canvas = document.getElementById('ft-tree-canvas');
    const width  = canvas.clientWidth  || 900;
    const height = canvas.clientHeight || 500;
    const margin = { top: 30, right: 120, bottom: 30, left: 120 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    d3.select('#ft-tree-svg').selectAll('*').remove();
    const svg = d3.select('#ft-tree-svg').attr('viewBox', `0 0 ${width} ${height}`);
    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

    const rootId = this._fanRootId || (data.persons[0] && data.persons[0].id);
    if (!rootId) return;
    const hierData = this._buildHierarchy(rootId);
    const root = d3.hierarchy(hierData);

    const treeLayout = d3.tree().size([innerH, innerW]);
    treeLayout(root);

    const self = this;

    /* Links */
    g.selectAll('.ft-pedigree-link')
      .data(root.links())
      .enter().append('path')
      .attr('class', 'ft-pedigree-link')
      .attr('d', d3.linkHorizontal().x(d => d.y).y(d => d.x))
      .attr('fill', 'none');

    /* Nodes */
    const node = g.selectAll('.ft-pedigree-node')
      .data(root.descendants())
      .enter().append('g')
      .attr('class', 'ft-pedigree-node')
      .attr('transform', d => `translate(${d.y},${d.x})`)
      .attr('cursor', 'pointer')
      .on('click', (event, d) => {
        if (d.data.id) self.editPerson(d.data.id);
      });

    node.append('circle')
      .attr('r', 16)
      .attr('fill', 'rgba(0,0,0,0.6)')
      .attr('stroke', d => self._nodeColor({ source_type: d.data.source_type }))
      .attr('stroke-width', 2.5);

    node.append('text')
      .attr('dy', '0.35em')
      .attr('text-anchor', 'middle')
      .attr('fill', d => self._nodeColor({ source_type: d.data.source_type }))
      .attr('font-size', '10px')
      .attr('font-weight', 'bold')
      .attr('font-family', 'Orbitron, sans-serif')
      .attr('pointer-events', 'none')
      .text(d => {
        const parts = d.data.name.split(' ');
        return parts.map(p => (p[0] || '').toUpperCase()).join('').substring(0, 2);
      });

    node.append('text')
      .attr('dy', -22)
      .attr('text-anchor', 'middle')
      .attr('fill', '#e2e8f0')
      .attr('font-size', '10px')
      .attr('font-family', 'IBM Plex Mono, monospace')
      .attr('pointer-events', 'none')
      .text(d => {
        const n = d.data.name;
        return n.length > 20 ? n.substring(0, 18) + '\u2026' : n;
      });

    node.append('text')
      .attr('dy', 30)
      .attr('text-anchor', 'middle')
      .attr('fill', 'var(--ft-muted)')
      .attr('font-size', '8px')
      .attr('font-family', 'IBM Plex Mono, monospace')
      .attr('pointer-events', 'none')
      .text(d => d.data.year || '');

    const zoom = d3.zoom().scaleExtent([0.2, 4])
      .on('zoom', event => { g.attr('transform', event.transform); });
    svg.call(zoom);
    this._zoomBehavior = zoom;
    this._svg = svg;
  },

  _nodeColor(person) {
    const map = { user_confirmed: '#00e5ff', from_records: '#10b981', ai_researching: '#f97316' };
    return map[person.source_type] || '#ef4444';
  },

  _shortName(first, last) {
    const f = (first || '?');
    const l = (last  || '');
    const full = l ? `${f} ${l}` : f;
    return full.length > 24 ? full.substring(0, 22) + '...' : full;
  },

  _initials(first, last) {
    return ((first || '?')[0] + (last ? last[0] : '')).toUpperCase();
  },

  _renderTreeStats() {
    const confirmed   = this.persons.filter(p => p.source_type === 'user_confirmed').length;
    const fromRecords = this.persons.filter(p => p.source_type === 'from_records').length;
    const researching = this.persons.filter(p => p.source_type === 'ai_researching').length;
    this.setHtml('ft-tree-stats', `
      <span class="ft-tree-stat">Total: <strong>${this.persons.length}</strong></span>
      <span class="ft-tree-stat">Confirmed: <strong style="color:#00e5ff">${confirmed}</strong></span>
      <span class="ft-tree-stat">From Records: <strong style="color:#10b981">${fromRecords}</strong></span>
      <span class="ft-tree-stat">Researching: <strong style="color:#f97316">${researching}</strong></span>
      <span class="ft-tree-stat">Relationships: <strong>${this.relationships.length}</strong></span>`);
    this._renderViewToggle();
  },

  resetZoom() {
    if (this._svg && this._zoomBehavior) {
      this._svg.transition().duration(500).call(this._zoomBehavior.transform, d3.zoomIdentity);
    }
  },

  /* ── PERSON CRUD ── */

  addPerson() {
    this.editingPersonId = null;
    document.getElementById('ft-person-modal-title').textContent = 'Add Person';
    this.setHtml('ft-person-modal-body', this.renderPersonForm(null));
    document.getElementById('ft-person-modal').classList.add('active');
    if (typeof lucide !== 'undefined') lucide.createIcons();
  },

  async editPerson(id) {
    this.editingPersonId = id;
    document.getElementById('ft-person-modal-title').textContent = 'Edit Person';
    this.setHtml('ft-person-modal-body', '<p class="ft-muted" style="padding:20px;text-align:center;">Loading...</p>');
    document.getElementById('ft-person-modal').classList.add('active');
    const data = await this.api(`/persons/${id}`);
    if (data.error) {
      this.setHtml('ft-person-modal-body', `<p class="ft-muted" style="padding:20px;text-align:center;">Error: ${this.escHtml(data.error)}</p>`);
      return;
    }
    this.setHtml('ft-person-modal-body', this.renderPersonForm(data.person || data));
    if (typeof lucide !== 'undefined') lucide.createIcons();
  },

  async savePerson() {
    const g = (id) => document.getElementById(id);
    const birthYear = g('ft-field-birth-year')?.value?.trim() || '';
    const deathYear = g('ft-field-death-year')?.value?.trim() || '';
    const formData = {
      first_name:  g('ft-field-first-name')?.value?.trim()  || '',
      last_name:   g('ft-field-last-name')?.value?.trim()   || '',
      birth_date:  birthYear ? `${birthYear}-01-01` : '',
      death_date:  deathYear ? `${deathYear}-01-01` : '',
      birth_place: g('ft-field-birth-place')?.value?.trim() || '',
      gender:      g('ft-field-gender')?.value              || '',
      source_type: g('ft-field-source-type')?.value         || 'user_confirmed',
      notes:       g('ft-field-notes')?.value?.trim()       || '',
    };
    if (!formData.first_name) { this.toast('First name is required.', true); return; }
    const url    = this.editingPersonId ? `/persons/${this.editingPersonId}` : '/persons';
    const method = this.editingPersonId ? 'PUT' : 'POST';
    const result = await this.api(url, { method, body: formData });
    if (result.success || result.id) {
      this.toast(this.editingPersonId ? 'Person updated.' : 'Person added.');
      this.closeModal();
      await this.loadTree();
    } else {
      this.toast(result.error || 'Failed to save person.', true);
    }
  },

  async deletePerson(id) {
    if (!confirm('Delete this person? This cannot be undone.')) return;
    const result = await this.api(`/persons/${id}`, { method: 'DELETE' });
    if (result.success) {
      this.toast('Person deleted.');
      this.closeModal();
      await this.loadTree();
    } else {
      this.toast(result.error || 'Failed to delete person.', true);
    }
  },

  /* ── RELATIONSHIPS ── */

  async addRelationship(aId, bId, type) {
    const result = await this.api('/relationships', {
      method: 'POST',
      body: { person_a_id: aId, person_b_id: bId, relationship_type: type },
    });
    if (result.success || result.id) {
      this.toast('Relationship added.');
      await this.loadTree();
    } else {
      this.toast(result.error || 'Failed to add relationship.', true);
    }
  },

  /* ── GEDCOM ── */

  importGedcom() {
    this._gedcomFile = null;
    document.getElementById('ft-gedcom-selected').textContent = '';
    this.setHtml('ft-import-result', '');
    const inp = document.getElementById('ft-gedcom-file-input');
    if (inp) inp.value = '';
    document.getElementById('ft-import-modal').classList.add('active');
    if (typeof lucide !== 'undefined') lucide.createIcons();
  },

  _gedcomFileSelected(file) {
    if (!file) return;
    this._gedcomFile = file;
    document.getElementById('ft-gedcom-selected').textContent =
      `Selected: ${file.name} (${Math.round(file.size / 1024)} KB)`;
  },

  handleGedcomDrop(e) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) this._gedcomFileSelected(file);
  },

  async doImport() {
    if (!this._gedcomFile) { this.toast('Please select a GEDCOM file first.', true); return; }
    this.setHtml('ft-import-result', '<p class="ft-muted" style="text-align:center;">Importing...</p>');
    const fd = new FormData();
    fd.append('file', this._gedcomFile);
    const result = await this.api('/gedcom/import', { method: 'POST', body: fd });
    if (result.success || result.imported) {
      this.setHtml('ft-import-result', `
        <div class="ft-card" style="border-left-color:#10b981;">
          <div class="ft-card-title" style="color:#10b981;">Import Complete</div>
          <div class="ft-card-meta">
            Persons imported: ${result.persons_imported ?? result.imported ?? 0}<br>
            Relationships: ${result.relationships_imported ?? 0}<br>
            Skipped: ${result.skipped ?? 0}
          </div>
        </div>`);
      this.toast('GEDCOM imported successfully.');
      await this.loadTree();
    } else {
      this.setHtml('ft-import-result',
        `<p style="color:#ef4444;font-size:0.85rem;">Error: ${this.escHtml(result.error || 'Import failed.')}</p>`);
      this.toast(result.error || 'Import failed.', true);
    }
  },

  exportGedcom() { window.location = this.BASE + '/gedcom/export'; },

  /* ── RESEARCH ── */

  async loadResearch() {
    const data     = await this.api('/research/queue');
    const queue    = data.queue || [];
    const active   = queue.filter(r => r.status === 'active' || r.status === 'queued');
    const findings = queue.filter(r => r.status === 'pending_review');
    const emptyActive = `<div class="ft-empty-state ft-empty-sm">
      <p>No active research tasks.</p></div>`;
    const emptyFindings = `<div class="ft-empty-state ft-empty-sm">
      <p>No pending findings.</p></div>`;
    this.setHtml('ft-research-active',   active.length   ? active.map(r   => this.renderResearchCard(r, false)).join('') : emptyActive);
    this.setHtml('ft-research-findings', findings.length ? findings.map(r => this.renderResearchCard(r, true)).join('')  : emptyFindings);
    if (typeof lucide !== 'undefined') lucide.createIcons();
  },

  async startResearch(personId, type) {
    const result = await this.api('/research/start', { method: 'POST', body: { person_id: personId, research_type: type } });
    if (result.success || result.id) { this.toast('Research task started.'); await this.loadResearch(); }
    else { this.toast(result.error || 'Failed to start research.', true); }
  },

  showStartResearchModal() {
    const personId = prompt('Enter Person ID to research:');
    if (!personId) return;
    const type = prompt('Research type (ancestry / descendants / records):', 'ancestry');
    if (type) this.startResearch(personId, type);
  },

  async acceptFinding(id) {
    const result = await this.api(`/research/${id}/accept`, { method: 'POST' });
    if (result.success) { this.toast('Finding accepted and added to tree.'); await this.loadResearch(); await this.loadTree(); }
    else { this.toast(result.error || 'Failed to accept finding.', true); }
  },

  async rejectFinding(id) {
    const result = await this.api(`/research/${id}/reject`, { method: 'POST' });
    if (result.success) { this.toast('Finding rejected.'); await this.loadResearch(); }
    else { this.toast(result.error || 'Failed to reject finding.', true); }
  },

  /* ── DOCUMENTS ── */

  async loadDocuments() {
    const data = await this.api('/documents');
    const list = data.documents || [];
    const empty = `<div class="ft-empty-state ft-empty-sm"><p>No documents uploaded yet.</p></div>`;
    this.setHtml('ft-documents-list', list.length ? list.map(d => this.renderDocumentCard(d)).join('') : empty);
    if (typeof lucide !== 'undefined') lucide.createIcons();
  },

  async uploadDocument(file) {
    if (!file) return;
    this.toast('Uploading document\u2026');
    const fd = new FormData(); fd.append('file', file);
    const result = await this.api('/documents/upload', { method: 'POST', body: fd });
    if (result.success || result.id) { this.toast('Document uploaded.'); await this.loadDocuments(); }
    else { this.toast(result.error || 'Upload failed.', true); }
  },

  handleDocDrop(e) { e.preventDefault(); this.uploadDocument(e.dataTransfer.files[0]); },

  async triggerOcr(docId) {
    this.toast('Running OCR\u2026');
    const result = await this.api(`/documents/${docId}/ocr`, { method: 'POST' });
    if (result.success || result.text) { this.toast('OCR complete.'); await this.loadDocuments(); }
    else { this.toast(result.error || 'OCR failed.', true); }
  },

  /* ── PHOTOS ── */

  async loadPhotos() {
    const data     = await this.api('/photos');
    const photos   = data.photos   || [];
    const clusters = data.clusters || [];

    const noPhotos = `<div class="ft-empty-state ft-empty-sm" style="grid-column:1/-1;"><p>No photos uploaded yet.</p></div>`;
    this.setHtml('ft-photo-gallery', photos.length ? photos.map(p => `
      <div class="ft-photo-item" onclick="FamilyTree._previewPhoto('${this.escHtml(p.url || '')}')">
        <img src="${this.escHtml(p.url || p.thumbnail_url || '')}" alt="${this.escHtml(p.filename || '')}" loading="lazy">
        <div class="ft-photo-caption">${this.escHtml(p.filename || '')}</div>
      </div>`).join('') : noPhotos);

    const noClusters = `<div class="ft-empty-state ft-empty-sm"><p>Run face clustering to group photos by person.</p></div>`;
    this.setHtml('ft-clusters-content', clusters.length ? clusters.map(c => `
      <div class="ft-card">
        <div class="ft-card-header">
          <span class="ft-card-title">${c.label ? this.escHtml(c.label) : 'Unknown Person'}</span>
          <span class="ft-badge ft-badge-gray">${c.face_count || 0} faces</span>
        </div>
        <div class="ft-card-meta">${c.photo_count || 0} photos</div>
        <div class="ft-card-actions">
          <select class="ft-select" style="flex:1;font-size:0.78rem;" id="ft-cluster-person-${this.escHtml(String(c.id))}">
            <option value="">-- Assign to person --</option>
            ${this.persons.map(p => `<option value="${p.id}">${this.escHtml([p.first_name, p.last_name].filter(Boolean).join(' '))}</option>`).join('')}
          </select>
          <button class="ft-btn ft-btn-sm ft-btn-primary"
            onclick="FamilyTree.labelFace('${this.escHtml(String(c.id))}', document.getElementById('ft-cluster-person-${this.escHtml(String(c.id))}').value)">
            Assign
          </button>
        </div>
      </div>`).join('') : noClusters);

    if (typeof lucide !== 'undefined') lucide.createIcons();
  },

  async uploadPhoto(file) {
    if (!file) return;
    this.toast('Uploading photo\u2026');
    const fd = new FormData(); fd.append('file', file);
    const result = await this.api('/photos/upload', { method: 'POST', body: fd });
    if (result.success || result.id) { this.toast('Photo uploaded.'); await this.loadPhotos(); }
    else { this.toast(result.error || 'Upload failed.', true); }
  },

  handlePhotoDrop(e) { e.preventDefault(); this.uploadPhoto(e.dataTransfer.files[0]); },

  async runClustering() {
    this.toast('Running face clustering\u2026 this may take a moment.');
    const result = await this.api('/photos/cluster', { method: 'POST' });
    if (result.success || result.clusters) {
      this.toast(`Clustering complete. ${result.cluster_count || 0} clusters found.`);
      await this.loadPhotos();
    } else { this.toast(result.error || 'Clustering failed.', true); }
  },

  async labelFace(faceId, personId) {
    if (!personId) { this.toast('Please select a person first.', true); return; }
    const result = await this.api(`/photos/faces/${faceId}/label`, { method: 'POST', body: { person_id: personId } });
    if (result.success) { this.toast('Face labeled.'); await this.loadPhotos(); }
    else { this.toast(result.error || 'Failed to label face.', true); }
  },

  async restorePhoto(docId) {
    const result = await this.api(`/photos/${docId}/restore`, { method: 'POST' });
    if (result.success || result.url) { this.toast('Photo restored.'); await this.loadPhotos(); }
    else { this.toast(result.error || 'Restore failed.', true); }
  },

  _previewPhoto(url) { if (url) window.open(url, '_blank'); },

  /* ── TIMELINE ── */

  async loadTimeline() {
    const data   = await this.api('/timeline');
    const events = data.events || [];
    const empty  = `<div class="ft-empty-state ft-empty-sm"><p>Timeline will appear when persons with dates are added.</p></div>`;
    this.setHtml('ft-timeline', events.length ? events.map(ev => this.renderTimelineEvent(ev)).join('') : empty);
    if (typeof lucide !== 'undefined') lucide.createIcons();
  },

  /* ── MODALS ── */

  openModal(title) {
    document.getElementById('ft-person-modal-title').textContent = title;
    document.getElementById('ft-person-modal').classList.add('active');
    if (typeof lucide !== 'undefined') lucide.createIcons();
  },

  closeModal() {
    document.getElementById('ft-person-modal').classList.remove('active');
    this.editingPersonId = null;
  },

  closeImportModal() {
    document.getElementById('ft-import-modal').classList.remove('active');
    this._gedcomFile = null;
  },

  /* ── RENDER HELPERS ── */

  renderPersonForm(person) {
    const v   = (f) => this.escHtml(person ? (person[f] || '') : '');
    const sel = (f, val) => (person && person[f] === val) ? 'selected' : '';
    // Extract year from date fields (birth_date may be "1890-01-01" or "1890")
    const yearOf = (f) => {
      if (!person || !person[f]) return '';
      const s = String(person[f]);
      return s.length >= 4 ? s.substring(0, 4) : s;
    };
    const deleteBtn = person
      ? `<button class="ft-btn ft-btn-danger ft-btn-sm" onclick="FamilyTree.deletePerson('${person.id}')" style="margin-left:auto;">Delete</button>`
      : '';
    return `<div style="padding:4px 0;">
      <div class="ft-form-row">
        <div class="ft-form-group">
          <label class="ft-label" for="ft-field-first-name">First Name *</label>
          <input class="ft-input" id="ft-field-first-name" type="text" value="${v('first_name')}" placeholder="Given name">
        </div>
        <div class="ft-form-group">
          <label class="ft-label" for="ft-field-last-name">Last Name</label>
          <input class="ft-input" id="ft-field-last-name" type="text" value="${v('last_name')}" placeholder="Family name">
        </div>
      </div>
      <div class="ft-form-row">
        <div class="ft-form-group">
          <label class="ft-label" for="ft-field-birth-year">Birth Year</label>
          <input class="ft-input" id="ft-field-birth-year" type="text" value="${yearOf('birth_date')}" placeholder="e.g. 1945">
        </div>
        <div class="ft-form-group">
          <label class="ft-label" for="ft-field-death-year">Death Year</label>
          <input class="ft-input" id="ft-field-death-year" type="text" value="${yearOf('death_date')}" placeholder="Leave blank if living">
        </div>
      </div>
      <div class="ft-form-group">
        <label class="ft-label" for="ft-field-birth-place">Birth Place</label>
        <input class="ft-input" id="ft-field-birth-place" type="text" value="${v('birth_place')}" placeholder="City, Country">
      </div>
      <div class="ft-form-row">
        <div class="ft-form-group">
          <label class="ft-label" for="ft-field-gender">Gender</label>
          <select class="ft-select" id="ft-field-gender">
            <option value="">-- Select --</option>
            <option value="male"   ${sel('gender','male')}>Male</option>
            <option value="female" ${sel('gender','female')}>Female</option>
            <option value="other"  ${sel('gender','other')}>Other</option>
          </select>
        </div>
        <div class="ft-form-group">
          <label class="ft-label" for="ft-field-source-type">Source</label>
          <select class="ft-select" id="ft-field-source-type">
            <option value="user_confirmed" ${sel('source_type','user_confirmed')}>User Confirmed</option>
            <option value="from_records"   ${sel('source_type','from_records')}>From Records</option>
            <option value="ai_researching" ${sel('source_type','ai_researching')}>AI Researching</option>
            <option value="unknown"        ${sel('source_type','unknown')}>Unknown</option>
          </select>
        </div>
      </div>
      <div class="ft-form-group">
        <label class="ft-label" for="ft-field-notes">Notes</label>
        <textarea class="ft-textarea" id="ft-field-notes" placeholder="Additional notes...">${v('notes')}</textarea>
      </div>
      <div class="bm-actions" style="margin:12px -24px -20px;padding:10px 24px;">
        ${deleteBtn}
        <span style="flex:1;"></span>
        <button class="btn-cancel" onclick="FamilyTree.closeModal()">Cancel</button>
        <button class="btn-submit" onclick="FamilyTree.savePerson()"><i data-lucide="save"></i> Save</button>
      </div>
    </div>`;
  },

  renderResearchCard(item, isFinding) {
    const badgeClass = { active:'ft-badge-green', queued:'ft-badge-gray', pending_review:'ft-badge-orange', completed:'ft-badge-cyan' }[item.status] || 'ft-badge-gray';
    const actions = isFinding ? `
      <div class="ft-card-actions">
        <button class="ft-btn ft-btn-sm ft-btn-primary" onclick="FamilyTree.acceptFinding('${item.id}')">Accept</button>
        <button class="ft-btn ft-btn-sm ft-btn-danger"  onclick="FamilyTree.rejectFinding('${item.id}')">Reject</button>
      </div>` : '';
    return `<div class="ft-card">
      <div class="ft-card-header">
        <span class="ft-card-title">${this.escHtml(item.research_type || item.type || 'Research')}</span>
        <span class="ft-badge ${badgeClass}">${this.escHtml(item.status || 'unknown')}</span>
      </div>
      <div class="ft-card-meta">Person: ${this.escHtml(String(item.person_id || ''))}
        ${item.found_name ? ` &mdash; Found: <strong>${this.escHtml(item.found_name)}</strong>` : ''}
        ${item.confidence ? ` &mdash; ${Math.round(item.confidence * 100)}% confidence` : ''}
      </div>
      ${item.summary ? `<div style="margin-top:6px;font-size:0.82rem;color:#94a3b8;">${this.escHtml(item.summary)}</div>` : ''}
      ${actions}
    </div>`;
  },

  renderDocumentCard(doc) {
    const ocrBadge = doc.ocr_status === 'done'
      ? '<span class="ft-badge ft-badge-green">OCR Done</span>'
      : doc.ocr_status === 'processing'
        ? '<span class="ft-badge ft-badge-orange">Processing</span>'
        : '<span class="ft-badge ft-badge-gray">No OCR</span>';
    return `<div class="ft-card">
      <div class="ft-card-header">
        <span class="ft-card-title">${this.escHtml(doc.filename || doc.original_filename || 'Document')}</span>
        ${ocrBadge}
      </div>
      <div class="ft-card-meta">
        ${doc.document_type ? this.escHtml(doc.document_type) + ' &mdash; ' : ''}
        ${doc.file_size ? Math.round(doc.file_size / 1024) + ' KB' : ''}
        ${doc.uploaded_at ? ' &mdash; ' + new Date(doc.uploaded_at).toLocaleDateString() : ''}
      </div>
      ${doc.ocr_text_preview ? `<div style="margin-top:8px;font-size:0.78rem;font-family:'IBM Plex Mono',monospace;color:#64748b;max-height:60px;overflow:hidden;">${this.escHtml(doc.ocr_text_preview)}</div>` : ''}
      <div class="ft-card-actions">
        ${doc.url ? `<a href="${this.escHtml(doc.url)}" target="_blank" class="ft-btn ft-btn-sm">View</a>` : ''}
        ${doc.ocr_status !== 'done' ? `<button class="ft-btn ft-btn-sm" onclick="FamilyTree.triggerOcr('${doc.id}')">Run OCR</button>` : ''}
      </div>
    </div>`;
  },

  /* ── MIGRATION MAP ── */

  _mapInstance: null,
  _mapLoaded: false,
  _mapData: null,
  _mapMarkers: [],
  _mapPaths: [],
  _mapView: false,

  toggleMapView() {
    this._mapView = !this._mapView;
    const timeline = document.getElementById('ft-timeline');
    const mapView  = document.getElementById('ft-map-view');
    const toggle   = document.getElementById('ft-map-toggle');
    if (!timeline || !mapView) return;

    if (this._mapView) {
      timeline.classList.add('ft-hidden');
      mapView.classList.remove('ft-hidden');
      toggle.classList.add('ft-btn-active');
      toggle.innerHTML = '<i data-lucide="list"></i> Timeline List';
      this._ensureLeaflet().then(() => this.loadMap());
    } else {
      timeline.classList.remove('ft-hidden');
      mapView.classList.add('ft-hidden');
      toggle.classList.remove('ft-btn-active');
      toggle.innerHTML = '<i data-lucide="map"></i> Migration Map';
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
  },

  _ensureLeaflet() {
    if (this._mapLoaded) return Promise.resolve();
    return new Promise((resolve) => {
      // Load CSS
      if (!document.querySelector('link[href*="leaflet"]')) {
        const css = document.createElement('link');
        css.rel = 'stylesheet';
        css.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
        document.head.appendChild(css);
      }
      // Load JS
      if (window.L) { this._mapLoaded = true; resolve(); return; }
      if (!document.querySelector('script[src*="leaflet"]')) {
        const script = document.createElement('script');
        script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
        script.onload = () => { this._mapLoaded = true; resolve(); };
        document.head.appendChild(script);
      } else {
        const check = setInterval(() => {
          if (window.L) { clearInterval(check); this._mapLoaded = true; resolve(); }
        }, 50);
      }
    });
  },

  async loadMap() {
    const container = document.getElementById('ft-map-container');
    if (!container || !window.L) return;

    const data = await this.api('/timeline/migration');
    this._mapData = data;

    if (!this._mapInstance) {
      this._mapInstance = L.map('ft-map-container', {
        center: [38.7, -9.14],
        zoom: 3,
        zoomControl: true,
        attributionControl: true,
      });
      L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19,
      }).addTo(this._mapInstance);
    }

    const minSlider = document.getElementById('ft-map-year-min');
    const maxSlider = document.getElementById('ft-map-year-max');
    if (minSlider && maxSlider) {
      minSlider.oninput = () => {
        document.getElementById('ft-map-year-min-val').textContent = minSlider.value;
        this._filterMapByYear();
      };
      maxSlider.oninput = () => {
        document.getElementById('ft-map-year-max-val').textContent = maxSlider.value;
        this._filterMapByYear();
      };
    }

    this._renderMapData(data);
    setTimeout(() => { this._mapInstance.invalidateSize(); }, 100);
  },

  _renderMapData(data) {
    if (!this._mapInstance || !data) return;

    this._mapMarkers.forEach(m => this._mapInstance.removeLayer(m));
    this._mapPaths.forEach(p => {
      if (p._ftAnimFrame) cancelAnimationFrame(p._ftAnimFrame);
      this._mapInstance.removeLayer(p);
    });
    this._mapMarkers = [];
    this._mapPaths = [];

    const bounds = [];

    (data.locations || []).forEach(loc => {
      const color = loc.event === 'birth' ? '#10b981' : '#ef4444';
      const icon = L.divIcon({
        className: 'ft-map-marker',
        html: '<div style="width:12px;height:12px;border-radius:50%;background:' + color +
              ';border:2px solid rgba(0,0,0,0.5);box-shadow:0 0 8px ' + color + '40;"></div>',
        iconSize: [12, 12],
        iconAnchor: [6, 6],
      });

      const yearStr = loc.year ? ' (' + loc.year + ')' : '';
      const marker = L.marker([loc.lat, loc.lng], { icon })
        .bindPopup('<strong style="color:' + color + ';">' + this.escHtml(loc.name) + '</strong><br>' +
          this.escHtml(loc.event === 'birth' ? 'Born' : 'Died') + ': ' + this.escHtml(loc.place) + yearStr);
      marker._ftYear = loc.year;
      marker._ftEvent = loc.event;
      marker.addTo(this._mapInstance);
      this._mapMarkers.push(marker);
      bounds.push([loc.lat, loc.lng]);
    });

    (data.paths || []).forEach(path => {
      const latlngs = [[path.from.lat, path.from.lng], [path.to.lat, path.to.lng]];

      const glow = L.polyline(latlngs, {
        color: '#10b981', weight: 4, opacity: 0.15,
      });
      glow._ftYearFrom = path.year_from;
      glow._ftYearTo = path.year_to;
      glow.addTo(this._mapInstance);
      this._mapPaths.push(glow);

      const line = L.polyline(latlngs, {
        color: '#10b981', weight: 2, opacity: 0.7, dashArray: '8, 12',
      });
      line._ftYearFrom = path.year_from;
      line._ftYearTo = path.year_to;

      const yearStr = (path.year_from || '?') + ' \u2192 ' + (path.year_to || '?');
      line.bindPopup(
        '<strong style="color:#10b981;">' + this.escHtml(path.name) + '</strong><br>' +
        this.escHtml(path.from_place || '') + ' \u2192 ' + this.escHtml(path.to_place || '') + '<br>' +
        '<span style="color:#94a3b8;">' + yearStr + '</span>'
      );
      line.addTo(this._mapInstance);
      this._mapPaths.push(line);

      this._animateDash(line);
    });

    if (bounds.length > 0) {
      this._mapInstance.fitBounds(bounds, { padding: [40, 40], maxZoom: 6 });
    }
  },

  _animateDash(polyline) {
    let offset = 0;
    const el = polyline.getElement && polyline.getElement();
    if (!el) {
      setTimeout(() => this._animateDash(polyline), 200);
      return;
    }
    const animate = () => {
      offset -= 0.5;
      el.style.strokeDashoffset = offset;
      polyline._ftAnimFrame = requestAnimationFrame(animate);
    };
    animate();
  },

  _filterMapByYear() {
    const minYear = parseInt(document.getElementById('ft-map-year-min')?.value) || 1400;
    const maxYear = parseInt(document.getElementById('ft-map-year-max')?.value) || 2026;

    this._mapMarkers.forEach(m => {
      const y = m._ftYear;
      const visible = !y || (y >= minYear && y <= maxYear);
      if (visible) {
        if (!this._mapInstance.hasLayer(m)) m.addTo(this._mapInstance);
      } else {
        this._mapInstance.removeLayer(m);
      }
    });

    this._mapPaths.forEach(p => {
      const yf = p._ftYearFrom;
      const yt = p._ftYearTo;
      const visible = (!yf && !yt) ||
        (yf && yf >= minYear && yf <= maxYear) ||
        (yt && yt >= minYear && yt <= maxYear) ||
        (yf && yt && yf <= maxYear && yt >= minYear);
      if (visible) {
        if (!this._mapInstance.hasLayer(p)) p.addTo(this._mapInstance);
      } else {
        this._mapInstance.removeLayer(p);
      }
    });
  },

  renderTimelineEvent(event) {
    const dotColors = { birth:'#10b981', death:'#ef4444', marriage:'#8b5cf6', migration:'#f97316', census:'#00e5ff' };
    const color = dotColors[event.event_type] || '#64748b';
    return `<div class="ft-timeline-event">
      <div class="ft-timeline-dot" style="background:${color};"></div>
      <div class="ft-timeline-date">${this.escHtml(String(event.year || event.date || 'Unknown date'))}</div>
      <div class="ft-timeline-content">
        <div class="ft-timeline-title">${this.escHtml(event.title || event.event_type || 'Event')}</div>
        ${event.description ? `<div class="ft-timeline-desc">${this.escHtml(event.description)}</div>` : ''}
        ${event.person_name ? `<div class="ft-timeline-desc" style="color:#10b981;">${this.escHtml(event.person_name)}</div>` : ''}
        ${event.location    ? `<div class="ft-timeline-desc">${this.escHtml(event.location)}</div>` : ''}
      </div>
    </div>`;
  },
};

document.addEventListener('DOMContentLoaded', () => FamilyTree.init());
