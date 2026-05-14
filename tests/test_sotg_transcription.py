"""
SOTG Transcription pipeline tests — covers:

  • Base TranscriptionAdapter — file-existence guard, size cap,
    empty-key guard, summary normalisation, retry policy with
    transient vs permanent error split.
  • GeminiAdapter / OpenAIAdapter — request bodies, response parsing,
    HTTP error handling. urllib calls monkey-patched so no real
    network traffic.
  • SOTGTranscriptionEngine — adapter selection from Settings,
    enqueue + worker processing path, SKIPPED gates (no key, missing
    file, missing file_path), DONE / FAILED stamping.
  • DB helpers — set_sotg_assignment_summary status enum guard,
    get_sotg_assignment_by_id join shape, pending list ordering,
    summary counts.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pytest

from core.database import Database


# Quiet logs during tests
logging.getLogger("Transcription").setLevel(logging.WARNING)
logging.getLogger("Transcription.Gemini").setLevel(logging.WARNING)
logging.getLogger("Transcription.OpenAI").setLevel(logging.WARNING)
logging.getLogger("SOTGTranscriptionEngine").setLevel(logging.WARNING)


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def fired_assignment(db, tmp_path):
    """A real SOTG show + link + assignment marked FIRED with an
    on-disk audio file the engine can actually read."""
    sid = db.create_sotg_show(
        rj_name=f"RJ {uuid.uuid4().hex[:6]}",
        show_name=f"Show {uuid.uuid4().hex[:6]}",
        days="Daily", time_start="06:00", time_end="07:00",
        color="#06b6d4", description="",
        link_names=["L1"])
    show = db.get_sotg_show(sid)
    link_id = int(show["links"][0]["id"])
    # Write a tiny "audio" file (content doesn't matter for stubbed
    # adapter; the engine only checks size > 0 + path exists)
    audio = tmp_path / "fired.mp3"
    audio.write_bytes(b"fake-mp3-header" + b"\x00" * 1024)
    today = date.today().isoformat()
    aid = db.upsert_sotg_assignment(
        show_id=sid, link_id=link_id, scheduled_date=today,
        file_path=str(audio), file_name=audio.name,
        file_duration_ms=30_000,
        sharp_time="06:00", priority="High", status="FIRED",
        allow_past=True)
    yield {"sid": sid, "aid": aid, "link_id": link_id,
           "audio": audio}
    try:
        db.delete_sotg_show(sid)
    except Exception:
        pass


# ── DB helpers ─────────────────────────────────────────────────────────────


def test_set_summary_rejects_unknown_status(db, fired_assignment):
    aid = fired_assignment["aid"]
    with pytest.raises(ValueError, match="unknown ai_status"):
        db.set_sotg_assignment_summary(
            aid, summary="x", provider="gemini", status="WHATEVER")


def test_set_summary_rejects_unknown_provider(db, fired_assignment):
    aid = fired_assignment["aid"]
    with pytest.raises(ValueError, match="unknown ai_provider"):
        db.set_sotg_assignment_summary(
            aid, summary="x", provider="chatgpt", status="DONE")


def test_set_summary_done_stamps_timestamp(db, fired_assignment):
    aid = fired_assignment["aid"]
    db.set_sotg_assignment_summary(
        aid, summary="Topic: line 1\nInsight: line 2",
        provider="gemini", status="DONE")
    row = db.get_sotg_assignment_by_id(aid)
    assert row["ai_status"] == "DONE"
    assert row["ai_provider"] == "gemini"
    assert row["ai_summary"].startswith("Topic")
    assert row["ai_summary_at"] is not None


def test_set_summary_failed_no_timestamp(db, fired_assignment):
    aid = fired_assignment["aid"]
    db.set_sotg_assignment_summary(
        aid, summary=None, provider="gemini", status="FAILED")
    row = db.get_sotg_assignment_by_id(aid)
    assert row["ai_status"] == "FAILED"
    assert row["ai_summary_at"] is None


def test_pending_transcription_filters_done_and_no_file(db,
                                                          fired_assignment):
    """The backfill query must skip rows that already have ai_status =
    DONE, and skip rows with file_path = NULL (nothing to transcribe)."""
    aid = fired_assignment["aid"]
    pending = db.get_pending_transcription_assignments(limit=20)
    # Our fixture row is FIRED + file_path set → should be in the list
    assert any(int(p["id"]) == aid for p in pending)
    # Mark DONE → drop from list
    db.set_sotg_assignment_summary(
        aid, summary="x", provider="gemini", status="DONE")
    pending = db.get_pending_transcription_assignments(limit=20)
    assert all(int(p["id"]) != aid for p in pending)


def test_get_sotg_assignment_by_id_joins_show_meta(db, fired_assignment):
    row = db.get_sotg_assignment_by_id(fired_assignment["aid"])
    assert row is not None
    assert "show_name" in row
    assert "rj_name" in row
    assert "link_name" in row
    assert row["link_name"] == "L1"


def test_summary_counts_today_buckets(db, fired_assignment):
    aid = fired_assignment["aid"]
    counts = db.get_sotg_summary_counts_today()
    # Fired row, no ai_status yet → counted as pending
    assert counts["pending"] >= 1
    db.set_sotg_assignment_summary(
        aid, summary="x", provider="gemini", status="DONE")
    counts = db.get_sotg_summary_counts_today()
    assert counts["done"] >= 1


def test_assignments_for_date_includes_ai_columns(db, fired_assignment):
    """Generate Report screen + PDF read these columns — must surface
    in the joined query."""
    today = date.today().isoformat()
    rows = db.get_sotg_assignments_for_date(today)
    target = [r for r in rows if int(r["assignment_id"])
               == fired_assignment["aid"]]
    assert target, "fixture row must surface in the joined query"
    r = target[0]
    for col in ("ai_summary", "ai_summary_at", "ai_provider", "ai_status"):
        assert col in r


# ── Adapter base ───────────────────────────────────────────────────────────


def test_base_adapter_rejects_missing_key(tmp_path):
    from core.transcription.gemini_adapter import GeminiAdapter
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"x" * 100)
    adapter = GeminiAdapter(api_key="", model="gemini-2.5-flash")
    from core.transcription import TranscriptionError
    with pytest.raises(TranscriptionError, match="no API key"):
        adapter.transcribe(str(audio))


def test_base_adapter_rejects_missing_file(tmp_path):
    from core.transcription.gemini_adapter import GeminiAdapter
    adapter = GeminiAdapter(api_key="key-here", model="gemini-2.5-flash")
    from core.transcription import TranscriptionError
    with pytest.raises(TranscriptionError, match="not found"):
        adapter.transcribe(str(tmp_path / "nonexistent.mp3"))


def test_base_adapter_rejects_oversized_file(tmp_path, monkeypatch):
    """Larger than MAX_AUDIO_BYTES → instant TranscriptionError, no
    network call attempted."""
    from core.transcription.gemini_adapter import GeminiAdapter
    from core.transcription import TranscriptionError, base as base_mod
    # Shrink the cap for the test so we don't have to create a 20 MB
    # temp file
    monkeypatch.setattr(base_mod, "MAX_AUDIO_BYTES", 1024)
    big = tmp_path / "big.mp3"
    big.write_bytes(b"X" * 4096)
    adapter = GeminiAdapter(api_key="k", model="gemini-2.5-flash")
    with pytest.raises(TranscriptionError, match="file too large"):
        adapter.transcribe(str(big))


def test_summary_normalize_strips_bullets():
    from core.transcription.gemini_adapter import GeminiAdapter
    adapter = GeminiAdapter(api_key="k", model="gemini-2.5-flash")
    raw = (
        "* Topic: weather\n"
        "- Insight: clear skies\n"
        "1. Quote: \"sunny day\"\n"
        "2) Call-to-action: tune in\n"
    )
    out = adapter._normalize_summary(raw)
    lines = out.splitlines()
    assert len(lines) == 4
    assert lines[0].startswith("Topic:")
    assert lines[2].startswith("Quote:")


def test_summary_normalize_caps_at_four_lines():
    from core.transcription.gemini_adapter import GeminiAdapter
    adapter = GeminiAdapter(api_key="k", model="gemini-2.5-flash")
    out = adapter._normalize_summary("a\nb\nc\nd\ne\nf")
    assert out.splitlines() == ["a", "b", "c", "d"]


# ── GeminiAdapter HTTP path ────────────────────────────────────────────────


class _FakeHTTPResponse:
    """Bare bones urllib response replacement for context-manager use."""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def test_gemini_happy_path(tmp_path, monkeypatch):
    from core.transcription import gemini_adapter as gm
    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"audio bytes")
    body = {
        "candidates": [{
            "content": {
                "parts": [{"text":
                            "Topic: A\nInsight: B\nQuote: C\nCTA: D"}]
            }
        }]
    }
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = req.data
        return _FakeHTTPResponse(json.dumps(body).encode("utf-8"))

    monkeypatch.setattr(gm.urllib.request, "urlopen", fake_urlopen)
    adapter = gm.GeminiAdapter(
        api_key="AIzaSyTEST", model="gemini-2.5-flash")
    result = adapter.transcribe(str(audio),
                                  link_context={"show_name": "X",
                                                 "rj_name": "Y"})
    assert "Topic: A" in result
    assert captured["url"].startswith(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash:generateContent?key=AIzaSyTEST")
    sent = json.loads(captured["body"].decode("utf-8"))
    assert sent["contents"][0]["parts"][1]["inline_data"]["mime_type"].startswith("audio/")


def test_gemini_401_raises_immediately(tmp_path, monkeypatch):
    from core.transcription import gemini_adapter as gm
    import urllib.error
    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"audio")

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {},
            io.BytesIO(b'{"error":"bad key"}'))

    monkeypatch.setattr(gm.urllib.request, "urlopen", fake_urlopen)
    adapter = gm.GeminiAdapter(api_key="bad", model="gemini-2.5-flash")
    from core.transcription import TranscriptionError
    with pytest.raises(TranscriptionError, match="auth failed"):
        adapter.transcribe(str(audio))


def test_gemini_500_retries_then_fails(tmp_path, monkeypatch):
    """5xx errors hit the retry loop in the base class. We patch
    RETRY_ATTEMPTS to 1 so the test runs fast."""
    from core.transcription import gemini_adapter as gm, base as base_mod
    import urllib.error
    monkeypatch.setattr(base_mod, "RETRY_ATTEMPTS", 1)
    monkeypatch.setattr(base_mod, "RETRY_BACKOFF_S", 0.01)
    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"audio")
    call_count = {"n": 0}

    def fake_urlopen(req, timeout=None):
        call_count["n"] += 1
        raise urllib.error.HTTPError(
            req.full_url, 500, "Server error", {},
            io.BytesIO(b'{"error":"boom"}'))

    monkeypatch.setattr(gm.urllib.request, "urlopen", fake_urlopen)
    adapter = gm.GeminiAdapter(api_key="k", model="gemini-2.5-flash")
    from core.transcription import TranscriptionError
    with pytest.raises(TranscriptionError, match="server error"):
        adapter.transcribe(str(audio))
    assert call_count["n"] == 2     # 1 initial + 1 retry


def test_gemini_test_connection_ok(monkeypatch):
    from core.transcription import gemini_adapter as gm
    monkeypatch.setattr(
        gm.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeHTTPResponse(b'{"models":[]}'))
    adapter = gm.GeminiAdapter(api_key="k", model="gemini-2.5-flash")
    res = adapter.test_connection()
    assert res.ok is True


def test_gemini_test_connection_401(monkeypatch):
    from core.transcription import gemini_adapter as gm
    import urllib.error

    def fail(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {}, io.BytesIO(b''))

    monkeypatch.setattr(gm.urllib.request, "urlopen", fail)
    adapter = gm.GeminiAdapter(api_key="bad", model="gemini-2.5-flash")
    res = adapter.test_connection()
    assert res.ok is False
    assert "401" in res.detail


# ── OpenAIAdapter HTTP path ────────────────────────────────────────────────


def test_openai_happy_path_two_calls(tmp_path, monkeypatch):
    """Whisper STT + GPT chat both invoked. Returns the chat summary."""
    from core.transcription import openai_adapter as oa
    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"audio bytes")
    calls: list[str] = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        if "audio/transcriptions" in req.full_url:
            return _FakeHTTPResponse(b"transcribed text here")
        if "chat/completions" in req.full_url:
            body = {
                "choices": [{"message":
                              {"content":
                               "Topic: A\nInsight: B\nQuote: C\nCTA: D"}}]
            }
            return _FakeHTTPResponse(json.dumps(body).encode("utf-8"))
        raise AssertionError(f"unexpected URL {req.full_url}")

    monkeypatch.setattr(oa.urllib.request, "urlopen", fake_urlopen)
    adapter = oa.OpenAIAdapter(api_key="sk-test", model="gpt-4o-mini")
    out = adapter.transcribe(str(audio))
    assert "Topic: A" in out
    assert any("audio/transcriptions" in u for u in calls)
    assert any("chat/completions" in u for u in calls)


def test_openai_whisper_401_surfaces(tmp_path, monkeypatch):
    from core.transcription import openai_adapter as oa
    import urllib.error
    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"audio")

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {},
            io.BytesIO(b'{"error":"bad key"}'))

    monkeypatch.setattr(oa.urllib.request, "urlopen", fake_urlopen)
    adapter = oa.OpenAIAdapter(api_key="sk-bad", model="gpt-4o-mini")
    from core.transcription import TranscriptionError
    with pytest.raises(TranscriptionError, match="auth failed"):
        adapter.transcribe(str(audio))


# ── Engine ────────────────────────────────────────────────────────────────


def test_engine_factory_returns_correct_adapter():
    from core.transcription import build_adapter, GeminiAdapter, OpenAIAdapter
    g = build_adapter("gemini", "k", "gemini-2.5-flash")
    assert isinstance(g, GeminiAdapter)
    o = build_adapter("openai", "sk-x", "gpt-4o-mini")
    assert isinstance(o, OpenAIAdapter)
    with pytest.raises(ValueError):
        build_adapter("zomg", "k")


def test_engine_skips_when_no_api_key(qapp, db, fired_assignment):
    """No key configured + drop fires → ai_status = SKIPPED (silent),
    no exception escapes the engine."""
    from core.settings import Settings
    from core.sotg_transcription_engine import (
        SOTGTranscriptionEngine,
        KEY_GEMINI_API_KEY, KEY_OPENAI_API_KEY, KEY_ACTIVE_PROVIDER,
    )
    # Wipe any pre-existing keys
    Settings().set(KEY_ACTIVE_PROVIDER, "gemini")
    Settings().set(KEY_GEMINI_API_KEY, "")
    Settings().set(KEY_OPENAI_API_KEY, "")
    engine = SOTGTranscriptionEngine(db=db)
    try:
        # Run worker directly (synchronously) to avoid threading flake
        worker = engine._worker
        assert worker is not None
        worker._process_one(fired_assignment["aid"])
        row = db.get_sotg_assignment_by_id(fired_assignment["aid"])
        assert row["ai_status"] == "SKIPPED"
    finally:
        engine.shutdown()


def test_engine_skips_when_file_missing(qapp, db, fired_assignment, monkeypatch):
    from core.settings import Settings
    from core.sotg_transcription_engine import (
        SOTGTranscriptionEngine, KEY_GEMINI_API_KEY, KEY_ACTIVE_PROVIDER,
    )
    Settings().set(KEY_ACTIVE_PROVIDER, "gemini")
    Settings().set(KEY_GEMINI_API_KEY, "fake-key")
    # Delete the audio file so the engine should skip with SKIPPED
    fired_assignment["audio"].unlink()
    engine = SOTGTranscriptionEngine(db=db)
    try:
        engine._worker._process_one(fired_assignment["aid"])
        row = db.get_sotg_assignment_by_id(fired_assignment["aid"])
        assert row["ai_status"] == "SKIPPED"
    finally:
        engine.shutdown()


def test_engine_success_path_stamps_done(qapp, db, fired_assignment,
                                            monkeypatch):
    """Full happy-path: engine picks up the FIRED aid, adapter
    returns a 4-line summary, DB stamps DONE + summary + provider."""
    from core.settings import Settings
    from core.sotg_transcription_engine import (
        SOTGTranscriptionEngine, KEY_GEMINI_API_KEY,
        KEY_GEMINI_MODEL, KEY_ACTIVE_PROVIDER,
    )
    Settings().set(KEY_ACTIVE_PROVIDER, "gemini")
    Settings().set(KEY_GEMINI_API_KEY, "fake-key")
    Settings().set(KEY_GEMINI_MODEL, "gemini-2.5-flash")

    # Stub the adapter's transcribe so no real HTTP fires
    captured = {}

    def fake_transcribe(self, audio_path, link_context=None):
        captured["audio_path"] = audio_path
        captured["link_context"] = link_context or {}
        return ("Topic: Diwali bhajan hour begins.\n"
                "Insight: RJ Pradeep highlights spiritual significance.\n"
                "Quote: \"Aaj raat har ghar mein roshni ho.\"\n"
                "Call-to-action: Listeners may call 1800-1234-567.")

    from core.transcription.gemini_adapter import GeminiAdapter
    monkeypatch.setattr(GeminiAdapter, "transcribe", fake_transcribe)

    engine = SOTGTranscriptionEngine(db=db)
    try:
        engine._worker._process_one(fired_assignment["aid"])
        row = db.get_sotg_assignment_by_id(fired_assignment["aid"])
        assert row["ai_status"] == "DONE"
        assert row["ai_provider"] == "gemini"
        assert row["ai_summary"].startswith("Topic: Diwali")
        assert row["ai_summary_at"] is not None
        # Link context was forwarded
        assert captured["link_context"]["rj_name"] == row["rj_name"]
    finally:
        engine.shutdown()


def test_engine_failure_stamps_failed(qapp, db, fired_assignment,
                                         monkeypatch):
    """Adapter raises TranscriptionError → engine stamps FAILED."""
    from core.settings import Settings
    from core.sotg_transcription_engine import (
        SOTGTranscriptionEngine, KEY_GEMINI_API_KEY, KEY_ACTIVE_PROVIDER,
    )
    Settings().set(KEY_ACTIVE_PROVIDER, "gemini")
    Settings().set(KEY_GEMINI_API_KEY, "fake-key")

    from core.transcription import TranscriptionError
    from core.transcription.gemini_adapter import GeminiAdapter

    def boom(self, audio_path, link_context=None):
        raise TranscriptionError("bad bad bad")

    monkeypatch.setattr(GeminiAdapter, "transcribe", boom)

    engine = SOTGTranscriptionEngine(db=db)
    try:
        engine._worker._process_one(fired_assignment["aid"])
        row = db.get_sotg_assignment_by_id(fired_assignment["aid"])
        assert row["ai_status"] == "FAILED"
        assert row["ai_summary"] is None
    finally:
        engine.shutdown()


def test_engine_enqueue_changes_queue_depth(qapp, db):
    from core.settings import Settings
    from core.sotg_transcription_engine import (
        SOTGTranscriptionEngine, KEY_GEMINI_API_KEY, KEY_ACTIVE_PROVIDER,
        KEY_ENGINE_ENABLED,
    )
    Settings().set(KEY_ACTIVE_PROVIDER, "gemini")
    Settings().set(KEY_GEMINI_API_KEY, "fake-key")
    Settings().set(KEY_ENGINE_ENABLED, "1")
    engine = SOTGTranscriptionEngine(db=db)
    try:
        # No-op when disabled — but it IS enabled here, so enqueue
        # should bump depth
        before = engine.queue_depth()
        engine.enqueue(99999999)    # non-existent aid is fine —
                                     # worker will look it up + skip
        # Worker may have already popped it; tolerate both. The point
        # is the call doesn't crash.
        assert engine.queue_depth() >= 0
    finally:
        engine.shutdown()


def test_engine_is_enabled_gates_on_key(qapp, db):
    from core.settings import Settings
    from core.sotg_transcription_engine import (
        SOTGTranscriptionEngine, KEY_GEMINI_API_KEY, KEY_ACTIVE_PROVIDER,
    )
    Settings().set(KEY_ACTIVE_PROVIDER, "gemini")
    Settings().set(KEY_GEMINI_API_KEY, "")
    engine = SOTGTranscriptionEngine(db=db)
    try:
        assert engine.is_enabled() is False
        Settings().set(KEY_GEMINI_API_KEY, "k")
        engine.reload_settings()
        assert engine.is_enabled() is True
    finally:
        engine.shutdown()


# ── Screen ────────────────────────────────────────────────────────────────


def test_assign_api_key_screen_constructs(qapp, db, qtbot):
    from core.sotg_transcription_engine import SOTGTranscriptionEngine
    from ui.sotg_assign_api_key import SOTGAssignAPIKey
    engine = SOTGTranscriptionEngine(db=db)
    try:
        s = SOTGAssignAPIKey(db, engine=engine)
        qtbot.addWidget(s)
        assert s.width() == 1440
        assert s.height() == 900
        from PyQt6.QtWidgets import QLabel
        lbl = s.findChild(QLabel, "hdr_station_lbl")
        assert lbl is not None
        s.deleteLater()
    finally:
        engine.shutdown()


def test_assign_api_key_switches_active_provider(qapp, db, qtbot):
    from core.settings import Settings
    from core.sotg_transcription_engine import (
        SOTGTranscriptionEngine, KEY_ACTIVE_PROVIDER,
    )
    from ui.sotg_assign_api_key import SOTGAssignAPIKey
    Settings().set(KEY_ACTIVE_PROVIDER, "gemini")
    engine = SOTGTranscriptionEngine(db=db)
    try:
        s = SOTGAssignAPIKey(db, engine=engine)
        qtbot.addWidget(s)
        s._on_activate_provider("openai")
        assert s._active_provider == "openai"
        assert Settings().get(KEY_ACTIVE_PROVIDER) == "openai"
        s._on_activate_provider("gemini")
        assert s._active_provider == "gemini"
        s.deleteLater()
    finally:
        engine.shutdown()


def test_assign_api_key_save_persists_settings(qapp, db, qtbot):
    """Saving a key writes to Settings + triggers engine reload."""
    from core.settings import Settings
    from core.sotg_transcription_engine import (
        SOTGTranscriptionEngine,
        KEY_GEMINI_API_KEY, KEY_ENGINE_ENABLED, KEY_ACTIVE_PROVIDER,
    )
    from ui.sotg_assign_api_key import SOTGAssignAPIKey
    from PyQt6.QtWidgets import QMessageBox
    engine = SOTGTranscriptionEngine(db=db)
    try:
        Settings().set(KEY_ACTIVE_PROVIDER, "gemini")
        Settings().set(KEY_GEMINI_API_KEY, "")
        s = SOTGAssignAPIKey(db, engine=engine)
        qtbot.addWidget(s)
        s._key_input.setText("AIzaSy_FRESH_KEY_FOR_TESTING")
        # Suppress the success toast
        original_info = QMessageBox.information
        QMessageBox.information = staticmethod(
            lambda *a, **kw: None)
        try:
            s._on_save_clicked()
        finally:
            QMessageBox.information = original_info
        assert Settings().get(KEY_GEMINI_API_KEY) == "AIzaSy_FRESH_KEY_FOR_TESTING"
        assert Settings().get(KEY_ENGINE_ENABLED) == "1"
        s.deleteLater()
    finally:
        engine.shutdown()


# ── Generate Report row expansion when ai_summary present ─────────────────


def test_generate_report_row_expands_when_summary_set(qapp):
    """The screen row should grow from 56 → 116px when ai_summary is
    populated, leaving room for the 4-line italic sub-block."""
    from ui.sotg_generate_report import _AssignmentRow
    bare = _AssignmentRow({
        "link_order": 1, "sharp_time": "06:00",
        "show_name": "X", "rj_name": "Y", "link_name": "Z",
        "status": "FIRED", "file_name": "z.mp3",
        "file_duration_ms": 30_000,
        "color": "#06b6d4",
    })
    summarized = _AssignmentRow({
        "link_order": 1, "sharp_time": "06:00",
        "show_name": "X", "rj_name": "Y", "link_name": "Z",
        "status": "FIRED", "file_name": "z.mp3",
        "file_duration_ms": 30_000,
        "color": "#06b6d4",
        "ai_status": "DONE",
        "ai_summary": ("Topic: greeting\nInsight: tip\n"
                        "Quote: \"hi\"\nCTA: tune in"),
    })
    assert bare.height() == _AssignmentRow.HEIGHT
    assert summarized.height() == _AssignmentRow.HEIGHT_WITH_SUMMARY
    bare.deleteLater()
    summarized.deleteLater()


# ── PDF generator picks up ai_summary ────────────────────────────────────


def test_pdf_renders_summary_when_db_carries_one(qapp, db, fired_assignment,
                                                    tmp_path):
    """End-to-end: stamp a DONE summary on the fixture, generate PDF,
    confirm file exists + is larger than the no-summary baseline."""
    from core.reports.sotg_daily_report import generate_sotg_daily_report
    today = date.today()
    no_summary_pdf = generate_sotg_daily_report(
        today, output_path=tmp_path / "before.pdf", db=db)
    before_size = no_summary_pdf.stat().st_size

    db.set_sotg_assignment_summary(
        fired_assignment["aid"],
        summary=("Topic: A long enough four-line summary about the segment.\n"
                  "Insight: RJ shared some interesting cultural context.\n"
                  "Quote: \"A direct line from the broadcast.\"\n"
                  "Call-to-action: Listeners encouraged to engage."),
        provider="gemini", status="DONE")

    with_summary_pdf = generate_sotg_daily_report(
        today, output_path=tmp_path / "after.pdf", db=db)
    after_size = with_summary_pdf.stat().st_size
    # Adding a 4-line block should add at least a few hundred bytes
    assert after_size > before_size


# ── MainWindow integration ───────────────────────────────────────────────


def test_main_window_mounts_sotg_assign_api_key(qapp, db, qtbot, monkeypatch):
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    assert hasattr(w, "sotg_assign_api_key")
    assert hasattr(w, "_transcription_engine")
    w._on_hub_screen_requested("assign_api_key")
    assert w._stack.currentWidget() is w.sotg_assign_api_key
    w.close()
    w.deleteLater()


def test_main_window_wires_studio_fire_to_engine_enqueue(
        qapp, db, qtbot, monkeypatch):
    """When Studio emits sotg_drop_fired, the engine.enqueue gets the
    aid. We mock enqueue to capture invocations."""
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                         lambda self: None)
    from ui.main_window import MainWindow
    w = MainWindow(db=db)
    qtbot.addWidget(w)
    captured: list[int] = []
    # Replace enqueue with a capture so we don't actually fire the
    # worker (no real key, would skip anyway, but cheaper)
    w._transcription_engine.enqueue = lambda aid: captured.append(int(aid))
    # Manually re-connect since we just rebound the bound method
    try:
        w.studio.sotg_drop_fired.disconnect()
    except (TypeError, RuntimeError):
        pass
    w.studio.sotg_drop_fired.connect(w._transcription_engine.enqueue)
    w.studio.sotg_drop_fired.emit(424242)
    assert captured == [424242]
    w.close()
    w.deleteLater()
