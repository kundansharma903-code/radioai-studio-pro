"""
RadioAI Studio Pro — Scheduler
Jazler SOHO-style 2-hour queue builder.
Wraps AutoScheduler and exposes a simple interface to the UI.
"""

import logging
import threading
from datetime import datetime
from typing import List, Optional

from core.auto_scheduler import AutoScheduler

log = logging.getLogger("Scheduler")


class Scheduler:
    """2-hour pre-load queue manager."""

    def __init__(self, db):
        self._db = db
        self._auto = AutoScheduler(db)
        self._queue: List[dict] = []
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def build_queue(self, hours: int = 2) -> List[dict]:
        """Build (or rebuild) the play queue for the next *hours* hours."""
        items_needed = hours * 12  # ~5 min per song → 12/hour estimate
        queue = self._auto.build_queue(max_items=items_needed)
        with self._lock:
            self._queue = queue
        log.info(f"Queue built: {len(queue)} items for {hours}h")
        self.queue_snapshot  # log detail
        return queue

    def get_queue(self) -> List[dict]:
        with self._lock:
            return list(self._queue)

    def pop_next(self) -> Optional[dict]:
        """Remove and return the first item from the queue."""
        with self._lock:
            if self._queue:
                return self._queue.pop(0)
        return None

    def peek_next(self) -> Optional[dict]:
        """Return the first item without removing it."""
        with self._lock:
            return self._queue[0] if self._queue else None

    def queue_length(self) -> int:
        with self._lock:
            return len(self._queue)

    def needs_refill(self, min_items: int = 6) -> bool:
        return self.queue_length() < min_items

    def get_clock_info(self) -> Optional[dict]:
        """Return info about the currently active clock."""
        return self._auto.get_current_clock()

    @property
    def queue_snapshot(self) -> str:
        """One-line summary for logging."""
        q = self.get_queue()
        if not q:
            return "Queue: empty"
        titles = [f"{i['artist'][:12]}/{i['title'][:12]}" for i in q[:4]]
        return f"Queue({len(q)}): {' | '.join(titles)}{'…' if len(q) > 4 else ''}"
