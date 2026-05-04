"""
RadioAI Studio Pro — Audio package (multi-channel BASS engine).

Public API:
  AudioEngine            — multi-channel player (QObject with pyqtSignals)
  AudioEngineError       — base error
  ChannelError           — invalid channel id / state
  FormatError            — unsupported format / decode error

BASS lifecycle (BASS_Init / BASS_Free) is NOT owned by this package — it
remains in main.py via core.audio_engine.bass_init / bass_free, the canonical
single-process BASS device. The new AudioEngine consumes that device.

Coexistence: `core.audio_engine.AudioEngine` (legacy single-deck, unwired)
remains untouched in Phase A. Phase B will pick a winner.
"""

from core.audio.engine import AudioEngine
from core.audio.exceptions import (
    AudioEngineError, ChannelError, FormatError,
)

__all__ = [
    "AudioEngine",
    "AudioEngineError", "ChannelError", "FormatError",
]
