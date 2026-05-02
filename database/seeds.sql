-- ════════════════════════════════════════════════════════════════════
-- RadioAI Studio Pro — Default Seed Data
-- ════════════════════════════════════════════════════════════════════
-- Loaded on first run when the corresponding tables are empty.
-- INSERT OR IGNORE everywhere so re-running is safe.
-- ════════════════════════════════════════════════════════════════════

-- ── Settings ────────────────────────────────────────────────────────
INSERT OR IGNORE INTO settings (key, value) VALUES
    ('station_name',         'My Radio Station'),
    ('station_location',     ''),
    ('ai_model',             'claude-sonnet-4-20250514'),
    ('ad_limit_per_hour',    '15'),
    ('auto_mode',            'SOHO'),

    -- Scheduling rules (also exposed via the Scheduling screen)
    ('same_song_days',       '7'),
    ('same_slot_days',       '3'),
    ('artist_separation',    '0'),
    ('selection_randomness', '0'),
    ('same_artist_hours',    '2'),
    ('same_category_mins',   '30'),
    ('artist_title_sep_hours','1'),
    ('vocal_type',           'Alternate'),
    ('scheduling_auto_mode', 'SOHO'),

    -- Studio defaults
    ('crossfade_ms',         '3000'),
    ('crossfade_duration',   '3'),
    ('fade_out_start',       '6'),
    ('fade_curve_type',      'Logarithmic'),
    ('load_next_song',       'At mix point of current'),
    ('preload_buffer',       '10 seconds ahead'),
    ('automix_trigger',      'At song MIX POINT marker'),
    ('fallback_action',      'Skip and play next'),
    ('missing_file_alert',   'true'),
    ('autocue_threshold',    '-40'),
    ('autocue_scan_mode',    'Scan first 10s + last 10s'),

    -- Volumes
    ('master_volume',        '85'),
    ('cue_volume',           '70'),
    ('jingle_volume',        '90'),
    ('mic_volume',           '75'),

    -- VU + display
    ('vu_decay_speed',       'Normal (300ms decay)'),
    ('peak_hold_duration',   '2 seconds'),
    ('clip_indicator',       'true'),
    ('cue_split_mode',       'Left: On-Air + Right: Cue'),
    ('show_crossfade_preview','true'),
    ('flash_mix_point',      'true'),

    -- Audio engine
    ('audio_buffer_size',    '256'),
    ('sample_rate',          '44100'),
    ('bit_depth',            '32-bit float'),
    ('audio_engine',         'WASAPI'),

    -- Misc
    ('default_separation_min','120'),
    ('ai_enabled',           '1'),
    ('rds_enabled',          '0');

-- ── Default song categories ─────────────────────────────────────────
-- Seven Indian-radio-friendly categories. Colours match the Design.md
-- accent palette (cyan/purple/green/amber/red/pink/muted).
INSERT OR IGNORE INTO categories (name, color, description, auto_rotate, separation_min, display_order) VALUES
    ('Hot Currents', '#F59E0B', 'Current chart-toppers in heavy rotation',  'Rotate after 1 play',  120, 1),
    ('Classics',     '#8B5CF6', 'All-time classics and evergreens',          'Rotate after 5 plays', 360, 2),
    ('Pop',          '#10B981', 'Mainstream pop hits',                       'Rotate after 2 plays', 180, 3),
    ('Dance',        '#06B6D4', 'High-energy dance and EDM',                 'Rotate after 2 plays', 180, 4),
    ('Romantic',     '#F43F5E', 'Romantic / slow-tempo tracks',              'Rotate after 3 plays', 240, 5),
    ('Devotional',   '#A78BFA', 'Devotional and spiritual songs',            'Rotate after 4 plays', 300, 6),
    ('News Break',   '#454D6D', 'News bulletins and information segments',   'No rotation',          480, 7);

-- ── Default Stitcher config row ─────────────────────────────────────
INSERT OR IGNORE INTO stitcher_config (id) VALUES (1);

-- ── Default admin user (kavish / admin123 — change after first login) ───
-- password_hash is sha256 of the plaintext shown in the comment above.
INSERT OR IGNORE INTO users (username, display_name, email, role, password_hash) VALUES
    ('kavish', 'DJ Kavish', 'kavish@kissfm.in', 'Administrator',
     '240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9');
