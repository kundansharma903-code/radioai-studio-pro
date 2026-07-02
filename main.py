"""
RadioAI Studio Pro v2.0 — Entry Point
Startup sequence:
  1. setup_logging
  2. prevent_sleep (Windows)
  3. QApplication
  4. load style.qss
  5. BASS audio init
  6. Database.verify()
  7. Settings.load()
  8. MainWindow (1440×900)
  9. app.exec()
  10. AudioEngine.shutdown → bass_free → allow_sleep on exit
"""

import sys
import os
import logging

# Force UTF-8 on Windows terminals (dev mode). In PyInstaller's
# console=False GUI build, sys.stdout / sys.stderr are None (no
# console attached), so the .buffer access would crash on launch
# from Windows Explorer. Guard accordingly — this code only does
# meaningful work when an interactive console is actually attached.
if sys.platform == "win32":
    import io
    if sys.stdout is not None and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace")
    if sys.stderr is not None and hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace")

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase, QIcon

# ── Project root on sys.path ──────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from core.logger import setup_logging, get_logger
from core.sleep_prevent import prevent_sleep, allow_sleep
from core.audio_engine import bass_init, bass_free
from core.database import Database
from core.settings import Settings

log = get_logger("main")


def load_fonts() -> int:
    """Register all .ttf files in assets/fonts/ with QFontDatabase.
    Must be called AFTER QApplication is created."""
    from core.paths import resource_path
    fonts_dir = str(resource_path("assets", "fonts"))
    if not os.path.isdir(fonts_dir):
        log.warning(f"fonts dir not found: {fonts_dir}")
        return 0
    loaded = 0
    for fname in sorted(os.listdir(fonts_dir)):
        if not fname.lower().endswith((".ttf", ".otf")):
            continue
        path = os.path.join(fonts_dir, fname)
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id == -1:
            log.error(f"Font load failed: {fname}")
        else:
            families = QFontDatabase.applicationFontFamilies(font_id)
            log.info(f"Font loaded: {fname} -> {families}")
            loaded += 1
    return loaded


def verify_inter_weights() -> None:
    """One-shot startup check: log which Inter weight styles QFontDatabase
    actually registered. The Studio premium typography uses Black /
    Bold / SemiBold weights — if any are missing, log a warning so
    operators / future-us notice typography is rendering at fallback.

    QFont auto-falls-back gracefully (Qt picks the closest available
    weight), so a missing Black isn't fatal — just visually less
    crisp. This check surfaces the situation rather than masking it.
    """
    families = QFontDatabase.families()
    inter_families = [f for f in families if "Inter" in f]
    if not inter_families:
        log.warning("[font check] No Inter family registered — Studio "
                    "typography will fall back to default sans-serif")
        return
    target_family = "Inter Variable"
    if target_family not in families:
        # Variable font registers under multiple names; fall back to
        # the first Inter-prefixed one we find.
        target_family = inter_families[0]
    styles = QFontDatabase.styles(target_family)
    log.info(f"[font check] Inter family={target_family!r} "
             f"styles={styles}")
    # Normalize both sides — Inter Variable registers SemiBold without
    # a space ("Text SemiBold"), and the substring check would falsely
    # miss it if we wrote "Semi Bold". Strip whitespace + lowercase
    # both sides so "Semi Bold" / "SemiBold" / "Text SemiBold" all
    # match equivalently.
    def _norm(s: str) -> str:
        return s.replace(" ", "").lower()
    norm_styles = [_norm(st) for st in styles]
    needed = ["Black", "Bold", "Semi Bold", "Medium"]
    missing = [s for s in needed
               if not any(_norm(s) in ns for ns in norm_styles)]
    if missing:
        log.warning(f"[font check] Inter missing weights: {missing} — "
                    f"Qt will substitute the closest available weight")


def load_stylesheet(app: QApplication) -> bool:
    # Prefer premium.qss (built for Phase 2+); fall back to style.qss
    from core.paths import resource_path
    for name in ("premium.qss", "style.qss"):
        qss_path = str(resource_path("assets", name))
        if os.path.exists(qss_path):
            try:
                with open(qss_path, encoding="utf-8") as f:
                    app.setStyleSheet(f.read())
                log.info(f"{name} loaded")
                return True
            except Exception as exc:
                log.error(f"Failed to load {name}: {exc}")
    log.warning("No QSS stylesheet found")
    return False


