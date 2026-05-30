/**
 * What The Fact — Bias Ratings Content Script
 * T3014: Bias Ratings on Social Media
 *
 * Scans social media pages for links to Canadian news outlets,
 * fetches bias ratings from the WTF API, and injects coloured
 * dot badges next to each matching link.
 *
 * Bias colour coding:
 *   blue   = left-leaning
 *   grey   = centre / balanced
 *   red    = right-leaning
 *   yellow = unknown / unrated
 */

const WTF_API_URL = "https://what-the-fact.com/api/edu/v1/sources";
const CACHE_KEY = "wtf_bias_sources_cache";
const CACHE_TTL_MS = 6 * 60 * 60 * 1000; // 6 hours

// Known Canadian news domains to match against
const CANADIAN_NEWS_DOMAINS = new Set([
  "cbc.ca",
  "ctv.ca",
  "ctvcalgary.ca",
  "globalnews.ca",
  "theglobeandmail.com",
  "nationalpost.com",
  "torontostar.com",
  "thestar.com",
  "montrealgazette.com",
  "ottawacitizen.com",
  "calgaryherald.com",
  "edmontonjournal.com",
  "vancouversun.com",
  "ledevoir.com",
  "lapresse.ca",
  "journaldemontreal.com",
  "journaldequebec.com",
  "postmedia.com",
  "macleans.ca",
  "thetyee.ca",
  "rabble.ca",
  "ipolitics.ca",
  "hilltimes.com",
  "policyoptions.irpp.org",
  "theconversation.com",
  "canadaland.com",
  "westernstandard.ca",
  "torontosun.com",
  "calgarysun.com",
  "ottawasun.com",
  "winnipegsun.com",
  "edmontonexaminer.com",
  "cp24.com",
  "citynews.ca",
  "680news.com",
  "570news.com",
  "ici.radio-canada.ca",
  "rcinet.ca",
]);

// Map a categorical WTF bias_lean label to a CSS class name.
// The API exposes labels like: left, center-left, center, center-right, right.
function biasLeanToClass(lean) {
  if (!lean) return null;
  const l = String(lean).toLowerCase().replace(/_/g, "-").trim();
  if (l === "left" || l === "center-left" || l === "centre-left") {
    return "wtf-bias-left";
  }
  if (l === "right" || l === "center-right" || l === "centre-right") {
    return "wtf-bias-right";
  }
  if (l === "center" || l === "centre" || l === "balanced" || l === "mixed") {
    return "wtf-bias-centre";
  }
  return null;
}

// Map WTF bias scores to CSS class names
// WTF uses a numeric scale; we bucket into left/centre/right
function biasScoreToClass(score) {
  if (score === null || score === undefined) return "wtf-bias-unknown";
  if (score < -0.2) return "wtf-bias-left";
  if (score > 0.2) return "wtf-bias-right";
  return "wtf-bias-centre";
}

// Resolve the best bias class for a source: prefer the categorical
// bias_lean label (renders even when avg_score is NULL), fall back to
// the numeric bias_score bucket.
function resolveBiasClass(score, lean) {
  const leanClass = biasLeanToClass(lean);
  if (leanClass) return leanClass;
  return biasScoreToClass(score);
}

