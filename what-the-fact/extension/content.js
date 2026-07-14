/**
 * What The Fact — Bias Ratings Content Script (#3328)
 *
 * Scans social-media pages for links to Canadian news outlets, looks up their WTF bias,
 * and injects a coloured dot badge next to each matching link. Pure logic (domain parsing,
 * bias mapping, lookups) lives in bias-logic.js (loaded first, exposed as `WTFBias`).
 *
 * Badge colour: blue = left, grey = centre, red = right, yellow = unrated.
 */

const WTF_API_URL = "https://what-the-fact.com/api/edu/v1/sources";
const CACHE_KEY = "wtf_bias_sources_cache";
const CACHE_TTL_MS = 6 * 60 * 60 * 1000; // 6 hours

// Retrieve cached sources or fetch fresh from the (CORS-open) WTF API.
async function getSources() {
  return new Promise((resolve) => {
    chrome.storage.local.get([CACHE_KEY], (result) => {
      const cached = result[CACHE_KEY];
      if (cached && cached.timestamp && Date.now() - cached.timestamp < CACHE_TTL_MS) {
        resolve(cached.data);
        return;
      }
      fetch(WTF_API_URL)
        .then((r) => r.json())
        .then((data) => {
          const sources = data.sources || data || [];
          chrome.storage.local.set({
            [CACHE_KEY]: { timestamp: Date.now(), data: sources },
          });
          resolve(sources);
        })
        .catch((err) => {
          console.warn("[WTF Bias] Failed to fetch sources:", err);
          resolve(cached ? cached.data : []);
        });
    });
  });
}

// Inject a badge dot immediately after a link element.
function injectBadge(linkEl, biasClass, outletName, band, score) {
  if (linkEl.dataset.wtfBadged) return; // don't double-badge
  linkEl.dataset.wtfBadged = "1";

  const badge = document.createElement("span");
  badge.className = `wtf-bias-badge ${biasClass}`;

  const direction = WTFBias.biasDirectionText(biasClass);
  const bandPart = band ? ` · ${WTFBias.formatBandLabel(band)}` : "";
  const scorePart =
    score !== null && score !== undefined && !Number.isNaN(Number(score))
      ? ` (${Number(score).toFixed(2)})`
      : "";
  badge.title = `${outletName || "Unknown"}: ${direction}${bandPart}${scorePart} — What The Fact`;

  linkEl.insertAdjacentElement("afterend", badge);
}

// Scan all links in the document and badge the ones pointing at a known outlet.
function scanLinks(biasMap, nameMap) {
  const links = document.querySelectorAll("a[href]");
  for (const link of links) {
    const href = link.getAttribute("href");
    if (!href) continue;

    let domain = WTFBias.extractDomain(href);
    // X/Twitter rewrites external links to t.co/... — the outlet can't be read from the
    // href, but its real domain is in the visible link text. Resolve it so those links
    // still get badged. (#4671)
    if (!domain || WTFBias.SHORTENER_DOMAINS.has(domain)) {
      const fromText = WTFBias.extractDomainFromText(link.textContent);
      if (fromText) domain = fromText;
    }
    if (!domain) continue;

    // Match if it's a known Canadian outlet (hardcoded fast-path OR API-sourced).
    if (!WTFBias.CANADIAN_NEWS_DOMAINS.has(domain) && !(domain in biasMap)) continue;

    const entry = biasMap[domain] || null;
    const score = entry ? entry.score ?? null : null;
    const lean = entry ? entry.lean ?? null : null;
    const band = entry ? entry.band ?? null : null;
    const biasClass = WTFBias.resolveBiasClass(band, lean, score);
    const outletName = nameMap[domain] || domain;

    injectBadge(link, biasClass, outletName, band, score);
  }
}

// Watch for dynamically injected links (SPAs like X load content async). Debounced.
function observeNewLinks(biasMap, nameMap) {
  const observer = new MutationObserver((mutations) => {
    let hasNewNodes = false;
    for (const mutation of mutations) {
      if (mutation.addedNodes.length > 0) {
        hasNewNodes = true;
        break;
      }
    }
    if (hasNewNodes) {
      clearTimeout(observer._timer);
      observer._timer = setTimeout(() => scanLinks(biasMap, nameMap), 300);
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
}

// Entry point.
(async () => {
  try {
    const sources = await getSources();
    const biasMap = WTFBias.buildBiasMap(sources);
    const nameMap = WTFBias.buildNameMap(sources);
    scanLinks(biasMap, nameMap);
    observeNewLinks(biasMap, nameMap);
  } catch (err) {
    console.error("[WTF Bias] Content script error:", err);
  }
})();
