-- ════════════════════════════════════════════════════════════════════
-- RadioAI Studio Pro — Campaign recovery (incident 2026-05-04)
--
-- Restores the 15 campaigns I accidentally deleted via a malformed
-- LIKE pattern. Data sourced from chat-history evidence:
--   • Phase A backfill log (id ↔ name ↔ auto_code mapping)
--   • Phase A get_all_campaigns first-row dump (Bank of Stars Promo full row)
--   • Phase B Library screenshots (visible category, priority, dates)
--
-- Confirmed unrecoverable (no replacement attempted):
--   • spot_files (10 rows — real audio paths lost)
--   • campaign_schedule (~791 rows — break times lost)
--   • description column for 14 of 15 rows (only Bank of Stars known)
--   • contracted_plays_per_day for 14 of 15 rows (only Bank of Stars known)
--
-- Defaults applied where the original value is unknown:
--   • description       → NULL
--   • programming_mode  → 'Weekly'      (schema default, matches Bank of Stars)
--   • playback_order    → 'In Rotation' (schema default, matches Bank of Stars)
--   • contracted_plays_per_day → 3      (schema default; Bank of Stars=2 known)
--   • min_gap_minutes   → 30            (schema default after migration)
--   • max_per_break     → 1             (schema default after migration)
--   • availability      → 'active'      (schema default after migration)
--
-- Auto codes mirror the original sequential backfill (1→400001, …, 15→400015)
-- so generate_auto_code() will return 400016 for the next new campaign.
--
-- SAFETY:
--   • Wrapped in BEGIN TRANSACTION
--   • Final SELECT count must equal 15 — caller must verify before COMMIT
-- ════════════════════════════════════════════════════════════════════

BEGIN TRANSACTION;

-- 1. FreshBurst Cola — Summer  (id=1, Commercials, High)
INSERT INTO campaigns (id, name, description, category, priority,
                       programming_mode, playback_order,
                       start_date, end_date,
                       contracted_plays_per_day, is_active, auto_code)
VALUES (1, 'FreshBurst Cola — Summer', NULL,
        'Commercials', 'High', 'Weekly', 'In Rotation',
        '2026-04-01', '2026-06-30', 3, 1, '400001');

-- 2. NovaTech Mobile — Launch  (id=2, Commercials, High)
INSERT INTO campaigns (id, name, description, category, priority,
                       programming_mode, playback_order,
                       start_date, end_date,
                       contracted_plays_per_day, is_active, auto_code)
VALUES (2, 'NovaTech Mobile — Launch', NULL,
        'Commercials', 'High', 'Weekly', 'In Rotation',
        '2026-03-15', '2026-06-15', 3, 1, '400002');

-- 3. City FM Station ID  (id=3, Station ID, Always)
INSERT INTO campaigns (id, name, description, category, priority,
                       programming_mode, playback_order,
                       start_date, end_date,
                       contracted_plays_per_day, is_active, auto_code)
VALUES (3, 'City FM Station ID', NULL,
        'Station ID', 'Always', 'Weekly', 'In Rotation',
        '2026-01-01', 'Never', 3, 1, '400003');

-- 4. Traffic Update Sting  (id=4, News Break, Always)
INSERT INTO campaigns (id, name, description, category, priority,
                       programming_mode, playback_order,
                       start_date, end_date,
                       contracted_plays_per_day, is_active, auto_code)
VALUES (4, 'Traffic Update Sting', NULL,
        'News Break', 'Always', 'Weekly', 'In Rotation',
        '2026-01-01', 'Never', 3, 1, '400004');

-- 5. Bank of Stars Promo  (id=5, Commercials, Medium) — FULL DATA KNOWN
INSERT INTO campaigns (id, name, description, category, priority,
                       programming_mode, playback_order,
                       start_date, end_date,
                       contracted_plays_per_day, is_active, auto_code)
VALUES (5, 'Bank of Stars Promo', 'Banking promotion',
        'Commercials', 'Medium', 'Weekly', 'In Rotation',
        '2026-01-01', 'Never', 2, 1, '400005');

-- 6. Sunrise Mall Weekend  (id=6, Commercials, Medium — already past end_date)
INSERT INTO campaigns (id, name, description, category, priority,
                       programming_mode, playback_order,
                       start_date, end_date,
                       contracted_plays_per_day, is_active, auto_code)
VALUES (6, 'Sunrise Mall Weekend', NULL,
        'Commercials', 'Medium', 'Weekly', 'In Rotation',
        '2026-04-11', '2026-04-13', 3, 1, '400006');

-- 7. PureLife Water  (id=7, Commercials, Low)
INSERT INTO campaigns (id, name, description, category, priority,
                       programming_mode, playback_order,
                       start_date, end_date,
                       contracted_plays_per_day, is_active, auto_code)
