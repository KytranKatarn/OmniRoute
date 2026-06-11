import logging
import os
import threading
import time

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

POOL_SIZE = int(os.getenv("SCOUT_POOL_SIZE", "3"))

SLOT_PROXIES: dict[int, str | None] = {
    0: None,
    1: os.getenv("SCOUT_VPS_SOCKS") or None,
    2: os.getenv("SCOUT_PROXY_URL") or None,
}


class BrowserPool:
    """
    Thread-safe browser slot pool.

    Playwright's sync API ties every object (Playwright, Browser, Context, Page)
    to the OS thread + greenlet that created it.  Nothing can cross thread
    boundaries.

    Solution: this class only manages *slot reservation* (a counter + lock).
    The actual Playwright launch / browser / context / page are all created
    inside the worker thread that calls claim(), via a thread-local
    sync_playwright() session.  release() tears down everything in the same
    thread before marking the slot free.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._slots: dict[int, str] = {i: "free" for i in range(self.size)}
        # thread-local storage: each worker thread keeps its own pw/browser/context/page
        self._tls = threading.local()
        # fleet_labels: slot_id -> node label (for dynamic fleet egress slots)
        self._fleet_labels: dict[int, str] = {}
        # slot_proxy: slot_id -> proxy string (overrides SLOT_PROXIES for fleet slots)
        self._slot_proxy: dict[int, str | None] = {}
        # Emit "ready" log lines so startup looks the same as before
        for slot_id in range(self.size):
            proxy = SLOT_PROXIES.get(slot_id)
            logger.info("Pool slot %d ready (proxy=%s)", slot_id, proxy or "direct")
        self._start_fleet_refresh()

    # ------------------------------------------------------------------
    # Internal: per-thread Playwright lifecycle
    # ------------------------------------------------------------------

    def _tls_start(self) -> None:
        """Start a Playwright instance in the current thread (idempotent)."""
        if not getattr(self._tls, "pw", None):
            self._tls.pw = sync_playwright().start()
            self._tls.browser = self._tls.pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            self._tls.context = None
            self._tls.page = None

    def _tls_open_page(self, proxy: str | None):
        """Open a fresh context+page in the current thread."""
        ctx_opts: dict = {"viewport": {"width": 1280, "height": 800}}
        if proxy:
            ctx_opts["proxy"] = {"server": proxy}
        self._tls.context = self._tls.browser.new_context(**ctx_opts)
        self._tls.page = self._tls.context.new_page()
        return self._tls.page

    def _tls_close_page(self) -> None:
        """Close current context+page but keep browser alive for reuse."""
        try:
            if self._tls.page:
                self._tls.page.close()
        except Exception:
            pass
        try:
            if self._tls.context:
                self._tls.context.close()
        except Exception:
            pass
        self._tls.page = None
        self._tls.context = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def claim(self, egress_tier: int = 1, proxy_override: str | None = None) -> tuple[int, any]:
        """
        Reserve a slot and return (slot_id, page).
        Must be called from the thread that will USE the page.

        proxy_override (#4007): when set, the page opens through THAT proxy
        regardless of the slot's tier mapping — this is how per-session
        browse-from-country egress reaches a specific outpost's SOCKS5 without
        depending on the tier→slot fleet machinery. The slot is still reserved
        for concurrency control. None = unchanged tier-based behaviour.
        """
        preferred = max(0, min(egress_tier - 1, self.size - 1))
        order = [preferred] + [i for i in range(self.size) if i != preferred]

        # Step 1: acquire slot under lock only — no Playwright I/O inside lock
        slot_id = None
        with self._lock:
            for sid in order:
                if self._slots[sid] == "free":
                    self._slots[sid] = "busy"
                    slot_id = sid
                    break

        if slot_id is None:
            raise RuntimeError("No browser slots available — all busy")

        # Step 2: open page OUTSIDE the lock so Playwright I/O doesn't block other claims
        try:
            self._tls_start()
            if proxy_override is not None:
                proxy = proxy_override
            else:
                # Fleet slots override SLOT_PROXIES; static slots fall back to SLOT_PROXIES
                proxy = self._slot_proxy.get(slot_id, SLOT_PROXIES.get(slot_id))
            page = self._tls_open_page(proxy)
            return slot_id, page
        except Exception:
            # Reset slot so it's not permanently stuck as "busy"
            with self._lock:
                self._slots[slot_id] = "free"
            raise

    def release(self, slot_id: int, page: any) -> None:  # noqa: ARG002
        """Close page/context in the current thread, mark slot free."""
        self._tls_close_page()
        with self._lock:
            self._slots[slot_id] = "free"

    def available_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._slots.values() if s == "free")

    def status(self) -> dict:
        with self._lock:
            return {"pool_size": self.size, "slots": dict(self._slots)}

    def _refresh_fleet_slots(self) -> None:
        """Register/deregister fleet node egress slots based on remote_nodes."""
        from proxy_selector import discover_fleet_egress

        fleet_nodes = discover_fleet_egress()
        fleet_proxies = {n["label"]: n["proxy"] for n in fleet_nodes}

        with self._lock:
            # Remove stale fleet slots
            stale = [
                slot_id
                for slot_id, label in self._fleet_labels.items()
                if label not in fleet_proxies
            ]
            for slot_id in stale:
                self._slots.pop(slot_id, None)
                self._slot_proxy.pop(slot_id, None)
                self._fleet_labels.pop(slot_id, None)
                logger.info("Fleet slot %d removed (node offline)", slot_id)

            # Add new fleet slots (slot tracking only — TLS init on first claim)
            existing_labels = set(self._fleet_labels.values())
            next_id = (max(self._slots.keys(), default=self.size - 1) + 1)
            for label, proxy in fleet_proxies.items():
                if label not in existing_labels:
                    self._slots[next_id] = "free"
                    self._slot_proxy[next_id] = proxy
                    self._fleet_labels[next_id] = label
                    logger.info("Fleet slot %d added: %s (%s)", next_id, label, proxy)
                    next_id += 1

    def _start_fleet_refresh(self) -> None:
        """Background thread: refresh fleet node egress slots every 5 minutes."""
        def _loop():
            while True:
                time.sleep(300)
                try:
                    self._refresh_fleet_slots()
                except Exception as exc:
                    logger.warning("Fleet refresh error: %s", exc)

        t = threading.Thread(target=_loop, daemon=True, name="fleet-egress-refresh")
        t.start()
        logger.info("Fleet egress refresh started (5min interval)")

    @property
    def size(self) -> int:
        return POOL_SIZE
