"""
RadioAI Studio Pro — station branding (operator-supplied logo).

The operator picks an image in Settings → General → Station Identity.
We do NOT keep a pointer to wherever they picked it from: that file can
be moved, renamed or deleted behind the app's back, and a report that
silently loses its logo (or worse, its whole header) is a support call.
Instead the image is validated, normalised to a square PNG and COPIED
into ``paths.BRANDING_DIR``. The settings row then holds a path we own.

Public API
----------
``set_station_logo(src)``   validate + copy + record → Path | None
``station_logo_path()``     the stored logo, or None when unset/missing
``clear_station_logo()``    forget it (the PNG on disk is removed too)
``load_station_logo()``     QImage ready to paint, or None

Consumers (both PDF reports) call ``load_station_logo()`` and fall back
to their painted placeholder tile when it returns None, so a station
with no logo configured looks exactly as it did before this module
existed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage

from core import paths

log = logging.getLogger("Branding")

SETTINGS_KEY = "station_logo_path"

#: The report tile is a 48pt square; store at 4× so it stays crisp when
#: the PDF is zoomed or printed, without keeping a huge bitmap around.
LOGO_STORE_PX = 192

#: File name inside BRANDING_DIR. Fixed so a re-upload replaces the old
#: one instead of littering the folder.
LOGO_FILENAME = "station_logo.png"

SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


def _settings():
    from core.settings import Settings
    return Settings()


def logo_file() -> Path:
    """Canonical on-disk location (may not exist)."""
    return paths.BRANDING_DIR / LOGO_FILENAME


def _square_crop(img: QImage) -> QImage:
    """Centre-crop to a square, then scale to LOGO_STORE_PX.

    The report paints into a 48×48 rounded tile, so a non-square upload
    would otherwise be stretched. Centre-cropping keeps the logo's
    proportions and puts its middle in the tile.
    """
    w, h = img.width(), img.height()
    if w != h:
        side = min(w, h)
        img = img.copy((w - side) // 2, (h - side) // 2, side, side)
    return img.scaled(
        LOGO_STORE_PX, LOGO_STORE_PX,
        Qt.AspectRatioMode.IgnoreAspectRatio,      # already square
        Qt.TransformationMode.SmoothTransformation)


def set_station_logo(src: str | Path) -> Optional[Path]:
    """Validate ``src``, store a normalised square PNG, record the path.

    Returns the stored Path, or None when the file is missing, is not a
    readable image, or cannot be written. Never raises — the caller is a
    UI button and should show a friendly message on None.
    """
    try:
        src_path = Path(str(src)).expanduser()
    except Exception:
        return None
    if not src_path.is_file():
        log.warning(f"set_station_logo: no such file {src_path}")
        return None
    if src_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        log.warning(f"set_station_logo: unsupported type {src_path.suffix!r}")
        return None

    img = QImage(str(src_path))
    if img.isNull() or img.width() <= 0 or img.height() <= 0:
        log.warning(f"set_station_logo: not a readable image {src_path}")
        return None

    dest = logo_file()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not _square_crop(img).save(str(dest), "PNG"):
            log.error(f"set_station_logo: could not write {dest}")
            return None
    except (OSError, PermissionError) as exc:
        log.error(f"set_station_logo: write failed {dest}: {exc}")
        return None

    try:
        _settings().set(SETTINGS_KEY, str(dest))
    except Exception as exc:
        log.error(f"set_station_logo: settings write failed: {exc}")
        return None
    log.info(f"station logo set from {src_path.name} → {dest}")
    return dest


def station_logo_path() -> Optional[Path]:
    """The configured logo, or None when unset or gone from disk."""
    try:
        raw = (_settings().get(SETTINGS_KEY, "") or "").strip()
    except Exception:
        return None
    if not raw:
        return None
    p = Path(raw)
    if not p.is_file():
        # Don't clear the setting — the folder may be temporarily
        # unavailable. Callers just fall back to the painted tile.
        log.warning(f"station logo missing on disk: {p}")
        return None
    return p


def load_station_logo() -> Optional[QImage]:
    """QImage for painting, or None. Cheap enough for per-page use."""
    p = station_logo_path()
    if p is None:
        return None
    img = QImage(str(p))
    if img.isNull():
        log.warning(f"station logo unreadable: {p}")
        return None
    return img


def clear_station_logo() -> None:
    """Forget the logo and remove the copy we own. Idempotent."""
    p = logo_file()
    try:
        if p.is_file():
            p.unlink()
    except (OSError, PermissionError) as exc:
        log.warning(f"clear_station_logo: could not delete {p}: {exc}")
    try:
        _settings().set(SETTINGS_KEY, "")
    except Exception as exc:
        log.warning(f"clear_station_logo: settings write failed: {exc}")
    log.info("station logo cleared")
