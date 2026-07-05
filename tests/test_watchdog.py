"""
core/watchdog.py — crash watchdog wiring tests.

Pinned behaviour (operator-approved 2026-07-04, after the 01:29 crash
left 8.5h of dead air):
  • Dev runs (sys.frozen falsy) NEVER spawn the watchdog.
  • Frozen runs spawn hidden PowerShell with the bundled script and
    the full parameter set (pid, exe, marker, logs).
  • write_clean_exit_marker stamps a fresh timestamp file.
  • assets/watchdog.ps1 ships in the repo AND is listed in the
    PyInstaller spec (a missing script = watchdog silently dead).
"""

from __future__ import annotations

import os
import subprocess

from core import watchdog


def test_dev_run_never_spawns(monkeypatch):
    spawned = []
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: spawned.append(a))
    monkeypatch.setattr("sys.frozen", False, raising=False)
    assert watchdog.start_watchdog() is False
    assert spawned == []


def test_frozen_run_spawns_with_full_params(monkeypatch, tmp_path):
    import sys
    spawned: list = []

    class _P:
        def __init__(self, cmd, **kw):
            spawned.append((cmd, kw))

    monkeypatch.setattr(subprocess, "Popen", _P)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable",
                        r"C:\Program Files\RadioAI Studio Pro"
                        r"\RadioAI Studio Pro.exe", raising=False)
    # sys.frozen makes resource_path resolve relative to the (fake)
    # exe — pin it to the repo's real assets dir for the test.
    import core.paths as _paths
    from pathlib import Path
    repo_assets = Path(__file__).resolve().parent.parent
    monkeypatch.setattr(
        _paths, "resource_path",
        lambda *parts: repo_assets.joinpath(*parts))

    assert watchdog.start_watchdog() is True
    assert len(spawned) == 1
    cmd, kw = spawned[0]
    joined = " ".join(cmd)
    assert cmd[0] == "powershell"
    assert "-WindowStyle" in cmd and "Hidden" in cmd
    assert "watchdog.ps1" in joined
    assert "-AppPid" in cmd and str(os.getpid()) in cmd
    assert "-ExePath" in cmd and sys.executable in cmd
    assert "-MarkerPath" in cmd and "-RestartLog" in cmd
    assert kw.get("stdin") is subprocess.DEVNULL


def test_clean_exit_marker_written(monkeypatch, tmp_path):
    monkeypatch.setattr(watchdog, "_logs_dir",
                        lambda: str(tmp_path))
    watchdog.write_clean_exit_marker()
    p = tmp_path / watchdog.MARKER_NAME
    assert p.exists()
    assert len(p.read_text().strip()) == 19   # YYYY-mm-dd HH:MM:SS


def test_script_ships_in_repo_and_spec():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "assets", "watchdog.ps1")
    assert os.path.exists(script), "assets/watchdog.ps1 missing"
    body = open(script, encoding="utf-8").read()
    for token in ("AppPid", "MarkerPath", "WaitForExit",
                  "Start-Process", "RestartLog"):
        assert token in body
    spec = open(os.path.join(root, "RadioAIStudioPro.spec"),
                encoding="utf-8").read()
    assert "watchdog.ps1" in spec, "spec must bundle watchdog.ps1"
