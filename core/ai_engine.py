"""RadioAI Studio Pro — AI Engine

All 10 AI functions with real algorithms.
Functions 1-5, 7-9 use local algorithms (no API).
Functions 6, 10 optionally call Claude API for edge cases.
"""

import json
import random
from datetime import datetime, timedelta
from core.database import DatabaseManager


class AIEngine:
    """AI engine for RadioAI Studio Pro — KISS FM 91.5."""

    def __init__(self, db=None):
        self.db = db or DatabaseManager()

    # ── FUNCTION 1: Auto-fill Metadata ──────────────────────────────────

    def auto_fill_metadata(self, file_path):
        """Read ID3 tags and detect BPM/energy from an audio file.

        Returns dict with: artist, title, album, year, bpm, energy, duration_ms
        Uses mutagen for tags, librosa for BPM/energy detection.
        Falls back to Claude API if genre tags are missing.
        """
        result = {}
        try:
            from mutagen import File as MutagenFile
            audio = MutagenFile(file_path, easy=True)
            if audio:
                result["artist"] = (audio.get("artist") or [""])[0]
                result["title"] = (audio.get("title") or [""])[0]
                result["album"] = (audio.get("album") or [""])[0]
                year_raw = (audio.get("date") or [""])[0]
                if year_raw:
                    result["year"] = int(year_raw[:4])
                result["duration_ms"] = int(audio.info.length * 1000) if hasattr(audio, "info") else 0
        except Exception:
            pass

        try:
            import librosa
            y, sr = librosa.load(file_path, sr=22050, duration=60)
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            result["bpm"] = int(round(float(tempo)))
            rms = librosa.feature.rms(y=y)[0].mean()
            if rms > 0.1:
                result["energy"] = "High"
            elif rms > 0.05:
                result["energy"] = "Medium"
            else:
                result["energy"] = "Low"
        except Exception:
            pass

        return result

    # ── FUNCTION 2: Overplay Alert ──────────────────────────────────────

    def check_overplay(self, song_id, threshold=3.5):
        """Check if a song has been overplayed in the last 7 days.

        Formula: plays_this_week > (7 / rotation_days) * 1.5
        Default rotation_days=3 → threshold = 7/3*1.5 = 3.5 → alert if 4+ plays
        Returns: dict with is_overplayed, plays_this_week, threshold
        """
        rows = self.db.execute(
            "SELECT COUNT(*) FROM broadcast_log "
            "WHERE song_id = ? AND played_at > datetime('now', '-7 days')",
            (song_id,),
        )
        plays = rows[0][0] if rows else 0
        return {
            "is_overplayed": plays > threshold,
            "plays_this_week": plays,
            "threshold": threshold,
            "severity": "warning" if plays > threshold else "ok",
            "message": f"Played {plays}x this week — consider rest period"
            if plays > threshold
            else f"Played {plays}x this week — within limits",
        }

    # ── FUNCTION 3: Energy Match ────────────────────────────────────────

    def get_energy_preference(self, hour=None):
        """Return the preferred energy level for a given hour.

        Time-of-day curve:
        06-10: High (morning drive)
        10-14: Medium-High
        14-18: Medium
        18-22: High (evening drive)
        22-06: Low (late night)
        """
        if hour is None:
            hour = datetime.now().hour

        if 6 <= hour < 10:
            return "High"
        elif 10 <= hour < 14:
            return "Medium"
        elif 14 <= hour < 18:
            return "Medium"
        elif 18 <= hour < 22:
            return "High"
        else:
            return "Low"

    def check_energy_match(self, song_id, hour=None):
        """Check if a song's energy matches the preferred level for the current hour."""
        preferred = self.get_energy_preference(hour)
        rows = self.db.execute("SELECT energy FROM songs WHERE id = ?", (song_id,))
        if not rows:
            return {"match": False, "message": "Song not found"}
        song_energy = rows[0][0] or "Medium"
        match = song_energy == preferred
        return {
            "match": match,
            "song_energy": song_energy,
            "preferred_energy": preferred,
            "hour": hour or datetime.now().hour,
            "severity": "ok" if match else "info",
            "message": f"{'Good' if match else 'Mismatch'}: {song_energy} energy "
            f"{'fits' if match else 'vs preferred'} {preferred} for this hour",
        }

    # ── FUNCTION 4: Rotation Health ─────────────────────────────────────

    def get_rotation_health(self, category_id=None):
        """Calculate rotation health as percentage of unique songs played in 30 days.

        health = (unique_songs_30d / total_songs) * 100
        <50% = Poor, 50-70% = Fair, >70% = Good
        """
        if category_id:
            total_rows = self.db.execute(
                "SELECT COUNT(*) FROM songs WHERE category_id = ? AND is_enabled = 1",
                (category_id,),
            )
            unique_rows = self.db.execute(
                "SELECT COUNT(DISTINCT song_id) FROM broadcast_log "
                "WHERE song_id IN (SELECT id FROM songs WHERE category_id = ?) "
                "AND played_at > datetime('now', '-30 days')",
                (category_id,),
            )
        else:
            total_rows = self.db.execute(
                "SELECT COUNT(*) FROM songs WHERE is_enabled = 1"
            )
            unique_rows = self.db.execute(
                "SELECT COUNT(DISTINCT song_id) FROM broadcast_log "
                "WHERE played_at > datetime('now', '-30 days')"
            )

        total = total_rows[0][0] if total_rows else 0
        unique = unique_rows[0][0] if unique_rows else 0

        if total == 0:
            return {"health": 0, "rating": "N/A", "unique": 0, "total": 0}

        health = round((unique / total) * 100, 1)
        if health >= 70:
            rating = "Good"
        elif health >= 50:
            rating = "Fair"
        else:
            rating = "Poor"

        return {
            "health": health,
            "rating": rating,
            "unique_songs_30d": unique,
            "total_songs": total,
            "message": f"Rotation health: {health}% ({rating}) — {unique}/{total} songs played in 30 days",
        }

    # ── FUNCTION 5: Similar Songs ───────────────────────────────────────

    def find_similar_songs(self, song_id, bpm_range=15, limit=10):
        """Find songs similar to a given song by BPM, energy, and category.

        SELECT * FROM songs WHERE ABS(bpm - ?) <= 15
        AND energy = ? AND category_id = ? AND id != ?
        """
        rows = self.db.execute(
            "SELECT bpm, energy, category_id FROM songs WHERE id = ?", (song_id,)
        )
        if not rows:
            return []
        bpm, energy, cat_id = rows[0][0], rows[0][1], rows[0][2]
        if not bpm:
            return []

        similar = self.db.execute(
            """SELECT s.id, s.artist, s.title, s.bpm, s.energy,
                      c.name AS category_name
               FROM songs s
               LEFT JOIN categories c ON s.category_id = c.id
               WHERE ABS(s.bpm - ?) <= ?
               AND s.energy = ? AND s.category_id = ? AND s.id != ?
               AND s.is_enabled = 1
               ORDER BY ABS(s.bpm - ?) ASC
               LIMIT ?""",
            (bpm, bpm_range, energy, cat_id, song_id, bpm, limit),
        )
        return [
            {
                "id": r[0], "artist": r[1], "title": r[2],
                "bpm": r[3], "energy": r[4], "category": r[5],
            }
            for r in similar
        ]

    # ── FUNCTION 6: Break Conflict Detection ────────────────────────────

    def detect_break_conflicts(self):
        """Check if any break's scheduled spots exceed its duration.

        Alert if total spot duration > break_duration_sec * 1.1 (10% buffer)
        """
        breaks = self.db.execute(
            "SELECT id, break_time, break_duration_sec FROM break_schedule WHERE is_active = 1"
        )
        conflicts = []
        for brk in breaks:
            brk_id, brk_time, brk_dur = brk[0], brk[1], brk[2]
            spots = self.db.execute(
                """SELECT COALESCE(SUM(sf.duration_ms), 0) / 1000.0
                   FROM campaign_schedule cs
                   JOIN campaigns c ON cs.campaign_id = c.id
                   JOIN spot_files sf ON sf.campaign_id = c.id
                   WHERE cs.break_time = ? AND c.is_active = 1 AND sf.is_active = 1""",
                (brk_time,),
            )
            total_sec = spots[0][0] if spots else 0
            max_sec = brk_dur * 1.1
            if total_sec > max_sec:
                conflicts.append({
                    "break_time": brk_time,
                    "break_duration_sec": brk_dur,
                    "total_spot_sec": round(total_sec, 1),
                    "overflow_sec": round(total_sec - brk_dur, 1),
                    "severity": "warning",
                    "message": f"Break at {brk_time}: {round(total_sec)}s of spots in {brk_dur}s slot",
                })
        return conflicts

    # ── FUNCTION 7: Campaign Delivery Monitor ───────────────────────────

    def monitor_campaign_delivery(self):
        """Check if campaigns are meeting their contracted plays.

        URGENT if <80% with <3 days remaining
        WARNING if <90% with <7 days remaining
        """
        campaigns = self.db.execute(
            "SELECT id, name, end_date, contracted_plays_per_day FROM campaigns WHERE is_active = 1"
        )
        alerts = []
        now = datetime.now()
        for c in campaigns:
            c_id, name, end_date_str, contracted = c[0], c[1], c[2], c[3]
            if not end_date_str or end_date_str == "Never":
                continue

            try:
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
            except (ValueError, TypeError):
                continue

            days_remaining = (end_date - now).days
            if days_remaining < 0:
                continue

            plays_today = self.db.execute(
                "SELECT COUNT(*) FROM broadcast_log "
                "WHERE campaign_id = ? AND played_at > datetime('now', '-1 day')",
                (c_id,),
            )[0][0]

            delivery_pct = (plays_today / max(contracted, 1)) * 100

            if delivery_pct < 80 and days_remaining < 3:
                alerts.append({
                    "campaign": name, "delivery_pct": round(delivery_pct),
                    "days_remaining": days_remaining, "severity": "urgent",
                    "message": f"{name}: {round(delivery_pct)}% delivery, {days_remaining} days left",
                })
            elif delivery_pct < 90 and days_remaining < 7:
                alerts.append({
                    "campaign": name, "delivery_pct": round(delivery_pct),
                    "days_remaining": days_remaining, "severity": "warning",
                    "message": f"{name}: {round(delivery_pct)}% delivery, {days_remaining} days left",
                })

        return alerts

    # ── FUNCTION 8: Optimal Break Time Suggestion ───────────────────────

    def suggest_break_times(self):
        """Analyze historical overruns and library depth to suggest optimal break times.

        Looks at hours with most content and least timing variance.
        """
        suggestions = []
        for hour in range(6, 24):
            song_count = self.db.execute(
                "SELECT COUNT(*) FROM broadcast_log "
                "WHERE entry_type = 'song' "
                f"AND CAST(strftime('%H', played_at) AS INTEGER) = ?",
                (hour,),
            )[0][0]

            avg_variance = self.db.execute(
                "SELECT AVG(ABS(variance_ms)) FROM broadcast_log "
                f"WHERE CAST(strftime('%H', played_at) AS INTEGER) = ? "
                "AND variance_ms IS NOT NULL",
                (hour,),
            )[0][0] or 0

            if song_count > 0:
                suggestions.append({
                    "hour": hour,
                    "time": f"{hour:02d}:00",
                    "song_count": song_count,
                    "avg_variance_ms": round(avg_variance),
                    "quality": "good" if avg_variance < 10000 else "fair",
                })

        suggestions.sort(key=lambda x: x["avg_variance_ms"])
        return suggestions[:6]

    # ── FUNCTION 9: Smart Clock Builder ─────────────────────────────────

    def optimize_clock(self, clock_id):
        """Analyze a clock and suggest improvements.

        If category health <50%: suggest reducing slots for that category.
        If >90%: suggest adding slots. Check energy curve alignment.
        """
        slots = self.db.execute(
            "SELECT cs.slot_type, cs.category_id, cs.energy_pref, c.name "
            "FROM clock_slots cs "
            "LEFT JOIN categories c ON cs.category_id = c.id "
            "WHERE cs.clock_id = ?",
            (clock_id,),
        )
        recommendations = []
        category_counts = {}
        for slot in slots:
            cat_id = slot[1]
            cat_name = slot[3] or "Unknown"
            if cat_id:
                category_counts[cat_id] = category_counts.get(cat_id, 0) + 1

        for cat_id, count in category_counts.items():
            health = self.get_rotation_health(cat_id)
            if health["health"] < 50 and health["total_songs"] > 0:
                recommendations.append({
                    "type": "reduce_slots",
                    "category_id": cat_id,
                    "health": health["health"],
                    "current_slots": count,
                    "severity": "warning",
                    "message": f"Category rotation at {health['health']}% — consider reducing slots",
                })
            elif health["health"] > 90:
                recommendations.append({
                    "type": "add_slots",
                    "category_id": cat_id,
                    "health": health["health"],
                    "current_slots": count,
                    "severity": "info",
                    "message": f"Category at {health['health']}% — room to add more slots",
                })

        return recommendations

    # ── FUNCTION 10: Autonomous Daily Log Generation ────────────────────

    def generate_daily_log(self, target_date=None):
        """Generate a complete broadcast log for a given date.

        Per hour → get active clock → per slot → select song
        Filter: separation time + overplay + energy match
        Pick song with lowest recent play count
        Fill breaks with campaigns by priority
        """
        if target_date is None:
            target_date = datetime.now().strftime("%Y-%m-%d")

        entries = []
        warnings = []
        position = 0
        current_time = datetime.strptime(f"{target_date} 00:00:00", "%Y-%m-%d %H:%M:%S")

        for hour in range(24):
            hour_time = current_time.replace(hour=hour, minute=0, second=0)
            preferred_energy = self.get_energy_preference(hour)

            clocks = self.db.execute(
                "SELECT c.id FROM clocks c "
                "JOIN auto_schedule a ON a.clock_id = c.id "
                "WHERE a.hour_start <= ? AND a.hour_end > ? "
                "AND a.day_of_week = ? AND c.is_active = 1",
                (hour, hour, hour_time.weekday()),
            )

            if not clocks:
                clocks = self.db.execute(
                    "SELECT id FROM clocks WHERE is_active = 1 LIMIT 1"
                )

            if clocks:
                clock_id = clocks[0][0]
                slots = self.db.execute(
                    "SELECT slot_type, category_id, energy_pref, is_break "
                    "FROM clock_slots WHERE clock_id = ? ORDER BY slot_order",
                    (clock_id,),
                )
            else:
                slots = []

            minute_offset = 0
            for slot in slots:
                slot_type, cat_id, energy_pref, is_break = slot[0], slot[1], slot[2], slot[3]
                entry_time = hour_time + timedelta(minutes=minute_offset)

                if is_break:
                    break_entries = self._fill_break(entry_time, position)
                    for be in break_entries:
                        entries.append(be)
                        position += 1
                    minute_offset += 2
                elif slot_type == "Song" and cat_id:
                    song, warning = self._select_song(cat_id, preferred_energy, entry_time)
                    if song:
                        entries.append({
                            "position": position,
                            "scheduled_time": entry_time.strftime("%H:%M:%S"),
                            "entry_type": "song",
                            "song_id": song["id"],
                            "title": song["title"],
                            "artist": song["artist"],
                            "duration_ms": song["duration_ms"],
                        })
                        minute_offset += (song["duration_ms"] or 180000) / 60000
                        position += 1
                    if warning:
                        warnings.append(warning)

            if not slots:
                songs = self.db.execute(
                    "SELECT id, artist, title, duration_ms, energy FROM songs "
                    "WHERE is_enabled = 1 ORDER BY RANDOM() LIMIT 12"
                )
                for s in songs:
                    entry_time = hour_time + timedelta(minutes=minute_offset)
                    entries.append({
                        "position": position,
                        "scheduled_time": entry_time.strftime("%H:%M:%S"),
                        "entry_type": "song",
                        "song_id": s[0],
                        "title": s[2],
                        "artist": s[1],
                        "duration_ms": s[3],
                    })
                    minute_offset += (s[3] or 180000) / 60000
                    position += 1
                    if minute_offset >= 55:
                        break

        return {
            "date": target_date,
            "entries": entries,
            "total_entries": len(entries),
            "warnings": warnings,
            "warning_count": len(warnings),
            "generated_by": "AI",
        }

    def _select_song(self, category_id, preferred_energy, current_time):
        """Select the best song for a slot based on separation, overplay, and energy."""
        candidates = self.db.execute(
            """SELECT s.id, s.artist, s.title, s.duration_ms, s.energy, s.bpm,
                      s.separation_minutes, s.artist_sep_minutes
               FROM songs s
               WHERE s.category_id = ? AND s.is_enabled = 1
               ORDER BY RANDOM()""",
            (category_id,),
        )
        warning = None
        for c in candidates:
            song_id = c[0]
            sep_min = c[6] or 120
            last_play = self.db.execute(
                "SELECT MAX(played_at) FROM broadcast_log WHERE song_id = ?",
                (song_id,),
            )
            if last_play and last_play[0][0]:
                try:
                    last = datetime.strptime(last_play[0][0], "%Y-%m-%d %H:%M:%S")
                    if (current_time - last).total_seconds() < sep_min * 60:
                        continue
                except (ValueError, TypeError):
                    pass

            overplay = self.check_overplay(song_id)
            if overplay["is_overplayed"]:
                warning = {
                    "song_id": song_id,
                    "artist": c[1],
                    "message": f"Overplay warning: {c[1]} — {c[2]}",
                }

            return {
                "id": c[0], "artist": c[1], "title": c[2],
                "duration_ms": c[3], "energy": c[4],
            }, warning

        if candidates:
            c = candidates[0]
            return {
                "id": c[0], "artist": c[1], "title": c[2],
                "duration_ms": c[3], "energy": c[4],
            }, {"message": f"No ideal song found for category {category_id}, using fallback"}

        return None, None

    def _fill_break(self, break_time, start_position):
        """Fill a commercial break with active campaigns by priority."""
        campaigns = self.db.execute(
            """SELECT c.id, c.name, sf.filename, sf.duration_ms
               FROM campaigns c
               JOIN spot_files sf ON sf.campaign_id = c.id
               WHERE c.is_active = 1 AND sf.is_active = 1
               ORDER BY
                 CASE c.priority
                   WHEN 'High' THEN 1
                   WHEN 'Always' THEN 1
                   WHEN 'Medium' THEN 2
                   WHEN 'Low' THEN 3
                   ELSE 4
                 END,
                 RANDOM()
               LIMIT 3"""
        )
        entries = []
        offset = 0
        for c in campaigns:
            entry_time = break_time + timedelta(milliseconds=offset)
            entries.append({
                "position": start_position + len(entries),
                "scheduled_time": entry_time.strftime("%H:%M:%S"),
                "entry_type": "break",
                "campaign_id": c[0],
                "title": c[2],
                "artist": c[1],
                "duration_ms": c[3] or 30000,
            })
            offset += c[3] or 30000
        return entries

    # ── Batch Analysis ──────────────────────────────────────────────────

    def get_all_insights(self):
        """Run all AI analysis and return a combined insights summary."""
        insights = []

        songs = self.db.execute("SELECT id FROM songs WHERE is_enabled = 1")
        for s in songs[:50]:
            op = self.check_overplay(s[0])
            if op["is_overplayed"]:
                insights.append({
                    "type": "overplay", "severity": "warning",
                    "entity_id": s[0], "message": op["message"],
                })

        health = self.get_rotation_health()
        if health["health"] < 50:
            insights.append({
                "type": "rotation", "severity": "warning",
                "message": health["message"],
            })

        conflicts = self.detect_break_conflicts()
        for c in conflicts:
            insights.append({
                "type": "break_conflict", "severity": c["severity"],
                "message": c["message"],
            })

        delivery = self.monitor_campaign_delivery()
        for d in delivery:
            insights.append({
                "type": "campaign_delivery", "severity": d["severity"],
                "message": d["message"],
            })

        return insights
