"""
RadioAI Studio Pro — SOTG Transcription Engine.

Background QThread worker that listens for fired SOTG drops, transcribes
the audio via the active provider (Gemini default · OpenAI optional),
and persists a 4-line summary in ``sotg_assignments.ai_summary``.

Wiring:
  • Studio dispatcher calls ``mark_sotg_assignment_fired(aid)``.
  • Studio (or main_window) then calls ``engine.enqueue(aid)``.
  • Engine pushes the aid onto its internal queue.
  • Worker thread pops, looks up the assignment, reads audio + context,
    calls the active adapter, persists the summary.
  • ``transcription_finished(aid, status)`` signal fires so the Assign
    API Key screen + Generate Report screen can refresh.

Single-worker design (one outstanding HTTP call at a time) keeps the
free-tier quota safe and the queue ordering deterministic. The queue
is in-memory only — engine restarts via the Backfill button when the
operator clicks it.

Failure handling:
  • Missing API key → ai_status = SKIPPED (silent per operator's
    spec: "no broadcast-loop noise").
  • Missing audio file on disk → SKIPPED.
  • Provider error after retries → FAILED (toast via signal).
  • Timeout-specific retries inherited from base adapter.

Engine is OWNED by MainWindow + lives for the app's lifetime. Shared
across the Assign API Key screen (for live status), Studio (for the
enqueue hook), and Generate Report (passive — reads DB).
"""

from __future__ import annotations

import logging
import os
import threading
from queue import Queue, Empty
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.settings import Settings
from core.database import Database
from core.transcription import (
    TranscriptionAdapter, TranscriptionError, TranscriptionTimeout,
    GeminiAdapter, OpenAIAdapter, build_adapter,
)

log = logging.getLogger("SOTGTranscriptionEngine")


# Settings keys (single source of truth — UI + engine read/write here)
KEY_ACTIVE_PROVIDER = "sotg_ai_active_provider"     # 'gemini' | 'openai'
KEY_GEMINI_API_KEY  = "sotg_ai_gemini_key"
KEY_GEMINI_MODEL    = "sotg_ai_gemini_model"
KEY_OPENAI_API_KEY  = "sotg_ai_openai_key"
KEY_OPENAI_MODEL    = "sotg_ai_openai_model"
KEY_ENGINE_ENABLED  = "sotg_ai_engine_enabled"      # '1' | '0'


