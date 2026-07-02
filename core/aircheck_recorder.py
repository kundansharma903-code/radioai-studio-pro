"""
RadioAI — Aircheck Recorder (hourly broadcast logger)

Records what actually airs — the soundcard's OUTPUT — into one file per
clock hour, the industry-standard compliance "logger" every radio
automation suite ships (Jazler's Audio Logger equivalent).

How it captures audio
---------------------
BASS exposes WASAPI *loopback* recording devices: virtual inputs that
mirror an output device's stream. The recorder SMART-FOLLOWS the playout
device — it asks BASS which playback device the app is actually using
(``BASS_GetDevice``), then picks the recording device with the SAME NAME
and the ``BASS_DEVICE_LOOPBACK`` flag. Whatever airs (songs, spots,
sweeper overlays, jingles, stitcher blocks) is in that stream, already
mixed by Windows — no tap into AudioEngine, no BASSmix, Invariant #1
untouched.

File lifecycle
--------------
``Recordings root`` comes from the ``path_recordings`` setting
(Settings → General → Storage). Month folder → date folder → one file
per clock hour named by the hour (operator's browsing layout):

    <path_recordings>\2026-07\2026-07-02\18-00.wav   (recording)
    <path_recordings>\2026-07\2026-07-02\18-00.mp3   (after encode)

The RECORDPROC callback (BASS recording thread — file I/O ONLY, never
Qt/DB) appends raw PCM to the open WAV. A 1s QTimer on the Qt thread
rotates at the top of each hour: finalize WAV header → background-encode
to MP3 via ffmpeg (WAV deleted on success; kept with a warning if ffmpeg
is missing) → prune date folders older than the retention window.

Settings keys
-------------
    aircheck_enabled          "1"/"0"  master switch (default ON)
    aircheck_device_override  ""       empty = Auto (follow output device)
    aircheck_bitrate          "32"     MP3 kbps (32-192; ≤48 encodes mono)
    aircheck_retention_days   "90"     prune date folders older than this
    path_recordings           recordings root (Settings → General)
"""

from __future__ import annotations

import ctypes
import logging
import shutil
import subprocess
import threading
import wave
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from core.audio import _bass
from core.settings import Settings

log = logging.getLogger("Aircheck")

RECORD_FREQ = 44100
RECORD_CHANS = 2
SAMPLE_BYTES = 2          # 16-bit PCM (BASS default record format)
MONTH_DIR_FMT = "%Y-%m"
DATE_DIR_FMT = "%Y-%m-%d"


# ── Device resolution (pure helpers — unit-testable) ─────────────────────────

def _active_output_device_name() -> str:
    """Name of the playback device BASS is currently initialised on."""
    dll = _bass.get_dll()
    dev = dll.BASS_GetDevice()
    if dev == 0xFFFFFFFF:
        return ""
    info = _bass.BASS_DEVICEINFO()
    if not dll.BASS_GetDeviceInfo(dev, ctypes.byref(info)):
        return ""
    return (info.name or b"").decode(errors="replace")


def enumerate_loopback_devices() -> list[tuple[int, str]]:
    """[(record_device_index, name)] for every enabled LOOPBACK device."""
    dll = _bass.get_dll()
    out: list[tuple[int, str]] = []
    i = 0
    info = _bass.BASS_DEVICEINFO()
    while dll.BASS_RecordGetDeviceInfo(i, ctypes.byref(info)):
        enabled = bool(info.flags & _bass.BASS_DEVICE_ENABLED)
        loopback = bool(info.flags & _bass.BASS_DEVICE_LOOPBACK)
        if enabled and loopback:
            out.append((i, (info.name or b"").decode(errors="replace")))
        i += 1
    return out


def resolve_record_device(playback_name: str,
                          loopbacks: list[tuple[int, str]],
                          override_name: str = "") -> tuple[int, str]:
    """Pick the recording device index. Ladder:
    manual override (exact name) → loopback matching the active playback
    device's name → any loopback → (-1, reason)."""
    if override_name:
        for idx, name in loopbacks:
            if name == override_name:
                return idx, name
    if playback_name:
        for idx, name in loopbacks:
            if name == playback_name:
                return idx, name
    if loopbacks:
        return loopbacks[0]
    return -1, "no loopback recording device found"


