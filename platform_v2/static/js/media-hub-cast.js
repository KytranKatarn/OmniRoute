/**
 * media-hub-cast.js — Google Chromecast integration for Media Hub (T3302)
 *
 * Loads after media-hub.js. Integrates with the existing openVideoPlayer()
 * flow: when a video is playing the cast button appears and allows the user
 * to send the stream to any Chromecast on the LAN.
 *
 * Cast SDK is Chrome/Edge only — the __onGCastApiAvailable callback never
 * fires on Firefox/Safari, so this file is a safe no-op on those browsers.
 *
 * Architecture:
 *   Browser → /api/cast/stream-url → returns LAN URL (192.168.1.200:<jellyfin_port>)
 *   Browser → Chromecast SDK → Chromecast fetches LAN URL directly
 *
 * The LAN URL is used because:
 *   1. Chromecast is on the same 192.168.1.x network as the hub
 *   2. External subdomain (media.kytranempowerment.com) hits Hostinger CDN
 *      which has a 60 s timeout — video streams would be cut off
 *   3. Docker-internal hostnames (e.g. 'media_jellyfin') are not reachable
 *      from the Chromecast device
 */

(function () {
    'use strict';

    const CAST_APP_ID = 'CC1AD845'; // Default Media Receiver — no registration needed
    const CAST_API_BASE = '/tools/media-hub/api/cast';

    // Tracks the item currently loaded in the video player modal
    let _currentCastItem = null;

    // -------------------------------------------------------------------------
    // SDK availability callback — set BEFORE the SDK script tag executes
    // -------------------------------------------------------------------------
    window['__onGCastApiAvailable'] = function (isAvailable) {
        if (!isAvailable) return;

        try {
            cast.framework.CastContext.getInstance().setOptions({
                receiverApplicationId: CAST_APP_ID,
                autoJoinPolicy: chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED,
            });

            // Show/hide the cast controls based on device availability
            const ctx = cast.framework.CastContext.getInstance();
            ctx.addEventListener(
                cast.framework.CastContextEventType.CAST_STATE_CHANGED,
                _onCastStateChanged
            );
        } catch (e) {
            console.warn('[Cast] SDK init error:', e);
        }
    };

    function _onCastStateChanged(e) {
        const controls = document.getElementById('videoCastControls');
        if (!controls) return;

        const noDevices = e.castState === cast.framework.CastState.NO_DEVICES_AVAILABLE;
        // Only show cast controls when the video player modal is active
        const playerActive = document.getElementById('videoPlayerModal')?.classList.contains('active');
        controls.style.display = (noDevices || !playerActive) ? 'none' : 'flex';
    }

    // -------------------------------------------------------------------------
    // Public API — called from media-hub.js when the player opens/closes
    // -------------------------------------------------------------------------

    /**
     * Call this when openVideoPlayer() succeeds so cast knows what's playing.
     * Exposes the item to the cast button handler and shows cast controls if
     * a Chromecast device is available.
     *
     * @param {Object} item  — same item object passed to openVideoPlayer()
     */
    window.castSetCurrentItem = function (item) {
        _currentCastItem = item;
        _refreshCastControlsVisibility();
    };

    /**
     * Call this when closeVideoPlayer() runs so we hide the cast controls.
     */
    window.castClearCurrentItem = function () {
        _currentCastItem = null;
        const controls = document.getElementById('videoCastControls');
        if (controls) controls.style.display = 'none';
    };

    function _refreshCastControlsVisibility() {
        if (!_isCastAvailable()) return;
        const controls = document.getElementById('videoCastControls');
        if (controls && _currentCastItem) {
            controls.style.display = 'flex';
        }
    }

    function _isCastAvailable() {
        try {
            const state = cast.framework.CastContext.getInstance().getCastState();
            return state !== cast.framework.CastState.NO_DEVICES_AVAILABLE;
        } catch (e) {
            return false;
        }
    }

    // -------------------------------------------------------------------------
    // Cast launcher click handler
    // -------------------------------------------------------------------------
    // The <google-cast-launcher> element handles session request automatically.
    // We hook into SESSION_STATE_CHANGED so we can load media once connected.

    document.addEventListener('DOMContentLoaded', function () {
        const ctx = _getCastContext();
        if (!ctx) return; // SDK not available (Firefox/Safari)

        ctx.addEventListener(
            cast.framework.CastContextEventType.SESSION_STATE_CHANGED,
            function (e) {
                const resumed =
                    e.sessionState === cast.framework.SessionState.SESSION_RESUMED;
                const started =
                    e.sessionState === cast.framework.SessionState.SESSION_STARTED;

                if ((started || resumed) && _currentCastItem) {
                    _loadMediaOnCast(_currentCastItem);
                }
            }
        );
    });

    function _getCastContext() {
        try {
            return cast.framework.CastContext.getInstance();
        } catch (e) {
            return null;
        }
    }

    // -------------------------------------------------------------------------
    // Load media on the connected Chromecast
    // -------------------------------------------------------------------------

    async function _loadMediaOnCast(item) {
        const session = _getCastContext()?.getCurrentSession();
        if (!session) {
            console.warn('[Cast] No active session to load media into');
            return;
        }

        try {
            // Build query params mirroring openVideoPlayer's stream fetch
            const params = new URLSearchParams({ item_id: item.id });
            if (item.title) params.set('title', item.title);
            if (item.year) params.set('year', item.year);
            if (item.media_type) params.set('type', item.media_type);
            if (item.media_type === 'episode') {
                const showTitle = item.metadata?.show_title || item.show_title;
                if (showTitle) params.set('show_title', showTitle);
                if (item.season_number !== undefined) params.set('season', item.season_number);
                if (item.episode_number !== undefined) params.set('episode', item.episode_number);
            }

            const resp = await fetch(`${CAST_API_BASE}/stream-url?${params.toString()}`);
            const data = await resp.json();

            if (!data.success) {
                _showCastToast('Cast error: ' + (data.error || 'Unknown error'));
                return;
            }

            const contentType = data.container === 'm3u8'
                ? 'application/x-mpegURL'
                : 'video/mp4';

            const mediaInfo = new chrome.cast.media.MediaInfo(data.url, contentType);
            mediaInfo.metadata = new chrome.cast.media.MovieMediaMetadata();
            mediaInfo.metadata.title = data.title || item.title || 'Media Hub';

            if (data.poster) {
                mediaInfo.metadata.images = [new chrome.cast.Image(data.poster)];
            }

            const loadRequest = new chrome.cast.media.LoadRequest(mediaInfo);
            await session.loadMedia(loadRequest);

            _showCastToast('Casting to TV...');
        } catch (err) {
            console.error('[Cast] loadMedia error:', err);
            _showCastToast('Cast failed: ' + err.message);
        }
    }

    // -------------------------------------------------------------------------
    // Utility
    // -------------------------------------------------------------------------

    function _showCastToast(msg) {
        // Reuse the existing showToast() from media-hub.js if available
        if (typeof window.showToast === 'function') {
            window.showToast(msg, 'info');
        } else {
            console.info('[Cast]', msg);
        }
    }

})();
