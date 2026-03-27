/* Dashboard tab — hero stats + recent events */

let dashboardLoaded = false;

async function loadDashboard() {
  if (dashboardLoaded) return;

  try {
    const stats = await API.getStats();
    document.getElementById('stat-regulations-value').textContent = stats.regulations || 0;
    document.getElementById('stat-court-value').textContent = '—';
    document.getElementById('stat-news-value').textContent = stats.legal_news || 0;
    document.getElementById('stat-legislation-value').textContent = stats.gazette_items || 0;
  } catch (e) {
    console.error('[G.A.V.E.L.] Stats error:', e);
  }

  // Recent regulations
  try {
    const regs = await API.getRegulations({ limit: 5 });
    const el = document.getElementById('widget-regulations-list');
    if (regs.length === 0) {
      el.textContent = 'No regulations yet';
    } else {
      el.textContent = '';
      regs.forEach(r => {
        const div = document.createElement('div');
        div.className = 'widget-item';
        const title = document.createElement('span');
        title.className = 'widget-item__title';
        title.textContent = r.title;
        const meta = document.createElement('span');
        meta.className = 'widget-item__meta';
        meta.textContent = fmtDate(r.published_date);
        div.appendChild(title);
        div.appendChild(meta);
        el.appendChild(div);
      });
    }
  } catch (e) {
    document.getElementById('widget-regulations-list').textContent = 'Failed to load';
  }

  // Recent news
  try {
    const news = await API.getEvents({ type: 'news', limit: 5 });
    const el = document.getElementById('widget-news-list');
    if (news.length === 0) {
      el.textContent = 'No news yet';
    } else {
      el.textContent = '';
      news.forEach(n => {
        const div = document.createElement('div');
        div.className = 'widget-item';
        const title = document.createElement('span');
        title.className = 'widget-item__title';
        if (n.source_url) {
          const a = document.createElement('a');
          a.href = n.source_url;
          a.target = '_blank';
          a.textContent = n.title;
          title.appendChild(a);
        } else {
          title.textContent = n.title;
        }
        const meta = document.createElement('span');
        meta.className = 'widget-item__meta';
        meta.textContent = n.category || '';
        div.appendChild(title);
        div.appendChild(meta);
        el.appendChild(div);
      });
    }
  } catch (e) {
    document.getElementById('widget-news-list').textContent = 'Failed to load';
  }

  // Recent gazette
  try {
    const gaz = await API.getEvents({ type: 'regulation', limit: 5 });
    const el = document.getElementById('widget-gazette-list');
    if (gaz.length === 0) {
      el.textContent = 'No gazette items yet';
    } else {
      el.textContent = '';
      gaz.forEach(g => {
        const div = document.createElement('div');
        div.className = 'widget-item';
        const title = document.createElement('span');
        title.className = 'widget-item__title';
        if (g.source_url) {
          const a = document.createElement('a');
          a.href = g.source_url;
          a.target = '_blank';
          a.textContent = g.title;
          title.appendChild(a);
        } else {
          title.textContent = g.title;
        }
        const meta = document.createElement('span');
        meta.className = 'widget-item__meta';
        meta.textContent = g.category || '';
        div.appendChild(title);
        div.appendChild(meta);
        el.appendChild(div);
      });
    }
  } catch (e) {
    document.getElementById('widget-gazette-list').textContent = 'Failed to load';
  }

  dashboardLoaded = true;
}
