"""
RadioAI Studio Pro — Centralised filesystem paths (Phase L).

Single source of truth for every runtime path the app uses to read
or write data. Replaces the legacy ``%LOCALAPPDATA%\\RadioAI\\``
flat layout with a professional Adobe / Logic-Pro-style hierarchy
under ``%LOCALAPPDATA%\\RadioAI Studio Pro\\`` so each kind of data
gets its own folder:

    %LOCALAPPDATA%\\RadioAI Studio Pro\\
        Database\\radioai.db        — SQLite DB
        Logs\\                       — rotating app log
        Reports\\                    — SOTG daily PDFs + spot play reports
        Cache\\                      — transcripts, transient files
        Config\\                     — user JSON overrides (future)
        Backups\\                    — operator-triggered DB backups

The four target subfolders are created on import (idempotent — no
error if they already exist).

LEGACY MIGRATION
----------------
Operators upgrading from the old flat layout
(``%LOCALAPPDATA%\\RadioAI\\radioai.db``) get a one-time, fully
safe migration:

  1. ``migrate_legacy_database()`` is called early in main.py boot
     (before Database() is instantiated).
  2. If the new DB file already exists at the new path: no-op.
  3. If only the legacy DB exists: it's COPIED (not moved) to the
     new path. The old file stays where it was as a safety backup.
     Operator can delete the old folder manually after verifying
     the new install runs cleanly for a few sessions.
  4. If neither exists: no-op (fresh-install path, ``Database()``
     will create a new DB at the new path).

The COPY approach (vs. move/rename) is deliberate: if anything
goes wrong after migration, the operator's untouched original DB
is still at the old location. No data-loss path.

LEGACY EXPORTS (don't remove)
-----------------------------
``core.constants`` re-exports ``DB_PATH`` and ``LOG_PATH`` from
this module for backward compatibility. All existing code paths
that ``from core.constants import DB_PATH`` keep working — they
now resolve to the new location automatically.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger("paths")


# ── App brand constants — used for folder naming ─────────────────────────
APP_FOLDER_NAME = "RadioAI Studio Pro"
LEGACY_FOLDER_NAME = "RadioAI"

# Resolve the user's local AppData directory. On non-Windows
# (tests / future Mac/Linux ports) fall back to ~/AppData/Local
# under home — keeps the codebase portable without changing path
# semantics on Windows.
_LOCAL_APPDATA = os.environ.get(
    "LOCALAPPDATA",
    os.path.expanduser("~/AppData/Local"))


# ── Public path constants ────────────────────────────────────────────────
APP_DATA_ROOT = Path(_LOCAL_APPDATA) / APP_FOLDER_NAME

DB_DIR        = APP_DATA_ROOT / "Database"
LOGS_DIR      = APP_DATA_ROOT / "Logs"
REPORTS_DIR   = APP_DATA_ROOT / "Reports"
CACHE_DIR     = APP_DATA_ROOT / "Cache"
CONFIG_DIR    = APP_DATA_ROOT / "Config"
BACKUPS_DIR   = APP_DATA_ROOT / "Backups"

# Direct file paths
DB_PATH       = DB_DIR / "radioai.db"
LOG_PATH      = LOGS_DIR   # logger writes radioai.log + rotated backups here

# Legacy paths — only used by the migration helper
LEGACY_ROOT   = Path(_LOCAL_APPDATA) / LEGACY_FOLDER_NAME
LEGACY_DB     = LEGACY_ROOT / "radioai.db"
LEGACY_LOGS   = LEGACY_ROOT / "logs"


def ensure_dirs() -> None:
    """Create the professional folder hierarchy if missing. Idempotent
    — safe to call on every boot."""
    for d in (APP_DATA_ROOT, DB_DIR, LOGS_DIR,
              REPORTS_DIR, CACHE_DIR, CONFIG_DIR, BACKUPS_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as exc:
            log.warning(f"could not create {d}: {exc}")


def migrate_legacy_database() -> bool:
    """One-time, safe migration of the legacy
    ``%LOCALAPPDATA%\\RadioAI\\radioai.db`` to the new
    ``%LOCALAPPDATA%\\RadioAI Studio Pro\\Database\\radioai.db``.

    Behavior:
      * If new DB already exists → no-op (no risk of overwriting
        a freshly-set-up install).
      * If only legacy DB exists → COPY to new location. Legacy
        file is left in place as backup.
      * If neither exists → no-op (fresh install path).

    Returns True if a migration was actually performed (operator
    might want to log this prominently); False if no-op.

    Never raises — any IO error is logged and we fall through
    without breaking the boot path."""
    try:
        if DB_PATH.exists():
            # New DB already present — no migration needed.
            return False
        if not LEGACY_DB.exists():
            # Fresh install — no legacy data to migrate.
            return False
        # Migration path
        ensure_dirs()
        log.info(
            f"[paths] migrating legacy DB: {LEGACY_DB} → {DB_PATH}")
        shutil.copy2(str(LEGACY_DB), str(DB_PATH))
        # SQLite WAL companion files — copy if present so a
        # mid-transaction snapshot doesn't get lost. Harmless if
        # they don't exist.
        for sfx in ("-wal", "-shm"):
            src = LEGACY_DB.with_suffix(LEGACY_DB.suffix + sfx)
            if src.exists():
                dst = DB_PATH.with_suffix(DB_PATH.suffix + sfx)
                shutil.copy2(str(src), str(dst))
        log.info(
            f"[paths] migration done — legacy file preserved at "
            f"{LEGACY_DB} as backup")
        return True
    except Exception as exc:
        log.warning(f"[paths] legacy DB migration failed: {exc}")
        return False


# Create folders on first import so any caller that just reads
# DB_PATH / LOGS_DIR can trust them to exist.
ensure_dirs()
