"""
Obsidian Vault File Watcher
Real-time file system monitoring for vault changes

Purpose:
- Monitor /mnt/archie_brain/knowledge/ for file changes
- Detect CREATE, MODIFY, DELETE, MOVE events for .md files
- Debounce rapid changes (Obsidian auto-saves frequently)
- Trigger knowledge base re-indexing on changes
- Log all events to vault_sync_log table

Pattern: Background thread-based worker (similar to git_commit_poller.py)

Author: A.R.C.H.I.E. Platform
Date: 2026-01-08
"""
import os
import time
import threading
from datetime import datetime
from typing import Dict, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent


class VaultEventHandler(FileSystemEventHandler):
    """Handles file system events for vault directory"""

    def __init__(self, watcher):
        self.watcher = watcher
        super().__init__()

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory and event.src_path.endswith('.md'):
            self.watcher._queue_event('CREATE', event.src_path)

    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory and event.src_path.endswith('.md'):
            self.watcher._queue_event('MODIFY', event.src_path)

    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory and event.src_path.endswith('.md'):
            self.watcher._queue_event('DELETE', event.src_path)

    def on_moved(self, event: FileSystemEvent):
        if not event.is_directory and event.src_path.endswith('.md'):
            self.watcher._queue_event('MOVE', event.src_path, event.dest_path)


class ObsidianVaultWatcher:
    """Monitors Obsidian vault for file changes"""

    def __init__(
        self,
        vault_path: str = '/mnt/archie_brain/knowledge/',
        debounce_delay: float = 2.0,
        enabled: bool = True
    ):
        self.vault_path = vault_path
        self.debounce_delay = debounce_delay
        self.enabled = enabled

        self.running = False
        self.observer = None
        self.event_queue = {}  # file_path -> (event_type, timestamp, dest_path)
        self.queue_lock = threading.Lock()
        self.processor_thread = None

        # Statistics
        self.events_detected = 0
        self.events_processed = 0
        self.last_event_time = None

    def start(self):
        """Start the file watcher in background thread"""
        if self.running:
            print("[Vault Watcher] Already running")
            return

        if not self.enabled:
            print("[Vault Watcher] Disabled, not starting")
            return

        if not os.path.exists(self.vault_path):
            print(f"[Vault Watcher] Vault path does not exist: {self.vault_path}")
            return

        print(f"[Vault Watcher] Starting (debounce: {self.debounce_delay}s)")

        self.running = True

        # Start watchdog observer
        event_handler = VaultEventHandler(self)
        self.observer = Observer()
        self.observer.schedule(event_handler, self.vault_path, recursive=True)
        self.observer.start()

        # Start event processor thread
        self.processor_thread = threading.Thread(
            target=self._process_events_loop,
            daemon=True,
            name="VaultEventProcessor"
        )
        self.processor_thread.start()

        print("[Vault Watcher] Started successfully")

    def stop(self):
        """Gracefully stop the file watcher"""
        if not self.running:
            return

        print("[Vault Watcher] Stopping...")
        self.running = False

        # Stop observer
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=5.0)

        # Wait for processor thread
        if self.processor_thread:
            self.processor_thread.join(timeout=5.0)

        print("[Vault Watcher] Stopped")

    def _queue_event(
        self,
        event_type: str,
        file_path: str,
        dest_path: Optional[str] = None
    ):
        """
        Queue a file system event with debouncing

        Args:
            event_type: CREATE, MODIFY, DELETE, MOVE
            file_path: Source file path
            dest_path: Destination path (for MOVE events)
        """
        # Filter out temporary files
        if self._is_temp_file(file_path):
            return

        with self.queue_lock:
            # Update or add event (most recent wins)
            self.event_queue[file_path] = (
                event_type,
                time.time(),
                dest_path
            )
            self.events_detected += 1
            self.last_event_time = datetime.now()

    def _is_temp_file(self, file_path: str) -> bool:
        """Check if file is temporary (ignore these)"""
        filename = os.path.basename(file_path)
        temp_patterns = ['.tmp', '.swp', '~', '.bak']
        return any(filename.endswith(pattern) for pattern in temp_patterns)

    def _process_events_loop(self):
        """Main event processing loop (runs in background thread)"""
        while self.running:
            try:
                time.sleep(0.5)  # Check queue every 500ms

                # Get events ready for processing (debounced)
                ready_events = self._get_ready_events()

                if ready_events:
                    for file_path, (event_type, _, dest_path) in ready_events.items():
                        self._handle_event(event_type, file_path, dest_path)

            except Exception as e:
                print(f"[Vault Watcher] Error in processing loop: {e}")

    def _get_ready_events(self) -> Dict:
        """Get events that have passed debounce delay"""
        ready = {}
        current_time = time.time()

        with self.queue_lock:
            to_remove = []

            for file_path, (event_type, timestamp, dest_path) in self.event_queue.items():
                # Check if debounce delay has passed
                if current_time - timestamp >= self.debounce_delay:
                    ready[file_path] = (event_type, timestamp, dest_path)
                    to_remove.append(file_path)

            # Remove processed events from queue
            for file_path in to_remove:
                del self.event_queue[file_path]

        return ready

    def _handle_event(
        self,
        event_type: str,
        file_path: str,
        dest_path: Optional[str] = None
    ):
        """
        Handle a debounced file system event

        Args:
            event_type: CREATE, MODIFY, DELETE, MOVE
            file_path: Source file path
            dest_path: Destination path (for MOVE events)
        """
        try:
            print(f"[Vault Watcher] {event_type}: {os.path.basename(file_path)}")

            # Trigger re-indexing
            self._trigger_reindex(event_type, file_path, dest_path)

            # Log to database
            self._log_sync_event(event_type, file_path, 'success')

            self.events_processed += 1

        except Exception as e:
            print(f"[Vault Watcher] Error handling {event_type} for {file_path}: {e}")
            self._log_sync_event(event_type, file_path, 'error', str(e))

    def _trigger_reindex(
        self,
        event_type: str,
        file_path: str,
        dest_path: Optional[str] = None
    ):
        """
        Trigger knowledge base re-indexing

        Args:
            event_type: Event type
            file_path: File path
            dest_path: Destination path (for MOVE)
        """
        # Import here to avoid circular dependency
        try:
            from knowledge_vault_indexer import reindex_note

            if event_type in ['CREATE', 'MODIFY']:
                reindex_note(file_path)
            elif event_type == 'DELETE':
                # Remove from knowledge base
                print(f"[Vault Watcher] Note deleted: {file_path}")
                # TODO: Call knowledge base delete function
            elif event_type == 'MOVE':
                # Re-index at new location
                if dest_path:
                    reindex_note(dest_path)

        except ImportError:
            # Indexer not yet implemented
            print(f"[Vault Watcher] Indexer not available, skipping re-index")
        except Exception as e:
            print(f"[Vault Watcher] Re-index error: {e}")

    def _log_sync_event(
        self,
        event_type: str,
        file_path: str,
        status: str,
        error_message: Optional[str] = None
    ):
        """
        Log sync event to database

        Args:
            event_type: Event type
            file_path: File path
            status: success or error
            error_message: Error message if status is error
        """
        try:
            from database import db

            query = """
                INSERT INTO vault_sync_log
                (event_type, file_path, status, error_message, processed_at)
                VALUES (%s, %s, %s, %s, %s)
            """

            with db.engine.connect() as conn:
                conn.execute(
                    db.text(query),
                    (event_type, file_path, status, error_message, datetime.now())
                )
                conn.commit()

        except Exception as e:
            print(f"[Vault Watcher] Failed to log sync event: {e}")

    def get_status(self) -> Dict:
        """Get watcher status"""
        return {
            'running': self.running,
            'vault_path': self.vault_path,
            'debounce_delay': self.debounce_delay,
            'events_detected': self.events_detected,
            'events_processed': self.events_processed,
            'queued_events': len(self.event_queue),
            'last_event_time': self.last_event_time.isoformat() if self.last_event_time else None
        }


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

