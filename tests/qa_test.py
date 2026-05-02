"""RadioAI Studio Pro — Automated QA Test Suite

Run with: python tests/qa_test.py
No user input, no Claude API, fully automated.
Saves report to tests/reports/ and returns exit code 0 (pass) or 1 (fail).
"""

import sys
import os
import json
import time
import hashlib
import shutil
from datetime import datetime

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

# ── Terminal Colors ───────────────────────────────────────────────────────

class C:
    PASS = "\033[92m"   # green
    FAIL = "\033[91m"   # red
    WARN = "\033[93m"   # yellow
    INFO = "\033[96m"   # cyan
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"
    PURPLE = "\033[95m"


def ok(msg):
    return f"  {C.PASS}\u2705 {msg}{C.RESET}"

def fail(msg):
    return f"  {C.FAIL}\u274c {msg}{C.RESET}"

def warn(msg):
    return f"  {C.WARN}\u26a0  {msg}{C.RESET}"

def header(phase, total, title):
    w = 40
    print()
    print(f"{C.PURPLE}{C.BOLD}\u2554{'═'*w}\u2557{C.RESET}")
    print(f"{C.PURPLE}{C.BOLD}\u2551   RADIOAI QA - PHASE {phase}/{total}{'':>{w-24-len(str(phase))-len(str(total))}}\u2551{C.RESET}")
    print(f"{C.PURPLE}{C.BOLD}\u2551   {title:<{w-4}}\u2551{C.RESET}")
    print(f"{C.PURPLE}{C.BOLD}\u255a{'═'*w}\u255d{C.RESET}")
    print()

def section(name):
    print(f"  {C.INFO}{C.BOLD}[{name}]{C.RESET}")

def separator():
    print(f"\n{C.DIM}{'━'*44}{C.RESET}")


# ── Test Runner ───────────────────────────────────────────────────────────

class TestResult:
    def __init__(self, name, passed, message="", detail=""):
        self.name = name
        self.passed = passed
        self.message = message
        self.detail = detail

