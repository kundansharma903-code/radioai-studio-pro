"""RadioAI Studio Pro — Schema-file based DB Manager.

This module is a thin, file-driven wrapper around SQLite that provides:
  * initialize()      — run schema.sql + seeds.sql on a fresh DB
  * run_migrations()  — apply database/migrations/*.sql once each
  * get_connection()  — return a configured sqlite3.Connection
  * backup()          — copy the live DB to a dated .bak file

The legacy `core.database.DatabaseManager` is the singleton the running
app uses (it embeds its own SCHEMA_SQL string). This `DBManager` is the
canonical, file-driven version intended for tooling, tests and future
clean-room installs. Both point at the same on-disk file:

    %LOCALAPPDATA%\\RadioAI\\radioai.db
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


HERE = Path(__file__).resolve().parent
SCHEMA_FILE = HERE / "schema.sql"
SEEDS_FILE = HERE / "seeds.sql"
MIGRATIONS_DIR = HERE / "migrations"


class DBManager:
    """File-driven SQLite manager for RadioAI Studio Pro."""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            local = os.environ.get("LOCALAPPDATA") or str(Path.home())
            app_data = Path(local) / "RadioAI"
            app_data.mkdir(parents=True, exist_ok=True)
            db_path = str(app_data / "radioai.db")
        self.db_path = db_path

    # ── connection ──────────────────────────────────────────────────

    def get_connection(self) -> sqlite3.Connection:
        """Return a sqlite3.Connection with WAL + FK + Row factory set."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ── schema bootstrap ────────────────────────────────────────────

    def initialize(self) -> None:
        """Run schema.sql + seeds.sql against the database.

        Both files use IF NOT EXISTS / INSERT OR IGNORE so this is safe
        to call repeatedly. The migrations table is also created here so
        run_migrations() has something to query.
        """
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.executescript(self._read(SCHEMA_FILE))
            cur.executescript(self._read(SEEDS_FILE))
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    name       TEXT PRIMARY KEY,
                    applied_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
            conn.commit()

    # ── migrations ──────────────────────────────────────────────────

    def run_migrations(self) -> list[str]:
        """Apply every *.sql in migrations/ that hasn't run yet.

        Each migration is recorded in schema_migrations after success.
        ALTER TABLE statements that fail with "duplicate column" are
        treated as already applied so re-running is safe on a DB that
        was previously initialised by the legacy code path.

        Returns the list of migration names that were applied this run.
        """
        if not MIGRATIONS_DIR.exists():
            return []

        applied: list[str] = []
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    name       TEXT PRIMARY KEY,
                    applied_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
            done = {r[0] for r in cur.execute("SELECT name FROM schema_migrations")}

            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.name in done:
                    continue
                self._apply_migration(cur, path)
                cur.execute(
                    "INSERT OR IGNORE INTO schema_migrations (name) VALUES (?)",
                    (path.name,),
                )
                applied.append(path.name)
            conn.commit()
        return applied

    def _apply_migration(self, cur: sqlite3.Cursor, path: Path) -> None:
        """Run one migration file, statement-by-statement.

        Tolerates `duplicate column name` errors so 004_cue_editor and
        similar idempotent ALTERs don't break re-runs against an older
        DB that already has the columns.
        """
        sql = self._read(path)
        # naive but sufficient: split on ';' that ends a line
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
            try:
                cur.execute(stmt)
            except sqlite3.OperationalError as e:
                msg = str(e).lower()
                if "duplicate column" in msg or "already exists" in msg:
                    continue
                raise

    # ── housekeeping ────────────────────────────────────────────────

    def backup(self, dest_dir: str | None = None) -> str:
        """Copy the live DB to a dated .bak file.

        Returns the path of the created backup. Uses sqlite3's online
        backup API so it is safe while the app is running.
        """
        if dest_dir is None:
            dest_dir = str(Path(self.db_path).parent / "backups")
        Path(dest_dir).mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = str(Path(dest_dir) / f"radioai_{stamp}.db")

        src = sqlite3.connect(self.db_path)
        try:
            dst = sqlite3.connect(dest)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return dest

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _read(path: Path) -> str:
        return path.read_text(encoding="utf-8")


# Convenience: run as a script to bootstrap a fresh DB.
if __name__ == "__main__":
    mgr = DBManager()
    print(f"DB path:       {mgr.db_path}")
    mgr.initialize()
    print("schema + seeds: applied")
    applied = mgr.run_migrations()
    if applied:
        print("migrations applied:")
        for name in applied:
            print(f"  - {name}")
    else:
        print("migrations:    nothing new to apply")
