"""
RadioAI Studio Pro — Database Layer
Thread-safe SQLite singleton.
All SQL lives here — no raw queries in UI code.
Schema: %LOCALAPPDATA%/RadioAI/radioai.db (33 tables, see schema.sql)
"""

import sqlite3
import threading
import logging
from typing import Optional, List

from core.constants import DB_PATH

log = logging.getLogger("Database")


class Database:
    """Singleton, thread-local connection pool."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._local = threading.local()
                    cls._instance = inst
                    log.info(f"Database path: {DB_PATH}")
        return cls._instance

    # ── Connection ────────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        """Return a thread-local connection, creating it if needed."""
        if not getattr(self._local, "conn", None):
            conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            self._local.conn = conn
        return self._local.conn

    def verify(self) -> bool:
        """Check DB is reachable and report song count."""
        try:
            count = self._conn().execute(
                "SELECT COUNT(*) FROM songs"
            ).fetchone()[0]
            log.info(f"DB OK — {count} songs loaded")
            return True
        except Exception as exc:
            log.error(f"DB verification failed: {exc}")
            return False

    # ── Songs ─────────────────────────────────────────────────────────────────

    def get_songs(
        self,
        category_id: Optional[int] = None,
        energy: Optional[str] = None,
        vocal: Optional[str] = None,
        search: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[sqlite3.Row]:
        sql = """
            SELECT s.*, c.name AS cat_name, c.color AS cat_color
            FROM   songs s
            LEFT JOIN categories c ON s.category_id = c.id
            WHERE  s.is_enabled = 1
        """
        params: list = []
        if category_id:
            sql += " AND s.category_id = ?"
            params.append(category_id)
        if energy and energy != "Any":
            sql += " AND s.energy = ?"
            params.append(energy)
        if vocal and vocal != "Any":
            sql += " AND s.vocal = ?"
            params.append(vocal)
        if search:
            sql += " AND (s.title LIKE ? OR s.artist LIKE ?)"
            params += [f"%{search}%", f"%{search}%"]
        sql += " ORDER BY s.artist, s.title"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self._conn().execute(sql, params).fetchall()

    def get_song(self, song_id: int) -> Optional[sqlite3.Row]:
        return self._conn().execute(
            """
            SELECT s.*, c.name AS cat_name, c.color AS cat_color
            FROM   songs s
            LEFT JOIN categories c ON s.category_id = c.id
            WHERE  s.id = ?
            """,
            [song_id],
        ).fetchone()

    def get_song_play_stats(self, song_id: int) -> dict:
        """Return {'play_count': int, 'last_played': str|None} for a song.
        Used by the Confirm Delete dialog so the user knows what they're losing."""
        conn = self._conn()
        row = conn.execute(
            "SELECT COUNT(*) AS n, MAX(played_at) AS last "
            "FROM broadcast_log WHERE song_id = ?",
            [int(song_id)],
        ).fetchone()
        return {
            "play_count":  int(row["n"] or 0) if row else 0,
            "last_played": (row["last"] if row else None) or None,
        }

    def delete_song(self, song_id: int) -> None:
        """Permanently remove a song. Handles cascading manually because none
        of the referencing FKs declare ON DELETE CASCADE.

        Strategy:
          - Audit/history tables (broadcast_log, ai_daily_log, ai_decisions)
            → NULL out song_id. Airtime history is precious; we keep the row
              and just clear the link.
          - Membership tables (playlist_songs, final_log_entries)
            → DELETE rows. Without a target song the entry is meaningless.
          - clock_slots.item_id is a soft reference (no FK constraint), but
            we still NULL it to prevent the scheduler from trying to play a
            ghost id.
          - songs row itself is deleted last.

        All steps run in a single transaction; a single rollback on failure.
        """
        sid = int(song_id)
        conn = self._conn()
        try:
            conn.execute("BEGIN")
            # NULL out FK in audit/history tables
            conn.execute("UPDATE broadcast_log SET song_id = NULL WHERE song_id = ?", [sid])
            conn.execute("UPDATE ai_daily_log  SET song_id = NULL WHERE song_id = ?", [sid])
            conn.execute("UPDATE ai_decisions  SET song_id = NULL WHERE song_id = ?", [sid])
            # Soft reference in clock_slots (item_id == song id when slot is locked)
            conn.execute(
                "UPDATE clock_slots SET item_id = 0 "
                "WHERE slot_type = 'song' AND item_id = ?",
                [sid],
            )
            # DELETE membership rows
            conn.execute("DELETE FROM playlist_songs    WHERE song_id = ?", [sid])
            conn.execute("DELETE FROM final_log_entries WHERE song_id = ?", [sid])
            # Finally the song
            conn.execute("DELETE FROM songs WHERE id = ?", [sid])
            conn.commit()
            log.info(f"Song id={sid} deleted")
        except Exception:
            conn.rollback()
            raise

    def get_next_song(
        self,
        category_id: int,
        hour: int,
        date=None,
        exclude_ids: Optional[List[int]] = None,
    ) -> Optional[sqlite3.Row]:
        """
        Jazler-style progressive song selection.
        Level 1: full rules (7-day + 3-day slot separation)
        Level 2: relax slot rule  (7-day only)
        Level 3: any song in category (least recently played)
        """
        exclude = exclude_ids or []
        conn = self._conn()
        h = str(hour).zfill(2)

        # Build NOT IN clause for already-queued songs
        if exclude:
            ex_ph = ",".join("?" * len(exclude))
            ex_clause = f"AND s.id NOT IN ({ex_ph})"
        else:
            ex_clause = ""

        base_select = """
            SELECT s.id, s.title, s.artist, s.file_path,
                   s.duration_ms, s.hook_in_ms, s.hook_out_ms,
                   s.start_point_ms, s.intro_end_ms,
                   s.outro_point_ms, s.mix_point_ms,
                   s.fade_in_ms, s.fade_out_ms,
                   s.category_id, s.energy, s.vocal,
                   c.name AS cat_name, c.color AS cat_color,
                   COALESCE(
                       (SELECT MAX(played_at) FROM broadcast_log
                        WHERE song_id = s.id),
                       '2000-01-01'
                   ) AS last_played
            FROM   songs s
            LEFT JOIN categories c ON s.category_id = c.id
            WHERE  s.category_id = ?
            AND    s.is_enabled = 1
        """

        seven_day = """
            AND s.id NOT IN (
                SELECT song_id FROM broadcast_log
                WHERE  played_at > datetime('now', 'localtime', '-7 days')
                AND    song_id IS NOT NULL
            )
        """
        three_day_slot = f"""
            AND s.id NOT IN (
                SELECT song_id FROM broadcast_log
                WHERE  strftime('%H', played_at) = '{h}'
                AND    played_at > datetime('now', 'localtime', '-3 days')
                AND    song_id IS NOT NULL
            )
        """
        tail = "ORDER BY last_played ASC LIMIT 1"

        attempts = [
            # Level 1 — full rules
            (base_select + ex_clause + seven_day + three_day_slot + tail,
             [category_id] + exclude),
            # Level 2 — relax slot rule
            (base_select + ex_clause + seven_day + tail,
             [category_id] + exclude),
            # Level 3 — any song in category
            (base_select + tail,
             [category_id]),
        ]

        for level, (sql, params) in enumerate(attempts):
            row = conn.execute(sql, params).fetchone()
            if row:
                if level > 0:
                    log.warning(
                        f"Song select level {level + 1} for "
                        f"category_id={category_id} hour={hour}"
                    )
                return row

        log.error(f"No songs found for category_id={category_id}")
        return None

    # ── Broadcast Log ─────────────────────────────────────────────────────────

    def _ensure_broadcast_log_columns(self) -> None:
        """Phase F2 — clock_id + slot_idx columns on broadcast_log
        distinguish scheduler-driven plays from manual ones. Idempotent."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(broadcast_log)").fetchall()}
        adds = [
            ("clock_id",  "INTEGER REFERENCES clocks(id)"),
            ("slot_idx",  "INTEGER"),
        ]
        for col, decl in adds:
            if col not in cols:
                conn.execute(f"ALTER TABLE broadcast_log ADD COLUMN {col} {decl}")
        conn.commit()

    def log_play(
        self,
        entry_type: str,
        song_id: Optional[int] = None,
        campaign_id: Optional[int] = None,
        duration_ms: int = 0,
        deck: str = "A",
        was_manual: int = 0,
        clock_id: Optional[int] = None,
        slot_idx: Optional[int] = None,
    ) -> None:
        self._ensure_broadcast_log_columns()
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO broadcast_log
                (entry_type, song_id, campaign_id, duration_ms,
                 deck, was_manual, operator,
                 clock_id, slot_idx,
                 played_at, actual_time)
            VALUES (?, ?, ?, ?, ?, ?, 'AI AUTO',
                    ?, ?,
                    datetime('now','localtime'),
                    datetime('now','localtime'))
            """,
            [entry_type, song_id, campaign_id, duration_ms, deck, was_manual,
             clock_id, slot_idx],
        )
        conn.commit()

    def get_history(self, limit: int = 20,
                    entry_types: tuple = ("song", "spot")) -> List[sqlite3.Row]:
        """Recent broadcast log entries for the Studio history panel.

        Phase D6: defaults to including BOTH songs and spots so the
        scheduler-triggered spot entries from Phase D4 surface in the
        UI. Pass `entry_types=('song',)` to restrict to songs only."""
        placeholders = ",".join("?" * len(entry_types))
        return self._conn().execute(
            f"""
            SELECT bl.*, s.title, s.artist, s.duration_ms AS song_duration_ms,
                   c.name  AS cat_name,  c.color AS cat_color,
                   cmp.name AS campaign_name
            FROM   broadcast_log bl
            LEFT JOIN songs      s   ON bl.song_id     = s.id
            LEFT JOIN categories c   ON s.category_id  = c.id
            LEFT JOIN campaigns  cmp ON bl.campaign_id = cmp.id
            WHERE  bl.entry_type IN ({placeholders})
            ORDER  BY bl.played_at DESC
            LIMIT  ?
            """,
            [*entry_types, limit],
        ).fetchall()

    # ── Clocks ────────────────────────────────────────────────────────────────

    def get_active_clock(
        self, day_of_week: int, hour: int
    ) -> Optional[sqlite3.Row]:
        """
        Return the clock assigned to this day+hour in the 24×7 grid.
        auto_schedule.hour_start <= hour < auto_schedule.hour_end
        day_of_week: 0=Mon … 6=Sun
        """
        return self._conn().execute(
            """
            SELECT c.*, a.day_of_week, a.hour_start, a.hour_end
            FROM   auto_schedule a
            JOIN   clocks c ON a.clock_id = c.id
            WHERE  a.day_of_week = ?
            AND    a.hour_start <= ?
            AND    a.hour_end   >  ?
            AND    c.is_active  = 1
            LIMIT  1
            """,
            [day_of_week, hour, hour],
        ).fetchone()

    def get_clock_slots(self, clock_id: int) -> List[sqlite3.Row]:
        return self._conn().execute(
            """
            SELECT cs.*, c.name AS cat_name, c.color AS cat_color
            FROM   clock_slots cs
            LEFT JOIN categories c ON cs.category_id = c.id
            WHERE  cs.clock_id = ?
            ORDER  BY cs.slot_order ASC
            """,
            [clock_id],
        ).fetchall()

    def get_all_clocks(self) -> List[sqlite3.Row]:
        return self._conn().execute(
            """
            SELECT c.*, COUNT(cs.id) AS slot_count
            FROM   clocks c
            LEFT JOIN clock_slots cs ON cs.clock_id = c.id
            GROUP  BY c.id
            ORDER  BY c.name
            """,
        ).fetchall()

    # ── Clock CRUD (Phase F2 — Clock Editor) ──────────────────────────────────

    def get_clock(self, clock_id: int) -> Optional[sqlite3.Row]:
        """Single clock row by id. Returns None if not found."""
        return self._conn().execute(
            "SELECT * FROM clocks WHERE id = ?", [int(clock_id)]
        ).fetchone()

    # ── Playlists (Premium-theme Playlists screen — Figma 239:2) ─────────

    def _ensure_playlists_columns(self) -> None:
        """Add the Playlists-screen columns (kind / updated_at) if missing.
        Idempotent — safe to call on every read."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(playlists)").fetchall()}
        adds = [
            ("kind",        "TEXT DEFAULT 'manual'"),     # manual|imported|smart
            ("updated_at",  "TEXT DEFAULT (datetime('now'))"),
        ]
        for col, decl in adds:
            if col not in cols:
                conn.execute(f"ALTER TABLE playlists ADD COLUMN {col} {decl}")
        conn.commit()

    def get_playlists_with_stats(self) -> list[dict]:
        """Return all playlists with computed track count + total duration_ms.

        Each row: {id, name, description, kind, scheduled_day,
                   scheduled_time, is_active, updated_at,
                   track_count, total_duration_ms}.
        Used by the Premium Playlists screen."""
        self._ensure_playlists_columns()
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT p.*,
                   COUNT(ps.id) AS track_count,
                   COALESCE(SUM(s.duration_ms), 0) AS total_duration_ms
            FROM   playlists p
            LEFT JOIN playlist_songs ps ON ps.playlist_id = p.id
            LEFT JOIN songs          s  ON ps.song_id     = s.id
            GROUP  BY p.id
            ORDER  BY (CASE WHEN p.scheduled_day IS NOT NULL AND p.scheduled_day != ''
                            THEN 0 ELSE 1 END),
                      p.updated_at DESC, p.name
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def get_playlist_first_tracks(
        self, playlist_id: int, limit: int = 5
    ) -> list[dict]:
        """First N songs in a playlist, in playback position order."""
        rows = self._conn().execute(
            """
            SELECT s.id, s.title, s.artist, s.duration_ms,
                   s.file_path, ps.position
            FROM   playlist_songs ps
            JOIN   songs s ON ps.song_id = s.id
            WHERE  ps.playlist_id = ?
            ORDER  BY ps.position
            LIMIT  ?
            """,
            [int(playlist_id), int(limit)],
        ).fetchall()
        return [dict(r) for r in rows]

    def set_playlist_scheduled(
        self, playlist_id: int, scheduled_day: Optional[str] = None,
        scheduled_time: Optional[str] = None,
    ) -> None:
        """Mark a playlist as scheduled (or unschedule by passing both
        as None). Stamp updated_at."""
        self._ensure_playlists_columns()
        conn = self._conn()
        from datetime import datetime as _dt
        now_str = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE playlists SET scheduled_day = ?, scheduled_time = ?, "
            "updated_at = ? WHERE id = ?",
            [scheduled_day, scheduled_time, now_str, int(playlist_id)],
        )
        conn.commit()

    def _ensure_clocks_columns(self) -> None:
        """Phase F-Final C3 — add modal-Clock-Editor columns to `clocks`
        if missing. Idempotent — safe to call on every save_clock."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(clocks)").fetchall()}
        adds = [
            ("comments",                "TEXT"),
            ("color",                   "TEXT"),
            ("backup_song_filter",      "TEXT"),
            ("loop_cycle_enabled",      "INTEGER DEFAULT 1"),
            ("show_only_descriptions",  "INTEGER DEFAULT 0"),
        ]
        for col, decl in adds:
            if col not in cols:
                conn.execute(f"ALTER TABLE clocks ADD COLUMN {col} {decl}")
        conn.commit()

    def save_clock(self, clock_id: int, data: dict) -> None:
        """Update top-level clock fields. Slots are saved separately via
        save_clock_slots — same transaction is the caller's job (Studio
        F2 wraps both in one BEGIN/COMMIT for atomic clock-edit save)."""
        self._ensure_clocks_columns()
        conn = self._conn()
        cols_present = {r[1] for r in conn.execute(
            "PRAGMA table_info(clocks)").fetchall()}
        sets, values = [], []
        for k in ("name", "time_start", "time_end", "day_mask",
                  "description", "is_active",
                  # Phase F-Final C3 — modal Clock Editor fields
                  "comments", "color", "backup_song_filter",
                  "loop_cycle_enabled", "show_only_descriptions"):
            if k in cols_present and k in data:
                sets.append(f"{k} = ?")
                values.append(data[k])
        if not sets:
            return
        values.append(int(clock_id))
        conn.execute(
            f"UPDATE clocks SET {', '.join(sets)} WHERE id = ?", values
        )
        conn.commit()

    def _ensure_clock_slots_columns(self) -> None:
        """Add the F2.2.1 + F2.3 + F-Final columns (Figma 59:2 redesign +
        rotation engine + Jazler-style filter slots) if missing.
        Idempotent — safe to call on every save_clock_slots."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(clock_slots)").fetchall()}
        adds = [
            ("fallback_category_id", "INTEGER REFERENCES categories(id)"),
            ("pin_to_time",          "INTEGER NOT NULL DEFAULT 0"),
            # F2.3 (Figma 59:2 per-type panels)
            ("duration_seconds",     "INTEGER"),
            ("ref_text",             "TEXT"),
            # F-Final S1-S5 (rotation engine)
            ("selection_mode",       "TEXT DEFAULT 'random_from_category'"),
            # F-Final C3 (ref 225:5 — Jazler filter-based slots)
            ("filter_json",          "TEXT"),
            ("specific_song_id",     "INTEGER REFERENCES songs(id)"),
            ("specific_artist_id",   "INTEGER"),
            ("minute_position",      "INTEGER DEFAULT 0"),
        ]
        added_minute_position = False
        for col, decl in adds:
            if col not in cols:
                conn.execute(f"ALTER TABLE clock_slots ADD COLUMN {col} {decl}")
                if col == "minute_position":
                    added_minute_position = True
        # If minute_position is brand-new, backfill from slot_order so
        # existing data renders on the circular face. Rough heuristic:
        # 4-min slots, slot 1 → 0min, slot 2 → 4min, …
        if added_minute_position:
            conn.execute(
                "UPDATE clock_slots SET minute_position = "
                "((slot_order - 1) * 4) % 60 "
                "WHERE minute_position IS NULL OR minute_position = 0"
            )
        conn.commit()

    def _ensure_voice_tracks_table(self) -> None:
        """Create voice_tracks if missing (Phase F-Final). Idempotent."""
        conn = self._conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_tracks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                file_path   TEXT,
                duration_ms INTEGER DEFAULT 0,
                valid_from  TEXT,
                valid_to    TEXT,
                label       TEXT,
                is_active   INTEGER DEFAULT 1
            )
            """)
        conn.commit()

    def seed_rotation_test_data(self) -> dict:
        """Phase F-Final: seed minimal test data for the rotation engine
        if the corresponding tables are empty. Returns counts inserted.

        - 3 sweepers (real audio path resolution is the operator's job
          to wire later — placeholder file_path='' lets the picker
          return a row that Studio handles gracefully)
        - 2 station IDs (rows in `jingles` with category='Station ID')
        - 2 voice tracks (always-valid window)

        Idempotent: only seeds when each table is empty for the
        rotation type."""
        self._ensure_voice_tracks_table()
        conn = self._conn()
        added = {"sweepers": 0, "station_ids": 0, "voice_tracks": 0}

        n = conn.execute("SELECT COUNT(*) FROM sweepers").fetchone()[0]
        if int(n or 0) == 0:
            for nm in ("KISS Energy", "Drop the Beat", "Coming Up Next"):
                conn.execute(
                    "INSERT INTO sweepers (name, category, file_path, "
                    "duration_ms, is_enabled) VALUES (?, 'Station', '', 8000, 1)",
                    [nm])
                added["sweepers"] += 1

        n = conn.execute(
            "SELECT COUNT(*) FROM jingles WHERE category = 'Station ID'"
        ).fetchone()[0]
        if int(n or 0) == 0:
            for nm in ("KISS FM 91.5 Main Ident", "KISS Shot 01"):
                conn.execute(
                    "INSERT INTO jingles (name, category, file_path, "
                    "duration_ms, is_enabled) VALUES "
                    "(?, 'Station ID', '', 5000, 1)",
                    [nm])
                added["station_ids"] += 1

        n = conn.execute("SELECT COUNT(*) FROM voice_tracks").fetchone()[0]
        if int(n or 0) == 0:
            for nm, lbl in (("Morning Open", "Show open"),
                            ("Weather Tag", "Daily weather tag")):
                conn.execute(
                    "INSERT INTO voice_tracks (name, file_path, "
                    "duration_ms, valid_from, valid_to, label, is_active) "
                    "VALUES (?, '', 30000, NULL, NULL, ?, 1)",
                    [nm, lbl])
                added["voice_tracks"] += 1

        conn.commit()
        return added

    # ── Voice tracks / sweepers / station IDs lookup (Phase F-Final) ──────

    def get_voice_tracks(self, today: Optional[str] = None) -> List[sqlite3.Row]:
        """Active voice tracks valid on `today` (YYYY-MM-DD).
        NULL valid_from / valid_to = always valid."""
        from datetime import datetime as _dt
        today = today or _dt.now().strftime("%Y-%m-%d")
        return self._conn().execute(
            """
            SELECT * FROM voice_tracks
            WHERE  is_active = 1
            AND    (valid_from IS NULL OR valid_from <= ?)
            AND    (valid_to   IS NULL OR valid_to   >= ?)
            """,
            [today, today],
        ).fetchall()

    def get_sweepers_active(self) -> List[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM sweepers WHERE is_enabled = 1"
        ).fetchall()

    def get_station_ids_active(self) -> List[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM jingles "
            "WHERE category = 'Station ID' AND is_enabled = 1"
        ).fetchall()

    def get_jingle_pads_active(self,
                               pallet_id: Optional[int] = None
                               ) -> List[sqlite3.Row]:
        sql = ("SELECT * FROM jingle_pads "
               "WHERE file_path IS NOT NULL AND file_path != ''")
        params: list = []
        if pallet_id:
            sql += " AND pallet_id = ?"
            params.append(int(pallet_id))
        return self._conn().execute(sql, params).fetchall()

    def create_clock(self, name: str = "New Clock") -> int:
        """Insert a fresh empty clock with safe defaults.
        Returns the new clock id. Used by the Clock Editor's '+ New' action."""
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO clocks (name, time_start, time_end, day_mask, "
            "is_active) VALUES (?, '00:00', '01:00', 127, 1)",
            [name or "New Clock"],
        )
        conn.commit()
        return int(cur.lastrowid)

    def duplicate_clock(self, clock_id: int) -> int:
        """Clone the clock plus its slots. Returns new clock id.

        New name is "<original> (copy)". All slot fields are copied
        verbatim except id (autoincrement) and clock_id (rebound).
        Single transaction — rolls back if any insert fails."""
        self._ensure_clock_slots_columns()
        conn = self._conn()
        src = self.get_clock(int(clock_id))
        if src is None:
            raise ValueError(f"clock {clock_id} not found")
        src_slots = self.get_clock_slots(int(clock_id))
        cols_present = {r[1] for r in conn.execute(
            "PRAGMA table_info(clock_slots)").fetchall()}
        try:
            conn.execute("BEGIN")
            cur = conn.execute(
                "INSERT INTO clocks (name, time_start, time_end, day_mask, "
                "description, is_active) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    f"{src['name']} (copy)",
                    src["time_start"], src["time_end"],
                    src["day_mask"],
                    src["description"] if "description" in src.keys() else None,
                    src["is_active"] if "is_active" in src.keys() else 1,
                ],
            )
            new_id = int(cur.lastrowid)
            for slot in src_slots:
                payload: dict = {"clock_id": new_id}
                for k in cols_present:
                    if k in ("id", "clock_id"):
                        continue
                    if k in slot.keys():
                        payload[k] = slot[k]
                cols = ", ".join(payload.keys())
                ph   = ", ".join(["?"] * len(payload))
                conn.execute(
                    f"INSERT INTO clock_slots ({cols}) VALUES ({ph})",
                    list(payload.values()),
                )
            conn.commit()
            return new_id
        except Exception:
            conn.rollback()
            raise

    def delete_clock(self, clock_id: int) -> None:
        """Delete a clock by exact id (FK ON DELETE CASCADE removes its
        slots and any auto_schedule rows). Refuses to drop the very last
        clock so the editor always has something to load."""
        conn = self._conn()
        total = conn.execute("SELECT COUNT(*) FROM clocks").fetchone()[0]
        if int(total or 0) <= 1:
            raise ValueError("cannot delete the last remaining clock")
        cid = int(clock_id)
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM clocks WHERE id = ?", [cid])
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ── Final Log (Phase F-Final S5) ─────────────────────────────────────

    def get_final_log(self, log_date: str):
        """Return the final_logs row for `log_date` ('YYYY-MM-DD'), or None."""
        return self._conn().execute(
            "SELECT * FROM final_logs WHERE log_date = ? LIMIT 1",
            [str(log_date)],
        ).fetchone()

    def get_final_log_entries(self, log_id: int) -> List[sqlite3.Row]:
        """All entries in a final_log, ordered by position."""
        return self._conn().execute(
            "SELECT * FROM final_log_entries WHERE log_id = ? "
            "ORDER BY position ASC",
            [int(log_id)],
        ).fetchall()

    def delete_final_log(self, log_date: str) -> int:
        """Delete the log + entries (cascade) for `log_date`. Returns rows
        removed at the parent level."""
        conn = self._conn()
        cur = conn.execute("DELETE FROM final_logs WHERE log_date = ?",
                           [str(log_date)])
        conn.commit()
        return int(cur.rowcount or 0)

    def generate_final_log(self, log_date: str, scheduler) -> dict:
        """Phase F-Final S5: pre-compute the 24-hour playout for `log_date`
        using the scheduler's pickers. Returns
        {log_id, entry_count, hours_resolved, hours_empty, warning_count}.

        Generation strategy:
          1. Replace any existing final_log for this date (idempotent)
          2. For each hour 0..23:
               - resolve clock via force_clocks override OR auto_schedule
               - if no clock for this hour, skip
               - reset scheduler cursor (so generation is deterministic
                 within an hour), walk all clock_slots once, pick each
               - schedule each picked item at cumulative-time-from-hour-start
        Each picked item is stored as a final_log_entries row.

        `scheduler`: a SchedulerEngine instance — used for its pickers.
        Pickers consult the live broadcast_log for separation, so
        generation is approximate; a future polish pass can supply a
        local 'already-picked' set for stricter same-day separation.
        """
        from datetime import datetime as _dt
        date_str = str(log_date)

        # Resolve day_of_week for the target date.
        try:
            dow = _dt.strptime(date_str, "%Y-%m-%d").weekday()
        except ValueError:
            raise ValueError(f"log_date must be YYYY-MM-DD, got {log_date!r}")

        conn = self._conn()
        # Replace any existing log for this date.
        self.delete_final_log(date_str)

        # Insert the parent log row.
        cur = conn.execute(
            "INSERT INTO final_logs (log_date, generated_by, generated_at, "
            "is_locked, warning_count) VALUES (?, 'AI', "
            "datetime('now', 'localtime'), 0, 0)",
            [date_str],
        )
        log_id = int(cur.lastrowid)

        hours_resolved = 0
        hours_empty = 0
        warnings = 0
        position = 0

        for hour in range(24):
            # Resolve clock for this (date, hour).
            when = _dt.strptime(f"{date_str} {hour:02d}:00", "%Y-%m-%d %H:%M")
            try:
                fc = self.get_force_clock_for(when)
                clock_id = int(fc["clock_id"]) if fc else None
            except Exception:
                clock_id = None
            if clock_id is None:
                row = self.get_active_clock(dow, hour)
                clock_id = int(row["id"]) if row else None
            if clock_id is None:
                hours_empty += 1
                continue

            slots = self.get_clock_slots(clock_id)
            if not slots:
                hours_empty += 1
                continue
            hours_resolved += 1

            # Reset scheduler cursor for deterministic per-hour walk.
            scheduler._clock_slot_cursor = 0
            scheduler._active_hour_key = (dow, hour)

            cumulative_seconds = 0
            for _ in slots:
                item = scheduler.pick_next_item(when)
                if item is None:
                    warnings += 1
                    break
                # Time within the hour
                slot_h = hour + cumulative_seconds // 3600
                slot_m = (cumulative_seconds % 3600) // 60
                slot_s = cumulative_seconds % 60
                scheduled_time = (
                    f"{slot_h:02d}:{slot_m:02d}:{slot_s:02d}")

                # Map item_type → entry_type + song_id / jingle_id / campaign_id
                etype = item.get("item_type", "song")
                song_id = (int(item["item_id"])
                           if etype == "song" and item.get("item_id") else None)
                campaign_id = (int(item["item_id"])
                               if etype == "spot" and item.get("item_id") else None)
                jingle_id = (int(item["item_id"])
                             if etype in ("jingle", "station_id")
                             and item.get("item_id") else None)

                conn.execute(
                    "INSERT INTO final_log_entries (log_id, scheduled_time, "
                    "entry_type, song_id, campaign_id, jingle_id, "
                    "title_override, artist_override, duration_ms, "
                    "is_locked, position) VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                    [log_id, scheduled_time, etype, song_id,
                     campaign_id, jingle_id,
                     item.get("title"), item.get("artist"),
                     int(item.get("duration_ms") or 0), position])
                position += 1
                cumulative_seconds += max(1, int(item.get("duration_ms") or 0) // 1000)
                if cumulative_seconds >= 3600:
                    break

        # Update warning_count + entry_count is implicit (count via query).
        conn.execute("UPDATE final_logs SET warning_count = ? WHERE id = ?",
                     [warnings, log_id])
        conn.commit()

        entry_count = int(conn.execute(
            "SELECT COUNT(*) FROM final_log_entries WHERE log_id = ?",
            [log_id]).fetchone()[0])
        return {
            "log_id":         log_id,
            "entry_count":    entry_count,
            "hours_resolved": hours_resolved,
            "hours_empty":    hours_empty,
            "warning_count":  warnings,
        }

    # ── Force Clocks (Phase F-Final S4 resolution layer) ─────────────────────

    def get_force_clock_for(self, when) -> Optional[sqlite3.Row]:
        """Return the force_clocks row that overrides today × hour at the
        given datetime, or None. Single-shot rule: first matching override
        for the date wins (active only).

        `when`: datetime — inspected for date + time."""
        from datetime import datetime as _dt
        if when is None:
            when = _dt.now()
        date_str = when.strftime("%Y-%m-%d")
        time_str = when.strftime("%H:%M")
        return self._conn().execute(
            """
            SELECT * FROM force_clocks
            WHERE  is_active = 1
            AND    override_date = ?
            AND    (time_start IS NULL OR time_start <= ?)
            AND    (time_end   IS NULL OR time_end   >= ?)
            ORDER  BY id
            LIMIT  1
            """,
            [date_str, time_str, time_str],
        ).fetchone()

    def list_force_clocks(self) -> List[sqlite3.Row]:
        """All active force_clocks rows, most-recent-first."""
        return self._conn().execute(
            "SELECT * FROM force_clocks WHERE is_active = 1 "
            "ORDER BY override_date DESC, id DESC"
        ).fetchall()

    def add_force_clock(self, name: str, clock_id: int,
                        override_date: str, time_start: str = "00:00",
                        time_end: str = "23:59") -> int:
        """Insert a new override. Returns the new row id."""
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO force_clocks (name, clock_id, override_date, "
            "time_start, time_end, is_active) VALUES (?, ?, ?, ?, ?, 1)",
            [name or "Override", int(clock_id), str(override_date),
             str(time_start), str(time_end)],
        )
        conn.commit()
        return int(cur.lastrowid)

    def delete_force_clock(self, force_clock_id: int) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM force_clocks WHERE id = ?",
                     [int(force_clock_id)])
        conn.commit()

    # ── Auto Schedule grid (Phase F1) ────────────────────────────────────────

    def normalize_auto_schedule(self) -> int:
        """Split any multi-hour auto_schedule rows into per-hour rows.
        Idempotent — second call updates 0. Run on first F1 mount so the
        grid editor always sees one row per (day, hour)."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, clock_id, day_of_week, hour_start, hour_end "
            "FROM auto_schedule WHERE hour_end - hour_start > 1"
        ).fetchall()
        if not rows:
            return 0
        try:
            conn.execute("BEGIN")
            for r in rows:
                conn.execute("DELETE FROM auto_schedule WHERE id = ?", [r[0]])
                for h in range(int(r[3]), int(r[4])):
                    conn.execute(
                        "INSERT INTO auto_schedule (clock_id, day_of_week, "
                        "hour_start, hour_end) VALUES (?, ?, ?, ?)",
                        [int(r[1]), int(r[2]), int(h), int(h) + 1])
            conn.commit()
            return len(rows)
        except Exception:
            conn.rollback()
            raise

    def get_auto_schedule_grid(self) -> dict:
        """Return {(day, hour): clock_id} for the entire 24×7 grid.
        Multi-hour ranges are expanded so each hour has its own entry."""
        rows = self._conn().execute(
            "SELECT clock_id, day_of_week, hour_start, hour_end FROM auto_schedule"
        ).fetchall()
        grid: dict = {}
        for r in rows:
            for h in range(int(r["hour_start"]), int(r["hour_end"])):
                grid[(int(r["day_of_week"]), h)] = int(r["clock_id"])
        return grid

    def set_auto_schedule_cell(self, day_of_week: int, hour: int,
                               clock_id: int) -> None:
        """Assign clock to (day, hour). Replaces any existing assignment
        that overlaps this hour. Per CLAUDE.md guardrail — DELETE WHERE
        is exact-match equality (not LIKE), safe."""
        conn = self._conn()
        d = int(day_of_week); h = int(hour); cid = int(clock_id)
        try:
            conn.execute("BEGIN")
            conn.execute(
                "DELETE FROM auto_schedule WHERE day_of_week = ? "
                "AND hour_start <= ? AND hour_end > ?", [d, h, h])
            conn.execute(
                "INSERT INTO auto_schedule (clock_id, day_of_week, "
                "hour_start, hour_end) VALUES (?, ?, ?, ?)",
                [cid, d, h, h + 1])
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def clear_auto_schedule_cell(self, day_of_week: int, hour: int) -> None:
        """Remove any assignment that covers (day, hour)."""
        conn = self._conn()
        d = int(day_of_week); h = int(hour)
        conn.execute(
            "DELETE FROM auto_schedule WHERE day_of_week = ? "
            "AND hour_start <= ? AND hour_end > ?", [d, h, h])
        conn.commit()

    def clear_all_auto_schedule(self) -> int:
        """Wipe the entire grid. Returns rows removed.
        Refuses if WHERE-style clauses leak — uses unconditional DELETE."""
        conn = self._conn()
        cur = conn.execute("DELETE FROM auto_schedule")
        conn.commit()
        return int(cur.rowcount or 0)

    def migrate_spot_to_break(self) -> int:
        """Phase F2.3 — rename clock_slots.slot_type 'Spot'/'spot' to
        'Break'. Idempotent: second call updates 0 rows. The auto and
        AI schedulers were updated to accept either token, so calling
        this on first ClockEditor mount is safe even if upstream code
        somewhere still emits 'Spot'."""
        conn = self._conn()
        cur = conn.execute(
            "UPDATE clock_slots SET slot_type='Break' "
            "WHERE LOWER(slot_type) = 'spot'"
        )
        conn.commit()
        return int(cur.rowcount or 0)

    def save_clock_slots(self, clock_id: int, slots: list) -> None:
        """Replace this clock's slot list with `slots`. DELETE+INSERT
        within a transaction. Per CLAUDE.md guardrail: WHERE clock_id = ?
        is exact-match on a known id, not a LIKE pattern — safe."""
        self._ensure_clock_slots_columns()
        conn = self._conn()
        cols_present = {r[1] for r in conn.execute(
            "PRAGMA table_info(clock_slots)").fetchall()}
        cid = int(clock_id)
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM clock_slots WHERE clock_id = ?", [cid])
            for i, slot in enumerate(slots or []):
                payload: dict = {"clock_id": cid, "slot_order": i + 1}
                for k in ("slot_type", "category_id", "energy_pref",
                         "vocal_pref", "priority_pref",
                         "separation_override", "position_minutes",
                         "is_break", "sweeper_position", "item_id",
                         "fallback_category_id", "pin_to_time",
                         "duration_seconds", "ref_text", "selection_mode",
                         # F-Final C3
                         "filter_json", "specific_song_id",
                         "specific_artist_id", "minute_position"):
                    if k in cols_present and k in slot:
                        payload[k] = slot[k]
                cols = ", ".join(payload.keys())
                ph   = ", ".join(["?"] * len(payload))
                conn.execute(
                    f"INSERT INTO clock_slots ({cols}) VALUES ({ph})",
                    list(payload.values()),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ── AI Schedule ───────────────────────────────────────────────────────────

    def get_ai_schedule(self, date, hour: int) -> List[sqlite3.Row]:
        """Return the AI-generated slots for a specific date+hour."""
        return self._conn().execute(
            """
            SELECT al.*, s.title, s.artist, s.file_path,
                   s.duration_ms, s.hook_in_ms, s.hook_out_ms,
                   s.start_point_ms, s.intro_end_ms,
                   s.outro_point_ms, s.fade_in_ms, s.fade_out_ms,
                   c.name AS cat_name, c.color AS cat_color
            FROM   ai_daily_log al
            LEFT JOIN songs s ON al.song_id = s.id
            LEFT JOIN categories c ON s.category_id = c.id
            WHERE  al.schedule_date = ?
            AND    al.hour          = ?
            AND    al.status        = 'scheduled'
            ORDER  BY al.position ASC
            """,
            [str(date), hour],
        ).fetchall()

    def get_schedule_status(self, date) -> Optional[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM ai_schedule_status WHERE schedule_date = ?",
            [str(date)],
        ).fetchone()

    # ── Settings ──────────────────────────────────────────────────────────────

    def get_setting(self, key: str, default=None):
        row = self._conn().execute(
            "SELECT value FROM settings WHERE key = ?", [key]
        ).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            [key, str(value)],
        )
        conn.commit()

    def get_all_settings(self) -> dict:
        rows = self._conn().execute(
            "SELECT key, value FROM settings"
        ).fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ── Campaigns / Spots ─────────────────────────────────────────────────────

    def get_campaigns(self, active_only: bool = True) -> List[sqlite3.Row]:
        sql = """
            SELECT c.*, COUNT(sf.id) AS file_count
            FROM   campaigns c
            LEFT JOIN spot_files sf ON sf.campaign_id = c.id
            WHERE  1=1
        """
        if active_only:
            sql += """
            AND (c.end_date IS NULL
              OR c.end_date = 'Never'
              OR c.end_date >= date('now'))
            AND c.is_active = 1
            """
        sql += " GROUP BY c.id ORDER BY c.name"
        return self._conn().execute(sql).fetchall()

    def get_hourly_ad_usage(self) -> float:
        """Return ad minutes used in the current clock hour."""
        row = self._conn().execute(
            """
            SELECT COALESCE(SUM(duration_ms) / 60000.0, 0.0) AS ad_mins
            FROM   broadcast_log
            WHERE  entry_type IN ('spot', 'ad', 'break')
            AND    strftime('%H', played_at) = strftime('%H', 'now', 'localtime')
            AND    date(played_at)           = date('now', 'localtime')
            """
        ).fetchone()
        return float(row["ad_mins"]) if row else 0.0

    def get_next_break(self) -> Optional[sqlite3.Row]:
        """Return the next active break entry after now."""
        return self._conn().execute(
            """
            SELECT * FROM break_schedule
            WHERE  is_active = 1
            ORDER  BY break_time ASC
            LIMIT  1
            """
        ).fetchone()

    # ── Campaigns CRUD (Spots & Commercials Library) ──────────────────────────

    def _ensure_campaign_schedule_columns(self) -> None:
        """Add `priority` to campaign_schedule if missing. Idempotent."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(campaign_schedule)").fetchall()}
        if "priority" not in cols:
            conn.execute(
                "ALTER TABLE campaign_schedule "
                "ADD COLUMN priority TEXT DEFAULT 'Medium'"
            )
        conn.commit()

    def _ensure_campaigns_columns(self) -> None:
        """Add UI-specific campaign columns if missing + backfill auto_code.
        Idempotent — safe to call on every connection bootstrap.

        Also bootstraps the campaign_schedule.priority column so callers that
        only run this single migration get both upgrades."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(campaigns)").fetchall()}
        adds = [
            ("auto_code",       "TEXT"),
            ("min_gap_minutes", "INTEGER DEFAULT 30"),
            ("max_per_break",   "INTEGER DEFAULT 1"),
            ("availability",    "TEXT DEFAULT 'active'"),
        ]
        for col, decl in adds:
            if col not in cols:
                conn.execute(f"ALTER TABLE campaigns ADD COLUMN {col} {decl}")
        # Backfill auto_code for rows that don't have one yet. Picks up
        # from MAX existing numeric code (or 400000 if none) so we never
        # collide with codes added by future inserts.
        nulls = conn.execute(
            "SELECT id FROM campaigns "
            "WHERE auto_code IS NULL OR auto_code = '' "
            "ORDER BY id"
        ).fetchall()
        if nulls:
            mrow = conn.execute(
                "SELECT MAX(CAST(auto_code AS INTEGER)) AS m FROM campaigns "
                "WHERE auto_code IS NOT NULL AND auto_code != ''"
            ).fetchone()
            start = (int(mrow["m"]) if mrow and mrow["m"] else 400000) + 1
            for i, r in enumerate(nulls):
                conn.execute(
                    "UPDATE campaigns SET auto_code = ? WHERE id = ?",
                    [str(start + i), r["id"]],
                )
        conn.commit()
        # Cascade: bring campaign_schedule schema up to date too
        self._ensure_campaign_schedule_columns()

    def get_all_campaigns(self, filter: str = "all") -> List[sqlite3.Row]:
        """Return campaigns with file_count + active flag.

        filter:
          'all'      — all campaigns
          'active'   — is_active=1 AND not past end_date
          'expired'  — past end_date (excludes 'Never')
        """
        sql = """
            SELECT c.*, COUNT(sf.id) AS file_count,
                   CASE
                       WHEN c.is_active = 0 THEN 0
                       WHEN c.end_date IS NULL OR c.end_date = ''
                            OR c.end_date = 'Never'
                            OR c.end_date >= date('now') THEN 1
                       ELSE 0
                   END AS is_currently_active
            FROM   campaigns c
            LEFT JOIN spot_files sf ON sf.campaign_id = c.id
        """
        params: list = []
        f = (filter or "all").lower()
        if f == "active":
            sql += " WHERE c.is_active = 1 AND (c.end_date IS NULL " \
                   "OR c.end_date = '' OR c.end_date = 'Never' " \
                   "OR c.end_date >= date('now'))"
        elif f == "expired":
            sql += " WHERE c.end_date IS NOT NULL AND c.end_date != '' " \
                   "AND c.end_date != 'Never' AND c.end_date < date('now')"
        sql += " GROUP BY c.id ORDER BY c.name"
        return self._conn().execute(sql, params).fetchall()

    def get_campaign(self, campaign_id: int) -> Optional[dict]:
        """Return campaign + nested files + schedule, as a plain dict.
        Returns None if not found."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM campaigns WHERE id = ?", [int(campaign_id)],
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["spot_files"] = [dict(r) for r in self.get_spot_files(campaign_id)]
        d["schedule"]   = [dict(r) for r in self.get_break_schedule(campaign_id)]
        return d

    def add_campaign(self, data: dict) -> int:
        """Insert a campaign. Auto-fills auto_code if not provided."""
        conn = self._conn()
        cols_present = {r[1] for r in conn.execute(
            "PRAGMA table_info(campaigns)").fetchall()}
        payload = {}
        candidates = (
            "name", "description", "category", "priority",
            "programming_mode", "playback_order",
            "start_date", "end_date",
            "contracted_plays_per_day", "is_active",
            "auto_code", "min_gap_minutes", "max_per_break", "availability",
        )
        for k in candidates:
            if k in cols_present and k in data:
                payload[k] = data[k]
        # Sensible defaults
        payload.setdefault("name", data.get("name", "New Campaign"))
        if "auto_code" in cols_present and not payload.get("auto_code"):
            payload["auto_code"] = self.generate_auto_code()

        cols = ", ".join(payload.keys())
        ph   = ", ".join(["?"] * len(payload))
        cur = conn.execute(
            f"INSERT INTO campaigns ({cols}) VALUES ({ph})",
            list(payload.values()),
        )
        conn.commit()
        return int(cur.lastrowid or 0)

    def update_campaign(self, campaign_id: int, data: dict) -> None:
        conn = self._conn()
        cols_present = {r[1] for r in conn.execute(
            "PRAGMA table_info(campaigns)").fetchall()}
        sets, values = [], []
        for k in (
            "name", "description", "category", "priority",
            "programming_mode", "playback_order",
            "start_date", "end_date",
            "contracted_plays_per_day", "is_active",
            "auto_code", "min_gap_minutes", "max_per_break", "availability",
        ):
            if k in cols_present and k in data:
                sets.append(f"{k} = ?")
                values.append(data[k])
        if not sets:
            return
        values.append(int(campaign_id))
        conn.execute(
            f"UPDATE campaigns SET {', '.join(sets)} WHERE id = ?", values
        )
        conn.commit()

    def delete_campaign(self, campaign_id: int) -> None:
        """Delete a campaign. spot_files cascades via FK; campaign_schedule
        is hand-cleaned because that table doesn't declare CASCADE."""
        conn = self._conn()
        sid = int(campaign_id)
        conn.execute("DELETE FROM campaign_schedule WHERE campaign_id = ?", [sid])
        # broadcast_log + final_log_entries reference campaigns(id) but we
        # preserve their history rows by NULL-ing the FK (same pattern as
        # delete_song).
        conn.execute("UPDATE broadcast_log SET campaign_id = NULL "
                     "WHERE campaign_id = ?", [sid])
        conn.execute("UPDATE final_log_entries SET campaign_id = NULL "
                     "WHERE campaign_id = ?", [sid])
        conn.execute("DELETE FROM campaigns WHERE id = ?", [sid])
        conn.commit()

    def generate_auto_code(self) -> str:
        """Return the next 6-digit auto_code (starts at 400001).
        Stable: based on max existing auto_code, not on row count."""
        conn = self._conn()
        row = conn.execute(
            "SELECT auto_code FROM campaigns "
            "WHERE auto_code IS NOT NULL AND auto_code != '' "
            "ORDER BY CAST(auto_code AS INTEGER) DESC LIMIT 1"
        ).fetchone()
        try:
            last = int(row["auto_code"]) if row else 400000
        except (ValueError, TypeError):
            last = 400000
        return str(max(400001, last + 1))

    # ── Spot files ────────────────────────────────────────────────────────────

    def get_spot_files(self, campaign_id: int) -> List[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM spot_files WHERE campaign_id = ? "
            "ORDER BY display_order, id",
            [int(campaign_id)],
        ).fetchall()

    def add_spot_file(self, campaign_id: int, data: dict) -> int:
        conn = self._conn()
        cur = conn.execute(
            """
            INSERT INTO spot_files (campaign_id, filename, file_path,
                                    duration_ms, is_active, display_order)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                int(campaign_id),
                data.get("filename") or "",
                data.get("file_path") or "",
                int(data.get("duration_ms", 0) or 0),
                int(data.get("is_active", 1)),
                int(data.get("display_order", 0)),
            ],
        )
        conn.commit()
        return int(cur.lastrowid or 0)

    def delete_spot_file(self, file_id: int) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM spot_files WHERE id = ?", [int(file_id)])
        conn.commit()

    # ── Scheduler dispatch helpers (Phase D4) ────────────────────────────────

    def get_active_breaks_for_day(self, day_of_week: int) -> List[sqlite3.Row]:
        """Return all campaign_schedule rows for a given day-of-week
        (0=Mon … 6=Sun) where the campaign is active and not past its
        end date.

        Used by the SchedulerEngine each midnight to refresh its in-memory
        break list. Keyed by break_time + campaign_id; the scheduler then
        ticks against this list."""
        self._ensure_campaign_schedule_columns()
        conn = self._conn()
        return conn.execute(
            """
            SELECT cs.id, cs.campaign_id, cs.day_of_week, cs.break_time,
                   cs.slot_order,
                   COALESCE(cs.priority, 'Medium') AS priority,
                   c.name AS campaign_name
            FROM   campaign_schedule cs
            JOIN   campaigns c ON cs.campaign_id = c.id
            WHERE  cs.day_of_week = ?
            AND    c.is_active = 1
            AND   (c.end_date IS NULL OR c.end_date = ''
                    OR c.end_date = 'Never'
                    OR c.end_date >= date('now'))
            ORDER  BY cs.break_time
            """,
            [int(day_of_week)],
        ).fetchall()

    # ── Break schedule (campaign × day × break_time) ──────────────────────────

    def get_break_schedule(self, campaign_id: int) -> List[sqlite3.Row]:
        """All scheduled breaks for a campaign — one row per (day, time).
        Includes priority (post-migration). Older DBs without the column
        still work via the columns-present check."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(campaign_schedule)").fetchall()}
        priority_select = ", priority" if "priority" in cols else ""
        return conn.execute(
            f"SELECT id, campaign_id, day_of_week, break_time, slot_order"
            f"{priority_select} "
            f"FROM   campaign_schedule "
            f"WHERE  campaign_id = ? "
            f"ORDER  BY day_of_week, break_time",
            [int(campaign_id)],
        ).fetchall()

    def update_break_schedule(self, campaign_id: int,
                              schedule: list) -> None:
        """Replace the campaign's schedule with `schedule` (list of dicts
        with keys day_of_week, break_time, slot_order, priority). Atomic."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(campaign_schedule)").fetchall()}
        has_priority = "priority" in cols
        sid = int(campaign_id)
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM campaign_schedule WHERE campaign_id = ?",
                         [sid])
            for item in (schedule or []):
                if has_priority:
                    conn.execute(
                        "INSERT INTO campaign_schedule "
                        "(campaign_id, day_of_week, break_time, "
                        " slot_order, priority) "
                        "VALUES (?, ?, ?, ?, ?)",
                        [
                            sid,
                            int(item.get("day_of_week", 0)),
                            item.get("break_time") or "",
                            int(item.get("slot_order", 0)),
                            item.get("priority") or "Medium",
                        ],
                    )
                else:
                    conn.execute(
                        "INSERT INTO campaign_schedule "
                        "(campaign_id, day_of_week, break_time, slot_order) "
                        "VALUES (?, ?, ?, ?)",
                        [
                            sid,
                            int(item.get("day_of_week", 0)),
                            item.get("break_time") or "",
                            int(item.get("slot_order", 0)),
                        ],
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ── Jingles ───────────────────────────────────────────────────────────────

    def get_jingles(self, category: Optional[str] = None) -> List[sqlite3.Row]:
        sql = "SELECT * FROM jingles WHERE is_enabled = 1"
        params: list = []
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY name"
        return self._conn().execute(sql, params).fetchall()

    def get_instant_jingle_pads(self) -> List[sqlite3.Row]:
        """Return the N25-N30 instant jingle pads (first pallet, 6 pads)."""
        rows = self._conn().execute(
            """
            SELECT jp.*, jpl.name AS pallet_name
            FROM   jingle_pads jp
            JOIN   jingle_pallets jpl ON jp.pallet_id = jpl.id
            WHERE  jp.file_path IS NOT NULL
            ORDER  BY jpl.display_order ASC, jp.pad_index ASC
            LIMIT  6
            """
        ).fetchall()
        # Fallback: return last 6 jingles if no pads configured
        if not rows:
            rows = self._conn().execute(
                "SELECT * FROM jingles WHERE is_enabled=1 ORDER BY id DESC LIMIT 6"
            ).fetchall()
        return rows

    # ── Instant Jingle Pallets / Pads CRUD ────────────────────────────────────

    def _ensure_jingle_pads_columns(self) -> None:
        """Add play_count + last_played columns to jingle_pads if missing.
        Idempotent — safe to call on every connection bootstrap."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jingle_pads)").fetchall()}
        if "play_count" not in cols:
            conn.execute("ALTER TABLE jingle_pads ADD COLUMN play_count INTEGER DEFAULT 0")
        if "last_played" not in cols:
            conn.execute("ALTER TABLE jingle_pads ADD COLUMN last_played TEXT")
        conn.commit()

    # ── Songs / Audio Cue Editor ──────────────────────────────────────────────
    #
    # TODO: Schema cleanup — consolidate duplicate cue columns:
    #   - intro_point_ms (canonical) vs intro_end_ms vs intro_time (legacy)
    #   - mix_point_ms   (canonical) vs mix_point (legacy)
    #   - hook_in_ms     (canonical) vs hook_in_time (legacy)
    #   - hook_out_ms    (canonical) vs hook_out_time (legacy)
    #   - outro_point_ms (canonical) vs outro_time (legacy)
    #   - start_point_ms (canonical) vs any others
    #
    # Phase 5+ writes only to canonical _ms columns. Legacy columns stay for
    # backward-compat until a migration phase consolidates them.
    # ──────────────────────────────────────────────────────────────────────────

    def _ensure_song_cue_columns(self) -> None:
        """Add the 6 cue-editor columns missing from songs. Idempotent —
        same pattern as _ensure_jingle_pads_columns."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(songs)").fetchall()}
        adds = [
            ("auto_cue",          "INTEGER DEFAULT 0"),
            ("normalize",         "INTEGER DEFAULT 0"),
            ("bit_depth_32",      "INTEGER DEFAULT 0"),
            ("title_field_mode",  "TEXT DEFAULT 'AUTO'"),
            ("artist_field_mode", "TEXT DEFAULT 'AUTO'"),
            ("update_on_play",    "TEXT DEFAULT 'Yes'"),
        ]
        for col, decl in adds:
            if col not in cols:
                conn.execute(f"ALTER TABLE songs ADD COLUMN {col} {decl}")
        conn.commit()

    # The cue editor speaks in canonical column names. This list is the
    # source of truth — every read/write goes through it.
    _CUE_FIELDS = (
        "start_point_ms", "intro_point_ms",
        "hook_in_ms", "hook_out_ms",
        "outro_point_ms", "mix_point_ms",
        "fade_in_ms", "fade_out_ms",
        "volume_level", "variable_length",
        "auto_cue", "normalize", "bit_depth_32",
        "title_field_mode", "artist_field_mode", "update_on_play",
    )

    def get_song_cue_data(self, song_id: int) -> dict:
        """Return all cue-editor-relevant fields for a song as a flat dict.
        Keys are canonical column names. Missing columns default to 0/empty.
        Caller can rely on every key in _CUE_FIELDS being present."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(songs)").fetchall()}
        # Always include id + duration_ms + file_path + name fields for header
        select_cols = ["id", "title", "artist", "duration_ms", "file_path"]
        for f in self._CUE_FIELDS:
            if f in cols:
                select_cols.append(f)
        sql = f"SELECT {', '.join(select_cols)} FROM songs WHERE id = ?"
        row = conn.execute(sql, [int(song_id)]).fetchone()
        if not row:
            return {}
        d = {k: row[k] for k in row.keys()}
        # Ensure every cue field is present even if the column was missing
        for f in self._CUE_FIELDS:
            d.setdefault(f, 0 if f.endswith("_ms") or f in (
                "volume_level", "variable_length",
                "auto_cue", "normalize", "bit_depth_32") else "")
        return d

    def save_song_cue_points(self, song_id: int, data: dict) -> None:
        """Persist cue-editor changes. Only writes canonical columns that
        actually exist on the table — quietly skips anything missing so
        older DBs without the migration don't error."""
        conn = self._conn()
        cols_present = {r[1] for r in conn.execute(
            "PRAGMA table_info(songs)").fetchall()}
        sets, values = [], []
        for f in self._CUE_FIELDS:
            if f in cols_present and f in data:
                sets.append(f"{f} = ?")
                values.append(data[f])
        if not sets:
            return
        values.append(int(song_id))
        conn.execute(
            f"UPDATE songs SET {', '.join(sets)} WHERE id = ?", values
        )
        conn.commit()

    def get_pallets(self) -> List[sqlite3.Row]:
        return self._conn().execute(
            """
            SELECT jpl.*, COUNT(jp.id) AS pad_count,
                   SUM(CASE WHEN jp.file_path IS NOT NULL AND jp.file_path != ''
                            THEN 1 ELSE 0 END) AS filled_count
            FROM   jingle_pallets jpl
            LEFT JOIN jingle_pads jp ON jp.pallet_id = jpl.id
            GROUP  BY jpl.id
            ORDER  BY jpl.display_order, jpl.id
            """
        ).fetchall()

    def get_pallet(self, pallet_id: int) -> Optional[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM jingle_pallets WHERE id = ?", [int(pallet_id)]
        ).fetchone()

    def add_pallet(self, data: dict) -> int:
        conn = self._conn()
        cur = conn.execute(
            """
            INSERT INTO jingle_pallets (name, owner, grid_cols, grid_rows,
                                        audio_output, display_order)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                data.get("name", "New Pallet"),
                data.get("owner") or "",
                int(data.get("grid_cols", 5)),
                int(data.get("grid_rows", 6)),
                int(data.get("audio_output", 3)),
                int(data.get("display_order", 0)),
            ],
        )
        conn.commit()
        return int(cur.lastrowid or 0)

    def update_pallet(self, pallet_id: int, data: dict) -> None:
        conn = self._conn()
        cols_present = {r[1] for r in conn.execute(
            "PRAGMA table_info(jingle_pallets)").fetchall()}
        sets, values = [], []
        for k in ("name", "owner", "grid_cols", "grid_rows",
                  "audio_output", "display_order"):
            if k in cols_present and k in data:
                sets.append(f"{k} = ?")
                values.append(data[k])
        if not sets:
            return
        values.append(int(pallet_id))
        conn.execute(
            f"UPDATE jingle_pallets SET {', '.join(sets)} WHERE id = ?", values
        )
        conn.commit()

    def delete_pallet(self, pallet_id: int) -> None:
        """Delete a pallet (cascades to its pads via FK ON DELETE CASCADE)."""
        conn = self._conn()
        conn.execute("DELETE FROM jingle_pallets WHERE id = ?", [int(pallet_id)])
        conn.commit()

    def get_pads(self, pallet_id: int) -> List[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM jingle_pads WHERE pallet_id = ? ORDER BY pad_index",
            [int(pallet_id)],
        ).fetchall()

    def get_pad(self, pad_id: int) -> Optional[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM jingle_pads WHERE id = ?", [int(pad_id)]
        ).fetchone()

    def add_pad(self, data: dict) -> int:
        conn = self._conn()
        cur = conn.execute(
            """
            INSERT INTO jingle_pads (pallet_id, pad_index, label, file_path,
                                     duration_ms, color, volume, behaviour)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                int(data.get("pallet_id", 0)),
                int(data.get("pad_index", 0)),
                data.get("label") or "",
                data.get("file_path"),
                int(data.get("duration_ms", 0) or 0),
                data.get("color") or "#06b6d4",
                int(data.get("volume", 100) or 100),
                data.get("behaviour") or "play_once",
            ],
        )
        conn.commit()
        return int(cur.lastrowid or 0)

    def update_pad(self, pad_id: int, data: dict) -> None:
        conn = self._conn()
        cols_present = {r[1] for r in conn.execute(
            "PRAGMA table_info(jingle_pads)").fetchall()}
        sets, values = [], []
        for k in ("label", "file_path", "duration_ms", "color",
                  "volume", "behaviour"):
            if k in cols_present and k in data:
                sets.append(f"{k} = ?")
                values.append(data[k])
        if not sets:
            return
        values.append(int(pad_id))
        conn.execute(
            f"UPDATE jingle_pads SET {', '.join(sets)} WHERE id = ?", values
        )
        conn.commit()

    def assign_audio_to_pad(self, pad_id: int, file_path: str,
                            duration_ms: int = 0) -> None:
        """Wire a real audio file (and its detected duration) to a pad."""
        self.update_pad(pad_id, {
            "file_path": file_path,
            "duration_ms": int(duration_ms or 0),
        })

    def clear_pad(self, pad_id: int) -> None:
        """Wipe pad's audio + label/duration but keep the slot + colour."""
        self.update_pad(pad_id, {
            "label": "",
            "file_path": None,
            "duration_ms": 0,
        })

    def record_pad_play(self, pad_id: int) -> None:
        """Increment play_count + bump last_played to now (localtime)."""
        conn = self._conn()
        conn.execute(
            "UPDATE jingle_pads "
            "SET play_count = COALESCE(play_count, 0) + 1, "
            "    last_played = datetime('now', 'localtime') "
            "WHERE id = ?",
            [int(pad_id)],
        )
        conn.commit()

    def get_pad_play_stats(self, pad_id: int, days: int = 7) -> dict:
        """Return plays-in-last-N-days for the AI insight panel.

        Note: jingle_pads only stores the most-recent last_played + total
        play_count, so we approximate "plays in last N days" with total
        play_count when last_played falls inside the window. For a precise
        count we would need a jingle_play_log table — flagged as follow-up.
        """
        conn = self._conn()
        row = conn.execute(
            "SELECT play_count, last_played FROM jingle_pads WHERE id = ?",
            [int(pad_id)],
        ).fetchone()
        if not row:
            return {"plays_in_window": 0, "play_count": 0, "last_played": None}
        plays_total = int(row["play_count"] or 0)
        last = row["last_played"]
        in_window = 0
        if last and plays_total > 0:
            cutoff = conn.execute(
                "SELECT datetime('now', 'localtime', ?)",
                [f'-{int(days)} days'],
            ).fetchone()[0]
            if str(last) >= str(cutoff):
                in_window = plays_total
        return {
            "plays_in_window": in_window,
            "play_count":      plays_total,
            "last_played":     last,
        }

    # ── Categories ────────────────────────────────────────────────────────────

    def get_categories(self) -> List[sqlite3.Row]:
        return self._conn().execute(
            """
            SELECT c.*, COUNT(s.id) AS song_count
            FROM   categories c
            LEFT JOIN songs s ON s.category_id = c.id
            GROUP  BY c.id
            ORDER  BY c.name
            """
        ).fetchall()

    # ── Dashboard stats ───────────────────────────────────────────────────────

    def get_dashboard_stats(self) -> dict:
        """Return all stats needed by Control Panel in one call."""
        from datetime import datetime
        conn = self._conn()
        today = datetime.now().strftime("%Y-%m-%d")
        s = {}

        def cnt(sql, params=()):
            try:
                row = conn.execute(sql, params).fetchone()
                return int(row[0]) if row else 0
            except Exception:
                return 0

        s["songs_total"]       = cnt("SELECT COUNT(*) FROM songs WHERE is_enabled=1")
        s["categories_total"]  = cnt("SELECT COUNT(*) FROM categories")
        s["clocks_total"]      = cnt("SELECT COUNT(*) FROM clocks WHERE is_active=1")
        s["clock_slots_total"] = cnt("SELECT COUNT(*) FROM clock_slots")
        s["campaigns_active"]  = cnt(
            "SELECT COUNT(*) FROM campaigns WHERE is_active=1 "
            "AND (end_date IS NULL OR end_date='' OR end_date='Never' OR end_date>=date('now'))"
        )
        s["spot_files_total"]  = cnt("SELECT COUNT(*) FROM spot_files")
        s["jingles_total"]     = cnt("SELECT COUNT(*) FROM jingles WHERE is_enabled=1")
        s["jingle_pallets"]    = cnt("SELECT COUNT(*) FROM jingle_pallets")
        s["jingle_pads"]       = cnt("SELECT COUNT(*) FROM jingle_pads WHERE file_path IS NOT NULL AND file_path != ''")
        s["sweepers_total"]    = cnt("SELECT COUNT(*) FROM sweepers WHERE is_enabled=1")
        s["playlists_total"]   = cnt("SELECT COUNT(*) FROM playlists")
        s["force_clocks"]      = cnt("SELECT COUNT(*) FROM force_clocks WHERE is_active=1")
        s["final_logs"]        = cnt("SELECT COUNT(*) FROM final_logs")
        s["auto_schedule_set"] = cnt("SELECT COUNT(*) FROM auto_schedule")
        s["broadcast_total"]   = cnt("SELECT COUNT(*) FROM broadcast_log")

        s["songs_today"] = cnt(
            "SELECT COUNT(*) FROM broadcast_log WHERE entry_type='song' AND date(played_at)=?", [today]
        )
        s["spots_today"] = cnt(
            "SELECT COUNT(*) FROM broadcast_log "
            "WHERE entry_type IN ('spot','ad','break') AND date(played_at)=?", [today]
        )

        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(duration_ms)/3600000.0, 0) FROM broadcast_log WHERE date(played_at)=?",
                [today],
            ).fetchone()
            s["hours_today"] = round(float(row[0]) if row and row[0] else 0.0, 1)
        except Exception:
            s["hours_today"] = 0.0

        s["ai_decisions"] = cnt("SELECT COUNT(*) FROM ai_decisions WHERE run_date=?", [today])

        try:
            row = conn.execute(
                "SELECT status, songs_scheduled, generated_at FROM ai_schedule_status "
                "WHERE schedule_date=?", [today]
            ).fetchone()
            if row:
                s["ai_status"] = row[0] or "pending"
                s["ai_songs_scheduled"] = int(row[1] or 0)
                s["ai_last_run"] = (str(row[2])[11:16] if row[2] else "—")
            else:
                s["ai_status"] = "pending"
                s["ai_songs_scheduled"] = 0
                s["ai_last_run"] = "—"
        except Exception:
            s["ai_status"] = "pending"
            s["ai_songs_scheduled"] = 0
            s["ai_last_run"] = "—"

        return s

    # ── Categories CRUD ───────────────────────────────────────────────────────

    def get_category(self, category_id: int):
        return self._conn().execute(
            "SELECT * FROM categories WHERE id = ?", [int(category_id)]
        ).fetchone()

    def add_category(self, data: dict) -> int:
        """Insert a new category. Required: data['name']."""
        conn = self._conn()
        cols_present = {r[1] for r in conn.execute("PRAGMA table_info(categories)").fetchall()}
        payload = {}
        for k in ("name", "color", "description"):
            if k in cols_present and k in data:
                payload[k] = data[k]
        # Sensible defaults
        payload.setdefault("name", data.get("name", "New Category"))
        if "color" in cols_present:
            payload.setdefault("color", data.get("color") or "#8b5cf6")

        cols = ", ".join(payload.keys())
        placeholders = ", ".join(["?"] * len(payload))
        cur = conn.execute(
            f"INSERT INTO categories ({cols}) VALUES ({placeholders})",
            list(payload.values()),
        )
        conn.commit()
        return int(cur.lastrowid or 0)

    def update_category(self, category_id: int, data: dict) -> None:
        conn = self._conn()
        cols_present = {r[1] for r in conn.execute("PRAGMA table_info(categories)").fetchall()}
        sets = []
        values = []
        for k in ("name", "color", "description"):
            if k in cols_present and k in data:
                sets.append(f"{k} = ?")
                values.append(data[k])
        if not sets:
            return
        values.append(int(category_id))
        conn.execute(
            f"UPDATE categories SET {', '.join(sets)} WHERE id = ?", values
        )
        conn.commit()

    def delete_category(self, category_id: int, reassign_to: int = None) -> int:
        """Delete a category. Reassign its songs to *reassign_to* (or NULL).
        Returns the number of songs that were reassigned."""
        conn = self._conn()
        # Reassign first
        cur = conn.execute(
            "UPDATE songs SET category_id = ? WHERE category_id = ?",
            [reassign_to, int(category_id)],
        )
        moved = cur.rowcount or 0
        conn.execute("DELETE FROM categories WHERE id = ?", [int(category_id)])
        conn.commit()
        return moved

    def get_songs_by_category(self, category_id: int, limit: int = 5) -> list:
        return self._conn().execute(
            """
            SELECT s.id, s.title, s.artist
            FROM   songs s
            WHERE  s.category_id = ?
            ORDER BY s.artist COLLATE NOCASE
            LIMIT ?
            """,
            [int(category_id), int(limit)],
        ).fetchall()

    # ── Artists ───────────────────────────────────────────────────────────────

    def _ensure_artists_table(self) -> None:
        """Create artists table on first use (idempotent)."""
        conn = self._conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artists (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL UNIQUE,
                display_name  TEXT,
                country       TEXT,
                primary_genre TEXT,
                era           TEXT,
                notes         TEXT,
                is_favorite   INTEGER DEFAULT 0,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_artists_name ON artists(name)"
        )
        conn.commit()

    def add_artist(self, data: dict) -> int:
        """Insert a new artist. Returns id. Required: data['name']."""
        self._ensure_artists_table()
        conn = self._conn()
        cur = conn.execute(
            """
            INSERT INTO artists (name, display_name, country, primary_genre, era, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                data.get("name", "").strip(),
                data.get("display_name") or None,
                data.get("country") or None,
                data.get("primary_genre") or None,
                data.get("era") or None,
                data.get("notes") or None,
            ],
        )
        conn.commit()
        return int(cur.lastrowid or 0)

    def get_all_artists(self) -> list:
        """Return every artist with a song-count (joined from the songs table)."""
        self._ensure_artists_table()
        rows = self._conn().execute(
            """
            SELECT a.*,
                   COALESCE(
                       (SELECT COUNT(*) FROM songs s WHERE LOWER(s.artist) = LOWER(a.name)),
                       0
                   ) AS songs_count
            FROM artists a
            ORDER BY a.name COLLATE NOCASE
            """
        ).fetchall()
        return rows

    def search_artists(self, query: str) -> list:
        """Filter artists by substring match on name/country/genre."""
        self._ensure_artists_table()
        q = f"%{(query or '').lower().strip()}%"
        rows = self._conn().execute(
            """
            SELECT a.*,
                   COALESCE(
                       (SELECT COUNT(*) FROM songs s WHERE LOWER(s.artist) = LOWER(a.name)),
                       0
                   ) AS songs_count
            FROM artists a
            WHERE LOWER(a.name) LIKE ?
               OR LOWER(COALESCE(a.country, '')) LIKE ?
               OR LOWER(COALESCE(a.primary_genre, '')) LIKE ?
            ORDER BY a.name COLLATE NOCASE
            """,
            [q, q, q],
        ).fetchall()
        return rows

    def get_artist_by_id(self, artist_id: int):
        self._ensure_artists_table()
        return self._conn().execute(
            "SELECT * FROM artists WHERE id = ?", [int(artist_id)]
        ).fetchone()

    def toggle_artist_favorite(self, artist_id: int) -> bool:
        """Flip is_favorite. Returns the new value."""
        self._ensure_artists_table()
        conn = self._conn()
        row = conn.execute(
            "SELECT is_favorite FROM artists WHERE id = ?", [int(artist_id)]
        ).fetchone()
        if not row:
            return False
        new_val = 0 if int(row[0]) else 1
        conn.execute(
            "UPDATE artists SET is_favorite = ? WHERE id = ?",
            [new_val, int(artist_id)],
        )
        conn.commit()
        return bool(new_val)

    def update_artist(self, artist_id: int, data: dict) -> None:
        self._ensure_artists_table()
        conn = self._conn()
        cols = ["name", "display_name", "country", "primary_genre", "era", "notes"]
        sets = ", ".join(f"{c} = ?" for c in cols if c in data)
        values = [data[c] for c in cols if c in data]
        if not sets:
            return
        values.append(int(artist_id))
        conn.execute(f"UPDATE artists SET {sets} WHERE id = ?", values)
        conn.commit()

    def delete_artist(self, artist_id: int) -> None:
        self._ensure_artists_table()
        conn = self._conn()
        conn.execute("DELETE FROM artists WHERE id = ?", [int(artist_id)])
        conn.commit()

    # ── Song CRUD ─────────────────────────────────────────────────────────────

    def song_exists(self, artist: str, title: str) -> bool:
        """Return True if a song with this artist+title (case-insensitive) is in the library."""
        a = (artist or "").strip().lower()
        t = (title or "").strip().lower()
        if not a or not t:
            return False
        row = self._conn().execute(
            "SELECT 1 FROM songs WHERE LOWER(artist) = ? AND LOWER(title) = ? LIMIT 1",
            [a, t],
        ).fetchone()
        return row is not None

    def add_song(self, song: dict) -> int:
        """Insert a new song. Returns the new song's id."""
        conn = self._conn()
        # Map only columns that exist in the songs table to be defensive
        cols_present = {r[1] for r in conn.execute("PRAGMA table_info(songs)").fetchall()}

        # Ensure the canonical columns we care about
        payload = {}
        for k, v in song.items():
            if k in cols_present:
                payload[k] = v

        # Required defaults
        payload.setdefault("title", song.get("title", "Untitled"))
        payload.setdefault("artist", song.get("artist", "Unknown"))
        if "is_enabled" in cols_present:
            payload.setdefault("is_enabled", 1)

        cols = ", ".join(payload.keys())
        placeholders = ", ".join(["?"] * len(payload))
        cur = conn.execute(
            f"INSERT INTO songs ({cols}) VALUES ({placeholders})",
            list(payload.values()),
        )
        conn.commit()
        return int(cur.lastrowid or 0)

    # ── Legacy compat ─────────────────────────────────────────────────────────

    def execute(self, sql: str, params=()):
        """Compat for legacy engines (auto_scheduler, ai_daily_scheduler).
        SELECT/PRAGMA/WITH → list of rows. Write ops → commit + return []."""
        conn = self._conn()
        cursor = conn.execute(sql, params)
        if sql.strip().upper().startswith(("SELECT", "PRAGMA", "WITH")):
            return cursor.fetchall()
        conn.commit()
        return []
