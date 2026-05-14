"""
Shared base class + constants for the transcription adapter family.

The contract every adapter honours:

  adapter.transcribe(audio_path, link_context=None) -> str

Returns a 4-line English summary (each line ≤ 90 chars). Raises
``TranscriptionError`` on any failure the engine should surface to
the operator (bad key, quota exhausted, 5xx after retries, malformed
response). Raises ``TranscriptionTimeout`` specifically for timeout
paths so the engine can choose to retry vs abandon.

Adapters MUST NOT log API keys or audio content. They MAY log
provider name + model + duration metadata.

Adapters MUST validate audio file size against ``MAX_AUDIO_BYTES``
(20 MB — Gemini's inline limit, comfortable headroom for typical
30-second SOTG drops which are ~500 KB). Larger files raise
``TranscriptionError("file too large …")`` and the engine stamps
SKIPPED rather than retrying.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("Transcription")


# ── Constants ──────────────────────────────────────────────────────────────

MAX_AUDIO_BYTES = 20 * 1024 * 1024     # 20 MB — Gemini inline limit
HTTP_TIMEOUT_S = 60                     # per-request timeout
RETRY_ATTEMPTS = 2                      # additional tries after first failure
RETRY_BACKOFF_S = 1.5                   # base backoff (multiplied by attempt)

# Prompt template — used by every provider so the 4-line shape stays
# consistent across Gemini's audio path AND OpenAI's STT→summary
# 2-call pipeline.
SUMMARY_PROMPT = (
    "You are summarising a short radio broadcast clip (Hindi-English mix). "
    "Output EXACTLY 4 lines in plain English, each ≤ 90 characters, "
    "no markdown, no preamble, no trailing notes:\n"
    "  Line 1 — Topic: <subject of the segment>\n"
    "  Line 2 — Insight: <key message or insight the RJ shared>\n"
    "  Line 3 — Quote: <notable phrase / detail mentioned (in quotes)>\n"
    "  Line 4 — Call-to-action: <listener instruction or '—' if none>\n"
)


# ── Exceptions ─────────────────────────────────────────────────────────────


class TranscriptionError(RuntimeError):
    """Adapter-level failure — bad key, 4xx/5xx after retries, malformed
    response. Engine surfaces this as ai_status = FAILED."""


class TranscriptionTimeout(TranscriptionError):
    """Timeout-specific subclass — engine MAY choose retry policy
    differently for timeouts."""


# ── Base adapter ───────────────────────────────────────────────────────────


class TranscriptionAdapter:
    """Abstract base. Concrete subclasses implement ``_call_provider``
    and inherit:
      • file-size validation
      • file-exists guard
      • metadata helper for the summary prompt
      • retry loop with linear backoff
    """

    provider_name: str = ""   # subclass sets — 'gemini' / 'openai'

    def __init__(self, *, api_key: str, model: str):
        self.api_key = api_key or ""
        self.model = model

    # ── Public ────────────────────────────────────────────────────

    def transcribe(self, audio_path: str,
                    link_context: Optional[dict] = None) -> str:
        """Return a 4-line summary string. Raises TranscriptionError
        or TranscriptionTimeout on failure."""
        if not self.api_key.strip():
            raise TranscriptionError(
                f"no API key configured for {self.provider_name}")
        if not audio_path:
            raise TranscriptionError("audio_path is empty")
        path = Path(audio_path)
        if not path.is_file():
            raise TranscriptionError(
                f"audio file not found on disk: {audio_path}")
        size = path.stat().st_size
        if size <= 0:
            raise TranscriptionError(
                f"audio file is empty: {audio_path}")
        if size > MAX_AUDIO_BYTES:
            raise TranscriptionError(
                f"file too large for inline transcription "
                f"({size:,} bytes > {MAX_AUDIO_BYTES:,} cap)")

        import time
        last_exc: Optional[Exception] = None
        attempts = RETRY_ATTEMPTS + 1
        for attempt in range(1, attempts + 1):
            try:
                return self._call_provider(path, link_context or {})
            except TranscriptionTimeout as exc:
                last_exc = exc
                log.warning(
                    f"[{self.provider_name}] timeout (attempt {attempt}"
                    f"/{attempts}): {exc}")
            except TranscriptionError as exc:
                # Don't retry on permanent errors (4xx, malformed)
                msg = str(exc).lower()
                if any(s in msg for s in ("401", "403", "invalid",
                                            "malformed", "missing key",
                                            "quota")):
                    raise
                last_exc = exc
                log.warning(
                    f"[{self.provider_name}] transient (attempt {attempt}"
                    f"/{attempts}): {exc}")
            if attempt < attempts:
                time.sleep(RETRY_BACKOFF_S * attempt)
        # Exhausted retries
        raise last_exc or TranscriptionError(
            "transcription failed after all retries")

    # ── Subclass contract ─────────────────────────────────────────

    def _call_provider(self, audio_path: Path, link_context: dict) -> str:
        """Subclass implements provider-specific request + parse.
        Receives a validated Path + optional context dict
        (show_name, rj_name, link_name)."""
        raise NotImplementedError

    # ── Helpers ───────────────────────────────────────────────────

    def _build_prompt(self, link_context: dict) -> str:
        """Prepend show/RJ/link context to the shared prompt so the
        provider has a hint about who's speaking."""
        ctx = ""
        if link_context:
            bits = []
            if link_context.get("show_name"):
                bits.append(f"Show: {link_context['show_name']}")
            if link_context.get("rj_name"):
                bits.append(f"RJ: {link_context['rj_name']}")
            if link_context.get("link_name"):
                bits.append(f"Segment: {link_context['link_name']}")
            if bits:
                ctx = "Context — " + " · ".join(bits) + "\n\n"
        return ctx + SUMMARY_PROMPT

    def _normalize_summary(self, raw: str) -> str:
        """Trim, drop empty lines, cap to first 4 non-empty lines,
        each line stripped of trailing whitespace + bullets."""
        if not raw:
            return ""
        lines = []
        for line in raw.splitlines():
            line = line.strip()
            # Strip leading bullet markers + numbering the model
            # sometimes adds ('* ', '- ', '1. ')
            for prefix in ("* ", "- ", "• "):
                if line.startswith(prefix):
                    line = line[len(prefix):].strip()
                    break
            if (len(line) > 2 and line[0].isdigit()
                    and line[1:3] in (". ", ") ")):
                line = line[3:].strip()
            if line:
                lines.append(line)
            if len(lines) >= 4:
                break
        return "\n".join(lines)


# ── Connection-test result type ────────────────────────────────────────────


class ConnectionTestResult:
    """Shape returned by adapter ``test_connection`` calls. The Assign
    API Key screen uses this to colour the status pill + show error
    detail."""

    __slots__ = ("ok", "detail")

    def __init__(self, ok: bool, detail: str = ""):
        self.ok = bool(ok)
        self.detail = detail or ""
