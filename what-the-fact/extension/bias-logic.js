/**
 * What The Fact — Bias Extension pure logic (#3328)
 *
 * No DOM and no chrome.* here — this file is loaded BEFORE content.js in the same
 * content-script isolated world (they share `globalThis`), and it is also require()-able
 * in Node for unit tests. Everything hangs off the `WTFBias` namespace.
 */
(function (root) {
  // Fast-path list of Canadian news domains. The live API (/api/edu/v1/sources) also
  // supplies domains dynamically; this list just guarantees coverage before the fetch lands.
  const CANADIAN_NEWS_DOMAINS = new Set([
    "cbc.ca",
    "ctv.ca",
    "ctvnews.ca",
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
    "macleans.ca",
    "thetyee.ca",
    "rabble.ca",
    "ipolitics.ca",
    "hilltimes.com",
    "theconversation.com",
    "canadaland.com",
    "westernstandard.ca",
    "torontosun.com",
    "cp24.com",
    "citynews.ca",
    "ici.radio-canada.ca",
    "aptnnews.ca",
    "bnnbloomberg.ca",
  ]);

  // Normalise a bias label to a lowercase, dash-separated form.
  function normLabel(label) {
    return String(label || "")
      .toLowerCase()
      .replace(/_/g, "-")
      .trim();
  }

  // Map a WTF bias label (a `band` or `bias_lean`: left / center-left / center /
  // center-right / right) to a 3-bucket badge CSS class. Returns null if unrecognised.
  function biasLabelToClass(label) {
    const l = normLabel(label);
    if (!l) return null;
    if (l === "left" || l === "center-left" || l === "centre-left") return "wtf-bias-left";
    if (l === "right" || l === "center-right" || l === "centre-right") return "wtf-bias-right";
    if (l === "center" || l === "centre" || l === "balanced" || l === "mixed") return "wtf-bias-centre";
    return null;
  }

  // Fallback: bucket the numeric avg_score (roughly -1..1) when no categorical label exists.
  function biasScoreToClass(score) {
    if (score === null || score === undefined) return "wtf-bias-unknown";
    const n = Number(score);
    if (Number.isNaN(n)) return "wtf-bias-unknown";
    if (n < -0.2) return "wtf-bias-left";
    if (n > 0.2) return "wtf-bias-right";
    return "wtf-bias-centre";
  }

  // Resolve the badge class for an outlet. Prefer WTF's computed `band` (consistent with
  // avg_score), then `bias_lean`, then the numeric score bucket. Never throws.
  function resolveBiasClass(band, lean, score) {
    return biasLabelToClass(band) || biasLabelToClass(lean) || biasScoreToClass(score);
  }

  // Extract a normalised root domain (www. stripped, lowercased) from an ABSOLUTE URL.
  // Returns null for relative links, javascript:/mailto:, or anything unparseable — those
  // are never external news links so they are correctly skipped.
  function extractDomain(href) {
    try {
      const u = new URL(href);
      if (u.protocol !== "http:" && u.protocol !== "https:") return null;
      return u.hostname.replace(/^www\./, "").toLowerCase();
    } catch {
      return null;
    }
  }

  // Build a lookup: domain -> { score, lean, band } from the API `sources` array.
  function buildBiasMap(sources) {
    const map = {};
    for (const src of sources || []) {
      if (!src || !src.domain) continue;
      const domain = String(src.domain).replace(/^www\./, "").toLowerCase();
      map[domain] = {
        score: src.avg_score ?? src.bias_score ?? null,
        lean: src.bias_lean ?? null,
        band: src.band ?? null,
      };
    }
    return map;
  }

  // Build a lookup: domain -> display name.
  function buildNameMap(sources) {
    const map = {};
    for (const src of sources || []) {
      if (!src || !src.domain) continue;
      const domain = String(src.domain).replace(/^www\./, "").toLowerCase();
      map[domain] = src.name || src.outlet_name || domain;
    }
    return map;
  }

  // Human-readable band label for the tooltip: "center-left" -> "Center-left".
  function formatBandLabel(band) {
    const l = normLabel(band);
    if (!l) return "Unrated";
    return l.charAt(0).toUpperCase() + l.slice(1);
  }

  // Short direction text keyed off the resolved badge class.
  function biasDirectionText(biasClass) {
    if (biasClass === "wtf-bias-left") return "Left-leaning";
    if (biasClass === "wtf-bias-right") return "Right-leaning";
    if (biasClass === "wtf-bias-centre") return "Centre / Balanced";
    return "Unrated";
  }

  // URL shorteners whose href hides the real outlet. X/Twitter rewrites EVERY external
  // link to t.co/..., so a t.co href can't be domain-matched — but the real domain is in
  // the link's visible text (see extractDomainFromText). (#4671)
  const SHORTENER_DOMAINS = new Set([
    "t.co",
    "bit.ly",
    "trib.al",
    "dlvr.it",
    "ow.ly",
    "buff.ly",
  ]);

  // Pull an outlet domain out of a link's DISPLAY text. On X an external link renders its
  // expanded URL as the text, e.g. "nytimes.com/2024/…" or "https://www.cbc.ca/news".
  // Returns the bare hostname ("nytimes.com") or null if the text isn't a URL. (#4671)
  function extractDomainFromText(text) {
    if (!text) return null;
    const token = String(text)
      .trim()
      .split(/\s/)[0]
      .replace(/^https?:\/\//i, "");
    const host = token.split("/")[0].replace(/^www\./i, "").toLowerCase();
    // Must look like a real domain: labels + a 2+ char alpha TLD (rejects "…", "1.2", etc.).
    if (/^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(host) && /\.[a-z]{2,}$/.test(host)) {
      return host;
    }
    return null;
  }

  root.WTFBias = {
    CANADIAN_NEWS_DOMAINS,
    SHORTENER_DOMAINS,
    biasLabelToClass,
    biasScoreToClass,
    resolveBiasClass,
    extractDomain,
    extractDomainFromText,
    buildBiasMap,
    buildNameMap,
    formatBandLabel,
    biasDirectionText,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);

if (typeof module !== "undefined" && module.exports) {
  module.exports = (typeof globalThis !== "undefined" ? globalThis : this).WTFBias;
}
