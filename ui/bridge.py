"""RadioAI Studio Pro — Python-JS Bridge

Every method returns JSON: {"success": true, "data": ...} or {"success": false, "error": "..."}
"""

import json
import os
import shutil
import hashlib
from datetime import datetime
from PyQt6.QtCore import QObject, pyqtSlot, pyqtSignal
from PyQt6.QtWidgets import QFileDialog
from core.database import DatabaseManager
from models.song import Song, Category


def _ok(data):
    return json.dumps({"success": True, "data": data})


def _err(e):
    return json.dumps({"success": False, "error": str(e)})


def _ms_to_str(ms):
    if not ms or ms < 0:
        return "—"
    total = int(ms) // 1000
    return f"{total // 60}:{total % 60:02d}"


def _scan_one_file(file_path):
    """Probe a single audio file with mutagen and return row dict."""
    filename = os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].lower()
    artist = ""
    title = ""
    album = ""
    year = ""
    bpm = 0
    duration_ms = 0
    status = "Ready"
    error_msg = ""

    try:
        if ext == ".mp3":
            from mutagen.mp3 import MP3
            from mutagen.id3 import ID3, ID3NoHeaderError
            audio = MP3(file_path)
            duration_ms = int((audio.info.length or 0) * 1000)
            try:
                tags = ID3(file_path)
                if tags.get("TPE1"):
                    artist = str(tags.get("TPE1"))
                if tags.get("TIT2"):
                    title = str(tags.get("TIT2"))
                if tags.get("TALB"):
                    album = str(tags.get("TALB"))
                if tags.get("TDRC"):
                    year = str(tags.get("TDRC"))
                if tags.get("TBPM"):
                    try:
                        bpm = int(float(str(tags.get("TBPM"))))
                    except Exception:
                        bpm = 0
            except ID3NoHeaderError:
                status = "No Tags"
            except Exception:
                status = "No Tags"

        elif ext == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(file_path)
            duration_ms = int((audio.info.length or 0) * 1000)
            artist = ", ".join(audio.get("artist", []) or [])
            title = ", ".join(audio.get("title", []) or [])
            album = ", ".join(audio.get("album", []) or [])
            yr = audio.get("date", []) or []
            if yr:
                year = str(yr[0])
            bp = audio.get("bpm", []) or []
            if bp:
                try:
                    bpm = int(float(str(bp[0])))
                except Exception:
                    bpm = 0

        elif ext == ".wav":
            import wave
            with wave.open(file_path, "rb") as w:
                frames = w.getnframes()
                rate = w.getframerate() or 1
                duration_ms = int(frames / rate * 1000)
            status = "No Tags"

        elif ext in (".m4a", ".ogg", ".aac", ".wma"):
            # Use mutagen for any other format it supports
            try:
                from mutagen import File as MutagenFile
                mf = MutagenFile(file_path)
                if mf and mf.info:
                    duration_ms = int((mf.info.length or 0) * 1000)
                    # Try common tag fields
                    if hasattr(mf, 'tags') and mf.tags:
                        for tag_key in ('\xa9ART', 'artist', 'ARTIST', 'TPE1'):
                            v = mf.tags.get(tag_key)
                            if v:
                                artist = str(v[0]) if isinstance(v, list) else str(v)
                                break
                        for tag_key in ('\xa9nam', 'title', 'TITLE', 'TIT2'):
                            v = mf.tags.get(tag_key)
                            if v:
                                title = str(v[0]) if isinstance(v, list) else str(v)
                                break
                        for tag_key in ('\xa9alb', 'album', 'ALBUM', 'TALB'):
                            v = mf.tags.get(tag_key)
                            if v:
                                album = str(v[0]) if isinstance(v, list) else str(v)
                                break
                    if not artist and not title:
                        status = "No Tags"
                else:
                    status = "No Tags"
            except Exception:
                status = "No Tags"

        else:
            status = "Error"
            error_msg = f"Unsupported extension: {ext}"

        # Fallback parse from filename
        if not artist and not title:
            name = os.path.splitext(filename)[0]
            parts = name.replace("_", " ")
            if " - " in parts:
                a, t = parts.split(" - ", 1)
                artist = a.strip()
                title = t.strip()
            else:
                title = parts.strip()
            if status == "Ready":
                status = "No Tags"

    except Exception as e:
        status = "Error"
        error_msg = str(e)

    return {
        "file_path": file_path,
        "filename": filename,
        "artist": artist,
        "title": title,
        "album": album,
        "year": year,
        "bpm": bpm,
        "duration": _ms_to_str(duration_ms) if duration_ms > 0 else "—",
        "duration_ms": duration_ms,
        "status": status,
        "error": error_msg,
        "selected": status in ("Ready", "No Tags"),
    }


