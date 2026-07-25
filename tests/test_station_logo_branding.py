"""
Station logo branding (2026-07-25).

Operator request: upload the station logo in Settings so it appears on
the report headers instead of the built-in RadioAI tile.

Contract pinned here:
  • the picked image is COPIED into paths.BRANDING_DIR as a normalised
    square PNG — never referenced in place (an external path can vanish;
    that is exactly how 18 jingle rows lost their audio the same day)
  • non-images / missing files are rejected, they never half-apply
  • a missing logo file degrades to "no logo" rather than raising
  • both PDF reports keep rendering with a logo set, without one, and
    with a configured-but-deleted logo (fallback to the painted tile)

Every test redirects BRANDING_DIR into tmp_path and restores the
settings key, so the operator's real branding is untouched.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QColor

from core import branding, paths
from core.database import Database
from core.settings import Settings


@pytest.fixture
def logo_env(qapp, tmp_path, monkeypatch):
    """Isolate BRANDING_DIR + the settings key.

    Clears the key on SETUP as well as restoring it on teardown —
    ``Settings`` is a process-wide singleton, so without the setup clear
    these tests only pass in the order they happen to run in.
    """
    db = Database()
    Settings().load(db)
    original = Settings().get(branding.SETTINGS_KEY, "")
    monkeypatch.setattr(paths, "BRANDING_DIR", tmp_path / "Branding")
    Settings().set(branding.SETTINGS_KEY, "")
    try:
        yield tmp_path
    finally:
        try:
            Settings().set(branding.SETTINGS_KEY, original or "")
        except Exception:
            pass


def _make_image(path: Path, w: int = 300, h: int = 200,
                color: str = "#ff0000") -> Path:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(str(path))
    return path


# ── set_station_logo ────────────────────────────────────────────────────


def test_upload_copies_into_branding_dir(logo_env):
    src = _make_image(logo_env / "my_logo.png")
    dest = branding.set_station_logo(src)
    assert dest is not None
    assert dest.is_file()
    assert dest.parent == paths.BRANDING_DIR
    # The stored copy is independent of the source.
    src.unlink()
    assert branding.station_logo_path() == dest


def test_upload_normalises_to_a_square_png(logo_env):
    """A 300×200 upload must become a square so the 48×48 report tile
    never stretches it."""
    dest = branding.set_station_logo(_make_image(logo_env / "wide.png",
                                                 300, 200))
    img = QImage(str(dest))
    assert img.width() == img.height() == branding.LOGO_STORE_PX


def test_upload_accepts_jpg(logo_env):
    dest = branding.set_station_logo(_make_image(logo_env / "l.jpg", 120, 120))
    assert dest is not None and dest.suffix == ".png"


def test_reupload_replaces_rather_than_accumulates(logo_env):
    branding.set_station_logo(_make_image(logo_env / "a.png",
                                          color="#ff0000"))
    branding.set_station_logo(_make_image(logo_env / "b.png",
                                          color="#00ff00"))
    files = list(paths.BRANDING_DIR.iterdir())
    assert len(files) == 1, f"stale copies left behind: {files}"


def test_rejects_missing_file(logo_env):
    assert branding.set_station_logo(logo_env / "nope.png") is None
    assert branding.station_logo_path() is None


def test_rejects_non_image(logo_env):
    bad = logo_env / "notes.txt"
    bad.write_text("this is not an image")
    assert branding.set_station_logo(bad) is None


def test_rejects_image_with_unsupported_suffix(logo_env):
    weird = logo_env / "logo.tiff"
    _make_image(logo_env / "tmp.png").replace(weird)
    assert branding.set_station_logo(weird) is None


# ── read / clear ────────────────────────────────────────────────────────


def test_path_is_none_when_unset(logo_env):
    Settings().set(branding.SETTINGS_KEY, "")
    assert branding.station_logo_path() is None
    assert branding.load_station_logo() is None


def test_path_is_none_when_file_deleted_behind_our_back(logo_env):
    dest = branding.set_station_logo(_make_image(logo_env / "l.png"))
    dest.unlink()
    # Degrades quietly — callers fall back to the painted tile.
    assert branding.station_logo_path() is None
    assert branding.load_station_logo() is None


def test_clear_removes_copy_and_setting(logo_env):
    dest = branding.set_station_logo(_make_image(logo_env / "l.png"))
    assert dest.is_file()
    branding.clear_station_logo()
    assert not dest.exists()
    assert branding.station_logo_path() is None


def test_clear_is_idempotent(logo_env):
    branding.clear_station_logo()
    branding.clear_station_logo()
    assert branding.station_logo_path() is None


def test_load_returns_paintable_image(logo_env):
    branding.set_station_logo(_make_image(logo_env / "l.png"))
    img = branding.load_station_logo()
    assert img is not None and not img.isNull()
    assert img.width() > 0


# ── Reports keep working in all three states ────────────────────────────


@pytest.fixture
def campaign(logo_env):
    import uuid
    db = Database()
    conn = db._conn()
    cur = conn.execute(
        "INSERT INTO campaigns (name, description, category, priority, "
        "programming_mode, playback_order, start_date, end_date, "
        "contracted_plays_per_day, is_active) "
        "VALUES (?, 'Logo Test', 'Commercials', 'High', 'Weekly', "
        "'In Rotation', '2026-05-01', '2026-05-03', 2, 1)",
        [f"_test_logo_{uuid.uuid4().hex[:8]}"])
    cid = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO spot_files (campaign_id, filename, file_path, "
        "duration_ms, is_active, display_order) "
        "VALUES (?, 'a.mp3', '', 30000, 1, 0)", [cid])
    conn.commit()
    try:
        yield cid, db
    finally:
        conn.execute("DELETE FROM spot_files WHERE campaign_id = ?", [cid])
        conn.execute("DELETE FROM campaigns WHERE id = ?", [cid])
        conn.commit()


def _gen(cid, db, out: Path) -> Path:
    from core.reports import (generate_spot_play_report,
                              REPORT_MODE_SCHEDULED)
    return generate_spot_play_report(
        cid, REPORT_MODE_SCHEDULED,
        date(2026, 5, 1), date(2026, 5, 3), output_path=out, db=db)


def test_report_renders_without_a_logo(campaign, tmp_path):
    cid, db = campaign
    branding.clear_station_logo()
    out = _gen(cid, db, tmp_path / "nologo.pdf")
    assert out.is_file() and out.stat().st_size > 1000


def test_report_renders_with_a_logo(campaign, tmp_path, logo_env):
    cid, db = campaign
    branding.set_station_logo(_make_image(logo_env / "l.png"))
    out = _gen(cid, db, tmp_path / "withlogo.pdf")
    assert out.is_file() and out.stat().st_size > 1000


def test_report_falls_back_when_logo_file_is_gone(campaign, tmp_path,
                                                   logo_env):
    """The setting still points at a path but the PNG was deleted — the
    report must still produce its header, not raise."""
    cid, db = campaign
    dest = branding.set_station_logo(_make_image(logo_env / "l.png"))
    dest.unlink()
    out = _gen(cid, db, tmp_path / "brokenlogo.pdf")
    assert out.is_file() and out.stat().st_size > 1000
