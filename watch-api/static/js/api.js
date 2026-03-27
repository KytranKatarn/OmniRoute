/* W.A.T.C.H. API Client — base fetch wrapper */

const API = {
  /**
   * Fetch JSON from a /api/* endpoint with query params.
   * Returns parsed JSON or throws with a message.
   */
  async get(path, params = {}) {
    const url = new URL(path, window.location.origin);
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') {
        url.searchParams.set(k, v);
      }
    });
    const res = await fetch(url.toString());
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      throw new Error(`API ${path} → ${res.status}: ${text}`);
    }
    return res.json();
  },

  /** Convenience helpers */
  stats: () => API.get('/api/stats'),
  contracts: (params) => API.get('/api/contracts', params),
  bills: (params) => API.get('/api/parliament/bills', params),
  votes: (params) => API.get('/api/parliament/votes', params),
  spending: (params) => API.get('/api/spending', params),
  events: (params) => API.get('/api/events', params),
};

/**
 * Format a dollar amount to a compact Canadian string.
 * e.g. 4500000 → "$4.5M"  |  125000 → "$125K"
 */
function fmtAmount(n) {
  if (n == null || isNaN(n)) return '—';
  n = Number(n);
  if (n >= 1e9) return '$' + (n / 1e9).toFixed(1).replace(/\.0$/, '') + 'B';
  if (n >= 1e6) return '$' + (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
  if (n >= 1e3) return '$' + (n / 1e3).toFixed(0) + 'K';
  return '$' + n.toLocaleString('en-CA');
}

/**
 * Format a date string (YYYY-MM-DD or ISO) to a short locale string.
 */
function fmtDate(str) {
  if (!str) return '—';
  const d = new Date(str);
  if (isNaN(d)) return str;
  return d.toLocaleDateString('en-CA', { year: 'numeric', month: 'short', day: 'numeric' });
}

/**
 * Escape HTML special chars to prevent XSS.
 */
function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Render an empty-state div.
 */
function emptyState(msg = 'No data found.') {
  return `<div class="empty-state"><div class="empty-state__icon">🔍</div><p>${esc(msg)}</p></div>`;
}

/**
 * Render a loading div.
 */
function loadingState(msg = 'Loading…') {
  return `<div class="loading">${esc(msg)}</div>`;
}

/**
 * Build a level badge element.
 */
function levelBadge(level) {
  const cls = { federal: 'federal', provincial: 'provincial', municipal: 'municipal' }[level] || 'federal';
  return `<span class="badge badge--${cls}">${esc(level || 'unknown')}</span>`;
}

/**
 * Build a status badge for bills/votes.
 */
function statusBadge(status) {
  const map = {
    passed: 'passed', defeated: 'defeated', introduced: 'introduced',
    committee: 'committee', royal_assent: 'passed',
  };
  const cls = map[status] || 'introduced';
  const label = status ? status.replace(/_/g, ' ') : 'unknown';
  return `<span class="badge badge--${cls}">${esc(label)}</span>`;
}

/**
 * Build a type badge for events.
 */
function typeBadge(type) {
  const map = { contract: 'contract', bill: 'bill', vote: 'vote', spending: 'spending' };
  const cls = map[type] || 'contract';
  return `<span class="badge badge--${cls}">${esc(type || '?')}</span>`;
}
