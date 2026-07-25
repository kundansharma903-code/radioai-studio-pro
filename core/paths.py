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
import sys
from pathlib import Path

log = logging.getLogger("paths")


# ── Resource path resolver — dev vs PyInstaller frozen ───────────────────
def resource_path(*relative_parts: str) -> Path:
    """Resolve a path under the app's bundled resources folder.

    Works transparently in three modes:

      * Dev (``py main.py`` from source) — project root is the
        parent of the package this module lives in.
      * PyInstaller onefolder build — sys.executable's directory
        is the install folder (where assets/ was bundled).
      * PyInstaller onefile build — sys._MEIPASS points to the
        temp extraction directory.

    Usage:
        from core.paths import resource_path
        img = QPixmap(str(resource_path("assets", "splash.png")))

    Returns a ``Path`` object — caller can ``str()`` if needed."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundle
        base = getattr(sys, "_MEIPASS", None)
        if base is None:
            base = os.path.dirname(sys.executable)
    else:
        # Dev: project root = two dirs up from this file
        # (core/paths.py → core/ → project_root)
        base = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
    return Path(base, *relative_parts)


def is_frozen() -> bool:
    """True if running from a PyInstaller bundle (.exe)."""
    return getattr(sys, "frozen", False)


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
# Operator-supplied branding (station logo). The uploaded image is
# COPIED here rather than referenced in place — an external path can be
# moved or deleted behind the app's back (exactly how 18 jingle rows
# lost their audio on 2026-07-25), and a report must never break
# because of that.
BRANDING_DIR  = APP_DATA_ROOT / "Branding"

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
              REPORTS_DIR, CACHE_DIR, CONFIG_DIR, BACKUPS_DIR,
              BRANDING_DIR):
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


def bootstrap_fresh_database() -> bool:
    """Fresh-install DB bootstrap — runs ``database/schema.sql`` +
    ``database/seeds.sql`` if the database has no tables yet.

    Use case: a clean Windows machine where someone just ran the
    Inno Setup installer. There's no legacy ``%LA%\\RadioAI\\``
    DB to migrate from, and the new ``%LA%\\RadioAI Studio Pro\\
    Database\\radioai.db`` doesn't exist either. Without this, the
    app would launch into a structurally-empty SQLite file and
    crash on the first query (no songs / clocks / categories
    tables exist).

    Resolution order:
      1. ``migrate_legacy_database()`` runs first (called from
         main.py). If a legacy DB exists, it gets copied and this
         bootstrap helper becomes a no-op.
      2. If the file at DB_PATH already has user tables, no-op.
      3. Otherwise, run schema.sql (41 CREATE TABLE IF NOT EXISTS
         statements) and seeds.sql (13 INSERT OR IGNORE statements
         for default categories, settings, etc.). The file at
         DB_PATH is created cleanly if it didn't already exist.

    Returns True if bootstrap actually ran; False if no-op (DB
    already had tables). Never raises — any IO failure is logged
    and returns False so the boot path doesn't crash."""
    import sqlite3
    try:
        schema_path = resource_path("database", "schema.sql")
        seeds_path = resource_path("database", "seeds.sql")
        if not schema_path.exists():
            log.warning(
                f"[paths] schema.sql not found at {schema_path} — "
                f"cannot bootstrap fresh DB")
            return False

        ensure_dirs()

        # Quick check: does the DB already have user tables?
        # sqlite_master lists every CREATE'd object; if any
        # non-sqlite_ table exists, the DB is already populated.
        conn = sqlite3.connect(str(DB_PATH))
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'").fetchone()
            existing_tables = int(row[0] or 0) if row else 0
        finally:
            conn.close()

        if existing_tables > 0:
            return False    # DB already has tables — no bootstrap

        # Empty DB — apply schema + seeds
        log.info(
            f"[paths] empty database detected at {DB_PATH} — "
            f"bootstrapping fresh schema + seeds (first launch on "
            f"this machine, no legacy DB to migrate)")
        conn = sqlite3.connect(str(DB_PATH))
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
            n_tables = int(conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table'").fetchone()[0] or 0)
            log.info(
                f"[paths] schema applied ({n_tables} tables created)")
            if seeds_path.exists():
                with open(seeds_path, "r", encoding="utf-8") as f:
                    conn.executescript(f.read())
                log.info(f"[paths] seeds applied ({seeds_path.name})")
            else:
                log.warning(
                    f"[paths] seeds.sql not bundled at {seeds_path}")
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as exc:
        log.warning(f"[paths] fresh-DB bootstrap failed: {exc}")
        return False


def _quick_check(path) -> bool:
    """True when SQLite reports 'ok' for the file. Read-only URI open
    so a missing file is never created as a side effect."""
    import sqlite3
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            conn.close()
    except Exception:
        return False


def ensure_database_health() -> str:
    """Launch-time DB safety net (added 2026-07-02 after three real
    corruption incidents in two days — processes killed mid-WAL-write
    corrupted the live DB, and the app then ran a broken session with
    silently-failing writes, e.g. a blank Studio History panel).

    1. ``PRAGMA quick_check`` on the live DB.
    2. Healthy → refresh a once-per-day auto-backup in
       ``BACKUPS_DIR/auto/radioai_auto_YYYYMMDD.db`` (newest 7 kept).
    3. Malformed → quarantine db+wal+shm into
       ``BACKUPS_DIR/corrupt_<ts>/`` and restore the NEWEST auto-backup
       that itself passes quick_check. Self-heal beats a broken session.

    Returns a status string for the boot log: ``healthy`` /
    ``healthy+backup`` / ``restored:<name>`` / ``corrupt-no-backup`` /
    ``skipped:<reason>``.
    """
    import sqlite3
    from datetime import datetime

    if not DB_PATH.exists():
        return "skipped:no-db"
    auto_dir = BACKUPS_DIR / "auto"
    auto_dir.mkdir(parents=True, exist_ok=True)

    if _quick_check(DB_PATH):
        today_name = f"radioai_auto_{datetime.now():%Y%m%d}.db"
        dest = auto_dir / today_name
        if dest.exists():
            return "healthy"
        try:
            src = sqlite3.connect(str(DB_PATH))
            dst = sqlite3.connect(str(dest))
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            # prune to the newest 7 (names sort chronologically)
            backups = sorted(auto_dir.glob("radioai_auto_*.db"))
            for old in backups[:-7]:
                try:
                    old.unlink()
                except Exception:
                    pass
            return "healthy+backup"
        except Exception as exc:
            log.warning(f"[paths] auto-backup failed: {exc}")
            return "healthy"

    # ── Malformed: quarantine + restore newest healthy backup ──
    log.error(
        "[paths] DATABASE CORRUPT at launch (quick_check failed) — "
        "attempting auto-restore from the newest healthy backup")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    quarantine = BACKUPS_DIR / f"corrupt_{ts}"
    quarantine.mkdir(parents=True, exist_ok=True)
    for ext in ("", "-wal", "-shm"):
        p = Path(str(DB_PATH) + ext)
        if p.exists():
            try:
                shutil.move(str(p), str(quarantine / p.name))
            except Exception as exc:
                log.warning(f"[paths] quarantine of {p.name} failed: {exc}")
    for cand in sorted(auto_dir.glob("radioai_auto_*.db"), reverse=True):
        if _quick_check(cand):
            shutil.copy2(str(cand), str(DB_PATH))
            log.warning(
                f"[paths] database auto-restored from {cand.name}; "
                f"corrupt files preserved in {quarantine}")
            return f"restored:{cand.name}"
    log.error(
        "[paths] no healthy auto-backup available — the corrupt DB was "
        f"quarantined to {quarantine}; a fresh DB will be bootstrapped")
    return "corrupt-no-backup"


# Create folders on first import so any caller that just reads
# DB_PATH / LOGS_DIR can trust them to exist.
ensure_dirs()
