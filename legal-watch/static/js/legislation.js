/* Legislation tab — legislation events + Civic Watch link */

let legislationLoaded = false;

async function loadLegislation() {
  if (legislationLoaded) return;

  const container = document.getElementById('legislation-content');
  container.textContent = '';

  // Civic Watch link card
  const card = document.createElement('div');
  card.className = 'placeholder-card';
  card.style.marginBottom = '24px';
  card.style.borderColor = 'var(--legislation)';

  const h3 = document.createElement('h3');
  h3.style.color = 'var(--legislation)';
  h3.textContent = 'Parliament Activity';
  card.appendChild(h3);

  const p1 = document.createElement('p');
  p1.textContent = 'For full parliamentary tracking (bills, votes, committee reports), visit Kytran Civic Watch.';
  card.appendChild(p1);

  const p2 = document.createElement('p');
  p2.style.marginTop = '12px';
  const link = document.createElement('a');
  link.href = 'https://civic.kytranempowerment.com/#parliament';
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.style.color = 'var(--legislation)';
  link.style.fontWeight = '600';
  link.textContent = 'Open Civic Watch Parliament Tab \u2192';
  p2.appendChild(link);
  card.appendChild(p2);

  container.appendChild(card);

  // Load legislation-type events
  try {
    const events = await API.getEvents({ type: 'regulation', category: 'legislation', limit: 50 });

    if (events.length > 0) {
      const wrapper = document.createElement('div');
      wrapper.style.overflowX = 'auto';
      const table = document.createElement('table');
      table.className = 'data-table';

      const thead = document.createElement('thead');
      const headerRow = document.createElement('tr');
      ['Title', 'Source', 'Category', 'Date'].forEach(text => {
        const th = document.createElement('th');
        th.textContent = text;
        headerRow.appendChild(th);
      });
      thead.appendChild(headerRow);
      table.appendChild(thead);

      const tbody = document.createElement('tbody');
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
        badge.className = 'badge badge--legislation';
        badge.textContent = ev.category || 'legislation';
        tdCat.appendChild(badge);
        const tdDate = document.createElement('td');
        tdDate.textContent = fmtDate(ev.published_date);
        tr.append(tdTitle, tdSource, tdCat, tdDate);
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      wrapper.appendChild(table);
      container.appendChild(wrapper);
    } else {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.textContent = 'No legislation events ingested yet. Gazette items with legislation keywords will appear here.';
      container.appendChild(empty);
    }
  } catch (e) {
    const err = document.createElement('div');
    err.className = 'empty-state';
    err.textContent = 'Error loading legislation events: ' + e.message;
    container.appendChild(err);
  }

  legislationLoaded = true;
}
