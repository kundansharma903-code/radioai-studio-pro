-- Migration: 001_initial
-- Date: 2026-04-14
-- Description: Core tables — songs, categories, campaigns, jingles,
--              sweepers, clocks, broadcast log, settings, users.

CREATE TABLE IF NOT EXISTS categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    color           TEXT    DEFAULT '#8B5CF6',
    description     TEXT,
    auto_rotate     TEXT    DEFAULT 'Rotate after 1 play',
    separation_min  INTEGER DEFAULT 120,
    display_order   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS songs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    artist              TEXT    NOT NULL,
    title               TEXT    NOT NULL,
    album               TEXT,
    playlister_code     TEXT,
    auto_code           INTEGER UNIQUE,
    label               TEXT,
    cd_key              TEXT,
    barcode             TEXT,
    songwriter          TEXT,
    composer            TEXT,
    comments            TEXT,
    category_id         INTEGER REFERENCES categories(id),
    era                 TEXT,
    vocal               TEXT,
    priority            INTEGER DEFAULT 1,
    year                INTEGER,
    bpm                 INTEGER,
    energy              TEXT,
    duration_ms         INTEGER,
    file_path           TEXT,
    is_enabled          INTEGER DEFAULT 1,
    is_frozen           INTEGER DEFAULT 0,
    entry_date          TEXT    DEFAULT (datetime('now')),
    start_point_ms      INTEGER DEFAULT 0,
    intro_point_ms      INTEGER DEFAULT 0,
    hook_in_ms          INTEGER DEFAULT 0,
    hook_out_ms         INTEGER DEFAULT 0,
    outro_point_ms      INTEGER DEFAULT 0,
    mix_point_ms        INTEGER DEFAULT 0,
    fade_in_ms          INTEGER DEFAULT 0,
    fade_out_ms         INTEGER DEFAULT 0,
    fade_out_position   TEXT    DEFAULT 'OFF',
    volume_level        INTEGER DEFAULT 100,
    variable_length     INTEGER DEFAULT 0,
    separation_minutes  INTEGER DEFAULT 120,
    artist_sep_minutes  INTEGER DEFAULT 30
);

