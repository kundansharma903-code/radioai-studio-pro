"""
RadioAI — Station Backup & Restore (operator-approved 2026-07-09).

Goal: one-click safety net so a corrupted / deleted / relocated
database never means re-entering every song, category and spot.

Same-machine version updates already keep the data automatically (the
DB lives in %LOCALAPPDATA%, outside the install folder, and the schema
is idempotent). This module adds the operator-facing recovery path:

  • backup_now(dest)   — checkpoint the WAL, then copy radioai.db to a
                         timestamped file the operator chooses (e.g. on
                         the music drive). Read-only on the live DB.
  • stage_restore(src) — validate that `src` is a real RadioAI DB, copy
                         it into a staging slot and drop a marker. Does
                         NOT touch the live DB — the operator restarts.
  • apply_staged_restore() — called at BOOT, before any DB connection,
                         if a marker exists: replace radioai.db with the
                         staged copy, delete the stale WAL/SHM, clear the
                         marker. This restart-based swap is why restore
                         can never corrupt a live/open database (the
                         2026-07 corruption incidents were all live-DB
                         mutations under force-kill).

Everything is best-effort + logged; a backup/restore failure must never
crash the broadcast app.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("BackupRestore")

# Tables whose presence proves a file is a genuine RadioAI database
# (guards Restore against the operator picking a random .db).
_SIGNATURE_TABLES = ("songs", "categories", "settings", "campaigns")


def _db_path() -> Path:
    from core.paths import DB_PATH
    return Path(DB_PATH)


def _staging_path() -> Path:
    from core.paths import DB_DIR
    return Path(DB_DIR) / "_restore_staged.db"


def _marker_path() -> Path:
    from core.paths import DB_DIR
    return Path(DB_DIR) / "_restore.marker"


# ── Validation ───────────────────────────────────────────────────────────

def is_valid_radioai_db(path) -> bool:
    """True when `path` is a readable SQLite file containing the core
    RadioAI tables. Used to reject a wrong file before staging it."""
    p = Path(path)
    if not p.exists() or p.stat().st_size < 1024:
        return False
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            names = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
    except Exception:
        return False
    return all(t in names for t in _SIGNATURE_TABLES)


def _checkpoint(db_file: Path) -> None:
    """Fold the WAL into the main file so the copy is self-contained."""
    try:
        con = sqlite3.connect(str(db_file))
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            con.close()
    except Exception as exc:
        log.warning(f"[backup] checkpoint failed (copying anyway): {exc}")


# ── Backup ───────────────────────────────────────────────────────────────

def backup_now(dest_dir) -> Optional[str]:
    """Copy the live DB to `dest_dir` as
    ``RadioAI_backup_YYYY-MM-DD_HH-MM.db``. Returns the written path, or
    None on failure. Read-only w.r.t. the live DB (checkpoint + copy2)."""
    src = _db_path()
    if not src.exists():
        log.warning("[backup] no live DB to back up")
        return None
    try:
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        _checkpoint(src)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        out = dest / f"RadioAI_backup_{stamp}.db"
        shutil.copy2(str(src), str(out))
        log.info(f"[backup] station backed up -> {out}")
        return str(out)
    except Exception as exc:
        log.error(f"[backup] backup failed: {exc}", exc_info=True)
        return None


def latest_auto_backup_time() -> Optional[str]:
    """'YYYY-MM-DD HH:MM' of the newest auto-backup, or None."""
    try:
        from core.paths import BACKUPS_DIR
        auto = Path(BACKUPS_DIR) / "auto"
        files = sorted(auto.glob("radioai_auto_*.db"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return datetime.fromtimestamp(
                files[0].stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return None


# ── Restore (staged; applied at next boot) ───────────────────────────────

def stage_restore(src_file) -> bool:
    """Validate `src_file` and stage it for restore on the next launch.
    The live DB is NOT touched here — the operator restarts and
    apply_staged_restore() performs the swap safely. Returns True when
    staged."""
    if not is_valid_radioai_db(src_file):
        log.warning(f"[restore] rejected — not a RadioAI DB: {src_file}")
        return False
    try:
        staging = _staging_path()
        shutil.copy2(str(src_file), str(staging))
        with open(_marker_path(), "w", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\n{src_file}\n")
        log.info(f"[restore] staged {src_file} — applies on next launch")
        return True
    except Exception as exc:
        log.error(f"[restore] staging failed: {exc}", exc_info=True)
        _clear_staging()
        return False


def has_pending_restore() -> bool:
    return _marker_path().exists() and _staging_path().exists()


def _clear_staging() -> None:
    for p in (_staging_path(), _marker_path()):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


def apply_staged_restore() -> bool:
    """BOOT hook — call BEFORE opening any DB connection. If a valid
    staged restore is pending, replace radioai.db with it, remove the
    stale WAL/SHM, and clear the staging slot. Returns True when a
    restore was applied. Safe: operates only on closed files."""
    if not has_pending_restore():
        return False
    staging = _staging_path()
    if not is_valid_radioai_db(staging):
        log.warning("[restore] staged file invalid — discarding")
        _clear_staging()
        return False
    db = _db_path()
    try:
        db.parent.mkdir(parents=True, exist_ok=True)
        # Keep the pre-restore DB as a safety copy (never silently lose
        # data — if the operator restores by mistake they can recover).
        if db.exists():
            pre = db.with_suffix(
                db.suffix + f".pre_restore_"
                f"{datetime.now():%Y%m%d_%H%M%S}")
            try:
                shutil.copy2(str(db), str(pre))
            except Exception:
                pass
        # Remove stale WAL/SHM so SQLite doesn't replay them over the
        # freshly restored main file.
        for ext in ("-wal", "-shm"):
            side = Path(str(db) + ext)
            if side.exists():
                try:
                    side.unlink()
                except Exception:
                    pass
        shutil.copy2(str(staging), str(db))
        log.info("[restore] staged backup applied — station data "
                 "restored")
        _clear_staging()
        return True
    except Exception as exc:
        log.error(f"[restore] apply failed: {exc}", exc_info=True)
        _clear_staging()
        return False
