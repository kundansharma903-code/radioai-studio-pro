"""
Visual layout audit — render every screen offscreen and save PNGs.

Usage:  py scripts/audit_screens.py
Output: design_refs/audit/<screen>.png (design_refs is untracked)

No engines are started (engine/scheduler params get None), no BASS
init, DB is opened read-mostly through the normal Database singleton.
Each screen is constructed exactly the way MainWindow does, then
widget.grab() captures the composed pixmap at native canvas size.
"""

from __future__ import annotations

import os
import sys
import traceback

# Native platform gives real font rendering (Inter/Segoe); widgets are
# grabbed without show() so nothing flashes on the operator's screen.
# Set AUDIT_OFFSCREEN=1 to force the offscreen platform (CI).
if os.environ.get("AUDIT_OFFSCREEN") == "1":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "design_refs", "audit")


def main() -> int:
    app = QApplication(sys.argv)

    # Same stylesheet cascade as main.py
    from core.paths import resource_path
    for name in ("premium.qss", "style.qss"):
        p = resource_path("assets", name)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                app.setStyleSheet(f.read())
            break

    from core.database import Database
    db = Database()
    os.makedirs(OUT_DIR, exist_ok=True)

    def shot(name: str, builder) -> None:
        try:
            w = builder()
            w.setAttribute
            pm = w.grab()
            path = os.path.join(OUT_DIR, f"{name}.png")
            pm.save(path, "PNG")
            print(f"OK   {name:<32} {pm.width()}x{pm.height()}")
            w.deleteLater()
        except Exception as exc:
            print(f"FAIL {name:<32} {exc}")
            traceback.print_exc(limit=2)

    def b(mod, cls, *a, **k):
        def _make():
            m = __import__(f"ui.{mod}", fromlist=[cls])
            return getattr(m, cls)(*a, **k)
        return _make

    shots = [
        ("control_panel",       b("control_panel", "ControlPanel", db)),
        ("songs_library",       b("songs_library", "SongsLibrary", db,
                                  engine=None)),
        ("category_move",       b("category_move", "CategoryMove", db)),
        ("instant_jingles",     b("instant_jingles", "InstantJingles", db,
                                  engine=None)),
        ("spots_commercials",   b("spots_commercials", "SpotsCommercials",
                                  db, engine=None)),
        ("sweepers_library",    b("sweepers_library", "SweepersLibrary", db,
                                  engine=None)),
        ("jingles_library",     b("jingles_library", "JinglesLibrary", db,
                                  engine=None)),
        ("stitcher",            b("stitcher", "Stitcher", db, engine=None)),
        ("final_log",           b("final_log", "FinalLog", db,
                                  scheduler=None)),
        ("settings_general",    b("settings_general", "SettingsGeneral", db)),
        ("settings_hub",        b("settings_hub", "SettingsHub", db)),
        ("settings_soundcard",  b("settings_soundcard", "SettingsSoundcard",
                                  db)),
        ("settings_studio",     b("settings_studio", "SettingsStudio", db)),
        ("play_history",        b("play_history", "PlayHistory", db)),
        ("category_performance", b("category_performance",
                                   "CategoryPerformance", db)),
        ("rotation_health",     b("rotation_health", "RotationHealthScreen",
                                  db=db, engine=None)),
        ("ai_magic_hub",        b("ai_magic_hub", "AIMagicHub", db)),
        ("spot_on_the_go_shell", b("spot_on_the_go_shell",
                                   "SpotOnTheGoShell", db)),
        ("sotg_create_schedule", b("sotg_create_schedule",
                                   "SOTGCreateSchedule", db)),
        ("sotg_assign",         b("sotg_assign", "SOTGAssign", db,
                                  engine=None)),
        ("sotg_generate_report", b("sotg_generate_report",
                                   "SOTGGenerateReport", db)),
        ("sotg_assign_api_key", b("sotg_assign_api_key", "SOTGAssignAPIKey",
                                  db, engine=type("_StubTx", (), {
                                      "queue_depth": lambda self: 0,
                                      "is_enabled": lambda self: False,
                                      "is_alive": lambda self: False,
                                      "reload_settings":
                                          lambda self: None,
                                      "enqueue_backfill":
                                          lambda self, *a, **k: 0})())),
        ("scheduling_automation_hub", b("scheduling_automation_hub",
                                        "SchedulingAutomationHub",
                                        db=db, engine=None)),
        ("scheduling_daily_plan_review", b("scheduling_daily_plan_review",
                                           "SchedulingDailyPlanReview",
                                           db=db)),
        ("scheduling_hub",      b("scheduling_hub", "SchedulingHub", db,
                                  scheduler=None)),
        ("playlists",           b("playlists", "Playlists", db,
                                  scheduler=None, studio=None, engine=None)),
        ("playlist_new",        b("playlist_new", "PlaylistNew", db,
                                  scheduler=None, engine=None)),
        ("auto_schedule",       b("auto_schedule", "AutoSchedule", db,
                                  scheduler=None)),
        ("clock_editor",        b("clock_editor", "ClockEditor", db,
                                  scheduler=None)),
        ("playlist_edit",       b("playlist_edit", "PlaylistEdit", db,
                                  scheduler=None, engine=None)),
        ("studio",              b("studio", "Studio", db, engine=None,
                                  scheduler=None,
                                  instant_jingle_engine=None)),
    ]

    for name, builder in shots:
        shot(name, builder)

    print(f"\nPNGs in: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