// Extract root domain from a URL string
function extractDomain(href) {
  try {
    const url = new URL(href);
    // Strip www. prefix for matching
    return url.hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

// Retrieve cached sources or fetch fresh from WTF API
async function getSources() {
  return new Promise((resolve) => {
    chrome.storage.local.get([CACHE_KEY], (result) => {
      const cached = result[CACHE_KEY];
      if (
        cached &&
        cached.timestamp &&
        Date.now() - cached.timestamp < CACHE_TTL_MS
      ) {
        resolve(cached.data);
        return;
      }

      // Cache miss or stale — fetch fresh
      fetch(WTF_API_URL)
        .then((r) => r.json())
        .then((data) => {
          // data expected: { sources: [{ domain, bias_score, outlet_name }, ...] }
          const sources = data.sources || data || [];
          chrome.storage.local.set({
            [CACHE_KEY]: { timestamp: Date.now(), data: sources },
          });
          resolve(sources);
        })
        .catch((err) => {
          console.warn("[WTF Bias] Failed to fetch sources:", err);
          // Return cached stale data if available, else empty
          resolve(cached ? cached.data : []);
        });
    });
  });
}

// Build a lookup map: domain → { score, lean }
function buildBiasMap(sources) {
  const map = {};
  for (const src of sources) {
    if (src.domain) {
      // Normalise domain
      const domain = src.domain.replace(/^www\./, "").toLowerCase();
      map[domain] = {
        score: src.bias_score ?? src.avg_score ?? null,
        lean: src.bias_lean ?? null,
      };
    }
  }
  return map;
}

// Inject a badge dot next to a link element
function injectBadge(linkEl, biasClass, outletName, score) {
  // Don't double-badge
  if (linkEl.dataset.wtfBadged) return;
  linkEl.dataset.wtfBadged = "1";

  const badge = document.createElement("span");
  badge.className = `wtf-bias-badge ${biasClass}`;

  // Tooltip text
  const direction =
    biasClass === "wtf-bias-left"
      ? "Left-leaning"
      : biasClass === "wtf-bias-right"
      ? "Right-leaning"
      : biasClass === "wtf-bias-centre"
      ? "Centre / Balanced"
      : "Unrated";

  const scoreStr =
    score !== null && score !== undefined ? ` (${score.toFixed(2)})` : "";
  badge.title = `${outletName || "Unknown"}: ${direction}${scoreStr} — What The Fact`;

  // Insert immediately after the link
  linkEl.insertAdjacentElement("afterend", badge);
}

// Scan all links in the document and badge matching ones
async function scanLinks(biasMap, sourcesArray) {
  // Build a name lookup too
  const nameMap = {};
  for (const src of sourcesArray) {
    if (src.domain) {
      const d = src.domain.replace(/^www\./, "").toLowerCase();
      nameMap[d] = src.outlet_name || src.name || d;
    }
  }

  const links = document.querySelectorAll("a[href]");
  for (const link of links) {
    const href = link.getAttribute("href");
    if (!href) continue;

    const domain = extractDomain(href);
    if (!domain) continue;

    // Check if it's a known Canadian news domain (fast-path)
    let matched = false;
    let matchedDomain = null;

    if (CANADIAN_NEWS_DOMAINS.has(domain)) {
      matched = true;
      matchedDomain = domain;
    } else {
      // Also check API-sourced domains not in our hardcoded list
      if (domain in biasMap) {
        matched = true;
        matchedDomain = domain;
      }
    }

    if (!matched) continue;

    const entry = biasMap[matchedDomain] || null;
    const score = entry ? entry.score ?? null : null;
    const lean = entry ? entry.lean ?? null : null;
    const biasClass = resolveBiasClass(score, lean);
    const outletName = nameMap[matchedDomain] || matchedDomain;

    injectBadge(link, biasClass, outletName, score);
  }
}

// Watch for dynamically injected links (SPAs like Twitter/X load content async)
function observeNewLinks(biasMap, sourcesArray) {
  const observer = new MutationObserver((mutations) => {
    let hasNewNodes = false;
    for (const mutation of mutations) {
      if (mutation.addedNodes.length > 0) {
        hasNewNodes = true;
        break;
      }
    }
    if (hasNewNodes) {
      // Debounce — coalesce rapid mutations
      clearTimeout(observer._timer);
      observer._timer = setTimeout(() => scanLinks(biasMap, sourcesArray), 300);
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });
}

// Entry point
(async () => {
  try {
    const sources = await getSources();
    const biasMap = buildBiasMap(sources);

    // Initial scan
    await scanLinks(biasMap, sources);

    // Watch for dynamic content
    observeNewLinks(biasMap, sources);
  } catch (err) {
    console.error("[WTF Bias] Content script error:", err);
  }
})();