class Bridge(QObject):

    library_requested = pyqtSignal(str)
    studio_requested = pyqtSignal()
    studio_close_requested = pyqtSignal()
    navigate_requested = pyqtSignal(str)
    break_started = pyqtSignal(str)         # JSON-encoded list of spots
    break_ended = pyqtSignal()              # legacy — kept for any listeners
    crossfade_complete = pyqtSignal(str)    # new — deck letter that is now active

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = DatabaseManager()
        self._audio = None
        self._scheduler = None
        self._last_break_spots = []
        # Eagerly start the break scheduler so breaks fire even when
        # the user is on other screens. This also initialises the audio
        # engine as a side effect.
        try:
            _ = self.scheduler
        except Exception as e:
            print(f"[bridge] scheduler startup failed: {e}")

    # ── Audio engine (lazy init) ────────────────────────────────────────

    @property
    def audio(self):
        if self._audio is None:
            from core.audio_engine import AudioEngine
            self._audio = AudioEngine()
        return self._audio

    # ── Break scheduler (lazy init, notification-only) ──────────────────

    @property
    def scheduler(self):
        if self._scheduler is None:
            from core.break_scheduler import BreakScheduler
            self._scheduler = BreakScheduler(self.db)
            self._scheduler.on_break_due = self._on_break_due
            self._scheduler.start()
        return self._scheduler

    def _on_break_due(self, spots):
        """Scheduler fired — emit the full spot list to the Studio UI.

        The Studio JS subscribes to `break_started` via QWebChannel and
        plays the spots on the active deck, then crossfades back to
        music when done.
        """
        try:
            self._last_break_spots = spots
            payload = json.dumps([{
                "campaign": s.get("campaign_name", ""),
                "campaign_id": s.get("campaign_id"),
                "filename": s.get("filename", ""),
                "file_path": s.get("file_path", ""),
                "duration_ms": s.get("duration_ms", 0),
                "priority": s.get("priority", ""),
            } for s in spots])
            self.break_started.emit(payload)
        except Exception as e:
            print(f"[bridge] _on_break_due error: {e}")

    # ── Navigation (void — no return) ───────────────────────────────────

    @pyqtSlot(str)
    def open_library(self, key):
        self.library_requested.emit(key)

    @pyqtSlot()
    def open_studio(self):
        self.studio_requested.emit()

    @pyqtSlot()
    def close_studio(self):
        """Called by Studio JS goBack() — hides the Studio window without
        tearing down VLC decks or JS state."""
        self.studio_close_requested.emit()

    @pyqtSlot(str)
    def navigate(self, page):
        self.navigate_requested.emit(page)

    # ── Settings ────────────────────────────────────────────────────────

    @pyqtSlot(result=str)
    def get_stats(self):
        try:
            return _ok(self.db.get_stats())
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_all_settings(self):
        try:
            rows = self.db.execute("SELECT key, value FROM settings")
            return _ok({r[0]: r[1] for r in rows})
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, str, result=str)
    def save_setting(self, key, value):
        try:
            self.db.set_setting(key, str(value))
            return _ok(True)
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def save_all_settings(self, settings_json):
        try:
            settings = json.loads(settings_json)
            for key, value in settings.items():
                self.db.set_setting(key, str(value))
            return _ok({"saved": len(settings)})
        except Exception as e:
            return _err(e)

    # ── Songs ───────────────────────────────────────────────────────────

    @pyqtSlot(str, result=str)
    def search_artists(self, query):
        try:
            rows = self.db.execute(
                "SELECT DISTINCT artist FROM songs WHERE artist LIKE ? ORDER BY artist LIMIT 10",
                (f"%{query}%",)
            )
            return _ok([r[0] for r in rows])
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def get_songs(self, filters_json="{}"):
        try:
            filters = json.loads(filters_json) if filters_json else {}
            songs = Song.all(self.db, filters if filters else None)
            return _ok([s.to_dict() for s in songs])
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_categories(self):
        try:
            return _ok([c.to_dict() for c in Category.all(self.db)])
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_categories_full(self):
        try:
            rows = self.db.execute(
                "SELECT c.id, c.name, c.color, c.description, c.auto_rotate, c.separation_min, "
                "COUNT(s.id) as song_count FROM categories c "
                "LEFT JOIN songs s ON s.category_id = c.id "
                "GROUP BY c.id ORDER BY c.display_order, c.name"
            )
            return _ok([{"id": r[0], "name": r[1], "color": r[2] or "#8B5CF6",
                          "description": r[3] or "", "auto_rotate": r[4] or "",
                          "separation_min": r[5] or 120, "song_count": r[6]} for r in rows])
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def save_category(self, cat_json):
        try:
            c = json.loads(cat_json)
            if not c.get("name"):
                return _err("Category name required")
            if c.get("id"):
                self.db.execute(
                    "UPDATE categories SET name=?, color=?, description=?, auto_rotate=?, separation_min=? WHERE id=?",
                    (c["name"], c.get("color", "#8B5CF6"), c.get("description", ""),
                     c.get("auto_rotate", ""), c.get("separation_min", 120), c["id"]))
                return _ok("Category updated")
            else:
                uid = self.db.execute_insert(
                    "INSERT INTO categories (name, color, description, auto_rotate, separation_min) VALUES (?,?,?,?,?)",
                    (c["name"], c.get("color", "#8B5CF6"), c.get("description", ""),
                     c.get("auto_rotate", ""), c.get("separation_min", 120)))
                return _ok({"id": uid, "message": "Category created"})
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def delete_category(self, cat_id):
        try:
            rows = self.db.execute("SELECT COUNT(*) FROM songs WHERE category_id=?", (cat_id,))
            count = rows[0][0] if rows else 0
            if count > 0:
                return _err(f"Cannot delete — {count} songs use this category. Move songs first.")
            self.db.execute("DELETE FROM categories WHERE id=?", (cat_id,))
            return _ok("Category deleted")
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def get_songs_in_category(self, cat_id):
        try:
            rows = self.db.execute(
                "SELECT id, artist, title FROM songs WHERE category_id=? ORDER BY artist LIMIT 20",
                (cat_id,))
            return _ok([{"id": r[0], "artist": r[1], "title": r[2]} for r in rows])
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def add_song(self, song_json):
        try:
            s = json.loads(song_json)
            if not s.get("artist"):
                return _err("Artist is required")
            if not s.get("title"):
                return _err("Song title is required")
            # Generate auto_code
            rows = self.db.execute("SELECT MAX(auto_code) FROM songs")
            next_code = (rows[0][0] or 300000) + 1
            uid = self.db.execute_insert(
                "INSERT INTO songs (artist, title, album, playlister_code, label, cd_key, barcode, "
                "songwriter, composer, comments, category_id, era, vocal, priority, year, bpm, "
                "file_path, is_enabled, is_frozen, auto_code) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (s["artist"], s["title"], s.get("album",""), s.get("playlister_code",""),
                 s.get("label",""), s.get("cd_key",""), s.get("barcode",""),
                 s.get("songwriter",""), s.get("composer",""), s.get("comments",""),
                 s.get("category_id"), s.get("era"), s.get("vocal"),
                 int(s.get("priority",1)), s.get("year"), s.get("bpm"),
                 s.get("file_path",""), 1 if s.get("is_enabled",True) else 0,
                 1 if s.get("is_frozen",False) else 0, next_code))
            return _ok({"id": uid, "auto_code": next_code})
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def update_song(self, song_json):
        try:
            s = json.loads(song_json)
            sid = s.get("id")
            if not sid:
                return _err("Song ID required")
            if not s.get("artist"):
                return _err("Artist is required")
            if not s.get("title"):
                return _err("Song title is required")
            self.db.execute(
                "UPDATE songs SET artist=?, title=?, album=?, playlister_code=?, label=?, "
                "cd_key=?, barcode=?, songwriter=?, composer=?, comments=?, category_id=?, "
                "era=?, vocal=?, priority=?, year=?, bpm=?, file_path=?, is_enabled=?, is_frozen=? "
                "WHERE id=?",
                (s["artist"], s["title"], s.get("album",""), s.get("playlister_code",""),
                 s.get("label",""), s.get("cd_key",""), s.get("barcode",""),
                 s.get("songwriter",""), s.get("composer",""), s.get("comments",""),
                 s.get("category_id"), s.get("era"), s.get("vocal"),
                 int(s.get("priority",1)), s.get("year"), s.get("bpm"),
                 s.get("file_path",""), 1 if s.get("is_enabled",True) else 0,
                 1 if s.get("is_frozen",False) else 0, sid))
            return _ok({"id": sid, "message": "Song updated"})
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def delete_song(self, song_id):
        try:
            self.db.execute("DELETE FROM songs WHERE id=?", (song_id,))
            return _ok("Song deleted")
        except Exception as e:
            return _err(e)

    # ── Spots & Commercials ─────────────────────────────────────────────

    @pyqtSlot(str, result=str)
    def get_campaigns(self, filters_json="{}"):
        try:
            filters = json.loads(filters_json) if filters_json else {}
            query = (
                "SELECT c.id, c.name, c.category, c.priority, c.start_date, c.end_date, "
                "c.is_active, c.programming_mode, c.playback_order, COUNT(sf.id) as spot_count "
                "FROM campaigns c LEFT JOIN spot_files sf ON sf.campaign_id = c.id WHERE 1=1"
            )
            params = []
            status = filters.get("status")
            if status == "active":
                query += " AND c.is_active = 1"
            elif status == "expired":
                query += " AND c.is_active = 0"
            cat = filters.get("category")
            if cat and cat != "all":
                query += " AND c.category = ?"
                params.append(cat)
            prio = filters.get("priority")
            if prio and prio != "all":
                query += " AND c.priority = ?"
                params.append(prio)
            query += " GROUP BY c.id ORDER BY c.id"
            rows = self.db.execute(query, tuple(params))
            campaigns = [{
                "id": r[0], "name": r[1], "category": r[2] or "",
                "priority": r[3] or "", "start_date": r[4] or "",
                "end_date": r[5] or "", "is_active": bool(r[6]),
                "programming_mode": r[7] or "", "playback_order": r[8] or "",
                "spot_count": r[9] or 0
            } for r in rows]
            return _ok({"campaigns": campaigns, "total": len(campaigns)})
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def get_campaign_details(self, campaign_id):
        try:
            rows = self.db.execute(
                "SELECT id, name, description, category, priority, programming_mode, "
                "playback_order, start_date, end_date, contracted_plays_per_day, is_active "
                "FROM campaigns WHERE id=?", (campaign_id,))
            if not rows:
                return _err("Campaign not found")
            r = rows[0]
            campaign = {
                "id": r[0], "name": r[1], "description": r[2] or "",
                "category": r[3] or "", "priority": r[4] or "",
                "programming_mode": r[5] or "", "playback_order": r[6] or "",
                "start_date": r[7] or "", "end_date": r[8] or "",
                "contracted_plays_per_day": r[9] or 0, "is_active": bool(r[10])
            }
            # Spot files
            spots = self.db.execute(
                "SELECT id, filename, file_path, duration_ms, is_active "
                "FROM spot_files WHERE campaign_id=? ORDER BY display_order, id",
                (campaign_id,))
            campaign["spot_files"] = [{
                "id": s[0], "filename": s[1], "file_path": s[2] or "",
                "duration_ms": s[3] or 0, "is_active": bool(s[4])
            } for s in spots]
            # Schedule via campaign_schedule
            sched = self.db.execute(
                "SELECT day_of_week, break_time FROM campaign_schedule "
                "WHERE campaign_id=? ORDER BY day_of_week, break_time",
                (campaign_id,))
            campaign["break_schedule"] = [{"day": s[0], "time": s[1]} for s in sched]
            return _ok(campaign)
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def save_campaign(self, campaign_json):
        try:
            c = json.loads(campaign_json)
            if not c.get("name"):
                return _err("Campaign name required")
            cid = c.get("id")
            if cid:
                self.db.execute(
                    "UPDATE campaigns SET name=?, category=?, priority=?, start_date=?, "
                    "end_date=?, is_active=?, programming_mode=?, playback_order=?, description=? "
                    "WHERE id=?",
                    (c["name"], c.get("category", "Commercials"), c.get("priority", "Medium"),
                     c.get("start_date", ""), c.get("end_date", ""),
                     1 if c.get("is_active", True) else 0,
                     c.get("programming_mode", "Weekly"), c.get("playback_order", "In Rotation"),
                     c.get("description", ""), cid))
                return _ok({"id": cid, "message": "Campaign updated"})
            else:
                cid = self.db.execute_insert(
                    "INSERT INTO campaigns (name, category, priority, start_date, end_date, "
                    "is_active, programming_mode, playback_order, description) "
                    "VALUES (?,?,?,?,?,1,?,?,?)",
                    (c["name"], c.get("category", "Commercials"), c.get("priority", "Medium"),
                     c.get("start_date", ""), c.get("end_date", "Never"),
                     c.get("programming_mode", "Weekly"), c.get("playback_order", "In Rotation"),
                     c.get("description", "")))
                return _ok({"id": cid, "message": "Campaign created"})
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def delete_campaign(self, campaign_id):
        try:
            rows = self.db.execute("SELECT name FROM campaigns WHERE id=?", (campaign_id,))
            if not rows:
                return _err("Campaign not found")
            name = rows[0][0]
            self.db.execute("DELETE FROM spot_files WHERE campaign_id=?", (campaign_id,))
            self.db.execute("DELETE FROM campaign_schedule WHERE campaign_id=?", (campaign_id,))
            self.db.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
            return _ok(f"Deleted: {name}")
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def add_spot_file(self, spot_json):
        try:
            s = json.loads(spot_json)
            if not s.get("campaign_id"):
                return _err("Campaign ID required")
            if not s.get("filename"):
                return _err("Filename required")
            sid = self.db.execute_insert(
                "INSERT INTO spot_files (campaign_id, filename, file_path, duration_ms, is_active) "
                "VALUES (?,?,?,?,1)",
                (int(s["campaign_id"]), s["filename"], s.get("file_path", ""),
                 int(s.get("duration_ms", 30000))))
            return _ok({"id": sid, "message": "Spot file added"})
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def delete_spot_file(self, spot_id):
        try:
            self.db.execute("DELETE FROM spot_files WHERE id=?", (spot_id,))
            return _ok("Spot file deleted")
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def save_break_schedule(self, schedule_json):
        try:
            data = json.loads(schedule_json)
            campaign_id = data.get("campaign_id")
            schedule = data.get("schedule", [])
            if not campaign_id:
                return _err("Campaign ID required")
            # Clear existing
            self.db.execute("DELETE FROM campaign_schedule WHERE campaign_id=?", (campaign_id,))
            # Insert new slots
            for slot in schedule:
                self.db.execute(
                    "INSERT INTO campaign_schedule (campaign_id, day_of_week, break_time) VALUES (?,?,?)",
                    (int(campaign_id), int(slot["day"]), slot["time"]))
            return _ok({"saved": len(schedule), "message": f"Saved {len(schedule)} slots"})
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def get_break_schedule(self, campaign_id):
        try:
            rows = self.db.execute(
                "SELECT day_of_week, break_time FROM campaign_schedule WHERE campaign_id=? "
                "ORDER BY day_of_week, break_time", (campaign_id,))
            return _ok([{"day": r[0], "time": r[1]} for r in rows])
        except Exception as e:
            return _err(e)

    # ── Jingles ─────────────────────────────────────────────────────────

    @pyqtSlot(str, result=str)
    def get_jingles(self, filters_json="{}"):
        try:
            filters = json.loads(filters_json) if filters_json else {}
            query = (
                "SELECT id, name, category, duration_ms, properties, is_enabled, "
                "playlister_code, file_path, display_order FROM jingles WHERE 1=1"
            )
            params = []
            search = (filters.get("search") or "").strip()
            if search:
                query += " AND (name LIKE ? OR category LIKE ?)"
                params.extend([f"%{search}%", f"%{search}%"])
            cat = filters.get("category")
            if cat and cat != "all":
                query += " AND category = ?"
                params.append(cat)
            if filters.get("only_enabled"):
                query += " AND is_enabled = 1"
            query += " ORDER BY display_order, name"
            rows = self.db.execute(query, tuple(params))

            jingles = []
            for r in rows:
                dur_ms = r[3] or 0
                sec = dur_ms // 1000
                dur_str = f"{sec // 60}:{sec % 60:02d}"
                jingles.append({
                    "id": r[0], "name": r[1] or "", "category": r[2] or "",
                    "duration_ms": dur_ms, "duration": dur_str,
                    "properties": r[4] or "Regular",
                    "is_enabled": bool(r[5]),
                    "playlister_code": r[6] or "",
                    "file_path": r[7] or "",
                    "last_used": "Never",
                    "comments": ""
                })
            return _ok({"jingles": jingles, "total": len(jingles)})
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def save_jingle(self, jingle_json):
        try:
            j = json.loads(jingle_json)
            if not j.get("name"):
                return _err("Jingle name required")
            # Convert "0:05" to ms
            dur_str = j.get("duration", "0:05")
            try:
                parts = str(dur_str).split(":")
                dur_ms = (int(parts[0]) * 60 + int(parts[1])) * 1000
            except Exception:
                dur_ms = j.get("duration_ms", 5000)
            jid = j.get("id")
            if jid:
                self.db.execute(
                    "UPDATE jingles SET name=?, category=?, duration_ms=?, properties=?, "
                    "playlister_code=?, file_path=?, is_enabled=? WHERE id=?",
                    (j["name"], j.get("category", "Station ID"), dur_ms,
                     j.get("properties", "Regular"), j.get("playlister_code", ""),
                     j.get("file_path", ""), 1 if j.get("is_enabled", True) else 0, jid))
                return _ok({"id": jid, "message": "Jingle updated"})
            else:
                # Auto-generate playlister code J####
                if not j.get("playlister_code"):
                    rows = self.db.execute("SELECT MAX(id) FROM jingles")
                    next_num = (rows[0][0] or 0) + 1
                    j["playlister_code"] = f"J{next_num:04d}"
                jid = self.db.execute_insert(
                    "INSERT INTO jingles (name, category, duration_ms, properties, "
                    "playlister_code, file_path, is_enabled) VALUES (?,?,?,?,?,?,1)",
                    (j["name"], j.get("category", "Station ID"), dur_ms,
                     j.get("properties", "Regular"), j["playlister_code"], j.get("file_path", "")))
                return _ok({"id": jid, "playlister_code": j["playlister_code"], "message": "Jingle created"})
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def get_jingle(self, jingle_id):
        try:
            rows = self.db.execute(
                "SELECT id, name, category, duration_ms, properties, is_enabled, "
                "playlister_code, file_path FROM jingles WHERE id=?", (jingle_id,))
            if not rows:
                return _err("Jingle not found")
            r = rows[0]
            dur_ms = r[3] or 0
            sec = dur_ms // 1000
            return _ok({
                "id": r[0], "name": r[1] or "", "category": r[2] or "",
                "duration_ms": dur_ms, "duration": f"{sec // 60}:{sec % 60:02d}",
                "properties": r[4] or "Regular", "is_enabled": bool(r[5]),
                "playlister_code": r[6] or "", "file_path": r[7] or "",
            })
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def delete_jingle(self, jingle_id):
        try:
            rows = self.db.execute("SELECT name FROM jingles WHERE id=?", (jingle_id,))
            if not rows:
                return _err("Jingle not found")
            name = rows[0][0]
            self.db.execute("DELETE FROM jingles WHERE id=?", (jingle_id,))
            return _ok(f"Deleted: {name}")
        except Exception as e:
            return _err(e)

    # ── Sweepers ────────────────────────────────────────────────────────

    @pyqtSlot(str, result=str)
    def get_sweepers(self, filters_json="{}"):
        try:
            filters = json.loads(filters_json) if filters_json else {}
            query = (
                "SELECT id, name, category, duration_ms, position, properties, is_enabled, "
                "playlister_code, file_path, comments, song_volume, sweeper_volume, "
                "position_offset, fade_duration FROM sweepers WHERE 1=1"
            )
            params = []
            search = (filters.get("search") or "").strip()
            if search:
                query += " AND name LIKE ?"
                params.append(f"%{search}%")
            pos = filters.get("position")
            if pos and pos != "all":
                query += " AND position = ?"
                params.append(pos)
            cat = filters.get("category")
            if cat and cat != "all":
                query += " AND category = ?"
                params.append(cat)
            query += " ORDER BY name"
            rows = self.db.execute(query, tuple(params))

            sweepers = []
            for r in rows:
                dur_ms = r[3] or 0
                sec = dur_ms // 1000
                sweepers.append({
                    "id": r[0], "name": r[1] or "", "category": r[2] or "",
                    "duration_ms": dur_ms, "duration": f"{sec // 60}:{sec % 60:02d}",
                    "position": r[4] or "Bridge at End",
                    "properties": r[5] or "Regular",
                    "is_enabled": bool(r[6]),
                    "playlister_code": r[7] or "",
                    "file_path": r[8] or "",
                    "comments": r[9] or "",
                    "song_volume": r[10] if r[10] is not None else 60,
                    "sweeper_volume": r[11] if r[11] is not None else 100,
                    "position_offset": r[12] if r[12] is not None else 0.0,
                    "fade_duration": r[13] if r[13] is not None else 0.5,
                    "last_used": "Never"
                })
            return _ok({"sweepers": sweepers, "total": len(sweepers)})
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def get_sweeper(self, sweeper_id):
        try:
            r = self.db.execute(
                "SELECT id, name, category, duration_ms, position, properties, is_enabled, "
                "playlister_code, file_path, comments, song_volume, sweeper_volume, "
                "position_offset, fade_duration FROM sweepers WHERE id=?", (sweeper_id,))
            if not r:
                return _err("Sweeper not found")
            r = r[0]
            dur_ms = r[3] or 0
            sec = dur_ms // 1000
            return _ok({
                "id": r[0], "name": r[1] or "", "category": r[2] or "",
                "duration_ms": dur_ms, "duration": f"{sec // 60}:{sec % 60:02d}",
                "position": r[4] or "Bridge at End", "properties": r[5] or "Regular",
                "is_enabled": bool(r[6]), "playlister_code": r[7] or "",
                "file_path": r[8] or "", "comments": r[9] or "",
                "song_volume": r[10] if r[10] is not None else 60,
                "sweeper_volume": r[11] if r[11] is not None else 100,
                "position_offset": r[12] if r[12] is not None else 0.0,
                "fade_duration": r[13] if r[13] is not None else 0.5,
            })
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def save_sweeper(self, sweeper_json):
        try:
            s = json.loads(sweeper_json)
            if not s.get("name"):
                return _err("Sweeper name required")
            dur_str = s.get("duration", "0:08")
            try:
                parts = str(dur_str).split(":")
                dur_ms = (int(parts[0]) * 60 + int(parts[1])) * 1000
            except Exception:
                dur_ms = s.get("duration_ms", 8000)
            sid = s.get("id")
            # Safely coerce nullable numeric fields — the JS form can
            # send null when a slider hasn't been touched or the DB row
            # has NULL from an older schema.  int(None) / float(None)
            # throws TypeError, which was the "Failed to save" bug.
            song_vol = int(s.get("song_volume") or 60)
            swpr_vol = int(s.get("sweeper_volume") or 100)
            pos_off = float(s.get("position_offset") or 0.0)
            fade_d = float(s.get("fade_duration") or 0.5)

            if sid:
                self.db.execute(
                    "UPDATE sweepers SET name=?, category=?, duration_ms=?, position=?, "
                    "properties=?, playlister_code=?, file_path=?, comments=?, is_enabled=?, "
                    "song_volume=?, sweeper_volume=?, position_offset=?, fade_duration=? WHERE id=?",
                    (s["name"], s.get("category") or "Station", dur_ms,
                     s.get("position") or "Bridge at End", s.get("properties") or "Regular",
                     s.get("playlister_code") or "", s.get("file_path") or "",
                     s.get("comments") or "",
                     1 if s.get("is_enabled", True) else 0,
                     song_vol, swpr_vol, pos_off, fade_d,
                     sid))
                return _ok({"id": sid, "message": "Sweeper updated"})
            else:
                if not s.get("playlister_code"):
                    rows = self.db.execute("SELECT MAX(id) FROM sweepers")
                    next_num = (rows[0][0] or 0) + 1
                    s["playlister_code"] = f"SW-{next_num:04d}"
                sid = self.db.execute_insert(
                    "INSERT INTO sweepers (name, category, duration_ms, position, properties, "
                    "playlister_code, file_path, comments, is_enabled, song_volume, sweeper_volume, "
                    "position_offset, fade_duration) VALUES (?,?,?,?,?,?,?,?,1,?,?,?,?)",
                    (s["name"], s.get("category") or "Station", dur_ms,
                     s.get("position") or "Bridge at End", s.get("properties") or "Regular",
                     s["playlister_code"], s.get("file_path") or "",
                     s.get("comments") or "",
                     song_vol, swpr_vol, pos_off, fade_d))
                return _ok({"id": sid, "playlister_code": s["playlister_code"], "message": "Sweeper created"})
        except Exception as e:
            return _err(e)

    # ── The Stitcher ────────────────────────────────────────────────────

    @pyqtSlot(result=str)
    def get_stitcher_config(self):
        try:
            keys = [
                "stitcher_hooks_enabled", "stitcher_opening_audio",
                "stitcher_separator_audio", "stitcher_closing_audio",
                "stitcher_fallback_audio", "stitcher_min_hooks",
                "stitcher_max_hooks", "stitcher_hook_duration", "stitcher_trigger",
                "stitcher_rta_enabled", "stitcher_rta_hours_folder",
                "stitcher_rta_minutes_folder", "stitcher_rta_trigger", "stitcher_rta_format",
                "stitcher_news_enabled", "stitcher_news_opening",
                "stitcher_news_bed", "stitcher_news_closing",
                "stitcher_news_voiceover_folder", "stitcher_news_trim_bed",
            ]
            config = {k: self.db.get_setting(k) for k in keys}
            return _ok(config)
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def save_stitcher_config(self, config_json):
        try:
            config = json.loads(config_json)
            for k, v in config.items():
                self.db.set_setting(str(k), str(v) if v is not None else "")
            return _ok({"saved": len(config), "message": "Stitcher config saved!"})
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_songs_with_hooks(self):
        try:
            rows = self.db.execute(
                "SELECT s.id, s.artist, s.title, s.hook_in_ms, s.hook_out_ms, "
                "s.duration_ms, c.name "
                "FROM songs s LEFT JOIN categories c ON s.category_id = c.id "
                "WHERE s.hook_in_ms IS NOT NULL AND s.hook_in_ms > 0 "
                "AND s.hook_out_ms IS NOT NULL AND s.hook_out_ms > 0 "
                "ORDER BY s.artist, s.title")
            def ms_to_str(ms):
                if not ms:
                    return "0:00"
                s = int(ms) // 1000
                return f"{s // 60}:{s % 60:02d}"
            return _ok([{
                "id": r[0], "artist": r[1] or "", "title": r[2] or "",
                "hook_in": ms_to_str(r[3]), "hook_out": ms_to_str(r[4]),
                "hook_display": f"{ms_to_str(r[3])} - {ms_to_str(r[4])}",
                "duration_ms": r[5] or 0,
                "category": r[6] or ""
            } for r in rows])
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_songs_without_hooks(self):
        try:
            rows = self.db.execute(
                "SELECT s.id, s.artist, s.title, c.name "
                "FROM songs s LEFT JOIN categories c ON s.category_id = c.id "
                "WHERE s.hook_in_ms IS NULL OR s.hook_in_ms = 0 "
                "OR s.hook_out_ms IS NULL OR s.hook_out_ms = 0 "
                "ORDER BY s.artist, s.title LIMIT 50")
            return _ok([{
                "id": r[0], "artist": r[1] or "", "title": r[2] or "",
                "category": r[3] or ""
            } for r in rows])
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, str, str, result=str)
    def set_song_hook(self, song_id, hook_in, hook_out):
        try:
            def str_to_ms(s):
                s = (s or "").strip()
                if not s:
                    return 0
                parts = s.split(":")
                if len(parts) == 2:
                    return (int(parts[0]) * 60 + int(parts[1])) * 1000
                return int(float(s) * 1000)
            hin = str_to_ms(hook_in)
            hout = str_to_ms(hook_out)
            self.db.execute(
                "UPDATE songs SET hook_in_ms=?, hook_out_ms=? WHERE id=?",
                (hin, hout, song_id))
            return _ok({"hook_in": hook_in, "hook_out": hook_out, "message": "Hook saved"})
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def browse_audio_folder(self):
        try:
            folder = QFileDialog.getExistingDirectory(None, "Select Audio Folder", "")
            return _ok(folder.replace("/", "\\") if folder else "")
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def delete_sweeper(self, sweeper_id):
        try:
            rows = self.db.execute("SELECT name FROM sweepers WHERE id=?", (sweeper_id,))
            if not rows:
                return _err("Sweeper not found")
            name = rows[0][0]
            self.db.execute("DELETE FROM sweepers WHERE id=?", (sweeper_id,))
            return _ok(f"Deleted: {name}")
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_jingle_categories(self):
        try:
            rows = self.db.execute(
                "SELECT DISTINCT category FROM jingles WHERE category IS NOT NULL ORDER BY category")
            existing = [r[0] for r in rows if r[0]]
            defaults = ["Station ID", "Shotguns", "Ad Break", "News Break",
                        "Weather", "Traffic", "Promo", "Signature"]
            all_cats = sorted(set(defaults + existing))
            return _ok(all_cats)
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def browse_audio_file(self):
        try:
            path, _ = QFileDialog.getOpenFileName(
                None, "Select Audio File", "",
                "Audio Files (*.mp3 *.wav *.flac *.ogg *.m4a *.aac);;All Files (*)")
            return _ok(path.replace("/", "\\") if path else "")
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def get_song_details(self, song_id):
        try:
            song = Song.get(self.db, song_id)
            if not song:
                return _err("Song not found")
            d = song.to_dict()
            d["play_stats"] = Song.get_play_stats(self.db, song_id)
            return _ok(d)
        except Exception as e:
            return _err(e)

    # ── File Dialogs ────────────────────────────────────────────────────

    @pyqtSlot(result=str)
    def browse_folder(self):
        try:
            folder = QFileDialog.getExistingDirectory(None, "Select Folder")
            if folder:
                os.makedirs(folder, exist_ok=True)
                return _ok(folder.replace("/", "\\"))
            return _ok("")
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def browse_file(self):
        try:
            path, _ = QFileDialog.getOpenFileName(
                None, "Select File", "", "Database Files (*.db);;All Files (*)"
            )
            return _ok(path.replace("/", "\\") if path else "")
        except Exception as e:
            return _err(e)

    # ── Database ────────────────────────────────────────────────────────

    @pyqtSlot(result=str)
    def get_db_stats(self):
        try:
            db_path = self.db.db_path
            size_bytes = os.path.getsize(db_path) if os.path.exists(db_path) else 0
            tables = ["songs", "campaigns", "jingles", "sweepers", "categories",
                      "clocks", "playlists", "broadcast_log", "users", "settings"]
            counts = {}
            total = 0
            for t in tables:
                try:
                    rows = self.db.execute(f"SELECT COUNT(*) FROM {t}")
                    counts[t] = rows[0][0]
                    total += rows[0][0]
                except Exception:
                    counts[t] = 0
            return _ok({
                "path": db_path.replace("/", "\\"),
                "size_mb": round(size_bytes / (1024 * 1024), 2),
                "total_records": total,
                "table_counts": counts,
                "last_backup": self.db.get_setting("last_backup_time", "Never"),
            })
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def check_integrity(self):
        try:
            rows = self.db.execute("PRAGMA integrity_check")
            result = rows[0][0] if rows else "unknown"
            return _ok({"result": result, "passed": result == "ok"})
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def backup_database(self):
        try:
            db_path = self.db.db_path
            backup_dir = self.db.get_setting("backup_destination",
                os.path.join(os.path.dirname(db_path), "Backups"))
            os.makedirs(backup_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            backup_path = os.path.join(backup_dir, f"radioai_backup_{ts}.db")
            shutil.copy2(db_path, backup_path)
            self.db.set_setting("last_backup_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            return _ok({"path": backup_path.replace("/", "\\"),
                         "size_mb": round(os.path.getsize(backup_path) / (1024*1024), 2)})
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def reset_database(self):
        try:
            from core.database import SCHEMA_SQL
            db_path = self.db.db_path
            # Backup first
            backup_dir = os.path.join(os.path.dirname(db_path), "Backups")
            os.makedirs(backup_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            shutil.copy2(db_path, os.path.join(backup_dir, f"pre_reset_{ts}.db"))
            # Drop all tables and recreate
            tables = self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            for t in tables:
                if t[0] != "sqlite_sequence":
                    self.db.execute(f"DROP TABLE IF EXISTS {t[0]}")
            with self.db.connection() as conn:
                conn.executescript(SCHEMA_SQL)
            return _ok("Database reset. Restart required.")
        except Exception as e:
            return _err(e)

    # ── Users ───────────────────────────────────────────────────────────

    @pyqtSlot(result=str)
    def get_users(self):
        try:
            rows = self.db.execute(
                "SELECT id, username, display_name, email, role, is_active, created_at, last_login FROM users ORDER BY id"
            )
            return _ok([{"id": r[0], "username": r[1], "display_name": r[2], "email": r[3],
                          "role": r[4], "is_active": r[5], "created_at": r[6], "last_login": r[7]} for r in rows])
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def add_user(self, user_json):
        try:
            u = json.loads(user_json)
            if not u.get("username"):
                return _err("Username required")
            if not u.get("password"):
                return _err("Password required")
            existing = self.db.execute("SELECT id FROM users WHERE username=?", (u["username"],))
            if existing:
                return _err(f"Username '{u['username']}' already exists")
            pw_hash = hashlib.sha256(u["password"].encode()).hexdigest()
            uid = self.db.execute_insert(
                "INSERT INTO users (username, display_name, email, role, password_hash, is_active) VALUES (?,?,?,?,?,1)",
                (u["username"], u.get("display_name", u["username"]), u.get("email", ""),
                 u.get("role", "DJ"), pw_hash))
            return _ok({"id": uid, "message": "User created"})
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def update_user(self, user_json):
        try:
            u = json.loads(user_json)
            uid = u.get("id")
            if not uid:
                return _err("User ID required")
            if u.get("password"):
                pw_hash = hashlib.sha256(u["password"].encode()).hexdigest()
                self.db.execute(
                    "UPDATE users SET display_name=?, email=?, role=?, password_hash=? WHERE id=?",
                    (u.get("display_name", ""), u.get("email", ""), u.get("role", "DJ"), pw_hash, uid))
            else:
                self.db.execute(
                    "UPDATE users SET display_name=?, email=?, role=? WHERE id=?",
                    (u.get("display_name", ""), u.get("email", ""), u.get("role", "DJ"), uid))
            return _ok("User updated")
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def delete_user(self, user_id):
        try:
            admins = self.db.execute("SELECT COUNT(*) FROM users WHERE role='Administrator'")
            user_role = self.db.execute("SELECT role FROM users WHERE id=?", (user_id,))
            if admins[0][0] <= 1 and user_role and user_role[0][0] == "Administrator":
                return _err("Cannot delete the last administrator!")
            self.db.execute("DELETE FROM users WHERE id=?", (user_id,))
            return _ok("User deleted")
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def reset_password(self, user_id):
        try:
            import random, string
            new_pw = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
            pw_hash = hashlib.sha256(new_pw.encode()).hexdigest()
            self.db.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, user_id))
            return _ok(new_pw)
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_access_log(self):
        try:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS access_log "
                "(id INTEGER PRIMARY KEY, username TEXT, action TEXT, timestamp TEXT DEFAULT (datetime('now')))"
            )
            rows = self.db.execute("SELECT username, action, timestamp FROM access_log ORDER BY id DESC LIMIT 20")
            return _ok([{"username": r[0], "action": r[1], "timestamp": r[2]} for r in rows])
        except Exception as e:
            return _err(e)

    # ── Audio ───────────────────────────────────────────────────────────

    @pyqtSlot(result=str)
    def get_audio_devices(self):
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            output_devices = []
            input_devices = []
            for i, d in enumerate(devices):
                device = {"index": i, "name": d["name"],
                          "channels": max(d["max_output_channels"], d["max_input_channels"]),
                          "sample_rate": int(d["default_samplerate"])}
                if d["max_output_channels"] > 0:
                    output_devices.append(device)
                if d["max_input_channels"] > 0:
                    input_devices.append(device)
            return _ok({"outputs": output_devices, "inputs": input_devices})
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def play_test_tone(self, device_index):
        try:
            import sounddevice as sd
            import numpy as np
            sr = 44100
            duration = 2
            t = np.linspace(0, duration, int(sr * duration), False)
            tone = 0.3 * np.sin(2 * np.pi * 1000 * t)
            tone_stereo = np.column_stack([tone, tone])
            sd.play(tone_stereo.astype(np.float32), samplerate=sr, device=device_index)
            return _ok("Test tone playing")
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def play_test_tone_all(self):
        try:
            import sounddevice as sd
            import numpy as np
            sr = 44100
            t = np.linspace(0, 1.0, int(sr * 1.0), False)
            tone = 0.3 * np.sin(2 * np.pi * 1000 * t)
            tone_stereo = np.column_stack([tone, tone]).astype(np.float32)
            results = []
            for i in [1, 2, 3, 4]:
                idx = self.db.get_setting(f"audio_output_{i}")
                if idx is not None and idx != "":
                    try:
                        sd.play(tone_stereo, samplerate=sr, device=int(idx))
                        sd.wait()
                        results.append({"device": int(idx), "status": "ok"})
                    except Exception as e:
                        results.append({"device": int(idx), "status": str(e)})
            return _ok(results)
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def save_audio_routing(self, routing_json):
        try:
            if isinstance(routing_json, str):
                routing = json.loads(routing_json)
            else:
                routing = routing_json
            count = 0
            for key, value in routing.items():
                self.db.set_setting(str(key), str(value))
                count += 1
            return _ok({"message": "Routing saved", "count": count})
        except json.JSONDecodeError as e:
            return _err(f"Invalid JSON: {e}")
        except Exception as e:
            return _err(e)

    # ── Studio Settings ──────────────────────────────────────────────────

    @pyqtSlot(result=str)
    def get_studio_settings(self):
        try:
            keys = [
                'crossfade_duration', 'fade_out_start', 'fade_curve_type',
                'load_next_song', 'preload_buffer', 'automix_trigger',
                'fallback_action', 'missing_file_alert',
                'autocue_threshold', 'autocue_scan_mode',
                'master_volume', 'cue_volume', 'jingle_volume', 'mic_volume',
                'vu_decay_speed', 'peak_hold_duration', 'clip_indicator',
                'cue_split_mode', 'show_crossfade_preview', 'flash_mix_point',
                'audio_buffer_size', 'sample_rate', 'bit_depth', 'audio_engine',
            ]
            settings = {}
            for key in keys:
                val = self.db.get_setting(key)
                if val is not None:
                    settings[key] = val
            return _ok(settings)
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def save_studio_settings(self, settings_json):
        try:
            settings = json.loads(settings_json)
            for key, value in settings.items():
                self.db.set_setting(str(key), str(value))
            return _ok({"message": "Studio settings saved", "count": len(settings)})
        except Exception as e:
            return _err(e)

    # ── Weather & API ───────────────────────────────────────────────────

    @pyqtSlot(str, str, result=str)
    def test_weather_api(self, api_key, city):
        try:
            import requests
            url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return _ok({"temp": data["main"]["temp"], "condition": data["weather"][0]["description"],
                             "humidity": data["main"]["humidity"], "city": data["name"]})
            return _err(f"HTTP {resp.status_code}")
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def test_claude_api(self, api_key):
        try:
            import requests
            resp = requests.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-sonnet-4-20250514", "max_tokens": 10,
                      "messages": [{"role": "user", "content": "Say OK"}]}, timeout=15)
            if resp.status_code == 200:
                return _ok({"model": "claude-sonnet-4-20250514", "latency_ms": resp.elapsed.microseconds // 1000})
            return _err(f"HTTP {resp.status_code}")
        except Exception as e:
            return _err(e)

    # ── Audio Engine ────────────────────────────────────────────────────

    @pyqtSlot(str, result=str)
    def load_and_play(self, file_path):
        try:
            if not file_path or not os.path.exists(file_path):
                raise ValueError(f"File not found: {file_path}")
            self.audio.load_deck_a(file_path)
            self.audio.play_deck_a()
            return _ok("Playing on Deck A")
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def load_deck_a(self, file_path):
        try:
            if not file_path or not os.path.exists(file_path):
                raise ValueError(f"File not found: {file_path}")
            self.audio.load_deck_a(file_path)
            return _ok("Loaded on Deck A")
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def load_deck_b(self, file_path):
        try:
            if not file_path or not os.path.exists(file_path):
                raise ValueError(f"File not found: {file_path}")
            self.audio.load_deck_b(file_path)
            return _ok("Loaded on Deck B")
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def deck_control(self, action):
        try:
            actions = {
                'play_a': self.audio.play_deck_a,
                'pause_a': self.audio.pause_deck_a,
                'stop_a': self.audio.stop_deck_a,
                'play_b': self.audio.play_deck_b,
                'pause_b': self.audio.pause_deck_b,
                'stop_b': self.audio.stop_deck_b,
                'crossfade': self.audio.crossfade,
                'crossfade_ba': self.audio.crossfade_ba,
                'stop_jingle': self.audio.stop_jingle,
            }
            if action not in actions:
                raise ValueError(f"Unknown action: {action}")
            actions[action]()
            return _ok(f"Action: {action}")
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_playback_position(self):
        try:
            return _ok(self.audio.get_position())
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_playback_state(self):
        """Nested state dict consumed by the new Studio JS."""
        try:
            return _ok({
                'deck_a': self.audio.get_state('A'),
                'deck_b': self.audio.get_state('B'),
                'active_deck': self.audio.active_deck,
                'is_crossfading': self.audio.is_crossfading,
            })
        except Exception as e:
            return _err(e)

    # ── Clean 2-deck API slots (new architecture) ───────────────────────

    @pyqtSlot(str, str, result=str)
    def load_deck(self, deck, file_path):
        try:
            if deck not in ('A', 'B'):
                raise ValueError(f"Unknown deck: {deck}")
            if not self.audio.load_deck(deck, file_path):
                raise ValueError(f"File not found or load failed: {file_path}")
            return _ok(f"Loaded Deck {deck}")
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def play_deck(self, deck):
        try:
            if deck not in ('A', 'B'):
                raise ValueError(f"Unknown deck: {deck}")
            self.audio.play_deck(deck)
            return _ok(f"Playing Deck {deck}")
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def pause_deck(self, deck):
        try:
            self.audio.pause_deck(deck)
            return _ok(f"Paused Deck {deck}")
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def stop_deck(self, deck):
        try:
            self.audio.stop_deck(deck)
            return _ok(f"Stopped Deck {deck}")
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def start_crossfade(self):
        """Start a unified active→standby crossfade."""
        try:
            def _done(outgoing, incoming):
                try:
                    self.crossfade_complete.emit(incoming)
                except Exception:
                    pass
            self.audio.crossfade_to_standby(duration=3.0, callback=_done)
            return _ok("Crossfade started")
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, int, result=str)
    def set_deck_volume(self, deck, volume):
        try:
            if deck == 1:
                self.audio.set_volume_deck_a(volume)
            else:
                self.audio.set_volume_deck_b(volume)
            return _ok({"deck": deck, "volume": volume})
        except Exception as e:
            return _err(e)

    # String-deck variant used by the spot break flow. Takes 'A' or 'B'
    # so the JS doesn't have to maintain its own A→1/B→2 mapping.
    @pyqtSlot(str, int, result=str)
    def set_volume(self, deck, volume):
        try:
            if deck not in ('A', 'B'):
                raise ValueError(f"Unknown deck: {deck}")
            self.audio.set_volume(deck, volume)
            return _ok({"deck": deck, "volume": volume})
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, int, result=str)
    def seek_deck(self, deck, position_ms):
        try:
            if deck == 1:
                self.audio.seek_deck_a(position_ms)
            else:
                self.audio.seek_deck_b(position_ms)
            return _ok({"deck": deck, "position_ms": position_ms})
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def seek_deck_a(self, position_ms):
        try:
            self.audio.seek_deck_a(position_ms)
            return _ok({"deck": "A", "position_ms": position_ms})
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def seek_deck_b(self, position_ms):
        try:
            self.audio.seek_deck_b(position_ms)
            return _ok({"deck": "B", "position_ms": position_ms})
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def fade_out_deck(self, deck):
        try:
            if deck == 'A':
                self.audio.fade_out_deck_a(duration=3)
            elif deck == 'B':
                self.audio.fade_out_deck_b(duration=3)
            else:
                raise ValueError(f"Unknown deck: {deck}")
            return _ok(f"Fading out Deck {deck}")
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def play_jingle_pad(self, file_path):
        try:
            if not self.audio.play_jingle(file_path):
                raise ValueError(f"File not found: {file_path}")
            return _ok("Jingle playing")
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def get_file_duration(self, file_path):
        try:
            dur_ms = self.audio.get_duration(file_path)
            total_secs = int(dur_ms) // 1000
            return _ok({"ms": dur_ms, "formatted": f"{total_secs // 60}:{total_secs % 60:02d}"})
        except Exception as e:
            return _err(e)

    # ── Break Scheduler slots ───────────────────────────────────────────

    @pyqtSlot(result=str)
    def get_next_break(self):
        try:
            nb = self.scheduler.get_next_break()
            return _ok(nb or "")
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_todays_breaks(self):
        try:
            return _ok(self.scheduler.get_todays_breaks())
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_upcoming_spots(self):
        """Return campaigns scheduled within the next 20 minutes (10-min window).

        Uses the real schema: `campaign_schedule` with INT day_of_week (0-6)
        and HH:MM `break_time`. Joins `campaigns` + `spot_files` for counts.
        """
        try:
            from datetime import datetime, timedelta

            now = datetime.now()
            window_end = now + timedelta(minutes=20)

            def round_to_10(dt):
                return dt.replace(minute=(dt.minute // 10) * 10, second=0, microsecond=0)

            check_slots = []
            slot = round_to_10(now)
            while slot <= window_end:
                check_slots.append(slot.strftime('%H:%M'))
                slot += timedelta(minutes=10)

            dow = now.weekday()  # 0=Mon .. 6=Sun
            today_ymd = now.strftime('%Y-%m-%d')

            upcoming = []
            for time_slot in check_slots:
                rows = self.db.execute(
                    "SELECT c.id, c.name, c.category, c.priority, cs.break_time, "
                    "COUNT(sf.id) AS spot_count "
                    "FROM campaigns c "
                    "JOIN campaign_schedule cs ON cs.campaign_id = c.id "
                    "LEFT JOIN spot_files sf ON sf.campaign_id = c.id AND sf.is_active = 1 "
                    "WHERE c.is_active = 1 "
                    "AND cs.day_of_week = ? "
                    "AND cs.break_time = ? "
                    "GROUP BY c.id, cs.break_time",
                    (dow, time_slot)
                )
                for camp in rows:
                    slot_dt = datetime.strptime(f"{today_ymd} {time_slot}", '%Y-%m-%d %H:%M')
                    diff_mins = int((slot_dt - now).total_seconds() / 60)
                    if 0 <= diff_mins <= 20:
                        upcoming.append({
                            'campaign_id': camp[0],
                            'name': camp[1],
                            'category': camp[2] or '',
                            'priority': camp[3] or '',
                            'break_time': camp[4],
                            'spot_count': camp[5] or 0,
                            'mins_until': diff_mins,
                            'label': 'NOW' if diff_mins == 0 else f'in {diff_mins}m',
                        })

            upcoming.sort(key=lambda x: x['mins_until'])
            return _ok({
                'spots': upcoming,
                'checked_at': now.strftime('%H:%M:%S'),
                'window': '20 minutes',
            })
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_current_break(self):
        try:
            spots = self._last_break_spots or []
            return _ok({
                "active": len(spots) > 0,
                "spots": [{
                    "campaign": s.get("campaign_name", ""),
                    "filename": s.get("filename", ""),
                } for s in spots],
            })
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_playlist_queue(self):
        """Unified studio queue: clock-driven songs + upcoming breaks.

        Uses the AutoScheduler to read the current hour's clock
        assignment and build a queue from its slots. Falls back to
        random songs if no clock is assigned.
        """
        try:
            from datetime import datetime, timedelta
            from core.auto_scheduler import AutoScheduler

            # ── Clock-driven song selection ──
            scheduler = AutoScheduler(self.db)
            queue = scheduler.build_queue(max_items=20)

            def ms_to_str(ms):
                if not ms:
                    return "0:00"
                s = int(ms) // 1000
                return f"{s // 60}:{s % 60:02d}"

            # ── Breaks (next 4 hours only, today) ──
            now = datetime.now()
            dow = now.weekday()
            current_hhmm = now.strftime('%H:%M')
            cutoff_hhmm = (now + timedelta(hours=4)).strftime('%H:%M')

            break_rows = self.db.execute(
                "SELECT cs.break_time, "
                "GROUP_CONCAT(DISTINCT c.name), "
                "COUNT(DISTINCT sf.id) "
                "FROM campaign_schedule cs "
                "JOIN campaigns c ON c.id = cs.campaign_id "
                "LEFT JOIN spot_files sf ON sf.campaign_id = c.id AND sf.is_active = 1 "
                "WHERE c.is_active = 1 "
                "AND cs.day_of_week = ? "
                "AND cs.break_time > ? "
                "AND cs.break_time <= ? "
                "GROUP BY cs.break_time "
                "ORDER BY cs.break_time "
                "LIMIT 8",
                (dow, current_hhmm, cutoff_hhmm)
            )

            # ── Stitcher blocks (insert before each break if enabled) ──
            # When the Stitcher module is on and "trigger before every break"
            # is checked, we build a compact "Coming Up Next" summary from
            # songs-with-hooks and insert it into the queue right before each
            # break row so the DJ can see the Stitcher segment in context.
            stitch_item = None
            try:
                stitch_cfg = self.db.get_stitcher_config_v2()
                if (stitch_cfg.get("module_enabled") and
                        stitch_cfg.get("trigger_before_every_break")):
                    stitch_songs = self.db.get_songs_for_stitcher()
                    with_hooks = [s for s in stitch_songs if s.get("has_hook")]
                    min_hooks = int(stitch_cfg.get("min_hooks_required", 2) or 2)
                    max_hooks = int(stitch_cfg.get("max_hooks", 4) or 4)
                    if len(with_hooks) >= min_hooks:
                        n = min(len(with_hooks), max_hooks)
                        hook_dur = int(stitch_cfg.get("hook_duration_seconds", 8) or 8)
                        est_secs = 3 + (n * hook_dur) + max(0, n - 1) + 4
                        hook_artists = ", ".join(
                            s.get("artist", "?") for s in with_hooks[:n]
                        )
                        stitch_item = {
                            'type': 'stitcher',
                            'id': 0,
                            'artist': 'STITCHER',
                            'title': f'Coming Up Next ({n} hooks)',
                            'duration': ms_to_str(est_secs * 1000),
                            'duration_secs': est_secs,
                            'file_path': '',
                            'bpm': 0,
                            'year': 0,
                            'category': 'Stitcher',
                            'cat_color': '#14B8A6',
                            'status': 'Stitcher',
                            'sched_time': '',
                            'hook_artists': hook_artists,
                        }
            except Exception as e:
                print(f"[get_playlist_queue] stitcher query error: {e}")

            for b in break_rows:
                # Insert the Stitcher block before each break
                if stitch_item:
                    queue.append(dict(stitch_item, sched_time=b[0]))
                queue.append({
                    'type': 'break',
                    'id': 0,
                    'artist': '',
                    'title': b[1] or 'Break',
                    'duration': '—',
                    'duration_secs': 0,
                    'file_path': '',
                    'bpm': 0,
                    'year': 0,
                    'category': 'Ad Break',
                    'cat_color': '#F43F5E',
                    'status': 'Break',
                    'sched_time': b[0],
                    'spot_count': b[2] or 0,
                })

            # If there are no breaks but stitcher is configured, add one
            # standalone block so the DJ can see it's active
            if not break_rows and stitch_item:
                queue.append(stitch_item)

            return _ok(queue)
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_studio_queue(self):
        """Return real songs from DB for the Studio queue."""
        try:
            rows = self.db.execute(
                "SELECT s.id, s.artist, s.title, s.duration_ms, s.file_path, "
                "s.bpm, s.year, c.name, c.color "
                "FROM songs s LEFT JOIN categories c ON s.category_id = c.id "
                "WHERE s.is_enabled = 1 "
                "ORDER BY s.id LIMIT 20"
            )
            def ms_to_str(ms):
                if not ms:
                    return "0:00"
                s = int(ms) // 1000
                return f"{s // 60}:{s % 60:02d}"
            songs = [{
                "id": r[0], "artist": r[1], "title": r[2],
                "duration_ms": r[3] or 0, "duration": ms_to_str(r[3]),
                "file_path": r[4] or "", "bpm": r[5] or 0,
                "year": r[6] or 0,
                "category": r[7] or "Uncategorized",
                "category_color": r[8] or "#8B5CF6",
            } for r in rows]
            return _ok(songs)
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_studio_jingles(self):
        """Return jingles for the jingle pads on the Studio screen."""
        try:
            rows = self.db.execute(
                "SELECT id, name, file_path, duration_ms, category "
                "FROM jingles WHERE is_enabled = 1 "
                "ORDER BY display_order, id LIMIT 12"
            )
            def ms_to_str(ms):
                if not ms:
                    return "0:00"
                s = int(ms) // 1000
                return f"{s // 60}:{s % 60:02d}"
            jingles = [{
                "id": r[0], "name": r[1], "file_path": r[2] or "",
                "duration_ms": r[3] or 0, "duration": ms_to_str(r[3]),
                "category": r[4] or "Station ID",
            } for r in rows]
            return _ok(jingles)
        except Exception as e:
            return _err(e)

    # ── Mass Import ─────────────────────────────────────────────────────

    @pyqtSlot(str, str, result=str)
    def scan_folder(self, folder_path, options_json):
        try:
            if not folder_path or not os.path.isdir(folder_path):
                return _err(f"Folder not found: {folder_path}")

            options = json.loads(options_json) if options_json else {}
            include_sub = bool(options.get("include_subfolders", True))
            extensions = []
            if options.get("mp3", True):
                extensions.append(".mp3")
            if options.get("wav", True):
                extensions.append(".wav")
            if options.get("flac", True):
                extensions.append(".flac")
            # Always include these common formats
            extensions.extend([".m4a", ".ogg", ".aac", ".wma"])
            # Deduplicate
            extensions = list(set(extensions))
            if not extensions:
                return _err("No file types selected")

            audio_files = []
            if include_sub:
                for root, _dirs, files in os.walk(folder_path):
                    for f in files:
                        if os.path.splitext(f)[1].lower() in extensions:
                            audio_files.append(os.path.join(root, f))
            else:
                for f in os.listdir(folder_path):
                    full = os.path.join(folder_path, f)
                    if os.path.isfile(full) and os.path.splitext(f)[1].lower() in extensions:
                        audio_files.append(full)

            # Cap to 500 files for UI responsiveness
            audio_files = audio_files[:500]

            results = []
            for file_path in audio_files:
                row = _scan_one_file(file_path)
                results.append(row)

            ready = sum(1 for r in results if r["status"] == "Ready")
            no_tags = sum(1 for r in results if r["status"] == "No Tags")
            errors = sum(1 for r in results if r["status"] == "Error")

            return _ok({
                "files": results,
                "total": len(results),
                "ready": ready,
                "no_tags": no_tags,
                "errors": errors,
            })
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def mass_import_songs(self, import_json):
        try:
            data = json.loads(import_json)
            files = data.get("files", [])
            defaults = data.get("defaults", {}) or {}
            skip_dupes = bool(data.get("skip_duplicates", True))

            category_id = defaults.get("category_id")
            if category_id in ("", None):
                category_id = None
            else:
                try:
                    category_id = int(category_id)
                except Exception:
                    category_id = None

            default_era = (defaults.get("era") or "").strip() or None
            try:
                default_year = int(defaults.get("year") or 0) or None
            except Exception:
                default_year = None
            try:
                default_priority = int(defaults.get("priority") or 1)
            except Exception:
                default_priority = 1
            default_enabled = 1 if defaults.get("enabled", True) else 0

            imported = 0
            skipped = 0
            errors = 0

            for f in files:
                if not f.get("selected"):
                    continue
                if f.get("status") == "Error":
                    errors += 1
                    continue

                artist = (f.get("artist") or "").strip() or "Unknown Artist"
                title = (f.get("title") or "").strip()
                if not title:
                    title = os.path.splitext(f.get("filename") or "")[0] or "Untitled"

                if skip_dupes:
                    existing = self.db.execute(
                        "SELECT id FROM songs WHERE LOWER(artist)=LOWER(?) AND LOWER(title)=LOWER(?) LIMIT 1",
                        (artist, title)
                    )
                    if existing:
                        skipped += 1
                        continue

                # Year: prefer scanned, fall back to default
                year_val = f.get("year")
                if year_val:
                    try:
                        year_val = int(str(year_val)[:4])
                    except Exception:
                        year_val = default_year
                else:
                    year_val = default_year

                try:
                    bpm_val = int(f.get("bpm") or 0) or None
                except Exception:
                    bpm_val = None

                try:
                    self.db.execute(
                        "INSERT INTO songs "
                        "(artist, title, album, category_id, era, priority, year, bpm, "
                        "duration_ms, file_path, is_enabled) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            artist,
                            title,
                            (f.get("album") or "").strip() or None,
                            category_id,
                            default_era,
                            default_priority,
                            year_val,
                            bpm_val,
                            int(f.get("duration_ms") or 0),
                            f.get("file_path") or "",
                            default_enabled,
                        )
                    )
                    imported += 1
                except Exception as e:
                    print(f"[mass_import] insert error: {e}")
                    errors += 1

            return _ok({
                "imported": imported,
                "skipped": skipped,
                "errors": errors,
                "message": f"Done — {imported} imported, {skipped} skipped, {errors} errors",
            })
        except Exception as e:
            return _err(e)

    # ── Studio screen — Libraries / History / Stitcher / AI ─────────────

    @pyqtSlot(str, str, result=str)
    def get_library_songs(self, tab_type='songs', query=''):
        """Tabbed library browser used by the Studio screen.

        tab_type: 'songs' | 'spots' | 'mic' | 'jingles' | 'favs'
        query   : free-text search applied across artist/title/category.
        """
        try:
            q = (query or '').strip().lower()
            like = f"%{q}%" if q else None

            def ms_to_str(ms):
                if not ms:
                    return "0:00"
                s = int(ms) // 1000
                return f"{s // 60}:{s % 60:02d}"

            results = []

            if tab_type == 'spots':
                # Spots = active campaigns + their spot files
                base = (
                    "SELECT sf.id, c.name AS artist, sf.filename AS title, "
                    "c.category, sf.duration_ms, sf.file_path, c.priority "
                    "FROM spot_files sf "
                    "JOIN campaigns c ON c.id = sf.campaign_id "
                    "WHERE sf.is_active = 1 AND c.is_active = 1"
                )
                params = []
                if like:
                    base += " AND (LOWER(c.name) LIKE ? OR LOWER(sf.filename) LIKE ? OR LOWER(c.category) LIKE ?)"
                    params = [like, like, like]
                base += " ORDER BY c.priority DESC, sf.id LIMIT 200"
                rows = self.db.execute(base, tuple(params))
                for r in rows:
                    results.append({
                        "id": r[0], "artist": r[1] or "", "title": r[2] or "",
                        "category": r[3] or "", "bpm": "",
                        "year": "", "duration": ms_to_str(r[4]),
                        "file_path": r[5] or "", "type": "spot",
                    })

            elif tab_type == 'jingles':
                base = (
                    "SELECT id, name, category, duration_ms, file_path "
                    "FROM jingles WHERE is_enabled = 1"
                )
                params = []
                if like:
                    base += " AND (LOWER(name) LIKE ? OR LOWER(category) LIKE ?)"
                    params = [like, like]
                base += " ORDER BY display_order, id LIMIT 200"
                rows = self.db.execute(base, tuple(params))
                for r in rows:
                    results.append({
                        "id": r[0], "artist": "", "title": r[1] or "",
                        "category": r[2] or "", "bpm": "",
                        "year": "", "duration": ms_to_str(r[3]),
                        "file_path": r[4] or "", "type": "jingle",
                    })

            elif tab_type == 'mic':
                # No mic table — return empty for now
                pass

            elif tab_type == 'favs':
                # Favourites = enabled songs with priority >= 5 (or any
                # heuristic). Real favourites would need a `favourites`
                # table; we approximate from priority for now.
                base = (
                    "SELECT s.id, s.artist, s.title, c.name, s.bpm, s.year, "
                    "s.duration_ms, s.file_path "
                    "FROM songs s LEFT JOIN categories c ON s.category_id = c.id "
                    "WHERE s.is_enabled = 1 AND s.priority >= 5"
                )
                params = []
                if like:
                    base += " AND (LOWER(s.artist) LIKE ? OR LOWER(s.title) LIKE ?)"
                    params = [like, like]
                base += " ORDER BY s.priority DESC, s.artist LIMIT 200"
                rows = self.db.execute(base, tuple(params))
                for r in rows:
                    results.append({
                        "id": r[0], "artist": r[1] or "", "title": r[2] or "",
                        "category": r[3] or "", "bpm": r[4] or "",
                        "year": r[5] or "", "duration": ms_to_str(r[6]),
                        "file_path": r[7] or "", "type": "song",
                    })

            else:  # 'songs' default
                base = (
                    "SELECT s.id, s.artist, s.title, c.name, s.bpm, s.year, "
                    "s.duration_ms, s.file_path "
                    "FROM songs s LEFT JOIN categories c ON s.category_id = c.id "
                    "WHERE s.is_enabled = 1 "
                    "AND s.file_path IS NOT NULL AND s.file_path != ''"
                )
                params = []
                if like:
                    base += " AND (LOWER(s.artist) LIKE ? OR LOWER(s.title) LIKE ? OR LOWER(c.name) LIKE ?)"
                    params = [like, like, like]
                base += " ORDER BY s.artist, s.title LIMIT 200"
                rows = self.db.execute(base, tuple(params))
                for r in rows:
                    results.append({
                        "id": r[0], "artist": r[1] or "", "title": r[2] or "",
                        "category": r[3] or "", "bpm": r[4] or "",
                        "year": r[5] or "", "duration": ms_to_str(r[6]),
                        "file_path": r[7] or "", "type": "song",
                    })

            return _ok(results)
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_play_history(self):
        """Last 50 broadcast_log entries with artist/title resolved via JOIN."""
        try:
            rows = self.db.execute(
                "SELECT bl.id, bl.played_at, bl.entry_type, "
                "bl.song_id, bl.campaign_id, bl.jingle_id, bl.duration_ms, "
                "s.artist, s.title, "
                "c.name AS camp_name, "
                "j.name AS jingle_name "
                "FROM broadcast_log bl "
                "LEFT JOIN songs s ON s.id = bl.song_id "
                "LEFT JOIN campaigns c ON c.id = bl.campaign_id "
                "LEFT JOIN jingles j ON j.id = bl.jingle_id "
                "ORDER BY bl.played_at DESC LIMIT 50"
            )
            def ms_to_str(ms):
                if not ms:
                    return "—"
                s = int(ms) // 1000
                return f"{s // 60}:{s % 60:02d}"

            history = []
            for r in rows:
                played_at = r[1] or ""
                # Trim to HH:MM if it's a full timestamp
                time_str = played_at[-8:-3] if len(played_at) >= 16 else played_at
                entry_type = r[2] or "song"
                if r[7]:  # song
                    artist, title = r[7], r[8] or ""
                elif r[9]:  # campaign
                    artist, title = "SPOT", r[9]
                elif r[10]:  # jingle
                    artist, title = "JINGLE", r[10]
                else:
                    artist, title = "", ""
                history.append({
                    "id": r[0],
                    "time": time_str,
                    "played_at": played_at,
                    "type": entry_type,
                    "artist": artist,
                    "title": title,
                    "duration": ms_to_str(r[6]),
                })
            return _ok(history)
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def add_to_history(self, json_str):
        """Insert a play event into broadcast_log.

        Expected JSON: {song_id?, campaign_id?, jingle_id?,
                        type, duration_ms?, deck?}
        Plain text artist/title from JS is ignored — the read path
        joins the FK tables to resolve display strings.
        """
        try:
            data = json.loads(json_str) if json_str else {}
            entry_type = data.get("type", "song")
            song_id = data.get("song_id")
            campaign_id = data.get("campaign_id")
            jingle_id = data.get("jingle_id")
            duration_ms = data.get("duration_ms") or 0
            deck = data.get("deck", "A")
            self.db.execute(
                "INSERT INTO broadcast_log "
                "(played_at, entry_type, song_id, campaign_id, jingle_id, "
                "duration_ms, deck, was_manual, operator) "
                "VALUES (datetime('now','localtime'), ?, ?, ?, ?, ?, ?, 0, 'AI AUTO')",
                (entry_type, song_id, campaign_id, jingle_id, int(duration_ms), deck)
            )
            return _ok("Logged")
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_stitcher_config(self):
        """Return the four-slot stitcher hook config from settings."""
        try:
            keys = [
                ("OPEN", "stitcher_opening_audio"),
                ("HOOK 1", "stitcher_hook1_audio"),
                ("HOOK 2", "stitcher_hook2_audio"),
                ("CLOSE", "stitcher_closing_audio"),
            ]
            slots = []
            for label, key in keys:
                path = self.db.get_setting(key) or ""
                filename = os.path.basename(path) if path else ""
                duration = ""
                if path and os.path.exists(path):
                    try:
                        ms = self.audio.get_duration(path)
                        if ms:
                            s = int(ms) // 1000
                            duration = f"{s // 60}:{s % 60:02d}"
                    except Exception:
                        pass
                slots.append({
                    "label": label,
                    "filename": filename or "—",
                    "duration": duration or "0:00",
                    "configured": bool(path),
                })
            return _ok(slots)
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_ai_insights(self):
        """Return current AI insights for the Studio panel.

        Pulls active rows from the `ai_insights` table; falls back to
        a small set of computed insights if the table is empty.
        """
        try:
            rows = self.db.execute(
                "SELECT severity, message, detail FROM ai_insights "
                "WHERE is_dismissed = 0 "
                "ORDER BY created_at DESC LIMIT 4"
            )
            insights = []
            for r in rows:
                sev = r[0] or "info"
                icon = {"warning": "⚠", "info": "✦", "data": "📊", "timing": "⏱"}.get(sev, "✦")
                insights.append({
                    "icon": icon,
                    "severity": sev,
                    "message": r[1] or "",
                    "detail": r[2] or "",
                })

            if not insights:
                # Lightweight computed defaults so the panel isn't blank
                try:
                    song_count = self.db.execute("SELECT COUNT(*) FROM songs WHERE is_enabled=1")[0][0]
                    camp_count = self.db.execute("SELECT COUNT(*) FROM campaigns WHERE is_active=1")[0][0]
                except Exception:
                    song_count, camp_count = 0, 0
                insights = [
                    {"icon": "📊", "severity": "data",
                     "message": f"Library: {song_count} active songs",
                     "detail": ""},
                    {"icon": "📊", "severity": "data",
                     "message": f"{camp_count} active campaigns",
                     "detail": ""},
                    {"icon": "✦", "severity": "info",
                     "message": "Auto-deck switching active",
                     "detail": ""},
                    {"icon": "⏱", "severity": "timing",
                     "message": "Crossfade lead: 4s",
                     "detail": ""},
                ]
            return _ok(insights)
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def insert_next(self, song_id):
        """Hint to the studio JS to load this song to the standby deck.

        The actual deck loading happens client-side via load_deck —
        this slot just looks up the file path so the JS can call
        load_deck with the right argument.
        """
        try:
            rows = self.db.execute(
                "SELECT id, artist, title, file_path, duration_ms, "
                "(SELECT name FROM categories WHERE id = songs.category_id), bpm, year "
                "FROM songs WHERE id = ?",
                (int(song_id),)
            )
            if not rows:
                return _err(f"Song {song_id} not found")
            r = rows[0]
            return _ok({
                "id": r[0], "artist": r[1] or "", "title": r[2] or "",
                "file_path": r[3] or "", "duration_ms": r[4] or 0,
                "category": r[5] or "", "bpm": r[6] or "", "year": r[7] or "",
            })
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def replace_now(self, song_id):
        """Same lookup as insert_next — JS decides whether to load to
        the active or standby deck based on the action label."""
        return self.insert_next(song_id)

    # ── Stitcher Step A — v2 slots backed by `stitcher_config` table ────
    # These have a `_v2` suffix so they don't shadow the older
    # settings-key-based stitcher slots elsewhere in this file. The new
    # stitcher.html JS calls the v2 names exclusively.

    @pyqtSlot(result=str)
    def get_stitcher_config_v2(self):
        try:
            return _ok(self.db.get_stitcher_config_v2())
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def save_stitcher_config_v2(self, json_str):
        try:
            data = json.loads(json_str) if json_str else {}
            self.db.save_stitcher_config_v2(data)
            return _ok(True)
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_songs_for_stitcher(self):
        try:
            return _ok(self.db.get_songs_for_stitcher())
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, float, float, result=str)
    def save_song_hook_v2(self, song_id, hook_in, hook_out):
        try:
            self.db.save_song_hook(song_id, hook_in, hook_out)
            return _ok(True)
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def remove_song_hook(self, song_id):
        try:
            self.db.remove_song_hook(song_id)
            return _ok(True)
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def browse_audio_file_for_field(self, field_name):
        """Open a file picker rooted at the project folder, return the
        selected path. `field_name` is purely cosmetic — it goes into
        the dialog title."""
        try:
            label = field_name or "Audio"
            path, _ = QFileDialog.getOpenFileName(
                None,
                f"Select Audio — {label}",
                "C:\\RadioAI\\",
                "Audio Files (*.mp3 *.wav *.ogg *.aac *.m4a)",
            )
            return _ok(path or "")
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def preview_audio_file(self, file_path):
        """Quick fire-and-forget preview using a transient VLC player
        — does NOT touch deck A or deck B."""
        try:
            if not file_path or not os.path.exists(file_path):
                return _err("File not found")
            import vlc
            # Stash on the bridge so the player isn't garbage-collected
            # mid-playback.
            if not hasattr(self, "_preview_player"):
                self._preview_instance = vlc.Instance("--quiet")
                self._preview_player = self._preview_instance.media_player_new()
            else:
                try:
                    self._preview_player.stop()
                except Exception:
                    pass
            media = self._preview_instance.media_new(file_path)
            self._preview_player.set_media(media)
            self._preview_player.audio_set_volume(85)
            self._preview_player.play()
            return _ok(True)
        except Exception as e:
            return _err(e)

    # ── Audio Cue Editor slots ──────────────────────────────────────────

    @pyqtSlot(int, result=str)
    def get_song_cue_data(self, song_id):
        try:
            return _ok(self.db.get_song_cue_data(song_id))
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, str, result=str)
    def save_song_cue_points(self, song_id, json_str):
        try:
            data = json.loads(json_str) if json_str else {}
            self.db.save_song_cue_points(song_id, data)
            return _ok(True)
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, float, float, result=str)
    def preview_cue_segment(self, file_path, start_sec, duration_sec):
        """Play a specific segment of an audio file for preview.

        Uses the bridge's transient preview player (separate from the
        Studio decks A/B), seeks to start_sec, and stops after
        duration_sec on a daemon thread.
        """
        try:
            if not file_path or not os.path.exists(file_path):
                return _err(f"File not found: {file_path}")
            import vlc
            import threading
            import time as _time
            if not hasattr(self, "_preview_player"):
                self._preview_instance = vlc.Instance("--quiet")
                self._preview_player = self._preview_instance.media_player_new()
            else:
                try:
                    self._preview_player.stop()
                except Exception:
                    pass
            media = self._preview_instance.media_new(file_path)
            self._preview_player.set_media(media)
            self._preview_player.audio_set_volume(85)
            self._preview_player.play()

            # Schedule the seek + auto-stop on a daemon thread so we
            # return to the JS immediately.
            player = self._preview_player

            def cue_and_stop():
                try:
                    _time.sleep(0.30)  # let VLC initialise
                    player.set_time(int(max(0, start_sec) * 1000))
                    player.audio_set_volume(85)
                    _time.sleep(max(0.1, duration_sec))
                    player.stop()
                except Exception:
                    pass

            threading.Thread(target=cue_and_stop, daemon=True).start()
            return _ok(True)
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def get_audio_duration(self, file_path):
        """Probe an audio file's duration in seconds via mutagen first
        (no playback overhead) and fall back to VLC if needed."""
        try:
            if not file_path or not os.path.exists(file_path):
                return _ok(0.0)
            # Fast path: mutagen
            try:
                from mutagen import File as MutagenFile
                mf = MutagenFile(file_path)
                if mf is not None and mf.info and mf.info.length:
                    return _ok(float(mf.info.length))
            except Exception:
                pass
            # Slow path: AudioEngine.get_duration uses VLC
            ms = self.audio.get_duration(file_path)
            return _ok(float(ms or 0) / 1000.0)
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def stop_preview_audio(self):
        try:
            if hasattr(self, "_preview_player"):
                self._preview_player.stop()
            return _ok(True)
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, str, result=str)
    def play_stitcher_chain(self, deck, queue_json):
        """Build the stitcher sequence from the ACTUAL playlist queue
        (Jazler standard: hooks come from songs that will play after the
        break, not from the library) and play it via StitcherEngine.

        *queue_json* is the JS ``JSON.stringify(window.eventQueue)`` —
        the live playlist the Studio screen is currently using. If empty
        or '[]', falls back to the library-based sequence.
        """
        try:
            config = self.db.get_stitcher_config_v2()
            if not config.get("module_enabled"):
                return _ok({"steps": 0, "running": False})

            # Parse the live queue from JS
            queue = []
            try:
                queue = json.loads(queue_json) if queue_json else []
            except Exception:
                queue = []

            seq = self._build_sequence_from_queue(config, queue)

            if not seq:
                # Strict mode: play fallback if configured
                fb = config.get("fallback_audio", "")
                if fb and os.path.exists(fb):
                    seq = [{"type": "fallback", "file_path": fb,
                            "seek_sec": 0, "duration_sec": 0,
                            "play_full": True, "label": "Fallback"}]
                    print("[stitcher] not enough hooks, playing fallback")
                else:
                    print("[stitcher] not enough hooks, no fallback set")
                    return _ok({"steps": 0, "running": False})

            # Lazy-init engine
            if not hasattr(self, '_stitcher_engine') or self._stitcher_engine is None:
                from core.stitcher_engine import StitcherEngine
                self._stitcher_engine = StitcherEngine(self.audio.instance)

            # Estimate duration
            from core.stitcher_engine import _get_duration_safe
            total_sec = 0.0
            for s in seq:
                if s.get("play_full"):
                    dur_ms = _get_duration_safe(self.audio.instance, s.get("file_path", ""))
                    total_sec += (dur_ms / 1000.0) if dur_ms > 0 else 5.0
                else:
                    total_sec += float(s.get("duration_sec", 8) or 8)

            self._stitcher_engine.play_block(sequence=seq, target_vol=85)

            return _ok({
                "steps": len(seq),
                "running": True,
                "estimated_sec": round(total_sec, 1),
            })
        except Exception as e:
            return _err(e)

    def _build_sequence_from_queue(self, config, queue):
        """Jazler-style: pick hooks from songs in the actual playlist queue.

        1. Filter queue to songs with file_path (skip breaks/stitcher rows)
        2. Apply time-window filter (only songs within next N minutes)
        3. Look up each song's hook_in_time from the DB
        4. Keep only songs with hooks set (hook_in_time > 0, has_hook = 1)
        5. Take up to max_hooks
        6. Build: opening + hooks(+seps) + closing
        """
        max_hooks = int(config.get("max_hooks", 4) or 4)
        min_hooks = int(config.get("min_hooks_required", 2) or 2)
        hook_dur = int(config.get("hook_duration_seconds", 8) or 8)
        time_window = int(config.get("time_window_minutes", 25) or 25)
        strict = bool(config.get("strict_mode", 0))

        # Step 1+2: filter queue to playable songs within time window
        avg_song_sec = 210  # 3:30 average
        candidates = []
        cumulative_sec = 0
        for item in queue:
            if item.get("type") != "song":
                continue
            fp = item.get("file_path", "")
            if not fp:
                continue
            cumulative_sec += item.get("duration_secs", avg_song_sec) or avg_song_sec
            if cumulative_sec / 60.0 > time_window:
                break
            candidates.append(item)

        # Step 3+4: look up hook data from DB for each candidate
        hooked = []
        for c in candidates:
            song_id = c.get("id")
            if not song_id:
                continue
            rows = self.db.execute(
                "SELECT hook_in_time, hook_out_time, has_hook "
                "FROM songs WHERE id = ? AND has_hook = 1 "
                "AND hook_in_time IS NOT NULL AND hook_in_time > 0",
                (int(song_id),)
            )
            if rows:
                hook_in = float(rows[0][0] or 0)
                hooked.append({
                    "file_path": c.get("file_path", ""),
                    "hook_in": hook_in,
                    "artist": c.get("artist", ""),
                    "title": c.get("title", ""),
                })
            if len(hooked) >= max_hooks:
                break

        # Strict mode check
        if len(hooked) < min_hooks:
            if strict:
                return []  # caller handles fallback
            # Non-strict: if we have at least 1 hook, use it
            if not hooked:
                return []

        # Step 6: build the sequence
        sequence = []
        opening = config.get("opening_audio", "")
        if opening and os.path.exists(opening):
            sequence.append({
                "type": "opening", "file_path": opening,
                "seek_sec": 0, "duration_sec": 0,
                "play_full": True, "label": "Opening Intro",
            })

        sep_file = config.get("separator_audio", "")
        for i, h in enumerate(hooked):
            sequence.append({
                "type": "hook", "file_path": h["file_path"],
                "seek_sec": h["hook_in"], "duration_sec": hook_dur,
                "play_full": False,
                "label": f"{h['artist']} - {h['title']}",
            })
            if i < len(hooked) - 1 and sep_file and os.path.exists(sep_file):
                sequence.append({
                    "type": "separator", "file_path": sep_file,
                    "seek_sec": 0, "duration_sec": 0,
                    "play_full": True, "label": "Separator",
                })

        closing = config.get("closing_audio", "")
        if closing and os.path.exists(closing):
            sequence.append({
                "type": "closing", "file_path": closing,
                "seek_sec": 0, "duration_sec": 0,
                "play_full": True, "label": "Closing Outro",
            })

        return sequence

    # ── Sweeper Engine ──────────────────────────────────────────────────

    @property
    def sweeper_engine(self):
        if not hasattr(self, '_sweeper_engine') or self._sweeper_engine is None:
            from core.sweeper_engine import SweeperEngine
            self._sweeper_engine = SweeperEngine(self.audio.instance)
        return self._sweeper_engine

    @pyqtSlot(int, result=str)
    def get_sweepers_for_assignment(self, limit=20):
        """Return enabled sweepers for the queue assignment dropdown."""
        try:
            rows = self.db.execute(
                "SELECT id, name, category, position, duration_ms, file_path "
                "FROM sweepers WHERE is_enabled = 1 "
                "ORDER BY category, name LIMIT ?", (int(limit),)
            )
            def ms_fmt(ms):
                if not ms: return "0:00"
                s = int(ms) // 1000
                return f"{s // 60}:{s % 60:02d}"
            return _ok([{
                "id": r[0], "name": r[1], "category": r[2],
                "position": r[3], "duration": ms_fmt(r[4]),
                "duration_ms": r[4] or 0, "file_path": r[5] or "",
            } for r in rows])
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, int, result=str)
    def schedule_sweeper_for_song(self, song_id, sweeper_id):
        """Schedule a sweeper overlay for a song that's about to play.

        Looks up the song's duration/intro_end_ms and the sweeper's
        file/position/volume, then tells the SweeperEngine to watch
        the active deck and fire at the right moment.
        """
        try:
            song_rows = self.db.execute(
                "SELECT duration_ms, intro_end_ms, intro_point_ms, file_path "
                "FROM songs WHERE id = ?", (int(song_id),)
            )
            if not song_rows:
                return _err(f"Song {song_id} not found")
            sr = song_rows[0]
            song_info = {
                "duration_ms": sr[0] or 0,
                "intro_end_ms": sr[1] or sr[2] or 0,  # prefer new column, fall back
                "file_path": sr[3] or "",
            }

            sw_rows = self.db.execute(
                "SELECT file_path, duration_ms, position, sweeper_volume, "
                "song_volume, position_offset FROM sweepers WHERE id = ?",
                (int(sweeper_id),)
            )
            if not sw_rows:
                return _err(f"Sweeper {sweeper_id} not found")
            swr = sw_rows[0]
            sweeper_info = {
                "file_path": swr[0] or "",
                "duration_ms": swr[1] or 0,
                "position": swr[2] or "Bridge at End",
                "sweeper_volume": swr[3] if swr[3] is not None else 100,
                "song_volume": swr[4] if swr[4] is not None else 60,
                "position_offset": swr[5] or 0,
            }

            # Determine which deck is active
            deck_player = self.audio._player(self.audio.active_deck)

            self.sweeper_engine.schedule_for_song(
                song_info=song_info,
                sweeper_info=sweeper_info,
                deck_player=deck_player,
            )

            return _ok({"scheduled": True, "position": sweeper_info["position"]})
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def cancel_sweeper(self):
        try:
            self.sweeper_engine.cancel()
            return _ok(True)
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def is_stitcher_running(self):
        """Check if the StitcherEngine background thread is still playing."""
        try:
            if hasattr(self, '_stitcher_engine') and self._stitcher_engine:
                return _ok(self._stitcher_engine.is_running)
            return _ok(False)
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_stitcher_play_sequence(self):
        """Return a flat list of audio segments for broadcast playback.

        Each segment is either a full-file play (opening/separator/closing)
        or a seek-and-play segment (hooks: seek to hook_in, play for
        hook_duration seconds).

        Returns _ok([]) if the stitcher is disabled or doesn't have enough
        hooks, so the caller can safely skip.
        """
        try:
            config = self.db.get_stitcher_config_v2()
            if not config.get("module_enabled"):
                return _ok([])

            songs = self.db.get_songs_for_stitcher()
            with_hooks = [s for s in songs if s.get("has_hook")]
            min_hooks = int(config.get("min_hooks_required", 2) or 2)
            if len(with_hooks) < min_hooks:
                return _ok([])

            max_hooks = int(config.get("max_hooks", 4) or 4)
            hook_dur = int(config.get("hook_duration_seconds", 8) or 8)
            n = min(len(with_hooks), max_hooks)

            sequence = []

            # Opening audio (play full file)
            opening = config.get("opening_audio", "")
            if opening and os.path.exists(opening):
                sequence.append({
                    "type": "opening",
                    "file_path": opening,
                    "seek_sec": 0,
                    "duration_sec": 0,
                    "play_full": True,
                    "label": "Opening Intro",
                })

            sep_file = config.get("separator_audio", "")

            for i, song in enumerate(with_hooks[:n]):
                song_path = song.get("file_path", "")
                if not song_path or not os.path.exists(song_path):
                    continue
                hook_in = float(song.get("hook_in_time", 0) or 0)
                sequence.append({
                    "type": "hook",
                    "file_path": song_path,
                    "seek_sec": hook_in,
                    "duration_sec": hook_dur,
                    "play_full": False,
                    "label": f"{song.get('artist', '?')} — {song.get('title', '?')}",
                })
                # Separator between hooks (not after the last one)
                if i < n - 1 and sep_file and os.path.exists(sep_file):
                    sequence.append({
                        "type": "separator",
                        "file_path": sep_file,
                        "seek_sec": 0,
                        "duration_sec": 0,
                        "play_full": True,
                        "label": "Separator",
                    })

            # Closing audio (play full file)
            closing = config.get("closing_audio", "")
            if closing and os.path.exists(closing):
                sequence.append({
                    "type": "closing",
                    "file_path": closing,
                    "seek_sec": 0,
                    "duration_sec": 0,
                    "play_full": True,
                    "label": "Closing Outro",
                })

            return _ok(sequence)
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_stitcher_preview_info(self):
        """Build the preview payload the Stitcher tab consumes:
        ordered sequence of opening → hooks → closing, plus stats."""
        try:
            config = self.db.get_stitcher_config_v2()
            songs = self.db.get_songs_for_stitcher()

            with_hooks = [s for s in songs if s.get("has_hook")]
            without = [s for s in songs if not s.get("has_hook")]

            hook_dur = int(config.get("hook_duration_seconds", 8) or 8)
            max_hooks = int(config.get("max_hooks", 4) or 4)
            n = min(len(with_hooks), max_hooks)

            # Estimated total: opening (~3s) + hooks*duration +
            # separators (1s each between hooks) + closing (~4s)
            est = 3 + (n * hook_dur) + max(0, n - 1) * 1 + 4

            sequence = []
            if config.get("opening_audio"):
                sequence.append({
                    "step": "OPENING",
                    "file": config["opening_audio"],
                    "label": "Opening Intro",
                    "duration": "~0:03",
                    "color": "#14b8a6",
                })

            for i, song in enumerate(with_hooks[:n]):
                sequence.append({
                    "step": f"HOOK {i + 1}",
                    "artist": song.get("artist", ""),
                    "title": song.get("title", ""),
                    "hook_in": song.get("hook_in_time", 0),
                    "hook_out": song.get("hook_out_time", 0),
                    "duration": f"0:{hook_dur:02d}",
                    "color": "#8b5cf6",
                })
                if i < n - 1 and config.get("separator_audio"):
                    sequence.append({
                        "step": "SEP",
                        "label": "Separator",
                        "color": "#252848",
                    })

            if config.get("closing_audio"):
                sequence.append({
                    "step": "CLOSING",
                    "file": config["closing_audio"],
                    "label": "Closing Outro",
                    "duration": "~0:04",
                    "color": "#14b8a6",
                })

            return _ok({
                "sequence": sequence,
                "songs_with_hooks": with_hooks,
                "songs_without_hooks": without,
                "estimated_duration": f"0:{est:02d}",
                "can_run": len(with_hooks) >= int(config.get("min_hooks_required", 2) or 2),
                "total_songs": len(songs),
                "hooks_set": len(with_hooks),
                "config": config,
            })
        except Exception as e:
            return _err(e)

    # ── Scheduling Screen ────────────────────────────────────────────────

    @pyqtSlot(result=str)
    def get_scheduling_stats(self):
        try:
            clock_count = self.db.execute("SELECT COUNT(*) FROM clocks")[0][0]
            force_count = self.db.execute(
                "SELECT COUNT(*) FROM force_clocks WHERE is_active = 1"
            )[0][0]
            from datetime import datetime
            today = datetime.now().strftime('%Y-%m-%d')
            log_rows = self.db.execute(
                "SELECT COUNT(*) FROM final_logs WHERE log_date = ?", (today,)
            )
            log_ready = log_rows[0][0] > 0 if log_rows else False
            return _ok({
                "clock_count": clock_count,
                "force_clocks_count": force_count,
                "log_ready": log_ready,
                "auto_mode": self.db.get_setting("scheduling_auto_mode") or "SOHO",
            })
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_week_grid(self):
        """Return the 7-day x 6-slot clock assignment grid."""
        try:
            rows = self.db.execute(
                "SELECT a.day_of_week, a.hour_start, a.hour_end, "
                "c.id, c.name, c.description "
                "FROM auto_schedule a "
                "JOIN clocks c ON c.id = a.clock_id "
                "WHERE c.is_active = 1 "
                "ORDER BY a.day_of_week, a.hour_start"
            )
            grid = {}
            for r in rows:
                day = r[0]
                h_start = r[1]
                slot_idx = 5 if h_start >= 22 else (4 if h_start >= 18 else (
                    3 if h_start >= 14 else (2 if h_start >= 10 else (
                    1 if h_start >= 6 else 0))))
                grid[(day, slot_idx)] = {"clock_id": r[3], "clock_name": r[4] or ""}

            DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
                         "Friday", "Saturday", "Sunday"]
            SLOT_INFO = [
                {"range": "00:00-06:00", "name": "Night"},
                {"range": "06:00-10:00", "name": "Morning"},
                {"range": "10:00-14:00", "name": "Daytime"},
                {"range": "14:00-18:00", "name": "Afternoon"},
                {"range": "18:00-22:00", "name": "Evening"},
                {"range": "22:00-00:00", "name": "Late Night"},
            ]
            result = []
            for si, slot in enumerate(SLOT_INFO):
                row = {"slot": si, "range": slot["range"], "name": slot["name"], "days": []}
                for d in range(7):
                    cell = grid.get((d, si))
                    row["days"].append({
                        "day": d, "day_name": DAY_NAMES[d],
                        "clock_name": cell["clock_name"] if cell else "",
                        "clock_id": cell["clock_id"] if cell else 0,
                    })
                result.append(row)
            return _ok({"grid": result, "day_names": DAY_NAMES})
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_separation_rules(self):
        try:
            keys = ["same_artist_hours", "same_song_days", "same_category_mins",
                    "artist_title_sep_hours", "vocal_type", "selection_randomness"]
            rules = {}
            for k in keys:
                rules[k] = self.db.get_setting(k) or ""
            return _ok(rules)
        except Exception as e:
            return _err(e)

    # ── Auto Schedule Grid ─────────────────────────────────────────────

    @pyqtSlot(result=str)
    def get_schedule_grid(self):
        """Full 24×7 auto-schedule grid."""
        try:
            rows = self.db.execute(
                "SELECT a.day_of_week, a.hour_start, c.id, c.name "
                "FROM auto_schedule a "
                "JOIN clocks c ON c.id = a.clock_id "
                "ORDER BY a.day_of_week, a.hour_start"
            )
            grid = {}
            for r in rows:
                grid[f"{r[0]}_{r[1]}"] = {"clock_id": r[2], "clock_name": r[3]}
            cells = []
            for d in range(7):
                for h in range(24):
                    c = grid.get(f"{d}_{h}")
                    cells.append({
                        "day": d, "hour": h,
                        "clock_id": c["clock_id"] if c else 0,
                        "clock_name": c["clock_name"] if c else "",
                    })
            return _ok(cells)
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, int, result=str)
    def assign_clock_to_cells(self, cells_json, clock_id):
        """Assign a clock to a list of grid cells [{day,hour},...]."""
        try:
            cells = json.loads(cells_json) if cells_json else []
            for cell in cells:
                d = int(cell["day"])
                h = int(cell["hour"])
                self.db.execute(
                    "DELETE FROM auto_schedule WHERE day_of_week=? AND hour_start=?",
                    (d, h))
                if clock_id > 0:
                    self.db.execute(
                        "INSERT INTO auto_schedule (clock_id, day_of_week, hour_start, hour_end) "
                        "VALUES (?,?,?,?)", (int(clock_id), d, h, h + 1))
            return _ok(True)
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def clear_schedule_grid(self):
        try:
            self.db.execute("DELETE FROM auto_schedule")
            return _ok(True)
        except Exception as e:
            return _err(e)

    # ── Clock CRUD ───────────────────────────────────────────────────────

    @pyqtSlot(result=str)
    def get_clocks_list(self):
        try:
            rows = self.db.execute(
                "SELECT c.id, c.name, c.time_start, c.time_end, c.is_active, c.description, "
                "(SELECT COUNT(*) FROM clock_slots WHERE clock_id=c.id) AS slot_count "
                "FROM clocks c ORDER BY c.name"
            )
            return _ok([{
                "id": r[0], "name": r[1] or "", "time_start": r[2] or "",
                "time_end": r[3] or "", "is_active": r[4],
                "description": r[5] or "", "slot_count": r[6] or 0,
            } for r in rows])
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def save_clock(self, clock_json):
        try:
            c = json.loads(clock_json) if clock_json else {}
            name = c.get("name", "").strip()
            if not name:
                return _err("Clock name required")
            cid = c.get("id")
            if cid:
                self.db.execute(
                    "UPDATE clocks SET name=?, time_start=?, time_end=?, description=?, is_active=1 WHERE id=?",
                    (name, c.get("time_start", ""), c.get("time_end", ""),
                     c.get("description", ""), int(cid)))
                return _ok({"id": cid})
            else:
                new_id = self.db.execute_insert(
                    "INSERT INTO clocks (name, time_start, time_end, description, day_mask, is_active) "
                    "VALUES (?,?,?,?,127,1)",
                    (name, c.get("time_start", ""), c.get("time_end", ""),
                     c.get("description", "")))
                return _ok({"id": new_id})
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def delete_clock(self, clock_id):
        try:
            self.db.execute("DELETE FROM clock_slots WHERE clock_id=?", (clock_id,))
            self.db.execute("DELETE FROM auto_schedule WHERE clock_id=?", (clock_id,))
            self.db.execute("DELETE FROM clocks WHERE id=?", (clock_id,))
            return _ok(True)
        except Exception as e:
            return _err(e)

    # ── Clock Slots CRUD ─────────────────────────────────────────────────

    @pyqtSlot(int, result=str)
    def get_clock_slots(self, clock_id):
        try:
            rows = self.db.execute(
                "SELECT cs.id, cs.slot_type, cs.category_id, cs.energy_pref, "
                "cs.vocal_pref, cs.priority_pref, cs.separation_override, cs.slot_order, "
                "cs.is_break, c.name AS cat_name, cs.sweeper_position, cs.item_id "
                "FROM clock_slots cs LEFT JOIN categories c ON c.id = cs.category_id "
                "WHERE cs.clock_id = ? ORDER BY cs.slot_order",
                (int(clock_id),))
            result = []
            for r in rows:
                item_name = ""
                stype = r[1] or "Song"
                iid = r[11] or 0
                if iid > 0:
                    if stype == "Sweeper":
                        nr = self.db.execute("SELECT name FROM sweepers WHERE id=?", (iid,))
                        if nr: item_name = nr[0][0] or ""
                    elif stype == "Jingle":
                        nr = self.db.execute("SELECT name FROM jingles WHERE id=?", (iid,))
                        if nr: item_name = nr[0][0] or ""
                result.append({
                    "id": r[0], "slot_type": stype,
                    "category_id": r[2], "energy": r[3] or "Any",
                    "vocal": r[4] or "Any", "priority": r[5] or "Normal",
                    "separation": r[6] or 0, "slot_order": r[7],
                    "is_break": r[8] or 0, "category_name": r[9] or "",
                    "sweeper_position": r[10] or "START_OF_SONG",
                    "item_id": iid, "item_name": item_name,
                })
            return _ok(result)
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, str, result=str)
    def add_clock_slot(self, clock_id, slot_json):
        try:
            s = json.loads(slot_json) if slot_json else {}
            max_order = self.db.execute(
                "SELECT MAX(slot_order) FROM clock_slots WHERE clock_id=?",
                (int(clock_id),))
            next_order = (max_order[0][0] or 0) + 1
            sid = self.db.execute_insert(
                "INSERT INTO clock_slots (clock_id, slot_type, category_id, energy_pref, "
                "vocal_pref, priority_pref, separation_override, slot_order, is_break, "
                "sweeper_position, item_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (int(clock_id), s.get("slot_type", "Song"),
                 int(s.get("category_id") or 0) or None,
                 s.get("energy", "Any"), s.get("vocal", "Any"),
                 s.get("priority", "Normal"),
                 int(s.get("separation") or 0),
                 next_order, 1 if s.get("is_break") else 0,
                 s.get("sweeper_position", "START_OF_SONG"),
                 int(s.get("item_id") or 0)))
            return _ok({"id": sid, "slot_order": next_order})
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, str, result=str)
    def update_clock_slot(self, slot_id, slot_json):
        try:
            s = json.loads(slot_json) if slot_json else {}
            self.db.execute(
                "UPDATE clock_slots SET slot_type=?, category_id=?, energy_pref=?, "
                "vocal_pref=?, priority_pref=?, separation_override=?, is_break=?, "
                "sweeper_position=?, item_id=? WHERE id=?",
                (s.get("slot_type", "Song"),
                 int(s.get("category_id") or 0) or None,
                 s.get("energy", "Any"), s.get("vocal", "Any"),
                 s.get("priority", "Normal"),
                 int(s.get("separation") or 0),
                 1 if s.get("is_break") else 0,
                 s.get("sweeper_position", "START_OF_SONG"),
                 int(s.get("item_id") or 0),
                 int(slot_id)))
            return _ok(True)
        except Exception as e:
            return _err(e)

    # ── Library items for Clock Editor tabs ───────────────────────────

    @pyqtSlot(str, result=str)
    def get_library_sweepers(self, category=''):
        try:
            q = "SELECT id, name, duration_ms, category, file_path FROM sweepers WHERE is_enabled=1"
            p = []
            if category and category != 'All':
                q += " AND category=?"
                p.append(category)
            q += " ORDER BY name"
            rows = self.db.execute(q, tuple(p))
            def fmt(ms):
                if not ms: return "0:00"
                s = int(ms) // 1000
                return f"{s // 60}:{s % 60:02d}"
            return _ok([{"id": r[0], "name": r[1] or "", "duration": fmt(r[2]),
                          "duration_ms": r[2] or 0, "category": r[3] or ""} for r in rows])
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def get_library_jingles(self, category=''):
        try:
            q = "SELECT id, name, duration_ms, category FROM jingles WHERE is_enabled=1"
            p = []
            if category and category != 'All':
                q += " AND category=?"
                p.append(category)
            q += " ORDER BY name"
            rows = self.db.execute(q, tuple(p))
            def fmt(ms):
                if not ms: return "0:00"
                s = int(ms) // 1000
                return f"{s // 60}:{s % 60:02d}"
            return _ok([{"id": r[0], "name": r[1] or "", "duration": fmt(r[2]),
                          "duration_ms": r[2] or 0, "category": r[3] or ""} for r in rows])
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def get_library_spots(self, category=''):
        try:
            q = ("SELECT sf.id, sf.filename, sf.duration_ms, c.name "
                 "FROM spot_files sf JOIN campaigns c ON c.id = sf.campaign_id "
                 "WHERE sf.is_active=1 AND c.is_active=1")
            p = []
            if category and category != 'All':
                q += " AND c.category=?"
                p.append(category)
            q += " ORDER BY c.name, sf.filename"
            rows = self.db.execute(q, tuple(p))
            def fmt(ms):
                if not ms: return "0:00"
                s = int(ms) // 1000
                return f"{s // 60}:{s % 60:02d}"
            return _ok([{"id": r[0], "name": r[1] or "", "duration": fmt(r[2]),
                          "duration_ms": r[2] or 0, "category": r[3] or ""} for r in rows])
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, result=str)
    def delete_clock_slot(self, slot_id):
        try:
            self.db.execute("DELETE FROM clock_slots WHERE id=?", (int(slot_id),))
            return _ok(True)
        except Exception as e:
            return _err(e)

    @pyqtSlot(int, int, int, result=str)
    def move_clock_slot(self, clock_id, slot_id, direction):
        """Move a slot up (-1) or down (+1)."""
        try:
            slots = self.db.execute(
                "SELECT id, slot_order FROM clock_slots WHERE clock_id=? ORDER BY slot_order",
                (int(clock_id),))
            ids = [r[0] for r in slots]
            idx = ids.index(int(slot_id))
            new_idx = max(0, min(len(ids) - 1, idx + direction))
            if idx != new_idx:
                ids[idx], ids[new_idx] = ids[new_idx], ids[idx]
                for i, sid in enumerate(ids):
                    self.db.execute("UPDATE clock_slots SET slot_order=? WHERE id=?", (i + 1, sid))
            return _ok(True)
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_active_clock_info(self):
        """Return the currently active clock for the Studio status display."""
        try:
            from core.auto_scheduler import AutoScheduler
            sched = AutoScheduler(self.db)
            clock = sched.get_current_clock()
            from datetime import datetime
            now = datetime.now()
            if clock:
                return _ok({
                    "active": True,
                    "clock_name": clock["name"],
                    "clock_id": clock["id"],
                    "hour": now.hour,
                    "day": now.weekday(),
                })
            return _ok({
                "active": False,
                "clock_name": "",
                "clock_id": 0,
                "hour": now.hour,
                "day": now.weekday(),
            })
        except Exception as e:
            return _err(e)

    # ── AI Daily Scheduler ─────────────────────────────────────────────

    @pyqtSlot(result=str)
    def get_ai_scheduler_status(self):
        try:
            from core.ai_daily_scheduler import AIDailyScheduler
            from datetime import datetime
            sched = AIDailyScheduler(self.db)
            today = datetime.now().strftime('%Y-%m-%d')
            return _ok(sched.get_status(today))
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def generate_ai_schedule(self, date_str):
        try:
            from core.ai_daily_scheduler import AIDailyScheduler
            from datetime import datetime
            sched = AIDailyScheduler(self.db)
            d = date_str.strip() if date_str else datetime.now().strftime('%Y-%m-%d')
            import threading
            threading.Thread(
                target=sched.generate_schedule, args=(d,), daemon=True
            ).start()
            return _ok({"message": "Generation started", "date": d})
        except Exception as e:
            return _err(e)

    # ── AI Magic ──────────────────────────────────────────────────────

    @pyqtSlot(result=str)
    def get_ai_magic_status(self):
        try:
            from core.ai_daily_scheduler import AIDailyScheduler
            from datetime import datetime
            ai = AIDailyScheduler(self.db)
            today = datetime.now().strftime('%Y-%m-%d')
            st = ai.get_status(today)
            # Count categories
            total_cats = self.db.execute("SELECT COUNT(*) FROM categories")[0][0]
            used_cats = self.db.execute(
                "SELECT COUNT(DISTINCT s.category_id) FROM ai_daily_log al "
                "JOIN songs s ON s.id = al.song_id WHERE al.schedule_date=?", (today,))[0][0]
            return _ok({
                "engine_running": True,
                "last_run": st.get("generated_at", ""),
                "next_run": "Tonight 12:00 AM",
                "today": {
                    "status": st.get("status", "pending"),
                    "songs_scheduled": st.get("songs_scheduled", 0),
                    "warnings_count": st.get("warnings_count", 0),
                    "categories_used": used_cats,
                    "total_categories": total_cats,
                },
                "components": [
                    {"name": "History Scanner", "detail": "Reads 30-day log", "status": "ACTIVE", "color": "#10b981"},
                    {"name": "Rule Engine", "detail": "7-day separation", "status": "ACTIVE", "color": "#06b6d4"},
                    {"name": "Song Picker", "detail": "Freshness score", "status": "ACTIVE", "color": "#a78bfa"},
                    {"name": "Warning System", "detail": "Low-category alert",
                     "status": f"{st.get('warnings_count',0)} WARNS" if st.get('warnings_count') else "OK", "color": "#f59e0b"},
                    {"name": "Log Writer", "detail": "176 slots saved", "status": "DONE", "color": "#10b981"},
                    {"name": "Midnight Timer", "detail": "Next: 12:00 AM", "status": "WAITING", "color": "#454d6d"},
                ],
            })
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_ai_magic_timeline(self):
        try:
            from datetime import datetime
            today = datetime.now().strftime('%Y-%m-%d')
            rows = self.db.execute(
                "SELECT step_time, step_label, step_detail, status "
                "FROM ai_run_steps WHERE run_date=? ORDER BY id", (today,))
            return _ok([{
                "time": r[0] or "", "label": r[1] or "", "detail": r[2] or "", "status": r[3] or "done"
            } for r in rows])
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_ai_magic_categories(self):
        try:
            rows = self.db.execute(
                "SELECT c.name, c.color, COUNT(s.id) as cnt "
                "FROM categories c "
                "LEFT JOIN songs s ON s.category_id = c.id AND s.is_enabled = 1 "
                "AND s.file_path IS NOT NULL AND s.file_path != '' "
                "GROUP BY c.id ORDER BY c.name")
            max_songs = 30
            return _ok([{
                "name": r[0], "color": r[1] or "#8B5CF6",
                "songs_total": r[2], "health_percent": min(100, int(r[2] / max_songs * 100)),
            } for r in rows])
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_ai_magic_decisions(self):
        try:
            from datetime import datetime
            today = datetime.now().strftime('%Y-%m-%d')
            rows = self.db.execute(
                "SELECT decision_time, decision_type, message "
                "FROM ai_decisions WHERE run_date=? ORDER BY id DESC LIMIT 10", (today,))
            return _ok([{"time": r[0] or "", "type": r[1] or "", "message": r[2] or ""} for r in rows])
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def save_separation_rules(self, rules_json):
        try:
            data = json.loads(rules_json) if rules_json else {}
            for k, v in data.items():
                self.db.set_setting(k, str(v))
            return _ok(True)
        except Exception as e:
            return _err(e)

    # ── Spots & Commercials AI Monitor ───────────────────────────────
    @pyqtSlot(result=str)
    def get_spots_hourly_usage(self):
        """Current clock-hour breakdown from broadcast_log.

        Buckets duration_ms by entry_type into songs / ads / jingles /
        sweepers. Status threshold applies to ads only:
          green < 12 min, amber 12-14 min, red 15+ min.
        """
        try:
            now = datetime.now()
            hour_start = now.replace(minute=0, second=0, microsecond=0)
            # Many log rows are written with duration_ms=0; fall back to the
            # joined library table's duration so the pie + totals aren't empty.
            rows = self.db.execute(
                "SELECT bl.entry_type, COALESCE(SUM("
                "CASE WHEN bl.duration_ms > 0 THEN bl.duration_ms "
                "     WHEN bl.song_id IS NOT NULL THEN s.duration_ms "
                "     WHEN bl.campaign_id IS NOT NULL THEN "
                "          (SELECT AVG(sf.duration_ms) FROM spot_files sf "
                "           WHERE sf.campaign_id = bl.campaign_id) "
                "     WHEN bl.jingle_id IS NOT NULL THEN j.duration_ms "
                "     ELSE 0 END), 0) "
                "FROM broadcast_log bl "
                "LEFT JOIN songs s ON s.id = bl.song_id "
                "LEFT JOIN jingles j ON j.id = bl.jingle_id "
                "WHERE bl.played_at >= ? GROUP BY bl.entry_type",
                (hour_start.strftime("%Y-%m-%d %H:%M:%S"),))
            buckets = {"song": 0, "spot": 0, "jingle": 0, "sweeper": 0}
            for et, total in rows:
                key = (et or "").lower()
                # 'stitcher' entries render as sweeper-adjacent content
                if key == "stitcher":
                    key = "sweeper"
                if key in buckets:
                    buckets[key] += int(total or 0)
            ads_min = buckets["spot"] / 60000.0
            if ads_min >= 15:
                status = "exceed"
            elif ads_min >= 12:
                status = "warning"
            else:
                status = "ok"
            return _ok({
                "hour": now.hour,
                "songs_ms": buckets["song"],
                "ads_ms": buckets["spot"],
                "jingles_ms": buckets["jingle"],
                "sweepers_ms": buckets["sweeper"],
                "ads_min": round(ads_min, 1),
                "remaining_min": round(max(0, 15 - ads_min), 1),
                "status": status,
            })
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_spots_hourly_trend(self):
        """Last 16 hours: ad minutes per hour (oldest → newest)."""
        try:
            from datetime import timedelta
            now = datetime.now()
            base = now.replace(minute=0, second=0, microsecond=0)
            out = []
            for offset in range(15, -1, -1):
                start = base - timedelta(hours=offset)
                end = start + timedelta(hours=1)
                rows = self.db.execute(
                    "SELECT COALESCE(SUM("
                    "CASE WHEN bl.duration_ms > 0 THEN bl.duration_ms "
                    "     WHEN bl.campaign_id IS NOT NULL THEN "
                    "          COALESCE((SELECT AVG(sf.duration_ms) FROM spot_files sf "
                    "                    WHERE sf.campaign_id = bl.campaign_id), 30000) "
                    "     ELSE 30000 END), 0) "
                    "FROM broadcast_log bl "
                    "WHERE bl.entry_type IN ('spot','ad','break','spots') AND bl.played_at >= ? AND bl.played_at < ?",
                    (start.strftime("%Y-%m-%d %H:%M:%S"),
                     end.strftime("%Y-%m-%d %H:%M:%S")))
                ms = int(rows[0][0]) if rows else 0
                mn = ms / 60000.0
                if mn >= 15:
                    color = "red"
                elif mn >= 12:
                    color = "amber"
                else:
                    color = "green"
                out.append({
                    "hour": start.hour,
                    "minutes": round(mn, 1),
                    "color": color,
                })
            return _ok(out)
        except Exception as e:
            return _err(e)

    @pyqtSlot(str, result=str)
    def get_spots_client_rotation(self, period):
        """Client breakdown sorted High → Low.

        period: 'hour' (current hour) | '7days' (trailing week).
        Tier: HIGH > 3 min/hr, MEDIUM 1-3, LOW < 1.
        """
        try:
            from datetime import timedelta
            now = datetime.now()
            if period == "hour":
                start = now.replace(minute=0, second=0, microsecond=0)
                hours_span = 1
            else:
                start = now - timedelta(days=7)
                hours_span = 24 * 7
            # Group by campaign_id (may be NULL for legacy rows). For rows
            # with zero duration_ms, fall back to the average spot_file
            # duration for that campaign (30 s default for unassigned).
            rows = self.db.execute(
                "SELECT bl.campaign_id, c.name, c.category, c.priority, "
                "COUNT(*) AS plays, COALESCE(SUM("
                "  CASE WHEN bl.duration_ms > 0 THEN bl.duration_ms "
                "       WHEN bl.campaign_id IS NOT NULL THEN "
                "            COALESCE((SELECT AVG(sf.duration_ms) FROM spot_files sf "
                "                      WHERE sf.campaign_id = bl.campaign_id), 30000) "
                "       ELSE 30000 END), 0) AS total_ms "
                "FROM broadcast_log bl "
                "LEFT JOIN campaigns c ON c.id = bl.campaign_id "
                "WHERE bl.entry_type IN ('spot','ad','break','spots') AND bl.played_at >= ? "
                "GROUP BY bl.campaign_id ORDER BY total_ms DESC",
                (start.strftime("%Y-%m-%d %H:%M:%S"),))
            out = []
            for r in rows:
                total_ms = int(r[5] or 0)
                plays = int(r[4] or 0)
                min_per_hr = (total_ms / 60000.0) / max(1, hours_span)
                if min_per_hr > 3:
                    tier = "HIGH"
                elif min_per_hr >= 1:
                    tier = "MEDIUM"
                else:
                    tier = "LOW"
                out.append({
                    "campaign_id": r[0],
                    "name": r[1] or ("Direct Spots" if r[0] is None else "Unknown"),
                    "category": r[2] or "",
                    "priority": r[3] or "",
                    "plays": plays,
                    "total_min": round(total_ms / 60000.0, 1),
                    "min_per_hour": round(min_per_hr, 1),
                    "tier": tier,
                })
            return _ok(out)
        except Exception as e:
            return _err(e)

    @pyqtSlot(result=str)
    def get_spots_ai_insight(self):
        """Auto-generated advisory based on current-hour usage."""
        try:
            from datetime import timedelta
            now = datetime.now()

            # Are there ANY spot plays at all? If not → onboarding message.
            any_rows = self.db.execute(
                "SELECT COUNT(*) FROM broadcast_log WHERE entry_type='spot'")
            if not any_rows or int(any_rows[0][0] or 0) == 0:
                return _ok({
                    "severity": "info",
                    "message": "Start broadcasting to see analytics.",
                })

            alerts = []  # list of (severity_rank, severity_str, text)

            # (a) Any client > 3 min/hour over the last 7 days
            week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
            hours_span = 24 * 7
            client_rows = self.db.execute(
                "SELECT c.name, COALESCE(SUM(bl.duration_ms),0) AS ms "
                "FROM broadcast_log bl LEFT JOIN campaigns c ON c.id=bl.campaign_id "
                "WHERE bl.entry_type IN ('spot','ad','break','spots') AND bl.campaign_id IS NOT NULL "
                "AND bl.played_at >= ? "
                "GROUP BY bl.campaign_id ORDER BY ms DESC", (week_start,))
            for name, ms in client_rows:
                min_per_hour = (int(ms or 0) / 60000.0) / hours_span
                if min_per_hour > 3:
                    alerts.append((2, "warning",
                        f"{name or 'Unknown'} using {min_per_hour:.1f} min/hr "
                        "— consider reducing rotation."))

            # (b) Any hour today > 15 min of ads
            today = now.strftime("%Y-%m-%d")
            hour_rows = self.db.execute(
                "SELECT strftime('%H', played_at) AS hr, "
                "COALESCE(SUM(duration_ms),0) AS ms "
                "FROM broadcast_log WHERE entry_type='spot' "
                "AND date(played_at) = ? GROUP BY hr", (today,))
            for hr, ms in hour_rows:
                mn = int(ms or 0) / 60000.0
                if mn > 15:
                    alerts.append((3, "critical",
                        f"Hour {hr}:00 exceeded limit ({mn:.1f} min > 15 min cap)."))

            if alerts:
                alerts.sort(key=lambda x: -x[0])
                top = alerts[0]
                if len(alerts) > 1:
                    msg = top[2] + f" (+{len(alerts)-1} more alert"
                    msg += "s)" if len(alerts) > 2 else ")"
                else:
                    msg = top[2]
                return _ok({"severity": top[1], "message": msg})

            # (c) All good
            return _ok({
                "severity": "ok",
                "message": "Ad rotation healthy ✅ All clients within limits.",
            })
        except Exception as e:
            return _err(e)
