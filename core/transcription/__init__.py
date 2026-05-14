"""
RadioAI Studio Pro — Transcription adapters.

Each adapter exposes a ``transcribe(audio_path) -> str`` method that
returns a 4-line English summary of the audio content. Adapters are
swappable behind a common base class — the active one is selected by
``Settings().get("sotg_ai_active_provider")``.

Adapters are pure HTTP clients (urllib stdlib only, no extra pip
deps) so packaging stays minimal.
"""

from core.transcription.base import (
    TranscriptionAdapter,
    TranscriptionError,
    TranscriptionTimeout,
    SUMMARY_PROMPT,
    MAX_AUDIO_BYTES,
)
from core.transcription.gemini_adapter import GeminiAdapter
from core.transcription.openai_adapter import OpenAIAdapter

__all__ = [
    "TranscriptionAdapter",
    "TranscriptionError",
    "TranscriptionTimeout",
    "GeminiAdapter",
    "OpenAIAdapter",
    "SUMMARY_PROMPT",
    "MAX_AUDIO_BYTES",
    "build_adapter",
]


def build_adapter(provider: str, api_key: str,
                   model: str = "") -> TranscriptionAdapter:
    """Factory — returns the right adapter for the configured provider.
    Raises ValueError on unknown provider."""
    p = (provider or "").lower().strip()
    if p == "gemini":
        return GeminiAdapter(api_key=api_key,
                              model=model or "gemini-2.5-flash")
    if p == "openai":
        return OpenAIAdapter(api_key=api_key,
                              model=model or "gpt-4o-mini")
    raise ValueError(f"unknown transcription provider: {provider!r}")
