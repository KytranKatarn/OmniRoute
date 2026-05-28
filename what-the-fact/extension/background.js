/**
 * What The Fact — Background Service Worker
 * T3014: Bias Ratings on Social Media
 *
 * Refreshes the WTF outlet bias sources cache every 6 hours
 * so content scripts always have fresh data without hitting the
 * API on every page load.
 */

const WTF_API_URL = "https://what-the-fact.com/api/edu/v1/sources";
const CACHE_KEY = "wtf_bias_sources_cache";
const CACHE_TTL_MS = 6 * 60 * 60 * 1000; // 6 hours
const ALARM_NAME = "wtf_refresh_sources";

// Fetch and store sources in chrome.storage.local
async function refreshSources() {
  try {
    const response = await fetch(WTF_API_URL);
    if (!response.ok) {
      console.warn(`[WTF Bias BG] API returned ${response.status}`);
      return;
    }
    const data = await response.json();
    const sources = data.sources || data || [];
    await chrome.storage.local.set({
      [CACHE_KEY]: { timestamp: Date.now(), data: sources },
    });
    console.log(
      `[WTF Bias BG] Refreshed ${sources.length} outlet bias records`
    );
  } catch (err) {
    console.error("[WTF Bias BG] Failed to refresh sources:", err);
  }
}

// On install/update: seed cache immediately and register 6h alarm
chrome.runtime.onInstalled.addListener(async () => {
  await refreshSources();

  // Clear any existing alarm before creating a new one
  await chrome.alarms.clear(ALARM_NAME);
  chrome.alarms.create(ALARM_NAME, {
    periodInMinutes: 360, // 6 hours
  });
});

// On browser startup: check if cache is stale and refresh if needed
chrome.runtime.onStartup.addListener(async () => {
  const result = await chrome.storage.local.get([CACHE_KEY]);
  const cached = result[CACHE_KEY];
  if (!cached || Date.now() - cached.timestamp > CACHE_TTL_MS) {
    await refreshSources();
  }
});

// Alarm handler — periodic refresh
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    refreshSources();
  }
});
