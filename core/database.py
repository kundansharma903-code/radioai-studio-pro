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
          - ai_rotation_decisions.song_id is a NO-ACTION FK (foreign_keys=ON
            would abort the delete) → DELETE the decision rows; they are a
            short-lived daily plan artifact, not precious history.
          - songs row itself is deleted last.

        All steps run in a single transaction; a single rollback on failure.
        """
        sid = int(song_id)
        self._ensure_ai_rotation_tables()   # before BEGIN (commits internally)
        conn = self._conn()
        try:
            conn.execute("BEGIN")
            # NULL out FK in audit/history tables
            conn.execute("UPDATE broadcast_log SET song_id = NULL WHERE song_id = ?", [sid])
            conn.execute("UPDATE ai_daily_log  SET song_id = NULL WHERE song_id = ?", [sid])
            conn.execute("UPDATE ai_decisions  SET song_id = NULL WHERE song_id = ?", [sid])
            # Rotation AI decision rows reference songs(id) with NO ACTION —
            # must go before the songs row or the delete aborts
            conn.execute("DELETE FROM ai_rotation_decisions WHERE song_id = ?", [sid])
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

    # ── Broadcast log — date/hour queries for Final Log Creator (Figma 14:2) ──

    def get_broadcast_log_for_hour(
        self, year: int, month: int, day: int, hour: int
    ) -> List[sqlite3.Row]:
        """All broadcast_log rows played during a specific clock-hour
        on a specific date, oldest-first. Joins songs/categories/campaigns/
        jingles so the Final Log Creator can render TITLE / ARTIST /
        CATEGORY without per-row lookups.

        `hour` is 0..23 (the start hour of the slot; rows are filtered
        with strftime('%H') == hour so a 10:00–11:00 slot includes
        any row whose played_at hour is exactly 10)."""
        date_s = f"{year:04d}-{month:02d}-{day:02d}"
        hr_s   = f"{hour:02d}"
        return self._conn().execute(
            """
            SELECT bl.*,
                   s.title          AS song_title,
                   s.artist         AS song_artist,
                   s.duration_ms    AS song_duration_ms,
                   c.name           AS cat_name,
                   c.color          AS cat_color,
                   cmp.name         AS campaign_name,
                   j.name           AS jingle_name
            FROM   broadcast_log bl
            LEFT JOIN songs      s   ON bl.song_id     = s.id
            LEFT JOIN categories c   ON s.category_id  = c.id
            LEFT JOIN campaigns  cmp ON bl.campaign_id = cmp.id
            LEFT JOIN jingles    j   ON bl.jingle_id   = j.id
            WHERE  date(bl.played_at) = ?
              AND  strftime('%H', bl.played_at) = ?
            ORDER  BY bl.played_at ASC
            """,
            [date_s, hr_s],
        ).fetchall()

    def get_broadcast_hour_counts_for_date(
        self, year: int, month: int, day: int
    ) -> dict:
        """Returns {hour: count} for hours 0..23 on the given date.
        Hours with zero entries are included (count=0) so the Final
        Log Creator sidebar can render all 24 slots uniformly."""
        date_s = f"{year:04d}-{month:02d}-{day:02d}"
        rows = self._conn().execute(
            """
            SELECT CAST(strftime('%H', played_at) AS INTEGER) AS hr,
                   COUNT(*)                                   AS n
            FROM   broadcast_log
            WHERE  date(played_at) = ?
            GROUP  BY hr
            """,
            [date_s],
        ).fetchall()
        out = {h: 0 for h in range(24)}
        for r in rows:
            out[int(r["hr"])] = int(r["n"])
        return out

    # ── Per-song play history (Figma 437:3 / ui/play_history.py) ──────────

    def get_song_play_history_summary(self, song_id: int) -> dict:
        """Single-song analytics — totals, recency, per-month / per-week
        counters, rolling 4-week average. All driven off broadcast_log
        with date filters in SQLite-native format so the SQL stays
        portable to the production DB."""
        sid = int(song_id)
        conn = self._conn()
        # Totals + first/last played + song-row added_at. The dev DB
        # uses 'entry_date' (older schema); newer installs use
        # 'created_at'. Probe for both — neither failing should kill
        # the summary call.
        cols = {c["name"] for c in conn.execute(
            "PRAGMA table_info(songs)").fetchall()}
        date_col = ("entry_date" if "entry_date" in cols
                    else ("created_at" if "created_at" in cols else None))
        added_at = None
        if date_col is not None:
            try:
                srow = conn.execute(
                    f"SELECT {date_col} AS d FROM songs WHERE id = ?",
                    [sid]).fetchone()
                added_at = srow["d"] if srow else None
            except Exception:
                added_at = None

        total = conn.execute(
            "SELECT COUNT(*) AS n FROM broadcast_log WHERE song_id = ?",
            [sid]).fetchone()
        total_plays = int(total["n"] if total else 0)

        last = conn.execute(
            "SELECT MAX(played_at) AS lp FROM broadcast_log "
            "WHERE song_id = ?", [sid]).fetchone()
        last_played_at = last["lp"] if last else None

        # Month / week buckets — SQLite date('now') is in UTC; localtime
        # keeps the count honest for an operator whose system clock is
        # the broadcast reference. All filters use 'localtime' modifier
        # so we stay consistent with broadcast_log.played_at.
        def cnt(where: str, params: list = None) -> int:
            r = conn.execute(
                f"SELECT COUNT(*) AS n FROM broadcast_log "
                f"WHERE song_id = ? {where}",
                [sid] + (params or [])).fetchone()
            return int(r["n"] if r else 0)

        plays_this_month = cnt(
            "AND strftime('%Y-%m', played_at) = "
            "strftime('%Y-%m', 'now','localtime')")
        plays_last_month = cnt(
            "AND strftime('%Y-%m', played_at) = "
            "strftime('%Y-%m', date('now','localtime','start of month',"
            "'-1 day'))")
        plays_this_week = cnt(
            "AND date(played_at) >= "
            "date('now','localtime','weekday 0','-7 days')")
        plays_last_week = cnt(
            "AND date(played_at) >= "
            "date('now','localtime','weekday 0','-14 days') "
            "AND date(played_at) < "
            "date('now','localtime','weekday 0','-7 days')")
        plays_4_weeks = cnt(
            "AND date(played_at) >= "
            "date('now','localtime','-28 days')")
        avg_per_week = round(plays_4_weeks / 4.0, 1)

        return {
            "song_id":          sid,
            "added_at":         added_at,
            "total_plays":      total_plays,
            "last_played_at":   last_played_at,
            "plays_this_month": plays_this_month,
            "plays_last_month": plays_last_month,
            "plays_this_week":  plays_this_week,
            "plays_last_week":  plays_last_week,
            "avg_per_week":     avg_per_week,
        }

    def get_song_monthly_plays(self, song_id: int,
                                months: int = 12) -> list:
        """Return per-month play counts for the last `months` months,
        oldest-first. Output: list of dicts {year, month, label, count}.
        Months with zero plays are included so the bar chart never has
        gaps."""
        sid = int(song_id)
        n = max(1, min(60, int(months)))
        # Aggregate counts by YYYY-MM
        rows = self._conn().execute(
            "SELECT strftime('%Y-%m', played_at) AS ym, COUNT(*) AS n "
            "FROM broadcast_log "
            "WHERE song_id = ? "
            "AND date(played_at) >= "
            "date('now','localtime','start of month', "
            "'-' || ? || ' months') "
            "GROUP BY ym",
            [sid, n - 1]).fetchall()
        counts_by_ym = {r["ym"]: int(r["n"]) for r in rows}

        # Build the rolling window — oldest..current
        import datetime as _dt
        today = _dt.date.today()
        # First of current month
        cur = _dt.date(today.year, today.month, 1)
        out: list = []
        seq: list = []
        for _ in range(n):
            seq.append((cur.year, cur.month))
            # Step back one month
            if cur.month == 1:
                cur = _dt.date(cur.year - 1, 12, 1)
            else:
                cur = _dt.date(cur.year, cur.month - 1, 1)
        seq.reverse()  # oldest-first

        MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        for (y, m) in seq:
            key = f"{y:04d}-{m:02d}"
            out.append({
                "year":  y,
                "month": m,
                "label": MONTH_LABELS[m - 1],
                "count": counts_by_ym.get(key, 0),
            })
        return out

    def get_song_recent_plays(self, song_id: int,
                                limit: int = 5) -> list:
        """Recent broadcast_log entries for this song joined with the
        clock name + day-of-week / slot info. Most-recent first."""
        sid = int(song_id)
        rows = self._conn().execute(
            """
            SELECT bl.played_at, bl.clock_id, bl.slot_idx, bl.operator,
                   bl.deck,
                   c.name AS clock_name
            FROM   broadcast_log bl
            LEFT JOIN clocks c ON bl.clock_id = c.id
            WHERE  bl.song_id = ?
            ORDER  BY bl.played_at DESC
            LIMIT  ?
            """,
            [sid, int(limit)]).fetchall()
        # Coerce to plain dicts for the screen — saves the consumer
        # from worrying about Row's quirky dict() conversion.
        return [{k: r[k] for k in r.keys()} for r in rows]

    # ── Per-category performance (ui/category_performance.py / Figma 448:3) ──

    def get_category_performance_summary(self, category_id: int) -> dict:
        """Aggregate analytics across every song in this category.

        Returns totals + recency + per-month / per-week counters +
        lifetime-average-per-song + most-played-song identity. Mirrors
        get_song_play_history_summary shape so the screen can lean on
        the same field names.
        """
        cid = int(category_id)
        conn = self._conn()

        cnt_songs = conn.execute(
            "SELECT COUNT(*) AS n FROM songs WHERE category_id = ?",
            [cid]).fetchone()
        song_count = int(cnt_songs["n"] if cnt_songs else 0)

        cat = conn.execute(
            "SELECT name, color FROM categories WHERE id = ?",
            [cid]).fetchone()
        cat_name = (cat["name"] if cat else "") or ""
        cat_color = (cat["color"] if cat and "color" in cat.keys()
                     else "") or ""

        total = conn.execute(
            "SELECT COUNT(*) AS n FROM broadcast_log bl "
            "JOIN songs s ON bl.song_id = s.id "
            "WHERE s.category_id = ?", [cid]).fetchone()
        total_plays = int(total["n"] if total else 0)

        last = conn.execute(
            "SELECT MAX(bl.played_at) AS lp FROM broadcast_log bl "
            "JOIN songs s ON bl.song_id = s.id "
            "WHERE s.category_id = ?", [cid]).fetchone()
        last_played_at = last["lp"] if last else None

        def cnt(where: str) -> int:
            r = conn.execute(
                "SELECT COUNT(*) AS n FROM broadcast_log bl "
                "JOIN songs s ON bl.song_id = s.id "
                "WHERE s.category_id = ? " + where,
                [cid]).fetchone()
            return int(r["n"] if r else 0)

        plays_this_month = cnt(
            "AND strftime('%Y-%m', bl.played_at) = "
            "strftime('%Y-%m', 'now','localtime')")
        plays_last_month = cnt(
            "AND strftime('%Y-%m', bl.played_at) = "
            "strftime('%Y-%m', date('now','localtime',"
            "'start of month','-1 day'))")
        plays_this_week = cnt(
            "AND date(bl.played_at) >= "
            "date('now','localtime','weekday 0','-7 days')")
        plays_last_week = cnt(
            "AND date(bl.played_at) >= "
            "date('now','localtime','weekday 0','-14 days') "
            "AND date(bl.played_at) < "
            "date('now','localtime','weekday 0','-7 days')")

        avg_per_song = round(total_plays / song_count, 1) \
            if song_count > 0 else 0.0

        # Most-played song inside this category.
        top = conn.execute(
            "SELECT s.id, s.title, s.artist, COUNT(bl.id) AS n "
            "FROM   songs s "
            "LEFT JOIN broadcast_log bl ON bl.song_id = s.id "
            "WHERE  s.category_id = ? "
            "GROUP  BY s.id "
            "ORDER  BY n DESC, s.title ASC "
            "LIMIT  1", [cid]).fetchone()
        if top is not None and int(top["n"] or 0) > 0:
            most_played = {
                "id":     int(top["id"]),
                "title":  top["title"] or "—",
                "artist": top["artist"] or "—",
                "count":  int(top["n"] or 0),
            }
        else:
            most_played = None

        return {
            "category_id":      cid,
            "category_name":    cat_name,
            "category_color":   cat_color,
            "song_count":       song_count,
            "total_plays":      total_plays,
            "last_played_at":   last_played_at,
            "plays_this_month": plays_this_month,
            "plays_last_month": plays_last_month,
            "plays_this_week":  plays_this_week,
            "plays_last_week":  plays_last_week,
            "avg_per_song":     avg_per_song,
            "most_played":      most_played,
        }

    def get_category_monthly_plays(self, category_id: int,
                                    months: int = 12) -> list:
        """Per-month aggregate plays for every song in the category,
        oldest-first. Zero-play months included so the bar chart never
        has gaps. Mirrors get_song_monthly_plays output shape."""
        cid = int(category_id)
        n = max(1, min(60, int(months)))
        rows = self._conn().execute(
            "SELECT strftime('%Y-%m', bl.played_at) AS ym, "
            "       COUNT(*) AS n "
            "FROM   broadcast_log bl "
            "JOIN   songs s ON bl.song_id = s.id "
            "WHERE  s.category_id = ? "
            "AND    date(bl.played_at) >= "
            "       date('now','localtime','start of month', "
            "       '-' || ? || ' months') "
            "GROUP  BY ym",
            [cid, n - 1]).fetchall()
        counts_by_ym = {r["ym"]: int(r["n"]) for r in rows}

        import datetime as _dt
        today = _dt.date.today()
        cur = _dt.date(today.year, today.month, 1)
        seq: list = []
        for _ in range(n):
            seq.append((cur.year, cur.month))
            if cur.month == 1:
                cur = _dt.date(cur.year - 1, 12, 1)
            else:
                cur = _dt.date(cur.year, cur.month - 1, 1)
        seq.reverse()

        MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        out = []
        for (y, m) in seq:
            out.append({
                "year":  y,
                "month": m,
                "label": MONTH_LABELS[m - 1],
                "count": counts_by_ym.get(f"{y:04d}-{m:02d}", 0),
            })
        return out

    # ── Spot on the Go (AI Magic submodule) — Create Schedule ─────────────

    def _ensure_sotg_tables(self) -> None:
        """Idempotent CREATE for sotg_shows + sotg_links + their index.
        First call creates; subsequent calls are no-op. Lets the
        Create Schedule screen run on a dev DB that pre-dates the
        schema.sql update without forcing a manual `db_manager.py
        --initialize` pass."""
        conn = self._conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sotg_shows (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                rj_name     TEXT    NOT NULL,
                show_name   TEXT    NOT NULL,
                days        TEXT    NOT NULL DEFAULT 'Daily',
                time_start  TEXT    NOT NULL,
                time_end    TEXT    NOT NULL,
                color       TEXT    DEFAULT '#06b6d4',
                description TEXT    DEFAULT '',
                created_at  TEXT    DEFAULT CURRENT_TIMESTAMP,
                updated_at  TEXT    DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sotg_links (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                show_id     INTEGER NOT NULL
                            REFERENCES sotg_shows(id) ON DELETE CASCADE,
                link_order  INTEGER NOT NULL,
                link_name   TEXT    NOT NULL,
                created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_sotg_links_show
                ON sotg_links(show_id, link_order);
            """
        )
        conn.commit()

    def create_sotg_show(self, *, rj_name: str, show_name: str,
                          days: str, time_start: str, time_end: str,
                          color: str, description: str,
                          link_names: list) -> int:
        """Insert one show + its N link rows in a single transaction.
        Returns the new show id. Raises on any validation slip."""
        self._ensure_sotg_tables()
        rj = (rj_name or "").strip()
        sn = (show_name or "").strip()
        if not rj or not sn:
            raise ValueError("rj_name and show_name are required")
        days_norm = (days or "Daily").strip() or "Daily"
        if days_norm not in ("Daily", "Weekdays", "Weekends"):
            raise ValueError(f"Unknown days value: {days_norm!r}")
        ts = (time_start or "").strip()
        te = (time_end or "").strip()
        if len(ts) != 5 or ts[2] != ":" or len(te) != 5 or te[2] != ":":
            raise ValueError(
                f"time_start/time_end must be HH:MM 24h ({ts!r} {te!r})")
        links = list(link_names or [])
        if len(links) < 1 or len(links) > 12:
            raise ValueError(
                f"link_names must hold 1..12 entries (got {len(links)})")

        conn = self._conn()
        try:
            conn.execute("BEGIN")
            cur = conn.execute(
                "INSERT INTO sotg_shows "
                "(rj_name, show_name, days, time_start, time_end, "
                " color, description) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [rj, sn, days_norm, ts, te,
                 color or "#06b6d4", description or ""])
            show_id = int(cur.lastrowid)
            for i, name in enumerate(links):
                conn.execute(
                    "INSERT INTO sotg_links "
                    "(show_id, link_order, link_name) VALUES (?, ?, ?)",
                    [show_id, i + 1, (name or f"Link {i+1}").strip()])
            conn.commit()
            return show_id
        except Exception:
            conn.rollback()
            raise

    def update_sotg_show(self, show_id: int, *, rj_name: str,
                          show_name: str, days: str, time_start: str,
                          time_end: str, color: str, description: str,
                          link_names: list) -> None:
        """Replace every field on the show + rebuild its link rows from
        scratch. Single transaction. Validates the same as create."""
        self._ensure_sotg_tables()
        sid = int(show_id)
        rj = (rj_name or "").strip()
        sn = (show_name or "").strip()
        if not rj or not sn:
            raise ValueError("rj_name and show_name are required")
        days_norm = (days or "Daily").strip() or "Daily"
        if days_norm not in ("Daily", "Weekdays", "Weekends"):
            raise ValueError(f"Unknown days value: {days_norm!r}")
        ts = (time_start or "").strip()
        te = (time_end or "").strip()
        if len(ts) != 5 or ts[2] != ":" or len(te) != 5 or te[2] != ":":
            raise ValueError(
                f"time_start/time_end must be HH:MM 24h ({ts!r} {te!r})")
        links = list(link_names or [])
        if len(links) < 1 or len(links) > 12:
            raise ValueError(
                f"link_names must hold 1..12 entries (got {len(links)})")

        conn = self._conn()
        try:
            conn.execute("BEGIN")
            conn.execute(
                "UPDATE sotg_shows SET rj_name = ?, show_name = ?, "
                "days = ?, time_start = ?, time_end = ?, color = ?, "
                "description = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                [rj, sn, days_norm, ts, te,
                 color or "#06b6d4", description or "", sid])
            conn.execute("DELETE FROM sotg_links WHERE show_id = ?",
                          [sid])
            for i, name in enumerate(links):
                conn.execute(
                    "INSERT INTO sotg_links "
                    "(show_id, link_order, link_name) VALUES (?, ?, ?)",
                    [sid, i + 1, (name or f"Link {i+1}").strip()])
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def delete_sotg_show(self, show_id: int) -> None:
        """Delete one show — ON DELETE CASCADE drops its links too."""
        self._ensure_sotg_tables()
        conn = self._conn()
        conn.execute("DELETE FROM sotg_shows WHERE id = ?",
                      [int(show_id)])
        conn.commit()

    def get_sotg_shows(self) -> list:
        """List every show + its link count. Ordered by time_start asc
        so the saved-shows table matches the day's chronological flow.
        Output: list of plain dicts."""
        self._ensure_sotg_tables()
        rows = self._conn().execute(
            """
            SELECT s.*,
                   COALESCE(
                     (SELECT COUNT(*) FROM sotg_links l
                      WHERE l.show_id = s.id), 0) AS link_count
            FROM   sotg_shows s
            ORDER  BY s.time_start ASC, s.id ASC
            """
        ).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def get_sotg_show(self, show_id: int) -> Optional[dict]:
        """One show + its link rows nested under 'links'. Returns None
        if the show doesn't exist."""
        self._ensure_sotg_tables()
        sid = int(show_id)
        row = self._conn().execute(
            "SELECT * FROM sotg_shows WHERE id = ?", [sid]).fetchone()
        if row is None:
            return None
        show = {k: row[k] for k in row.keys()}
        link_rows = self._conn().execute(
            "SELECT id, link_order, link_name FROM sotg_links "
            "WHERE show_id = ? ORDER BY link_order ASC",
            [sid]).fetchall()
        show["links"] = [{k: r[k] for k in r.keys()} for r in link_rows]
        return show

    # ── Spot on the Go — Assign (per-day file/time/priority) ──────────────

    def _ensure_sotg_assignments_table(self) -> None:
        """Idempotent CREATE for sotg_assignments + its indexes. Lets
        the Assign screen run on a dev DB that pre-dates the
        schema.sql update without a manual initialize pass.

        Also runs the AI Summary column migration: 2026-05-14 added
        ai_summary / ai_summary_at / ai_provider / ai_status. PRAGMA
        table_info() guards each ALTER so re-running on an already-
        migrated DB is a cheap no-op."""
        self._ensure_sotg_tables()  # parent FKs first
        conn = self._conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sotg_assignments (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                show_id           INTEGER NOT NULL
                                  REFERENCES sotg_shows(id) ON DELETE CASCADE,
                link_id           INTEGER NOT NULL
                                  REFERENCES sotg_links(id) ON DELETE CASCADE,
                scheduled_date    TEXT NOT NULL,
                file_path         TEXT,
                file_name         TEXT,
                file_duration_ms  INTEGER DEFAULT 0,
                sharp_time        TEXT,
                priority          TEXT,
                status            TEXT NOT NULL DEFAULT 'PENDING',
                fired_at          TEXT,
                ai_summary        TEXT,
                ai_summary_at     TEXT,
                ai_provider       TEXT,
                ai_status         TEXT,
                created_at        TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at        TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(link_id, scheduled_date)
            );
            CREATE INDEX IF NOT EXISTS idx_sotg_assignments_date
                ON sotg_assignments(scheduled_date);
            CREATE INDEX IF NOT EXISTS idx_sotg_assignments_show_date
                ON sotg_assignments(show_id, scheduled_date);
            """
        )
        # Migration: dev DBs that pre-date the AI Summary columns
        # need the columns appended. PRAGMA table_info gives the
        # current column set; SQLite has no IF NOT EXISTS for
        # ADD COLUMN, so we check first.
        existing_cols = {
            r["name"] for r in conn.execute(
                "PRAGMA table_info(sotg_assignments)").fetchall()
        }
        for col, ddl in (
            ("ai_summary",    "ALTER TABLE sotg_assignments ADD COLUMN ai_summary TEXT"),
            ("ai_summary_at", "ALTER TABLE sotg_assignments ADD COLUMN ai_summary_at TEXT"),
            ("ai_provider",   "ALTER TABLE sotg_assignments ADD COLUMN ai_provider TEXT"),
            ("ai_status",     "ALTER TABLE sotg_assignments ADD COLUMN ai_status TEXT"),
        ):
            if col not in existing_cols:
                conn.execute(ddl)
        conn.commit()

    @staticmethod
    def _validate_hhmm(s: str) -> bool:
        if not s or len(s) != 5 or s[2] != ":":
            return False
        try:
            hh, mm = int(s[:2]), int(s[3:])
        except ValueError:
            return False
        return 0 <= hh < 24 and 0 <= mm < 60

    def upsert_sotg_assignment(self, *, show_id: int, link_id: int,
                                scheduled_date: str,
                                file_path: Optional[str],
                                file_name: Optional[str],
                                file_duration_ms: int,
                                sharp_time: str,
                                priority: str,
                                status: str = "READY",
                                allow_past: bool = False) -> int:
        """INSERT-or-REPLACE one assignment for (link_id, scheduled_date).
        Server-side guard rejects past times when scheduled_date is
        today + allow_past is False — keeps a stale UI from sneaking a
        past schedule through. Returns the assignment id."""
        self._ensure_sotg_assignments_table()
        sid = int(show_id)
        lid = int(link_id)
        sd = (scheduled_date or "").strip()
        # YYYY-MM-DD validation
        if len(sd) != 10 or sd[4] != "-" or sd[7] != "-":
            raise ValueError(
                f"scheduled_date must be YYYY-MM-DD ({sd!r})")
        st = (sharp_time or "").strip()
        if not self._validate_hhmm(st):
            raise ValueError(
                f"sharp_time must be HH:MM 24h ({st!r})")
        prio_norm = (priority or "").strip().title()
        if prio_norm not in ("High", "Low"):
            raise ValueError(
                f"priority must be 'High' or 'Low' ({priority!r})")
        if status not in ("PENDING", "READY", "FIRED",
                          "MISSED", "CONFLICT"):
            raise ValueError(f"unknown status {status!r}")
        # Past-time guard
        if not allow_past:
            import datetime as _dt
            try:
                d = _dt.date(int(sd[:4]), int(sd[5:7]), int(sd[8:]))
            except ValueError:
                raise ValueError(
                    f"scheduled_date parse failed ({sd!r})")
            today = _dt.date.today()
            if d == today:
                now = _dt.datetime.now()
                hh, mm = int(st[:2]), int(st[3:])
                target_m = hh * 60 + mm
                now_m = now.hour * 60 + now.minute
                if target_m < now_m:
                    raise ValueError(
                        f"Cannot schedule {st} for today — that "
                        f"time has already passed (now "
                        f"{now.strftime('%H:%M')}).")
            elif d < today:
                raise ValueError(
                    f"Cannot schedule for a past date {sd!r}.")

        conn = self._conn()
        # Look up existing row by UNIQUE(link_id, scheduled_date)
        existing = conn.execute(
            "SELECT id FROM sotg_assignments "
            "WHERE link_id = ? AND scheduled_date = ?",
            [lid, sd]).fetchone()
        if existing:
            conn.execute(
                "UPDATE sotg_assignments SET show_id = ?, "
                "file_path = ?, file_name = ?, "
                "file_duration_ms = ?, sharp_time = ?, "
                "priority = ?, status = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [sid, file_path, file_name,
                 int(file_duration_ms or 0), st, prio_norm,
                 status, int(existing["id"])])
            aid = int(existing["id"])
        else:
            cur = conn.execute(
                "INSERT INTO sotg_assignments "
                "(show_id, link_id, scheduled_date, file_path, "
                " file_name, file_duration_ms, sharp_time, "
                " priority, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [sid, lid, sd, file_path, file_name,
                 int(file_duration_ms or 0), st, prio_norm,
                 status])
            aid = int(cur.lastrowid)
        conn.commit()
        return aid

    def delete_sotg_assignment(self, assignment_id: int) -> None:
        """Drop one assignment by id."""
        self._ensure_sotg_assignments_table()
        conn = self._conn()
        conn.execute("DELETE FROM sotg_assignments WHERE id = ?",
                      [int(assignment_id)])
        conn.commit()

    def mark_sotg_assignment_fired(self, assignment_id: int,
                                     fired_at: Optional[str] = None) -> None:
        """Stamp status = FIRED on the assignment + fired_at timestamp.
        Audio engine should call this after a successful link play."""
        self._ensure_sotg_assignments_table()
        from datetime import datetime as _dt
        ts = fired_at or _dt.now().isoformat(timespec="seconds")
        conn = self._conn()
        conn.execute(
            "UPDATE sotg_assignments "
            "SET status = 'FIRED', fired_at = ?, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?", [ts, int(assignment_id)])
        conn.commit()

    def get_sotg_assignment(self, link_id: int,
                              scheduled_date: str) -> Optional[dict]:
        """Single assignment lookup keyed by the UNIQUE(link, date)
        constraint. Returns None if not yet authored for that day."""
        self._ensure_sotg_assignments_table()
        row = self._conn().execute(
            "SELECT * FROM sotg_assignments "
            "WHERE link_id = ? AND scheduled_date = ?",
            [int(link_id), (scheduled_date or "").strip()]).fetchone()
        return {k: row[k] for k in row.keys()} if row else None

    def get_sotg_assignments_for_show_date(self, show_id: int,
                                             scheduled_date: str
                                             ) -> list:
        """All assignments for one (show, date) tuple, joined with the
        link template so the UI can render link_order + link_name
        alongside the file/time/priority/status. Sorted by link_order."""
        self._ensure_sotg_assignments_table()
        sid = int(show_id)
        sd = (scheduled_date or "").strip()
        rows = self._conn().execute(
            """
            SELECT  l.id            AS link_id,
                    l.link_order    AS link_order,
                    l.link_name     AS link_name,
                    a.id            AS assignment_id,
                    a.file_path     AS file_path,
                    a.file_name     AS file_name,
                    a.file_duration_ms AS file_duration_ms,
                    a.sharp_time    AS sharp_time,
                    a.priority      AS priority,
                    a.status        AS status,
                    a.fired_at      AS fired_at
            FROM    sotg_links l
            LEFT JOIN sotg_assignments a
                ON  a.link_id = l.id
                AND a.scheduled_date = ?
            WHERE   l.show_id = ?
            ORDER BY l.link_order ASC
            """,
            [sd, sid]).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def get_sotg_assignments_for_date(self, scheduled_date: str,
                                        status: Optional[str] = None
                                        ) -> list:
        """All assignments on the given date, optionally filtered by
        status. Joined with the link template + show envelope so the
        dispatcher has everything it needs to fire. Ordered by sharp
        time ascending — earliest first.

        Includes the AI Summary columns (ai_summary, ai_summary_at,
        ai_provider, ai_status) so the Generate Report screen + PDF
        can render the italicized 4-line summary sub-block under each
        link, and the Assign API Key screen's live preview can show
        per-row transcription state."""
        self._ensure_sotg_assignments_table()
        sd = (scheduled_date or "").strip()
        params = [sd]
        sql = """
            SELECT  a.id            AS assignment_id,
                    a.show_id       AS show_id,
                    a.link_id       AS link_id,
                    a.scheduled_date AS scheduled_date,
                    a.file_path     AS file_path,
                    a.file_name     AS file_name,
                    a.file_duration_ms AS file_duration_ms,
                    a.sharp_time    AS sharp_time,
                    a.priority      AS priority,
                    a.status        AS status,
                    a.fired_at      AS fired_at,
                    a.ai_summary    AS ai_summary,
                    a.ai_summary_at AS ai_summary_at,
                    a.ai_provider   AS ai_provider,
                    a.ai_status     AS ai_status,
                    l.link_order    AS link_order,
                    l.link_name     AS link_name,
                    s.show_name     AS show_name,
                    s.rj_name       AS rj_name,
                    s.color         AS color
            FROM    sotg_assignments a
            JOIN    sotg_links l ON l.id = a.link_id
            JOIN    sotg_shows s ON s.id = a.show_id
            WHERE   a.scheduled_date = ?
        """
        if status:
            sql += " AND a.status = ?"
            params.append(status)
        sql += " ORDER BY a.sharp_time ASC, a.id ASC"
        rows = self._conn().execute(sql, params).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def mark_sotg_assignment_missed(self, assignment_id: int) -> None:
        """Stamp status = MISSED. Used by the dispatcher when an
        assignment's sharp time has slipped past its tolerance window
        with no fire."""
        self._ensure_sotg_assignments_table()
        conn = self._conn()
        conn.execute(
            "UPDATE sotg_assignments SET status = 'MISSED', "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [int(assignment_id)])
        conn.commit()

    def get_sotg_assignment_counts_for_date(
            self, scheduled_date: str) -> dict:
        """Per-show breakdown for a given date:
            { show_id: {'total': N, 'ready': K, 'fired': F,
                        'missed': M, 'conflict': C, 'pending': P } }
        Used by the left-panel show cards to render the X/Y badge +
        mini status icons."""
        self._ensure_sotg_assignments_table()
        sd = (scheduled_date or "").strip()
        out: dict = {}
        # First: every show's total link count.
        show_rows = self._conn().execute(
            "SELECT s.id, COUNT(l.id) AS total "
            "FROM sotg_shows s "
            "LEFT JOIN sotg_links l ON l.show_id = s.id "
            "GROUP BY s.id"
        ).fetchall()
        for r in show_rows:
            out[int(r["id"])] = {
                "total": int(r["total"] or 0),
                "ready": 0, "fired": 0, "missed": 0,
                "conflict": 0, "pending": 0,
            }
        # Then: per-status counts for assignments on this date.
        agg = self._conn().execute(
            "SELECT show_id, status, COUNT(*) AS n "
            "FROM sotg_assignments WHERE scheduled_date = ? "
            "GROUP BY show_id, status", [sd]).fetchall()
        for r in agg:
            sid = int(r["show_id"])
            if sid not in out:
                out[sid] = {"total": 0, "ready": 0, "fired": 0,
                             "missed": 0, "conflict": 0, "pending": 0}
            key = (r["status"] or "PENDING").lower()
            if key in out[sid]:
                out[sid][key] = int(r["n"] or 0)
        return out

    # ── SOTG AI Summary helpers ────────────────────────────────────────

    def set_sotg_assignment_summary(self, assignment_id: int, *,
                                      summary: Optional[str],
                                      provider: Optional[str],
                                      status: str) -> None:
        """Persist a transcription result for one SOTG assignment.

        ``summary`` — the 4-line English summary text (None when status
                      is PROCESSING / FAILED / SKIPPED).
        ``provider`` — 'gemini' or 'openai' (None when no attempt made).
        ``status`` — PENDING / PROCESSING / DONE / FAILED / SKIPPED.

        Called by core/sotg_transcription_engine.py at every stage of
        the per-drop pipeline."""
        self._ensure_sotg_assignments_table()
        if status not in ("PENDING", "PROCESSING", "DONE",
                          "FAILED", "SKIPPED"):
            raise ValueError(f"unknown ai_status {status!r}")
        if provider is not None and provider not in ("gemini", "openai"):
            raise ValueError(f"unknown ai_provider {provider!r}")
        from datetime import datetime as _dt
        ts = _dt.now().isoformat(timespec="seconds") if status == "DONE" else None
        conn = self._conn()
        conn.execute(
            "UPDATE sotg_assignments SET "
            "  ai_summary = ?, ai_summary_at = ?, ai_provider = ?, "
            "  ai_status = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            [summary, ts, provider, status, int(assignment_id)])
        conn.commit()

    def get_sotg_assignment_by_id(self, assignment_id: int
                                    ) -> Optional[dict]:
        """Single-row lookup by primary key — joined with the link +
        show context the transcription engine needs to build summary
        prompts (RJ name, show name, link title)."""
        self._ensure_sotg_assignments_table()
        row = self._conn().execute(
            """
            SELECT  a.*,
                    l.link_order    AS link_order,
                    l.link_name     AS link_name,
                    s.show_name     AS show_name,
                    s.rj_name       AS rj_name
            FROM    sotg_assignments a
            JOIN    sotg_links l ON l.id = a.link_id
            JOIN    sotg_shows s ON s.id = a.show_id
            WHERE   a.id = ?
            """, [int(assignment_id)]).fetchone()
        return {k: row[k] for k in row.keys()} if row else None

    def get_pending_transcription_assignments(self, limit: int = 50
                                                ) -> list:
        """Backfill query — every FIRED assignment without a DONE
        ai_status, capped at ``limit`` most-recent first (ORDER BY
        fired_at DESC). Skips rows with no file_path (nothing to
        transcribe). Used by the Backfill Missing button."""
        self._ensure_sotg_assignments_table()
        rows = self._conn().execute(
            """
            SELECT  a.*,
                    l.link_order    AS link_order,
                    l.link_name     AS link_name,
                    s.show_name     AS show_name,
                    s.rj_name       AS rj_name
            FROM    sotg_assignments a
            JOIN    sotg_links l ON l.id = a.link_id
            JOIN    sotg_shows s ON s.id = a.show_id
            WHERE   a.status = 'FIRED'
            AND     (a.ai_status IS NULL OR a.ai_status != 'DONE')
            AND     a.file_path IS NOT NULL
            ORDER BY a.fired_at DESC, a.id DESC
            LIMIT   ?
            """, [int(limit)]).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def get_sotg_summary_counts_today(self) -> dict:
        """Hero stat-pill numbers for the Assign API Key screen:
        ``{ "done": N, "pending": K, "failed": F }``  for today's
        FIRED rows. PENDING here means status NULL or PROCESSING."""
        self._ensure_sotg_assignments_table()
        from datetime import date as _date
        today = _date.today().isoformat()
        agg = self._conn().execute(
            "SELECT ai_status, COUNT(*) AS n FROM sotg_assignments "
            "WHERE scheduled_date = ? AND status = 'FIRED' "
            "GROUP BY ai_status", [today]).fetchall()
        out = {"done": 0, "pending": 0, "failed": 0}
        for r in agg:
            s = (r["ai_status"] or "PENDING").upper()
            if s == "DONE":
                out["done"] += int(r["n"] or 0)
            elif s == "FAILED":
                out["failed"] += int(r["n"] or 0)
            else:    # PENDING / PROCESSING / SKIPPED / None
                out["pending"] += int(r["n"] or 0)
        return out

    # ══════════════════════════════════════════════════════════════════
    # AI Magic · Scheduling Automation — rotation engine (Phase C)
    # ══════════════════════════════════════════════════════════════════
    #
    # 4 tables: sister_groups, sister_group_members, ai_rotation_plans,
    # ai_rotation_decisions. All migrations idempotent via PRAGMA
    # table_info checks so dev DBs that pre-date Phase C migrate on
    # first call.

    _SISTER_GROUP_MAX = 5    # operator's Q-A cap

    def _ensure_ai_rotation_tables(self) -> None:
        """Idempotent CREATE for the rotation AI tables. Called by every
        helper below so the schema lands on first use even on a dev DB
        that hasn't run db_manager.py --initialize. Mirrors the schema
        in database/schema.sql."""
        conn = self._conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sister_groups (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS sister_group_members (
                group_id    INTEGER NOT NULL
                            REFERENCES sister_groups(id) ON DELETE CASCADE,
                category_id INTEGER NOT NULL
                            REFERENCES categories(id) ON DELETE CASCADE,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (group_id, category_id),
                UNIQUE (category_id)
            );

            CREATE INDEX IF NOT EXISTS idx_sister_members_group
                ON sister_group_members(group_id);
            CREATE INDEX IF NOT EXISTS idx_sister_members_category
                ON sister_group_members(category_id);

            CREATE TABLE IF NOT EXISTS ai_rotation_plans (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_date       TEXT NOT NULL UNIQUE,
                status          TEXT NOT NULL DEFAULT 'pending',
                total_changes   INTEGER DEFAULT 0,
                rested_count    INTEGER DEFAULT 0,
                promoted_count  INTEGER DEFAULT 0,
                clocks_balanced INTEGER DEFAULT 0,
                error_count     INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
                approved_at     TEXT,
                discarded_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS ai_rotation_decisions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id             INTEGER NOT NULL
                                    REFERENCES ai_rotation_plans(id)
                                    ON DELETE CASCADE,
                decision_date       TEXT NOT NULL,
                clock_id            INTEGER NOT NULL
                                    REFERENCES clocks(id) ON DELETE CASCADE,
                hour                INTEGER NOT NULL,
                slot_idx            INTEGER,
                song_id             INTEGER REFERENCES songs(id),
                action              TEXT NOT NULL,
                source_category_id  INTEGER REFERENCES categories(id),
                target_category_id  INTEGER REFERENCES categories(id),
                reason              TEXT,
                created_at          TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_rotation_decisions_date
                ON ai_rotation_decisions(decision_date);
            CREATE INDEX IF NOT EXISTS idx_rotation_decisions_clock_date
                ON ai_rotation_decisions(clock_id, decision_date);
            CREATE INDEX IF NOT EXISTS idx_rotation_decisions_song
                ON ai_rotation_decisions(song_id);
            CREATE INDEX IF NOT EXISTS idx_rotation_decisions_plan
                ON ai_rotation_decisions(plan_id);
            """
        )
        conn.commit()

    # ── Sister Group helpers ───────────────────────────────────────────

    def create_sister_group(self, category_ids: list[int]) -> int:
        """Create a new sister group containing the listed categories.

        Validates:
          • 2 ≤ len(category_ids) ≤ 5  (operator's cap)
          • All ids are unique within the input list
          • All ids reference real categories
          • No id is already a member of another group

        Returns the new group id. Atomic — the whole insertion either
        succeeds or rolls back."""
        self._ensure_ai_rotation_tables()
        if not isinstance(category_ids, (list, tuple)):
            raise ValueError(
                f"category_ids must be a list/tuple, got "
                f"{type(category_ids).__name__}")
        # Normalize + dedupe-aware validation
        try:
            ids = [int(c) for c in category_ids]
        except (TypeError, ValueError):
            raise ValueError(
                f"category_ids must be all ints, got {category_ids!r}")
        if len(ids) < 2:
            raise ValueError(
                f"sister group needs at least 2 categories, "
                f"got {len(ids)}")
        if len(ids) > self._SISTER_GROUP_MAX:
            raise ValueError(
                f"sister group capped at {self._SISTER_GROUP_MAX} "
                f"categories, got {len(ids)}")
        if len(set(ids)) != len(ids):
            raise ValueError(
                f"duplicate category ids in input: {ids!r}")

        conn = self._conn()
        # All ids must reference real categories
        found_rows = conn.execute(
            "SELECT id FROM categories WHERE id IN ("
            + ",".join("?" * len(ids)) + ")",
            ids).fetchall()
        found_ids = {int(r["id"]) for r in found_rows}
        missing = [c for c in ids if c not in found_ids]
        if missing:
            raise ValueError(
                f"unknown category id(s): {missing!r}")

        # No id should be in another group already
        existing = conn.execute(
            "SELECT category_id, group_id FROM sister_group_members "
            "WHERE category_id IN ("
            + ",".join("?" * len(ids)) + ")",
            ids).fetchall()
        if existing:
            collisions = [
                f"category {int(r['category_id'])} already in group "
                f"{int(r['group_id'])}"
                for r in existing
            ]
            raise ValueError(
                "sister group create failed — " + "; ".join(collisions))

        # Atomic insert
        try:
            cur = conn.execute(
                "INSERT INTO sister_groups DEFAULT VALUES")
            group_id = int(cur.lastrowid)
            conn.executemany(
                "INSERT INTO sister_group_members (group_id, category_id) "
                "VALUES (?, ?)",
                [(group_id, c) for c in ids])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return group_id

    def delete_sister_group(self, group_id: int) -> None:
        """Drop a group + cascade-delete its members. Idempotent —
        deleting a non-existent group is a no-op."""
        self._ensure_ai_rotation_tables()
        conn = self._conn()
        conn.execute("DELETE FROM sister_groups WHERE id = ?",
                      [int(group_id)])
        conn.commit()

    def add_category_to_sister_group(self, group_id: int,
                                       category_id: int) -> None:
        """Add a category to an existing group. Enforces the 5-cap +
        per-category uniqueness."""
        self._ensure_ai_rotation_tables()
        gid = int(group_id); cid = int(category_id)
        conn = self._conn()
        # Group must exist
        row = conn.execute(
            "SELECT id FROM sister_groups WHERE id = ?",
            [gid]).fetchone()
        if row is None:
            raise ValueError(f"sister group {gid} does not exist")
        # Category must exist
        row = conn.execute(
            "SELECT id FROM categories WHERE id = ?",
            [cid]).fetchone()
        if row is None:
            raise ValueError(f"category {cid} does not exist")
        # Cap check
        count = int(conn.execute(
            "SELECT COUNT(*) FROM sister_group_members "
            "WHERE group_id = ?", [gid]).fetchone()[0])
        if count >= self._SISTER_GROUP_MAX:
            raise ValueError(
                f"sister group {gid} is full "
                f"({self._SISTER_GROUP_MAX} categories)")
        # Already in some group? (UNIQUE constraint would also catch
        # this, but we want a clean error message)
        in_group = conn.execute(
            "SELECT group_id FROM sister_group_members "
            "WHERE category_id = ?", [cid]).fetchone()
        if in_group is not None:
            other = int(in_group["group_id"])
            if other == gid:
                return    # idempotent — already in this group
            raise ValueError(
                f"category {cid} already in sister group {other}")
        conn.execute(
            "INSERT INTO sister_group_members (group_id, category_id) "
            "VALUES (?, ?)", [gid, cid])
        conn.commit()

    def remove_category_from_sister_group(self, group_id: int,
                                            category_id: int) -> None:
        """Remove a category from a group. If membership drops below 2,
        the group is auto-deleted (1-member groups are meaningless)."""
        self._ensure_ai_rotation_tables()
        gid = int(group_id); cid = int(category_id)
        conn = self._conn()
        conn.execute(
            "DELETE FROM sister_group_members "
            "WHERE group_id = ? AND category_id = ?",
            [gid, cid])
        remaining = int(conn.execute(
            "SELECT COUNT(*) FROM sister_group_members "
            "WHERE group_id = ?", [gid]).fetchone()[0])
        if remaining < 2:
            conn.execute(
                "DELETE FROM sister_groups WHERE id = ?", [gid])
        conn.commit()

    def get_sister_groups(self) -> list:
        """All sister groups with their category details + per-group
        total-song count. Each entry:
          {
            'id': int,
            'categories': [{'id', 'name', 'color'}, ...],
            'total_songs': int,
            'created_at': str,
          }
        Sorted by created_at ASC (oldest first).

        Only groups with ≥1 member are returned — orphan envelopes
        (e.g. created by a partial test teardown where members
        cascaded out but the parent row remained) are filtered out
        at the SQL level. Operator's 2-min rule says any valid group
        must have at least 2 members; the engine also auto-deletes
        groups that drop below 2 via remove_category_from_sister_group.
        Filtering at read-time is the defensive belt to that braces."""
        self._ensure_ai_rotation_tables()
        conn = self._conn()
        group_rows = conn.execute(
            "SELECT id, created_at FROM sister_groups "
            "WHERE EXISTS ("
            "  SELECT 1 FROM sister_group_members "
            "  WHERE group_id = sister_groups.id"
            ") "
            "ORDER BY created_at ASC, id ASC").fetchall()
        out: list = []
        for g in group_rows:
            gid = int(g["id"])
            members = conn.execute(
                "SELECT c.id, c.name, c.color "
                "FROM sister_group_members m "
                "JOIN categories c ON c.id = m.category_id "
                "WHERE m.group_id = ? "
                "ORDER BY c.display_order ASC, c.name ASC",
                [gid]).fetchall()
            cats = [{"id": int(r["id"]),
                      "name": r["name"] or "",
                      "color": r["color"] or "#06b6d4"}
                     for r in members]
            # Aggregate song count across all member categories
            total = 0
            if cats:
                placeholders = ",".join("?" * len(cats))
                total_row = conn.execute(
                    f"SELECT COUNT(*) FROM songs "
                    f"WHERE is_enabled = 1 AND category_id IN ({placeholders})",
                    [c["id"] for c in cats]).fetchone()
                total = int(total_row[0] or 0)
            out.append({
                "id":           gid,
                "categories":   cats,
                "total_songs":  total,
                "created_at":   g["created_at"] or "",
            })
        return out

    def get_sister_group_for_category(self, category_id: int):
        """Return the group_id this category belongs to, or None if
        ungrouped."""
        self._ensure_ai_rotation_tables()
        row = self._conn().execute(
            "SELECT group_id FROM sister_group_members "
            "WHERE category_id = ?",
            [int(category_id)]).fetchone()
        return int(row["group_id"]) if row else None

    def get_sister_pool_for_category(self, category_id: int) -> list:
        """Return all category ids in the same sister group as the
        given category — including the category itself. If the category
        is ungrouped, returns ``[category_id]`` (pool of 1).

        Used by the rotation engine: when a clock's primary category
        is X, the eligible-song pool is union(X + sisters)."""
        self._ensure_ai_rotation_tables()
        cid = int(category_id)
        gid = self.get_sister_group_for_category(cid)
        if gid is None:
            return [cid]
        rows = self._conn().execute(
            "SELECT category_id FROM sister_group_members "
            "WHERE group_id = ? ORDER BY category_id ASC",
            [gid]).fetchall()
        ids = [int(r["category_id"]) for r in rows]
        if cid not in ids:
            ids.append(cid)
        return sorted(ids)

    # ── AI Rotation Plan helpers ───────────────────────────────────────

    def get_or_create_ai_rotation_plan(self, plan_date: str) -> int:
        """Get-or-create the daily plan envelope. Returns plan_id.
        Fresh plans default to status='pending' + zero counters."""
        self._ensure_ai_rotation_tables()
        pd = (plan_date or "").strip()
        if len(pd) != 10 or pd[4] != "-" or pd[7] != "-":
            raise ValueError(
                f"plan_date must be YYYY-MM-DD, got {pd!r}")
        conn = self._conn()
        row = conn.execute(
            "SELECT id FROM ai_rotation_plans WHERE plan_date = ?",
            [pd]).fetchone()
        if row is not None:
            return int(row["id"])
        cur = conn.execute(
            "INSERT INTO ai_rotation_plans (plan_date) VALUES (?)",
            [pd])
        conn.commit()
        return int(cur.lastrowid)

    def reset_ai_rotation_plan(self, plan_date: str) -> int:
        """Wipe today's decisions + reset envelope to status='pending'.
        Called by the engine before re-computing a plan from scratch.
        Returns the (refreshed) plan_id."""
        self._ensure_ai_rotation_tables()
        plan_id = self.get_or_create_ai_rotation_plan(plan_date)
        conn = self._conn()
        conn.execute(
            "DELETE FROM ai_rotation_decisions WHERE plan_id = ?",
            [plan_id])
        conn.execute(
            "UPDATE ai_rotation_plans SET "
            "  status = 'pending', total_changes = 0, "
            "  rested_count = 0, promoted_count = 0, "
            "  clocks_balanced = 0, error_count = 0, "
            "  approved_at = NULL, discarded_at = NULL "
            "WHERE id = ?", [plan_id])
        conn.commit()
        return plan_id

    def add_rotation_decision(self, *, plan_id: int,
                                 decision_date: str,
                                 clock_id: int,
                                 hour: int,
                                 song_id,
                                 action: str,
                                 slot_idx=None,
                                 source_category_id=None,
                                 target_category_id=None,
                                 reason: str = "") -> int:
        """Insert one rotation decision row. ``action`` must be
        'rest' or 'promote'. Returns the new row id."""
        self._ensure_ai_rotation_tables()
        if action not in ("rest", "promote", "pick"):
            raise ValueError(
                f"action must be 'rest', 'promote', or 'pick', "
                f"got {action!r}")
        h = int(hour)
        if h < 0 or h > 23:
            raise ValueError(f"hour must be 0-23, got {hour!r}")
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO ai_rotation_decisions "
            "(plan_id, decision_date, clock_id, hour, slot_idx, "
            " song_id, action, source_category_id, "
            " target_category_id, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [int(plan_id), (decision_date or "").strip(),
             int(clock_id), h,
             None if slot_idx is None else int(slot_idx),
             None if song_id is None else int(song_id),
             action,
             None if source_category_id is None
                 else int(source_category_id),
             None if target_category_id is None
                 else int(target_category_id),
             reason or ""])
        conn.commit()
        return int(cur.lastrowid)

    def update_ai_rotation_plan_stats(self, plan_id: int, *,
                                        rested: int = 0,
                                        promoted: int = 0,
                                        clocks_balanced: int = 0,
                                        errors: int = 0) -> None:
        """Refresh the plan envelope's aggregate counters after the
        engine writes a batch of decisions."""
        self._ensure_ai_rotation_tables()
        conn = self._conn()
        conn.execute(
            "UPDATE ai_rotation_plans SET "
            "  rested_count = ?, promoted_count = ?, "
            "  clocks_balanced = ?, error_count = ?, "
            "  total_changes = ? "
            "WHERE id = ?",
            [int(rested), int(promoted), int(clocks_balanced),
             int(errors), int(rested) + int(promoted),
             int(plan_id)])
        conn.commit()

    def get_ai_rotation_plan(self, plan_date: str):
        """Return the plan envelope for a date as a dict, or None if
        no plan computed yet."""
        self._ensure_ai_rotation_tables()
        row = self._conn().execute(
            "SELECT * FROM ai_rotation_plans WHERE plan_date = ?",
            [(plan_date or "").strip()]).fetchone()
        return {k: row[k] for k in row.keys()} if row else None

    def mark_ai_rotation_plan_approved(self, plan_date: str) -> None:
        """Stamp status='approved' + approved_at timestamp."""
        self._ensure_ai_rotation_tables()
        from datetime import datetime as _dt
        ts = _dt.now().isoformat(timespec="seconds")
        conn = self._conn()
        conn.execute(
            "UPDATE ai_rotation_plans SET "
            "  status = 'approved', approved_at = ? "
            "WHERE plan_date = ?",
            [ts, (plan_date or "").strip()])
        conn.commit()

    def mark_ai_rotation_plan_discarded(self, plan_date: str) -> None:
        """Stamp status='discarded' + discarded_at + WIPE the decision
        rows (the engine will compute again on next tick)."""
        self._ensure_ai_rotation_tables()
        from datetime import datetime as _dt
        ts = _dt.now().isoformat(timespec="seconds")
        conn = self._conn()
        # Stamp envelope
        conn.execute(
            "UPDATE ai_rotation_plans SET "
            "  status = 'discarded', discarded_at = ? "
            "WHERE plan_date = ?",
            [ts, (plan_date or "").strip()])
        # Wipe associated decisions
        plan = self.get_ai_rotation_plan(plan_date)
        if plan:
            conn.execute(
                "DELETE FROM ai_rotation_decisions WHERE plan_id = ?",
                [int(plan["id"])])
        conn.commit()

    def mark_ai_rotation_plan_auto_applied(self, plan_date: str) -> None:
        """Stamp status='auto_applied' (5-PM safety net path). Decisions
        stay in place so dispatcher consults them."""
        self._ensure_ai_rotation_tables()
        from datetime import datetime as _dt
        ts = _dt.now().isoformat(timespec="seconds")
        conn = self._conn()
        conn.execute(
            "UPDATE ai_rotation_plans SET "
            "  status = 'auto_applied', approved_at = ? "
            "WHERE plan_date = ?",
            [ts, (plan_date or "").strip()])
        conn.commit()

    def get_rotation_decisions_for_date(self, plan_date: str) -> list:
        """All decisions for a date joined with song / clock / category
        metadata for the Daily Plan Review screen. Sorted by hour ASC,
        then clock_id, then created_at."""
        self._ensure_ai_rotation_tables()
        rows = self._conn().execute(
            """
            SELECT  d.*,
                    s.title         AS song_title,
                    s.artist        AS song_artist,
                    c.name          AS clock_name,
                    cs.name         AS source_category_name,
                    cs.color        AS source_category_color,
                    ct.name         AS target_category_name,
                    ct.color        AS target_category_color
            FROM    ai_rotation_decisions d
            LEFT JOIN songs s       ON s.id  = d.song_id
            LEFT JOIN clocks c      ON c.id  = d.clock_id
            LEFT JOIN categories cs ON cs.id = d.source_category_id
            LEFT JOIN categories ct ON ct.id = d.target_category_id
            WHERE   d.decision_date = ?
            ORDER BY d.hour ASC, d.clock_id ASC, d.created_at ASC
            """, [(plan_date or "").strip()]).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def get_rotation_decisions_for_clock(self, clock_id: int,
                                            plan_date: str) -> list:
        """All decisions for one (clock, date) tuple — drives the
        per-card view in Daily Plan Review."""
        self._ensure_ai_rotation_tables()
        rows = self._conn().execute(
            """
            SELECT  d.*,
                    s.title         AS song_title,
                    s.artist        AS song_artist,
                    cs.name         AS source_category_name,
                    cs.color        AS source_category_color,
                    ct.name         AS target_category_name,
                    ct.color        AS target_category_color
            FROM    ai_rotation_decisions d
            LEFT JOIN songs s       ON s.id  = d.song_id
            LEFT JOIN categories cs ON cs.id = d.source_category_id
            LEFT JOIN categories ct ON ct.id = d.target_category_id
            WHERE   d.clock_id = ? AND d.decision_date = ?
            ORDER BY d.created_at ASC
            """, [int(clock_id), (plan_date or "").strip()]).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def get_active_rotation_decisions(self, plan_date: str,
                                         clock_id: int,
                                         hour: int) -> dict:
        """Read-only consult helper for SchedulerEngine._pick_song
        (BUG-2/BUG-3 fix): the decisions the operator actually
        approved for one (date, clock, hour) tuple.

        Returns:
            {'active': False, 'rest_ids': set(), 'picks': []}
                when no plan exists for the date OR its status is not
                'approved'/'auto_applied' (pending/discarded = the AI
                has no authority on air);
            {'active': True,
             'rest_ids': {song_id, ...},        # action='rest' rows
             'picks':    [{song_id, title, artist, file_path,
                           duration_ms, action}, ...]}
                                                # 'pick'/'promote' rows
        Picks are JOINed against songs with is_enabled=1 and a
        non-empty file_path so the scheduler can air them directly.
        SELECT-only — never writes."""
        self._ensure_ai_rotation_tables()
        out: dict = {"active": False, "rest_ids": set(), "picks": []}
        plan = self.get_ai_rotation_plan(plan_date)
        if not plan or plan.get("status") not in (
                "approved", "auto_applied"):
            return out
        out["active"] = True
        rows = self._conn().execute(
            """
            SELECT  d.song_id, d.action,
                    s.title, s.artist, s.file_path, s.duration_ms
            FROM    ai_rotation_decisions d
            JOIN    songs s ON s.id = d.song_id
            WHERE   d.plan_id  = ?
              AND   d.clock_id = ?
              AND   d.hour     = ?
              AND   d.song_id IS NOT NULL
              AND   s.is_enabled = 1
            """,
            [int(plan["id"]), int(clock_id), int(hour)]).fetchall()
        for r in rows:
            action = (r["action"] or "").strip().lower()
            if action == "rest":
                out["rest_ids"].add(int(r["song_id"]))
            elif action in ("pick", "promote"):
                if r["file_path"]:
                    out["picks"].append({
                        "song_id":     int(r["song_id"]),
                        "title":       r["title"],
                        "artist":      r["artist"],
                        "file_path":   r["file_path"],
                        "duration_ms": r["duration_ms"],
                        "action":      action,
                    })
        return out

    def purge_old_rotation_decisions(self, retention_days: int = 14) -> int:
        """Delete plan envelopes + cascade-delete decisions older than
        ``retention_days``. Returns count of plans deleted. Run by the
        engine's nightly maintenance tick."""
        self._ensure_ai_rotation_tables()
        from datetime import date as _date, timedelta as _td
        cutoff = (_date.today() - _td(days=int(retention_days))).isoformat()
        conn = self._conn()
        cur = conn.execute(
            "DELETE FROM ai_rotation_plans WHERE plan_date < ?",
            [cutoff])
        conn.commit()
        return cur.rowcount or 0

    # ── Time-Slot Freshness input ──────────────────────────────────────

    def get_songs_in_categories(self, category_ids: list,
                                   enabled_only: bool = True) -> list:
        """Return enabled songs whose category_id is in the given list.
        Used by RotationAIEngine to build the sister-category-aware
        candidate pool for a clock's primary category. Returns plain
        dicts (sqlite3.Row dicts get flaky on Py 3.14)."""
        if not category_ids:
            return []
        ids = [int(c) for c in category_ids]
        placeholders = ",".join("?" * len(ids))
        sql = (
            f"SELECT s.id, s.title, s.artist, s.category_id, "
            f"  s.file_path, s.duration_ms, s.year, s.bpm, "
            f"  s.energy, s.vocal "
            f"FROM songs s "
            f"WHERE s.category_id IN ({placeholders}) "
            f"{'AND s.is_enabled = 1' if enabled_only else ''} "
            f"AND s.file_path IS NOT NULL AND s.file_path != '' "
            f"ORDER BY s.id ASC"
        )
        rows = self._conn().execute(sql, ids).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def get_all_enabled_songs(self) -> list:
        """Return ALL enabled songs with a real on-disk file — same
        column shape as get_songs_in_categories. Used by the rotation
        engine when a clock's Song slot has NULL/0 category ("All
        Songs" slot): the candidate pool is the whole library."""
        rows = self._conn().execute(
            "SELECT s.id, s.title, s.artist, s.category_id, "
            "  s.file_path, s.duration_ms, s.year, s.bpm, "
            "  s.energy, s.vocal "
            "FROM songs s "
            "WHERE s.is_enabled = 1 "
            "AND s.file_path IS NOT NULL AND s.file_path != '' "
            "ORDER BY s.id ASC").fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def get_song_last_played_at(self, song_id: int):
        """Return ISO timestamp of the last time this song played
        anywhere, or None if never. Used by RotationAIEngine for the
        overall-recency veto (4hr same-song / 1hr same-artist)."""
        row = self._conn().execute(
            "SELECT MAX(played_at) AS last_at FROM broadcast_log "
            "WHERE song_id = ? AND entry_type = 'song' "
            "AND played_at IS NOT NULL", [int(song_id)]).fetchone()
        if row is None or row["last_at"] is None:
            return None
        return str(row["last_at"])

    def get_last_played_map(self) -> dict:
        """Bulk companion to get_song_last_played_at — ONE query for the
        whole library. Returns {song_id: ISO timestamp of most recent
        play}; songs that have never played are simply absent. Used by
        the Songs Library screen so the Last Played column doesn't need
        ~400 per-row queries."""
        rows = self._conn().execute(
            "SELECT song_id, MAX(played_at) AS last_at "
            "FROM broadcast_log "
            "WHERE song_id IS NOT NULL AND entry_type = 'song' "
            "AND played_at IS NOT NULL "
            "GROUP BY song_id").fetchall()
        return {int(r["song_id"]): str(r["last_at"]) for r in rows}

    # Placeholder "artists" that are really MISSING metadata — 115+
    # bulk-imported songs share "Unknown Artist", so treating them as
    # one artist made a single play rest the whole pool for an hour
    # (rotation audit 2026-07-02). Placeholders are exempt from the
    # same-artist separation everywhere.
    PLACEHOLDER_ARTISTS = frozenset(
        {"", "unknown artist", "unknown", "various", "various artists",
         "va", "n/a", "-"})

    def get_artist_last_played_at(self, artist: str):
        """ISO timestamp of the last time any song by this artist
        played, or None. Used for the 1-hour same-artist rule.

        Matching is normalized with .strip().casefold() on BOTH sides
        (Python-side, since SQLite's NOCASE is ASCII-only) so
        "Arijit Singh", "arijit singh" and "Arijit Singh " count as
        the same artist. Placeholder artists (Unknown Artist etc.) are
        NOT a real artist — always None, so untagged songs never veto
        each other. Stored data is never modified."""
        if not artist:
            return None
        needle = str(artist).strip().casefold()
        if not needle or needle in self.PLACEHOLDER_ARTISTS:
            return None
        rows = self._conn().execute(
            "SELECT s.artist AS artist, MAX(bl.played_at) AS last_at "
            "FROM broadcast_log bl "
            "JOIN songs s ON s.id = bl.song_id "
            "WHERE s.artist IS NOT NULL AND bl.entry_type = 'song' "
            "AND bl.played_at IS NOT NULL "
            "GROUP BY s.artist").fetchall()
        best = None
        for r in rows:
            if str(r["artist"]).strip().casefold() != needle:
                continue
            last_at = str(r["last_at"])
            if best is None or last_at > best:
                best = last_at
        return best

    def get_song_last_played_in_hour(self, song_id: int, hour: int):
        """Return the ISO date (YYYY-MM-DD) of the last time this song
        was played in the given hour-of-day slot. Returns None if the
        song has never been logged in this hour.

        Per operator's D2 = (b) — weekday is NOT a discriminator;
        Monday 10 AM and Friday 10 AM share the same slot history. The
        rotation engine's slot_age computation feeds off this method."""
        h = int(hour)
        if h < 0 or h > 23:
            raise ValueError(f"hour must be 0-23, got {hour!r}")
        try:
            row = self._conn().execute(
                "SELECT MAX(DATE(played_at)) AS last_date "
                "FROM broadcast_log "
                "WHERE song_id = ? "
                "AND entry_type = 'song' "
                "AND played_at IS NOT NULL "
                "AND CAST(strftime('%H', played_at) AS INT) = ?",
                [int(song_id), h]).fetchone()
        except Exception:
            return None
        if row is None or row["last_date"] is None:
            return None
        return str(row["last_date"])

    # ── Rotation Health screen aggregators ─────────────────────────────

    def get_rotation_summary_for_date(self, plan_date: str) -> dict:
        """Aggregate AI rotation decisions for one date, grouped per
        category. Drives the Rotation Health screen (Songs Library
        reports tile).

        Returns:
            {
              "plan":  None | plan envelope row dict,
              "categories": [
                {"category_id", "category_name", "category_color",
                 "rested":        [decision dicts],
                 "promoted_out":  [decision dicts],
                 "promoted_in":   [decision dicts]},
                ...
              ]
            }

        Bucket semantics (per operator's Q6 "both cards" decision):
          • RESTED        = action='rest'    AND source_category_id == category
          • PROMOTED OUT  = action='promote' AND source_category_id == category
          • PROMOTED IN   = action='promote' AND target_category_id == category
        A single promote decision therefore surfaces in BOTH the source
        category's PROMOTED OUT list and the target category's
        PROMOTED IN list — that's intentional (full audit trail).

        Empty categories are still included so the screen's "hide empty
        cards" toggle has data to work with."""
        self._ensure_ai_rotation_tables()
        date_iso = (plan_date or "").strip()

        plan = self.get_ai_rotation_plan(date_iso)
        decisions = self.get_rotation_decisions_for_date(date_iso)

        cats = self._conn().execute(
            "SELECT id, name, color FROM categories "
            "ORDER BY name COLLATE NOCASE ASC").fetchall()

        by_id: dict = {}
        for c in cats:
            by_id[int(c["id"])] = {
                "category_id":    int(c["id"]),
                "category_name":  c["name"] or "",
                "category_color": c["color"] or "#8891b8",
                "rested":         [],
                "promoted_out":   [],
                "promoted_in":    [],
            }

        for d in decisions:
            action = (d.get("action") or "").lower()
            src = d.get("source_category_id")
            tgt = d.get("target_category_id")
            if action == "rest" and src is not None and int(src) in by_id:
                by_id[int(src)]["rested"].append(d)
            elif action == "promote":
                if src is not None and int(src) in by_id:
                    by_id[int(src)]["promoted_out"].append(d)
                if tgt is not None and int(tgt) in by_id:
                    by_id[int(tgt)]["promoted_in"].append(d)

        return {
            "plan":       plan,
            "categories": list(by_id.values()),
        }

    def get_song_recent_plays_count(self, song_id: int,
                                       days: int = 7) -> int:
        """Count of broadcast_log 'song' entries for this song in the
        last `days` calendar days (rolling window from now). Used by
        Rotation Health screen's hover tooltip for the "last 7d plays"
        figure. Returns 0 if the song has never played in the window."""
        try:
            sid = int(song_id)
            d = max(int(days), 1)
        except (TypeError, ValueError):
            return 0
        try:
            row = self._conn().execute(
                "SELECT COUNT(*) AS n FROM broadcast_log "
                "WHERE song_id = ? AND entry_type = 'song' "
                "AND played_at IS NOT NULL "
                f"AND played_at >= datetime('now', '-{d} days')",
                [sid]).fetchone()
        except Exception:
            return 0
        return int(row["n"] or 0) if row else 0

    def get_category_songs_ranked(self, category_id: int) -> list:
        """Every song in this category with its total / week / month /
        last-played stats — ordered by total plays desc, then title.
        Zero-play songs are included so the operator can spot dead
        inventory. Output: list of plain dicts (sqlite3.Row dicts get
        flaky on Py 3.14, so we coerce up-front)."""
        cid = int(category_id)
        rows = self._conn().execute(
            """
            SELECT
              s.id              AS id,
              s.title           AS title,
              s.artist          AS artist,
              s.energy          AS energy,
              s.vocal           AS vocal,
              s.duration_ms     AS duration_ms,
              s.bpm             AS bpm,
              COALESCE(t.total_plays,  0) AS total_plays,
              COALESCE(t.plays_week,   0) AS plays_week,
              COALESCE(t.plays_month,  0) AS plays_month,
              t.last_played_at  AS last_played_at
            FROM   songs s
            LEFT JOIN (
              SELECT
                bl.song_id                                   AS sid,
                COUNT(*)                                     AS total_plays,
                SUM(CASE WHEN date(bl.played_at) >=
                          date('now','localtime','weekday 0','-7 days')
                         THEN 1 ELSE 0 END)                  AS plays_week,
                SUM(CASE WHEN strftime('%Y-%m', bl.played_at) =
                              strftime('%Y-%m', 'now','localtime')
                         THEN 1 ELSE 0 END)                  AS plays_month,
                MAX(bl.played_at)                            AS last_played_at
              FROM broadcast_log bl
              GROUP BY bl.song_id
            ) t ON t.sid = s.id
            WHERE  s.category_id = ?
            ORDER  BY total_plays DESC, s.title COLLATE NOCASE ASC
            """,
            [cid]).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

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
        """Add the premium Playlists-screen columns if missing. Idempotent.

        Scope:
          - kind (manual|imported|smart) + updated_at (Playlists screen S2)
          - color hex, tags csv, cover_path, status, auto_schedule_enabled
            (Create New Playlist S3 — draft state machine + meta fields)"""
        conn = self._conn()
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(playlists)").fetchall()}
        adds = [
            # Screen 2
            ("kind",        "TEXT DEFAULT 'manual'"),
            ("updated_at",  "TEXT DEFAULT (datetime('now'))"),
            # Screen 3 (new playlist creation)
            ("color",                    "TEXT"),                # hex e.g. '#06b6d4'
            ("tags",                     "TEXT"),                # comma-separated
            ("cover_path",               "TEXT"),                # asset path
            ("status",                   "TEXT DEFAULT 'active'"),  # 'draft' | 'active'
            ("auto_schedule_enabled",    "INTEGER DEFAULT 0"),
        ]
        for col, decl in adds:
            if col not in cols:
                conn.execute(f"ALTER TABLE playlists ADD COLUMN {col} {decl}")
        conn.commit()

    # ── Paginated song search (premium Create New Playlist) ─────────────

    def search_songs(
        self,
        query: Optional[str] = None,
        category_id: Optional[int] = None,
        bpm_min: Optional[int] = None,
        bpm_max: Optional[int] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        sort: str = "recent",
        offset: int = 0,
        limit: int = 10,
    ) -> List[sqlite3.Row]:
        """Paginated song search. Used by the Create New Playlist library
        browser; the heavy lifting is done in SQL so we never load the
        whole songs table into Python.

        Filters: text query (title or artist LIKE), category, BPM range,
        year range. Sort: 'recent' (entry_date DESC), 'az' (artist+title),
        'bpm' (bpm DESC). Always paginated — caller passes offset+limit."""
        sql, params = self._songs_filter_sql(
            query, category_id, bpm_min, bpm_max, year_min, year_max)
        sort_clause = {
            "recent": " ORDER BY s.entry_date DESC, s.id DESC",
            "az":     " ORDER BY s.artist, s.title",
            "bpm":    " ORDER BY s.bpm DESC, s.artist",
        }.get(str(sort or "recent").lower(), " ORDER BY s.entry_date DESC")
        sql = (
            "SELECT s.*, c.name AS cat_name, c.color AS cat_color "
            "FROM   songs s "
            "LEFT JOIN categories c ON s.category_id = c.id "
            "WHERE  s.is_enabled = 1"
            + sql
            + sort_clause
            + " LIMIT ? OFFSET ?"
        )
        params = list(params) + [int(limit), int(offset)]
        return self._conn().execute(sql, params).fetchall()

    def count_songs(
        self,
        query: Optional[str] = None,
        category_id: Optional[int] = None,
        bpm_min: Optional[int] = None,
        bpm_max: Optional[int] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
    ) -> int:
        """Match count for the same filter set. Used to drive the
        'Showing X results' label and the page X / Y indicator."""
        sql, params = self._songs_filter_sql(
            query, category_id, bpm_min, bpm_max, year_min, year_max)
        sql = (
            "SELECT COUNT(*) FROM songs s "
            "WHERE s.is_enabled = 1" + sql
        )
        row = self._conn().execute(sql, params).fetchone()
        return int(row[0] or 0) if row else 0

    @staticmethod
    def _songs_filter_sql(
        query, category_id, bpm_min, bpm_max, year_min, year_max,
    ) -> tuple[str, list]:
        """Build the WHERE-tail and params list shared by search_songs +
        count_songs. Returns (sql_fragment_starting_with_AND, params)."""
        sql = ""
        params: list = []
        q = (query or "").strip()
        if q:
            sql += " AND (s.title LIKE ? OR s.artist LIKE ?)"
            params += [f"%{q}%", f"%{q}%"]
        if category_id:
            sql += " AND s.category_id = ?"
            params.append(int(category_id))
        if bpm_min is not None:
            sql += " AND s.bpm >= ?"; params.append(int(bpm_min))
        if bpm_max is not None:
            sql += " AND s.bpm <= ?"; params.append(int(bpm_max))
        if year_min is not None:
            sql += " AND s.year >= ?"; params.append(int(year_min))
        if year_max is not None:
            sql += " AND s.year <= ?"; params.append(int(year_max))
        return sql, params

    # ── Playlist draft state machine (premium Create New Playlist) ──────

    def create_playlist_draft(
        self,
        name: str = "Untitled Playlist",
        kind: str = "manual",
        color: Optional[str] = None,
        tags: Optional[str] = None,
    ) -> int:
        """Insert a playlist row with status='draft'. Returns the new id.
        Used by the Create New Playlist screen on first user interaction
        so auto-save has a target row to write into."""
        self._ensure_playlists_columns()
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO playlists (name, kind, color, tags, status, "
            "is_active, updated_at) VALUES (?, ?, ?, ?, 'draft', 0, "
            "datetime('now'))",
            [str(name or "Untitled Playlist"), str(kind or "manual"),
             color, tags],
        )
        conn.commit()
        return int(cur.lastrowid)

    def update_playlist_draft(
        self,
        playlist_id: int,
        name: Optional[str] = None,
        kind: Optional[str] = None,
        color: Optional[str] = None,
        tags: Optional[str] = None,
        cover_path: Optional[str] = None,
        auto_schedule_enabled: Optional[bool] = None,
    ) -> None:
        """Update mutable meta fields on a draft (or active) playlist.
        Stamps updated_at. Idempotent — only writes columns the caller
        passed (None → unchanged)."""
        self._ensure_playlists_columns()
        conn = self._conn()
        cols_present = {r[1] for r in conn.execute(
            "PRAGMA table_info(playlists)").fetchall()}
        sets: list[str] = []; values: list = []
        candidate = {
            "name":                  name,
            "kind":                  kind,
            "color":                 color,
            "tags":                  tags,
            "cover_path":            cover_path,
            "auto_schedule_enabled":
                None if auto_schedule_enabled is None
                else (1 if auto_schedule_enabled else 0),
        }
        for col, val in candidate.items():
            if val is None or col not in cols_present:
                continue
            sets.append(f"{col} = ?")
            values.append(val)
        if not sets:
            return
        sets.append("updated_at = datetime('now')")
        values.append(int(playlist_id))
        conn.execute(
            f"UPDATE playlists SET {', '.join(sets)} WHERE id = ?", values)
        conn.commit()

    def replace_playlist_songs(
        self, playlist_id: int, song_ids: list[int]
    ) -> None:
        """Atomic DELETE+INSERT replace of a playlist's song list, in
        the order given. position field auto-numbered 1..N."""
        conn = self._conn()
        pid = int(playlist_id)
        try:
            conn.execute("BEGIN")
            conn.execute(
                "DELETE FROM playlist_songs WHERE playlist_id = ?", [pid])
            for i, sid in enumerate(list(song_ids or [])):
                conn.execute(
                    "INSERT INTO playlist_songs (playlist_id, song_id, "
                    "position) VALUES (?, ?, ?)",
                    [pid, int(sid), i + 1])
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def commit_playlist_draft(self, playlist_id: int) -> None:
        """Flip a draft to status='active' + is_active=1. Stamps
        updated_at. Used when the user clicks Save Playlist."""
        self._ensure_playlists_columns()
        conn = self._conn()
        conn.execute(
            "UPDATE playlists SET status = 'active', is_active = 1, "
            "updated_at = datetime('now') WHERE id = ?",
            [int(playlist_id)])
        conn.commit()

    def delete_playlist_draft(self, playlist_id: int) -> bool:
        """Delete a row IF its status is 'draft'. Returns True on delete,
        False if the row was already active (we never touch active
        playlists from this method). Used when the user clicks Cancel."""
        self._ensure_playlists_columns()
        conn = self._conn()
        row = conn.execute(
            "SELECT status FROM playlists WHERE id = ?", [int(playlist_id)]
        ).fetchone()
        if row is None or (row["status"] or "") != "draft":
            return False
        conn.execute(
            "DELETE FROM playlist_songs WHERE playlist_id = ?",
            [int(playlist_id)])
        conn.execute("DELETE FROM playlists WHERE id = ?", [int(playlist_id)])
        conn.commit()
        return True

    def get_playlists_with_stats(self) -> list[dict]:
        """Return all active playlists with computed track count + total
        duration_ms. Excludes status='draft' rows (in-progress playlists
        being built in the Create New Playlist screen).

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
            WHERE  COALESCE(p.status, 'active') != 'draft'
            GROUP  BY p.id
            ORDER  BY (CASE WHEN p.scheduled_day IS NOT NULL AND p.scheduled_day != ''
                            THEN 0 ELSE 1 END),
                      p.updated_at DESC, p.name
            """
        ).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

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
        return [{k: r[k] for k in r.keys()} for r in rows]

    def get_playlist(self, playlist_id: int) -> Optional[sqlite3.Row]:
        """Single playlist row by id, or None. Returns the canonical
        meta + the premium-screen extension cols (kind, color, tags,
        cover_path, status, auto_schedule_enabled). Used by the
        Edit Playlist screen (Figma 248:2) to populate its meta strip."""
        self._ensure_playlists_columns()
        return self._conn().execute(
            "SELECT * FROM playlists WHERE id = ?", [int(playlist_id)]
        ).fetchone()

    def get_playlist_songs(self, playlist_id: int) -> list[dict]:
        """Full song list for a playlist, in playback position order
        (no LIMIT). Used by the Edit Playlist screen — needs every
        track, not just the first N. ``get_playlist_first_tracks`` is
        the preview-card cousin (still valid for that use case)."""
        rows = self._conn().execute(
            """
            SELECT s.id, s.title, s.artist, s.duration_ms,
                   s.file_path, s.category_id, s.year, s.bpm,
                   s.album, ps.position
            FROM   playlist_songs ps
            JOIN   songs s ON ps.song_id = s.id
            WHERE  ps.playlist_id = ?
            ORDER  BY ps.position
            """,
            [int(playlist_id)],
        ).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

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

    def _ensure_sweepers_columns(self) -> None:
        """Add UI-specific sweeper columns if missing + backfill auto_code.
        Idempotent — safe to call on every dialog construction.

        Mirrors _ensure_campaigns_columns. Columns added here surface in the
        Sweeper Editor dialog (Figma 108:2). The base columns (name, category,
        file_path, duration_ms, position, properties, playlister_code,
        is_enabled) live in database/schema.sql and are not touched."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(sweepers)").fetchall()}
        adds = [
            ("auto_code",          "TEXT"),
            ("author",             "TEXT"),
            ("entry_date",         "TEXT"),
            ("comments",           "TEXT"),
            ("bpm",                "TEXT"),
            ("era_year",           "TEXT"),
            ("volume_song_pct",    "INTEGER DEFAULT 60"),
            ("volume_sweeper_pct", "INTEGER DEFAULT 100"),
            ("offset_seconds",     "REAL DEFAULT 0.0"),
            ("fade_seconds",       "REAL DEFAULT 0.5"),
            ("clock_id",           "INTEGER"),
            ("min_gap_minutes",    "INTEGER DEFAULT 15"),
            ("max_per_hour",       "INTEGER DEFAULT 4"),
        ]
        for col, decl in adds:
            if col not in cols:
                conn.execute(f"ALTER TABLE sweepers ADD COLUMN {col} {decl}")
        # Backfill auto_code for rows that don't have one yet. SWP-NNNN
        # sequence starts at 0001 and counts upward by id-order so the legacy
        # KISS Energy / Drop the Beat / Coming Up Next seeds get stable codes.
        nulls = conn.execute(
            "SELECT id FROM sweepers "
            "WHERE auto_code IS NULL OR auto_code = '' "
            "ORDER BY id"
        ).fetchall()
        if nulls:
            mrow = conn.execute(
                "SELECT MAX(CAST(SUBSTR(auto_code, 5) AS INTEGER)) AS m "
                "FROM sweepers "
                "WHERE auto_code IS NOT NULL AND auto_code LIKE 'SWP-%'"
            ).fetchone()
            start = (int(mrow["m"]) if mrow and mrow["m"] else 0) + 1
            for i, r in enumerate(nulls):
                conn.execute(
                    "UPDATE sweepers SET auto_code = ? WHERE id = ?",
                    [f"SWP-{start + i:04d}", r["id"]],
                )
        conn.commit()

    def next_sweeper_auto_code(self) -> str:
        """Compute the next SWP-NNNN code without inserting anything.
        Used to prefill the AUTO CODE pill when the editor dialog opens
        in NEW mode."""
        self._ensure_sweepers_columns()
        row = self._conn().execute(
            "SELECT MAX(CAST(SUBSTR(auto_code, 5) AS INTEGER)) AS m "
            "FROM sweepers "
            "WHERE auto_code IS NOT NULL AND auto_code LIKE 'SWP-%'"
        ).fetchone()
        n = (int(row["m"]) if row and row["m"] else 0) + 1
        return f"SWP-{n:04d}"

    # Field set the editor dialog writes — kept here so tests, the dialog,
    # and any future bulk-importer agree. `id` is excluded; `auto_code` is
    # generated server-side on add.
    SWEEPER_EDITABLE_FIELDS = (
        "name", "category", "file_path", "duration_ms", "position",
        "properties", "playlister_code", "is_enabled",
        "author", "entry_date", "comments", "bpm", "era_year",
        "volume_song_pct", "volume_sweeper_pct",
        "offset_seconds", "fade_seconds",
        "clock_id", "min_gap_minutes", "max_per_hour",
    )

    def add_sweeper(self, data: dict) -> int:
        """Insert a new sweeper. Generates auto_code (SWP-NNNN) so callers
        don't have to. Returns the new id.

        `data` may include any of the editable fields (see
        SWEEPER_EDITABLE_FIELDS). Missing keys take SQL defaults."""
        self._ensure_sweepers_columns()
        conn = self._conn()
        cols: list[str] = ["auto_code"]
        vals: list = [self.next_sweeper_auto_code()]
        for k in self.SWEEPER_EDITABLE_FIELDS:
            if k in data and data[k] is not None:
                cols.append(k)
                v = data[k]
                if k == "is_enabled":
                    v = 1 if v else 0
                vals.append(v)
        placeholders = ", ".join("?" for _ in vals)
        cur = conn.execute(
            f"INSERT INTO sweepers ({', '.join(cols)}) VALUES ({placeholders})",
            vals)
        conn.commit()
        return int(cur.lastrowid)

    def update_sweeper(self, sweeper_id: int, data: dict) -> None:
        """Update a sweeper row. Only keys present in `data` are touched;
        other columns (including auto_code) survive untouched."""
        self._ensure_sweepers_columns()
        sets: list[str] = []
        vals: list = []
        for k in self.SWEEPER_EDITABLE_FIELDS:
            if k in data:
                sets.append(f"{k} = ?")
                v = data[k]
                if k == "is_enabled":
                    v = 1 if v else 0
                vals.append(v)
        if not sets:
            return
        vals.append(int(sweeper_id))
        conn = self._conn()
        conn.execute(
            f"UPDATE sweepers SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()

    def get_station_ids_active(self) -> List[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM jingles "
            "WHERE category = 'Station ID' AND is_enabled = 1"
        ).fetchall()

    # ── Jingle Editor (Figma 106:2) — schema + helpers ────────────────────

    def _ensure_jingles_columns(self) -> None:
        """Add UI-specific jingle columns if missing + backfill auto_code.
        Idempotent — safe to call on every dialog construction.

        Mirrors _ensure_sweepers_columns. The base columns (name,
        category, file_path, duration_ms, properties, playlister_code,
        is_enabled, display_order) live in database/schema.sql and
        are not touched."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(jingles)").fetchall()}
        adds = [
            ("auto_code",       "TEXT"),
            ("author",          "TEXT"),
            ("entry_date",      "TEXT"),
            ("comments",        "TEXT"),
            ("bpm",             "TEXT"),
            ("era_year",        "TEXT"),
            ("clock_id",        "INTEGER"),
            ("min_gap_minutes", "INTEGER DEFAULT 30"),
            ("max_per_hour",    "INTEGER DEFAULT 2"),
        ]
        for col, decl in adds:
            if col not in cols:
                conn.execute(f"ALTER TABLE jingles ADD COLUMN {col} {decl}")
        # Backfill auto_code for legacy rows. JNG-NNNN sequence starts
        # at 0001, ordered by id so the existing dev-DB seed jingles
        # (KISS Main Ident, KISS Shot 01, etc.) get stable codes.
        nulls = conn.execute(
            "SELECT id FROM jingles "
            "WHERE auto_code IS NULL OR auto_code = '' "
            "ORDER BY id"
        ).fetchall()
        if nulls:
            mrow = conn.execute(
                "SELECT MAX(CAST(SUBSTR(auto_code, 5) AS INTEGER)) AS m "
                "FROM jingles "
                "WHERE auto_code IS NOT NULL AND auto_code LIKE 'JNG-%'"
            ).fetchone()
            start = (int(mrow["m"]) if mrow and mrow["m"] else 0) + 1
            for i, r in enumerate(nulls):
                conn.execute(
                    "UPDATE jingles SET auto_code = ? WHERE id = ?",
                    [f"JNG-{start + i:04d}", r["id"]],
                )
        # jingle_linked_spots — many-to-many between jingles + campaigns.
        # Lands here so the editor's LINKED SPOTS card can persist its
        # picks. ON DELETE CASCADE on both sides keeps orphans out.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS jingle_linked_spots ("
            "jingle_id   INTEGER NOT NULL "
            "  REFERENCES jingles(id)   ON DELETE CASCADE, "
            "campaign_id INTEGER NOT NULL "
            "  REFERENCES campaigns(id) ON DELETE CASCADE, "
            "PRIMARY KEY (jingle_id, campaign_id)"
            ")"
        )
        conn.commit()

    def next_jingle_auto_code(self) -> str:
        """Compute the next JNG-NNNN code without inserting anything.
        Used to prefill the AUTO CODE pill when the editor dialog opens
        in NEW mode."""
        self._ensure_jingles_columns()
        row = self._conn().execute(
            "SELECT MAX(CAST(SUBSTR(auto_code, 5) AS INTEGER)) AS m "
            "FROM jingles "
            "WHERE auto_code IS NOT NULL AND auto_code LIKE 'JNG-%'"
        ).fetchone()
        n = (int(row["m"]) if row and row["m"] else 0) + 1
        return f"JNG-{n:04d}"

    # Field set the editor dialog writes — kept here so tests, the
    # dialog, and any future bulk-importer agree. `id` is excluded;
    # `auto_code` is generated server-side on add.
    JINGLE_EDITABLE_FIELDS = (
        "name", "category", "file_path", "duration_ms",
        "properties", "playlister_code", "is_enabled",
        "author", "entry_date", "comments", "bpm", "era_year",
        "clock_id", "min_gap_minutes", "max_per_hour",
    )

    def add_jingle(self, data: dict) -> int:
        """Insert a new jingle. Generates auto_code (JNG-NNNN) so
        callers don't have to. Returns the new id."""
        self._ensure_jingles_columns()
        conn = self._conn()
        cols: list[str] = ["auto_code"]
        vals: list = [self.next_jingle_auto_code()]
        for k in self.JINGLE_EDITABLE_FIELDS:
            if k in data and data[k] is not None:
                cols.append(k)
                v = data[k]
                if k == "is_enabled":
                    v = 1 if v else 0
                vals.append(v)
        placeholders = ", ".join("?" for _ in vals)
        cur = conn.execute(
            f"INSERT INTO jingles ({', '.join(cols)}) "
            f"VALUES ({placeholders})", vals)
        conn.commit()
        return int(cur.lastrowid)

    def update_jingle(self, jingle_id: int, data: dict) -> None:
        """Partial update — only keys present in `data` are touched.
        Other columns (including auto_code) survive untouched."""
        self._ensure_jingles_columns()
        sets: list[str] = []
        vals: list = []
        for k in self.JINGLE_EDITABLE_FIELDS:
            if k in data:
                sets.append(f"{k} = ?")
                v = data[k]
                if k == "is_enabled":
                    v = 1 if v else 0
                vals.append(v)
        if not sets:
            return
        vals.append(int(jingle_id))
        conn = self._conn()
        conn.execute(
            f"UPDATE jingles SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()

    def get_jingle_linked_spots(self, jingle_id: int) -> List[sqlite3.Row]:
        """Resolve the campaigns linked to a jingle. Returns rows shaped
        for the LINKED SPOTS card: campaign id + name + auto_code."""
        self._ensure_jingles_columns()
        return self._conn().execute(
            "SELECT c.id AS campaign_id, c.name, c.auto_code "
            "FROM jingle_linked_spots jl "
            "JOIN campaigns c ON c.id = jl.campaign_id "
            "WHERE jl.jingle_id = ? "
            "ORDER BY c.name COLLATE NOCASE",
            [int(jingle_id)],
        ).fetchall()

    def set_jingle_linked_spots(self, jingle_id: int,
                                campaign_ids: list[int]) -> None:
        """Replace the linked-spots set for a jingle in one transaction.
        Empty `campaign_ids` clears the row's linked spots."""
        self._ensure_jingles_columns()
        conn = self._conn()
        conn.execute("DELETE FROM jingle_linked_spots WHERE jingle_id = ?",
                     [int(jingle_id)])
        for cid in campaign_ids:
            conn.execute(
                "INSERT OR IGNORE INTO jingle_linked_spots "
                "(jingle_id, campaign_id) VALUES (?, ?)",
                [int(jingle_id), int(cid)],
            )
        conn.commit()

    # ── Stitcher config (Figma 46:481) ────────────────────────────────────

    # Single-row config table. Editable fields kept as a tuple so the
    # screen + tests + future bulk migration agree on shape. `id` and
    # `updated_at` are excluded — the row is always id=1, updated_at
    # is bumped server-side.
    STITCHER_EDITABLE_FIELDS = (
        "opening_audio", "separator_audio",
        "closing_audio", "fallback_audio",
        "hook_duration_seconds", "min_hooks_required", "max_hooks",
        "module_enabled",
        "trigger_before_every_break", "trigger_every_n_songs",
        "trigger_every_n_songs_count", "trigger_top_of_hour",
        "trigger_mode",
        "time_window_minutes", "strict_mode",
    )

    def get_stitcher_config(self) -> dict:
        """Return the single-row stitcher_config as a dict. Falls back
        to a defaults dict if the row is missing (greenfield install
        where the table exists but no row was seeded — defensive)."""
        try:
            row = self._conn().execute(
                "SELECT * FROM stitcher_config WHERE id = 1"
            ).fetchone()
        except Exception:
            row = None
        if row is None:
            # Defensive defaults — same shape as the schema column
            # defaults so the editor screen always has something to
            # render even before the first save.
            return {
                "id": 1,
                "opening_audio": "", "separator_audio": "",
                "closing_audio": "", "fallback_audio": "",
                "hook_duration_seconds": 8,
                "min_hooks_required": 2, "max_hooks": 4,
                "module_enabled": 1,
                "trigger_before_every_break": 1,
                "trigger_every_n_songs": 0,
                "trigger_every_n_songs_count": 4,
                "trigger_top_of_hour": 0,
                "trigger_mode": "break_reference",
                "time_window_minutes": 25,
                "strict_mode": 0,
            }
        return {k: row[k] for k in row.keys()}

    def update_stitcher_config(self, data: dict) -> None:
        """Partial update — only keys present in ``data`` (and in
        STITCHER_EDITABLE_FIELDS) are written. Boolean-ish fields are
        coerced to 0/1 so the schema's INTEGER columns stay clean."""
        sets: list[str] = []
        vals: list = []
        bool_fields = {
            "module_enabled",
            "trigger_before_every_break",
            "trigger_every_n_songs",
            "trigger_top_of_hour",
            "strict_mode",
        }
        for k in self.STITCHER_EDITABLE_FIELDS:
            if k in data:
                sets.append(f"{k} = ?")
                v = data[k]
                if k in bool_fields:
                    v = 1 if v else 0
                vals.append(v)
        if not sets:
            return
        sets.append("updated_at = CURRENT_TIMESTAMP")
        conn = self._conn()
        conn.execute(
            f"UPDATE stitcher_config SET {', '.join(sets)} WHERE id = 1",
            vals)
        # If the UPDATE matched zero rows, the row was missing —
        # insert it so the editor's first save sticks.
        if conn.total_changes == 0:
            cols = list(data.keys()) + ["id"]
            placeholders = ", ".join("?" for _ in cols)
            row_vals = []
            for k in cols:
                if k == "id":
                    row_vals.append(1)
                else:
                    v = data[k]
                    if k in bool_fields:
                        v = 1 if v else 0
                    row_vals.append(v)
            conn.execute(
                f"INSERT OR REPLACE INTO stitcher_config "
                f"({', '.join(cols)}) VALUES ({placeholders})", row_vals)
        conn.commit()

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
        """Delete a clock and ALL its dependent rows across every
        table that references ``clocks(id)``. Manual cascade because
        the live DB (created from an earlier schema version) doesn't
        actually enforce the ``ON DELETE CASCADE`` declared in the
        current schema.sql — silent FK failures used to make the
        Delete Selected Clock button look broken in Main Auto
        Schedule (2026-05-16 bug). All operations in a single
        transaction so a mid-flight failure rolls back cleanly.

        Cleanup chain:
          • ``clock_slots``           — DELETE (slots are owned by
                                        the clock; no orphans allowed)
          • ``auto_schedule``         — DELETE (grid cells using
                                        this clock; gone with the clock)
          • ``ai_rotation_decisions`` — DELETE (per-day decisions
                                        tied to this clock; gone)
          • ``broadcast_log``         — NULL out clock_id only;
                                        preserves the historical
                                        record of what actually
                                        played, just loses the
                                        clock association
          • ``force_clocks``          — NULL out clock_id; preserves
                                        the override row's date

        Refuses to drop the very last clock so the editor always
        has something to load (raises ``ValueError``)."""
        conn = self._conn()
        total = conn.execute(
            "SELECT COUNT(*) FROM clocks WHERE is_active = 1"
        ).fetchone()[0]
        if int(total or 0) <= 1:
            raise ValueError("cannot delete the last remaining clock")
        cid = int(clock_id)
        try:
            conn.execute("BEGIN")
            # 1. Owned children — delete outright
            conn.execute(
                "DELETE FROM clock_slots WHERE clock_id = ?", [cid])
            conn.execute(
                "DELETE FROM auto_schedule WHERE clock_id = ?", [cid])
            # ai_rotation_decisions may not exist on very old DBs;
            # try/except keeps backwards compatibility.
            try:
                conn.execute(
                    "DELETE FROM ai_rotation_decisions "
                    "WHERE clock_id = ?", [cid])
            except Exception:
                pass
            # 2. Historical references — NULL out, preserve audit
            conn.execute(
                "UPDATE broadcast_log SET clock_id = NULL "
                "WHERE clock_id = ?", [cid])
            try:
                conn.execute(
                    "UPDATE force_clocks SET clock_id = NULL "
                    "WHERE clock_id = ?", [cid])
            except Exception:
                pass
            # 3. Finally drop the clock itself
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

    # ── Category Auto-Grid (dayparts) — 2026-07-02 ──────────────────────
    # Operator tags a category with air-time hours; core/auto_grid_builder
    # synthesises permanent AUTO clocks + fills empty grid cells daily.

    def _ensure_auto_grid_tables(self) -> None:
        conn = self._conn()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS category_dayparts ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " category_id INTEGER NOT NULL,"
            " day_of_week INTEGER,"          # NULL = every day (0=Mon..6=Sun)
            " hour_start INTEGER NOT NULL,"
            " hour_end INTEGER NOT NULL)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS auto_grid_clocks ("
            " cat_key TEXT PRIMARY KEY,"     # e.g. '1' or '1+4'
            " clock_id INTEGER NOT NULL)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS auto_grid_cells ("
            " day_of_week INTEGER NOT NULL,"
            " hour INTEGER NOT NULL,"
            " clock_id INTEGER NOT NULL,"
            " PRIMARY KEY (day_of_week, hour))")
        conn.commit()

    def set_category_dayparts(self, category_id: int,
                              parts: list) -> None:
        """Replace this category's air-time tags. `parts` =
        [(day_of_week_or_None, hour_start, hour_end), ...]. Exact-id
        DELETE per the destructive-op protocol."""
        self._ensure_auto_grid_tables()
        conn = self._conn()
        cid = int(category_id)
        conn.execute("BEGIN")
        conn.execute(
            "DELETE FROM category_dayparts WHERE category_id = ?", [cid])
        for dow, h1, h2 in parts or []:
            conn.execute(
                "INSERT INTO category_dayparts "
                "(category_id, day_of_week, hour_start, hour_end) "
                "VALUES (?, ?, ?, ?)",
                [cid, None if dow is None else int(dow),
                 int(h1), int(h2)])
        conn.commit()

    def get_category_dayparts(self, category_id: int) -> list:
        self._ensure_auto_grid_tables()
        rows = self._conn().execute(
            "SELECT day_of_week, hour_start, hour_end "
            "FROM category_dayparts WHERE category_id = ? "
            "ORDER BY hour_start", [int(category_id)]).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def get_all_category_dayparts(self) -> list:
        """Every daypart tag joined with its category — the builder's
        input. Disabled/deleted categories drop out naturally."""
        self._ensure_auto_grid_tables()
        rows = self._conn().execute(
            "SELECT dp.category_id, dp.day_of_week, dp.hour_start, "
            "dp.hour_end, c.name AS category_name "
            "FROM category_dayparts dp "
            "JOIN categories c ON c.id = dp.category_id "
            "ORDER BY dp.hour_start").fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def get_auto_grid_clock_id(self, cat_key: str):
        self._ensure_auto_grid_tables()
        row = self._conn().execute(
            "SELECT clock_id FROM auto_grid_clocks WHERE cat_key = ?",
            [str(cat_key)]).fetchone()
        return int(row[0]) if row else None

    def set_auto_grid_clock_id(self, cat_key: str, clock_id: int) -> None:
        self._ensure_auto_grid_tables()
        conn = self._conn()
        conn.execute(
            "INSERT INTO auto_grid_clocks (cat_key, clock_id) "
            "VALUES (?, ?) ON CONFLICT(cat_key) "
            "DO UPDATE SET clock_id = excluded.clock_id",
            [str(cat_key), int(clock_id)])
        conn.commit()

    def get_auto_grid_cell_records(self) -> dict:
        """(day_of_week, hour) -> clock_id for cells THIS feature
        placed. Anything not in here is operator-manual and sacred."""
        self._ensure_auto_grid_tables()
        rows = self._conn().execute(
            "SELECT day_of_week, hour, clock_id "
            "FROM auto_grid_cells").fetchall()
        return {(int(r[0]), int(r[1])): int(r[2]) for r in rows}

    def record_auto_grid_cell(self, day_of_week: int, hour: int,
                              clock_id: int) -> None:
        self._ensure_auto_grid_tables()
        conn = self._conn()
        conn.execute(
            "INSERT INTO auto_grid_cells (day_of_week, hour, clock_id) "
            "VALUES (?, ?, ?) ON CONFLICT(day_of_week, hour) "
            "DO UPDATE SET clock_id = excluded.clock_id",
            [int(day_of_week), int(hour), int(clock_id)])
        conn.commit()

    def remove_auto_grid_cell_record(self, day_of_week: int,
                                     hour: int) -> None:
        self._ensure_auto_grid_tables()
        conn = self._conn()
        conn.execute(
            "DELETE FROM auto_grid_cells "
            "WHERE day_of_week = ? AND hour = ?",
            [int(day_of_week), int(hour)])
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
        d = {k: row[k] for k in row.keys()}
        d["spot_files"] = [{k: r[k] for k in r.keys()} for r in self.get_spot_files(campaign_id)]
        d["schedule"]   = [{k: r[k] for k in r.keys()} for r in self.get_break_schedule(campaign_id)]
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
        # Stitcher: a single-row config table. "Active modules" =
        # count of non-empty audio paths (opening / separator /
        # closing / fallback) when module_enabled=1. 0 when the
        # module is disabled or the row is missing — keeps the
        # ControlPanel card honest about whether anything will
        # actually fire.
        try:
            row = conn.execute(
                "SELECT module_enabled, opening_audio, separator_audio, "
                "closing_audio, fallback_audio FROM stitcher_config "
                "WHERE id = 1"
            ).fetchone()
            if row and int(row[0] or 0):
                s["stitcher_active"] = sum(
                    1 for p in (row[1], row[2], row[3], row[4])
                    if (p or "").strip())
                s["stitcher_enabled"] = 1
            else:
                s["stitcher_active"] = 0
                s["stitcher_enabled"] = 0
        except Exception:
            s["stitcher_active"] = 0
            s["stitcher_enabled"] = 0
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
        Returns the number of songs that were reassigned.

        Rotation AI cleanup: ai_rotation_decisions.source/target_category_id
        reference categories(id) with NO ACTION (foreign_keys=ON) → those
        decision rows must be deleted first or the category delete aborts.
        sister_group_members declares ON DELETE CASCADE, but we delete
        explicitly too so the cleanup doesn't depend on FK enforcement."""
        cid = int(category_id)
        self._ensure_ai_rotation_tables()
        conn = self._conn()
        # Reassign first
        cur = conn.execute(
            "UPDATE songs SET category_id = ? WHERE category_id = ?",
            [reassign_to, cid],
        )
        moved = cur.rowcount or 0
        # Rotation AI references (NO-ACTION FKs) — must go before the
        # categories row
        conn.execute(
            "DELETE FROM ai_rotation_decisions "
            "WHERE source_category_id = ? OR target_category_id = ?",
            [cid, cid],
        )
        conn.execute(
            "DELETE FROM sister_group_members WHERE category_id = ?",
            [cid],
        )
        conn.execute("DELETE FROM categories WHERE id = ?", [cid])
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