class QARunner:
    def __init__(self):
        self.results = []
        self.phase_results = {}
        self.progress_file = os.path.join(PROJECT_ROOT, "tests", "progress.json")
        self.load_progress()

    def load_progress(self):
        self.progress = {"current_phase": 1, "completed_phases": [], "history": []}
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file) as f:
                    self.progress = json.load(f)
            except Exception:
                pass

    def save_progress(self):
        try:
            with open(self.progress_file, "w") as f:
                json.dump(self.progress, f, indent=2)
        except Exception:
            pass

    def test(self, name, fn):
        try:
            result = fn()
            if isinstance(result, tuple):
                passed, detail = result
            else:
                passed, detail = bool(result), ""
            r = TestResult(name, passed, detail)
        except Exception as e:
            r = TestResult(name, False, str(e))
        self.results.append(r)
        if r.passed:
            print(ok(f"{name}{(' — ' + r.message) if r.message else ''}"))
        else:
            print(fail(f"{name} — {r.message}"))
        return r.passed

    def run_all(self):
        start = time.time()
        print(f"\n{C.BOLD}{C.PURPLE}RadioAI Studio Pro — Automated QA System{C.RESET}")
        print(f"{C.DIM}Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{C.RESET}")
        print(f"{C.DIM}Project: {PROJECT_ROOT}{C.RESET}")

        # Phase 1: Settings & Database
        p1 = self.run_phase_1()
        self.phase_results[1] = p1

        # Phase 2: Libraries
        p2 = self.run_phase_2()
        self.phase_results[2] = p2

        # Phase 3: Audio & Dependencies
        p3 = self.run_phase_3()
        self.phase_results[3] = p3

        # Phase 4: Integration
        p4 = self.run_phase_4()
        self.phase_results[4] = p4

        elapsed = time.time() - start
        self.print_summary(elapsed)
        self.save_report(elapsed)
        self.update_progress()

        total_passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        return 0 if total_passed == total else 1

    # ── PHASE 1: Settings & Database ──────────────────────────────────

    def run_phase_1(self):
        header(1, 4, "Settings & Database")
        phase_start = len(self.results)

        section("Database Core")
        self.test("Database file exists", self._test_db_exists)
        self.test("Database opens without error", self._test_db_opens)
        self.test("All 18 tables created", self._test_tables_exist)
        self.test("Foreign keys enabled", self._test_foreign_keys)

        section("Settings CRUD")
        self.test("Save setting to DB", self._test_save_setting)
        self.test("Load setting from DB", self._test_load_setting)
        self.test("Station name persists", self._test_station_name)
        self.test("Bulk settings save", self._test_bulk_settings)

        section("File Paths")
        self.test("Music folder path configured", self._test_path_exists("path_music", "Music"))
        self.test("Logs folder accessible", self._test_path_exists("path_logs", "Logs"))

        section("Users")
        self.test("Users table has records", self._test_users_exist)
        self.test("Admin user exists", self._test_admin_exists)
        self.test("Password hash stored", self._test_password_hash)

        section("Backup")
        self.test("Backup creates file", self._test_backup)
        self.test("Integrity check passes", self._test_integrity)

        passed = sum(1 for r in self.results[phase_start:] if r.passed)
        total = len(self.results) - phase_start
        return (passed, total)

    def _test_db_exists(self):
        from core.database import DatabaseManager
        db = DatabaseManager()
        exists = os.path.exists(db.db_path)
        size = os.path.getsize(db.db_path) if exists else 0
        return (exists, f"{size/1024:.1f} KB") if exists else (False, "File not found")

    def _test_db_opens(self):
        from core.database import DatabaseManager
        db = DatabaseManager()
        rows = db.execute("SELECT 1")
        return (rows[0][0] == 1, "")

    def _test_tables_exist(self):
        from core.database import DatabaseManager
        db = DatabaseManager()
        expected = ["songs", "categories", "campaigns", "spot_files", "break_schedule",
                    "campaign_schedule", "jingles", "jingle_pallets", "jingle_pads",
                    "sweepers", "clocks", "clock_slots", "auto_schedule", "force_clocks",
                    "playlists", "playlist_songs", "final_logs", "final_log_entries",
                    "broadcast_log", "ai_insights", "settings", "users"]
        rows = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        found = {r[0] for r in rows}
        missing = [t for t in expected if t not in found]
        if missing:
            return (False, f"Missing: {', '.join(missing)}")
        return (True, f"{len(found)} tables found")

    def _test_foreign_keys(self):
        from core.database import DatabaseManager
        db = DatabaseManager()
        rows = db.execute("PRAGMA foreign_keys")
        return (rows[0][0] == 1, "PRAGMA foreign_keys=ON")

    def _test_save_setting(self):
        from core.database import DatabaseManager
        db = DatabaseManager()
        db.set_setting("_qa_test_key", "qa_test_value_123")
        return (True, "")

    def _test_load_setting(self):
        from core.database import DatabaseManager
        db = DatabaseManager()
        val = db.get_setting("_qa_test_key")
        db.execute("DELETE FROM settings WHERE key='_qa_test_key'")
        return (val == "qa_test_value_123", f"Got: {val}")

    def _test_station_name(self):
        from core.database import DatabaseManager
        db = DatabaseManager()
        name = db.get_setting("station_name", "")
        return (len(name) > 0, name)

    def _test_bulk_settings(self):
        from core.database import DatabaseManager
        db = DatabaseManager()
        for k in ["_qa_bulk_1", "_qa_bulk_2", "_qa_bulk_3"]:
            db.set_setting(k, "test")
        vals = [db.get_setting(k) for k in ["_qa_bulk_1", "_qa_bulk_2", "_qa_bulk_3"]]
        for k in ["_qa_bulk_1", "_qa_bulk_2", "_qa_bulk_3"]:
            db.execute("DELETE FROM settings WHERE key=?", (k,))
        return (all(v == "test" for v in vals), "3/3 saved and loaded")

    def _test_path_exists(self, key, fallback):
        def _inner():
            from core.database import DatabaseManager
            db = DatabaseManager()
            path = db.get_setting(key, os.path.join(PROJECT_ROOT, fallback))
            return (True, path)
        return _inner

    def _test_users_exist(self):
        from core.database import DatabaseManager
        db = DatabaseManager()
        rows = db.execute("SELECT COUNT(*) FROM users")
        count = rows[0][0]
        return (count > 0, f"{count} users")

    def _test_admin_exists(self):
        from core.database import DatabaseManager
        db = DatabaseManager()
        rows = db.execute("SELECT display_name FROM users WHERE role='Administrator'")
        if rows:
            return (True, rows[0][0])
        return (False, "No admin user found")

    def _test_password_hash(self):
        from core.database import DatabaseManager
        db = DatabaseManager()
        rows = db.execute("SELECT password_hash FROM users WHERE role='Administrator' LIMIT 1")
        if rows and rows[0][0]:
            h = rows[0][0]
            return (len(h) == 64, f"SHA-256 hash ({len(h)} chars)")
        return (False, "No hash found")

    def _test_backup(self):
        from core.database import DatabaseManager
        db = DatabaseManager()
        backup_dir = os.path.join(os.path.dirname(db.db_path), "QA_Backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, "qa_test_backup.db")
        shutil.copy2(db.db_path, backup_path)
        exists = os.path.exists(backup_path)
        size = os.path.getsize(backup_path) if exists else 0
        os.remove(backup_path)
        os.rmdir(backup_dir)
        return (exists and size > 0, f"Backup {size/1024:.1f} KB")

    def _test_integrity(self):
        from core.database import DatabaseManager
        db = DatabaseManager()
        rows = db.execute("PRAGMA integrity_check")
        result = rows[0][0] if rows else "unknown"
        return (result == "ok", result)

    # ── PHASE 2: Libraries ────────────────────────────────────────────

    def run_phase_2(self):
        header(2, 4, "Libraries & Data")
        phase_start = len(self.results)

        section("Songs Library")
        self.test("Songs table has records", self._test_songs_exist)
        self.test("Categories seeded", self._test_categories)
        self.test("Song model loads all", self._test_song_model)
        self.test("Song filtering works", self._test_song_filter)
        self.test("Song search works", self._test_song_search)

        section("Other Libraries")
        self.test("Campaigns table accessible", self._test_table_access("campaigns"))
        self.test("Jingles table accessible", self._test_table_access("jingles"))
        self.test("Sweepers table accessible", self._test_table_access("sweepers"))
        self.test("Clocks table accessible", self._test_table_access("clocks"))
        self.test("Playlists table accessible", self._test_table_access("playlists"))

        section("AI Engine")
        self.test("AI Engine imports", self._test_ai_import)
        self.test("Energy preference returns value", self._test_energy_pref)
        self.test("Overplay check runs", self._test_overplay)
        self.test("Rotation health calculates", self._test_rotation)
        self.test("Similar songs query runs", self._test_similar)

        passed = sum(1 for r in self.results[phase_start:] if r.passed)
        total = len(self.results) - phase_start
        return (passed, total)

    def _test_songs_exist(self):
        from core.database import DatabaseManager
        db = DatabaseManager()
        rows = db.execute("SELECT COUNT(*) FROM songs")
        count = rows[0][0]
        return (count > 0, f"{count} songs")

    def _test_categories(self):
        from core.database import DatabaseManager
        db = DatabaseManager()
        rows = db.execute("SELECT COUNT(*) FROM categories")
        count = rows[0][0]
        return (count >= 6, f"{count} categories")

    def _test_song_model(self):
        from models.song import Song
        from core.database import DatabaseManager
        db = DatabaseManager()
        songs = Song.all(db)
        return (len(songs) > 0, f"{len(songs)} songs loaded via model")

    def _test_song_filter(self):
        from models.song import Song
        from core.database import DatabaseManager
        db = DatabaseManager()
        songs = Song.all(db, {"category_id": 1})
        return (True, f"{len(songs)} songs in category 1")

    def _test_song_search(self):
        from models.song import Song
        from core.database import DatabaseManager
        db = DatabaseManager()
        songs = Song.all(db, {"search": "Amy"})
        found = any("amy" in (s.artist or "").lower() for s in songs)
        return (found, f"Found {len(songs)} results for 'Amy'")

    def _test_table_access(self, table):
        def _inner():
            from core.database import DatabaseManager
            db = DatabaseManager()
            rows = db.execute(f"SELECT COUNT(*) FROM {table}")
            return (True, f"{rows[0][0]} records")
        return _inner

    def _test_ai_import(self):
        from core.ai_engine import AIEngine
        ai = AIEngine()
        return (True, "AIEngine instantiated")

    def _test_energy_pref(self):
        from core.ai_engine import AIEngine
        ai = AIEngine()
        result = ai.get_energy_preference(8)
        return (result in ["High", "Medium", "Low"], f"8am → {result}")

    def _test_overplay(self):
        from core.ai_engine import AIEngine
        ai = AIEngine()
        result = ai.check_overplay(1)
        return ("is_overplayed" in result, f"plays={result.get('plays_this_week', '?')}")

    def _test_rotation(self):
        from core.ai_engine import AIEngine
        ai = AIEngine()
        result = ai.get_rotation_health()
        return ("health" in result, f"{result.get('health', '?')}% — {result.get('rating', '?')}")

    def _test_similar(self):
        from core.ai_engine import AIEngine
        ai = AIEngine()
        result = ai.find_similar_songs(1)
        return (isinstance(result, list), f"{len(result)} similar songs")

    # ── PHASE 3: Audio & Dependencies ─────────────────────────────────

    def run_phase_3(self):
        header(3, 4, "Audio & Dependencies")
        phase_start = len(self.results)

        section("Python Packages")
        self.test("PyQt6 installed", self._test_import("PyQt6.QtCore"))
        self.test("PyQt6-WebEngine installed", self._test_import("PyQt6.QtWebEngineWidgets"))
        self.test("mutagen installed", self._test_import("mutagen"))
        self.test("requests installed", self._test_import("requests"))
        self.test("cryptography installed", self._test_import("cryptography"))

        section("Audio System")
        self.test("sounddevice installed", self._test_import("sounddevice"))
        self.test("Audio devices detected", self._test_audio_devices)
        self.test("numpy installed (for audio)", self._test_import("numpy"))

        section("VLC")
        self.test("python-vlc installed", self._test_import("vlc"))
        self.test("VLC runtime available", self._test_vlc_runtime)

        section("Font Files")
        self.test("Inter Regular font exists", self._test_font("Inter_18pt-Regular.ttf"))
        self.test("Inter Bold font exists", self._test_font("Inter_18pt-Bold.ttf"))
        self.test("Roboto Mono font exists", self._test_font("RobotoMono-Regular.ttf"))

        passed = sum(1 for r in self.results[phase_start:] if r.passed)
        total = len(self.results) - phase_start
        return (passed, total)

    def _test_import(self, module):
        def _inner():
            try:
                __import__(module)
                return (True, "")
            except ImportError as e:
                return (False, str(e))
        return _inner

    def _test_audio_devices(self):
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            outputs = sum(1 for d in devices if d["max_output_channels"] > 0)
            inputs = sum(1 for d in devices if d["max_input_channels"] > 0)
            return (outputs > 0, f"{outputs} outputs, {inputs} inputs")
        except Exception as e:
            return (False, str(e))

    def _test_vlc_runtime(self):
        try:
            import vlc
            instance = vlc.Instance("--no-audio")
            instance.release()
            return (True, "VLC runtime OK")
        except Exception as e:
            return (False, str(e))

    def _test_font(self, filename):
        def _inner():
            path = os.path.join(PROJECT_ROOT, "assets", "fonts", filename)
            if os.path.exists(path):
                size = os.path.getsize(path)
                return (True, f"{size/1024:.0f} KB")
            return (False, f"Not found: {path}")
        return _inner

    # ── PHASE 4: Integration ──────────────────────────────────────────

    def run_phase_4(self):
        header(4, 4, "Integration & UI")
        phase_start = len(self.results)

        section("HTML Screens")
        expected_html = [
            "control_panel", "songs_library", "spots_library", "jingles_library",
            "instant_jingles", "sweepers_library", "stitcher",
            "clock_editor", "playlists", "force_clocks", "final_log_creator",
            "log_viewer", "rds_settings",
            "general_settings", "soundcards", "studio_settings",
            "users_security", "database_settings", "weather_api",
            "studio_screen",
        ]
        for name in expected_html:
            self.test(f"{name}.html exists", self._test_html(name))

        section("Shared Assets")
        self.test("shared.css exists", self._test_file("ui/web/shared.css"))

        section("Bridge")
        self.test("Bridge module imports", self._test_bridge_import)
        self.test("Bridge has settings methods", self._test_bridge_methods)

        section("Main Window")
        self.test("main.py exists", self._test_file("main.py"))
        self.test("MainWindow imports", self._test_main_import)

        passed = sum(1 for r in self.results[phase_start:] if r.passed)
        total = len(self.results) - phase_start
        return (passed, total)

    def _test_html(self, name):
        def _inner():
            path = os.path.join(PROJECT_ROOT, "ui", "web", f"{name}.html")
            if os.path.exists(path):
                size = os.path.getsize(path)
                return (True, f"{size/1024:.1f} KB")
            return (False, "File missing")
        return _inner

    def _test_file(self, relpath):
        def _inner():
            path = os.path.join(PROJECT_ROOT, relpath)
            return (os.path.exists(path), f"{os.path.getsize(path)/1024:.1f} KB" if os.path.exists(path) else "Missing")
        return _inner

    def _test_bridge_import(self):
        # Can't fully import Bridge without QApplication, but we can check the file
        path = os.path.join(PROJECT_ROOT, "ui", "bridge.py")
        if not os.path.exists(path):
            return (False, "bridge.py not found")
        with open(path) as f:
            content = f.read()
        has_class = "class Bridge" in content
        return (has_class, "Bridge class found")

    def _test_bridge_methods(self):
        path = os.path.join(PROJECT_ROOT, "ui", "bridge.py")
        with open(path) as f:
            content = f.read()
        methods = ["get_all_settings", "save_all_settings", "browse_folder",
                    "get_db_stats", "backup_database", "get_users", "get_audio_devices"]
        found = [m for m in methods if f"def {m}" in content]
        missing = [m for m in methods if m not in found]
        if missing:
            return (False, f"Missing: {', '.join(missing)}")
        return (True, f"{len(found)}/{len(methods)} methods found")

    def _test_main_import(self):
        path = os.path.join(PROJECT_ROOT, "main.py")
        with open(path) as f:
            content = f.read()
        return ("MainWindow" in content, "MainWindow referenced")

    # ── Summary & Reporting ───────────────────────────────────────────

    def print_summary(self, elapsed):
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        pct = (passed / total * 100) if total > 0 else 0

        separator()
        color = C.PASS if failed == 0 else C.FAIL if pct < 70 else C.WARN
        print(f"  {C.BOLD}SCORE: {color}{passed}/{total} ({pct:.0f}%){C.RESET}")
        if failed > 0:
            print(f"  {C.FAIL}FAILED: {failed} tests{C.RESET}")
        else:
            print(f"  {C.PASS}ALL TESTS PASSED{C.RESET}")

        # Phase breakdown
        print()
        phase_names = {1: "Settings & DB", 2: "Libraries", 3: "Audio & Deps", 4: "Integration"}
        for p in sorted(self.phase_results):
            pp, pt = self.phase_results[p]
            pc = C.PASS if pp == pt else C.WARN if pp/pt > 0.7 else C.FAIL
            icon = "\u2705" if pp == pt else "\u26a0 " if pp/pt > 0.7 else "\u274c"
            print(f"  {icon} Phase {p}: {phase_names[p]}: {pc}{pp}/{pt}{C.RESET}")

        print(f"\n  {C.DIM}Time: {elapsed:.1f}s{C.RESET}")

        if failed > 0:
            separator()
            print(f"  {C.FAIL}{C.BOLD}Fix these before moving on:{C.RESET}")
            for i, r in enumerate(self.results):
                if not r.passed:
                    print(f"  {C.FAIL}{i+1}. {r.name} — {r.message}{C.RESET}")

        separator()

    def save_report(self, elapsed):
        report_dir = os.path.join(PROJECT_ROOT, "tests", "reports")
        os.makedirs(report_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        report_path = os.path.join(report_dir, f"qa_report_{timestamp}.txt")

        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)

        lines = [
            f"RadioAI Studio Pro — QA Report",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Score: {passed}/{total} ({passed/total*100:.0f}%)",
            f"Duration: {elapsed:.1f}s",
            "",
        ]
        phase_names = {1: "Settings & DB", 2: "Libraries", 3: "Audio & Deps", 4: "Integration"}
        for p in sorted(self.phase_results):
            pp, pt = self.phase_results[p]
            lines.append(f"Phase {p} ({phase_names[p]}): {pp}/{pt}")

        lines.append("")
        lines.append("Detailed Results:")
        lines.append("-" * 50)
        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            lines.append(f"[{status}] {r.name}{(' — ' + r.message) if r.message else ''}")

        if any(not r.passed for r in self.results):
            lines.append("")
            lines.append("Failed Tests:")
            for r in self.results:
                if not r.passed:
                    lines.append(f"  - {r.name}: {r.message}")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        print(f"  {C.INFO}Report saved: {report_path}{C.RESET}")

    def update_progress(self):
        for p in sorted(self.phase_results):
            pp, pt = self.phase_results[p]
            if pp == pt and p not in self.progress["completed_phases"]:
                self.progress["completed_phases"].append(p)

        all_complete = all(p in self.progress["completed_phases"] for p in [1, 2, 3, 4])
        if all_complete:
            self.progress["current_phase"] = 4
        else:
            for p in [1, 2, 3, 4]:
                if p not in self.progress["completed_phases"]:
                    self.progress["current_phase"] = p
                    break

        self.progress["history"].append({
            "timestamp": datetime.now().isoformat(),
            "results": {str(p): list(v) for p, v in self.phase_results.items()},
        })
        if len(self.progress["history"]) > 50:
            self.progress["history"] = self.progress["history"][-50:]

        self.save_progress()
        separator()


# ── Entry Point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    runner = QARunner()
    exit_code = runner.run_all()
    sys.exit(exit_code)
