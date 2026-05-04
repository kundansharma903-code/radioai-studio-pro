"""
RadioAI Studio Pro v2.0 — Database Manager
Applies schema.sql and seeds.sql to the existing radioai.db.
All operations are non-destructive (IF NOT EXISTS / INSERT OR IGNORE).

Usage:
    cd E:\\RadioAI_v2
    py database/db_manager.py           # initialize + seed + verify
    py database/db_manager.py --init    # schema only
    py database/db_manager.py --seed    # seeds only
    py database/db_manager.py --verify  # verify only
"""

import sqlite3
import os
import sys
import argparse

# Force UTF-8 output on Windows terminals
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Resolve DB path even when run from any working directory
_APPDATA  = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
DB_PATH   = os.path.join(_APPDATA, "RadioAI", "radioai.db")
_HERE     = os.path.dirname(os.path.abspath(__file__))
SCHEMA    = os.path.join(_HERE, "schema.sql")
SEEDS     = os.path.join(_HERE, "seeds.sql")

# Tables that MUST exist after initialization
REQUIRED_TABLES = [
    "categories", "songs", "campaigns", "spot_files",
    "jingles", "jingle_pallets", "jingle_pads", "sweepers",
    "clocks", "clock_slots", "auto_schedule", "force_clocks",
    "playlists", "playlist_songs",
    "ai_daily_log", "ai_schedule_status", "ai_schedule_warnings",
    "ai_run_steps", "ai_decisions", "ai_insights",
    "broadcast_log", "final_logs", "final_log_entries",
    "stitcher_config", "settings", "users",
    "break_schedule", "campaign_schedule",
    "spot_schedules", "scheduling_rules",
    "access_log", "schema_migrations",
]

# Indexes that MUST exist
REQUIRED_INDEXES = [
    "idx_songs_category", "idx_songs_enabled", "idx_songs_artist",
    "idx_spot_files_camp", "idx_clock_slots_clk", "idx_auto_sched_day",
    "idx_broadcast_song", "idx_broadcast_when", "idx_broadcast_campaign",
    "idx_broadcast_type", "idx_aidaily_date", "idx_aistatus_date",
    "idx_aiwarn_date", "idx_aisteps_run", "idx_aidecide_run",
    "idx_finallog_date", "idx_finalentry_log", "idx_spot_sched_hour",
]


class DBManager:

    def __init__(self):
        self.db_path = DB_PATH
        self._check_db_exists()

    def _check_db_exists(self):
        if not os.path.exists(self.db_path):
            print(f"⚠  DB not found at: {self.db_path}")
            print("   Creating blank DB (fresh install).")
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        else:
            size_mb = os.path.getsize(self.db_path) / (1024 * 1024)
            print(f"   DB found: {self.db_path}  ({size_mb:.1f} MB)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode  = WAL")
        return conn

    # ── Public API ────────────────────────────────────────────────────

    def initialize(self) -> bool:
        """Apply schema.sql to DB. Safe on existing DB (IF NOT EXISTS)."""
        print("\n[1/3] Applying schema.sql …")
        try:
            sql = open(SCHEMA, encoding="utf-8").read()
            conn = self._connect()
            conn.executescript(sql)
            conn.commit()
            conn.close()
            print("      Schema applied ✅")
            return True
        except Exception as exc:
            print(f"      Schema FAILED ❌  {exc}")
            return False

    def seed(self) -> bool:
        """Apply seeds.sql. INSERT OR IGNORE — never overwrites existing rows."""
        print("\n[2/3] Applying seeds.sql …")
        try:
            sql = open(SEEDS, encoding="utf-8").read()
            conn = self._connect()
            conn.executescript(sql)
            conn.commit()
            conn.close()
            print("      Seeds applied ✅")
            return True
        except Exception as exc:
            print(f"      Seeds FAILED ❌  {exc}")
            return False

    def verify(self) -> bool:
        """Full integrity check. Returns True if everything is healthy."""
        print("\n[3/3] Verifying database …")
        conn = self._connect()
        ok = True

        # ── Table count ───────────────────────────────────────────────
        existing = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing_tables = [t for t in REQUIRED_TABLES if t not in existing]
        print(f"      Tables found   : {len(existing)}")
        if missing_tables:
            print(f"      Missing tables ❌ : {missing_tables}")
            ok = False
        else:
            print(f"      All required tables present ✅")

        # ── Row counts — critical data ─────────────────────────────────
        counts = {}
        for t in [
            "songs", "categories", "campaigns", "clocks",
            "clock_slots", "auto_schedule", "settings",
            "jingles", "ai_daily_log", "broadcast_log",
            "scheduling_rules", "spot_schedules",
        ]:
            if t in existing:
                n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                counts[t] = n

        songs_n = counts.get("songs", 0)
        if songs_n < 395:
            print(f"      Songs: {songs_n}  ❌  (expected 395+)")
            ok = False
        else:
            print(f"      Songs           : {songs_n} ✅  (preserved)")

        for t, n in counts.items():
            if t != "songs":
                print(f"      {t:<25}: {n}")

        # ── Index check ───────────────────────────────────────────────
        existing_idx = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
                " AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        missing_idx = [i for i in REQUIRED_INDEXES if i not in existing_idx]
        print(f"      Indexes found   : {len(existing_idx)}")
        if missing_idx:
            print(f"      Missing indexes ❌ : {missing_idx}")
            ok = False
        else:
            print(f"      All required indexes present ✅")

        # ── Foreign-key integrity ──────────────────────────────────────
        fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_violations:
            print(f"      FK violations   : {len(fk_violations)} ❌")
            for v in fk_violations[:5]:
                print(f"        {v}")
            ok = False
        else:
            print(f"      FK integrity    : OK ✅")

        # ── WAL journal mode ──────────────────────────────────────────
        jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
        print(f"      Journal mode    : {jm}")

        conn.close()
        print()
        if ok:
            print("═══ Database foundation READY for UI development ✅ ═══")
        else:
            print("═══ Database has issues — fix before proceeding ❌ ═══")
        return ok

    def full_report(self) -> None:
        """Detailed table+column report (same as Step 1 audit)."""
        print("\n══ Full DB Report ══")
        conn = self._connect()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        print(f"Total tables: {len(tables)}\n")
        for (t,) in tables:
            cols  = conn.execute(f"PRAGMA table_info({t})").fetchall()
            count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}  [{count} rows]")
            print(f"    {', '.join(c[1] for c in cols)}")
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="RadioAI DB Manager")
    parser.add_argument("--init",   action="store_true", help="Apply schema only")
    parser.add_argument("--seed",   action="store_true", help="Apply seeds only")
    parser.add_argument("--verify", action="store_true", help="Verify only")
    parser.add_argument("--report", action="store_true", help="Full table report")
    args = parser.parse_args()

    print("═══ RadioAI Studio Pro v2.0 — DB Manager ═══")
    dm = DBManager()

    if args.report:
        dm.full_report()
        return

    if args.init:
        dm.initialize()
    elif args.seed:
        dm.seed()
    elif args.verify:
        dm.verify()
    else:
        # Default: full run
        ok1 = dm.initialize()
        ok2 = dm.seed()
        ok3 = dm.verify()
        sys.exit(0 if (ok1 and ok2 and ok3) else 1)


if __name__ == "__main__":
    main()
