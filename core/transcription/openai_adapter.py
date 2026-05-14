"""
OpenAI transcription adapter — 2-call STT + summary pipeline.

Step 1: Whisper transcription
  POST https://api.openai.com/v1/audio/transcriptions
  multipart/form-data with file + model="whisper-1"
  → text response

Step 2: Chat completion (summarisation)
  POST https://api.openai.com/v1/chat/completions
  JSON body with our 4-line summary prompt + Whisper transcript
  → text response (the 4 lines)

The pipeline costs ~$0.006 / minute audio + ~$0.0002 / summary, so
roughly $0.01 per 30-second SOTG drop. Higher accuracy + better
punctuation than Gemini's audio path, but 2 round-trips means
3-6 seconds latency instead of 1-2.

The ``model`` setting on this adapter controls the SUMMARY model
(gpt-4o-mini default — fast + cheap). STT model is hard-coded to
``whisper-1`` since OpenAI hasn't shipped a Whisper replacement yet.
"""

from __future__ import annotations

import io
import json
import logging
import mimetypes
import uuid
import urllib.error
import urllib.request
from pathlib import Path

from core.transcription.base import (
    TranscriptionAdapter, TranscriptionError, TranscriptionTimeout,
    HTTP_TIMEOUT_S, ConnectionTestResult,
)

log = logging.getLogger("Transcription.OpenAI")


# Summary models accepted today. UI dropdown surfaces these.
DEFAULT_MODELS = (
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4-turbo",
)


def _build_multipart(file_path: Path, *,
                      model: str = "whisper-1",
                      response_format: str = "text") -> tuple[bytes, str]:
    """Build a multipart/form-data body for the Whisper endpoint.
    Returns (body_bytes, content_type) tuple. Pure-stdlib path so no
    `requests` dep is needed."""
    boundary = "----RadioAI" + uuid.uuid4().hex
    crlf = b"\r\n"
    buf = io.BytesIO()

    def _push_field(name: str, value: str):
        buf.write(f"--{boundary}".encode("ascii") + crlf)
        buf.write(f'Content-Disposition: form-data; name="{name}"'.encode("ascii") + crlf + crlf)
        buf.write(value.encode("utf-8") + crlf)

    _push_field("model", model)
    _push_field("response_format", response_format)

    # File field
    mime, _ = mimetypes.guess_type(str(file_path))
    if not mime:
        mime = "audio/mpeg"
    buf.write(f"--{boundary}".encode("ascii") + crlf)
    buf.write(
        f'Content-Disposition: form-data; name="file"; '
        f'filename="{file_path.name}"'.encode("ascii") + crlf)
    buf.write(f"Content-Type: {mime}".encode("ascii") + crlf + crlf)
    with open(file_path, "rb") as f:
        buf.write(f.read())
    buf.write(crlf)
    buf.write(f"--{boundary}--".encode("ascii") + crlf)

    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


class OpenAIAdapter(TranscriptionAdapter):
    provider_name = "openai"
    BASE_URL = "https://api.openai.com/v1"
    STT_MODEL = "whisper-1"

    def _call_provider(self, audio_path: Path, link_context: dict) -> str:
        # ── Step 1: Whisper STT ─────────────────────────────────
        transcript = self._whisper_stt(audio_path)
        if not transcript.strip():
            raise TranscriptionError(
                "Whisper returned empty transcript")

        # ── Step 2: GPT summarisation ───────────────────────────
        summary = self._chat_summarize(transcript, link_context)
        if not summary:
            raise TranscriptionError(
                "GPT summary was empty after normalisation")
        log.info(
            f"[openai] transcribe ok stt={self.STT_MODEL} "
            f"summary={self.model} size={audio_path.stat().st_size} bytes")
        return summary

    def _whisper_stt(self, audio_path: Path) -> str:
        body, ctype = _build_multipart(audio_path,
                                         model=self.STT_MODEL,
                                         response_format="text")
        req = urllib.request.Request(
            f"{self.BASE_URL}/audio/transcriptions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": ctype,
            },
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                return resp.read().decode("utf-8", errors="replace").strip()
        except urllib.error.HTTPError as exc:
            self._raise_for_http(exc, "Whisper STT")
        except urllib.error.URLError as exc:
            if "timed out" in str(exc).lower():
                raise TranscriptionTimeout(
                    f"Whisper request timed out after {HTTP_TIMEOUT_S}s") from exc
            raise TranscriptionError(
                f"Whisper network error: {exc}") from exc
        except TimeoutError as exc:
            raise TranscriptionTimeout(
                f"Whisper request timed out after {HTTP_TIMEOUT_S}s") from exc

    def _chat_summarize(self, transcript: str, link_context: dict) -> str:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._build_prompt(link_context)},
                {"role": "user",
                 "content": f"Transcript:\n\n{transcript}"},
            ],
            "temperature": 0.2,
            "max_tokens": 256,
        }
        req = urllib.request.Request(
            f"{self.BASE_URL}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            self._raise_for_http(exc, "Chat summarisation")
        except urllib.error.URLError as exc:
            if "timed out" in str(exc).lower():
                raise TranscriptionTimeout(
                    f"Chat request timed out after {HTTP_TIMEOUT_S}s") from exc
            raise TranscriptionError(
                f"Chat network error: {exc}") from exc
        except TimeoutError as exc:
            raise TranscriptionTimeout(
                f"Chat request timed out after {HTTP_TIMEOUT_S}s") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TranscriptionError(
                f"Chat response not JSON: {raw[:200]!r}") from exc

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise TranscriptionError(
                f"Chat response missing choices: {raw[:200]!r}")

        return self._normalize_summary(text)

    def _raise_for_http(self, exc: urllib.error.HTTPError, label: str):
        body_text = ""
        try:
            body_text = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        if exc.code == 401:
            raise TranscriptionError(
                f"OpenAI auth failed (401) — invalid API key. "
                f"Body: {body_text}") from exc
        if exc.code == 429:
            raise TranscriptionError(
                f"OpenAI rate-limited / quota exhausted (429). "
                f"Body: {body_text}") from exc
        if 400 <= exc.code < 500:
            raise TranscriptionError(
                f"OpenAI rejected {label} ({exc.code}). "
                f"Body: {body_text}") from exc
        raise TranscriptionError(
            f"OpenAI server error during {label} ({exc.code}). "
            f"Body: {body_text}") from exc

    # ── Connection test ──────────────────────────────────────────

    def test_connection(self) -> ConnectionTestResult:
        """List models — 200 means the key works."""
        if not self.api_key.strip():
            return ConnectionTestResult(False, "API key is empty")
        req = urllib.request.Request(
            f"{self.BASE_URL}/models",
            headers={"Authorization": f"Bearer {self.api_key}"},
            method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
            return ConnectionTestResult(True, f"Connected ({self.model})")
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                return ConnectionTestResult(
                    False, "Auth failed (401) — check the key")
            return ConnectionTestResult(
                False, f"HTTP {exc.code}: {exc.reason}")
        except urllib.error.URLError as exc:
            return ConnectionTestResult(False, f"Network: {exc.reason}")
        except Exception as exc:
            return ConnectionTestResult(False, str(exc))