def hour_file_stem(now: datetime) -> str:
    """One file per clock hour, named by the hour: '00-00', '10-00',
    '16-00' (Windows filenames can't hold ':'). Month + date context
    comes from the parent folders."""
    return f"{now:%H}-00"


def hour_file_dir(root: Path, now: datetime) -> Path:
    """<root>/<2026-07>/<2026-07-02> — month folder, then date folder."""
    return root / now.strftime(MONTH_DIR_FMT) / now.strftime(DATE_DIR_FMT)


# ── The engine ───────────────────────────────────────────────────────────────

class AircheckRecorder(QObject):
    """Hourly aircheck logger. Owned by MainWindow (8th engine).

    Threading: the RECORDPROC fires on BASS's recording thread and only
    appends bytes to an open file handle guarded by ``_file_lock``. All
    Qt work (timer, rotation, signals) stays on the Qt thread.
    """

    # (recording: bool, detail: device name when on / reason when off)
    state_changed = pyqtSignal(bool, str)
    error_occurred = pyqtSignal(str)
    file_rotated = pyqtSignal(str)     # finalized file path (post-encode)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._hrecord: int = 0
        self._record_device: int = -1
        self._device_name: str = ""
        self._wav: Optional[wave.Wave_write] = None
        self._wav_path: Optional[Path] = None
        self._file_lock = threading.Lock()
        self._bytes_written = 0
        self._ffmpeg = shutil.which("ffmpeg") or ""
        self._ffmpeg_warned = False
        # Keep a hard ref to the ctypes callback — GC'ing it while BASS
        # still calls into it is an instant access violation.
        self._proc = _bass.RECORDPROC(self._on_record_data)

        self._rotate_timer = QTimer(self)
        self._rotate_timer.setInterval(1000)
        self._rotate_timer.timeout.connect(self._tick)
        self._current_hour_key = ""

    # ── Public API ────────────────────────────────────────────────────

    @property
    def is_recording(self) -> bool:
        return self._hrecord != 0

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def current_file(self) -> str:
        return str(self._wav_path) if self._wav_path else ""

    def recordings_root(self) -> Path:
        raw = (Settings().get("path_recordings", "") or "").strip()
        if not raw:
            from core.paths import APP_DATA_ROOT
            return APP_DATA_ROOT / "Recordings"
        return Path(raw)

    def start(self) -> bool:
        """Init the loopback device and begin the current hour's file.
        Safe to call repeatedly (no-op while already recording)."""
        if self._hrecord:
            return True
        if not Settings().get_bool("aircheck_enabled", True):
            self.state_changed.emit(False, "aircheck disabled in settings")
            return False
        try:
            dll = _bass.get_dll()
            override = Settings().get("aircheck_device_override", "") or ""
            playback = _active_output_device_name()
            dev, name = resolve_record_device(
                playback, enumerate_loopback_devices(), override)
            if dev < 0:
                self._fail(f"aircheck: {name}")
                return False

            if not dll.BASS_RecordInit(dev):
                err = _bass.error_code()
                if err != 8:            # BASS_ERROR_ALREADY — device is up
                    self._fail(f"aircheck: BASS_RecordInit failed "
                               f"(device={dev} err={err})")
                    return False
            dll.BASS_RecordSetDevice(dev)

            if not self._open_hour_file(datetime.now()):
                return False

            h = dll.BASS_RecordStart(
                RECORD_FREQ, RECORD_CHANS, 0, self._proc, None)
            if not h:
                self._close_wav()
                self._fail(f"aircheck: BASS_RecordStart failed "
                           f"(err={_bass.error_code()})")
                return False

            self._hrecord = h
            self._record_device = dev
            self._device_name = name
            self._current_hour_key = datetime.now().strftime("%Y%m%d%H")
            self._rotate_timer.start()
            log.info(f"[aircheck] recording ON — device[{dev}] '{name}' "
                     f"→ {self._wav_path}")
            self.state_changed.emit(True, name)
            self._prune_old_recordings()
            return True
        except Exception as exc:                      # broadcast safety
            log.error(f"[aircheck] start failed: {exc}", exc_info=True)
            self._fail(f"aircheck: {exc}")
            return False

    def stop(self) -> None:
        """Stop recording and finalize + encode the open file."""
        self._rotate_timer.stop()
        if self._hrecord:
            try:
                _bass.get_dll().BASS_ChannelStop(self._hrecord)
            except Exception as exc:
                log.warning(f"[aircheck] ChannelStop failed: {exc}")
            self._hrecord = 0
        done = self._close_wav()
        if done:
            self._encode_async(done)
        try:
            _bass.get_dll().BASS_RecordFree()
        except Exception as exc:
            log.warning(f"[aircheck] RecordFree failed: {exc}")
        self._record_device = -1
        if self._device_name:
            log.info("[aircheck] recording OFF")
        self._device_name = ""
        self.state_changed.emit(False, "stopped")

    def restart(self) -> None:
        """Settings changed (device override / enable toggle) — re-resolve."""
        self.stop()
        self.start()

    # ── RECORDPROC — BASS recording thread. File I/O only. ───────────

    def _on_record_data(self, _handle, buffer, length, _user) -> bool:
        try:
            if length and buffer:
                data = ctypes.string_at(buffer, length)
                with self._file_lock:
                    if self._wav is not None:
                        self._wav.writeframesraw(data)
                        self._bytes_written += length
        except Exception:
            # Swallow everything — an exception escaping into BASS's C
            # thread would take the whole process down.
            pass
        return True

    # ── Hour rotation (Qt thread) ─────────────────────────────────────

    def _tick(self) -> None:
        try:
            key = datetime.now().strftime("%Y%m%d%H")
            if key != self._current_hour_key and self._hrecord:
                self._current_hour_key = key
                self._rotate()
        except Exception as exc:
            log.error(f"[aircheck] tick failed: {exc}", exc_info=True)

    def _rotate(self) -> None:
        """Top of the hour: seal the finished file, open the next one."""
        now = datetime.now()
        # Follow the output device across restarts of the audio setup:
        # if the active playback device no longer matches, re-resolve.
        playback = _active_output_device_name()
        override = Settings().get("aircheck_device_override", "") or ""
        if not override and playback and playback != self._device_name:
            log.info(f"[aircheck] output device changed "
                     f"('{self._device_name}' → '{playback}') — re-following")
            self.restart()
            return
        done = None
        with self._file_lock:
            done = self._close_wav_locked()
            self._open_hour_file_locked(now)
        log.info(f"[aircheck] rotated → {self._wav_path}")
        if done:
            self._encode_async(done)
        self._prune_old_recordings()

    # ── WAV file management ───────────────────────────────────────────

    def _open_hour_file(self, now: datetime) -> bool:
        with self._file_lock:
            return self._open_hour_file_locked(now)

    def _open_hour_file_locked(self, now: datetime) -> bool:
        try:
            folder = hour_file_dir(self.recordings_root(), now)
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{hour_file_stem(now)}.wav"
            w = wave.open(str(path), "wb")
            w.setnchannels(RECORD_CHANS)
            w.setsampwidth(SAMPLE_BYTES)
            w.setframerate(RECORD_FREQ)
            self._wav = w
            self._wav_path = path
            self._bytes_written = 0
            return True
        except Exception as exc:
            self._wav = None
            self._wav_path = None
            log.error(f"[aircheck] cannot open recording file: {exc}")
            self._fail(f"aircheck: cannot write to recordings folder "
                       f"({exc})")
            return False

    def _close_wav(self) -> Optional[Path]:
        with self._file_lock:
            return self._close_wav_locked()

    def _close_wav_locked(self) -> Optional[Path]:
        if self._wav is None:
            return None
        path = self._wav_path
        try:
            self._wav.close()          # rewrites the header with real size
        except Exception as exc:
            log.warning(f"[aircheck] WAV close failed: {exc}")
        self._wav = None
        self._wav_path = None
        # Drop empty files (recording never delivered data)
        try:
            if path and path.exists() and path.stat().st_size <= 44:
                path.unlink()
                return None
        except Exception:
            pass
        return path

    # ── MP3 encode (background thread, fire-and-forget) ──────────────

    def _encode_async(self, wav_path: Path) -> None:
        if not self._ffmpeg:
            if not self._ffmpeg_warned:
                self._ffmpeg_warned = True
                log.warning("[aircheck] ffmpeg not found — keeping WAV "
                            "files (≈635 MB/hour). Install ffmpeg for MP3.")
            return
        bitrate = Settings().get_int("aircheck_bitrate", 32)
        t = threading.Thread(
            target=self._encode_worker, args=(wav_path, bitrate),
            name="aircheck-encode", daemon=True)
        t.start()

    def _encode_worker(self, wav_path: Path, bitrate: int) -> None:
        mp3_path = wav_path.with_suffix(".mp3")
        # ≤48 kbps encodes MONO — low-rate stereo MP3 is mud, mono at
        # the same size stays clean (the compliance-logger norm).
        chan_args = ["-ac", "1"] if bitrate <= 48 else []
        try:
            res = subprocess.run(
                [self._ffmpeg, "-y", "-loglevel", "error",
                 "-i", str(wav_path),
                 "-codec:a", "libmp3lame", "-b:a", f"{bitrate}k",
                 *chan_args,
                 str(mp3_path)],
                capture_output=True, timeout=600,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if res.returncode == 0 and mp3_path.exists():
                wav_path.unlink(missing_ok=True)
                log.info(f"[aircheck] encoded {mp3_path.name} "
                         f"({bitrate} kbps)")
                self.file_rotated.emit(str(mp3_path))
            else:
                log.warning(f"[aircheck] ffmpeg encode failed "
                            f"(rc={res.returncode}) — WAV kept: "
                            f"{res.stderr.decode(errors='replace')[:200]}")
                self.file_rotated.emit(str(wav_path))
        except Exception as exc:
            log.warning(f"[aircheck] encode error — WAV kept: {exc}")

    # ── Retention cleanup ─────────────────────────────────────────────

    def _prune_old_recordings(self) -> None:
        """Delete date folders older than aircheck_retention_days.
        Layout: <root>/<YYYY-MM>/<YYYY-MM-DD>/. Emptied month folders
        are removed too. Legacy flat date folders at the root (the
        pre-month layout) are pruned the same way. Anything that isn't
        one of our date/month names is never touched."""
        try:
            days = Settings().get_int("aircheck_retention_days", 90)
            if days <= 0:
                return
            root = self.recordings_root()
            if not root.exists():
                return
            cutoff = datetime.now().date() - timedelta(days=days)

            def _parse(name: str, fmt: str):
                try:
                    return datetime.strptime(name, fmt).date()
                except ValueError:
                    return None

            def _prune_date_dir(entry: Path) -> None:
                d = _parse(entry.name, DATE_DIR_FMT)
                if d is not None and d < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
                    log.info(f"[aircheck] pruned old recordings: "
                             f"{entry.name}")

            for entry in root.iterdir():
                if not entry.is_dir():
                    continue
                if _parse(entry.name, DATE_DIR_FMT) is not None:
                    _prune_date_dir(entry)          # legacy flat layout
                elif _parse(entry.name + "-01", DATE_DIR_FMT) is not None:
                    # month folder (YYYY-MM) — walk its date folders
                    for sub in entry.iterdir():
                        if sub.is_dir():
                            _prune_date_dir(sub)
                    try:
                        next(entry.iterdir())
                    except StopIteration:
                        entry.rmdir()               # month emptied out
                        log.info(f"[aircheck] pruned empty month: "
                                 f"{entry.name}")
        except Exception as exc:
            log.warning(f"[aircheck] prune failed: {exc}")

    # ── Failure path ──────────────────────────────────────────────────

    def _fail(self, msg: str) -> None:
        log.error(f"[aircheck] {msg}")
        self.error_occurred.emit(msg)
        self.state_changed.emit(False, msg)
