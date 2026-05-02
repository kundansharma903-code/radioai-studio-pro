"""RadioAI Studio Pro — Database Manager (SQLite)"""

import sqlite3
import os
import threading
from contextlib import contextmanager


class DatabaseManager:
    """Thread-safe SQLite database manager for RadioAI Studio Pro."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path=None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, db_path=None):
        if self._initialized:
            return
        if db_path is None:
            app_data = os.path.join(os.environ.get("LOCALAPPDATA", "."), "RadioAI")
            os.makedirs(app_data, exist_ok=True)
            db_path = os.path.join(app_data, "radioai.db")
        self.db_path = db_path
        self._local = threading.local()
        self._initialize_database()
        self._initialized = True

    def _get_connection(self):
        if not hasattr(self._local, "connection") or self._local.connection is None:
            self._local.connection = sqlite3.connect(self.db_path)
            self._local.connection.row_factory = sqlite3.Row
            self._local.connection.execute("PRAGMA journal_mode=WAL")
            self._local.connection.execute("PRAGMA foreign_keys=ON")
        return self._local.connection

    @contextmanager
    def connection(self):
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    @contextmanager
    def cursor(self):
        with self.connection() as conn:
            cur = conn.cursor()
            try:
                yield cur
            finally:
                cur.close()

    def execute(self, sql, params=None):
        with self.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()

    def execute_insert(self, sql, params=None):
        with self.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.lastrowid

    def execute_many(self, sql, params_list):
        with self.cursor() as cur:
            cur.executemany(sql, params_list)

    def _initialize_database(self):
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            cur.executescript(SCHEMA_SQL)
            conn.commit()
            self._insert_defaults(cur)
            self._run_stitcher_migrations(cur)
            conn.commit()
        finally:
            cur.close()

    def _run_stitcher_migrations(self, cur):
        """Stitcher Step A: dedicated config table + per-song hook
        columns. Idempotent — safe to run on every startup."""
        # New stitcher_config table
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS stitcher_config (
                id INTEGER PRIMARY KEY DEFAULT 1,
                opening_audio TEXT DEFAULT '',
                separator_audio TEXT DEFAULT '',
                closing_audio TEXT DEFAULT '',
                fallback_audio TEXT DEFAULT '',
                hook_duration_seconds INTEGER DEFAULT 8,
                min_hooks_required INTEGER DEFAULT 2,
                max_hooks INTEGER DEFAULT 4,
                module_enabled INTEGER DEFAULT 1,
                trigger_before_every_break INTEGER DEFAULT 1,
                trigger_every_n_songs INTEGER DEFAULT 0,
                trigger_every_n_songs_count INTEGER DEFAULT 4,
                trigger_top_of_hour INTEGER DEFAULT 0,
                trigger_mode TEXT DEFAULT 'break_reference',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute("INSERT OR IGNORE INTO stitcher_config (id) VALUES (1)")

        # AI Daily Scheduler tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_daily_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_date TEXT NOT NULL,
                hour INTEGER NOT NULL,
                position INTEGER NOT NULL,
                song_id INTEGER,
                slot_type TEXT DEFAULT 'song',
                generated_at TEXT DEFAULT (datetime('now','localtime')),
                status TEXT DEFAULT 'scheduled'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_schedule_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_date TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT 'pending',
                generated_at TEXT DEFAULT (datetime('now','localtime')),
                warnings_count INTEGER DEFAULT 0,
                songs_scheduled INTEGER DEFAULT 0,
                error_message TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_schedule_warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_date TEXT NOT NULL,
                warning_type TEXT,
                category_name TEXT,
                message TEXT,
                severity TEXT DEFAULT 'info'
            )
        """)

        # AI Magic logging tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_run_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT NOT NULL,
                step_time TEXT,
                step_label TEXT,
                step_detail TEXT,
                status TEXT DEFAULT 'done'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT NOT NULL,
                decision_time TEXT,
                decision_type TEXT,
                song_id INTEGER,
                message TEXT
            )
        """)

        # Scheduling rules (stored in settings table)
        sched_defaults = [
            ("same_artist_hours", "2"),
            ("same_song_days", "7"),
            ("same_category_mins", "30"),
            ("artist_title_sep_hours", "1"),
            ("vocal_type", "Alternate"),
            ("selection_randomness", "0"),
            ("scheduling_auto_mode", "SOHO"),
        ]
        for key, val in sched_defaults:
            try:
                existing = cur.execute(
                    "SELECT value FROM settings WHERE key = ?", (key,)
                ).fetchone()
                if not existing:
                    cur.execute(
                        "INSERT INTO settings (key, value) VALUES (?, ?)", (key, val)
                    )
            except Exception:
                pass

        # Jazler-spec columns added later (idempotent ALTER)
        for col in (
            "ALTER TABLE stitcher_config ADD COLUMN time_window_minutes INTEGER DEFAULT 25",
            "ALTER TABLE stitcher_config ADD COLUMN strict_mode INTEGER DEFAULT 0",
        ):
            try:
                cur.execute(col)
            except Exception:
                pass

        # Add per-song hook columns (REAL seconds + has_hook flag) and
        # the cue editor's REAL-seconds intro/outro/mix columns. These
        # live alongside the existing INT-ms columns so older code paths
        # keep working unchanged.
        for col_sql in (
            "ALTER TABLE songs ADD COLUMN hook_in_time REAL DEFAULT 60.0",
            "ALTER TABLE songs ADD COLUMN hook_out_time REAL DEFAULT 68.0",
            "ALTER TABLE songs ADD COLUMN has_hook INTEGER DEFAULT 1",
            "ALTER TABLE songs ADD COLUMN intro_time REAL DEFAULT 0.0",
            "ALTER TABLE songs ADD COLUMN outro_time REAL DEFAULT 0.0",
            "ALTER TABLE songs ADD COLUMN mix_point REAL DEFAULT 0.0",
            "ALTER TABLE songs ADD COLUMN intro_end_ms INTEGER DEFAULT 0",
            "ALTER TABLE clock_slots ADD COLUMN sweeper_position TEXT DEFAULT 'START_OF_SONG'",
            "ALTER TABLE clock_slots ADD COLUMN item_id INTEGER DEFAULT 0",
        ):
            try:
                cur.execute(col_sql)
            except Exception:
                pass

        # Backfill: if rows have NULL or 0 has_hook, give them sane
        # defaults so the Stitcher preview works on a fresh DB.
        try:
            cur.execute(
                """
                UPDATE songs SET
                  hook_in_time = COALESCE(NULLIF(hook_in_time, 0), 60.0),
                  hook_out_time = COALESCE(NULLIF(hook_out_time, 0), 68.0),
                  has_hook = 1
                WHERE has_hook IS NULL OR has_hook = 0
                """
            )
        except Exception:
            pass

    def _insert_defaults(self, cur):
        cur.execute("SELECT COUNT(*) FROM categories")
        if cur.fetchone()[0] == 0:
            defaults = [
                ("Hot Currents", "#8B5CF6", "Current hits in heavy rotation", "Rotate after 1 play", 120, 1),
                ("Currents", "#A78BFA", "Current hits in normal rotation", "Rotate after 2 plays", 180, 2),
                ("Recurrents", "#6D28D9", "Recent hits still popular", "Rotate after 3 plays", 240, 3),
                ("Gold", "#F59E0B", "Classic hits", "Rotate after 5 plays", 360, 4),
                ("Power Gold", "#F43F5E", "Top classic hits", "Rotate after 3 plays", 240, 5),
                ("Specialty", "#06B6D4", "Themed/specialty tracks", "No rotation", 480, 6),
            ]
            cur.executemany(
                "INSERT INTO categories (name, color, description, auto_rotate, separation_min, display_order) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                defaults,
            )

        cur.execute("SELECT COUNT(*) FROM settings")
        if cur.fetchone()[0] == 0:
            default_settings = [
                ("station_name", "KISS FM 91.5"),
                ("station_location", "Jaipur, Rajasthan"),
                ("auto_mode", "1"),
                ("crossfade_ms", "3000"),
                ("default_separation_min", "120"),
                ("ai_enabled", "1"),
                ("rds_enabled", "0"),
                # Studio settings defaults
                ("crossfade_duration", "3"),
                ("fade_out_start", "6"),
                ("fade_curve_type", "Logarithmic"),
                ("load_next_song", "At mix point of current"),
                ("preload_buffer", "10 seconds ahead"),
                ("automix_trigger", "At song MIX POINT marker"),
                ("fallback_action", "Skip and play next"),
                ("missing_file_alert", "true"),
                ("autocue_threshold", "-40"),
                ("autocue_scan_mode", "Scan first 10s + last 10s"),
                ("master_volume", "85"),
                ("cue_volume", "70"),
                ("jingle_volume", "90"),
                ("mic_volume", "75"),
                ("vu_decay_speed", "Normal (300ms decay)"),
                ("peak_hold_duration", "2 seconds"),
                ("clip_indicator", "true"),
                ("cue_split_mode", "Left: On-Air + Right: Cue"),
                ("show_crossfade_preview", "true"),
                ("flash_mix_point", "true"),
                ("audio_buffer_size", "256"),
                ("sample_rate", "44100"),
                ("bit_depth", "32-bit float"),
                ("audio_engine", "WASAPI"),
            ]
            cur.executemany("INSERT INTO settings (key, value) VALUES (?, ?)", default_settings)

        # Seed demo songs
        cur.execute("SELECT COUNT(*) FROM songs")
        if cur.fetchone()[0] == 0:
            demo_songs = [
                ("Amy Winehouse", "You Know Im No Good", "Back to Black", 1, 2007, 125, "High", 225000, 1, 0),
                ("Bangles", "Walk Like An Egyptian", "Different Light", 4, 1986, 104, "Medium", 238000, 1, 0),
                ("Billie Eilish", "Bury a Friend", "When We All Fall Asleep", 1, 2019, 120, "High", 206000, 1, 0),
                ("Britney Spears", "You Drive Me Crazy", "Baby One More Time", 5, 1999, 112, "High", 194000, 1, 0),
                ("Camila Cabello ft. Young T...", "Havana", "Camila", 1, 2018, 105, "Medium", 217000, 1, 0),
                ("Coldplay", "Clocks", "A Rush of Blood to the Head", 4, 2002, 132, "Medium", 307000, 1, 1),
                ("Drake", "God's Plan", "Scorpion", 1, 2018, 77, "High", 198000, 1, 0),
                ("Eagle Eye Cherry", "Save Tonight", "Desireless", 4, 1997, 108, "Medium", 236000, 1, 0),
                ("Fairground Attraction", "Perfect", "First of a Million Kisses", 3, 1988, 96, "Low", 222000, 1, 0),
                ("Harry Styles", "As It Was", "Harry's House", 1, 2022, 174, "High", 157000, 1, 0),
                ("House Of Pain", "Jump Around", "House of Pain", 4, 1992, 107, "High", 212000, 1, 0),
                ("James Brown", "I Feel Good", "I Got You", 3, 1965, 136, "High", 166000, 1, 0),
                ("Jax Jones, Bebe Rexha", "Harder", "Snacks", 1, 2019, 122, "High", 194000, 1, 0),
                ("Kylie Minogue", "Step Back In Time", "Rhythm of Love", 4, 1990, 118, "Medium", 226000, 1, 0),
                ("Planet Funk", "Chase The Sun", "Non Zero Sumness", 4, 2001, 130, "Medium", 254000, 1, 0),
                ("Pm Dawn", "Gotta Be Movin'", "Of the Heart", 3, 1991, 98, "Low", 262000, 1, 1),
                ("Regard, Years & Years", "Hallucination", "Single", 1, 2021, 124, "High", 186000, 1, 0),
                ("REM", "Losing My Religion", "Out of Time", 4, 1991, 126, "Medium", 268000, 1, 0),
                ("Rick Astley", "Never Gonna Give You Up", "Whenever You Need Somebody", 4, 1987, 113, "Medium", 213000, 1, 0),
                ("Dua Lipa", "Levitating", "Future Nostalgia", 1, 2020, 103, "High", 203000, 1, 0),
                ("The Weeknd", "Blinding Lights", "After Hours", 1, 2020, 171, "High", 200000, 1, 0),
                ("Adele", "Rolling in the Deep", "21", 2, 2011, 105, "High", 228000, 1, 0),
                ("Bruno Mars", "Uptown Funk", "Unorthodox Jukebox", 1, 2014, 115, "High", 270000, 1, 0),
                ("Ed Sheeran", "Shape of You", "Divide", 2, 2017, 96, "Medium", 234000, 1, 0),
                ("Taylor Swift", "Shake It Off", "1989", 2, 2014, 160, "High", 219000, 1, 0),
            ]
            cur.executemany(
                "INSERT INTO songs (artist, title, album, category_id, year, bpm, energy, duration_ms, is_enabled, is_frozen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                demo_songs,
            )

        # Seed demo campaigns
        cur.execute("SELECT COUNT(*) FROM campaigns")
        if cur.fetchone()[0] == 0:
            demo_campaigns = [
                ("FreshBurst Cola — Summer", "Summer 2026 campaign", "Commercials", "High", "Weekly", "In Rotation", "2026-04-01", "2026-06-30", 3, 1),
                ("NovaTech Mobile — Launch", "New phone launch", "Commercials", "High", "Weekly", "Sequential", "2026-03-15", "2026-06-15", 4, 1),
                ("City FM Station ID", "Station identification", "Station ID", "Always", "Always On", "In Rotation", "2026-01-01", "Never", 12, 1),
                ("Traffic Update Sting", "Traffic jingles", "News Break", "Always", "Daily", "In Rotation", "2026-01-01", "Never", 8, 1),
                ("Bank of Stars Promo", "Banking promotion", "Commercials", "Medium", "Weekly", "In Rotation", "2026-01-01", "Never", 2, 1),
                ("Sunrise Mall Weekend", "Weekend mall ads", "Commercials", "Medium", "Daily", "In Rotation", "2026-04-11", "2026-04-13", 2, 1),
                ("PureLife Water", "Water brand ads", "Commercials", "Low", "Weekly", "In Rotation", "2026-03-01", "Never", 1, 1),
                ("Weather Flash", "Weather sponsors", "News Break", "Always", "Daily", "Sequential", "2026-01-01", "Never", 6, 1),
                ("Morning Drive Sponsor", "Drive-time sponsor", "Sponsor", "High", "Daily", "In Rotation", "2026-01-01", "2026-04-30", 5, 1),
                ("Evening News Intro", "News intro", "Station ID", "Always", "Daily", "In Rotation", "2026-01-01", "Never", 2, 1),
            ]
            cur.executemany(
                "INSERT INTO campaigns (name, description, category, priority, programming_mode, playback_order, start_date, end_date, contracted_plays_per_day, is_active) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                demo_campaigns,
            )
            # Seed spot files for first campaign
            demo_spots = [
                (1, "FreshBurst_30sec.mp3", "C:\\RadioAI\\Spots\\FreshBurst_30sec.mp3", 30000, 1, 0),
                (1, "FreshBurst_15sec.mp3", "C:\\RadioAI\\Spots\\FreshBurst_15sec.mp3", 15000, 1, 1),
                (1, "FreshBurst_Jingle.mp3", "C:\\RadioAI\\Spots\\FreshBurst_Jingle.mp3", 10000, 1, 2),
                (2, "NovaTech_15s.mp3", "C:\\RadioAI\\Spots\\NovaTech_15s.mp3", 15000, 1, 0),
                (2, "NovaTech_30s.mp3", "C:\\RadioAI\\Spots\\NovaTech_30s.mp3", 30000, 1, 1),
            ]
            cur.executemany(
                "INSERT INTO spot_files (campaign_id, filename, file_path, duration_ms, is_active, display_order) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                demo_spots,
            )

        # Seed default users
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            import hashlib
            users = [
                ("kavish", "DJ Kavish", "kavish@kissfm.in", "Administrator",
                 hashlib.sha256(b"admin123").hexdigest()),
                ("vas", "DJ Vas", "", "DJ",
                 hashlib.sha256(b"dj123").hexdigest()),
                ("night", "Night Jockey", "", "DJ",
                 hashlib.sha256(b"dj123").hexdigest()),
            ]
            cur.executemany(
                "INSERT INTO users (username, display_name, email, role, password_hash) VALUES (?,?,?,?,?)",
                users,
            )

    def get_setting(self, key, default=None):
        rows = self.execute("SELECT value FROM settings WHERE key = ?", (key,))
        return rows[0][0] if rows else default

    def set_setting(self, key, value):
        self.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value)),
        )

    def get_stats(self):
        stats = {}
        for table in ("songs", "campaigns", "jingles", "sweepers", "categories"):
            rows = self.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = rows[0][0]
        rows = self.execute(
            "SELECT COUNT(*) FROM songs WHERE is_enabled = 1"
        )
        stats["songs_enabled"] = rows[0][0]
        rows = self.execute(
            "SELECT COUNT(*) FROM campaigns WHERE is_active = 1"
        )
        stats["campaigns_active"] = rows[0][0]
        return stats

    # ── Stitcher Step A: dedicated config + per-song hook helpers ───────

    def get_stitcher_config_v2(self):
        """Return the row from the new `stitcher_config` table as a dict."""
        with self.cursor() as cur:
            cur.execute("SELECT * FROM stitcher_config WHERE id = 1")
            row = cur.fetchone()
            if not row:
                return {}
            cols = [c[0] for c in cur.description]
            return dict(zip(cols, row))

    def save_stitcher_config_v2(self, data):
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE stitcher_config SET
                    opening_audio = ?,
                    separator_audio = ?,
                    closing_audio = ?,
                    fallback_audio = ?,
                    hook_duration_seconds = ?,
                    min_hooks_required = ?,
                    max_hooks = ?,
                    module_enabled = ?,
                    trigger_before_every_break = ?,
                    trigger_every_n_songs = ?,
                    trigger_every_n_songs_count = ?,
                    trigger_top_of_hour = ?,
                    trigger_mode = ?,
                    time_window_minutes = ?,
                    strict_mode = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """,
                (
                    data.get("opening_audio", "") or "",
                    data.get("separator_audio", "") or "",
                    data.get("closing_audio", "") or "",
                    data.get("fallback_audio", "") or "",
                    int(data.get("hook_duration_seconds", 8) or 8),
                    int(data.get("min_hooks_required", 2) or 2),
                    int(data.get("max_hooks", 4) or 4),
                    int(data.get("module_enabled", 1) or 0),
                    int(data.get("trigger_before_every_break", 1) or 0),
                    int(data.get("trigger_every_n_songs", 0) or 0),
                    int(data.get("trigger_every_n_songs_count", 4) or 4),
                    int(data.get("trigger_top_of_hour", 0) or 0),
                    data.get("trigger_mode", "break_reference") or "break_reference",
                    int(data.get("time_window_minutes", 25) or 25),
                    int(data.get("strict_mode", 0) or 0),
                ),
            )
        return True

    def get_songs_for_stitcher(self):
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, artist, file_path,
                       hook_in_time, hook_out_time, has_hook
                FROM songs
                WHERE is_enabled = 1
                ORDER BY artist, title
                """
            )
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def save_song_hook(self, song_id, hook_in, hook_out):
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE songs SET
                    hook_in_time = ?,
                    hook_out_time = ?,
                    has_hook = 1
                WHERE id = ?
                """,
                (float(hook_in), float(hook_out), int(song_id)),
            )
        return True

    def remove_song_hook(self, song_id):
        with self.cursor() as cur:
            cur.execute("UPDATE songs SET has_hook = 0 WHERE id = ?", (int(song_id),))
        return True

    # ── Audio Cue Editor ────────────────────────────────────────────────

    def get_song_cue_data(self, song_id):
        """Return the full song row as a dict for the Cue Editor."""
        with self.cursor() as cur:
            cur.execute("SELECT * FROM songs WHERE id = ?", (int(song_id),))
            row = cur.fetchone()
            if not row:
                return {}
            cols = [c[0] for c in cur.description]
            return dict(zip(cols, row))

    def save_song_cue_points(self, song_id, data):
        """Persist all cue points + fade settings.

        Stores the new REAL-seconds columns (hook_in_time, hook_out_time,
        intro_time, outro_time, mix_point) and the existing fade_in_ms /
        fade_out_ms integer columns. has_hook is set to 1 so the Stitcher
        immediately picks up the song.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE songs SET
                    hook_in_time = ?,
                    hook_out_time = ?,
                    has_hook = 1,
                    intro_time = ?,
                    outro_time = ?,
                    mix_point = ?,
                    fade_in_ms = ?,
                    fade_out_ms = ?
                WHERE id = ?
                """,
                (
                    float(data.get("hook_in_time", 0) or 0),
                    float(data.get("hook_out_time", 8) or 8),
                    float(data.get("intro_time", 0) or 0),
                    float(data.get("outro_time", 0) or 0),
                    float(data.get("mix_point", 0) or 0),
                    int(data.get("fade_in_ms", 0) or 0),
                    int(data.get("fade_out_ms", 3000) or 3000),
                    int(song_id),
                ),
            )
        return True


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT DEFAULT '#8B5CF6',
    description TEXT,
    auto_rotate TEXT DEFAULT 'Rotate after 1 play',
    separation_min INTEGER DEFAULT 120,
    display_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS songs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    album TEXT,
    playlister_code TEXT,
    auto_code INTEGER UNIQUE,
    label TEXT,
    cd_key TEXT,
    barcode TEXT,
    songwriter TEXT,
    composer TEXT,
    comments TEXT,
    category_id INTEGER REFERENCES categories(id),
    era TEXT,
    vocal TEXT,
    priority INTEGER DEFAULT 1,
    year INTEGER,
    bpm INTEGER,
    energy TEXT,
    duration_ms INTEGER,
    file_path TEXT,
    is_enabled INTEGER DEFAULT 1,
    is_frozen INTEGER DEFAULT 0,
    entry_date TEXT DEFAULT (datetime('now')),
    start_point_ms INTEGER DEFAULT 0,
    intro_point_ms INTEGER DEFAULT 0,
    hook_in_ms INTEGER DEFAULT 0,
    hook_out_ms INTEGER DEFAULT 0,
    outro_point_ms INTEGER DEFAULT 0,
    mix_point_ms INTEGER DEFAULT 0,
    fade_in_ms INTEGER DEFAULT 0,
    fade_out_ms INTEGER DEFAULT 0,
    fade_out_position TEXT DEFAULT 'OFF',
    volume_level INTEGER DEFAULT 100,
    variable_length INTEGER DEFAULT 0,
    separation_minutes INTEGER DEFAULT 120,
    artist_sep_minutes INTEGER DEFAULT 30
);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT DEFAULT 'Commercials',
    priority TEXT DEFAULT 'Medium',
    programming_mode TEXT DEFAULT 'Weekly',
    playback_order TEXT DEFAULT 'Rotation',
    start_date TEXT,
    end_date TEXT,
    contracted_plays_per_day INTEGER DEFAULT 3,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS spot_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    duration_ms INTEGER,
    is_active INTEGER DEFAULT 1,
    display_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS break_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    break_time TEXT NOT NULL,
    day_mask INTEGER DEFAULT 127,
    break_duration_sec INTEGER DEFAULT 120,
    start_immediately INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS campaign_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER REFERENCES campaigns(id),
    day_of_week INTEGER,
    break_time TEXT,
    slot_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jingles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT DEFAULT 'Station ID',
    file_path TEXT,
    duration_ms INTEGER,
    properties TEXT,
    playlister_code TEXT,
    is_enabled INTEGER DEFAULT 1,
    display_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jingle_pallets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    owner TEXT,
    grid_cols INTEGER DEFAULT 5,
    grid_rows INTEGER DEFAULT 6,
    audio_output INTEGER DEFAULT 4,
    display_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jingle_pads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pallet_id INTEGER REFERENCES jingle_pallets(id) ON DELETE CASCADE,
    pad_index INTEGER NOT NULL,
    label TEXT,
    file_path TEXT,
    duration_ms INTEGER,
    color TEXT DEFAULT '#F59E0B',
    volume INTEGER DEFAULT 100,
    behaviour TEXT DEFAULT 'play_once'
);