VALUES (7, 'PureLife Water', NULL,
        'Commercials', 'Low', 'Weekly', 'In Rotation',
        '2026-03-01', 'Never', 3, 1, '400007');

-- 8. Weather Flash  (id=8, News Break, Always)
INSERT INTO campaigns (id, name, description, category, priority,
                       programming_mode, playback_order,
                       start_date, end_date,
                       contracted_plays_per_day, is_active, auto_code)
VALUES (8, 'Weather Flash', NULL,
        'News Break', 'Always', 'Weekly', 'In Rotation',
        '2026-01-01', 'Never', 3, 1, '400008');

-- 9. Morning Drive Sponsor  (id=9, Sponsor, High — past end_date)
--    NOTE: log showed name truncated to "Morning Drive Sponsor" — no "ship".
--    Original might have been "Morning Drive Sponsorship" but I can't be
--    certain. Using the value visible in the screenshot and backfill log.
INSERT INTO campaigns (id, name, description, category, priority,
                       programming_mode, playback_order,
                       start_date, end_date,
                       contracted_plays_per_day, is_active, auto_code)
VALUES (9, 'Morning Drive Sponsor', NULL,
        'Sponsor', 'High', 'Weekly', 'In Rotation',
        '2026-01-01', '2026-04-30', 3, 1, '400009');

-- 10. Evening News Intro  (id=10, Station ID, Always)
INSERT INTO campaigns (id, name, description, category, priority,
                       programming_mode, playback_order,
                       start_date, end_date,
                       contracted_plays_per_day, is_active, auto_code)
VALUES (10, 'Evening News Intro', NULL,
        'Station ID', 'Always', 'Weekly', 'In Rotation',
        '2026-01-01', 'Never', 3, 1, '400010');

-- 11. Matrix Neet Division  (id=11, Commercials, High) — user-added, recovered
INSERT INTO campaigns (id, name, description, category, priority,
                       programming_mode, playback_order,
                       start_date, end_date,
                       contracted_plays_per_day, is_active, auto_code)
VALUES (11, 'Matrix Neet Division', NULL,
        'Commercials', 'High', 'Weekly', 'In Rotation',
        '2026-04-10', '2026-06-04', 3, 1, '400011');

-- 12. Matrix Neet  (id=12, Commercials, Medium) — user-added, recovered
INSERT INTO campaigns (id, name, description, category, priority,
                       programming_mode, playback_order,
                       start_date, end_date,
                       contracted_plays_per_day, is_active, auto_code)
VALUES (12, 'Matrix Neet', NULL,
        'Commercials', 'Medium', 'Weekly', 'In Rotation',
        '2026-04-11', 'Never', 3, 1, '400012');

-- 13. Hello  (id=13, Commercials, Medium) — user-added, recovered
INSERT INTO campaigns (id, name, description, category, priority,
                       programming_mode, playback_order,
                       start_date, end_date,
                       contracted_plays_per_day, is_active, auto_code)
VALUES (13, 'Hello', NULL,
        'Commercials', 'Medium', 'Weekly', 'In Rotation',
        '2026-04-11', 'Never', 3, 1, '400013');

-- 14. Test 02  (id=14, Commercials, Medium) — user-added, recovered
INSERT INTO campaigns (id, name, description, category, priority,
                       programming_mode, playback_order,
                       start_date, end_date,
                       contracted_plays_per_day, is_active, auto_code)
VALUES (14, 'Test 02', NULL,
        'Commercials', 'Medium', 'Weekly', 'In Rotation',
        '2026-04-11', 'Never', 3, 1, '400014');

-- 15. Tst 02  (id=15, Commercials, Medium) — user-added, recovered
INSERT INTO campaigns (id, name, description, category, priority,
                       programming_mode, playback_order,
                       start_date, end_date,
                       contracted_plays_per_day, is_active, auto_code)
VALUES (15, 'Tst 02', NULL,
        'Commercials', 'Medium', 'Weekly', 'In Rotation',
        '2026-04-11', 'Never', 3, 1, '400015');

-- ──────────────────────────────────────────────────────────────────
-- Verification SELECT — caller must check this before COMMIT/ROLLBACK
-- ──────────────────────────────────────────────────────────────────
SELECT
    COUNT(*)                           AS row_count,
    MIN(id)                            AS min_id,
    MAX(id)                            AS max_id,
    MIN(CAST(auto_code AS INTEGER))    AS min_code,
    MAX(CAST(auto_code AS INTEGER))    AS max_code,
    SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active_rows
FROM   campaigns;

-- Caller decides: COMMIT;  or  ROLLBACK;
