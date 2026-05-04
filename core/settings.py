"""
RadioAI Studio Pro — Settings Singleton
Loads all settings from DB into an in-memory dict cache.
Use get()/set() for generic access, or named properties for common ones.
"""

import threading
import logging
from typing import Optional

log = logging.getLogger("Settings")


class Settings:
    """Singleton settings cache backed by the settings table."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._cache: dict = {}
                    inst._loaded = False
                    cls._instance = inst
        return cls._instance

    # ── Load / reload ─────────────────────────────────────────────────────────

    def load(self, db=None) -> None:
        """Load all settings from DB into cache. Call once at startup."""
        if db is None:
            from core.database import Database
            db = Database()
        try:
            self._cache = db.get_all_settings()
            self._loaded = True
            log.info(f"Settings loaded: {len(self._cache)} keys")
        except Exception as exc:
            log.error(f"Settings load failed: {exc}")
            self._cache = {}

    def reload(self, db=None) -> None:
        """Force a fresh load from DB."""
        self._loaded = False
        self.load(db)

    # ── Generic access ────────────────────────────────────────────────────────

    def get(self, key: str, default=None):
        return self._cache.get(key, default)

    def set(self, key: str, value, db=None) -> None:
        self._cache[key] = str(value)
        if db is None:
            from core.database import Database
            db = Database()
        db.set_setting(key, value)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self._cache.get(key, default))
        except (ValueError, TypeError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = self._cache.get(key, str(default)).lower()
        return val in ("1", "true", "yes", "on")

    def get_float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self._cache.get(key, default))
        except (ValueError, TypeError):
            return default

    # ── Named properties ──────────────────────────────────────────────────────

    @property
    def station_name(self) -> str:
        return self.get("station_name", "My Radio Station")

    @property
    def station_slogan(self) -> str:
        return self.get("station_slogan", "")

    @property
    def station_frequency(self) -> str:
        return self.get("station_frequency", "")

    @property
    def master_volume(self) -> int:
        return self.get_int("master_volume", 85)

    @property
    def jingle_volume(self) -> int:
        return self.get_int("jingle_volume", 90)

    @property
    def fade_in_ms(self) -> int:
        return self.get_int("fade_in_ms", 1000)

    @property
    def fade_out_ms(self) -> int:
        return self.get_int("fade_out_ms", 3000)

    @property
    def crossfade_ms(self) -> int:
        return self.get_int("crossfade_ms", 3000)

    @property
    def auto_mode_enabled(self) -> bool:
        return self.get_bool("auto_mode", True)

    @property
    def auto_queue_hours(self) -> int:
        return self.get_int("auto_queue_hours", 2)

    @property
    def same_song_days(self) -> int:
        return self.get_int("same_song_days", 7)

    @property
    def same_slot_days(self) -> int:
        return self.get_int("same_slot_days", 3)

    @property
    def same_artist_hours(self) -> int:
        return self.get_int("same_artist_hours", 2)

    @property
    def ad_limit_per_hour(self) -> int:
        return self.get_int("ad_limit_per_hour", 15)

    @property
    def ai_enabled(self) -> bool:
        return self.get_bool("ai_enabled", True)

    @property
    def ai_model(self) -> str:
        return self.get("ai_model", "claude-sonnet-4-6")

    @property
    def scheduling_mode(self) -> str:
        return self.get("scheduling_auto_mode", "SOHO")

    @property
    def time_format(self) -> str:
        return self.get("time_format", "24h")

    @property
    def audio_engine(self) -> str:
        return self.get("audio_engine", "WASAPI")