CREATE TABLE IF NOT EXISTS sweepers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT DEFAULT 'Station',
    file_path TEXT,
    duration_ms INTEGER,
    position TEXT DEFAULT 'Bridge at End',
    properties TEXT,
    playlister_code TEXT,
    is_enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS clocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    time_start TEXT,
    time_end TEXT,
    day_mask INTEGER DEFAULT 127,
    description TEXT,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS clock_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clock_id INTEGER NOT NULL REFERENCES clocks(id) ON DELETE CASCADE,
    slot_type TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id),
    energy_pref TEXT DEFAULT 'Any',
    vocal_pref TEXT DEFAULT 'Any',
    priority_pref TEXT DEFAULT 'Normal',
    separation_override INTEGER,
    position_minutes REAL,
    slot_order INTEGER NOT NULL,
    is_break INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS auto_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clock_id INTEGER REFERENCES clocks(id),
    day_of_week INTEGER NOT NULL,
    hour_start INTEGER NOT NULL,
    hour_end INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS force_clocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    clock_id INTEGER REFERENCES clocks(id),
    override_date TEXT NOT NULL,
    time_start TEXT DEFAULT '00:00',
    time_end TEXT DEFAULT '23:59',
    is_recurring INTEGER DEFAULT 0,
    recur_month INTEGER,
    recur_day INTEGER,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    playback_mode TEXT DEFAULT 'Ordered',
    on_finish TEXT DEFAULT 'Return to Clock',
    crossfade_sec INTEGER DEFAULT 3,
    scheduled_day TEXT,
    scheduled_time TEXT,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS playlist_songs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
    song_id INTEGER REFERENCES songs(id),
    position INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS final_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_date TEXT NOT NULL UNIQUE,
    is_locked INTEGER DEFAULT 0,
    generated_by TEXT DEFAULT 'AI',
    generated_at TEXT DEFAULT (datetime('now')),
    warning_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS final_log_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_id INTEGER NOT NULL REFERENCES final_logs(id) ON DELETE CASCADE,
    scheduled_time TEXT NOT NULL,
    entry_type TEXT NOT NULL,
    song_id INTEGER REFERENCES songs(id),
    campaign_id INTEGER REFERENCES campaigns(id),
    jingle_id INTEGER REFERENCES jingles(id),
    title_override TEXT,
    artist_override TEXT,
    duration_ms INTEGER,
    is_locked INTEGER DEFAULT 0,
    ai_flag TEXT,
    position INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS broadcast_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    played_at TEXT NOT NULL DEFAULT (datetime('now')),
    entry_type TEXT NOT NULL,
    song_id INTEGER REFERENCES songs(id),
    campaign_id INTEGER REFERENCES campaigns(id),
    jingle_id INTEGER REFERENCES jingles(id),
    scheduled_time TEXT,
    actual_time TEXT,
    duration_ms INTEGER,
    variance_ms INTEGER DEFAULT 0,
    deck TEXT DEFAULT 'A',
    was_manual INTEGER DEFAULT 0,
    operator TEXT DEFAULT 'AI AUTO'
);

CREATE TABLE IF NOT EXISTS ai_insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_type TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    severity TEXT DEFAULT 'info',
    message TEXT NOT NULL,
    detail TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    is_dismissed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    email TEXT,
    role TEXT DEFAULT 'DJ',
    password_hash TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    last_login TEXT
);
"""