CREATE TABLE IF NOT EXISTS campaigns (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    name                     TEXT    NOT NULL,
    description              TEXT,
    category                 TEXT    DEFAULT 'Commercials',
    priority                 TEXT    DEFAULT 'Medium',
    programming_mode         TEXT    DEFAULT 'Weekly',
    playback_order           TEXT    DEFAULT 'Rotation',
    start_date               TEXT,
    end_date                 TEXT,
    contracted_plays_per_day INTEGER DEFAULT 3,
    is_active                INTEGER DEFAULT 1,
    created_at               TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS spot_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id   INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    filename      TEXT    NOT NULL,
    file_path     TEXT    NOT NULL,
    duration_ms   INTEGER,
    is_active     INTEGER DEFAULT 1,
    display_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS break_schedule (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    break_time         TEXT    NOT NULL,
    day_mask           INTEGER DEFAULT 127,
    break_duration_sec INTEGER DEFAULT 120,
    start_immediately  INTEGER DEFAULT 0,
    is_active          INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS campaign_schedule (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER REFERENCES campaigns(id),
    day_of_week INTEGER,
    break_time  TEXT,
    slot_order  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jingles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    category        TEXT    DEFAULT 'Station ID',
    file_path       TEXT,
    duration_ms     INTEGER,
    properties      TEXT,
    playlister_code TEXT,
    is_enabled      INTEGER DEFAULT 1,
    display_order   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jingle_pallets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    owner         TEXT,
    grid_cols     INTEGER DEFAULT 5,
    grid_rows     INTEGER DEFAULT 6,
    audio_output  INTEGER DEFAULT 4,
    display_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jingle_pads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pallet_id   INTEGER REFERENCES jingle_pallets(id) ON DELETE CASCADE,
    pad_index   INTEGER NOT NULL,
    label       TEXT,
    file_path   TEXT,
    duration_ms INTEGER,
    color       TEXT    DEFAULT '#F59E0B',
    volume      INTEGER DEFAULT 100,
    behaviour   TEXT    DEFAULT 'play_once'
);

CREATE TABLE IF NOT EXISTS sweepers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    category        TEXT    DEFAULT 'Station',
    file_path       TEXT,
    duration_ms     INTEGER,
    position        TEXT    DEFAULT 'Bridge at End',
    properties      TEXT,
    playlister_code TEXT,
    is_enabled      INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS clocks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    time_start  TEXT,
    time_end    TEXT,
    day_mask    INTEGER DEFAULT 127,
    description TEXT,
    is_active   INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS clock_slots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    clock_id            INTEGER NOT NULL REFERENCES clocks(id) ON DELETE CASCADE,
    slot_type           TEXT    NOT NULL,
    category_id         INTEGER REFERENCES categories(id),
    energy_pref         TEXT    DEFAULT 'Any',
    vocal_pref          TEXT    DEFAULT 'Any',
    priority_pref       TEXT    DEFAULT 'Normal',
    separation_override INTEGER,
    position_minutes    REAL,
    slot_order          INTEGER NOT NULL,
    is_break            INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS auto_schedule (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clock_id    INTEGER REFERENCES clocks(id),
    day_of_week INTEGER NOT NULL,
    hour_start  INTEGER NOT NULL,
    hour_end    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS force_clocks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    clock_id      INTEGER REFERENCES clocks(id),
    override_date TEXT    NOT NULL,
    time_start    TEXT    DEFAULT '00:00',
    time_end      TEXT    DEFAULT '23:59',
    is_recurring  INTEGER DEFAULT 0,
    recur_month   INTEGER,
    recur_day     INTEGER,
    is_active     INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS playlists (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    description     TEXT,
    playback_mode   TEXT    DEFAULT 'Ordered',
    on_finish       TEXT    DEFAULT 'Return to Clock',
    crossfade_sec   INTEGER DEFAULT 3,
    scheduled_day   TEXT,
    scheduled_time  TEXT,
    is_active       INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS playlist_songs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
    song_id     INTEGER REFERENCES songs(id),
    position    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS final_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    log_date      TEXT    NOT NULL UNIQUE,
    is_locked     INTEGER DEFAULT 0,
    generated_by  TEXT    DEFAULT 'AI',
    generated_at  TEXT    DEFAULT (datetime('now')),
    warning_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS final_log_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    log_id          INTEGER NOT NULL REFERENCES final_logs(id) ON DELETE CASCADE,
    scheduled_time  TEXT    NOT NULL,
    entry_type      TEXT    NOT NULL,
    song_id         INTEGER REFERENCES songs(id),
    campaign_id     INTEGER REFERENCES campaigns(id),
    jingle_id       INTEGER REFERENCES jingles(id),
    title_override  TEXT,
    artist_override TEXT,
    duration_ms     INTEGER,
    is_locked       INTEGER DEFAULT 0,
    ai_flag         TEXT,
    position        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS broadcast_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    played_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    entry_type     TEXT    NOT NULL,
    song_id        INTEGER REFERENCES songs(id),
    campaign_id    INTEGER REFERENCES campaigns(id),
    jingle_id      INTEGER REFERENCES jingles(id),
    scheduled_time TEXT,
    actual_time    TEXT,
    duration_ms    INTEGER,
    variance_ms    INTEGER DEFAULT 0,
    deck           TEXT    DEFAULT 'A',
    was_manual     INTEGER DEFAULT 0,
    operator       TEXT    DEFAULT 'AI AUTO'
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    display_name  TEXT    NOT NULL,
    email         TEXT,
    role          TEXT    DEFAULT 'DJ',
    password_hash TEXT,
    is_active     INTEGER DEFAULT 1,
    created_at    TEXT    DEFAULT (datetime('now')),
    last_login    TEXT
);

CREATE INDEX IF NOT EXISTS idx_songs_category   ON songs(category_id);
CREATE INDEX IF NOT EXISTS idx_songs_enabled    ON songs(is_enabled);
CREATE INDEX IF NOT EXISTS idx_songs_artist     ON songs(artist);
CREATE INDEX IF NOT EXISTS idx_spot_files_camp  ON spot_files(campaign_id);
CREATE INDEX IF NOT EXISTS idx_clock_slots_clk  ON clock_slots(clock_id, slot_order);
CREATE INDEX IF NOT EXISTS idx_auto_sched_day   ON auto_schedule(day_of_week, hour_start);
