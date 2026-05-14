"""
Gemini transcription adapter — 1-call audio → summary path.

Uses Google's ``generateContent`` REST endpoint with the audio file
inline as base64. One call gets both the transcription (implicit)
and the 4-line summary (via our prompt). No SDK dependency —
``urllib.request`` + JSON only.

Endpoint:
  POST https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent?key=<KEY>

Request body shape (simplified):
  {
    "contents": [
      { "parts": [
          { "text": "<our 4-line summary prompt>" },
          { "inline_data": {
              "mime_type": "audio/mpeg",
              "data": "<base64 audio bytes>"
          }}
      ]}
    ],
    "generationConfig": {
      "temperature": 0.2,
      "maxOutputTokens": 256
    }
  }

Response shape (simplified):
  { "candidates": [{ "content": { "parts": [{ "text": "..." }] }}] }

The free tier model `gemini-2.5-flash` handles Hindi-English mix well
and gives plenty of headroom for 30-second SOTG drops (typically
~500 KB MP3, well under the 20 MB inline limit).
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path

from core.transcription.base import (
    TranscriptionAdapter, TranscriptionError, TranscriptionTimeout,
    HTTP_TIMEOUT_S, ConnectionTestResult,
)

log = logging.getLogger("Transcription.Gemini")


# Valid model names accepted by the Generate Content endpoint as of
# 2026-05-14. UI may extend; engine accepts any string but rejects
# anything that doesn't ping back successfully on test_connection.
DEFAULT_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
)


class GeminiAdapter(TranscriptionAdapter):
    provider_name = "gemini"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def _call_provider(self, audio_path: Path, link_context: dict) -> str:
        mime, _ = mimetypes.guess_type(str(audio_path))
        # SOTG audio is mp3 or wav; default to mpeg if guess fails
        if not mime or not mime.startswith("audio/"):
            mime = "audio/mpeg"

        with open(audio_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("ascii")

        body = {
            "contents": [{
                "parts": [
                    {"text": self._build_prompt(link_context)},
                    {"inline_data": {
                        "mime_type": mime,
                        "data": audio_b64,
                    }},
                ]
            }],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 256,
            },
        }
        url = (f"{self.BASE_URL}/models/{self.model}:generateContent"
               f"?key={self.api_key}")
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST")

        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body_text = ""
            try:
                body_text = exc.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                pass
            if exc.code in (401, 403):
                raise TranscriptionError(
                    f"Gemini auth failed ({exc.code}) — invalid or missing "
                    f"API key. Body: {body_text}") from exc
            if exc.code == 429:
                raise TranscriptionError(
                    f"Gemini rate-limited / quota exhausted (429). "
                    f"Body: {body_text}") from exc
            if 400 <= exc.code < 500:
                raise TranscriptionError(
                    f"Gemini rejected request ({exc.code}). "
                    f"Body: {body_text}") from exc
            # 5xx — let the base class retry
            raise TranscriptionError(
                f"Gemini server error ({exc.code}). "
                f"Body: {body_text}") from exc
        except urllib.error.URLError as exc:
            # Network-level (timeout, DNS, refused)
            if "timed out" in str(exc).lower():
                raise TranscriptionTimeout(
                    f"Gemini request timed out after {HTTP_TIMEOUT_S}s") from exc
            raise TranscriptionError(
                f"Gemini network error: {exc}") from exc
        except TimeoutError as exc:
            raise TranscriptionTimeout(
                f"Gemini request timed out after {HTTP_TIMEOUT_S}s") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TranscriptionError(
                f"Gemini response not JSON: {raw[:200]!r}") from exc

        # Pull out candidate text — defensive against shape drift
        text = ""
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            # Some responses use a "promptFeedback" block on refusal
            if "promptFeedback" in data:
                raise TranscriptionError(
                    f"Gemini refused: {data['promptFeedback']}")
            raise TranscriptionError(
                f"Gemini response missing candidates: {raw[:200]!r}")

        summary = self._normalize_summary(text)
        if not summary:
            raise TranscriptionError(
                f"Gemini returned empty summary: {text[:200]!r}")
        log.info(
            f"[gemini] transcribe ok model={self.model} "
            f"size={audio_path.stat().st_size} bytes")
        return summary

    # ── Connection test ──────────────────────────────────────────

    def test_connection(self) -> ConnectionTestResult:
        """Cheap ping — lists available models. 200 → key works.
        Does NOT consume transcription quota."""
        if not self.api_key.strip():
            return ConnectionTestResult(False, "API key is empty")
        url = f"{self.BASE_URL}/models?key={self.api_key}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
            return ConnectionTestResult(True, f"Connected ({self.model})")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return ConnectionTestResult(
                    False, f"Auth failed ({exc.code}) — check the key")
            return ConnectionTestResult(
                False, f"HTTP {exc.code}: {exc.reason}")
        except urllib.error.URLError as exc:
            return ConnectionTestResult(False, f"Network: {exc.reason}")
        except Exception as exc:
            return ConnectionTestResult(False, str(exc))
