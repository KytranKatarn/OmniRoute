/* Party and city branding.

   Two constraints shape this file.

   1. WE DO NOT SHIP OTHER PEOPLE'S LOGOS. Party logos and municipal crests are
      trademarks. What renders here is a MONOGRAM built from the party's own
      colour and initials — a designed placeholder, not an imitation of a
      logo. When a real asset exists, `logoUrl` fills the same tile and the
      monogram becomes the onerror fallback, exactly as member photos work.
   2. A MONOGRAM IS IDENTIFICATION, NOT ENDORSEMENT. It carries the party
      colour only. It never carries a delivery verdict or a lean band, so a
      Conservative blue tile can never be misread as a right-lean score.

   Exposed as window.WTFBrand so pages can load it alongside their own scripts
   without colliding at global scope. */

(function () {
'use strict';

/* Initials are authored, not derived: "Québec solidaire" initialises to QS,
   not to "Qs", and "Toronto — Chow administration" is a city, not a party. */
const MONO = {
  lib:'LPC', cpc:'CPC', ndp:'NDP', bq:'BQ', gpc:'GPC', ppc:'PPC',
  caq:'CAQ', pq:'PQ', qs:'QS', plq:'PLQ',
  onpc:'PC', olp:'OLP', onndp:'NDP',
  bcndp:'NDP', bccon:'BCC', ucp:'UCP', abndp:'NDP', sask:'SP',
  projet:'PM', ensemble:'EM', abc:'ABC', onecity:'OC', cope:'COPE', npa:'NPA',
  chow:'TO', gondek:'YYC'
};

/* Municipal entries brand on the CITY, since most Canadian municipalities have
   no parties at all — a city monogram is the honest unit there. */
const CITY_MONO = {
  'Toronto':'TO', 'Montréal':'MTL', 'Vancouver':'VAN', 'Calgary':'YYC',
  'Edmonton':'YEG', 'Ottawa':'OTT', 'Winnipeg':'WPG', 'Québec City':'QC',
  'Halifax':'HFX', 'Mississauga':'MIS', 'Brampton':'BRM', 'Hamilton':'HAM',
  'Surrey':'SRY', 'Burnaby':'BBY', 'Laval':'LVL', "St. John's":'SJ',
  'Regina':'REG', 'Saskatoon':'SAS', 'Victoria':'VIC', 'Kelowna':'KEL'
};

const esc = function (x) {
  return String(x == null ? '' : x).replace(/[&<>"]/g, function (c) {
    return ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;' })[c];
  });
};

/* Fall back to initials of significant words, skipping articles and the
   province qualifiers that would otherwise dominate a short monogram. */
const SKIP = { of:1, the:1, de:1, du:1, la:1, le:1, and:1, party:1, association:1, canada:1 };
function derive(name) {
  const words = String(name || '').replace(/[—–\-]/g, ' ').split(/\s+/)
    .filter(function (w) { return w && !SKIP[w.toLowerCase()]; });
  return words.map(function (w) { return w[0]; }).join('').slice(0, 4).toUpperCase();
}

function monogramFor(entity) {
  if (!entity) return '?';
  if (entity.mono) return entity.mono;
  if (entity.id && MONO[entity.id]) return MONO[entity.id];
  if (entity.nonpartisan && entity.city && CITY_MONO[entity.city]) return CITY_MONO[entity.city];
  if (entity.city && CITY_MONO[entity.city] && !entity.short) return CITY_MONO[entity.city];
  return derive(entity.short || entity.name || entity.city);
}

/* size: px. shape: 'tile' (parties) | 'round' (people) | 'shield' (cities).
   A city gets a shield because a crest is the civic convention, and it reads as
   a place rather than an organisation. */
function tile(entity, opts) {
  opts = opts || {};
  const size = opts.size || 44;
  const col = entity.col || 'var(--wtf-border)';
  const mono = monogramFor(entity);
  const shape = opts.shape || (entity.level === 'municipal' && entity.nonpartisan ? 'shield' : 'tile');
  const radius = shape === 'round' ? '50%'
    : shape === 'shield' ? Math.round(size * 0.18) + 'px ' + Math.round(size * 0.18) + 'px ' +
        Math.round(size * 0.42) + 'px ' + Math.round(size * 0.42) + 'px'
    : Math.round(size * 0.22) + 'px';
  /* Monogram scales to its own length so a four-letter mark still fits. */
  const fs = Math.round(size / (mono.length > 3 ? 3.4 : mono.length > 2 ? 2.9 : 2.5));

  return '<span class="wtf-brand" style="' +
      'width:' + size + 'px;height:' + size + 'px;border-radius:' + radius + ';' +
      'background:color-mix(in srgb, ' + col + ' 15%, transparent);' +
      'border:1.5px solid color-mix(in srgb, ' + col + ' 55%, transparent);' +
      'color:' + col + ';font-size:' + fs + 'px;' +
      '" title="' + esc(entity.name || entity.short || '') + '" aria-hidden="true">' +
    (entity.logoUrl
      ? '<img src="' + esc(entity.logoUrl) + '" alt="" onerror="this.remove()">' +
        '<span class="wtf-brand-m">' + esc(mono) + '</span>'
      : '<span class="wtf-brand-m">' + esc(mono) + '</span>') +
    (opts.label === false ? '' : '') +
  '</span>';
}

/* A wordmark pairs the tile with the name, for hero and card headers. */
function wordmark(entity, opts) {
  opts = opts || {};
  const size = opts.size || 44;
  const sub = opts.sub || '';
  return '<span class="wtf-brand-wm">' + tile(entity, opts) +
    '<span class="wtf-brand-tx">' +
      '<span class="wtf-brand-nm" style="font-size:' + (opts.nameSize || 18) + 'px">' +
        esc(opts.name || entity.short || entity.name) + '</span>' +
      (sub ? '<span class="wtf-brand-sub">' + esc(sub) + '</span>' : '') +
    '</span></span>';
}

/* Injected once so every page that loads this file gets the same treatment
   without repeating the rules. */
const CSS = '' +
  '.wtf-brand{display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;' +
    'font-family:var(--wtf-font-mono);font-weight:600;letter-spacing:.02em;overflow:hidden;position:relative;line-height:1}' +
  '.wtf-brand img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;padding:12%}' +
  '.wtf-brand img + .wtf-brand-m{opacity:0}' +
  '.wtf-brand-wm{display:inline-flex;align-items:center;gap:11px;min-width:0}' +
  '.wtf-brand-tx{display:flex;flex-direction:column;gap:2px;min-width:0}' +
  '.wtf-brand-nm{font-family:var(--wtf-font-serif);font-weight:600;letter-spacing:-.016em;color:var(--wtf-text);line-height:1.15}' +
  '.wtf-brand-sub{font-family:var(--wtf-font-mono);font-size:9px;letter-spacing:.07em;color:var(--wtf-text-muted)}';

(function inject() {
  if (document.getElementById('wtf-brand-css')) return;
  const s = document.createElement('style');
  s.id = 'wtf-brand-css';
  s.textContent = CSS;
  document.head.appendChild(s);
})();

window.WTFBrand = { tile:tile, wordmark:wordmark, monogram:monogramFor, cityMono:CITY_MONO };

})();
