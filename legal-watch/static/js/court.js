/* Court Decisions tab — CanLII placeholder */

let courtLoaded = false;

function loadCourt() {
  if (courtLoaded) return;

  const container = document.getElementById('court-content');
  container.textContent = '';

  const card = document.createElement('div');
  card.className = 'placeholder-card';

  const h3 = document.createElement('h3');
  h3.textContent = 'CanLII Integration';
  card.appendChild(h3);

  const p1 = document.createElement('p');
  p1.textContent = 'Court decision search is coming soon.';
  card.appendChild(p1);

  const p2 = document.createElement('p');
  p2.textContent = 'This feature will integrate with the Canadian Legal Information Institute (CanLII) to provide searchable access to Canadian court decisions, tribunal rulings, and legal commentary.';
  card.appendChild(p2);

  const p3 = document.createElement('p');
  p3.style.marginTop = '16px';
  const link = document.createElement('a');
  link.href = 'https://www.canlii.org/en/';
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.style.color = 'var(--accent)';
  link.style.fontWeight = '600';
  link.textContent = 'Search CanLII directly \u2192';
  p3.appendChild(link);
  card.appendChild(p3);

  const p4 = document.createElement('p');
  p4.style.marginTop = '24px';
  p4.style.fontSize = '0.75rem';
  p4.style.color = 'var(--text-dim)';
  p4.textContent = 'Awaiting API key approval from CanLII. Once available, G.A.V.E.L. will ingest and index federal and provincial court decisions automatically.';
  card.appendChild(p4);

  container.appendChild(card);
  courtLoaded = true;
}