_watcher_instance = None


def get_watcher() -> ObsidianVaultWatcher:
    """Get or create global watcher instance"""
    global _watcher_instance
    if _watcher_instance is None:
        _watcher_instance = ObsidianVaultWatcher()
    return _watcher_instance


def get_watcher_status() -> Dict:
    """Get status of global watcher instance"""
    watcher = get_watcher()
    return watcher.get_status()


def start_watcher():
    """Start global watcher instance"""
    watcher = get_watcher()
    watcher.start()


def stop_watcher():
    """Stop global watcher instance"""
    watcher = get_watcher()
    watcher.stop()


# ============================================================================
# TESTING
# ============================================================================

if __name__ == '__main__':
    print("=== Obsidian Vault Watcher Test ===\n")

    # Create test watcher
    watcher = ObsidianVaultWatcher(
        vault_path='/mnt/archie_brain/knowledge/',
        debounce_delay=2.0
    )

    # Start watcher
    watcher.start()

    print("\nWatcher is running. Monitoring vault for changes...")
    print("Try creating, modifying, or deleting notes in /mnt/archie_brain/knowledge/")
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            time.sleep(5)
            status = watcher.get_status()
            print(f"[Status] Events: {status['events_detected']} detected, "
                  f"{status['events_processed']} processed, "
                  f"{status['queued_events']} queued")
    except KeyboardInterrupt:
        print("\n\nStopping watcher...")
        watcher.stop()
        print("Watcher stopped successfully")
