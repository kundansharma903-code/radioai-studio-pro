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

import hashlib
import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("BackupRestore")

# A staged restore is applied at boot only if it was staged this recently
# AND the staged file still matches the size + SHA256 recorded when it
# was staged (QA ⚠29, operator 2026-10-19). A months-old leftover marker
# once silently replaced the live DB on boot. The operator restarts within
# minutes of staging; anything older is refused and offered on screen.
RESTORE_MAX_AGE_H = 24
_TS = "%Y-%m-%d %H:%M:%S"

# What the boot step did, for the post-launch notice (main.py):
# {"status": "none" | "applied" | "refused", "reason", "staged_at",
#  "source", "safety_copy"}.
LAST_RESTORE: dict = {"status": "none"}

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
    None on failure. Read-only w.r.t. the live DB.

    Uses SQLite's online backup API — a consistent snapshot that
    includes changes still sitting in the WAL. The previous checkpoint
    + file copy ignored the checkpoint's "busy" result: with the app's
    other connections open, the latest changes could silently miss the
    backup (2026-10-16). The daily auto-backup already used this API."""
    src = _db_path()
    if not src.exists():
        log.warning("[backup] no live DB to back up")
        return None
    try:
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        out = dest / f"RadioAI_backup_{stamp}.db"
        if not _snapshot(src, out):
            return None
        log.info(f"[backup] station backed up -> {out}")
        return str(out)
    except Exception as exc:
        log.error(f"[backup] backup failed: {exc}", exc_info=True)
        return None


def _snapshot(src: Path, out: Path) -> bool:
    """Online-backup `src` into `out` via a .partial temp file, validate,
    then atomically rename. False (and nothing left behind) on failure."""
    tmp = out.with_suffix(".db.partial")
    s_con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d_con = sqlite3.connect(str(tmp))
    try:
        s_con.backup(d_con)
    finally:
        d_con.close()
        s_con.close()
    if not is_valid_radioai_db(tmp):
        tmp.unlink(missing_ok=True)
        log.error("[backup] snapshot failed validation — not saved")
        return False
    os.replace(str(tmp), str(out))
    return True


# ── Scheduled auto-backup (General Settings → Backup card) ───────────────

# The old form default — never chosen by an operator, so it means
# "not set": use the real app-data auto folder instead.
LEGACY_DEFAULT_BACKUP_PATH = "C:\\RadioAI\\Backups\\"

AUTO_BACKUP_KEEP = 7

_INTERVAL_HOURS = {
    "Every 6 hours": 6, "Every 12 hours": 12, "Every 24 hours": 24,
    "Every 3 days": 72, "Every 7 days": 168, "Manual only": None,
}


def default_auto_backup_dir() -> Path:
    from core.paths import BACKUPS_DIR
    return Path(BACKUPS_DIR) / "auto"


def resolve_auto_backup_dir(path_backup: Optional[str]) -> Path:
    """`path_backup` setting -> folder. Empty / legacy default -> the
    app-data auto folder (where the once-per-launch backup also goes)."""
    raw = (path_backup or "").strip()
    if not raw or raw.rstrip("/\\").lower() == \
            LEGACY_DEFAULT_BACKUP_PATH.rstrip("\\").lower():
        return default_auto_backup_dir()
    return Path(raw)


def interval_hours(label: Optional[str]) -> Optional[int]:
    """'Every 24 hours' -> 24. 'Manual only' / unknown -> None (off)."""
    return _INTERVAL_HOURS.get((label or "").strip())


def _auto_files(dest: Path) -> list:
    return sorted(Path(dest).glob("radioai_auto_*.db"),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def auto_backup_due(dest_dir, hours: Optional[int],
                    now: Optional[datetime] = None) -> bool:
    """True when `hours` is set and the newest auto-backup in
    `dest_dir` is at least that old (or there is none)."""
    if not hours:
        return False
    now = now or datetime.now()
    try:
        files = _auto_files(Path(dest_dir))
    except Exception:
        files = []
    if not files:
        return True
    newest = datetime.fromtimestamp(files[0].stat().st_mtime)
    return (now - newest).total_seconds() >= hours * 3600


def run_auto_backup(dest_dir, keep: int = AUTO_BACKUP_KEEP) -> Optional[str]:
    """Write ``radioai_auto_YYYYMMDD_HHMM.db`` into `dest_dir` and prune
    to the newest `keep` auto files there. Safe off the UI thread (pure
    sqlite3, no Qt). Returns the written path or None."""
    src = _db_path()
    if not src.exists():
        return None
    try:
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / f"radioai_auto_{datetime.now():%Y%m%d_%H%M}.db"
        if not _snapshot(src, out):
            return None
        for old in _auto_files(dest)[keep:]:
            try:
                old.unlink()
            except Exception:
                pass
        log.info(f"[backup] scheduled auto-backup -> {out}")
        return str(out)
    except Exception as exc:
        log.error(f"[backup] scheduled auto-backup failed: {exc}",
                  exc_info=True)
        return None


def latest_auto_backup_time(dest_dir=None) -> Optional[str]:
    """'YYYY-MM-DD HH:MM' of the newest auto-backup, or None. Looks in
    `dest_dir` (the configured backup folder) and the default app-data
    auto folder, and returns the newer."""
    newest = None
    dirs = [default_auto_backup_dir()]
    if dest_dir:
        dirs.insert(0, Path(dest_dir))
    for d in dirs:
        try:
            files = _auto_files(d)
            if files:
                m = files[0].stat().st_mtime
                newest = m if newest is None else max(newest, m)
        except Exception:
            pass
    if newest is None:
        return None
    return datetime.fromtimestamp(newest).strftime("%Y-%m-%d %H:%M")


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
        _write_marker(staging, str(src_file))
        log.info(f"[restore] staged {src_file} — applies on next launch")
        return True
    except Exception as exc:
        log.error(f"[restore] staging failed: {exc}", exc_info=True)
        _clear_staging()
        return False


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_marker(staging: Path, source: str,
                  when: Optional[datetime] = None) -> None:
    """Marker v2: what was staged, when, and the staged file's identity."""
    marker = {
        "v": 2,
        "staged_at": (when or datetime.now()).strftime(_TS),
        "source": source,
        "size": staging.stat().st_size,
        "sha256": _sha256(staging),
    }
    with open(_marker_path(), "w", encoding="utf-8") as f:
        json.dump(marker, f)


