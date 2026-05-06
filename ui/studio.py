"""
RadioAI Studio Pro — Studio screen.

Transitional shim — re-exports the legacy Phase D Studio class so
``from ui.studio import Studio`` (used by ``ui.main_window`` + tests)
keeps working between rebuild attempts.

Will be replaced by the rebuilt premium-design screen once the new
Figma design is finalized. ``ui/studio_legacy.py`` stays as the
running Studio in the meantime — fully functional, on-air-tested
Phase D wiring.
"""

from ui.studio_legacy import Studio  # noqa: F401  (re-export)

__all__ = ["Studio"]