def main():
    # 1. Logging
    setup_logging(debug="--debug" in sys.argv)
    log.info("=" * 60)
    log.info("RadioAI Studio Pro v2.0 starting")
    log.info("=" * 60)

    # 2. Sleep prevention
    prevent_sleep()
    log.info("Sleep prevention active")

    # 3. Windows AppUserModelID — must be set BEFORE QApplication.
    # Without this, ``py main.py`` shows Python's default icon in
    # the taskbar (because Windows identifies the process as Python,
    # not as RadioAI). After PyInstaller packaging (Phase M), the
    # .exe carries its own identity and this hack is unnecessary,
    # but it's essential during dev to verify the icon shows up.
    if sys.platform == "win32":
        try:
            import ctypes
            APP_ID = "RadioAI.StudioPro.2.0"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                APP_ID)
            log.info(f"Windows AppUserModelID set: {APP_ID}")
        except Exception as exc:
            log.warning(f"AppUserModelID set failed: {exc}")

    # 3. QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("RadioAI Studio Pro")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("RadioAI")
    # High-DPI: PyQt6 enables it by default — no extra flags needed.

    # 3a. App icon — shown in the Windows taskbar, in the title bar
    # of every QWidget that doesn't override windowIcon, in the
    # Alt-Tab switcher, and (Phase M) embedded as the .exe file
    # icon visible in Windows Explorer. resource_path resolves
    # both dev and PyInstaller-frozen modes correctly.
    from core.paths import resource_path
    icon_path = str(resource_path("assets", "icon.png"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
        log.info(f"App icon set: {icon_path}")
    else:
        log.warning(f"App icon missing at {icon_path}")

    # 4. Splash screen — shown immediately, before any heavy init.
    # Stays visible through every init step below; status text +
    # progress bar update as each step completes; fades out + closes
    # when MainWindow.show() is called.
    from ui.splash import RadioAISplash
    splash = RadioAISplash(total_steps=8)
    splash.show_animated()

    # Per-step dwell — DB / Settings / BASS init each complete in
    # <100ms on a modern machine, so without artificial dwell the
    # splash flashes past in ~2s and the operator can't read any
    # of the status messages. We target a ~10s total splash window,
    # which gives the operator enough time to read each message +
    # see the progress bar fill smoothly. Dwell uses a local
    # QEventLoop — animations keep running, no thread block.
    STEP_DWELL_MS = 1000

    # ── Step 1: Connecting to database ───────────────────────────────
    splash.set_status("Connecting to database...", step=1)
    splash.dwell(STEP_DWELL_MS)
    # Phase L: migrate legacy %LOCALAPPDATA%\RadioAI\radioai.db to
    # the new professional %LOCALAPPDATA%\RadioAI Studio Pro\
    # Database\radioai.db location if needed. No-op after the first
    # successful run. Safe — uses copy (not move), so the legacy
    # DB is preserved as a backup.
    from core.paths import (
        migrate_legacy_database, bootstrap_fresh_database,
    )
    if migrate_legacy_database():
        log.info(
            "[boot] legacy database migrated to new professional "
            "folder layout. Old file preserved as backup.")
    # Phase N+: fresh-install bootstrap — if the migration was a
    # no-op (no legacy DB exists, which is the case on every
    # brand-new Windows machine), check whether the DB at the new
    # path has any tables. If not, apply schema.sql + seeds.sql so
    # Database() finds a properly-initialised structure when it
    # opens its connection moments later.
    if bootstrap_fresh_database():
        log.info(
            "[boot] fresh database bootstrapped from schema + "
            "seeds (no legacy DB found — first-launch path).")
    # DB safety net: quick_check + once-a-day auto-backup; a corrupt
    # DB is quarantined and auto-restored from the newest healthy
    # backup BEFORE Database() opens its connection (2026-07-02:
    # three corruption incidents in two days — the app must
    # self-heal, not run a broken session with silently-failing
    # writes like a blank History panel).
    try:
        from core.paths import ensure_database_health
        _health = ensure_database_health()
        log.info(f"[boot] database health: {_health}")
        if _health == "corrupt-no-backup" and bootstrap_fresh_database():
            log.warning(
                "[boot] fresh empty database bootstrapped after "
                "unrecoverable corruption")
    except Exception as exc:
        log.warning(f"[boot] database health check failed: {exc}")
    db = Database()
    db_ok = db.verify()
    song_count = 0
    if db_ok:
        try:
            rows = db._conn().execute(
                "SELECT COUNT(*) FROM songs").fetchone()
            song_count = rows[0] if rows else 0
        except Exception:
            pass
        # Auto-schedule audit log
        try:
            from datetime import datetime as _dt
            now = _dt.now()
            grid = db.get_auto_schedule_grid()
            row = db.get_active_clock(int(now.weekday()),
                                       int(now.hour))
            active = (f"clock id={row['id']} name={row['name']!r}"
                      if row is not None
                      else "(no clock assigned)")
            log.info(
                f"Auto-schedule grid: {len(grid)} cells assigned · "
                f"current cell (weekday={now.weekday()}, "
                f"hour={now.hour}) → {active}")
        except Exception as exc:
            log.warning(f"auto_schedule audit log failed: {exc}")
    else:
        log.error("Database verification failed — launching anyway")

    # ── Step 2: Loading settings ─────────────────────────────────────
    splash.set_status("Loading settings...", step=2)
    splash.dwell(STEP_DWELL_MS)
    settings = Settings()
    settings.load(db)
    # Fonts (must be loaded before stylesheet so fontDatabase is ready)
    n_fonts = load_fonts()
    log.info(f"Fonts registered: {n_fonts}")
    verify_inter_weights()
    load_stylesheet(app)

    # ── Step 3: Initializing audio engine ────────────────────────────
    splash.set_status("Initializing audio engine...", step=3)
    splash.dwell(STEP_DWELL_MS)
    if not bass_init():
        log.warning(
            "BASS audio init failed — playback will be unavailable")
    else:
        log.info("BASS audio ready")

    # ── Step 4: Querying audio devices ───────────────────────────────
    splash.set_status("Querying audio devices...", step=4)
    splash.dwell(STEP_DWELL_MS)
    # BASS itself handles device discovery during bass_init above.
    # This step exists to acknowledge it on the splash UI for the
    # operator + leaves a hook for richer device introspection later.
    log.info("Audio device subsystem ready (handled by BASS)")

    # ── Step 5: Loading clocks and schedules ─────────────────────────
    splash.set_status("Loading clocks and schedules...", step=5)
    splash.dwell(STEP_DWELL_MS)
    try:
        clock_count = db._conn().execute(
            "SELECT COUNT(*) FROM clocks WHERE is_active=1"
        ).fetchone()[0]
        slot_count = db._conn().execute(
            "SELECT COUNT(*) FROM clock_slots").fetchone()[0]
        log.info(f"Clocks: {clock_count} active · "
                 f"clock_slots: {slot_count}")
    except Exception as exc:
        log.warning(f"clock count preload failed: {exc}")

    # ── Step 6: Loading songs library ────────────────────────────────
    splash.set_status("Loading songs library...", step=6)
    splash.dwell(STEP_DWELL_MS)
    try:
        cat_count = db._conn().execute(
            "SELECT COUNT(*) FROM categories").fetchone()[0]
        log.info(f"Songs library: {song_count} songs · "
                 f"{cat_count} categories")
    except Exception as exc:
        log.warning(f"songs library preload failed: {exc}")

    # ── Step 7: Preparing AI engine ──────────────────────────────────
    splash.set_status("Preparing AI engine...", step=7)
    splash.dwell(STEP_DWELL_MS)
    # Rotation AI engine + SOTG transcription engine are constructed
    # inside MainWindow's __init__ — splash text accurately reflects
    # the work the next step is about to do.

    # ── Step 8: Starting Studio ──────────────────────────────────────
    splash.set_status("Starting Studio...", step=8)
    splash.dwell(STEP_DWELL_MS)
    from ui.main_window import MainWindow
    window = MainWindow(db_ok=db_ok, song_count=song_count, db=db)
    if "--maximized" in sys.argv:
        window.showMaximized()
        log.info("Window shown maximized")
    else:
        window.show()
        log.info(
            f"Window shown — outer={window.width()}x{window.height()}"
            f"  client={window.centralWidget().width()}x"
            f"{window.centralWidget().height()}")

    # Fade out the splash + transfer focus to the main window
    splash.finish_animated(window)

    # 9. Event loop
    exit_code = app.exec()

    # 10. Cleanup
    bass_free()
    allow_sleep()
    log.info(f"RadioAI Studio Pro exiting (code {exit_code})")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