class SOTGTranscriptionEngine(QObject):
    """QObject that owns a background QThread worker. Public surface
    is thread-safe — caller code in any thread can ``enqueue(aid)``,
    ``reload_settings()``, etc., and the worker pulls jobs serially."""

    # Signals
    transcription_started   = pyqtSignal(int)            # aid
    transcription_finished  = pyqtSignal(int, str)        # aid, status
    queue_changed           = pyqtSignal(int)            # queue depth
    engine_state_changed    = pyqtSignal(bool)           # True = running

    def __init__(self, db: Optional[Database] = None, parent=None):
        super().__init__(parent)
        self._db = db or Database()
        self._queue: "Queue[int]" = Queue()
        self._thread: Optional[QThread] = None
        self._worker: Optional[_Worker] = None
        self._lock = threading.Lock()
        self._adapter: Optional[TranscriptionAdapter] = None
        self._active_provider: str = ""

        self._load_adapter_from_settings()
        self._start_worker()

    # ── Public ────────────────────────────────────────────────────────

    def enqueue(self, assignment_id: int) -> None:
        """Push one SOTG assignment id onto the worker queue. Safe to
        call from any thread. No-op if the engine is disabled."""
        try:
            aid = int(assignment_id)
        except (TypeError, ValueError):
            return
        if not self.is_enabled():
            log.info(
                f"[sotg-engine] disabled — skipping aid={aid}")
            return
        self._queue.put(aid)
        self.queue_changed.emit(self._queue.qsize())

    def enqueue_backfill(self, limit: int = 50) -> int:
        """Pull every FIRED row without a DONE summary and enqueue
        them. Returns the number enqueued so the screen can toast."""
        rows = self._db.get_pending_transcription_assignments(limit=limit)
        n = 0
        for r in rows:
            self.enqueue(int(r["id"]))
            n += 1
        log.info(f"[sotg-engine] backfilled {n} pending assignments")
        return n

    def reload_settings(self) -> None:
        """Re-read provider + key from Settings. Call after the UI
        saves new credentials so subsequent jobs use them."""
        self._load_adapter_from_settings()

    def is_enabled(self) -> bool:
        """Engine runs only when toggled on AND the active provider
        has a non-empty API key. Both gates are operator-set."""
        if self._adapter is None:
            return False
        if not (self._adapter.api_key or "").strip():
            return False
        on = Settings().get(KEY_ENGINE_ENABLED, "1")
        return str(on).strip() in ("1", "true", "True", "yes")

    def queue_depth(self) -> int:
        return self._queue.qsize()

    def active_provider(self) -> str:
        return self._active_provider

    def shutdown(self) -> None:
        """Graceful shutdown — push sentinel, join thread."""
        if self._worker is not None:
            self._worker.stop()
        self._queue.put(-1)        # sentinel
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)

    # ── Internal ──────────────────────────────────────────────────────

    def _load_adapter_from_settings(self) -> None:
        with self._lock:
            s = Settings()
            self._active_provider = (s.get(KEY_ACTIVE_PROVIDER, "gemini") or "gemini")
            if self._active_provider == "openai":
                key = s.get(KEY_OPENAI_API_KEY, "") or ""
                model = s.get(KEY_OPENAI_MODEL, "gpt-4o-mini") or "gpt-4o-mini"
                self._adapter = OpenAIAdapter(api_key=key, model=model)
            else:
                # default to gemini for any non-openai value
                key = s.get(KEY_GEMINI_API_KEY, "") or ""
                model = s.get(KEY_GEMINI_MODEL, "gemini-2.5-flash") or "gemini-2.5-flash"
                self._adapter = GeminiAdapter(api_key=key, model=model)
            log.info(
                f"[sotg-engine] adapter ready: provider="
                f"{self._active_provider} model={self._adapter.model}")

    def _start_worker(self) -> None:
        self._thread = QThread()
        self._worker = _Worker(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._thread.start()
        self.engine_state_changed.emit(True)


class _Worker(QObject):
    """Lives on the engine's QThread. Loops on the queue, processes
    one job at a time. Emits signals back to the engine for UI."""

    def __init__(self, engine: SOTGTranscriptionEngine):
        super().__init__()
        self._engine = engine
        self._stopping = False

    def stop(self):
        self._stopping = True

    def run(self):
        """Blocking loop — pops aids, processes serially. -1 sentinel
        breaks out of the loop on shutdown."""
        log.info("[sotg-engine] worker thread started")
        while not self._stopping:
            try:
                aid = self._engine._queue.get(timeout=1.0)
            except Empty:
                continue
            if aid is None or aid == -1:
                break
            try:
                self._engine.queue_changed.emit(
                    self._engine._queue.qsize())
                self._process_one(int(aid))
            except Exception as exc:
                # Last-line defensive — must never kill the worker
                log.exception(
                    f"[sotg-engine] unhandled exception on aid={aid}: "
                    f"{exc}")
        log.info("[sotg-engine] worker thread stopped")

    def _process_one(self, aid: int) -> None:
        log.info(f"[sotg-engine] processing aid={aid}")
        self._engine.transcription_started.emit(aid)
        db = self._engine._db
        try:
            row = db.get_sotg_assignment_by_id(aid)
        except Exception as exc:
            log.warning(f"[sotg-engine] DB lookup failed aid={aid}: {exc}")
            return
        if row is None:
            log.warning(f"[sotg-engine] aid={aid} not found, skipping")
            return

        # Gate: file_path required
        file_path = (row.get("file_path") or "").strip()
        if not file_path:
            self._stamp(aid, summary=None, provider=None, status="SKIPPED")
            self._engine.transcription_finished.emit(aid, "SKIPPED")
            return
        if not os.path.isfile(file_path):
            log.info(
                f"[sotg-engine] aid={aid} file missing on disk: {file_path}")
            self._stamp(aid, summary=None, provider=None, status="SKIPPED")
            self._engine.transcription_finished.emit(aid, "SKIPPED")
            return

        adapter = self._engine._adapter
        if adapter is None or not (adapter.api_key or "").strip():
            log.info(
                f"[sotg-engine] aid={aid} no API key — silent skip "
                f"(operator's spec)")
            self._stamp(aid, summary=None, provider=None, status="SKIPPED")
            self._engine.transcription_finished.emit(aid, "SKIPPED")
            return

        # Mark PROCESSING so screens reflect the in-flight state
        self._stamp(aid, summary=None,
                     provider=adapter.provider_name, status="PROCESSING")

        link_ctx = {
            "show_name": row.get("show_name") or "",
            "rj_name":   row.get("rj_name") or "",
            "link_name": row.get("link_name") or "",
        }
        try:
            summary = adapter.transcribe(file_path, link_context=link_ctx)
        except TranscriptionTimeout as exc:
            log.warning(
                f"[sotg-engine] aid={aid} timed out: {exc}")
            self._stamp(aid, summary=None,
                         provider=adapter.provider_name, status="FAILED")
            self._engine.transcription_finished.emit(aid, "FAILED")
            return
        except TranscriptionError as exc:
            log.warning(
                f"[sotg-engine] aid={aid} failed: {exc}")
            self._stamp(aid, summary=None,
                         provider=adapter.provider_name, status="FAILED")
            self._engine.transcription_finished.emit(aid, "FAILED")
            return
        except Exception as exc:
            log.exception(
                f"[sotg-engine] aid={aid} unexpected: {exc}")
            self._stamp(aid, summary=None,
                         provider=adapter.provider_name, status="FAILED")
            self._engine.transcription_finished.emit(aid, "FAILED")
            return

        self._stamp(aid, summary=summary,
                     provider=adapter.provider_name, status="DONE")
        log.info(
            f"[sotg-engine] aid={aid} done ({adapter.provider_name})")
        self._engine.transcription_finished.emit(aid, "DONE")

    def _stamp(self, aid: int, *,
                summary: Optional[str],
                provider: Optional[str],
                status: str) -> None:
        try:
            self._engine._db.set_sotg_assignment_summary(
                aid, summary=summary, provider=provider, status=status)
        except Exception as exc:
            log.warning(
                f"[sotg-engine] aid={aid} stamp failed ({status}): {exc}")
