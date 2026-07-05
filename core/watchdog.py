"""
RadioAI — crash watchdog (operator-approved 2026-07-04).

Why: the 2026-07-04 01:29 on-air crash left the station silent for
8.5 hours. A broadcast box must self-heal: if the app DIES, it should
be back on air in ~30 seconds.

Design — "zero harm to the original ecosystem":
- The app SPAWNS its own watchdog at boot (a hidden PowerShell child,
  assets/watchdog.ps1). No scheduled task, no registry, no service —
  nothing persists when the app isn't running, and uninstall leaves
  no trace.
- The watchdog simply waits for the app process to exit, then reads
  the CLEAN-EXIT MARKER:
    · marker fresh (written < 120s ago)  → operator/installer closed
      the app on purpose → watchdog exits silently. Closing the app
      works exactly like before.
    · marker stale/absent               → CRASH → wait ~10s, relaunch
      the same exe, log to Logs/watchdog.log. The new instance spawns
      its own new watchdog.
- Crash-loop guard lives in the .ps1: 3 restarts inside 10 minutes →
  give up and log (a broken build must not flap forever).
- DEV runs (py main.py) never spawn the watchdog — only the frozen
  exe does. Killing a dev session stays consequence-free.
- The single-instance guard makes double-launches harmless anyway.

The clean-exit marker is also written by the single-instance early
exit and any normal main() return — every intentional path.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

log = logging.getLogger("Watchdog")

MARKER_NAME = "clean_exit.marker"


def _logs_dir() -> str:
    from core.constants import LOG_PATH
    os.makedirs(LOG_PATH, exist_ok=True)
    return LOG_PATH


def marker_path() -> str:
    return os.path.join(_logs_dir(), MARKER_NAME)


def write_clean_exit_marker() -> None:
    """Stamp 'this shutdown was intentional'. Called on every clean
    exit path BEFORE the process ends."""
    try:
        with open(marker_path(), "w", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\n")
    except Exception as exc:
        log.warning(f"[watchdog] clean-exit marker write failed: {exc}")


def build_watchdog_command(app_pid: int, exe_path: str) -> list:
    """The PowerShell invocation — pure function so tests can pin it
    without spawning anything."""
    from core.paths import resource_path
    script = str(resource_path("assets", "watchdog.ps1"))
    logs = _logs_dir()
    return [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-WindowStyle", "Hidden", "-File", script,
        "-AppPid", str(int(app_pid)),
        "-ExePath", exe_path,
        "-MarkerPath", marker_path(),
        "-LogPath", os.path.join(logs, "watchdog.log"),
        "-RestartLog", os.path.join(logs, "watchdog_restarts.log"),
    ]


def start_watchdog() -> bool:
    """Spawn the watchdog for THIS process. Frozen-exe only — dev
    sessions (py main.py) must stay freely killable. Returns True when
    the watchdog child started."""
    if not getattr(sys, "frozen", False):
        log.debug("[watchdog] dev run — watchdog not spawned")
        return False
    try:
        cmd = build_watchdog_command(os.getpid(), sys.executable)
        if not os.path.exists(cmd[7]):        # the -File script path
            log.warning("[watchdog] watchdog.ps1 not bundled — skipped")
            return False
        # Console stays hidden two ways: -WindowStyle Hidden AND the
        # process-wide CREATE_NO_WINDOW patch (core/win_console.py).
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        log.info(f"[watchdog] armed (pid={os.getpid()}) — crash "
                 f"recovery ~30s, clean exits untouched")
        return True
    except Exception as exc:
        log.warning(f"[watchdog] spawn failed: {exc}")
        return False
