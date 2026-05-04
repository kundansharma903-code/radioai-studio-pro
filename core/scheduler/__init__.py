"""
RadioAI Studio Pro — Scheduler package (Phase D3+).

Public API:
  SchedulerEngine    — background QThread broadcaster (1Hz tick)
  EventType          — enum of scheduled event types
  ScheduledEvent     — dataclass for queued events

Phase D3 scope: infrastructure only. The engine starts/stops cleanly
on its own QThread, ticks at 1Hz, but `_on_tick` is empty.

  D4 will fill in spot triggering (campaign_schedule → spot_due signal).
  D5 will fill in song queue auto-advance.

Lifecycle contract (matches AudioEngine pattern):
  - Caller MUST invoke stop() before app shutdown
  - MainWindow.closeEvent / aboutToQuit BOTH call stop() (idempotent)
  - stop() is called BEFORE AudioEngine.cleanup_all() — silence the
    event source first, then tear down audio
"""

from core.scheduler.engine import SchedulerEngine
from core.scheduler.events import EventType, ScheduledEvent

__all__ = ["SchedulerEngine", "EventType", "ScheduledEvent"]
