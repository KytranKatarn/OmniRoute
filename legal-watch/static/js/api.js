/* G.A.V.E.L. API client */
const API = {
  base: '/api',

  async get(path, params = {}) {
    const url = new URL(path, window.location.origin);
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
    });
    const res = await fetch(url);
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  },

  async getEvents(params = {}) {
    return this.get(`${this.base}/events`, params);
  },

  async getStats() {
    return this.get(`${this.base}/stats`);
  },

  async getRegulations(params = {}) {
    return this.get(`${this.base}/regulations`, params);
  },

  async getHealth() {
    return this.get('/health');
  },
};
