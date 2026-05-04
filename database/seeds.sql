-- ════════════════════════════════════════════════════════════════════
-- RadioAI Studio Pro v2.0 — Default Seed Data
-- ════════════════════════════════════════════════════════════════════
-- ALL inserts use INSERT OR IGNORE → 100% safe on existing DB.
-- Existing 86 settings, 15 categories, 395 songs are NEVER touched.
-- Only fills gaps where rows don't exist yet.
-- ════════════════════════════════════════════════════════════════════

-- ── Core Application Settings ─────────────────────────────────────
INSERT OR IGNORE INTO settings (key, value) VALUES
    ('station_name',           'My Radio Station'),
    ('station_location',       ''),
    ('station_frequency',      ''),
    ('station_slogan',         ''),
    ('station_email',          ''),
    ('station_region',         ''),
    ('station_city',           '');

-- Audio engine defaults
INSERT OR IGNORE INTO settings (key, value) VALUES
    ('master_volume',          '85'),
    ('jingle_volume',          '90'),
    ('cue_volume',             '70'),
    ('mic_volume',             '75'),
    ('fade_in_ms',             '1000'),
    ('fade_out_ms',            '3000'),
    ('spot_fade_ms',           '0'),
    ('crossfade_ms',           '3000'),
    ('crossfade_duration',     '6'),
    ('preload_buffer',         '10 seconds ahead'),
    ('audio_buffer_size',      '256'),
    ('sample_rate',            '44100'),
    ('bit_depth',              '32-bit float'),
    ('audio_engine',           'WASAPI');

-- Scheduling rules (also stored in settings for compatibility)
INSERT OR IGNORE INTO settings (key, value) VALUES
    ('same_song_days',         '7'),
    ('same_slot_days',         '3'),
    ('same_artist_hours',      '2'),
    ('same_category_mins',     '30'),
    ('artist_title_sep_hours', '1'),
    ('selection_randomness',   '0'),
    ('vocal_type',             'Alternate'),
    ('artist_separation',      '0'),
    ('ad_limit_per_hour',      '15'),
    ('default_separation_min', '120');

-- AI settings
INSERT OR IGNORE INTO settings (key, value) VALUES
    ('ai_enabled',             '1'),
    ('ai_model',               'claude-sonnet-4-20250514'),
    ('scheduling_auto_mode',   'SOHO');

-- Playback behaviour
INSERT OR IGNORE INTO settings (key, value) VALUES
    ('auto_mode',              '1'),
    ('auto_play_on_startup',   '1'),
    ('auto_queue_hours',       '2'),
    ('start_in_auto_mode',     'true'),
    ('automix_trigger',        'At song MIX POINT marker'),
    ('load_next_song',         'At mix point of current'),
    ('fallback_action',        'Skip and play next available song'),
    ('auto_load_last_session', 'true');

-- UI / display settings
INSERT OR IGNORE INTO settings (key, value) VALUES
    ('time_format',            '24h'),
    ('date_format',            'MM/DD/YYYY'),
    ('show_splash_screen',     'true'),
    ('minimize_to_tray',       'true'),
    ('start_on_windows_startup','false');

-- Cue editor settings
INSERT OR IGNORE INTO settings (key, value) VALUES
    ('autocue_threshold',      '-35'),
    ('autocue_scan_mode',      'Scan first 10s + last 10s (Fast)'),
    ('fade_curve_type',        'Logarithmic'),
    ('fade_out_start',         '5');

-- ── Scheduling Rules (new table) ──────────────────────────────────
INSERT OR IGNORE INTO scheduling_rules (rule_name, rule_value) VALUES
    ('same_song_days',         '7'),
    ('same_slot_days',         '3'),
    ('artist_separation_hrs',  '2'),
    ('category_sep_mins',      '30'),
    ('artist_title_sep_hrs',   '1'),
    ('selection_randomness',   '0'),
    ('vocal_alternation',      'false'),
    ('ad_limit_per_hour',      '15');

-- ── Default Categories ────────────────────────────────────────────
-- Station already has 15 categories. These are fallbacks for fresh install.
INSERT OR IGNORE INTO categories (name, color, description) VALUES
    ('Hot Currents',  '#F59E0B', 'Current chart hits'),
    ('Currents',      '#A78BFA', 'Recent releases'),
    ('Recurrents',    '#6D28D9', 'Recent favourites'),
    ('Gold',          '#F59E0B', 'Classic gold tracks'),
    ('Power Gold',    '#F43F5E', 'High-rotation gold'),
    ('Specialty',     '#06B6D4', 'Specialty programming'),
    ('Morning Vibes', '#8B5CF6', 'Upbeat morning tracks'),
    ('Bhajan',        '#F59E0B', 'Devotional / bhajan'),
    ('Classics',      '#8B5CF6', 'Classic hits'),
    ('Pop',           '#10B981', 'Pop hits'),
    ('Dance',         '#06B6D4', 'Dance / EDM'),
    ('Romantic',      '#F43F5E', 'Romantic songs'),
    ('Devotional',    '#A78BFA', 'Devotional tracks'),
    ('News Break',    '#454D6D', 'News / talk break');

-- ── Default Spot Schedules ────────────────────────────────────────
-- Commercial breaks at :30 of each hour, 5-minute max.
INSERT OR IGNORE INTO spot_schedules (day_of_week, hour, minute, max_duration_mins, is_active) VALUES
    (NULL, 6,  30, 5, 1),
    (NULL, 7,  30, 5, 1),
    (NULL, 8,  30, 5, 1),
    (NULL, 9,  30, 5, 1),
    (NULL, 10, 30, 5, 1),
    (NULL, 11, 30, 5, 1),
    (NULL, 12, 30, 5, 1),
    (NULL, 13, 30, 5, 1),
    (NULL, 14, 30, 5, 1),
    (NULL, 15, 30, 5, 1),
    (NULL, 16, 30, 5, 1),
    (NULL, 17, 30, 5, 1),
    (NULL, 18, 30, 5, 1),
    (NULL, 19, 30, 5, 1),
    (NULL, 20, 30, 5, 1),
    (NULL, 21, 30, 5, 1),
    (NULL, 22, 30, 5, 1);

-- ── Stitcher Default Config ───────────────────────────────────────
INSERT OR IGNORE INTO stitcher_config (id) VALUES (1);

-- ── Default Admin User ────────────────────────────────────────────
INSERT OR IGNORE INTO users (username, display_name, role) VALUES
    ('admin', 'Administrator', 'admin'),
    ('dj',    'On-Air DJ',     'dj');

-- ── Schema Version ────────────────────────────────────────────────
INSERT OR IGNORE INTO schema_migrations (name) VALUES ('v2.0.0_seeds');
