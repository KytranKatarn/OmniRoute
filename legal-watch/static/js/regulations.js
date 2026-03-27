/* Regulations tab — Canada Gazette table */

let regulationsLoaded = false;

async function loadRegulations() {
  if (regulationsLoaded) return;
  await fetchRegulations();
  regulationsLoaded = true;

  document.getElementById('regulations-filters').addEventListener('submit', e => {
    e.preventDefault();
    regulationsLoaded = false;
    fetchRegulations();
    regulationsLoaded = true;
  });
}

function _badgeEl(cls, text) {
  const span = document.createElement('span');
  span.className = 'badge badge--' + cls;
  span.textContent = text;
  return span;
}

async function fetchRegulations() {
  const tbody = document.getElementById('regulations-tbody');
  tbody.textContent = '';
  const loadRow = document.createElement('tr');
  const loadCell = document.createElement('td');
  loadCell.colSpan = 5;
  loadCell.className = 'loading';
  loadCell.textContent = 'Loading regulations...';
  loadRow.appendChild(loadCell);
  tbody.appendChild(loadRow);

  try {
    const type = document.getElementById('reg-type')?.value || '';
    const keyword = document.getElementById('reg-keyword')?.value || '';
    const regs = await API.getRegulations({ type, keyword, limit: 100 });

    tbody.textContent = '';
    if (regs.length === 0) {
      const r = document.createElement('tr');
      const c = document.createElement('td');
      c.colSpan = 5;
      c.className = 'empty-state';
      c.textContent = 'No regulations found';
      r.appendChild(c);
      tbody.appendChild(r);
      return;
    }

    regs.forEach(reg => {
      const tr = document.createElement('tr');
      const tdTitle = document.createElement('td');
      if (reg.source_url) {
        const a = document.createElement('a');
        a.href = reg.source_url;
        a.target = '_blank';
        a.textContent = reg.title;
        tdTitle.appendChild(a);
      } else {
        tdTitle.textContent = reg.title;
      }
      const tdPart = document.createElement('td');
      tdPart.textContent = reg.gazette_part || '';
      const tdType = document.createElement('td');
      tdType.appendChild(_badgeEl(reg.reg_type || 'general', reg.reg_type || 'unknown'));
      const tdDept = document.createElement('td');
      tdDept.textContent = reg.department || '\u2014';
      const tdDate = document.createElement('td');
      tdDate.textContent = fmtDate(reg.published_date);
      tr.append(tdTitle, tdPart, tdType, tdDept, tdDate);
      tbody.appendChild(tr);
    });
  } catch (e) {
    tbody.textContent = '';
    const r = document.createElement('tr');
    const c = document.createElement('td');
    c.colSpan = 5;
    c.className = 'empty-state';
    c.textContent = 'Error: ' + e.message;
    r.appendChild(c);
    tbody.appendChild(r);
  }
}