def _read_marker() -> Optional[dict]:
    """The v2 marker, or None for a missing / unreadable / legacy one
    (legacy markers were plain 'time\\nsource' text, written before the
    QA ⚠29 check existed — they are treated as stale)."""
    try:
        with open(_marker_path(), encoding="utf-8") as f:
            m = json.load(f)
        return m if isinstance(m, dict) and m.get("v") == 2 else None
    except Exception:
        return None


def _refuse_reason(staging: Path, marker: Optional[dict],
                   now: datetime, max_age_h: float) -> Optional[str]:
    """Why this staged restore must NOT be applied silently, or None."""
    if marker is None:
        return "its marker is from an older version or unreadable"
    try:
        staged_at = datetime.strptime(str(marker.get("staged_at")), _TS)
    except (TypeError, ValueError):
        return "its marker has no valid staging time"
    age = now - staged_at
    if age > timedelta(hours=max_age_h):
        return (f"it was staged {staged_at:%Y-%m-%d %H:%M}, more than "
                f"{max_age_h:g} h ago")
    if age < timedelta(minutes=-5):
        return f"its staging time {staged_at:%Y-%m-%d %H:%M} is in the future"
    try:
        if (staging.stat().st_size != int(marker.get("size") or -1)
                or _sha256(staging) != marker.get("sha256")):
            return "the staged file does not match what was staged"
    except Exception as exc:
        return f"the staged file could not be checked ({exc})"
    return None


def has_pending_restore() -> bool:
    return _marker_path().exists() and _staging_path().exists()


def pending_restore_info() -> dict:
    """{staged_at, source} of the pending restore (best effort)."""
    m = _read_marker() or {}
    if not m:
        try:
            lines = _marker_path().read_text(encoding="utf-8").splitlines()
            m = {"staged_at": lines[0] if lines else "",
                 "source": lines[1] if len(lines) > 1 else ""}
        except Exception:
            m = {}
    return {"staged_at": str(m.get("staged_at") or "unknown time"),
            "source": str(m.get("source") or "unknown source")}


