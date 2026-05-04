"""RadioAI Studio Pro -- AI Daily Scheduler

Generates a full day's schedule at midnight (or on demand) by
walking through every clock assigned in auto_schedule, resolving
each slot to a concrete song/sweeper/jingle, and writing the result
to ai_daily_log. The Studio's AutoScheduler reads this log instead
of picking songs in real time, ensuring variety and rule compliance.
"""

import logging
import threading
import time
from datetime import datetime, timedelta

log = logging.getLogger("AIDailyScheduler")


class AIDailyScheduler:
    def __init__(self, db):
        self.db = db

    # ── Midnight watcher ─────────────────────────────────────────────

    def start_midnight_watcher(self):
        """Background thread: triggers at 12AM or 1AM (backup), once per day."""
        last_triggered_date = None
        while True:
            try:
                now = datetime.now()
                today = now.date()
                tomorrow = today + timedelta(days=1)

                # Only trigger at exactly :00 of hour 0 or 1
                if now.hour in (0, 1) and now.minute == 0:

                    # Already triggered today? Skip.
                    if last_triggered_date == today:
                        time.sleep(30)
                        continue

                    # Check if tomorrow's schedule is already done
                    tomorrow_str = str(tomorrow)
                    done = self.is_schedule_done(tomorrow_str)

                    if done:
                        last_triggered_date = today
                        log.info(f"[AI Scheduler] {now.hour:02d}:00 — already done for {tomorrow_str}, skipping")
                    else:
                        last_triggered_date = today
                        log.info(f"[AI Scheduler] triggering at {now.hour:02d}:00 for {tomorrow_str}...")
                        self.generate_schedule(tomorrow_str)

            except Exception as e:
                log.error(f"[AI Scheduler] watcher error: {e}")
            time.sleep(30)

    def is_schedule_done(self, date_str):
        """Check if a schedule has already been generated for the given date."""
        rows = self.db.execute(
            "SELECT status FROM ai_schedule_status WHERE schedule_date = ?",
            (date_str,))
        return bool(rows and rows[0][0] == 'done')

    # ── Main generator ───────────────────────────────────────────────

    def _log_step(self, date_str, label, detail="", status="done"):
        try:
            t = datetime.now().strftime("%H:%M:%S")
            self.db.execute(
                "INSERT INTO ai_run_steps (run_date, step_time, step_label, step_detail, status) VALUES (?,?,?,?,?)",
                (date_str, t, label, detail, status))
        except Exception:
            pass

    def _log_decision(self, date_str, dtype, song_id, message):
        try:
            t = datetime.now().strftime("%H:%M:%S")
            self.db.execute(
                "INSERT INTO ai_decisions (run_date, decision_time, decision_type, song_id, message) VALUES (?,?,?,?,?)",
                (date_str, t, dtype, song_id or 0, message))
        except Exception:
            pass

    def generate_schedule(self, date_str):
        """Build a complete day's schedule for *date_str* (YYYY-MM-DD)."""
        try:
            self._set_status(date_str, "pending")
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            dow = dt.weekday()

            # Clear any existing log for this date
            self.db.execute("DELETE FROM ai_daily_log WHERE schedule_date=?", (date_str,))
            self.db.execute("DELETE FROM ai_schedule_warnings WHERE schedule_date=?", (date_str,))
            self.db.execute("DELETE FROM ai_run_steps WHERE run_date=?", (date_str,))
            self.db.execute("DELETE FROM ai_decisions WHERE run_date=?", (date_str,))

            self._log_step(date_str, "Midnight trigger fired", "Schedule generation started")
            self._log_step(date_str, "Reading clock grid", f"Day {dow}, checking 24 hours")

            songs_scheduled = 0
            warnings = []

            for hour in range(24):
                clock = self._get_clock(dow, hour)
                if not clock:
                    continue

                slots = self._get_clock_slots(clock["id"])
                position = 0

                for slot in slots:
                    stype = slot.get("slot_type", "Song")

                    if stype == "Song":
                        song = self._pick_best_song(
                            slot.get("category_id"),
                            hour, date_str
                        )
                        if song:
                            self._save_log(date_str, hour, position, song[0], "song")
                            songs_scheduled += 1
                        else:
                            cat_name = self._cat_name(slot.get("category_id"))
                            warnings.append({
                                "type": "no_song",
                                "category_name": cat_name,
                                "message": f"No song for hour {hour} category {cat_name}",
                                "severity": "critical",
                            })

                    elif stype == "Sweeper":
                        item_id = slot.get("item_id", 0)
                        if item_id:
                            self._save_log(date_str, hour, position, item_id, "sweeper")

                    elif stype == "Jingle":
                        item_id = slot.get("item_id", 0)
                        if item_id:
                            self._save_log(date_str, hour, position, item_id, "jingle")
                        else:
                            jingle = self._pick_random_jingle()
                            if jingle:
                                self._save_log(date_str, hour, position, jingle[0], "jingle")

                    elif stype == "Spot":
                        self._save_log(date_str, hour, position, 0, "spot")

                    position += 1

            self._log_step(date_str, f"Generating {songs_scheduled} slots", f"Across {len(set(h for h in range(24) if self._get_clock(dow, h)))} clock hours")

            # Check category health
            self._log_step(date_str, "Analyzing categories", "Checking song availability")
            for cat_warn in self._check_category_health(date_str):
                warnings.append(cat_warn)

            if warnings:
                self._log_step(date_str, f"{len(warnings)} warnings generated", "Low song count in categories", "warn")
            self._log_step(date_str, "Writing to Final Log", f"{songs_scheduled} songs saved")

            self._save_warnings(date_str, warnings)
            self._set_status(date_str, "done",
                             songs_scheduled=songs_scheduled,
                             warnings_count=len(warnings))

            self._log_step(date_str, "Schedule complete!", f"Status: DONE — Radio ready!")
            log.info(f"[AI Scheduler] {date_str}: {songs_scheduled} songs, {len(warnings)} warnings")

        except Exception as e:
            self._set_status(date_str, "failed", error=str(e))
            log.error(f"[AI Scheduler] failed for {date_str}: {e}")

    # ── Song selection with cascading fallbacks ──────────────────────

    def _pick_best_song(self, category_id, hour, date_str):
        """Song pick: 7-day same-song gap, 3-day fallback, then any."""
        base = (
            "SELECT s.id, s.title, s.artist FROM songs s "
            "WHERE s.is_enabled = 1 "
            "AND s.file_path IS NOT NULL AND s.file_path != ''"
        )
        cat_clause = " AND s.category_id = ?" if category_id else ""
        cat_params = [int(category_id)] if category_id else []

        # Attempt 1: not played in 7 days
        q1 = (base + cat_clause +
              " AND s.id NOT IN (SELECT song_id FROM broadcast_log WHERE played_at > datetime('now','-7 days') AND song_id IS NOT NULL)"
              " ORDER BY RANDOM() LIMIT 1")
        r = self.db.execute(q1, tuple(cat_params))
        if r:
            return r[0]

        # Attempt 2: not played in 3 days
        q2 = (base + cat_clause +
              " AND s.id NOT IN (SELECT song_id FROM broadcast_log WHERE played_at > datetime('now','-3 days') AND song_id IS NOT NULL)"
              " ORDER BY RANDOM() LIMIT 1")
        r = self.db.execute(q2, tuple(cat_params))
        if r:
            return r[0]

        # Attempt 3: any song in category
        q3 = base + cat_clause + " ORDER BY RANDOM() LIMIT 1"
        r = self.db.execute(q3, tuple(cat_params))
        if r:
            return r[0]

        # Attempt 4: any song at all
        r = self.db.execute(base + " ORDER BY RANDOM() LIMIT 1")
        return r[0] if r else None

    # ── Helpers ──────────────────────────────────────────────────────

    def _get_clock(self, dow, hour):
        rows = self.db.execute(
            "SELECT c.id, c.name FROM auto_schedule a "
            "JOIN clocks c ON c.id = a.clock_id "
            "WHERE a.day_of_week=? AND a.hour_start=? AND c.is_active=1 LIMIT 1",
            (dow, hour))
        return {"id": rows[0][0], "name": rows[0][1]} if rows else None

    def _get_clock_slots(self, clock_id):
        rows = self.db.execute(
            "SELECT slot_type, category_id, item_id, sweeper_position, energy_pref, vocal_pref "
            "FROM clock_slots WHERE clock_id=? ORDER BY slot_order",
            (int(clock_id),))
        return [{"slot_type": r[0] or "Song", "category_id": r[1], "item_id": r[2] or 0,
                 "sweeper_position": r[3] or "", "energy": r[4] or "Any", "vocal": r[5] or "Any"}
                for r in rows]

    def _pick_random_jingle(self):
        rows = self.db.execute(
            "SELECT id FROM jingles WHERE is_enabled=1 ORDER BY RANDOM() LIMIT 1")
        return rows[0] if rows else None

    def _cat_name(self, cat_id):
        if not cat_id:
            return "Any"
        rows = self.db.execute("SELECT name FROM categories WHERE id=?", (int(cat_id),))
        return rows[0][0] if rows else "Unknown"

    def _save_log(self, date_str, hour, position, song_id, slot_type):
        self.db.execute(
            "INSERT INTO ai_daily_log (schedule_date, hour, position, song_id, slot_type) "
            "VALUES (?,?,?,?,?)",
            (date_str, hour, position, song_id, slot_type))

    def _set_status(self, date_str, status, songs_scheduled=0, warnings_count=0, error=None):
        self.db.execute("DELETE FROM ai_schedule_status WHERE schedule_date=?", (date_str,))
        self.db.execute(
            "INSERT INTO ai_schedule_status (schedule_date, status, songs_scheduled, warnings_count, error_message) "
            "VALUES (?,?,?,?,?)",
            (date_str, status, songs_scheduled, warnings_count, error or ""))

    def _save_warnings(self, date_str, warnings):
        for w in warnings:
            self.db.execute(
                "INSERT INTO ai_schedule_warnings (schedule_date, warning_type, category_name, message, severity) "
                "VALUES (?,?,?,?,?)",
                (date_str, w.get("type", ""), w.get("category_name", ""),
                 w.get("message", ""), w.get("severity", "info")))

    def _check_category_health(self, date_str):
        """Warn if any category has very few enabled songs."""
        warnings = []
        cats = self.db.execute(
            "SELECT c.id, c.name, COUNT(s.id) as cnt "
            "FROM categories c LEFT JOIN songs s ON s.category_id=c.id AND s.is_enabled=1 "
            "GROUP BY c.id HAVING cnt < 10")
        for r in cats:
            warnings.append({
                "type": "low_songs",
                "category_name": r[1],
                "message": f"{r[1]}: only {r[2]} songs available",
                "severity": "warning",
            })
        return warnings

    # ── Query: get AI log for an hour ────────────────────────────────

    def get_hour_schedule(self, date_str, hour):
        """Return the pre-built song order for a specific hour."""
        rows = self.db.execute(
            "SELECT dl.song_id, dl.slot_type, dl.position, "
            "s.artist, s.title, s.file_path, s.duration_ms, s.bpm, s.year, "
            "c.name AS cat_name, c.color AS cat_color "
            "FROM ai_daily_log dl "
            "LEFT JOIN songs s ON s.id = dl.song_id "
            "LEFT JOIN categories c ON c.id = s.category_id "
            "WHERE dl.schedule_date=? AND dl.hour=? AND dl.status='scheduled' "
            "ORDER BY dl.position",
            (date_str, hour))
        return rows

    def get_status(self, date_str):
        rows = self.db.execute(
            "SELECT * FROM ai_schedule_status WHERE schedule_date=?", (date_str,))
        if not rows:
            return {"status": "pending", "songs_scheduled": 0, "warnings_count": 0,
                    "generated_at": None, "error_message": ""}
        r = rows[0]
        result = {
            "status": r[2], "generated_at": r[3],
            "warnings_count": r[4], "songs_scheduled": r[5],
            "error_message": r[6] or "",
        }
        warns = self.db.execute(
            "SELECT warning_type, category_name, message, severity "
            "FROM ai_schedule_warnings WHERE schedule_date=? ORDER BY severity DESC",
            (date_str,))
        result["warnings"] = [{"type": w[0], "category": w[1], "message": w[2], "severity": w[3]}
                               for w in warns]
        return result
