"""
Internal Channel state object for AudioEngine.

A Channel binds a never-reused channel id to its BASS stream handle plus
the bookkeeping the engine needs to manage that channel's lifecycle:
  - the original file path (logging, debugging)
  - the current state string (one of CHANNEL_STATES)
  - per-channel volume cache (0–100; mirrored to BASS via attribute write)
  - the SYNCPROC ref kept alive (ctypes callbacks GC otherwise)
  - the BASS sync handle (so we can BASS_ChannelRemoveSync on cleanup)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Allowed values for Channel.state. Mirrored on the wire by the
# AudioEngine.channel_state_changed signal.
CHANNEL_STATES = frozenset({
    "loaded", "playing", "paused", "stopped", "ended", "error",
})


@dataclass
class Channel:
    """Per-channel state. Only the engine should mutate these fields."""

    id: int                       # never-reused channel id
    handle: int                   # BASS stream handle
    file_path: str
    state: str = "loaded"         # one of CHANNEL_STATES
    volume: int = 100             # 0–100, mirrors BASS_ATTRIB_VOL
    sync_cb: Any = None           # ctypes SYNCPROC ref — must NOT be GC'd
    sync_handle: int = 0          # BASS sync handle (for RemoveSync)
    extras: dict = field(default_factory=dict)   # phase-specific scratchpad
