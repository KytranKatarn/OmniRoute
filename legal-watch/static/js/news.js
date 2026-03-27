/* Legal News tab — GDELT news table */

let newsLoaded = false;

async function loadNews() {
  if (newsLoaded) return;
  await fetchNews();
  newsLoaded = true;

  document.getElementById('news-filters').addEventListener('submit', e => {
    e.preventDefault();
    newsLoaded = false;
    fetchNews();
    newsLoaded = true;
  });
}

async function fetchNews() {
  const tbody = document.getElementById('news-tbody');
  tbody.textContent = '';
  const loadRow = document.createElement('tr');
  const loadCell = document.createElement('td');
  loadCell.colSpan = 4;
  loadCell.className = 'loading';
  loadCell.textContent = 'Loading legal news...';
  loadRow.appendChild(loadCell);
  tbody.appendChild(loadRow);

  try {
    const category = document.getElementById('news-category')?.value || '';
    const keyword = document.getElementById('news-keyword')?.value || '';
    const events = await API.getEvents({ type: 'news', category, keyword, limit: 100 });

    tbody.textContent = '';
    if (events.length === 0) {
      const r = document.createElement('tr');
      const c = document.createElement('td');
      c.colSpan = 4;
      c.className = 'empty-state';
      c.textContent = 'No legal news found';
      r.appendChild(c);
      tbody.appendChild(r);
      return;
    }

    events.forEach(ev => {
      const tr = document.createElement('tr');
      const tdTitle = document.createElement('td');
      if (ev.source_url) {
        const a = document.createElement('a');
        a.href = ev.source_url;
        a.target = '_blank';
        a.textContent = ev.title;
        tdTitle.appendChild(a);
      } else {
        tdTitle.textContent = ev.title;
      }
      const tdSource = document.createElement('td');
      tdSource.textContent = ev.source_name || '\u2014';
      const tdCat = document.createElement('td');
      const badge = document.createElement('span');
      badge.className = 'badge badge--' + (ev.category || 'general');
      badge.textContent = ev.category || 'general';
      tdCat.appendChild(badge);
      const tdDate = document.createElement('td');
      tdDate.textContent = fmtDate(ev.published_date);
      tr.append(tdTitle, tdSource, tdCat, tdDate);
      tbody.appendChild(tr);
    });
  } catch (err) {
    tbody.textContent = '';
    const r = document.createElement('tr');
    const c = document.createElement('td');
    c.colSpan = 4;
    c.className = 'empty-state';
    c.textContent = 'Error: ' + err.message;
    r.appendChild(c);
    tbody.appendChild(r);
  }
}
