"""
Scheduler event types.

Used internally by SchedulerEngine to queue future actions. D4 + D5
populate the queue from DB state (campaign_schedule rows, song queue
state). D3 defines the shapes only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EventType(str, Enum):
    """Event types emitted by the scheduler.

    Each value also matches a public pyqtSignal name on SchedulerEngine.
    Keep them in sync.
    """

    SPOT_DUE          = "spot_due"           # campaign_id should air at break_time
    SONG_AUTO_ADVANCE = "song_auto_advance"  # current ended; queue next
    BREAK_APPROACHING = "break_approaching"  # 30s warning before break
    SCHEDULE_RELOAD   = "schedule_reload"    # DB updated, refresh state


@dataclass
class ScheduledEvent:
    """A future action queued by the scheduler.

    Fields:
        type:      EventType — what to do
        payload:   dict — event-specific data (campaign_id, song_id, ...)
        fires_at:  monotonic seconds (time.monotonic()) — when to dispatch.
                   Past-due events fire on the next tick.
    """

    type:     EventType
    fires_at: float
    payload:  dict = field(default_factory=dict)