def approve_pending_restore() -> bool:
    """Operator chose "Apply on Next Restart" for a refused restore:
    re-stamp the marker for NOW with the staged file's current identity,
    so the next boot applies it."""
    staging = _staging_path()
    if not staging.exists() or not is_valid_radioai_db(staging):
        return False
    _write_marker(staging, pending_restore_info()["source"])
    log.warning("[restore] operator approved the pending restore — "
                "applies on next launch")
    return True


def discard_pending_restore() -> None:
    """Operator chose "Don't Apply": set the staged file and marker aside
    (renamed, never deleted — nothing is lost) so it stops coming back."""
    stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    for p in (_staging_path(), _marker_path()):
        try:
            if p.exists():
                p.rename(p.with_name(p.name + f".discarded_{stamp}"))
        except Exception as exc:
            log.warning(f"[restore] could not set aside {p.name}: {exc}")
    log.warning("[restore] operator declined the pending restore — "
                "set aside, live database unchanged")


def _clear_staging() -> None:
    for p in (_staging_path(), _marker_path()):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


def apply_staged_restore(now: Optional[datetime] = None,
                         max_age_h: float = RESTORE_MAX_AGE_H) -> bool:
    """BOOT hook — call BEFORE opening any DB connection. If a valid
    staged restore is pending, replace radioai.db with it, remove the
    stale WAL/SHM, and clear the staging slot. Returns True when a
    restore was applied. Safe: operates only on closed files.

    Applied ONLY when the marker is current-format, at most ``max_age_h``
    old, and the staged file still matches its recorded size + SHA256
    (QA ⚠29). Otherwise nothing is replaced, the staged files are KEPT,
    and LAST_RESTORE tells the post-launch notice to ask the operator."""
    LAST_RESTORE.clear()
    LAST_RESTORE["status"] = "none"
    if not has_pending_restore():
        return False
    staging = _staging_path()
    info = pending_restore_info()
    if not is_valid_radioai_db(staging):
        log.warning("[restore] staged file invalid — discarding")
        _clear_staging()
        return False
    reason = _refuse_reason(staging, _read_marker(), now or datetime.now(),
                            max_age_h)
    if reason:
        LAST_RESTORE.update(status="refused", reason=reason, **info)
        log.warning(f"[restore] NOT applied — {reason} "
                    f"(staged {info['staged_at']} from {info['source']}); "
                    f"live database unchanged, staged file kept")
        return False
    db = _db_path()
    pre = None
    try:
        db.parent.mkdir(parents=True, exist_ok=True)
        # Keep the pre-restore DB as a safety copy (never silently lose
        # data — if the operator restores by mistake they can recover).
        # SQLite backup API, so changes still in the WAL are in the
        # safety copy (a plain file copy missed them, and the WAL is
        # deleted just below). If the safety copy fails, ABORT: the
        # current data is untouched and the restore is not applied.
        if db.exists():
            pre = db.with_suffix(
                db.suffix + f".pre_restore_"
                f"{datetime.now():%Y%m%d_%H%M%S}")
            try:
                s_con = sqlite3.connect(str(db))
                d_con = sqlite3.connect(str(pre))
                try:
                    s_con.backup(d_con)
                finally:
                    d_con.close()
                    s_con.close()
            except Exception as exc:
                # e.g. an unreadable/corrupt DB: fall back to copying the
                # main file WITH its -wal/-shm so nothing is lost.
                log.warning(f"[restore] backup-API safety copy failed "
                            f"({exc}); copying db+wal+shm instead")
                try:
                    shutil.copy2(str(db), str(pre))
                    for ext in ("-wal", "-shm"):
                        side = Path(str(db) + ext)
                        if side.exists():
                            shutil.copy2(str(side), str(pre) + ext)
                except Exception as exc2:
                    log.error(f"[restore] safety copy failed - restore "
                              f"ABORTED, current data untouched: {exc2}",
                              exc_info=True)
                    _clear_staging()
                    return False
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
        LAST_RESTORE.update(status="applied", reason="", **info,
                            safety_copy=str(pre) if pre else "")
        log.warning(f"[restore] APPLIED — database replaced with the "
                    f"backup from {info['source']} (staged "
                    f"{info['staged_at']}); previous database kept as "
                    f"{pre}")
        _clear_staging()
        return True
    except Exception as exc:
        log.error(f"[restore] apply failed: {exc}", exc_info=True)
        _clear_staging()
        return False
