# BASSmix DLL — Setup Instructions

This folder is where `bassmix.dll` lives for the Phase 5 BASSmix
mixer-architecture migration.

## Why a Separate DLL

`pybass3` only bundles the core `bass.dll` and `tags.dll`. The mixer
addon (`bassmix.dll`) is shipped separately by un4seen.com and is
**not included** by default.

Until `bassmix.dll` is dropped into this folder, the application runs
on the **legacy direct-play architecture** — every audio engine
(AudioEngine, SweeperEngine, StitcherEngine, InstantJingleEngine)
creates BASS streams that play directly to the output device, and
BASS auto-mixes them at the device level. No breakage.

When `bassmix.dll` is present, the migration steps gradually shift
each engine to route through a unified mixer stream, unlocking:

- Multi-soundcard routing (e.g., music → broadcast output, mic → headphones)
- Sample-accurate cross-engine timing
- Master volume bus + ducking hooks
- Broadcast recording (tap on the mixer)

## How to Install

### Option A — automatic (when networked)

Run:
```
py scripts\fetch_bassmix.py
```
(coming in Step 5.0.1 — not yet)

### Option B — manual (recommended for now)

1. Visit https://www.un4seen.com/bass.html
2. Scroll to "BASSmix" — click the "BASSmix" download (latest is
   typically `bassmix24.zip`)
3. Extract the zip
4. Copy `bassmix.dll` (NOT `bassmix.lib` or others) into
   **this folder**: `core/audio/vendor/bassmix.dll`

That's it. Next app launch will pick it up automatically.

### Verification

```
py -c "from core.audio._bassmix import is_available; print('mixer available:', is_available())"
```

Expected when missing:
```
mixer available: False
```
Plus a log line:
```
INFO bassmix: bassmix.dll not found — mixer architecture is disabled.
```

Expected when installed:
```
mixer available: True
```
Plus:
```
INFO bassmix: bassmix.dll loaded from .../core/audio/vendor/bassmix.dll
```

## License

BASS / BASSmix is free for non-commercial use. Commercial use (any
on-air broadcasting, including a live radio station) requires a
license from un4seen.com.

This project already needs a BASS commercial license for production
(see top of `core/audio_engine.py`); the BASSmix addon uses the same
licensing model. No additional cost for development.

See:
- BASS license — https://www.un4seen.com/bass.html#license
- BASSmix license — same page, "BASSmix" section
